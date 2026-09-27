"""Selection contract for regulations.gov dockets and documents: the newest observation per identity wins and
the rest are counted discarded, identical canonical record digests collapse across differing raw bytes, and
differing bodies at one normalized instant still refuse a tie.
"""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from spicy_docs.releases.observations import volatile_tie_choice
from spicy_docs.source_native import (
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
)
from spicy_docs.source_native.profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native.regulations_gov import (
    VOLATILE_TIE_MARGIN_SECONDS,
    document_source_record_digest,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.regulations_gov.fixtures import (
    _acf_docket_scope,
    _acf_document_scope,
    _bis_document_scope,
    _build,
    _bytes,
    _CollapseFixture,
    _completed_at,
    _docket,
    _docket_collapse_fixture,
    _docket_object,
    _document,
    _document_collapse_fixture,
    _document_object,
    _epa_hq_document_scope,
    _Reader,
    _reader,
    _reordered,
)
from tests.source_fixtures import payload_rows


def test_docket_release_selects_newest_observation_and_counts_discard(tmp_path: Path) -> None:
    """The live Mirrulations mirror holds two objects for docket ACF-2007-0125 (modifyDate 2021-02-12 and the
    newer 2024-06-12 refetch), a later observation rather than a duplicate to filter out by filename, and the
    publisher must collapse to the newest exactly as comments do (2026-09-02 fix).
    """
    identity = "ACF-2007-0125"
    older = _docket(identity, agencyId="ACF", modifyDate="2021-02-12T01:00:50Z", title="older observation")
    newer = _docket(identity, agencyId="ACF", modifyDate="2024-06-12T01:16:04Z", title="newer observation")
    scope = _acf_docket_scope()
    release = tmp_path / "dockets"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCKET_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_docket_pages(
            lambda agency: (
                _Reader(
                    [
                        _docket_object(identity, value=older, tag="1", agency="ACF"),
                        _docket_object(identity, value=newer, tag="2", agency="ACF"),
                    ]
                )
                if agency == "ACF"
                else pytest.fail("wrong agency")
            ),
            query_scope=scope,
        ),
        build=_build(scope),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCKET_PROFILE)

    assert [row["record"]["data"]["attributes"]["title"] for row in reader.iter_records()] == ["newer observation"]
    receipt = json.loads((release / "receipts/publication.json").read_bytes())
    assert receipt["discoveredRecordCount"] == 2
    assert receipt["inputObservationCount"] == 2
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 1
    # The discarded older observation stays in the acquisition evidence.
    discovered = [record for row in payload_rows(release, "acquisition-pages") for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [identity, identity]
    assert len({record["recordDigest"] for record in discovered}) == 2


@pytest.mark.parametrize(
    "fixture",
    [_docket_collapse_fixture(), _document_collapse_fixture()],
    ids=["docket", "document"],
)
def test_release_collapses_identical_record_digests_with_differing_raw_bytes(
    tmp_path: Path, fixture: _CollapseFixture
) -> None:
    """Collapse equal canonical records even when raw JSON key order differs: ACF-2026-0199 refetches (18)/(19)
    share modifyDate, and reversing one payload's key order changes its bytes but not its record digest. Publish
    one record and retain all discarded observations byte-for-byte, including the older distinct version.
    """
    reordered_newest = _reordered(fixture.newest)
    assert reordered_newest == fixture.newest
    first_bytes = _bytes(fixture.newest, indent=2)
    second_bytes = _bytes(reordered_newest, indent=2)
    assert first_bytes != second_bytes
    assert fixture.record_digest(fixture.newest) == fixture.record_digest(reordered_newest)

    objects = [
        fixture.build_object(value=fixture.older, tag="1"),
        fixture.build_object(value=fixture.newest, tag="2"),
        fixture.build_object(value=reordered_newest, tag="3"),
    ]
    release = tmp_path / fixture.collection
    published = SourceNativeReleasePublisher(
        fixture.profile,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        fixture.iter_pages(
            lambda agency: _Reader(objects) if agency == "ACF" else pytest.fail("wrong agency"),
            query_scope=fixture.scope,
        ),
        build=_build(fixture.scope),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, fixture.profile)

    assert [row["record"]["data"]["attributes"]["title"] for row in reader.iter_records()] == ["newest observation"]
    receipt = json.loads((release / "receipts/publication.json").read_bytes())
    assert receipt["discoveredRecordCount"] == 3
    assert receipt["inputObservationCount"] == 3
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 2

    pages = payload_rows(release, "acquisition-pages")
    discovered = [record for row in pages for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [fixture.identity] * 3
    digests = {record["recordDigest"] for record in discovered}
    assert len(digests) == 2
    assert fixture.record_digest(fixture.newest) in digests

    # Both exact objects — differing raw bytes, equal record digest — stay
    # byte-for-byte in acquisition evidence; the same-instant pair is
    # deduplicated only at selection, not at the evidence layer.
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    with store.open(pages[0]["evidenceBlobRef"]) as stream:
        evidence_bytes = stream.read()
    with ZipFile(BytesIO(evidence_bytes)) as archive:
        assert archive.read("objects/000001.json") == first_bytes
        assert archive.read("objects/000002.json") == second_bytes


def test_document_release_selects_newest_observation_and_counts_discard(tmp_path: Path) -> None:
    """Documents collapse the same way as dockets and comments: a repeat object for one document id keeps only
    the newest observed modifyDate, with every older observation counted as discarded (2026-09-02 fix).
    """
    identity = "ACF-2021-0001-0001"
    older = _document(
        identity,
        agencyId="ACF",
        docketId="ACF-2021-0001",
        modifyDate="2021-03-01T00:00:00Z",
        postedDate="2021-02-15T00:00:00Z",
        title="older observation",
    )
    newer = _document(
        identity,
        agencyId="ACF",
        docketId="ACF-2021-0001",
        modifyDate="2024-06-12T01:16:04Z",
        postedDate="2021-02-15T00:00:00Z",
        title="newer observation",
    )
    scope = _acf_document_scope()
    release = tmp_path / "documents"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda agency: (
                _Reader(
                    [
                        _document_object(identity, value=older, tag="1", agency="ACF", docket_id="ACF-2021-0001"),
                        _document_object(identity, value=newer, tag="2", agency="ACF", docket_id="ACF-2021-0001"),
                    ]
                )
                if agency == "ACF"
                else pytest.fail("wrong agency")
            ),
            query_scope=scope,
        ),
        build=_build(scope),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)

    assert [row["record"]["data"]["attributes"]["title"] for row in reader.iter_records()] == ["newer observation"]
    receipt = json.loads((release / "receipts/publication.json").read_bytes())
    assert receipt["discoveredRecordCount"] == 2
    assert receipt["inputObservationCount"] == 2
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 1


def test_repeated_normalized_docket_versions_refuse_a_tie(tmp_path: Path) -> None:
    """Two DIFFERENT bodies at the same normalized instant are a genuine tie and still refuse (2026-09-02):
    only a repeated pair with an identical canonical record digest at one instant collapses.
    """
    identity = "ACF-2007-0125"
    first = _docket(identity, agencyId="ACF", modifyDate="2024-06-12T01:16:04Z", title="first")
    second = _docket(identity, agencyId="ACF", modifyDate="2024-06-12T01:16:04Z", title="second")
    scope = _acf_docket_scope()

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        SourceNativeReleasePublisher(
            REGULATIONS_GOV_DOCKET_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            iter_regulations_gov_docket_pages(
                lambda _agency: _Reader(
                    [
                        _docket_object(identity, value=first, tag="1", agency="ACF"),
                        _docket_object(identity, value=second, tag="2", agency="ACF"),
                    ]
                ),
                query_scope=scope,
            ),
            build=_build(scope),
            destination=tmp_path / "docket-tie",
        )


def test_repeated_normalized_document_versions_refuse_a_tie(tmp_path: Path) -> None:
    """Comparison is on the normalized UTC instant, so two differently offset stamps denoting the same instant
    still tie; the bodies differ (title "first" vs "second"), so their record digests differ too, and this still
    refuses (2026-09-02).
    """
    identity = "ACF-2021-0001-0001"
    first = _document(
        identity,
        agencyId="ACF",
        docketId="ACF-2021-0001",
        modifyDate="2024-06-12T01:16:04Z",
        postedDate="2021-02-15T00:00:00Z",
        title="first",
    )
    second = _document(
        identity,
        agencyId="ACF",
        docketId="ACF-2021-0001",
        modifyDate="2024-06-11T21:16:04-04:00",
        postedDate="2021-02-15T00:00:00Z",
        title="second",
    )
    scope = _acf_document_scope()

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        SourceNativeReleasePublisher(
            REGULATIONS_GOV_DOCUMENT_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            iter_regulations_gov_document_pages(
                lambda _agency: _Reader(
                    [
                        _document_object(identity, value=first, tag="1", agency="ACF", docket_id="ACF-2021-0001"),
                        _document_object(identity, value=second, tag="2", agency="ACF", docket_id="ACF-2021-0001"),
                    ]
                ),
                query_scope=scope,
            ),
            build=_build(scope),
            destination=tmp_path / "document-tie",
        )


def _publish_documents(tmp_path: Path, name: str, objects: list, scope: dict[str, object]) -> tuple[list, dict]:
    """Publish one document release from listed objects; its records and receipt. Publishing replays the release
    from its retained evidence, so a selection that evidence cannot reproduce fails here."""
    release = tmp_path / name
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(lambda _agency: _Reader(objects), query_scope=scope),
        build=_build(scope),
        destination=release,
    )
    records = list(_reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE).iter_records())
    return records, json.loads((release / "receipts/publication.json").read_bytes())


def _flag(records: list) -> object:
    assert len(records) == 1
    return records[0]["record"]["data"]["attributes"]["openForComment"]


def _at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def test_volatile_tie_goes_to_the_later_write_listed_before_a_bulk_uploaded_base(tmp_path: Path) -> None:
    """ACF-2023-0003's shape (live listing 2026-09-27): the base ``X.json`` came in the April 2025 bulk upload, and a
    re-fetch in 2026 was written as the flat ``X(2).json``, which S3 lists first. Both state one modifyDate and differ
    only in ``openForComment``; the later write (closed) publishes, not the last-listed base (open)."""
    identity, docket = "ACF-2023-0003-0001", "ACF-2023-0003"
    open_, closed = (
        _document(
            identity,
            agencyId="ACF",
            docketId=docket,
            modifyDate="2023-10-13T01:04:10Z",
            postedDate="2023-09-01T00:00:00Z",
            openForComment=flag,
        )
        for flag in (True, False)
    )
    objects = [
        _document_object(
            identity,
            value=closed,
            tag=docket,
            agency="ACF",
            docket_id=docket,
            key_suffix="(2)",
            last_modified=_at("2026-07-22T04:32:38Z"),
        ),
        _document_object(
            identity, value=open_, tag=docket, agency="ACF", docket_id=docket, last_modified=_at("2025-04-06T15:59:52Z")
        ),
    ]

    records, receipt = _publish_documents(tmp_path, "documents", objects, _acf_document_scope())

    assert _flag(records) is False
    assert (receipt["inputObservationCount"], receipt["publishedRecordCount"]) == (2, 1)
    assert receipt["discardedObservationCount"] == 1


def test_volatile_tie_goes_to_the_later_write_after_a_rewritten_base(tmp_path: Path) -> None:
    """BIS_FRDOC_0001's shape (live listing 2026-09-27): a stacked chain from the April 2025 bulk upload, the base
    ``X.json`` rewritten in place on 2026-04-09, then flat re-fetches up to ``X(8).json`` on 2026-09-24. S3 lists the
    base last, so the last-listed rule published the April copy; the September write publishes."""
    identity, docket = "BIS_FRDOC_0001-0123", "BIS_FRDOC_0001"

    def version(modified: str, flag: bool) -> dict:
        return _document(
            identity,
            agencyId="BIS",
            docketId=docket,
            modifyDate=modified,
            postedDate="2023-03-01T00:00:00Z",
            openForComment=flag,
        )

    objects = [
        _document_object(
            identity,
            value=version("2023-03-02T01:00:00Z", True),
            tag=docket,
            agency="BIS",
            docket_id=docket,
            key_suffix="(1)(2)(3)",
            last_modified=_at("2025-04-13T04:42:07Z"),
        ),
        _document_object(
            identity,
            value=version("2023-10-13T01:04:10Z", False),
            tag=docket,
            agency="BIS",
            docket_id=docket,
            key_suffix="(8)",
            last_modified=_at("2026-09-24T16:52:41Z"),
        ),
        _document_object(
            identity,
            value=version("2023-10-13T01:04:10Z", True),
            tag=docket,
            agency="BIS",
            docket_id=docket,
            last_modified=_at("2026-04-09T15:19:10Z"),
        ),
    ]

    records, receipt = _publish_documents(tmp_path, "documents", objects, _bis_document_scope())

    assert _flag(records) is False
    assert (receipt["inputObservationCount"], receipt["discardedObservationCount"]) == (3, 2)


@pytest.mark.parametrize(
    ("docket", "identity", "suffixes", "written"),
    [
        # DEA-2023-0148-0026 as listed 2026-09-27: its tied copies are the ends of a stacked chain that the April 2025
        # bulk upload wrote in one second, so LastModified cannot order them.
        (
            "DEA-2023-0148",
            "DEA-2023-0148-0026",
            ("(1)(2)(3)(4)(5)(6)(7)(8)(9)(10)(11)", "(1)(2)(3)(4)(5)(6)(7)(8)(9)(10)"),
            ("2025-04-13T12:58:33Z", "2025-04-13T12:58:33Z"),
        ),
        # Two live flat re-fetches 3,010 s apart, the second-closest pair of consecutive later writes measured.
        ("DEA-2024-0001", "DEA-2024-0001-0001", ("(3)", "(4)"), ("2026-08-20T13:18:51Z", "2026-08-20T14:09:01Z")),
    ],
    ids=["bulk-uploaded-stacked-chain", "live-writes-within-the-margin"],
)
def test_volatile_tie_within_the_margin_takes_the_smallest_digest_in_either_order(
    tmp_path: Path, docket: str, identity: str, suffixes: tuple[str, str], written: tuple[str, str]
) -> None:
    """Writes no more than ``VOLATILE_TIE_MARGIN_SECONDS`` apart carry no fetch order, so the tie publishes the smaller
    record digest -- a stable choice, not the latest -- whichever key holds which copy."""
    open_, closed = (
        _document(
            identity,
            agencyId="DEA",
            docketId=docket,
            modifyDate="2024-04-02T01:04:01Z",
            postedDate="2024-01-03T05:00:00Z",
            openForComment=flag,
        )
        for flag in (True, False)
    )
    stable = min((open_, closed), key=document_source_record_digest)["data"]["attributes"]["openForComment"]
    scope = {"agencies": ["DEA"], "publishedFrom": "2024-01-01", "publishedThrough": "2024-12-31"}
    published = []
    for name, bodies in (("as-listed", (open_, closed)), ("swapped", (closed, open_))):
        objects = [
            _document_object(
                identity,
                value=body,
                tag=docket,
                agency="DEA",
                docket_id=docket,
                key_suffix=suffix,
                last_modified=_at(stamp),
            )
            for body, suffix, stamp in zip(bodies, suffixes, written, strict=True)
        ]
        published.append(_flag(_publish_documents(tmp_path, name, objects, scope)[0]))

    assert published == [stable, stable]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # One hour and one second apart: the later write, though listed first.
        ([(0, 1_000 + 3_601, "sha256:c"), (1, 1_000, "sha256:b")], 0),
        # Exactly the margin apart: not clearly apart, so the smaller digest.
        ([(0, 1_000, "sha256:b"), (1, 1_000 + 3_600, "sha256:c")], 0),
        # The newest must lead every other copy; the choice stays among the two it does not lead, never the
        # older copy with the smallest digest overall.
        ([(2, 0, "sha256:a"), (0, 90_000, "sha256:c"), (1, 90_010, "sha256:b")], 1),
        # A copy without a stated write cannot be ordered.
        ([(0, None, "sha256:b"), (1, 90_000, "sha256:c")], 0),
        # Equal smallest digests fall to the earliest ordinal.
        ([(3, 5, "sha256:a"), (1, 5, "sha256:a"), (2, 6, "sha256:b")], 1),
    ],
    ids=["clearly-apart", "at-the-margin", "leads-every-copy", "unstated-write", "equal-digests"],
)
def test_volatile_tie_choice(rows: list, expected: int) -> None:
    assert VOLATILE_TIE_MARGIN_SECONDS == 3_600
    assert volatile_tie_choice(rows, margin_seconds=VOLATILE_TIE_MARGIN_SECONDS) == expected


def test_read_time_derived_field_difference_with_a_substantive_difference_still_refuses_the_tie(
    tmp_path: Path,
) -> None:
    """The same read-time-derived shape measured for EPA-HQ-OAR-2006-0894-0021 (two objects at modifyDate
    2024-04-25T01:00:59Z, one difference being ``openForComment``) still refuses when a second, substantive
    field -- here ``title`` -- also differs: only a difference confined to ``DOCUMENT_TIE_VOLATILE_FIELDS``
    collapses.
    """
    identity = "EPA-HQ-OAR-2006-0894-0021"
    first = _document(
        identity,
        agencyId="EPA",
        docketId="EPA-HQ-OAR-2006-0894",
        modifyDate="2024-04-25T01:00:59Z",
        postedDate="2024-04-01T00:00:00Z",
        openForComment=False,
        title="first",
    )
    second = _document(
        identity,
        agencyId="EPA",
        docketId="EPA-HQ-OAR-2006-0894",
        modifyDate="2024-04-25T01:00:59Z",
        postedDate="2024-04-01T00:00:00Z",
        openForComment=True,
        title="second",
    )
    scope = _epa_hq_document_scope()

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        SourceNativeReleasePublisher(
            REGULATIONS_GOV_DOCUMENT_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            iter_regulations_gov_document_pages(
                lambda _agency: _Reader(
                    [
                        _document_object(
                            identity, value=first, tag="1", agency="EPA", docket_id="EPA-HQ-OAR-2006-0894"
                        ),
                        _document_object(
                            identity, value=second, tag="2", agency="EPA", docket_id="EPA-HQ-OAR-2006-0894"
                        ),
                    ]
                ),
                query_scope=scope,
            ),
            build=_build(scope),
            destination=tmp_path / "document-tie",
        )
