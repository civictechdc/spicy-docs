"""Check XML preference without hiding refusals or resetting fetch bounds.

Pins exact XML capture in one request, HTML fallback only on document
unavailability, strict-mode refusal, credential refusal without reading the
body, retry and budget sharing across XML, MODS and HTML, and pacing that
continues across acquisitions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs.sources.federal_register import body_acquisition as acquisition
from spicy_docs.sources.federal_register.body_acquisition import FederalRegisterBodyAcquirer, FederalRegisterBodyBudget
from spicy_docs.sources.federal_register.body_sources import FederalRegisterBodySourceError
from spicy_docs.transport import capture, retry
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

DOCUMENT = "2026-18670"
DATE = "2026-09-11"
XML_URL = "https://www.federalregister.gov/documents/full_text/xml/2026/09/11/2026-18670.xml"
HTML_URL = "https://www.govinfo.gov/content/pkg/FR-2026-09-11/html/2026-18670.htm"
MODS_URL = "https://www.govinfo.gov/metadata/pkg/FR-2026-09-11/mods.xml"
XML = (
    b"<RULE><PREAMB><SUBJECT>Example</SUBJECT></PREAMB>"
    b"<FRDOC>[FR Doc. 2026-18670 Filed 9-10-26; 8:45 am]</FRDOC></RULE>"
)
HTML = b"<pre>Federal Register\n[FR Doc No: 2026-18670]\nSynthetic body.</pre>"
MODS = b"""<mods xmlns="http://www.loc.gov/mods/v3">
<extension><accessId>FR-2026-09-11</accessId></extension>
<relatedItem type="constituent"><part><extent unit="pages"><start>123</start></extent></part>
<extension><accessId>2026-18670</accessId></extension></relatedItem></mods>"""
BUDGET = FederalRegisterBodyBudget(3, 1024, 4096, 7.0, 0)
NOW = datetime(2026, 9, 11, tzinfo=UTC)


class Stream(httpx.SyncByteStream):
    """A response stream that counts reads and records closure."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class Transport(httpx.MockTransport):
    """A mock transport that records calls and closes on exit."""

    def __init__(self, *actions: httpx.Response | Exception) -> None:
        self.actions = iter(actions)
        self.calls: list[httpx.Request] = []
        self.closed = False
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return action

    def close(self) -> None:
        self.closed = True


def response(
    body: bytes = XML,
    status: int = 200,
    *,
    media_type: str | None = "application/xml",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """An HTTPX response over the given body."""
    content_headers = {} if media_type is None else {"content-type": media_type}
    return httpx.Response(status, stream=Stream(body), headers={**content_headers, **(headers or {})})


def acquire(client: FederalRegisterBodyAcquirer, **options: object) -> acquisition.FederalRegisterBodyAcquisition:
    """Acquire one Federal Register body under the given request."""
    return client.acquire(document_number=DOCUMENT, publication_date=DATE, **options)


def urls(transport: Transport) -> list[str]:
    """The URLs the transport was asked for."""
    return [str(call.url) for call in transport.calls]


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_default_acquires_exact_xml_with_one_request_even_when_html_needs_mods() -> None:
    """The default acquires exact XML in one request and carries no MODS or fallback evidence."""
    received = response(headers={"content-length": str(len(XML))})
    transport = Transport(received)
    budget = replace(BUDGET, max_requests=1)
    with FederalRegisterBodyAcquirer(budget=budget, transport=transport, clock=lambda: NOW) as client:
        result = acquire(client, html_route="mods-start-page", start_page=123)

    assert result.format == "xml" and result.route == "publisher-xml"
    assert result.requested_format == "prefer-xml"
    assert result.identity.source_document_number == DOCUMENT
    assert result.identity.publication_date == DATE
    assert result.body.body == XML
    assert result.body.sha256 == "sha256:" + hashlib.sha256(XML).hexdigest()
    assert result.body.requested_url == result.body.resolved_url == XML_URL
    assert result.body.observed_at == "2026-09-11T00:00:00Z"
    assert result.mods is result.mods_resolution is result.unavailable_xml is None
    assert result.request_count == 1 and result.budget == budget
    assert urls(transport) == [XML_URL]
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert received.is_closed and transport.closed


@pytest.mark.parametrize("media_type", ["text/xml; charset=utf-8", "Application/XML; charset=UTF-8"])
def test_strict_xml_accepts_publisher_xml_media_types(media_type: str) -> None:
    """Strict XML accepts the publisher's XML media types."""
    transport = Transport(response(media_type=media_type))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client, format="xml")
    assert result.requested_format == result.format == "xml"
    assert result.body.body == XML and result.unavailable_xml is None
    assert urls(transport) == [XML_URL]


@pytest.mark.parametrize("status", [404, 410])
def test_only_document_unavailability_permits_html_fallback_and_keeps_its_evidence(status: int) -> None:
    """Only document unavailability permits HTML fallback, and the unavailable response is kept as evidence."""
    unavailable = b"Publisher XML unavailable"
    transport = Transport(response(unavailable, status), response(HTML, media_type="text/html"))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client)

    assert result.format == "html" and result.route == "granule"
    assert result.requested_format == "prefer-xml"
    assert result.body.body == HTML and result.identity.source_document_number == DOCUMENT
    assert result.unavailable_xml is not None
    assert result.unavailable_xml.status_code == status and result.unavailable_xml.body == unavailable
    assert result.unavailable_xml.requested_url == XML_URL
    assert result.mods is result.mods_resolution is None
    assert result.request_count == 2 and urls(transport) == [XML_URL, HTML_URL]


def test_complete_unavailable_xml_response_needs_no_xml_media_type() -> None:
    """A complete unavailable XML response needs no XML media type to authorize fallback."""
    transport = Transport(response(b"No XML", 404, media_type=None), response(HTML, media_type="text/html"))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client)
    assert result.format == "html" and result.body.body == HTML
    assert result.unavailable_xml is not None and result.unavailable_xml.content_type is None
    assert result.unavailable_xml.body == b"No XML" and result.unavailable_xml.status_code == 404
    assert urls(transport) == [XML_URL, HTML_URL]


def test_encoded_unavailable_xml_refuses_before_reading_or_falling_back() -> None:
    """An encoded unavailable XML refuses before reading or falling back, with no response bytes attached."""
    stream = Stream(b"not complete unencoded evidence")
    transport = Transport(httpx.Response(404, stream=stream, headers={"content-encoding": "gzip"}))
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="content encoding") as caught,
    ):
        acquire(client)
    assert stream.reads == 0 and stream.closed
    assert caught.value.__dict__["refused_response"].response_bytes is None
    assert caught.value.__dict__["body_acquisition"]["unavailableXml"] is None
    assert urls(transport) == [XML_URL]


def test_incomplete_404_retries_xml_and_never_authorizes_html() -> None:
    """An incomplete 404 retries XML and never authorizes HTML."""

    class BrokenStream(Stream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"incomplete unavailable response"
            raise httpx.ReadError("connection ended before EOF")

    streams = [BrokenStream(), BrokenStream()]
    transport = Transport(*(httpx.Response(404, stream=stream) for stream in streams))
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(ConnectionError) as caught,
    ):
        acquire(client)
    assert all(stream.closed for stream in streams)
    assert urls(transport) == [XML_URL, XML_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == XML_URL and refusal.response_bytes is None
    context = caught.value.__dict__["body_acquisition"]
    assert context["requestCount"] == 2 and context["unavailableXml"] is None


@pytest.mark.parametrize("status", [404, 410])
def test_strict_xml_retains_unavailable_response_and_never_requests_html(status: int) -> None:
    """Strict XML retains the unavailable response and never requests HTML."""
    transport = Transport(response(b"No XML", status))
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        acquire(client, format="xml")

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == XML_URL and refusal.response_bytes == b"No XML"
    assert urls(transport) == [XML_URL]


@pytest.mark.parametrize(
    ("body", "media_type"),
    [
        (b"", "application/xml"),
        (b"<html><body>Check your browser</body></html>", "text/html"),
        (b"<html><body>Check your browser</body></html>", "application/xml"),
        (b"<RULE>", "application/xml"),
        (XML.replace(b"2026-18670", b"2026-99999"), "application/xml"),
        (XML, "text/html"),
        (XML, None),
    ],
)
def test_success_status_does_not_make_invalid_xml_unavailable(body: bytes, media_type: str | None) -> None:
    """A success status does not make invalid XML unavailable; it is a source-validation refusal."""
    received = response(body, media_type=media_type)
    transport = Transport(received)
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        acquire(client)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == XML_URL and refusal.response_bytes == body
    assert refusal.stage == "source-validation"
    assert urls(transport) == [XML_URL] and received.is_closed


@pytest.mark.parametrize("status", [401, 403])
def test_xml_credential_refusal_reads_no_body_and_never_falls_back(status: int) -> None:
    """An XML credential refusal reads no body and never falls back."""
    stream = Stream(b"credential material must not enter evidence")
    transport = Transport(httpx.Response(status, stream=stream))
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(CredentialRefusedError) as caught,
    ):
        acquire(client)

    assert urls(transport) == [XML_URL]
    assert stream.reads == 0 and stream.closed and transport.closed
    assert caught.value.__dict__["refused_response"].response_bytes is None


@pytest.mark.parametrize("status", [302, 400])
def test_other_xml_status_is_not_an_html_fallback_signal(status: int) -> None:
    """Another XML status is not an HTML fallback signal."""
    transport = Transport(response(b"Refused", status, headers={"location": "https://example.test/xml"}))
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        acquire(client)

    assert caught.value.__dict__["refused_response"].response_bytes == b"Refused"
    assert urls(transport) == [XML_URL]


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_exhausted_xml_retry_is_failure_not_permission_to_fetch_html(failure: int | str) -> None:
    """An exhausted XML retry is a failure, not permission to fetch HTML."""
    actions = [httpx.ReadTimeout("untrusted provider text") if failure == "timeout" else response(status=failure)]
    actions.append(httpx.ReadTimeout("untrusted provider text") if failure == "timeout" else response(status=failure))
    transport = Transport(*actions)
    error_type = ConnectionError if failure == "timeout" else RetryableHTTPStatusError
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(error_type) as caught,
    ):
        acquire(client)

    assert urls(transport) == [XML_URL, XML_URL]
    assert caught.value.__dict__["body_acquisition"]["requestCount"] == 2
    assert caught.value.__dict__["refused_response"].request_key == XML_URL


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("status", [200, 404])
def test_oversized_xml_is_not_retained_as_complete_or_replaced_with_html(declared: bool, status: int) -> None:
    """Oversized XML is not retained as complete or replaced with HTML."""
    stream = Stream(b"a" * 30, b"b" * 30, b"unread tail")
    transport = Transport(httpx.Response(status, stream=stream, headers={"content-length": "60"} if declared else {}))
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_body_bytes=40), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="byte bound") as caught,
    ):
        acquire(client)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.response_bytes is None and refusal.unavailable_reason == "response-byte-limit"
    assert stream.closed and stream.reads == (0 if declared else 2)
    assert urls(transport) == [XML_URL]


@pytest.mark.parametrize("content_length", ["bad", str(len(XML) + 1)])
@pytest.mark.parametrize("status", [200, 404])
def test_invalid_xml_content_length_refuses_instead_of_falling_back(content_length: str, status: int) -> None:
    """An invalid XML Content-Length refuses instead of falling back."""
    transport = Transport(response(status=status, headers={"content-length": content_length}))
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="Content-Length"),
    ):
        acquire(client)
    assert urls(transport) == [XML_URL]


def test_fallback_cannot_reset_exhausted_xml_request_budget() -> None:
    """Fallback cannot reset an exhausted XML request budget, and the budget refusal is attributed to the next
    request.
    """
    transport = Transport(response(b"No XML", 404))
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_requests=1), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="request budget") as caught,
    ):
        acquire(client)

    assert urls(transport) == [XML_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == HTML_URL and refusal.response_bytes is None
    assert refusal.stage == "before-request" and refusal.unavailable_reason == "request-budget-exhausted"
    assert caught.value.__dict__["body_acquisition"]["unavailableXml"].body == b"No XML"


def test_xml_then_html_retry_share_one_request_counter() -> None:
    """XML and an HTML retry share one request counter across three calls."""
    transport = Transport(response(b"No XML", 404), response(status=503), response(HTML, media_type="text/html"))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client)
    assert result.request_count == 3 and urls(transport) == [XML_URL, HTML_URL, HTML_URL]
    assert result.unavailable_xml is not None and result.unavailable_xml.body == b"No XML"


def test_xml_then_mods_then_html_share_budget_and_return_each_complete_capture() -> None:
    """XML, MODS and HTML share the budget and return each complete capture."""
    transport = Transport(response(b"No XML", 410), response(MODS), response(HTML, media_type="text/html"))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client, html_route="mods-start-page", start_page=123)

    assert result.format == "html" and result.route == "mods-start-page"
    assert result.request_count == 3 and urls(transport) == [XML_URL, MODS_URL, HTML_URL]
    assert result.mods is not None and result.mods.body == MODS
    assert result.mods_resolution is not None and result.mods_resolution.start_page == 123
    assert result.unavailable_xml is not None and result.unavailable_xml.status_code == 410
    assert result.body.body == HTML


@pytest.mark.parametrize("bad_mods", [False, True])
def test_failed_html_fallback_reports_active_response_and_keeps_xml_unavailability(bad_mods: bool) -> None:
    """A failed HTML fallback reports the active response and keeps XML unavailability."""
    rejected = b"Not the requested source document"
    actions = [response(b"No XML", 404)]
    options = {}
    if bad_mods:
        actions.append(response(rejected))
        options = {"html_route": "mods-start-page", "start_page": 123}
    else:
        actions.append(response(rejected, media_type="text/html"))
    transport = Transport(*actions)
    with (
        FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError) as caught,
    ):
        acquire(client, **options)

    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == (MODS_URL if bad_mods else HTML_URL)
    assert refusal.response_bytes == rejected and refusal.stage == "source-validation"
    context = caught.value.__dict__["body_acquisition"]
    assert context["unavailableXml"].body == b"No XML" and context["requestCount"] == 2


def test_budget_failure_after_mods_never_labels_xml_or_mods_as_failed_html() -> None:
    """A budget failure after MODS never labels XML or MODS as failed HTML."""
    transport = Transport(response(b"No XML", 404), response(MODS))
    with (
        FederalRegisterBodyAcquirer(budget=replace(BUDGET, max_requests=2), transport=transport) as client,
        pytest.raises(FederalRegisterBodySourceError, match="request budget") as caught,
    ):
        acquire(client, html_route="mods-start-page", start_page=123)

    assert urls(transport) == [XML_URL, MODS_URL]
    refusal = caught.value.__dict__["refused_response"]
    assert refusal.request_key == HTML_URL and refusal.response_bytes is None
    assert refusal.stage == "before-request"
    assert caught.value.__dict__["body_acquisition"]["unavailableXml"].body == b"No XML"


def test_explicit_html_skips_xml() -> None:
    """An explicit HTML request skips XML."""
    transport = Transport(response(HTML, media_type="text/html"))
    with FederalRegisterBodyAcquirer(budget=BUDGET, transport=transport) as client:
        result = acquire(client, format="html")
    assert result.format == "html" and result.route == "granule"
    assert result.unavailable_xml is None and result.request_count == 1
    assert result.requested_format == "html"
    assert urls(transport) == [HTML_URL]


def test_pacing_continues_across_xml_fallback_and_successive_acquisitions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pacing continues across an XML fallback and successive acquisitions."""
    current = [0.0]
    starts: list[float] = []
    monkeypatch.setattr(capture.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(capture.time, "sleep", lambda delay: current.__setitem__(0, current[0] + delay))

    def handle(request: httpx.Request) -> httpx.Response:
        starts.append(current[0])
        if len(starts) == 1:
            return response(b"No XML", 404)
        if str(request.url) == HTML_URL:
            return response(HTML, media_type="text/html")
        return response()

    with FederalRegisterBodyAcquirer(
        budget=replace(BUDGET, min_request_interval_seconds=0.4), transport=httpx.MockTransport(handle)
    ) as client:
        assert acquire(client).request_count == 2
        assert acquire(client).request_count == 1
    assert starts == [0.0, 0.4, 0.8]
