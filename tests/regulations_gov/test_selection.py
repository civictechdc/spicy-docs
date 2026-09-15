"""Regulations Gov: selection behavior."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from spicy_docs.source_native import (
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
)
from spicy_docs.source_native.profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native.regulations_gov import (
    DOCUMENT_TIE_VOLATILE_FIELDS,
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
    """The live Mirrulations mirror holds two objects for docket
    ACF-2007-0125 (``.../docket/ACF-2007-0125.json``, modifyDate
    2021-02-12, and the newer ``...(1).json``, modifyDate 2024-06-12) — a
    later observation of the same record, not a duplicate to filter out by
    filename. The publisher must collapse to the newest exactly as comments
    do (2026-09-02 fix), instead of refusing the repeated id.
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
    """Collapse equal canonical records even when raw JSON key order differs.

    ACF-2026-0199 refetches (18)/(19) share modifyDate. Reversing one payload's key
    order changes its bytes, not its record digest. Publish one record and retain
    all discarded observations byte-for-byte, including the older distinct version.
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
    """Documents collapse the same way as dockets and comments: a repeat
    object for one document id keeps only the newest observed modifyDate,
    with every older observation counted as discarded (2026-09-02 fix).
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
    """Two DIFFERENT bodies at the same normalized instant are a genuine tie
    and still refuse (2026-09-02): only a repeated pair with an identical
    canonical record digest at one instant collapses, per
    ``test_release_collapses_identical_record_digests_with_differing_raw_bytes``.
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
    """Comparison is on the normalized UTC instant, so two differently offset
    stamps denoting the same instant still tie. The bodies differ (title
    "first" vs "second"), so their record digests differ too, and this still
    refuses (2026-09-02): only a repeated pair with an identical canonical
    record digest at one instant collapses."""
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


def test_read_time_derived_field_only_difference_collapses_without_tying(tmp_path: Path) -> None:
    """Collapse a tied version whose only difference is read-time openForComment.

    BIS-2023-0021-0001 refetches can cross the comment deadline without changing
    modifyDate. Publish the last-listed object (openForComment=True here) as the
    only available fetch-recency signal; count and retain the discarded observation.
    """
    assert DOCUMENT_TIE_VOLATILE_FIELDS == {"openForComment", "withinCommentPeriod"}
    identity = "BIS-2023-0021-0001"
    closed = _document(
        identity,
        agencyId="BIS",
        docketId="BIS-2023-0021",
        modifyDate="2023-10-13T01:04:10Z",
        postedDate="2023-10-01T00:00:00Z",
        openForComment=False,
    )
    reopened = _document(
        identity,
        agencyId="BIS",
        docketId="BIS-2023-0021",
        modifyDate="2023-10-13T01:04:10Z",
        postedDate="2023-10-01T00:00:00Z",
        openForComment=True,
    )
    scope = _bis_document_scope()
    release = tmp_path / "documents"

    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader(
                [
                    _document_object(identity, value=closed, tag="1", agency="BIS", docket_id="BIS-2023-0021"),
                    _document_object(identity, value=reopened, tag="2", agency="BIS", docket_id="BIS-2023-0021"),
                ]
            ),
            query_scope=scope,
        ),
        build=_build(scope),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)

    published_records = list(reader.iter_records())
    assert len(published_records) == 1
    assert published_records[0]["record"]["data"]["attributes"]["openForComment"] is True

    receipt = json.loads((release / "receipts/publication.json").read_bytes())
    assert receipt["discoveredRecordCount"] == 2
    assert receipt["inputObservationCount"] == 2
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 1

    # Both mirror objects -- differing only in openForComment -- stay
    # byte-exact in acquisition evidence; the collapse happens only at
    # selection.
    discovered = [record for row in payload_rows(release, "acquisition-pages") for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [identity, identity]
    assert len({record["recordDigest"] for record in discovered}) == 2


def test_read_time_derived_field_difference_with_a_substantive_difference_still_refuses_the_tie(
    tmp_path: Path,
) -> None:
    """The same read-time-derived shape measured for
    EPA-HQ-OAR-2006-0894-0021 (two objects at modifyDate
    2024-04-25T01:00:59Z, one difference being ``openForComment``) still
    refuses when a second, substantive field -- here ``title`` -- also
    differs: only a difference confined to ``DOCUMENT_TIE_VOLATILE_FIELDS``
    collapses."""
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
