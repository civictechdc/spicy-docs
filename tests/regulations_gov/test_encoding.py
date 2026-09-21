"""Encoding contract: source values round-trip byte-exact (integers in the JSON-safe range, Unicode text,
nulls), while oversized, unsafe-key, non-bytes, float and duplicate-key objects are refused without a release --
retaining the exact captured bytes when bytes exist and reporting ``not-retained`` when they do not.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from rulespec_artifacts import ArtifactVerificationError

from spicy_docs.source_native import SourceNativeReleasePublisher
from spicy_docs.source_native.profiles import REGULATIONS_GOV_DOCUMENT_PROFILE
from spicy_docs.source_native.regulations_gov import (
    RegulationsGovSourceError,
    iter_regulations_gov_document_pages,
)
from spicy_docs.source_native.store import LocalSourceNativeBlobStore
from spicy_docs.sources.regulations_gov import acquisition
from tests.regulations_gov.fixtures import (
    _build,
    _completed_at,
    _document,
    _document_object,
    _document_scope,
    _Reader,
    _reader,
)

SAFE_INTEGER = 9007199254740991


def _publish(tmp_path: Path, source_object):
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    result = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE, blob_store=store, clock=_completed_at
    ).publish(
        iter_regulations_gov_document_pages(lambda _agency: _Reader([source_object]), query_scope=_document_scope()),
        build=_build(_document_scope()),
        destination=tmp_path / "documents",
    )
    return result, store


@pytest.mark.parametrize("size", [0, SAFE_INTEGER])
def test_source_values_round_trip_without_normalizing_text_or_numeric_strings(tmp_path: Path, size: int) -> None:
    source = _document(title=f"Café e\u0301 汉 😀 \u2028\u2029 {SAFE_INTEGER + 1}")
    formats = source["data"]["attributes"]["fileFormats"]
    formats[0]["size"] = size
    formats[1]["size"] = "000" + str(SAFE_INTEGER)
    original = _document_object(value=source)
    published, _ = _publish(tmp_path, original)
    reader = _reader(tmp_path / "documents", published.artifact.pin, REGULATIONS_GOV_DOCUMENT_PROFILE)

    (row,) = reader.iter_records()
    assert row["record"] == source
    assert row["record"]["data"]["attributes"]["withdrawn"] is True
    assert row["record"]["data"]["attributes"]["subtype"] is None
    evidence = reader.record_evidence(source["data"]["id"])
    assert evidence is not None
    with ZipFile(BytesIO(reader.read_evidence(evidence["evidenceBlobRef"]))) as archive:
        captured = [archive.read(name) for name in archive.namelist()]
    assert captured.count(original.content) == 1


@pytest.mark.parametrize(
    ("case", "error_type", "message"),
    [
        ("integer-too-large", ArtifactVerificationError, "outside the JSON safe range"),
        ("integer-too-small", ArtifactVerificationError, "outside the JSON safe range"),
        ("float", RegulationsGovSourceError, "unsupported float"),
        ("negative-zero", RegulationsGovSourceError, "unsupported float"),
        ("duplicate-key", RegulationsGovSourceError, "repeats field"),
        ("lone-surrogate", ArtifactVerificationError, "lone Unicode surrogate"),
        ("missing-etag", RegulationsGovSourceError, "lacks a source ETag"),
        ("wrong-identity", RegulationsGovSourceError, "does not match body identity"),
        ("empty", RegulationsGovSourceError, "bytes are invalid"),
    ],
)
def test_refused_source_objects_retain_exact_bytes_without_a_release(
    tmp_path: Path, case: str, error_type: type[Exception], message: str
) -> None:
    source = _document()
    if case in {"integer-too-large", "integer-too-small"}:
        source["meta"]["totalElements"] = (SAFE_INTEGER + 1) * (-1 if case == "integer-too-small" else 1)
    elif case in {"float", "negative-zero"}:
        source["meta"]["totalElements"] = 1.5 if case == "float" else -0.0
    elif case == "lone-surrogate":
        source["data"]["attributes"]["title"] = "\ud800"
    original = _document_object(value=source)
    if case == "duplicate-key":
        original = replace(
            original, content=original.content.replace(b'"hasMore": false', b'"hasMore": false, "hasMore": true')
        )
    elif case == "missing-etag":
        original = replace(original, etag="")
    elif case == "wrong-identity":
        original = replace(original, key=original.key.replace("0001-0001.json", "0001-0002.json"))
    elif case == "empty":
        original = replace(original, content=b"")

    with pytest.raises(error_type, match=message) as caught:
        _publish(tmp_path, original)

    assert not (tmp_path / "documents").exists()
    response = caught.value.failed_acquisition["response"]
    assert response["status"] == "retained"
    assert response["requestKey"] == original.key
    assert response["byteSize"] == len(original.content)
    with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(response["blobRef"]) as handle:
        assert handle.read() == original.content


def test_oversized_captured_object_reports_limit_without_retaining_body(tmp_path: Path, monkeypatch) -> None:
    original = _document_object()
    monkeypatch.setattr(acquisition, "MAX_OBJECT_BYTES", len(original.content) - 1)
    with pytest.raises(RegulationsGovSourceError, match="bytes are invalid") as caught:
        _publish(tmp_path, original)
    response = caught.value.failed_acquisition["response"]
    assert response["status"] == "not-retained"
    assert response["reason"] == "source-byte-limit"
    assert response["byteSize"] == len(original.content)
    assert not (tmp_path / "documents").exists()
    assert not list((tmp_path / "blobs" / "sha256").iterdir())


def test_unrepresentable_derived_size_refuses_without_altering_source_bytes(tmp_path: Path) -> None:
    source = _document()
    source["data"]["attributes"]["fileFormats"][0]["size"] = str(SAFE_INTEGER + 1)
    original = _document_object(value=source)
    with pytest.raises(ArtifactVerificationError, match="outside the JSON safe range") as caught:
        _publish(tmp_path, original)
    assert not (tmp_path / "documents").exists()
    response = caught.value.failed_acquisition["response"]
    assert response["status"] == "retained"
    assert response["mediaType"] == "application/zip"
    with (
        LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(response["blobRef"]) as handle,
        ZipFile(handle) as archive,
    ):
        assert [archive.read(name) for name in archive.namelist()].count(original.content) == 1


def test_refused_object_preserves_original_exception_instance(monkeypatch) -> None:
    original = _document_object()
    error = RegulationsGovSourceError("source classifier refusal")

    def refuse(_value):
        raise error

    monkeypatch.setattr(acquisition, "classify_document", refuse)
    pages = iter_regulations_gov_document_pages(lambda _agency: _Reader([original]), query_scope=_document_scope())
    with pytest.raises(RegulationsGovSourceError) as caught:
        next(pages)
    assert caught.value is error
    assert error.refused_response.response_bytes == original.content


@pytest.mark.parametrize("key", ["raw-data/EPA/汉.json", "raw-data/EPA/x\n.json", None])
def test_unsafe_object_key_uses_safe_pack_context(tmp_path: Path, key: object) -> None:
    original = replace(_document_object(), key=key)
    with pytest.raises(RegulationsGovSourceError, match="object keys") as caught:
        _publish(tmp_path, original)
    response = caught.value.failed_acquisition["response"]
    assert response["requestKey"] == (
        "mirrulations://regulations-gov/documents/pack?agency=EPA&packIndex=0&terminal=false"
    )
    assert response["status"] == "retained"
    with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(response["blobRef"]) as handle:
        assert handle.read() == original.content


def test_non_bytes_object_does_not_invent_response_evidence(tmp_path: Path) -> None:
    original = replace(_document_object(), content="not captured bytes")
    with pytest.raises(RegulationsGovSourceError, match="bytes are invalid") as caught:
        _publish(tmp_path, original)
    response = caught.value.failed_acquisition["response"]
    assert response["status"] == "not-retained"
    assert response["reason"] == "response-unavailable"
    assert "byteSize" not in response
    assert "blobRef" not in response
    assert not (tmp_path / "documents").exists()


def test_later_iterator_error_does_not_inherit_buffered_object_bytes(tmp_path: Path) -> None:
    original = _document_object()
    error = ValueError("later enumeration failed")

    class InterruptedReader:
        def iter_source_objects(self, *, max_bytes: int):
            yield original
            raise error

    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="later enumeration failed") as caught:
        SourceNativeReleasePublisher(REGULATIONS_GOV_DOCUMENT_PROFILE, blob_store=store, clock=_completed_at).publish(
            iter_regulations_gov_document_pages(lambda _agency: InterruptedReader(), query_scope=_document_scope()),
            build=_build(_document_scope()),
            destination=tmp_path / "documents",
        )
    assert caught.value is error
    assert not hasattr(error, "refused_response")
    assert error.failed_acquisition["response"] == {"status": "not-retained", "reason": "response-unavailable"}
    assert not (tmp_path / "documents").exists()
    assert not list((tmp_path / "blobs" / "sha256").iterdir())
