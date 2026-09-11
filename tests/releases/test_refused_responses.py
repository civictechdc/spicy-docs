"""A refused acquisition leaves exact diagnostic bytes, never a partial release."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import httpx
import pytest
from rulespec_artifacts import describe_member_from_receipt

from examples.offline_release import FIXED_NOW, HTML, PRODUCT_ID, PRODUCT_URL, capture
from spicy_docs.cli.source_native import main
from spicy_docs.releases import indexing, refusals
from spicy_docs.releases.publish import SourceNativeReleasePublisher
from spicy_docs.sources.federal_register.native import FederalRegisterSourceError
from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from spicy_docs.transport.acquisition import fetch_federal_register
from tests.releases.fixtures import (
    FEDERAL_REGISTER_PROFILE,
    IMPLEMENTATION_ID,
    _build,
    _completed_at,
    _document,
    _page,
    _publish,
)
from tests.source_fixtures import federal_response


def _report(error: Exception) -> dict:
    report = getattr(error, "failed_acquisition", None)
    assert isinstance(report, dict)
    return report


def _read_response(tmp_path: Path, error: Exception) -> bytes:
    response = _report(error)["response"]
    assert response["status"] == "retained"
    with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(response["blobRef"]) as stream:
        payload = stream.read()
    assert len(payload) == response["byteSize"]
    assert response["blobRef"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert not (tmp_path / "release").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blobs"]
    return payload


@pytest.mark.parametrize("payload", [b"\xffinvalid JSON", b'{"results":[]}'])
def test_shared_parse_refusal_retains_exact_bytes(tmp_path: Path, payload: bytes) -> None:
    with pytest.raises(FederalRegisterSourceError) as raised:
        _publish(tmp_path, [_page(0, 0, payload)])
    assert _read_response(tmp_path, raised.value) == payload
    assert _report(raised.value)["response"]["stage"] == "page-validation"


def test_page_bytes_are_stored_before_parser_and_original_error_survives(tmp_path: Path) -> None:
    payload = b"publisher changed this page"
    ref = "sha256:" + hashlib.sha256(payload).hexdigest()
    original = FederalRegisterSourceError("the parser's original diagnosis")
    cause = UnicodeError("original cause")

    def parse(raw: bytes):
        with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(ref) as stream:
            assert stream.read() == raw == payload
        raise original from cause

    with pytest.raises(FederalRegisterSourceError) as raised:
        _publish(tmp_path, [_page(0, 0, payload)], profile=replace(FEDERAL_REGISTER_PROFILE, parse_page_response=parse))
    assert raised.value is original
    assert raised.value.__cause__ is cause
    assert str(raised.value) == "the parser's original diagnosis"
    assert _read_response(tmp_path, original) == payload


def test_inventory_refusal_retains_page_that_cannot_prove_its_count(tmp_path: Path) -> None:
    payload = federal_response(_document(), count=2, total_pages=1)
    with pytest.raises(FederalRegisterSourceError, match="declared and observed record counts") as raised:
        _publish(tmp_path, [_page(0, 0, payload)])
    assert _read_response(tmp_path, raised.value) == payload


def test_iterator_failure_does_not_misidentify_previous_success_as_refused(tmp_path: Path) -> None:
    payload = federal_response(_document())
    original = OSError("next response unavailable")

    def pages():
        yield _page(0, 0, payload)
        raise original

    with pytest.raises(OSError) as raised:
        _publish(tmp_path, pages())
    assert raised.value is original
    report = _report(original)
    assert report["response"] == {"status": "not-retained", "reason": "response-unavailable"}
    context = report["retainedPageEvidence"]
    assert context["contextOnly"] is True
    assert context["count"] == 1
    assert context["truncated"] is False
    with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(
        context["references"][0]["blobRef"]
    ) as stream:
        assert stream.read() == payload
    assert not (tmp_path / "release").exists()


def test_oversized_page_is_reported_without_retaining_a_prefix(tmp_path: Path, monkeypatch) -> None:
    assert indexing.MAX_EVIDENCE_BYTES == refusals.MAX_EVIDENCE_BYTES
    monkeypatch.setattr(indexing, "MAX_EVIDENCE_BYTES", 3)
    monkeypatch.setattr(refusals, "MAX_EVIDENCE_BYTES", 3)
    with pytest.raises(ValueError, match="evidence bound") as raised:
        _publish(tmp_path, [_page(0, 0, b"1234")])
    report = _report(raised.value)["response"]
    assert report["status"] == "not-retained"
    assert report["reason"] == "response-byte-limit"
    assert report["byteSize"] == 4
    assert "blobRef" not in report
    assert not any(path.is_file() for path in (tmp_path / "blobs").rglob("*"))


def test_diagnostic_storage_failure_keeps_original_source_error(tmp_path: Path) -> None:
    original = FederalRegisterSourceError("unreadable publisher body")
    attach_refused_response(original, RefusedResponse(PRODUCT_URL, "source-validation", b"bad body", "text/html"))

    class FailingStore(LocalSourceNativeBlobStore):
        def put_blob(self, blob_ref, byte_size, chunks):
            raise OSError("diagnostic write failed api_key=secret")

    def pages():
        raise original
        yield  # pragma: no cover - keep this an acquisition iterator

    publisher = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE, blob_store=FailingStore(tmp_path / "blobs"), clock=_completed_at
    )
    with pytest.raises(FederalRegisterSourceError) as raised:
        publisher.publish(pages(), build=_build(), destination=tmp_path / "release")
    assert raised.value is original
    report = _report(original)["response"]
    assert report["reason"] == "storage-failed"
    assert report["status"] == "not-retained"
    assert "secret" not in json.dumps(report)
    assert "blobRef" not in report
    assert [path.name for path in tmp_path.iterdir()] == ["blobs"]


def test_error_report_bounds_context_and_scrubs_request_before_truncation(tmp_path: Path) -> None:
    original = ValueError("source failure")
    request = "https://publisher.test/?api_key=" + "secret" * 1000
    attach_refused_response(original, RefusedResponse(request, "transport", None, "text/html", "transport-unavailable"))
    members = {}
    for index in range(10):
        ref = "sha256:" + hashlib.sha256(str(index).encode()).hexdigest()
        members[ref] = describe_member_from_receipt(
            blob_ref=ref, role="evidence", media_type="application/json", byte_size=1, record_count=0
        )
    refusals.record_failed_acquisition(
        original,
        source_system_id="test",
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        evidence_members=members,
    )
    report = _report(original)
    assert report["retainedPageEvidence"]["count"] == 10
    assert len(report["retainedPageEvidence"]["references"]) == 8
    assert report["retainedPageEvidence"]["truncated"] is True
    assert report["response"]["requestKey"] == "https://publisher.test/?api_key=<redacted>"
    assert "secret" not in json.dumps(report)


def test_cli_gao_refusal_exposes_exact_body_for_offline_diagnosis(tmp_path: Path) -> None:
    raw = HTML.replace(b"/topics/information-security", b"/not-a-topic")
    errors, output = StringIO(), StringIO()
    status = main(
        [
            "publish",
            "--source",
            "gao-product-pages",
            "--product-id",
            PRODUCT_ID,
            "--destination",
            str(tmp_path / "release"),
            "--blob-store",
            str(tmp_path / "blobs"),
            "--implementation-id",
            IMPLEMENTATION_ID,
        ],
        fetch_gao=lambda url: replace(capture(url), body=raw),
        clock=lambda: FIXED_NOW,
        stdout=output,
        stderr=errors,
    )
    assert status == 1
    assert output.getvalue() == ""
    result = json.loads(errors.getvalue())
    assert result["error"]["code"] == "acquisition-failed"
    assert result["ok"] is False
    response = result["failedAcquisition"]["response"]
    assert response["status"] == "retained"
    with LocalSourceNativeBlobStore(tmp_path / "blobs", create=False).open(response["blobRef"]) as stream:
        assert stream.read() == raw
    assert not (tmp_path / "release").exists()


def test_cli_scrubs_http_error_url_and_failed_response_request_key(tmp_path: Path) -> None:
    secret = "secret-from-the-publisher-cursor"
    next_url = "https://www.federalregister.gov/api/v1/documents?format=json&page=2&api_key=" + secret
    first = federal_response(_document(), count=2, total_pages=2, next_page_url=next_url)

    def respond(request: httpx.Request) -> httpx.Response:
        if str(request.url) == next_url:
            return httpx.Response(404, request=request)
        return httpx.Response(200, content=first, request=request)

    errors = StringIO()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        status = main(
            [
                "publish",
                "--source",
                "federal-register",
                "--since",
                "2026-08-25",
                "--until",
                "2026-08-25",
                "--destination",
                str(tmp_path / "release"),
                "--blob-store",
                str(tmp_path / "blobs"),
                "--implementation-id",
                IMPLEMENTATION_ID,
            ],
            fetch=lambda url: fetch_federal_register(client, url),
            clock=lambda: FIXED_NOW,
            stdout=StringIO(),
            stderr=errors,
        )
    assert status == 1
    assert secret not in errors.getvalue()
    report = json.loads(errors.getvalue())
    assert report["error"]["code"] == "transport-failed"
    assert "api_key=<redacted>" in report["error"]["message"]
    assert report["failedAcquisition"]["response"]["requestKey"].endswith("api_key=<redacted>")
    assert report["failedAcquisition"]["response"]["status"] == "not-retained"
    assert report["failedAcquisition"]["retainedPageEvidence"]["count"] == 1
    assert not (tmp_path / "release").exists()
