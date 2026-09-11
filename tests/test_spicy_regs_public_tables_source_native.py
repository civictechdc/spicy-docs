"""The spicy-regs public tables as the first rung of supply.

PLAN.md's supply-precedence ruling (accepted 2026-08-31) starts acquisition at
the community's already-collected tables, captured and digest-pinned like any
source.  These tests hold the comment-text scope to that: whole partition
objects pinned by digest, every declared column preserved including the nulls
and the ``See attached`` bodies, a scope that names exactly the partitions it
covers, and a fail-closed refusal the moment the published table's columns
drift.  Nothing here touches the network.
"""

from __future__ import annotations

import ast
import io
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import polars as pl
import pytest
from rulespec_artifacts import LocalMemberSource, Producer

from spicy_docs.cli.source_native import main as source_native_main
from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.schemas.spicy_regs_public_tables import (
    PUBLIC_COMMENT_COLUMNS,
    PUBLIC_COMMENT_FILE_COLUMNS,
)
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native_profiles import SPICY_REGS_PUBLIC_COMMENT_PROFILE
from spicy_docs.sources.public_comments.native import (
    CAPTURE_PACK_TYPE,
    MANIFEST_ENTRY,
    MAX_PARTS_PER_AGENCY,
    PARTITION_ENTRY,
    SOURCE_SYSTEM_ID,
    PublicTableAcquisitionCheck,
    PublicTableCapture,
    PublicTableFetch,
    PublicTableSourceError,
    capture_pack_bytes,
    classify_comment_row,
    comment_acquisition_policy,
    comment_partition_locator,
    comment_rendition_rows,
    comment_source_issued_version,
    field_diagnostics,
    iter_spicy_regs_public_comment_pages,
    parse_comment_page_response,
    parse_public_table_request,
    spicy_regs_public_comment_query_scope,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

_IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
_PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=_IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="2.0",
    verifier_implementation_id=_IMPLEMENTATION_ID,
)
_BOILERPLATE = "See attached"
_ATTACHMENTS = json.dumps(
    [
        {
            "title": "Exact attachment title",
            "formats": [
                {
                    "url": "https://downloads.regulations.gov/EPA-2026-0001-0001/attachment.pdf",
                    "format": "pdf",
                    "size": 123,
                },
                {
                    "url": "https://downloads.regulations.gov/EPA-2026-0001-0001/attachment.txt",
                    "format": "txt",
                    "size": 7,
                },
            ],
        }
    ]
)


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


def _row(
    comment_id: str = "EPA-2026-0001-0001",
    **overrides: str | None,
) -> dict[str, str | None]:
    """One published comment row, defaulting to the table's real sparseness."""

    row: dict[str, str | None] = dict.fromkeys(PUBLIC_COMMENT_FILE_COLUMNS)
    row.update(
        {
            "comment_id": comment_id,
            "docket_id": "EPA-2026-0001",
            "title": "Comment on the proposed rule",
            "comment": _BOILERPLATE,
            "document_type": "Public Submission",
            "posted_date": "2026-08-24T04:00:00Z",
            "modify_date": "2026-08-25T01:02:03Z",
            "attachments_json": _ATTACHMENTS,
        }
    )
    row.update(overrides)
    return row


def _partition_bytes(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...] = PUBLIC_COMMENT_FILE_COLUMNS,
    schema: dict[str, Any] | None = None,
) -> bytes:
    declared = schema or {name: pl.String for name in columns}
    frame = pl.DataFrame(
        {name: [row.get(name) for row in rows] for name in columns},
        schema=declared,
    )
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def _capture(
    agency: str,
    part_index: int,
    rows: list[dict[str, Any]],
    *,
    content: bytes | None = None,
    etag: str | None = '"pinned-etag"',
    last_modified: str | None = "Mon, 25 Aug 2026 00:00:00 GMT",
) -> PublicTableCapture:
    return PublicTableCapture(
        locator=comment_partition_locator(agency, part_index),
        content=content if content is not None else _partition_bytes(rows),
        fetched_at="2026-08-25T00:00:00Z",
        etag=etag,
        last_modified=last_modified,
    )


def _mirror(captures: list[PublicTableCapture]):
    by_locator = {capture.locator: capture for capture in captures}

    def fetch(locator: str) -> PublicTableCapture | None:
        return by_locator.get(locator)

    return fetch


def _scope(*agencies: str) -> dict[str, Any]:
    return {"agencies": sorted(agencies or ("EPA",)), "table": "comments"}


def _publish(
    tmp_path: Path,
    captures: list[PublicTableCapture],
    *,
    scope: dict[str, Any] | None = None,
    name: str = "release",
    blobs: str = "blobs",
    fetch: PublicTableFetch | None = None,
    profile: SourceNativeProfile = SPICY_REGS_PUBLIC_COMMENT_PROFILE,
):
    query_scope = scope or _scope()
    return SourceNativeReleasePublisher(
        profile,
        blob_store=LocalSourceNativeBlobStore(tmp_path / blobs),
        clock=_completed_at,
    ).publish(
        iter_spicy_regs_public_comment_pages(fetch or _mirror(captures), query_scope=query_scope),
        build=SourceNativeReleaseBuild(
            query_scope=query_scope,
            producer=_PRODUCER,
            started_at="2026-08-25T00:00:00Z",
        ),
        destination=tmp_path / name,
    )


def _reader(root: Path, pin) -> SourceNativeReleaseReader:
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(root.parent / "blobs"),
        profile=SPICY_REGS_PUBLIC_COMMENT_PROFILE,
        expected_pin=pin,
        accepted_verifier_implementation_ids=frozenset({_IMPLEMENTATION_ID}),
    )


def test_every_published_column_survives_capture_including_nulls_and_boilerplate(
    tmp_path: Path,
) -> None:
    published = _publish(tmp_path, [_capture("EPA", 0, [_row()])])
    rows = list(_reader(published.root, published.artifact.pin).iter_records())

    assert len(rows) == 1
    record = rows[0]["record"]
    assert set(record) == set(PUBLIC_COMMENT_COLUMNS)
    # The partition key is carried by the directory name, not the file bytes.
    assert record["agency_code"] == "EPA"
    # "See attached" is a fact about the source at this layer, not noise, and
    # the columns the publisher left empty stay empty rather than disappearing.
    assert record["comment"] == _BOILERPLATE
    assert record["text_content"] is None
    assert record["text_extraction_status"] is None
    assert record["organization"] is None
    assert rows[0]["sourceRecordId"] == "EPA-2026-0001-0001"
    assert _reader(published.root, published.artifact.pin).source_system_id == SOURCE_SYSTEM_ID
    outcome = _reader(published.root, published.artifact.pin).collection_outcome
    assert outcome["sourceStateScope"] == "observed-crawl"
    assert outcome["traversalAcceptance"] == "single-observed-traversal"
    assert outcome["acquisitionPolicyVersion"] == "1.1"
    assert outcome["acquisitionPolicy"] == comment_acquisition_policy(_scope())


def test_capture_pins_the_partition_bytes_and_states_upstream_freshness() -> None:
    content = _partition_bytes([_row()])
    pack = capture_pack_bytes(_capture("EPA", 0, [], content=content), agency="EPA", part_index=0, terminal=True)

    with ZipFile(io.BytesIO(pack)) as archive:
        assert archive.namelist() == [MANIFEST_ENTRY, PARTITION_ENTRY]
        assert archive.read(PARTITION_ENTRY) == content

    response = parse_comment_page_response(pack)
    manifest = response["_capture"]
    assert manifest["captureType"] == CAPTURE_PACK_TYPE
    assert manifest["byteSize"] == len(content)
    assert manifest["sha256"].startswith("sha256:")
    assert manifest["fetchedAt"] == "2026-08-25T00:00:00Z"
    assert manifest["locator"] == "https://data.spicy-regs.dev/comments/agency/agency_code=EPA/part-0.parquet"
    # The mirror publishes no freshness manifest of its own; what it does state
    # is per-object HTTP validators, so those are what a capture records.
    assert manifest["etag"] == '"pinned-etag"'
    assert manifest["lastModified"] == "Mon, 25 Aug 2026 00:00:00 GMT"


def test_capture_refuses_a_partition_that_differs_from_its_pinned_digest() -> None:
    pack = capture_pack_bytes(_capture("EPA", 0, [_row()]), agency="EPA", part_index=0, terminal=True)
    swapped = _partition_bytes([_row("EPA-2026-0001-0002")])
    tampered = io.BytesIO()
    with ZipFile(io.BytesIO(pack)) as source, ZipFile(tampered, "w") as target:
        target.writestr(MANIFEST_ENTRY, source.read(MANIFEST_ENTRY))
        target.writestr(PARTITION_ENTRY, swapped)

    with pytest.raises(PublicTableSourceError, match="pinned digest|size differs"):
        parse_comment_page_response(tampered.getvalue())


def test_capture_refuses_a_manifest_that_renames_its_partition() -> None:
    pack = capture_pack_bytes(_capture("EPA", 0, [_row()]), agency="EPA", part_index=0, terminal=True)
    with ZipFile(io.BytesIO(pack)) as archive:
        manifest = json.loads(archive.read(MANIFEST_ENTRY))
        content = archive.read(PARTITION_ENTRY)
    manifest["locator"] = "https://example.test/comments.parquet"
    relabelled = io.BytesIO()
    with ZipFile(relabelled, "w") as target:
        target.writestr(MANIFEST_ENTRY, json.dumps(manifest))
        target.writestr(PARTITION_ENTRY, content)

    with pytest.raises(PublicTableSourceError, match="locator differs"):
        parse_comment_page_response(relabelled.getvalue())


@pytest.mark.parametrize(
    ("label", "columns", "schema"),
    [
        ("added", (*PUBLIC_COMMENT_FILE_COLUMNS, "sentiment_score"), None),
        ("removed", PUBLIC_COMMENT_FILE_COLUMNS[:-1], None),
        ("renamed", ("body", *PUBLIC_COMMENT_FILE_COLUMNS[1:]), None),
        (
            "reordered",
            (PUBLIC_COMMENT_FILE_COLUMNS[1], PUBLIC_COMMENT_FILE_COLUMNS[0], *PUBLIC_COMMENT_FILE_COLUMNS[2:]),
            None,
        ),
        (
            "unpartitioned",
            ("agency_code", *PUBLIC_COMMENT_FILE_COLUMNS),
            None,
        ),
        (
            "retyped",
            PUBLIC_COMMENT_FILE_COLUMNS,
            {name: (pl.Int64 if name == "comment_id" else pl.String) for name in PUBLIC_COMMENT_FILE_COLUMNS},
        ),
    ],
)
def test_published_column_drift_fails_closed(
    label: str,
    columns: tuple[str, ...],
    schema: dict[str, Any] | None,
) -> None:
    row: dict[str, Any] = dict(_row())
    row["agency_code"] = "EPA"
    row["body"] = _BOILERPLATE
    row["sentiment_score"] = None
    if schema is not None:
        row["comment_id"] = 1

    content = _partition_bytes([row], columns=columns, schema=schema)
    pack = capture_pack_bytes(_capture("EPA", 0, [], content=content), agency="EPA", part_index=0, terminal=True)

    with pytest.raises(PublicTableSourceError, match="drifted"):
        parse_comment_page_response(pack)


@pytest.mark.parametrize("mutation", ["added", "removed"])
def test_row_column_drift_fails_closed(mutation: str) -> None:
    row: dict[str, Any] = dict(_row())
    row["agency_code"] = "EPA"
    if mutation == "added":
        row["sentiment_score"] = "0.5"
    else:
        del row["receive_date"]

    with pytest.raises(PublicTableSourceError, match="drifted"):
        classify_comment_row(row)


def test_a_nontext_cell_is_refused_rather_than_coerced() -> None:
    row: dict[str, Any] = dict(_row())
    row["agency_code"] = "EPA"
    row["posted_date"] = 20260824

    with pytest.raises(PublicTableSourceError, match="posted_date must be text or null"):
        classify_comment_row(row)


@pytest.mark.parametrize(
    "scope",
    [
        {"agencies": [], "table": "comments"},
        {"agencies": ["FDA", "EPA"], "table": "comments"},
        {"agencies": ["EPA", "EPA"], "table": "comments"},
        {"agencies": ["EPA"], "table": "documents"},
        {"agencies": ["EPA"], "table": "comments", "postedFrom": "2026-08-01"},
        {"agencies": "EPA", "table": "comments"},
    ],
)
def test_scope_declaration_is_closed_sorted_and_partition_named(scope: dict[str, Any]) -> None:
    with pytest.raises(PublicTableSourceError):
        spicy_regs_public_comment_query_scope(scope)


def test_scope_declaration_names_the_partitions_a_capture_covers() -> None:
    canonical = spicy_regs_public_comment_query_scope({"agencies": ["EPA", "FDA"], "table": "comments"})
    assert canonical == {"agencies": ["EPA", "FDA"], "table": "comments"}

    policy = comment_acquisition_policy(canonical)
    assert policy["initialQueryScope"] == canonical
    assert policy["strategy"] == "observed-contiguous-part-probing"
    assert policy["acquisitionRung"] == "community-mirror"
    # The upstream pipeline already chose the current row per comment_id.
    assert policy["observationSelection"]["reselectedHere"] is False
    assert policy["observationSelection"]["selectedBy"] == "upstream-spicy-regs-pipeline"


def test_capture_must_cover_exactly_the_scoped_partitions(tmp_path: Path) -> None:
    with pytest.raises(PublicTableSourceError, match="capture for FDA did not obtain requested part-0.parquet"):
        _publish(
            tmp_path,
            [_capture("EPA", 0, [_row()])],
            scope=_scope("EPA", "FDA"),
        )


@pytest.mark.parametrize("later_part", [None, 2])
def test_first_missing_part_ends_observation_without_requesting_later_parts(
    tmp_path: Path, later_part: int | None
) -> None:
    captures = [_capture("EPA", 0, [_row()])]
    if later_part is not None:
        captures.append(_capture("EPA", later_part, [_row("EPA-2026-0001-0002")]))
    mirror = _mirror(captures)
    requested = []

    def fetch(locator: str) -> PublicTableCapture | None:
        requested.append(locator)
        return mirror(locator)

    published = _publish(tmp_path, captures, fetch=fetch)
    reader = _reader(published.root, published.artifact.pin)
    assert requested == [comment_partition_locator("EPA", 0), comment_partition_locator("EPA", 1)]
    assert [row["sourceRecordId"] for row in reader.iter_records()] == ["EPA-2026-0001-0001"]
    assert reader.collection_outcome["sourceStateScope"] == "observed-crawl"
    assert reader.collection_outcome["acquisitionEvidenceCount"] == 1
    assert reader.collection_outcome["reconciliationPassCount"] == 1


def test_missing_first_part_refuses_instead_of_publishing_empty_input(tmp_path: Path) -> None:
    requested = []

    def fetch(locator: str) -> None:
        requested.append(locator)

    with pytest.raises(PublicTableSourceError, match="did not obtain requested part-0.parquet"):
        _publish(tmp_path, [], fetch=fetch)
    assert requested == [comment_partition_locator("EPA", 0)]
    assert not (tmp_path / "release").exists()


def test_present_empty_partition_publishes_observed_empty_input(tmp_path: Path) -> None:
    published = _publish(tmp_path, [_capture("EPA", 0, [])])
    reader = _reader(published.root, published.artifact.pin)

    assert list(reader.iter_records()) == []
    assert reader.collection_outcome["recordOutcome"] == "empty"
    assert reader.collection_outcome["sourceStateScope"] == "observed-crawl"
    assert reader.collection_outcome["requestedScope"] == _scope()
    assert reader.collection_outcome["acquisitionEvidenceCount"] == 1


def test_partition_probe_bound_refuses_without_claiming_complete_membership() -> None:
    first = _capture("EPA", 0, [])
    requested = []

    def fetch(locator: str) -> PublicTableCapture:
        requested.append(locator)
        return replace(first, locator=locator)

    with pytest.raises(PublicTableSourceError, match="exceeded its partition bound"):
        list(iter_spicy_regs_public_comment_pages(fetch, query_scope=_scope()))
    assert MAX_PARTS_PER_AGENCY == 64
    assert requested == [comment_partition_locator("EPA", index) for index in range(MAX_PARTS_PER_AGENCY)]


@pytest.mark.parametrize("failed_part", [0, 2])
def test_request_failure_never_becomes_terminal_or_empty_evidence(tmp_path: Path, failed_part: int) -> None:
    requested = []
    error = PublicTableSourceError("public-table upstream request failed")

    def fetch(locator: str) -> PublicTableCapture:
        requested.append(locator)
        part = len(requested) - 1
        if part == failed_part:
            raise error
        return _capture("EPA", part, [_row(f"EPA-2026-0001-000{part}")])

    with pytest.raises(PublicTableSourceError) as caught:
        _publish(tmp_path, [], fetch=fetch)
    assert caught.value is error
    assert requested == [comment_partition_locator("EPA", index) for index in range(failed_part + 1)]
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("old_claim", [False, True])
def test_current_profile_refuses_prior_policy_and_complete_snapshot_claim(tmp_path: Path, old_claim: bool) -> None:
    def old_policy(scope):
        policy = comment_acquisition_policy(scope)
        del policy["coverageLimits"]
        policy["strategy"] = "complete-public-table-partition-capture"
        return policy

    old_profile = replace(
        SPICY_REGS_PUBLIC_COMMENT_PROFILE,
        acquisition_policy_version="1.0",
        acquisition_policy=old_policy,
        source_state_scope="complete-snapshot" if old_claim else "observed-crawl",
        traversal_acceptance="source-enumeration" if old_claim else "single-observed-traversal",
    )
    published = _publish(tmp_path, [_capture("EPA", 0, [_row()])], profile=old_profile)

    with pytest.raises(SourceNativeReleaseError, match="unsupported .* profile|requires current .* policy version"):
        _reader(published.root, published.artifact.pin)


def test_acquisition_check_refuses_a_capture_that_misses_a_scoped_partition() -> None:
    check = PublicTableAcquisitionCheck("comments")
    response = parse_comment_page_response(
        capture_pack_bytes(_capture("EPA", 0, [_row()]), agency="EPA", part_index=0, terminal=True)
    )
    check.add_window(
        response,
        page_window=parse_public_table_request(
            "spicy-regs-tables://public/comments/partition?agency=EPA&partIndex=0&terminal=true"
        ),
        records_included=True,
        response_bytes=b"",
    )

    with pytest.raises(PublicTableSourceError, match="does not cover exact agencies"):
        check.finish(query_scope=_scope("EPA", "FDA"))


def test_acquisition_check_refuses_unordered_or_nonterminal_partitions() -> None:
    def window(agency: str, part_index: int, terminal: bool):
        return parse_public_table_request(
            f"spicy-regs-tables://public/comments/partition?agency={agency}"
            f"&partIndex={part_index}&terminal={'true' if terminal else 'false'}"
        )

    def response(agency: str, part_index: int, terminal: bool):
        return parse_comment_page_response(
            capture_pack_bytes(
                _capture(agency, part_index, [_row(f"{agency}-2026-0001-0001")]),
                agency=agency,
                part_index=part_index,
                terminal=terminal,
            )
        )

    check = PublicTableAcquisitionCheck("comments")
    check.add_window(
        response("FDA", 0, True),
        page_window=window("FDA", 0, True),
        records_included=True,
        response_bytes=b"",
    )
    with pytest.raises(PublicTableSourceError, match="not ASCII-sorted"):
        check.add_window(
            response("EPA", 0, True),
            page_window=window("EPA", 0, True),
            records_included=True,
            response_bytes=b"",
        )

    open_capture = PublicTableAcquisitionCheck("comments")
    open_capture.add_window(
        response("EPA", 0, False),
        page_window=window("EPA", 0, False),
        records_included=True,
        response_bytes=b"",
    )
    with pytest.raises(PublicTableSourceError, match="missing a terminal partition"):
        open_capture.finish(query_scope=_scope("EPA"))


def test_an_empty_partition_is_evidence_even_though_it_carries_no_rows(tmp_path: Path) -> None:
    published = _publish(
        tmp_path,
        [_capture("EPA", 0, []), _capture("FDA", 0, [_row("FDA-2026-0002-0001")])],
        scope=_scope("EPA", "FDA"),
    )
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())

    assert receipt["acquisitionEvidenceCount"] == 2
    assert receipt["publishedRecordCount"] == 1


def test_multi_part_agency_capture_is_ordered_and_terminates_once(tmp_path: Path) -> None:
    pages = list(
        iter_spicy_regs_public_comment_pages(
            _mirror(
                [
                    _capture("EPA", 0, [_row("EPA-2026-0001-0001")]),
                    _capture("EPA", 1, [_row("EPA-2026-0001-0002")]),
                ]
            ),
            query_scope=_scope("EPA"),
        )
    )

    windows = [parse_public_table_request(page.request_key) for page in pages]
    assert [(window.agency, window.part_index, window.terminal) for window in windows] == [
        ("EPA", 0, False),
        ("EPA", 1, True),
    ]
    assert [page.page_index for page in pages] == [0, 1]

    published = _publish(
        tmp_path,
        [
            _capture("EPA", 0, [_row("EPA-2026-0001-0001")]),
            _capture("EPA", 1, [_row("EPA-2026-0001-0002")]),
        ],
    )
    identities = [row["sourceRecordId"] for row in _reader(published.root, published.artifact.pin).iter_records()]
    assert identities == ["EPA-2026-0001-0001", "EPA-2026-0001-0002"]


@pytest.mark.parametrize(
    "request_key",
    [
        "spicy-regs-tables://public/comments/partition?agency=EPA&partIndex=0",
        "spicy-regs-tables://public/documents/partition?agency=EPA&partIndex=0&terminal=true",
        "spicy-regs-tables://public/comments/partition?partIndex=0&terminal=true&agency=EPA",
        "https://data.spicy-regs.dev/comments/agency/agency_code=EPA/part-0.parquet",
    ],
)
def test_capture_request_keys_must_be_canonical(request_key: str) -> None:
    with pytest.raises(PublicTableSourceError):
        parse_public_table_request(request_key)


def test_a_repeated_identity_fails_closed_rather_than_being_collapsed(tmp_path: Path) -> None:
    # The upstream pipeline selects one row per comment_id. Two rows for one id
    # is upstream breakage, and this profile refuses rather than re-selecting.
    with pytest.raises(SourceNativeReleaseError, match="repeats"):
        _publish(
            tmp_path,
            [
                _capture(
                    "EPA",
                    0,
                    [
                        _row("EPA-2026-0001-0001", modify_date="2026-08-24T00:00:00Z"),
                        _row("EPA-2026-0001-0001", modify_date="2026-08-25T00:00:00Z"),
                    ],
                )
            ],
        )


def test_identity_and_version_come_from_the_columns_the_table_carries() -> None:
    record = classify_comment_row({**_row(), "agency_code": "EPA"})

    assert record["comment_id"] == "EPA-2026-0001-0001"
    assert comment_source_issued_version(record) == "2026-08-25T01:02:03Z"
    assert comment_source_issued_version(classify_comment_row({**_row(modify_date=None), "agency_code": "EPA"})) is None
    # Selection stays upstream, so the profile declares no observation version.
    assert SPICY_REGS_PUBLIC_COMMENT_PROFILE.observation_version is None


def test_attachment_locators_become_renditions_in_declared_order() -> None:
    record = classify_comment_row({**_row(), "agency_code": "EPA"})
    rows = comment_rendition_rows(record)

    assert [row["sourceField"] for row in rows] == [
        "attachments_json[0].formats[0]",
        "attachments_json[0].formats[1]",
    ]
    assert [row["mediaType"] for row in rows] == ["application/pdf", "text/plain"]
    assert [row["expectedByteSize"] for row in rows] == [123, 7]
    assert field_diagnostics(record) == []


def test_attachment_renditions_reach_the_published_release(tmp_path: Path) -> None:
    published = _publish(tmp_path, [_capture("EPA", 0, [_row()])])
    renditions = list(_reader(published.root, published.artifact.pin).iter_renditions())

    assert [row["locator"] for row in renditions] == [
        "https://downloads.regulations.gov/EPA-2026-0001-0001/attachment.pdf",
        "https://downloads.regulations.gov/EPA-2026-0001-0001/attachment.txt",
    ]
    assert {row["sourceRecordId"] for row in renditions} == {"EPA-2026-0001-0001"}
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["renditionIndexCount"] == 2


@pytest.mark.parametrize(
    ("attachments", "code"),
    [
        ("{not json", "malformed-attachments-json"),
        ('{"formats": []}', "malformed-attachments-json"),
        ("[3]", "malformed-attachment"),
        ('[{"title": "t", "formats": [{"format": "pdf"}]}]', "malformed-attachment-format"),
    ],
)
def test_malformed_publisher_json_is_described_not_repaired(attachments: str, code: str) -> None:
    record = classify_comment_row({**_row(attachments_json=attachments), "agency_code": "EPA"})
    diagnostics = field_diagnostics(record)

    assert [entry["code"] for entry in diagnostics] == [code]
    # The exact publisher value survives beside its diagnosis.
    assert record["attachments_json"] == attachments
    assert diagnostics[0]["value"] == attachments


def test_reconciliation_is_stable_across_an_independent_replay(tmp_path: Path) -> None:
    captures = [_capture("EPA", 0, [_row()]), _capture("FDA", 0, [_row("FDA-2026-0002-0001")])]
    first = _publish(tmp_path, deepcopy(captures), scope=_scope("EPA", "FDA"), name="first")
    # A second, independent capture of the same partition bytes into its own
    # payload store must land on the same artifact, byte accounting included.
    second = _publish(
        tmp_path,
        deepcopy(captures),
        scope=_scope("EPA", "FDA"),
        name="second",
        blobs="blobs-replay",
    )

    assert first.artifact.pin == second.artifact.pin
    assert first.artifact.root["spec"]["sourceStateDigest"] == second.artifact.root["spec"]["sourceStateDigest"]

    output = StringIO()
    exit_code = source_native_main(
        [
            "verify",
            "--source",
            "spicy-regs-public-comments",
            "--release",
            str(first.root),
            "--blob-store",
            str(tmp_path / "blobs"),
            "--logical-id",
            first.artifact.pin.logical_id,
            "--artifact-digest",
            first.artifact.pin.artifact_digest,
            "--accepted-verifier-implementation-id",
            _IMPLEMENTATION_ID,
        ],
        stdout=output,
        stderr=StringIO(),
    )

    assert exit_code == 0
    verified = json.loads(output.getvalue())
    assert verified["artifactDigest"] == first.artifact.pin.artifact_digest
    assert verified["sourceStateDigest"] == first.artifact.root["spec"]["sourceStateDigest"]


def test_profile_is_available_through_the_single_injected_cli(tmp_path: Path) -> None:
    output = StringIO()
    requested: list[str] = []
    mirror = _mirror([_capture("EPA", 0, [_row()])])

    def fetch(locator: str) -> PublicTableCapture | None:
        requested.append(locator)
        return mirror(locator)

    instants = iter(
        [
            datetime.fromisoformat("2026-08-25T00:00:00+00:00"),
            datetime.fromisoformat("2026-08-25T00:00:01+00:00"),
        ]
    )
    exit_code = source_native_main(
        [
            "publish",
            "--source",
            "spicy-regs-public-comments",
            "--agency",
            "EPA",
            "--destination",
            str(tmp_path / "cli-release"),
            "--blob-store",
            str(tmp_path / "blobs"),
            "--implementation-id",
            _IMPLEMENTATION_ID,
        ],
        fetch_public_table=fetch,
        clock=lambda: next(instants),
        stdout=output,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert json.loads(output.getvalue())["source"] == "spicy-regs-public-comments"
    assert requested == [
        "https://data.spicy-regs.dev/comments/agency/agency_code=EPA/part-0.parquet",
        "https://data.spicy-regs.dev/comments/agency/agency_code=EPA/part-1.parquet",
    ]


def test_cli_refuses_a_date_window_for_the_partition_scoped_source(tmp_path: Path) -> None:
    errors = StringIO()
    exit_code = source_native_main(
        [
            "publish",
            "--source",
            "spicy-regs-public-comments",
            "--since",
            "2026-08-24",
            "--until",
            "2026-08-24",
            "--agency",
            "EPA",
            "--destination",
            str(tmp_path / "dated"),
            "--blob-store",
            str(tmp_path / "blobs"),
            "--implementation-id",
            _IMPLEMENTATION_ID,
        ],
        fetch_public_table=_mirror([]),
        stdout=StringIO(),
        stderr=errors,
    )

    assert exit_code == 1
    assert json.loads(errors.getvalue())["error"]["message"].startswith("--since and --until are not valid")


def test_public_table_source_boundary_has_no_sibling_product_imports() -> None:
    repository = Path(__file__).resolve().parents[1]
    imported: set[str] = set()
    for relative in (
        "src/spicy_docs/sources/public_comments/native.py",
        "src/spicy_docs/schemas/spicy_regs_public_tables.py",
    ):
        tree = ast.parse((repository / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)

    assert not {name for name in imported if name.startswith(("docspec", "refspec", "spicysearch", "spicy_regs"))}
