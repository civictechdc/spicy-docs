"""Regulations Gov: evidence behavior."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from spicy_docs.source_native import (
    SourceNativeReleasePublisher,
)
from spicy_docs.source_native.profiles import (
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native.regulations_gov import (
    RegulationsGovPage,
    RegulationsGovSourceError,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
    parse_document_page_response,
    parse_mirrulations_request,
)
from spicy_docs.sources.regulations_gov import acquisition
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.regulations_gov.fixtures import (
    _build,
    _completed_at,
    _docket,
    _docket_object,
    _docket_scope,
    _document,
    _document_object,
    _document_scope,
    _Reader,
    _reader,
)
from tests.source_fixtures import payload_rows


def test_document_pages_capture_exact_listing_metadata_and_object_bytes_once() -> None:
    calls: list[tuple[str, int]] = []
    source_object = _document_object()
    pages = list(
        iter_regulations_gov_document_pages(
            lambda agency: _Reader(
                [source_object] if agency == "EPA" else pytest.fail("wrong agency"),
                calls,
            ),
            query_scope=_document_scope(),
        )
    )

    assert calls == [("iter", 16 * 1024 * 1024)]
    assert len(pages) == 1
    pack = pages[0]
    window = parse_mirrulations_request(pack.request_key)
    assert (window.agency, window.pack_index, window.terminal) == ("EPA", 0, True)
    with ZipFile(BytesIO(pack.response_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("objects/000000.json") == source_object.content
    assert manifest["objects"] == [
        {
            "byteSize": len(source_object.content),
            "entry": "objects/000000.json",
            "etag": source_object.etag,
            "included": True,
            "key": source_object.key,
            "versionId": source_object.version_id,
        }
    ]
    assert parse_document_page_response(pack.response_bytes)["results"] == [_document()]


def test_out_of_scope_objects_remain_evidence_without_becoming_records(tmp_path: Path) -> None:
    in_scope = _document_object()
    out_record = _document(
        "EPA-2026-0001-0002",
        postedDate="2026-08-23T23:59:59Z",
    )
    out_of_scope = _document_object(
        "EPA-2026-0001-0002",
        value=out_record,
        etag='"older-etag"',
    )
    release = tmp_path / "bounded"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([in_scope, out_of_scope]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)
    pages = payload_rows(release, "acquisition-pages")

    assert [row["sourceRecordId"] for row in reader.iter_records()] == ["EPA-2026-0001-0001"]
    assert [row["recordsIncluded"] for row in pages] == [True]
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    with store.open(pages[0]["evidenceBlobRef"]) as stream:
        parsed = parse_document_page_response(stream.read())
    assert [item["included"] for item in parsed["_packedRecords"]] == [True, False]


def test_undated_document_stays_in_evidence_without_aborting_the_agency(tmp_path: Path) -> None:
    """A live FMCSA publish (53,156 documents) aborted outright: exactly three
    objects, e.g. FMCSA-2007-0006-0015, carry ``postedDate: null`` with
    ``modifyDate`` present, and the strict date parse raised for the whole
    agency instead of treating one undatable document as evidence-only
    (2026-09-02 fix). A null ``postedDate`` is outside every date scope, the
    same disposition as any other out-of-scope object: it stays in evidence
    and contributes no record, and the dated documents still publish.
    """
    dated = _document_object()
    undated_record = _document("EPA-2026-0001-0002", postedDate=None)
    undated = _document_object(
        "EPA-2026-0001-0002",
        value=undated_record,
        etag='"undated-etag"',
    )
    release = tmp_path / "undated"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([dated, undated]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)
    pages = payload_rows(release, "acquisition-pages")

    assert [row["sourceRecordId"] for row in reader.iter_records()] == ["EPA-2026-0001-0001"]
    assert [row["recordsIncluded"] for row in pages] == [True]
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    with store.open(pages[0]["evidenceBlobRef"]) as stream:
        parsed = parse_document_page_response(stream.read())
    assert [item["included"] for item in parsed["_packedRecords"]] == [True, False]
    undated_evidence = parsed["_packedRecords"][1]["record"]
    assert undated_evidence["data"]["id"] == "EPA-2026-0001-0002"
    assert undated_evidence["data"]["attributes"]["postedDate"] is None


def test_malformed_posted_date_document_stays_in_evidence_without_aborting_the_agency(
    tmp_path: Path,
) -> None:
    """A live FAA full-history publish (205,696 documents) aborted outright
    nine minutes in: one document carries a non-null ``postedDate`` that
    fails canonical-date parsing, and the strict date parse raised for the
    whole agency instead of treating one unusable document as evidence-only
    (2026-09-02 fix). A malformed ``postedDate`` gets the same disposition as
    a null one: it stays in evidence, contributes no record, and the dated
    documents still publish.
    """
    dated = _document_object()
    malformed_record = _document("EPA-2026-0001-0002", postedDate="not-a-date")
    malformed = _document_object(
        "EPA-2026-0001-0002",
        value=malformed_record,
        etag='"malformed-etag"',
    )
    release = tmp_path / "malformed"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([dated, malformed]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)
    pages = payload_rows(release, "acquisition-pages")

    assert [row["sourceRecordId"] for row in reader.iter_records()] == ["EPA-2026-0001-0001"]
    assert [row["recordsIncluded"] for row in pages] == [True]
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    with store.open(pages[0]["evidenceBlobRef"]) as stream:
        parsed = parse_document_page_response(stream.read())
    assert [item["included"] for item in parsed["_packedRecords"]] == [True, False]
    malformed_evidence = parsed["_packedRecords"][1]["record"]
    assert malformed_evidence["data"]["id"] == "EPA-2026-0001-0002"
    assert malformed_evidence["data"]["attributes"]["postedDate"] == "not-a-date"


def test_missing_or_changed_enumerated_object_refuses_complete_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquisition, "MAX_EVIDENCE_PACK_OBJECTS", 1)
    pages = list(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([_document_object(), _document_object("EPA-2026-0001-0002")]),
            query_scope=_document_scope(),
        )
    )
    assert len(pages) == 2
    with pytest.raises(RegulationsGovSourceError, match="missing a terminal pack"):
        SourceNativeReleasePublisher(
            REGULATIONS_GOV_DOCUMENT_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            pages[:1],
            build=_build(_document_scope()),
            destination=tmp_path / "missing",
        )

    changed_request = pages[1].request_key.replace("terminal=true", "terminal=false")
    changed_page = RegulationsGovPage(
        traversal_index=0,
        page_index=1,
        window_index=1,
        window_page_index=0,
        request_key=changed_request,
        source_cursor=None,
        response_bytes=pages[1].response_bytes,
    )
    with pytest.raises(RegulationsGovSourceError, match="request differs from its evidence"):
        SourceNativeReleasePublisher(
            REGULATIONS_GOV_DOCUMENT_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            [pages[0], changed_page],
            build=_build(_document_scope()),
            destination=tmp_path / "changed",
        )


@pytest.mark.parametrize(
    "key_suffix",
    ["", "(1)", "(1)(2)(3)(4)(5)(6)(7)(8)(9)(10)(11)(12)"],
    ids=["no-suffix", "single-refetch-suffix", "twelve-stacked-refetch-suffixes"],
)
def test_key_identity_matching_body_admits_refetch_suffixes(key_suffix: str) -> None:
    """The key decides which agency and collection an object is admitted
    into; the body decides what it is. A refetch suffix is key-only
    bookkeeping -- Mirrulations appends one ``(N)`` group per refetch of the
    same object without deleting the earlier copy, and a BIS document
    (sampled 2026-09-02) carries twelve stacked groups -- so it must not
    stop the key's claimed identity from matching the body's once every
    trailing group is stripped.
    """
    refetched = _document_object(key_suffix=key_suffix)
    pages = list(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([refetched]),
            query_scope=_document_scope(),
        )
    )
    parsed = parse_document_page_response(pages[-1].response_bytes)
    assert [item["record"]["data"]["id"] for item in parsed["_packedRecords"]] == ["EPA-2026-0001-0001"]
    assert [item["included"] for item in parsed["_packedRecords"]] == [True]


def test_key_identity_mismatched_body_refuses_naming_both_key_and_identity() -> None:
    """An object filed under one key whose body declares a different
    identity must be refused outright -- admitting it would let the key
    decide which agency and collection it lands in while the body silently
    substitutes what it is.
    """
    key = "raw-data/EPA/EPA-2026-0001/text-1/documents/EPA-2026-0001-0001.json"
    mismatched = _document_object(
        "EPA-2026-0001-0001",
        value=_document("EPA-2026-0001-0099"),
    )
    assert mismatched.key == key
    with pytest.raises(RegulationsGovSourceError) as excinfo:
        list(
            iter_regulations_gov_document_pages(
                lambda _agency: _Reader([mismatched]),
                query_scope=_document_scope(),
            )
        )
    assert key in str(excinfo.value)
    assert "EPA-2026-0001-0099" in str(excinfo.value)


def test_docket_key_identity_mismatched_body_refuses() -> None:
    """The same key-versus-body identity check applies to dockets: the
    admission logic is shared across collections, not document-specific.
    """
    key = "raw-data/EPA/EPA-2026-0001/text-1/docket/EPA-2026-0001.json"
    mismatched = _docket_object(
        "EPA-2026-0001",
        value=_docket("EPA-2026-9999"),
    )
    assert mismatched.key == key
    with pytest.raises(RegulationsGovSourceError) as excinfo:
        list(
            iter_regulations_gov_docket_pages(
                lambda _agency: _Reader([mismatched]),
                query_scope=_docket_scope(),
            )
        )
    assert key in str(excinfo.value)
    assert "EPA-2026-9999" in str(excinfo.value)
