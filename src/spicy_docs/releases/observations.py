"""Disk-backed observation selection and ordered release rows."""

from __future__ import annotations

import heapq
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from rulespec_artifacts import (
    FramedSection,
    framed_section_digest,
    parse_canonical_json,
)

from spicy_docs.releases.format import (
    _PAGE_SHAPE,
    _UNCLASSIFIED_RECORD_ID_PREFIX,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
)
from spicy_docs.releases.profile import (
    SourceNativePage,
    SourceNativeProfile,
)


def _policy_for_scope(
    query_scope: Mapping[str, Any],
    profile: SourceNativeProfile,
) -> dict[str, Any]:
    policy = profile.acquisition_policy(query_scope)
    if not isinstance(policy, Mapping):
        raise SourceNativeReleaseError(f"{profile.name} acquisition policy builder did not return an object")
    return dict(policy)


def _policy_digest(build: SourceNativeReleaseBuild, profile: SourceNativeProfile) -> str:
    return _section_digest(
        "spicyregs-acquisition-policy/1",
        "policy",
        1,
        (_policy_for_scope(build.query_scope, profile),),
    )


def _section_digest(domain: str, section: str, count: int, values: Iterable[Mapping[str, Any]]) -> str:
    """Hash ordered rows through Rulespec with their declared count, without buffering."""
    return framed_section_digest(domain, (FramedSection(section, count, values),))


def _source_state_digest(
    scopes: tuple[int, Iterable[Mapping[str, Any]]],
    schemas: tuple[int, Iterable[Mapping[str, Any]]],
    records: tuple[int, Iterable[Mapping[str, Any]]],
    renditions: tuple[int, Iterable[Mapping[str, Any]]],
) -> str:
    return framed_section_digest(
        "spicyregs-source-state/1",
        (
            FramedSection("scopes", *scopes),
            FramedSection("schemas", *schemas),
            FramedSection("records", *records),
            FramedSection("renditions", *renditions),
        ),
    )


def _same_traversal(connection: sqlite3.Connection, left: int, right: int) -> bool:
    left_count = connection.execute("SELECT count(*) FROM observations WHERE traversal = ?", (left,)).fetchone()[0]
    right_count = connection.execute("SELECT count(*) FROM observations WHERE traversal = ?", (right,)).fetchone()[0]
    if left_count != right_count:
        return False
    difference = connection.execute(
        "SELECT 1 FROM observations l JOIN observations r ON r.traversal = ? AND r.ordinal = l.ordinal "
        "WHERE l.traversal = ? AND (l.source_record_id != r.source_record_id OR l.record_digest != r.record_digest) "
        "LIMIT 1",
        (right, left),
    ).fetchone()
    return difference is None


def _observation_version(
    profile: SourceNativeProfile,
    record: Mapping[str, Any],
) -> str | None:
    if profile.observation_version is None:
        return None
    value = profile.observation_version(record)
    if value is not None and (not isinstance(value, str) or not value):
        raise SourceNativeReleaseError(f"{profile.name} observation version must be nonempty text or null")
    return value


def _tie_group_is_volatile_only(
    connection: sqlite3.Connection,
    *,
    traversal: int,
    source_record_id: str,
    source_version: str | None,
    tie_comparison_digest: Callable[[Mapping[str, Any]], str],
) -> bool:
    """One same-instant group collapses when every observed record shares
    one ``tie_comparison_digest`` -- a profile's narrower, tie-judging-only
    view of the record (see ``SourceNativeProfile.tie_comparison_digest``)
    that omits fields derived at read time rather than carried by the
    document. Bounded to the rows of one tied identity, never the whole
    corpus.
    """

    reference: str | None = None
    for (payload,) in connection.execute(
        "SELECT record_payload FROM observations WHERE traversal = ? AND source_record_id = ? AND source_version IS ?",
        (traversal, source_record_id, source_version),
    ):
        wrapped = parse_canonical_json(bytes(payload))
        record = wrapped.get("record") if isinstance(wrapped, Mapping) else None
        if not isinstance(record, Mapping):
            raise SourceNativeReleaseError("indexed source-native record is not an object")
        digest = tie_comparison_digest(record)
        if reference is None:
            reference = digest
        elif digest != reference:
            return False
    return True


def _select_observations(
    connection: sqlite3.Connection,
    *,
    profile: SourceNativeProfile,
) -> None:
    """Select one record per source id using the disk-backed SQLite index."""

    connection.execute("UPDATE observations SET selected = 0")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS observations_selection "
        "ON observations (traversal, source_record_id, source_version, record_digest, ordinal)"
    )
    volatile_groups: list[tuple[int, str, str | None]] = []
    if profile.observation_version is None:
        duplicate = connection.execute(
            "SELECT traversal, source_record_id FROM observations "
            "GROUP BY traversal, source_record_id HAVING count(*) > 1 "
            "ORDER BY traversal, source_record_id LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise SourceNativeReleaseError(f"{profile.name} traversal repeats {str(duplicate[1])!r}")
    else:
        duplicate_condition = (
            "count(*) > 1" if profile.refuse_equal_observation_versions else "count(DISTINCT record_digest) > 1"
        )
        # A profile may declare tie_comparison_digest -- a second, narrower
        # digest that omits fields derived at read time rather than stored
        # on the record. Every other profile leaves it None, which
        # reproduces today's refusal exactly.
        tie_comparison_digest = profile.tie_comparison_digest
        for traversal, source_record_id, source_version in connection.execute(
            "SELECT traversal, source_record_id, source_version FROM observations "
            "GROUP BY traversal, source_record_id, source_version HAVING "
            f"{duplicate_condition} "
            "ORDER BY traversal, source_record_id, source_version IS NULL, "
            "source_version DESC"
        ):
            if tie_comparison_digest is not None and _tie_group_is_volatile_only(
                connection,
                traversal=traversal,
                source_record_id=source_record_id,
                source_version=source_version,
                tie_comparison_digest=tie_comparison_digest,
            ):
                volatile_groups.append((traversal, source_record_id, source_version))
                continue
            raise SourceNativeReleaseError(
                f"{profile.name} has an unresolved source-version tie for {str(source_record_id)!r} at {source_version!r}"
            )

    # One grouped maximum over the file-backed index above, not a correlated
    # search per candidate: linear index scans instead of O(n**2) when one
    # identity carries n observations. SQLite's ``max`` skips nulls and yields
    # null only when every observation is null, so ``IS`` marks the newest
    # non-null normalized version or the sole null version; the refusals above
    # already leave one record digest per (traversal, source id, version)
    # group, so the earliest ordinal breaks an identical repeat.
    connection.execute(
        "UPDATE observations SET selected = 1 WHERE (traversal, ordinal) IN ("
        "SELECT candidate.traversal, min(candidate.ordinal) FROM observations AS candidate "
        "JOIN (SELECT traversal, source_record_id, max(source_version) AS newest "
        "FROM observations GROUP BY traversal, source_record_id) AS preferred "
        "ON preferred.traversal = candidate.traversal "
        "AND preferred.source_record_id = candidate.source_record_id "
        "AND candidate.source_version IS preferred.newest "
        "GROUP BY candidate.traversal, candidate.source_record_id)"
    )

    # A volatile-only group's members share one source_version (the group-by
    # above) and only differ in read-time-derived fields, so which one is
    # "the" record is otherwise arbitrary; prefer the one the source listed
    # last (max ordinal) as the later, more current fetch. Re-point selection
    # only within the exact tied identity, and only if the block above just
    # made it the winner (selected = 1 already present) -- an older,
    # non-newest volatile-only group is left untouched.
    for traversal, source_record_id, source_version in volatile_groups:
        already_preferred = connection.execute(
            "SELECT 1 FROM observations WHERE traversal = ? AND source_record_id = ? "
            "AND source_version IS ? AND selected = 1",
            (traversal, source_record_id, source_version),
        ).fetchone()
        if already_preferred is None:
            continue
        connection.execute(
            "UPDATE observations SET selected = CASE WHEN ordinal = ("
            "SELECT max(ordinal) FROM observations "
            "WHERE traversal = ? AND source_record_id = ? AND source_version IS ?"
            ") THEN 1 ELSE 0 END "
            "WHERE traversal = ? AND source_record_id = ? AND source_version IS ?",
            (
                traversal,
                source_record_id,
                source_version,
                traversal,
                source_record_id,
                source_version,
            ),
        )


def _accepted_traversal(
    connection: sqlite3.Connection,
    *,
    traversal_count: int,
    profile: SourceNativeProfile,
) -> int:
    if profile.traversal_acceptance in {
        "single-observed-traversal",
        "source-enumeration",
    }:
        if traversal_count != 1:
            raise SourceNativeReleaseError(f"{profile.name} acceptance requires exactly one traversal")
        return 0
    for right in range(1, traversal_count):
        if _same_traversal(connection, right - 1, right):
            return right
    raise SourceNativeReleaseError("observed crawl lacks two stable consecutive traversals")


def _validate_evidence_media_type(page: SourceNativePage) -> None:
    if page.evidence_media_type not in {"application/json", "application/zip"}:
        raise SourceNativeReleaseError("source-native evidence media type is unsupported")


def _query_mappings(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> Iterator[Mapping[str, Any]]:
    for (payload,) in connection.execute(query, parameters):
        value = parse_canonical_json(bytes(payload))
        if not isinstance(value, Mapping):
            raise SourceNativeReleaseError("indexed source-native record is not an object")
        yield value


def _query_renditions(
    connection: sqlite3.Connection,
    accepted_traversal: int,
    partition_id: str | None = None,
) -> Iterator[Mapping[str, Any]]:
    query = (
        "SELECT rendition_payload FROM observations "
        "WHERE traversal = ? AND selected = 1 "
        + ("AND partition_id = ? " if partition_id is not None else "")
        + "ORDER BY source_record_id"
    )
    parameters: tuple[object, ...] = (
        (accepted_traversal, partition_id) if partition_id is not None else (accepted_traversal,)
    )
    for (payload,) in connection.execute(query, parameters):
        values = parse_canonical_json(bytes(payload))
        if not isinstance(values, list):
            raise SourceNativeReleaseError("indexed rendition group is not an array")
        for value in values:
            if not isinstance(value, Mapping):
                raise SourceNativeReleaseError("indexed rendition row is not an object")
            yield value


def _ordered_rendition_rows(
    profile: SourceNativeProfile,
    record: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    values = tuple(profile.rendition_rows(record))
    keys: list[tuple[str, str]] = []
    for value in values:
        source_record_id = value.get("sourceRecordId")
        rendition_id = value.get("renditionId")
        if (
            not isinstance(source_record_id, str)
            or not source_record_id
            or not isinstance(rendition_id, str)
            or not rendition_id
        ):
            raise SourceNativeReleaseError(f"{profile.name} rendition row lacks its closed identity")
        keys.append((source_record_id, rendition_id))
    if len(set(keys)) != len(keys):
        raise SourceNativeReleaseError(f"{profile.name} rendition identity is repeated")
    return tuple(value for _, value in sorted(zip(keys, values, strict=True)))


def _ledger_rows(
    connection: sqlite3.Connection,
    accepted_traversal: int,
    partition_id: str | None = None,
) -> Iterator[Mapping[str, Any]]:
    query = (
        "SELECT observations.source_record_id, observations.evidence_ref "
        "FROM observations "
        "WHERE observations.traversal = ? AND observations.selected = 1 "
        + ("AND observations.partition_id = ? " if partition_id is not None else "")
        + "ORDER BY observations.source_record_id"
    )
    parameters: tuple[object, ...] = (
        (accepted_traversal, partition_id) if partition_id is not None else (accepted_traversal,)
    )
    for source_record_id, evidence_ref in connection.execute(query, parameters):
        yield {
            "evidenceBlobRef": evidence_ref,
            "failure": None,
            "observationRef": {"sourceRecordId": source_record_id},
            "sourceRecordId": source_record_id,
        }


def _unclassified_source_record_id(traversal_index: int, page_index: int, record_index: int) -> str:
    """A deterministic stand-in identity for a record that failed classification.

    Its position in evidence already retained -- traversal, page, and index
    within that page's declared results -- is the one identity available
    without asking the profile for anything new, and it is stable for the
    same bytes replayed the same way.
    """

    return f"{_UNCLASSIFIED_RECORD_ID_PREFIX}:{traversal_index}:{page_index}:{record_index}"


def _failure_ledger_rows(
    connection: sqlite3.Connection,
    accepted_traversal: int,
    partition_id: str | None = None,
) -> Iterator[Mapping[str, Any]]:
    query = (
        "SELECT source_record_id, failure_class, reason_code, evidence_ref FROM failures "
        "WHERE traversal = ? "
        + ("AND partition_id = ? " if partition_id is not None else "")
        + "ORDER BY source_record_id"
    )
    parameters: tuple[object, ...] = (
        (accepted_traversal, partition_id) if partition_id is not None else (accepted_traversal,)
    )
    for source_record_id, failure_class, reason_code, evidence_ref in connection.execute(query, parameters):
        yield {
            "evidenceBlobRef": evidence_ref,
            "failure": {
                "class": failure_class,
                "evidenceDigest": evidence_ref,
                "reasonCode": reason_code,
            },
            "observationRef": {"sourceRecordId": source_record_id},
            "sourceRecordId": source_record_id,
        }


def _full_ledger_rows(
    connection: sqlite3.Connection,
    accepted_traversal: int,
    partition_id: str | None = None,
) -> Iterator[Mapping[str, Any]]:
    """Every ledger row for one accepted traversal: published successes and
    recorded failures, interleaved in one global sourceRecordId order.

    ``_ledger_rows`` and ``_failure_ledger_rows`` are each already sorted by
    ``sourceRecordId`` (one SQL query, one ``ORDER BY``, per function), so
    merging the two needs no sort of its own -- it matches what the
    partition reader enforces on the other end (:func:`_partition_rows`,
    which refuses a partition whose identity does not strictly increase).
    """

    return heapq.merge(
        _ledger_rows(connection, accepted_traversal, partition_id),
        _failure_ledger_rows(connection, accepted_traversal, partition_id),
        key=lambda row: row["sourceRecordId"],
    )


def _page_rows(
    connection: sqlite3.Connection,
    accepted_traversal: int,
    *,
    accepted_only: bool = False,
    partition_id: str | None = None,
) -> Iterator[Mapping[str, Any]]:
    # The inner query below runs once per page and filters on (traversal, page),
    # but the table's primary key is (traversal, ordinal) and the selection index
    # leads (traversal, source_record_id). SQLite therefore narrowed on traversal
    # alone and then examined every observation in it -- once per page. Measured
    # by EXPLAIN QUERY PLAN and by timing the loop at the composite release's own
    # cardinality (1,007,639 observations over 1,072 pages): 39.8 ms/page without
    # this index and 0.2 ms/page with it, about 200x on the query.
    #
    # Created here rather than beside `observations_selection`, because that
    # function also serves the producer replay gate's observations table, which
    # has no `page` column at all -- the statement would raise there.
    connection.execute("CREATE INDEX IF NOT EXISTS observations_page ON observations (traversal, page, ordinal)")
    conditions: list[str] = []
    parameters: list[object] = []
    if accepted_only:
        conditions.append("traversal = ?")
        parameters.append(accepted_traversal)
    if partition_id is not None:
        conditions.append("partition_id = ?")
        parameters.append(partition_id)
    query = (
        "SELECT traversal, page, window_index, window_page, records_included, request_key, "
        "source_cursor, next_cursor, evidence_ref, evidence_media_type "
        "FROM pages " + (("WHERE " + " AND ".join(conditions) + " ") if conditions else "") + "ORDER BY traversal, page"
    )
    for (
        traversal,
        page,
        window_index,
        window_page,
        records_included,
        request_key,
        source_cursor,
        next_cursor,
        evidence_ref,
        evidence_media_type,
    ) in connection.execute(query, tuple(parameters)):
        discovered = [
            {"recordDigest": record_digest, "sourceRecordId": source_record_id}
            for source_record_id, record_digest in connection.execute(
                "SELECT source_record_id, record_digest FROM observations "
                "WHERE traversal = ? AND page = ? ORDER BY ordinal",
                (traversal, page),
            )
        ]
        yield _PAGE_SHAPE.build(
            accepted=traversal == accepted_traversal,
            discoveredRecords=discovered,
            evidenceMediaType=evidence_media_type,
            evidenceBlobRef=evidence_ref,
            pageIndex=page,
            requestKey=request_key,
            recordsIncluded=bool(records_included),
            responseDigest=evidence_ref,
            sourceCursor=source_cursor,
            terminal=next_cursor is None,
            traversalIndex=traversal,
            windowIndex=window_index,
            windowPageIndex=window_page,
        )
