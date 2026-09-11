"""Index acquisition pages and classified observations for publication."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from rulespec_artifacts import (
    MemberDescriptor,
    canonical_json_bytes,
    describe_member_from_receipt,
)

from spicy_docs.releases.format import (
    FAILURE_CLASS_DETERMINISTIC,
    MAX_EVIDENCE_BYTES,
    REASON_RECORD_UNCLASSIFIABLE,
    ROLE_EVIDENCE,
    SourceNativeReleaseError,
)
from spicy_docs.releases.observations import (
    _observation_version,
    _ordered_rendition_rows,
    _select_observations,
    _unclassified_source_record_id,
    _validate_evidence_media_type,
)
from spicy_docs.releases.partitions import (
    _ByteAccounting,
    _partition_id,
)
from spicy_docs.source_native_profile import (
    AcquisitionCheck,
    SourceNativePage,
    SourceNativeProfile,
)
from spicy_docs.source_native_store import SourceNativeBlobStore


def index_pages(
    connection: sqlite3.Connection,
    pages: Iterable[SourceNativePage],
    *,
    blob_store: SourceNativeBlobStore,
    accounting: _ByteAccounting,
    evidence_members: dict[str, MemberDescriptor],
    query_scope: Mapping[str, Any],
    profile: SourceNativeProfile,
) -> None:
    connection.executescript(
        "CREATE TABLE pages (traversal INTEGER, page INTEGER, window_index INTEGER, window_page INTEGER, "
        "records_included INTEGER, request_key TEXT, source_cursor TEXT, next_cursor TEXT, "
        "evidence_ref TEXT, evidence_media_type TEXT, partition_id TEXT, "
        "PRIMARY KEY (traversal, page), UNIQUE (traversal, window_index, window_page));"
        "CREATE TABLE observations (traversal INTEGER, page INTEGER, ordinal INTEGER, source_record_id TEXT, "
        "source_version TEXT, selected INTEGER NOT NULL DEFAULT 0, record_digest TEXT, "
        "record_payload BLOB, rendition_payload BLOB, evidence_ref TEXT, partition_id TEXT, "
        "PRIMARY KEY (traversal, ordinal));"
        "CREATE TABLE failures (traversal INTEGER, page INTEGER, record_index INTEGER, "
        "source_record_id TEXT, failure_class TEXT, reason_code TEXT, evidence_ref TEXT, "
        "partition_id TEXT, PRIMARY KEY (traversal, page, record_index));"
    )
    previous: SourceNativePage | None = None
    previous_next: str | None = None
    inventory = None
    seen_urls: set[str] = set()
    current_window: object | None = None
    acquisition_checks: dict[int, AcquisitionCheck] = {}
    ordinal = 0
    saw_page = False
    for page in pages:
        saw_page = True
        if len(page.response_bytes) > MAX_EVIDENCE_BYTES:
            raise SourceNativeReleaseError(f"{profile.name} page exceeds the evidence bound")
        if page.traversal_index >= profile.max_traversals:
            raise SourceNativeReleaseError(f"{profile.name} acquisition exceeds its traversal bound")
        starts_window = page.window_page_index == 0
        _validate_page_chain(page, previous, previous_next, profile)
        if previous is not None and page.traversal_index != previous.traversal_index:
            ordinal = 0
        if starts_window:
            inventory = profile.traversal_check()
            seen_urls = {page.request_key}
            if profile.page_window is None:
                if page.window_index != 0:
                    raise SourceNativeReleaseError(f"{profile.name} acquisition declares an unsupported nested window")
                current_window = None
            else:
                current_window = profile.page_window(page.request_key)
        response = profile.parse_page_response(page.response_bytes)
        records_included = profile.records_included(
            response,
            query_scope=query_scope,
            page_window=current_window,
        )
        if not isinstance(records_included, bool):
            raise SourceNativeReleaseError(f"{profile.name} page disposition is not boolean")
        if starts_window:
            check = acquisition_checks.setdefault(
                page.traversal_index,
                profile.acquisition_check(),
            )
            check.add_window(
                response,
                page_window=current_window,
                records_included=records_included,
                response_bytes=page.response_bytes,
            )
        elif not records_included:
            raise SourceNativeReleaseError(f"{profile.name} non-record evidence cannot continue a page chain")
        if records_included:
            if inventory is None:
                raise RuntimeError(f"{profile.name} page inventory was not initialized")
            inventory.add(response, page_index=page.window_page_index)
            next_cursor = profile.next_page(response, seen_urls=seen_urls)
        else:
            next_cursor = None
        _validate_evidence_media_type(page)
        evidence_ref = "sha256:" + hashlib.sha256(page.response_bytes).hexdigest()
        evidence_descriptor = evidence_members.get(evidence_ref)
        if evidence_descriptor is None:
            write = blob_store.put_blob(
                evidence_ref,
                len(page.response_bytes),
                (page.response_bytes,),
            )
            accounting.add(
                byte_size=len(page.response_bytes),
                reused=write.reused,
                bytes_written=write.bytes_written,
            )
            evidence_descriptor = describe_member_from_receipt(
                blob_ref=evidence_ref,
                role=ROLE_EVIDENCE,
                media_type=page.evidence_media_type,
                byte_size=len(page.response_bytes),
                record_count=0,
            )
            evidence_members[evidence_ref] = evidence_descriptor
        elif (
            evidence_descriptor.byte_size != len(page.response_bytes)
            or evidence_descriptor.media_type != page.evidence_media_type
        ):
            raise SourceNativeReleaseError("source-native evidence content has conflicting declarations")
        connection.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page.traversal_index,
                page.page_index,
                page.window_index,
                page.window_page_index,
                int(records_included),
                page.request_key,
                page.source_cursor,
                next_cursor,
                evidence_ref,
                page.evidence_media_type,
                _partition_id(f"{page.traversal_index}:{page.page_index}"),
            ),
        )
        for record_index, raw_record in enumerate(response["results"] if records_included else ()):
            try:
                record = profile.classify_record(raw_record)
                profile.validate_record_scope(
                    record,
                    query_scope=query_scope,
                    page_window=current_window,
                )
            except ValueError:
                # This record fails to classify or falls outside its
                # declared scope. The identical bytes reparse identically,
                # so the failure is deterministic by the ruled boundary
                # ("would the identical unchanged request plausibly
                # succeed?") -- no judgment is coded here, only that one
                # fixed answer. The page's own evidence blob already
                # holds this record's bytes (evidence_ref, above), so
                # nothing new needs writing to keep "the object" in
                # evidence; only a ledger row naming the failure does.
                failure_source_record_id = _unclassified_source_record_id(
                    page.traversal_index, page.page_index, record_index
                )
                connection.execute(
                    "INSERT INTO failures VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        page.traversal_index,
                        page.page_index,
                        record_index,
                        failure_source_record_id,
                        FAILURE_CLASS_DETERMINISTIC,
                        REASON_RECORD_UNCLASSIFIABLE,
                        evidence_ref,
                        _partition_id(failure_source_record_id),
                    ),
                )
                continue
            wrapped = profile.wrap_record(
                record,
                schema_digest=profile.source_schema_digest(),
            )
            renditions = _ordered_rendition_rows(profile, record)
            source_record_id = wrapped.get("sourceRecordId")
            if not isinstance(source_record_id, str) or not source_record_id:
                raise SourceNativeReleaseError(f"{profile.name} wrapped record lacks sourceRecordId")
            try:
                connection.execute(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                    (
                        page.traversal_index,
                        page.page_index,
                        ordinal,
                        source_record_id,
                        _observation_version(profile, record),
                        profile.record_digest(record),
                        canonical_json_bytes(wrapped),
                        canonical_json_bytes(renditions),
                        evidence_ref,
                        _partition_id(source_record_id),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise SourceNativeReleaseError(f"{profile.name} observation index repeats ordinal {ordinal}") from error
            ordinal += 1
        previous = page
        previous_next = next_cursor if isinstance(next_cursor, str) else None
        if records_included and previous_next is None:
            if inventory is None:
                raise RuntimeError(f"{profile.name} page inventory was not initialized")
            inventory.finish()
    if not saw_page:
        raise SourceNativeReleaseError(f"{profile.name} acquisition has no evidence pages")
    if previous_next is not None:
        raise SourceNativeReleaseError(f"{profile.name} acquisition has no terminal page")
    for traversal in sorted(acquisition_checks):
        acquisition_checks[traversal].finish(query_scope=query_scope)
    _select_observations(connection, profile=profile)
    connection.commit()


def _validate_page_chain(
    page: SourceNativePage,
    previous: SourceNativePage | None,
    previous_next: str | None,
    profile: SourceNativeProfile,
) -> None:
    """Require contiguous traversal, window, and page transitions before indexing."""
    starts_window = page.window_page_index == 0
    if previous is None:
        if page.traversal_index != 0 or page.page_index != 0 or page.window_index != 0 or not starts_window:
            raise SourceNativeReleaseError(f"{profile.name} acquisition must start at traversal 0 page 0")
    elif page.traversal_index == previous.traversal_index:
        if page.page_index != previous.page_index + 1:
            raise SourceNativeReleaseError(f"{profile.name} page indexes are not contiguous")
        if starts_window:
            if previous_next is not None or page.window_index != previous.window_index + 1:
                raise SourceNativeReleaseError(f"{profile.name} window chain is missing or forked")
        elif (
            page.window_index != previous.window_index
            or page.window_page_index != previous.window_page_index + 1
            or page.source_cursor != previous_next
            or page.request_key != page.source_cursor
        ):
            raise SourceNativeReleaseError(f"{profile.name} page chain is missing or forked")
    else:
        if previous_next is not None:
            raise SourceNativeReleaseError(f"{profile.name} traversal ended before its terminal page")
        if (
            page.traversal_index != previous.traversal_index + 1
            or page.page_index != 0
            or page.window_index != 0
            or not starts_window
        ):
            raise SourceNativeReleaseError(f"{profile.name} traversal indexes are not contiguous")
