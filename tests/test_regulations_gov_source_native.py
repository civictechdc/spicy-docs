"""Regulations.gov source-native facts and exact acquisition evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource, Producer

from spicy_docs import regulations_gov_source_native
from spicy_docs.regulations_gov_source_native import (
    DOCKET_COLLECTION,
    DOCKET_SOURCE_SYSTEM_ID,
    DOCUMENT_COLLECTION,
    DOCUMENT_SOURCE_SYSTEM_ID,
    DOCUMENT_TIE_VOLATILE_FIELDS,
    MAX_QUERY_DAYS,
    RegulationsGovPage,
    RegulationsGovSourceError,
    classify_docket,
    classify_document,
    docket_acquisition_policy,
    docket_source_record_digest,
    document_acquisition_policy,
    document_rendition_rows,
    document_source_record_digest,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
    observation_version,
    parse_document_page_response,
    parse_mirrulations_request,
    regulations_gov_docket_query_scope,
    regulations_gov_document_query_scope,
    source_issued_version,
)
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native_profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

_IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
_PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=_IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="1.0",
    verifier_implementation_id=_IMPLEMENTATION_ID,
)


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


def _document(identity: str = "EPA-2026-0001-0001", **attributes: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "additionalRins": ["2060-AV12", "source-value-that-is-not-a-rin"],
        "agencyId": "EPA",
        "commentEndDate": None,
        "docketId": "EPA-2026-0001",
        "documentType": "Notice",
        "fileFormats": [
            {
                "fileUrl": f"https://downloads.regulations.gov/{identity}/content.pdf",
                "format": "pdf",
                "size": 123,
            },
            {
                "fileUrl": f"https://downloads.regulations.gov/{identity}/notice.xml",
                "format": "xml",
                "size": None,
            },
        ],
        "frDocNum": "2026-10001",
        "modifyDate": "2026-08-25T01:02:03Z",
        "postedDate": "2026-08-24T04:00:00Z",
        "reasonWithdrawn": "Issued in error",
        "subtype": None,
        "title": "Exact source title",
        "topics": ["Air quality", {"id": "source-topic", "label": "Source topic"}],
        "withdrawn": True,
    }
    values.update(attributes)
    return {
        "data": {
            "id": identity,
            "type": DOCUMENT_COLLECTION,
            "attributes": values,
            "links": {"self": f"https://api.regulations.gov/v4/documents/{identity}"},
        },
        "included": [
            {
                "id": f"{identity}-attachment-1",
                "type": "attachments",
                "attributes": {
                    "description": None,
                    "fileFormats": [
                        {
                            "fileUrl": (f"https://downloads.regulations.gov/{identity}/attachment.docx"),
                            "format": "docx",
                            "size": "99",
                        }
                    ],
                    "title": "Supporting attachment",
                },
            }
        ],
        "meta": {"hasMore": False, "totalElements": 1},
    }


def _docket(identity: str = "EPA-2026-0001", **attributes: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "agencyId": "EPA",
        "category": None,
        "displayProperties": [{"name": "abstract", "label": "Description", "tooltip": None}],
        "dkAbstract": "Exact docket abstract",
        "docketType": "Rulemaking",
        "keywords": ["air", "emissions"],
        "modifyDate": "2026-08-24T05:00:00Z",
        "rin": None,
        "title": "Exact docket title",
    }
    values.update(attributes)
    return {
        "data": {
            "id": identity,
            "type": DOCKET_COLLECTION,
            "attributes": values,
            "links": {"self": f"https://api.regulations.gov/v4/dockets/{identity}"},
        }
    }


def _bytes(value: object, *, indent: int | None = None) -> bytes:
    return json.dumps(value, indent=indent, separators=None if indent else (",", ":")).encode()


@dataclass(frozen=True, slots=True)
class _Object:
    key: str
    etag: str
    version_id: str | None
    content: bytes


class _Reader:
    def __init__(self, objects: list[_Object], calls: list[tuple[str, int]] | None = None) -> None:
        self.objects = objects
        self.calls = calls

    def iter_source_objects(self, *, max_bytes: int) -> Iterator[_Object]:
        if self.calls is not None:
            self.calls.append(("iter", max_bytes))
        yield from self.objects


def _document_object(
    identity: str = "EPA-2026-0001-0001",
    *,
    value: dict[str, Any] | None = None,
    etag: str = '"document-etag"',
    tag: str = "1",
    agency: str = "EPA",
    docket_id: str = "EPA-2026-0001",
    key_suffix: str = "",
) -> _Object:
    return _Object(
        key=(f"raw-data/{agency}/{docket_id}/text-{tag}/documents/{identity}{key_suffix}.json"),
        etag=etag,
        version_id="document-version-1",
        content=_bytes(value or _document(identity), indent=2),
    )


def _docket_object(
    identity: str = "EPA-2026-0001",
    *,
    value: dict[str, Any] | None = None,
    etag: str = '"docket-etag"',
    tag: str = "1",
    agency: str = "EPA",
    key_suffix: str = "",
) -> _Object:
    return _Object(
        key=f"raw-data/{agency}/{identity}/text-{tag}/docket/{identity}{key_suffix}.json",
        etag=etag,
        version_id=None,
        content=_bytes(value or _docket(identity), indent=2),
    )


def _document_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "publishedFrom": "2026-08-24",
        "publishedThrough": "2026-08-24",
    }


def _docket_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "modifiedFrom": "2026-08-24",
        "modifiedThrough": "2026-08-24",
    }


def _build(query_scope: dict[str, object]) -> SourceNativeReleaseBuild:
    return SourceNativeReleaseBuild(
        query_scope=query_scope,
        producer=_PRODUCER,
        started_at="2026-08-25T00:00:00Z",
    )


def _reader(root: Path, pin, profile) -> SourceNativeReleaseReader:
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(root.parent / "blobs"),
        profile=profile,
        expected_pin=pin,
        accepted_verifier_implementation_ids=frozenset({_IMPLEMENTATION_ID}),
    )


def _payload_rows(root: Path, partition_kind: str) -> list[dict[str, Any]]:
    receipt = json.loads((root / "receipts/publication.json").read_bytes())
    store = LocalSourceNativeBlobStore(root.parent / "blobs")
    rows: list[dict[str, Any]] = []
    for partition in receipt["payloadPartitions"]:
        if partition["partitionKind"] != partition_kind:
            continue
        with store.open(partition["blobRef"]) as stream:
            rows.extend(json.loads(line) for line in stream)
    return rows


def test_document_record_preserves_source_facts_and_join_keys_without_prejoining() -> None:
    raw = _document()

    assert classify_document(raw) == raw
    attributes = raw["data"]["attributes"]
    assert attributes["docketId"] == "EPA-2026-0001"
    assert attributes["frDocNum"] == "2026-10001"
    assert attributes["topics"] == [
        "Air quality",
        {"id": "source-topic", "label": "Source topic"},
    ]
    assert attributes["withdrawn"] is True
    assert attributes["reasonWithdrawn"] == "Issued in error"
    assert "docket" not in raw and "federalRegister" not in raw
    assert raw["meta"]["hasMore"] is False


def test_document_renditions_preserve_all_file_format_evidence() -> None:
    rows = document_rendition_rows(classify_document(_document()))

    assert [row["sourceField"] for row in rows] == [
        "data.attributes.fileFormats[0]",
        "data.attributes.fileFormats[1]",
        "included[0].attributes.fileFormats[0]",
    ]
    assert [row["mediaType"] for row in rows] == [
        "application/pdf",
        "application/xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    assert [row["expectedByteSize"] for row in rows] == [123, None, 99]
    assert all(row["expectedSha256"] is None for row in rows)


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


def test_document_release_uses_one_source_enumeration_and_replays_exact_bytes(
    tmp_path: Path,
) -> None:
    source_object = _document_object()
    release = tmp_path / "documents"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([source_object]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=release,
    )
    reader = _reader(
        release,
        published.artifact.pin,
        REGULATIONS_GOV_DOCUMENT_PROFILE,
    )

    assert reader.source_system_id == DOCUMENT_SOURCE_SYSTEM_ID
    assert reader.source_state_scope == "complete-snapshot"
    assert next(iter(reader.iter_records()))["record"] == _document()
    assert len(list(reader.iter_renditions())) == 3
    receipt = json.loads((release / "receipts/publication.json").read_bytes())
    assert receipt["reconciliationPassCount"] == 1
    assert receipt["acquisitionEvidenceCount"] == 1
    assert not (release / "evidence").exists()

    with pytest.raises(SourceNativeReleaseError, match="unsupported Regulations.gov dockets"):
        _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCKET_PROFILE)


def test_docket_release_is_separate_and_preserves_docket_source_facts(tmp_path: Path) -> None:
    raw = _docket()
    source_object = _docket_object(value=raw)
    release = tmp_path / "dockets"
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCKET_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_docket_pages(
            lambda _agency: _Reader([source_object]),
            query_scope=_docket_scope(),
        ),
        build=_build(_docket_scope()),
        destination=release,
    )
    reader = _reader(release, published.artifact.pin, REGULATIONS_GOV_DOCKET_PROFILE)

    assert classify_docket(raw) == raw
    assert reader.source_system_id == DOCKET_SOURCE_SYSTEM_ID
    assert next(iter(reader.iter_records()))["record"] == raw
    assert list(reader.iter_renditions()) == []


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
    pages = _payload_rows(release, "acquisition-pages")

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
    pages = _payload_rows(release, "acquisition-pages")

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
    pages = _payload_rows(release, "acquisition-pages")

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
    monkeypatch.setattr(regulations_gov_source_native, "MAX_EVIDENCE_PACK_OBJECTS", 1)
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
    ("mutate", "message"),
    [
        (lambda value: value.update({"newTopLevel": None}), "record fields"),
        (
            lambda value: value["data"]["attributes"].update({"newAttribute": None}),
            "attributes fields",
        ),
        (
            lambda value: value["data"]["attributes"]["fileFormats"][0].update({"newFormatFact": None}),
            "fileFormats.*fields",
        ),
        (
            lambda value: value["included"][0]["attributes"].update({"newAttachmentFact": None}),
            "attachment attributes fields",
        ),
    ],
)
def test_document_schema_drift_fails_closed(mutate, message: str) -> None:
    raw = deepcopy(_document())
    mutate(raw)
    with pytest.raises(RegulationsGovSourceError, match=message):
        classify_document(raw)


def test_strict_ascii_ids_and_keys_make_declared_order_unambiguous() -> None:
    with pytest.raises(RegulationsGovSourceError, match="strict ASCII"):
        classify_document(_document("EPA-2026-0001-000é"))
    invalid = _Object(
        key="raw-data/EPA/EPA-2026/text-1/documents/é.json",
        etag='"etag"',
        version_id=None,
        content=_bytes(_document()),
    )
    with pytest.raises(RegulationsGovSourceError, match="object key"):
        list(
            iter_regulations_gov_document_pages(
                lambda _agency: _Reader([invalid]),
                query_scope=_document_scope(),
            )
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


@pytest.mark.parametrize(
    ("scope", "validator", "message"),
    [
        (
            {
                "agencies": ["EPA", "EPA"],
                "publishedFrom": "2026-08-24",
                "publishedThrough": "2026-08-24",
            },
            regulations_gov_document_query_scope,
            "sorted, and distinct",
        ),
        (
            {
                "agencies": ["EPA"],
                "modifiedFrom": "2026-08-25",
                "modifiedThrough": "2026-08-24",
            },
            regulations_gov_docket_query_scope,
            "reversed",
        ),
        (
            {
                "agencies": ["EPA"],
                # MAX_QUERY_DAYS is ~40 years (regulations.gov/FDMS source
                # history begins in the 1990s); this span exceeds it.
                "publishedFrom": "1900-01-01",
                "publishedThrough": "2026-08-24",
            },
            regulations_gov_document_query_scope,
            "date bound",
        ),
    ],
)
def test_query_scopes_are_closed_ascii_and_bounded(scope, validator, message: str) -> None:
    with pytest.raises(RegulationsGovSourceError, match=message):
        validator(scope)


def test_query_scope_spans_a_full_source_history_up_to_the_inclusive_bound() -> None:
    """One window per agency must cover a source's whole history (2026-09-02
    amendment); the superseded 366-day bound refused every such scope.
    """
    start = date(1990, 1, 1)
    full_history = regulations_gov_document_query_scope(
        {"agencies": ["EPA"], "publishedFrom": start.isoformat(), "publishedThrough": "2026-09-02"}
    )
    assert full_history["publishedFrom"] == "1990-01-01"
    assert full_history["publishedThrough"] == "2026-09-02"

    def scope(inclusive_days: int) -> dict[str, object]:
        through = start + timedelta(days=inclusive_days - 1)
        return {"agencies": ["EPA"], "publishedFrom": start.isoformat(), "publishedThrough": through.isoformat()}

    assert MAX_QUERY_DAYS == 14_640
    widest = regulations_gov_document_query_scope(scope(MAX_QUERY_DAYS))
    assert widest["publishedThrough"] == "2030-01-30"  # 1990-01-01 + 14,639 days
    with pytest.raises(RegulationsGovSourceError, match="date bound"):
        regulations_gov_document_query_scope(scope(MAX_QUERY_DAYS + 1))

    # The bound is a sealed acquisition-policy member, not just a guard.
    assert document_acquisition_policy(_document_scope())["maxQueryDays"] == 14_640


def _acf_docket_scope() -> dict[str, object]:
    return {
        "agencies": ["ACF"],
        "modifiedFrom": "2021-01-01",
        "modifiedThrough": "2024-12-31",
    }


def _acf_document_scope() -> dict[str, object]:
    return {
        "agencies": ["ACF"],
        "publishedFrom": "2021-01-01",
        "publishedThrough": "2024-12-31",
    }


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
    discovered = [record for row in _payload_rows(release, "acquisition-pages") for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [identity, identity]
    assert len({record["recordDigest"] for record in discovered}) == 2


def _reordered(value: Any) -> Any:
    """Rebuild a JSON-decodable value with every mapping's keys reversed.

    Content-equal to ``value`` — a JSON parser decodes the identical record
    either way — but serializing this alongside the original produces two
    byte-different encodings of that one record, proving the collapse keys
    equality on the canonical record digest, not raw bytes.
    """
    if isinstance(value, dict):
        return {key: _reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reordered(item) for item in value]
    return value


@dataclass(frozen=True)
class _CollapseFixture:
    collection: str
    profile: Any
    scope: dict[str, object]
    identity: str
    iter_pages: Callable[..., Iterator[RegulationsGovPage]]
    record_digest: Callable[[Mapping[str, Any]], str]
    older: dict[str, Any]
    newest: dict[str, Any]
    build_object: Callable[..., _Object]


def _docket_collapse_fixture() -> _CollapseFixture:
    identity = "ACF-2007-0125"
    return _CollapseFixture(
        collection="docket",
        profile=REGULATIONS_GOV_DOCKET_PROFILE,
        scope=_acf_docket_scope(),
        identity=identity,
        iter_pages=iter_regulations_gov_docket_pages,
        record_digest=docket_source_record_digest,
        older=_docket(identity, agencyId="ACF", modifyDate="2021-02-12T01:00:50Z", title="older observation"),
        newest=_docket(identity, agencyId="ACF", modifyDate="2024-06-12T01:16:04Z", title="newest observation"),
        build_object=lambda *, value, tag: _docket_object(identity, value=value, tag=tag, agency="ACF"),
    )


def _document_collapse_fixture() -> _CollapseFixture:
    identity = "ACF-2021-0001-0001"
    return _CollapseFixture(
        collection="document",
        profile=REGULATIONS_GOV_DOCUMENT_PROFILE,
        scope=_acf_document_scope(),
        identity=identity,
        iter_pages=iter_regulations_gov_document_pages,
        record_digest=document_source_record_digest,
        older=_document(
            identity,
            agencyId="ACF",
            docketId="ACF-2021-0001",
            modifyDate="2021-03-01T00:00:00Z",
            postedDate="2021-02-15T00:00:00Z",
            title="older observation",
        ),
        newest=_document(
            identity,
            agencyId="ACF",
            docketId="ACF-2021-0001",
            modifyDate="2024-06-12T01:16:04Z",
            postedDate="2021-02-15T00:00:00Z",
            title="newest observation",
        ),
        build_object=lambda *, value, tag: _document_object(
            identity, value=value, tag=tag, agency="ACF", docket_id="ACF-2021-0001"
        ),
    )


@pytest.mark.parametrize(
    "fixture",
    [_docket_collapse_fixture(), _document_collapse_fixture()],
    ids=["docket", "document"],
)
def test_release_collapses_identical_record_digests_with_differing_raw_bytes(
    tmp_path: Path, fixture: _CollapseFixture
) -> None:
    """A live docket publish surfaced ACF-2026-0199 with two Mirrulations
    objects ("(18)" and "(19)") at one modifyDate instant — a re-fetch of one
    active docket, not a tie to refuse. Equality for the collapse is the
    canonical record digest, not raw bytes (2026-09-02 fix): this fixture
    proves it directly by serializing the second "newest" observation with
    reversed JSON key order, so its raw bytes differ from the first while its
    record digest is identical. Two observations of one record at one instant
    with equal record digests select one published record; every redundant
    input remains counted as a discarded observation and stays byte-exact in
    acquisition evidence, alongside the older, genuinely distinct
    observation.
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
            lambda agency: (_Reader(objects) if agency == "ACF" else pytest.fail("wrong agency")),
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

    pages = _payload_rows(release, "acquisition-pages")
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
                        _document_object(
                            identity, value=older, tag="1", agency="ACF", docket_id="ACF-2021-0001"
                        ),
                        _document_object(
                            identity, value=newer, tag="2", agency="ACF", docket_id="ACF-2021-0001"
                        ),
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


def _bis_document_scope() -> dict[str, object]:
    return {
        "agencies": ["BIS"],
        "publishedFrom": "2023-01-01",
        "publishedThrough": "2023-12-31",
    }


def _epa_hq_document_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "publishedFrom": "2024-01-01",
        "publishedThrough": "2024-12-31",
    }


def test_read_time_derived_field_only_difference_collapses_without_tying(tmp_path: Path) -> None:
    """A live agency fan-out lost BIS after 85 minutes on exactly this
    shape: BIS-2023-0021-0001 has two Mirrulations objects at one modifyDate
    instant (2023-10-13T01:04:10Z) whose only difference is
    ``openForComment`` -- a field regulations.gov computes at read time from
    commentStartDate/commentEndDate against "now", not a stored document
    fact, so a later refetch after the comment window closed flips it while
    the document's own modifyDate does not move. Two such observations
    collapse to one published record instead of refusing a tie (2026-09-02
    fix); every redundant observation still counts as discarded and stays in
    evidence. The mirror's own listing order is the only signal of fetch
    recency, so the last-listed object -- ``openForComment: True`` here --
    is the one published.
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
    discovered = [record for row in _payload_rows(release, "acquisition-pages") for record in row["discoveredRecords"]]
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


def test_document_source_issued_version_falls_back_to_posted_date_when_modify_date_is_null() -> None:
    raw = _document(modifyDate=None, postedDate="2026-08-24T04:00:00Z")

    assert source_issued_version(raw, collection=DOCUMENT_COLLECTION) == "2026-08-24T04:00:00Z"
    assert observation_version(raw, collection=DOCUMENT_COLLECTION) == "2026-08-24T04:00:00.000000Z"


@pytest.mark.parametrize(
    ("posted_date", "modify_date", "expected_version"),
    [
        (None, "2024-11-07T22:18:46Z", "2024-11-07T22:18:46.000000Z"),
        (None, None, None),
        ("not-a-date", "2024-11-07T22:18:46Z", "2024-11-07T22:18:46.000000Z"),
        ("not-a-date", None, None),
    ],
    ids=[
        "null-posted-date-modify-date-present",
        "null-posted-date-both-dates-null",
        "malformed-posted-date-modify-date-present",
        "malformed-posted-date-both-dates-unusable",
    ],
)
def test_classify_document_tolerates_an_unusable_posted_date(
    posted_date: str | None,
    modify_date: str | None,
    expected_version: str | None,
) -> None:
    """Three live FMCSA documents publish ``postedDate: null`` with
    ``modifyDate`` present, e.g. FMCSA-2007-0006-0015. A live FAA
    full-history publish (205,696 documents) later surfaced a document with a
    non-null ``postedDate`` that fails canonical-date parsing, and the strict
    parse aborted the whole agency nine minutes in (2026-09-02 fix): null and
    unparseable are both undatable, not corrupt, so classification tolerates
    either without coercing or repairing the raw value. A document whose
    ``postedDate`` is unusable but whose ``modifyDate`` is present still
    orders by ``modifyDate``; one where both are unusable has a null
    instant, which the collapse orders last rather than refusing.
    """
    record = classify_document(_document(postedDate=posted_date, modifyDate=modify_date))
    assert record["data"]["attributes"]["postedDate"] == posted_date
    assert observation_version(record, collection=DOCUMENT_COLLECTION) == expected_version


def test_docket_source_issued_version_matches_the_raw_modify_date() -> None:
    raw = _docket(modifyDate="2021-02-12T01:00:50Z")

    assert source_issued_version(raw, collection=DOCKET_COLLECTION) == "2021-02-12T01:00:50Z"
    assert observation_version(raw, collection=DOCKET_COLLECTION) == "2021-02-12T01:00:50.000000Z"


def test_an_unknown_collection_refuses_instead_of_raising_a_lookup_error() -> None:
    with pytest.raises(RegulationsGovSourceError, match="not a source-native collection"):
        source_issued_version(_docket(), collection="rulemakings")


def test_docket_and_document_acquisition_policies_declare_the_newest_observation_collapse() -> None:
    document_selection = document_acquisition_policy(_document_scope())["observationSelection"]
    assert document_selection == {
        "groupBy": "/data/id",
        "orderBy": "coalesce(/data/attributes/modifyDate, /data/attributes/postedDate) DESC NULLS LAST",
        "tieDisposition": "refuse-differing-record-digest-at-normalized-instant",
    }

    docket_selection = docket_acquisition_policy(_docket_scope())["observationSelection"]
    assert docket_selection == {
        "groupBy": "/data/id",
        "orderBy": "/data/attributes/modifyDate DESC NULLS LAST",
        "tieDisposition": "refuse-differing-record-digest-at-normalized-instant",
    }


def test_document_attribute_cfr_part_accepts_a_string_or_null_and_refuses_an_array() -> None:
    """The regulations.gov v4 API documents ``cfrPart`` as a string, and the
    live mirror carries only strings or nulls (sampled 2026-09-02, 120
    documents across ACF/FMCSA/SEC: 106 null, 14 str, 0 arrays) — never the
    text array the schema previously required.
    """
    textual = classify_document(_document(cfrPart="45 CFR 302,303,307"))
    assert textual["data"]["attributes"]["cfrPart"] == "45 CFR 302,303,307"

    null_valued = classify_document(_document(cfrPart=None))
    assert null_valued["data"]["attributes"]["cfrPart"] is None

    with pytest.raises(RegulationsGovSourceError, match="cfrPart must be text or null"):
        classify_document(_document(cfrPart=["45 CFR 302", "45 CFR 303"]))
