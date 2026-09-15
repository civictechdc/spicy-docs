"""Regulations Gov: records behavior."""

from __future__ import annotations

from copy import deepcopy

import pytest

from spicy_docs.source_native.regulations_gov import (
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    RegulationsGovSourceError,
    classify_document,
    document_rendition_rows,
    iter_regulations_gov_document_pages,
    observation_version,
    source_issued_version,
)
from tests.regulations_gov.fixtures import (
    _bytes,
    _docket,
    _document,
    _document_scope,
    _Object,
    _Reader,
)


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
    """Preserve null or unparseable postedDate values without repairing them.

    FMCSA and FAA records exhibit both shapes. Order by modifyDate when present;
    when it is null and postedDate is unusable, retain a null instant that sorts last.
    Malformed modifyDate values still refuse.
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
