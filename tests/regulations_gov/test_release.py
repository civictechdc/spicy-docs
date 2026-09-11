"""Regulations Gov: release behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
)
from spicy_docs.source_native_profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
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
