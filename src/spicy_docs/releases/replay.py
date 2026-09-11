"""Reconstruct observations independently from retained evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from rulespec_artifacts import (
    BlobSource,
    MemberDescriptor,
    MemberSource,
    canonical_json_bytes,
)

from spicy_docs.releases.format import (
    _PAGE_SHAPE,
    MAX_EVIDENCE_BYTES,
    SourceNativeReleaseError,
)
from spicy_docs.releases.observations import (
    _accepted_traversal,
    _observation_version,
    _select_observations,
)
from spicy_docs.releases.partitions import (
    _open_descriptor,
    _partition_rows,
    _PayloadPartition,
)
from spicy_docs.releases.profile import (
    AcquisitionCheck,
    SourceNativeProfile,
    TraversalCheck,
)


def _replay_acquisition(
    connection: sqlite3.Connection,
    *,
    source: MemberSource,
    blob_source: BlobSource | None,
    evidence_members: Mapping[str, MemberDescriptor],
    page_partitions: Sequence[_PayloadPartition],
    query_scope: Mapping[str, Any],
    profile: SourceNativeProfile,
) -> tuple[int, int]:
    """Replay sorted page/evidence streams with only one active window in memory."""

    connection.executescript(
        "CREATE TABLE pages (traversal INTEGER, page INTEGER, window_index INTEGER, window_page INTEGER, "
        "records_included INTEGER, accepted INTEGER, request_key TEXT, source_cursor TEXT, next_cursor TEXT, "
        "evidence_ref TEXT, payload BLOB, PRIMARY KEY (traversal, page), "
        "UNIQUE (traversal, window_index, window_page));"
        "CREATE TABLE observations (traversal INTEGER, ordinal INTEGER, source_record_id TEXT, "
        "source_version TEXT, selected INTEGER NOT NULL DEFAULT 0, record_digest TEXT, "
        "record_payload BLOB, evidence_ref TEXT, PRIMARY KEY (traversal, ordinal));"
    )
    pages = _partition_rows(source, blob_source, page_partitions)
    seen_evidence: set[str] = set()
    previous_traversal = -1
    previous_page = -1
    previous_window = -1
    previous_window_page = -1
    previous_next: str | None = None
    current_window: object | None = None
    current_inventory: TraversalCheck | None = None
    current_seen_urls: set[str] = set()
    current_check: AcquisitionCheck | None = None
    ordinal = 0
    saw_page = False
    for raw_page_row in pages:
        page_row = _PAGE_SHAPE.parse(raw_page_row)
        traversal = page_row.get("traversalIndex")
        page_index = page_row.get("pageIndex")
        window_index = page_row.get("windowIndex")
        window_page_index = page_row.get("windowPageIndex")
        declared_records_included = page_row.get("recordsIncluded")
        accepted_flag = page_row.get("accepted")
        assert isinstance(traversal, int)
        assert isinstance(page_index, int)
        assert isinstance(window_index, int)
        assert isinstance(window_page_index, int)
        assert isinstance(declared_records_included, bool)
        assert isinstance(accepted_flag, bool)
        starts_traversal = traversal != previous_traversal
        starts_window = window_page_index == 0
        if starts_traversal:
            if current_check is not None:
                current_check.finish(query_scope=query_scope)
            if (
                traversal != previous_traversal + 1
                or page_index != 0
                or window_index != 0
                or not starts_window
                or previous_next is not None
            ):
                raise SourceNativeReleaseError("acquisition traversal indexes are missing or forked")
            current_check = profile.acquisition_check()
            previous_page = -1
            previous_window = -1
            previous_window_page = -1
            ordinal = 0
        elif page_index != previous_page + 1:
            raise SourceNativeReleaseError("acquisition page indexes are not contiguous")
        source_cursor = page_row.get("sourceCursor")
        request_key = page_row.get("requestKey")
        if (
            source_cursor is not None
            and (not isinstance(source_cursor, str) or not source_cursor)
            or not isinstance(request_key, str)
            or not request_key
        ):
            raise SourceNativeReleaseError("acquisition page cursor or request key is invalid")
        if starts_window:
            if source_cursor is not None or previous_next is not None or window_index != previous_window + 1:
                raise SourceNativeReleaseError("acquisition window indexes are missing or forked")
            if profile.page_window is None:
                if window_index != 0:
                    raise SourceNativeReleaseError(f"{profile.name} acquisition declares an unsupported nested window")
                current_window = None
            else:
                current_window = profile.page_window(request_key)
            current_inventory = profile.traversal_check()
            current_seen_urls = {request_key}
        elif (
            window_index != previous_window
            or window_page_index != previous_window_page + 1
            or source_cursor != previous_next
            or request_key != source_cursor
        ):
            raise SourceNativeReleaseError("acquisition continuation request differs from its cursor chain")
        evidence_ref = page_row.get("evidenceBlobRef")
        evidence_media_type = page_row.get("evidenceMediaType")
        member = evidence_members.get(evidence_ref) if isinstance(evidence_ref, str) else None
        if (
            member is None
            or member.blob_ref != evidence_ref
            or evidence_ref != page_row.get("responseDigest")
            or member.media_type != evidence_media_type
        ):
            raise SourceNativeReleaseError("acquisition page evidence pin differs")
        assert isinstance(evidence_ref, str)
        seen_evidence.add(evidence_ref)
        with _open_descriptor(source, blob_source, member) as stream:
            response_bytes = stream.read(MAX_EVIDENCE_BYTES + 1)
        if len(response_bytes) > MAX_EVIDENCE_BYTES:
            raise SourceNativeReleaseError("acquisition evidence exceeds its product bound")
        response = profile.parse_page_response(response_bytes)
        records_included = profile.records_included(
            response,
            query_scope=query_scope,
            page_window=current_window,
        )
        if records_included is not declared_records_included:
            raise SourceNativeReleaseError("acquisition page disposition differs from source evidence")
        if starts_window:
            assert current_check is not None
            current_check.add_window(
                response,
                page_window=current_window,
                records_included=records_included,
                response_bytes=response_bytes,
            )
        elif not records_included:
            raise SourceNativeReleaseError(f"{profile.name} non-record evidence cannot continue a page chain")
        if current_inventory is None:
            raise SourceNativeReleaseError("acquisition window begins without an explicit boundary")
        if records_included:
            current_inventory.add(response, page_index=window_page_index)
            next_cursor = profile.next_page(response, seen_urls=current_seen_urls)
        else:
            next_cursor = None
        terminal = next_cursor is None
        if records_included and terminal:
            current_inventory.finish()
        if page_row.get("terminal") is not terminal:
            raise SourceNativeReleaseError("acquisition terminal marker differs from source evidence")
        discovered = page_row.get("discoveredRecords")
        if not isinstance(discovered, list):
            raise SourceNativeReleaseError("acquisition page discoveredRecords is not an array")
        expected_discovered = []
        for raw in response["results"] if records_included else ():
            try:
                classified = profile.classify_record(raw)
                profile.validate_record_scope(
                    classified,
                    query_scope=query_scope,
                    page_window=current_window,
                )
            except ValueError:
                # Reproduces the writer's own outcome on this same evidence
                # (_index_pages skips this record for the identical reason,
                # deterministically, given the same bytes) rather than
                # aborting the whole build-gate replay. The ledger walk in
                # verify_source_native_release proves the admitted failure
                # rows well-formed and reconciles their per-class counts; it
                # does not ask this replay to reconstruct them, so nothing
                # further is recorded here -- the record is simply absent
                # from both expected_discovered and the replayed
                # observations table, exactly as it is absent from the
                # writer's.
                continue
            wrapped = profile.wrap_record(
                classified,
                schema_digest=profile.source_schema_digest(),
            )
            identity = wrapped.get("sourceRecordId")
            if not isinstance(identity, str) or not identity:
                raise SourceNativeReleaseError(f"{profile.name} wrapped record lacks sourceRecordId")
            digest = profile.record_digest(classified)
            expected_discovered.append({"recordDigest": digest, "sourceRecordId": identity})
            try:
                connection.execute(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                    (
                        traversal,
                        ordinal,
                        identity,
                        _observation_version(profile, classified),
                        digest,
                        canonical_json_bytes(wrapped),
                        evidence_ref,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise SourceNativeReleaseError(f"accepted acquisition repeats observation ordinal {ordinal}") from error
            ordinal += 1
        if discovered != expected_discovered:
            raise SourceNativeReleaseError("acquisition page record inventory differs")
        connection.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                traversal,
                page_index,
                window_index,
                window_page_index,
                int(records_included),
                int(accepted_flag),
                request_key,
                source_cursor,
                next_cursor,
                evidence_ref,
                canonical_json_bytes(page_row),
            ),
        )
        saw_page = True
        previous_traversal = traversal
        previous_page = page_index
        previous_window = window_index
        previous_window_page = window_page_index
        previous_next = next_cursor if isinstance(next_cursor, str) else None
    if not saw_page or current_check is None:
        raise SourceNativeReleaseError("acquisition has no evidence pages")
    if seen_evidence != set(evidence_members):
        raise SourceNativeReleaseError("acquisition pages do not account for exact evidence membership")
    current_check.finish(query_scope=query_scope)
    if previous_next is not None:
        raise SourceNativeReleaseError("acquisition traversal has no terminal page")
    traversal_count = previous_traversal + 1
    if traversal_count > profile.max_traversals:
        raise SourceNativeReleaseError("acquisition traversal count exceeds its bound")
    _select_observations(connection, profile=profile)
    accepted = _accepted_traversal(
        connection,
        traversal_count=traversal_count,
        profile=profile,
    )
    wrong_flag = connection.execute(
        "SELECT 1 FROM pages WHERE accepted != (traversal = ?) LIMIT 1",
        (accepted,),
    ).fetchone()
    if wrong_flag is not None:
        raise SourceNativeReleaseError("acquisition accepted-traversal flags differ")
    connection.commit()
    return accepted, traversal_count
