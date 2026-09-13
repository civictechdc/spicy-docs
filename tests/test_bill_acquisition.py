"""Prove bounded status-to-selected-text acquisition with retained responses."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.bill_acquisition import (
    BillAcquirer,
    BillAcquisitionBudget,
    BillSourceUnavailableError,
)
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError, bill_status_locator
from spicy_docs.sources.congress.bill_text import bill_xml_locator
from spicy_docs.transport import capture, retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
STATUS = (FIXTURES / "status-119hr6028.xml").read_bytes()
TEXT = (FIXTURES / "text-119hr6028eh.xml").read_bytes()
IDENTITY = BillIdentity(119, "hr", 6028)
PACKAGE = "BILLS-119hr6028eh"
BUDGET = BillAcquisitionBudget(3, 32 * 1024, 32 * 1024, 7, 0)
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def response(body=STATUS, status=200, *, content_type="text/xml", **headers):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type, **headers})


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_status_and_explicit_text_keep_exact_bytes_and_distinct_request_counts():
    transport = Transport(response(), response(TEXT))
    with BillAcquirer(budget=BUDGET, transport=transport, clock=lambda: NOW) as source:
        status = source.acquire_status(IDENTITY)
        text = source.acquire_text(status, package_id=PACKAGE)
    assert status.capture.body == STATUS and text.capture.body == TEXT
    assert status.status.identity == text.identity.identity == IDENTITY
    assert text.identity.package_id == PACKAGE
    assert status.request_count == text.request_count == 1
    assert status.capture.observed_at == text.capture.observed_at == "2026-09-12T00:00:00Z"
    assert text.capture.byte_size == len(TEXT)
    assert text.capture.sha256.startswith("sha256:")
    assert [str(request.url) for request in transport.calls] == [
        bill_status_locator(IDENTITY),
        bill_xml_locator(IDENTITY, PACKAGE),
    ]
    assert all(request.method == "GET" for request in transport.calls)


@pytest.mark.parametrize("http_status", [404, 410])
@pytest.mark.parametrize("operation", ["status", "text"])
def test_unavailable_locator_is_distinct_and_retains_response(http_status, operation):
    transport = Transport(*([response()] if operation == "text" else []), response(b"absent", http_status))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY) if operation == "text" else None
        with pytest.raises(BillSourceUnavailableError) as caught:
            if status is None:
                source.acquire_status(IDENTITY)
            else:
                source.acquire_text(status, package_id=PACKAGE)
    assert caught.value.capture.body == b"absent"
    assert caught.value.capture.status_code == http_status
    assert caught.value.refused_response.response_bytes == b"absent"
    assert caught.value.bill_acquisition["requestCount"] == 1


@pytest.mark.parametrize("http_status", [401, 403])
def test_access_refusal_aborts_once(http_status):
    transport = Transport(response(b"private", http_status))
    with (
        BillAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CredentialRefusedError) as caught,
    ):
        source.acquire_status(IDENTITY)
    assert len(transport.calls) == 1
    assert caught.value.refused_response.response_bytes is None


@pytest.mark.parametrize("http_status", [302, 400, 204])
def test_other_status_cannot_become_absence_or_a_document(http_status):
    transport = Transport(response(b"refused", http_status, location="https://example.invalid/"))
    with BillAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceError) as caught:
        source.acquire_status(IDENTITY)
    assert type(caught.value) is BillSourceError
    assert len(transport.calls) == 1
    assert caught.value.refused_response.response_bytes == b"refused"


@pytest.mark.parametrize("http_status", [429, 502])
def test_failed_text_retries_have_no_status_body_misattribution(http_status):
    transport = Transport(response(), response(b"temporary", http_status), response(b"temporary", http_status))
    with BillAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(RetryableHTTPStatusError) as caught:
            source.acquire_text(status, package_id=PACKAGE)
    assert len(transport.calls) == 3
    assert caught.value.bill_acquisition["requestCount"] == 2
    assert caught.value.refused_response.request_key == bill_xml_locator(IDENTITY, PACKAGE)
    assert caught.value.refused_response.response_bytes is None


@pytest.mark.parametrize(
    "body,media_type",
    [
        (b"", "text/xml"),
        (b"<html>challenge</html>", "text/xml"),
        (STATUS, "text/html"),
        (STATUS.replace(b"<number>6028", b"<number>1"), "text/xml"),
    ],
)
def test_wrong_status_shape_or_identity_retains_failed_source(body, media_type):
    transport = Transport(response(body, content_type=media_type))
    with BillAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceError) as caught:
        source.acquire_status(IDENTITY)
    assert caught.value.refused_response.response_bytes == body
    assert caught.value.refused_response.stage == "source-validation"


def test_unoffered_package_and_edited_status_refuse_before_text_request():
    transport = Transport(response())
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(BillSourceError, match="offered"):
            source.acquire_text(status, package_id="BILLS-119hr6028enr")
        altered = replace(status, status=replace(status.status, title="Edited title"))
        with pytest.raises(BillSourceError, match="retained XML") as caught:
            source.acquire_text(altered, package_id=PACKAGE)
    assert len(transport.calls) == 1
    assert caught.value.bill_acquisition["requestCount"] == 0
    assert caught.value.refused_response.stage == "status-validation"


@pytest.mark.parametrize(
    "body,media_type",
    [
        (b"<html>challenge</html>", "text/xml"),
        (TEXT, "application/pdf"),
        (TEXT.replace(b"6028 EH", b"6028 IH"), "text/xml"),
    ],
)
def test_wrong_text_format_or_version_refuses_without_fallback(body, media_type):
    transport = Transport(response(), response(body, content_type=media_type))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(BillSourceError) as caught:
            source.acquire_text(status, package_id=PACKAGE)
    assert len(transport.calls) == 2
    assert caught.value.refused_response.response_bytes == body


def test_narrower_caller_limit_applies_and_is_recorded_in_failure():
    transport = Transport(response(), response(TEXT))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(BillSourceError, match="byte bound") as caught:
            source.acquire_text(status, package_id=PACKAGE, max_bytes=len(TEXT) - 1)
    assert caught.value.bill_acquisition["budget"]["max_text_bytes"] == len(TEXT) - 1
    assert caught.value.refused_response.unavailable_reason == "response-byte-limit"


def test_narrower_success_limit_is_recorded_in_result():
    transport = Transport(response(), response(TEXT))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        text = source.acquire_text(status, package_id=PACKAGE, max_bytes=len(TEXT))
    assert text.budget.max_text_bytes == len(TEXT)


def test_pacing_covers_retry_then_separate_text_call(monkeypatch):
    current = [0.0]
    starts = []
    monkeypatch.setattr(capture.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(capture.time, "sleep", lambda delay: current.__setitem__(0, current[0] + delay))
    responses = iter([response(b"busy", 502), response(), response(TEXT)])

    def handle(request):
        starts.append(current[0])
        return next(responses)

    with BillAcquirer(
        budget=replace(BUDGET, min_request_interval_seconds=0.4), transport=httpx.MockTransport(handle)
    ) as source:
        status = source.acquire_status(IDENTITY)
        text = source.acquire_text(status, package_id=PACKAGE)
    assert starts == pytest.approx([0, 0.4, 0.8])
    assert status.request_count == 2 and text.request_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_requests", True),
        ("max_requests", 0),
        ("max_status_bytes", 0),
        ("max_text_bytes", False),
        ("timeout_seconds", 0),
        ("min_request_interval_seconds", float("nan")),
    ],
)
def test_invalid_limits_refuse(field, value):
    with pytest.raises(ValueError, match=field):
        replace(BUDGET, **{field: value})


def test_closed_client_cannot_fetch():
    source = BillAcquirer(budget=BUDGET, transport=Transport())
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.acquire_status(IDENTITY)


def test_configured_budget_cannot_diverge_from_transport():
    with BillAcquirer(budget=BUDGET, transport=Transport()) as source, pytest.raises(AttributeError):
        source.budget = replace(BUDGET, max_requests=50)
