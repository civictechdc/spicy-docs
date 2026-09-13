"""Regulations Gov: release behavior."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.regulations_gov_source_native import (
    DOCKET_SOURCE_SYSTEM_ID,
    DOCUMENT_SOURCE_SYSTEM_ID,
    classify_docket,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.source_native import (
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    verify_source_native_release,
)
from spicy_docs.source_native_profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
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


def test_document_json_renditions_survive_publication_and_retained_replay(tmp_path: Path) -> None:
    raw = _document(
        fileFormats=[
            {"fileUrl": "https://example.test/download", "format": "JSON", "size": 10},
            {"fileUrl": "https://example.test/data.json?download=1#table", "format": None},
            {"fileUrl": "https://example.test/path.xml/child", "format": None},
        ]
    )
    raw["included"][0]["attributes"]["fileFormats"] = [
        {"fileUrl": "https://example.test/attachment", "format": "json"},
    ]
    blob_store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=blob_store,
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([_document_object(value=raw)]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=tmp_path / "documents",
    )
    reader = _reader(published.root, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)
    assert next(iter(reader.iter_records()))["record"] == raw
    rows = {row["sourceField"]: row for row in reader.iter_renditions()}
    assert [rows[f"data.attributes.fileFormats[{index}]"]["mediaType"] for index in range(3)] == [
        "application/json",
        "application/json",
        "application/octet-stream",
    ]
    assert rows["included[0].attributes.fileFormats[0]"]["mediaType"] == "application/json"
    assert reader.collection_outcome["acquisitionPolicyVersion"] == "1.2"
    assert (
        reader.collection_outcome["acquisitionPolicy"]["renditions"]["mediaType"]["aliases"]["json"]
        == "application/json"
    )
    verify_source_native_release(
        published.artifact,
        LocalMemberSource(published.root),
        profile=REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_source=blob_store,
    )


def test_document_admission_refuses_the_prior_media_type_policy(tmp_path: Path) -> None:
    old_profile = replace(REGULATIONS_GOV_DOCUMENT_PROFILE, acquisition_policy_version="1.1")
    published = SourceNativeReleasePublisher(
        old_profile,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_document_pages(
            lambda _agency: _Reader([_document_object()]),
            query_scope=_document_scope(),
        ),
        build=_build(_document_scope()),
        destination=tmp_path / "documents",
    )
    with pytest.raises(SourceNativeReleaseError, match="requires current .* policy version"):
        _reader(published.root, published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)
