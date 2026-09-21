"""Bounded status-to-selected-text acquisition with retained responses.

Pins exact captured bytes and request counts, credential refusal aborting once,
404/410 as unavailable rather than absence, refusal of wrong shapes/identity
before a second request, caller-bounded limits, pacing, and budget validation.
"""

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
    """An HTTPX response over the given bytes."""
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type, **headers})


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_status_and_explicit_text_keep_exact_bytes_and_distinct_request_counts():
    """Both fetches keep exact bytes, timestamp, size/hash and one request each, from their own GET locators."""
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
    """A 404/410 on status or text raises BillSourceUnavailableError with the retained body, status and request
    count.
    """
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
    """A 401/403 raises CredentialRefusedError after exactly one request, with no response bytes attached."""
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
    """A 302/400/204 is a plain BillSourceError, never absence or a document, and keeps the returned bytes."""
    transport = Transport(response(b"refused", http_status, location="https://example.invalid/"))
    with BillAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceError) as caught:
        source.acquire_status(IDENTITY)
    assert type(caught.value) is BillSourceError
    assert len(transport.calls) == 1
    assert caught.value.refused_response.response_bytes == b"refused"


@pytest.mark.parametrize("http_status", [429, 502])
def test_failed_text_retries_have_no_status_body_misattribution(http_status):
    """A 429/502 text retry attributes the refusal to the text locator with the bounded request count and no status
    body.
    """
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
    """Empty, challenge, wrong-media-type or altered-number status bodies fail source validation with the failed
    bytes retained.
    """
    transport = Transport(response(body, content_type=media_type))
    with BillAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(BillSourceError) as caught:
        source.acquire_status(IDENTITY)
    assert caught.value.refused_response.response_bytes == body
    assert caught.value.refused_response.stage == "source-validation"


def test_unoffered_package_and_edited_status_refuse_before_text_request():
    """An unoffered package or edited retained status refuses at status-validation with zero text requests."""
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
    """A challenge page, wrong media type or mismatched version code refuses with the failed bytes and no fallback."""
    transport = Transport(response(), response(body, content_type=media_type))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(BillSourceError) as caught:
            source.acquire_text(status, package_id=PACKAGE)
    assert len(transport.calls) == 2
    assert caught.value.refused_response.response_bytes == body


def test_narrower_caller_limit_applies_and_is_recorded_in_failure():
    """A caller byte limit below the response is recorded on the failure with a response-byte-limit reason."""
    transport = Transport(response(), response(TEXT))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        with pytest.raises(BillSourceError, match="byte bound") as caught:
            source.acquire_text(status, package_id=PACKAGE, max_bytes=len(TEXT) - 1)
    assert caught.value.bill_acquisition["budget"]["max_text_bytes"] == len(TEXT) - 1
    assert caught.value.refused_response.unavailable_reason == "response-byte-limit"


def test_narrower_success_limit_is_recorded_in_result():
    """A caller byte limit equal to the response size is recorded on the successful result."""
    transport = Transport(response(), response(TEXT))
    with BillAcquirer(budget=BUDGET, transport=transport) as source:
        status = source.acquire_status(IDENTITY)
        text = source.acquire_text(status, package_id=PACKAGE, max_bytes=len(TEXT))
    assert text.budget.max_text_bytes == len(TEXT)


def test_pacing_covers_retry_then_separate_text_call(monkeypatch):
    """With a 0.4s minimum interval, a retry and a separate text call start at 0, 0.4 and 0.8s."""
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
    """Boolean, zero and NaN budget limits raise ValueError naming the field."""
    with pytest.raises(ValueError, match=field):
        replace(BUDGET, **{field: value})


def test_closed_client_cannot_fetch():
    """A closed acquirer refuses to fetch."""
    source = BillAcquirer(budget=BUDGET, transport=Transport())
    source.close()
    with pytest.raises(ValueError, match="closed"):
        source.acquire_status(IDENTITY)


def test_configured_budget_cannot_diverge_from_transport():
    """Reassigning the budget after construction raises AttributeError."""
    with BillAcquirer(budget=BUDGET, transport=Transport()) as source, pytest.raises(AttributeError):
        source.budget = replace(BUDGET, max_requests=50)
