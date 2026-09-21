"""GAO report files are selected by product ID and proved by their own bytes.

Pins per-host locator spellings, PDF magic and trailer checks, index-proved
products, exact keyless captures, and 404/403 semantics where a keyless 403
aborts without establishing absence.
"""

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.gao.files import (
    DEFAULT_MAX_INDEX_BYTES,
    MAX_REPORT_FILE_BYTES,
    GaoReportFileAcquirer,
    GaoReportFileBudget,
    GaoReportFileSourceError,
    GaoReportFileUnavailableError,
    gao_report_index_locator,
    gao_report_pdf_locator,
    parse_gao_report_index,
    validate_gao_report_pdf,
)
from spicy_docs.transport import retry
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "gao_files"
INDEX = (FIXTURES / "gao-26-107693-index.html").read_bytes()
PDF_HEAD = (FIXTURES / "gao-26-107693-pdf-head.bin").read_bytes()
ACCESS_DENIED = (FIXTURES / "files-access-denied.xml").read_bytes()
PRODUCT = "gao-26-107693"
PDF_URL = "https://files.gao.gov/assets/gao-26-107693.pdf"
INDEX_URL = "https://files.gao.gov/reports/GAO-26-107693/index.html"
# A synthetic, minimal PDF: the publisher's multi-megabyte bodies are not
# committed, so transport behaviour is exercised on bytes of our own making.
PDF = b"%PDF-1.4\n1 0 obj\n<</Type/Catalog>>\nendobj\ntrailer\n<</Root 1 0 R>>\n%%EOF\n"
BUDGET = GaoReportFileBudget(3, DEFAULT_MAX_INDEX_BYTES, 4 * 1024 * 1024, 7, 0)


def response(body=PDF, status=200, *, content_type="application/octet-stream"):
    """An HTTPX response over the given bytes."""
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


def index_response(body=INDEX, status=200, *, content_type="text/html"):
    """An HTTPX response over the pinned index bytes."""
    return response(body, status, content_type=content_type)


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


def test_locators_keep_the_publisher_spelling_each_host_requires():
    """Each host's locator keeps the publisher spelling it requires, including the highlights rendition."""
    assert gao_report_pdf_locator(PRODUCT) == PDF_URL
    assert gao_report_pdf_locator(PRODUCT, rendition="highlights") == (
        "https://files.gao.gov/assets/gao-26-107693-highlights.pdf"
    )
    assert gao_report_index_locator(PRODUCT) == INDEX_URL


@pytest.mark.parametrize("product_id", ["GAO-26-107693", "gao-26-107693/", "", "gao_26_107693", "a" * 200])
def test_report_files_are_selected_by_the_product_id_grammar(product_id):
    """Report files are selected only by a valid product ID."""
    with pytest.raises(GaoReportFileSourceError, match="product ID"):
        gao_report_pdf_locator(product_id)
    with pytest.raises(GaoReportFileSourceError, match="product ID"):
        gao_report_index_locator(product_id)


def test_unknown_rendition_is_refused():
    """An unknown rendition is refused."""
    with pytest.raises(GaoReportFileSourceError, match="rendition"):
        gao_report_pdf_locator(PRODUCT, rendition="summary")


def test_pinned_index_states_its_report_pdf_its_product_and_its_title():
    """The pinned index states its report PDF, product URL and title."""
    index = parse_gao_report_index(INDEX, product_id=PRODUCT)
    assert index.locator == INDEX_URL and index.pdf_url == PDF_URL
    assert index.product_url == "https://www.gao.gov/products/gao-26-107693"
    assert index.title is not None and index.title.startswith("GAO-26-107693, AVIATION CYBERSECURITY")


@pytest.mark.parametrize(
    "body,message",
    [
        (b"", "nonempty"),
        (b"<html><head><title>x</title></head><body></body></html>", "does not link its report PDF"),
        (INDEX.replace(b'href="/assets/gao-26-107693.pdf"', b'href="/assets/gao-26-999999.pdf"'), "report PDF"),
        (INDEX.replace(b"/assets/gao-26-107693.pdf", b"/assets/gao-26-107693.pdf.html"), "report PDF"),
        (
            INDEX.replace(b'href="https://www.gao.gov/products/gao-26-107693"', b'href="https://www.gao.gov"'),
            "canonical product page",
        ),
        (INDEX.replace(b"<title>", b"\xff\xfe<title>"), "valid UTF-8"),
        (b"<html><head></head><body>Checking your browser</body></html>", "does not link its report PDF"),
    ],
)
def test_index_refusals_name_the_failed_check(body, message):
    """Index refusals name the failed check."""
    with pytest.raises(GaoReportFileSourceError, match=message):
        parse_gao_report_index(body, product_id=PRODUCT)


def test_index_bounds_are_explicit():
    """Index bounds are explicit and refuse on violation."""
    with pytest.raises(GaoReportFileSourceError, match="byte bound"):
        parse_gao_report_index(INDEX, product_id=PRODUCT, max_bytes=len(INDEX) - 1)
    for max_bytes in (0, True, MAX_REPORT_FILE_BYTES + 1):
        with pytest.raises(ValueError, match="max_bytes"):
            parse_gao_report_index(INDEX, product_id=PRODUCT, max_bytes=max_bytes)


def test_report_pdf_capture_is_exact_and_keyless():
    """A report PDF capture is exact and keyless with no index fetched."""
    transport = Transport(response())
    with GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report_pdf(PRODUCT)
    assert result.pdf_capture.body == PDF and result.pdf_capture.requested_url == PDF_URL
    assert result.pdf.pdf_version == "1.4" and result.pdf.locator == PDF_URL
    assert result.pdf_capture.byte_size == len(PDF)
    assert result.index is None and result.index_capture is None
    assert result.request_count == 1 and result.budget == BUDGET
    request = transport.calls[0]
    assert str(request.url) == PDF_URL and request.headers["accept-encoding"] == "identity"
    assert "x-api-key" not in request.headers and "authorization" not in request.headers


def test_publisher_pdf_media_type_is_accepted_and_the_magic_bytes_decide():
    """The publisher's PDF media type is accepted, with magic bytes deciding."""
    for content_type in ("application/octet-stream", "application/pdf; charset=binary"):
        transport = Transport(response(content_type=content_type))
        with GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source:
            assert source.acquire_report_pdf(PRODUCT).pdf.pdf_version == "1.4"


def test_highlights_rendition_is_requested_at_its_own_locator():
    """The highlights rendition is requested at its own locator."""
    transport = Transport(response())
    with GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report_pdf(PRODUCT, rendition="highlights")
    assert result.pdf.rendition == "highlights"
    assert str(transport.calls[0].url) == gao_report_pdf_locator(PRODUCT, rendition="highlights")


@pytest.mark.parametrize(
    "answer,message",
    [
        (response(b"<html>Access denied</html>", content_type="text/html"), "Content-Type"),
        (response(b"<html>Access denied</html>"), "PDF- magic"),
        (response(INDEX, content_type="text/html"), "Content-Type"),
        (response(PDF_HEAD), "PDF trailer"),
        (response(PDF.replace(b"%%EOF\n", b"")), "PDF trailer"),
    ],
)
def test_a_200_that_is_not_a_pdf_is_refused_with_its_bytes_retained(answer, message):
    """A 200 that is not a PDF is refused with its bytes retained and the operation recorded."""
    transport = Transport(answer)
    with (
        GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(GaoReportFileSourceError, match=message) as raised,
    ):
        source.acquire_report_pdf(PRODUCT)
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.gao_report_file_acquisition["operation"] == "report-pdf"
    assert raised.value.gao_report_file_acquisition["productId"] == PRODUCT
    assert len(transport.calls) == 1


def test_real_publisher_prefix_carries_the_magic_and_a_truncated_body_is_refused():
    """A real publisher prefix carries the magic, while a truncated body is refused for its trailer."""
    assert PDF_HEAD.startswith(b"%PDF-1.7\r")
    transport = Transport(response(PDF_HEAD))
    with (
        GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(GaoReportFileSourceError, match="PDF trailer"),
    ):
        source.acquire_report_pdf(PRODUCT)


def test_a_body_whose_final_url_differs_from_the_locator_is_refused():
    """A body whose final URL differs from the locator is refused."""
    capture = _capture(PDF, url="https://files.gao.gov/assets/gao-26-999999.pdf")
    with pytest.raises(GaoReportFileSourceError, match="final URL"):
        validate_gao_report_pdf(capture, product_id=PRODUCT)


def _capture(body, *, url=PDF_URL):
    """Acquire a report PDF through the given response."""
    return CapturedBodyResponse(
        requested_url=url,
        resolved_url=url,
        status_code=200,
        content_type="application/octet-stream",
        observed_at="2026-09-14T17:00:00Z",
        body=body,
    )


@pytest.mark.parametrize("status", [404, 410])
def test_a_404_names_the_file_unavailable(status):
    """A 404 names the file unavailable."""
    transport = Transport(response(b"gone", status))
    with (
        GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(GaoReportFileUnavailableError) as raised,
    ):
        source.acquire_report_pdf(PRODUCT)
    assert raised.value.capture.status_code == status


def test_the_file_hosts_403_aborts_and_never_becomes_absence():
    """The file host's 403 aborts and never becomes absence, with the keyless body kept as evidence."""
    transport = Transport(response(ACCESS_DENIED, 403, content_type="application/xml"))
    with (
        GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CredentialRefusedError) as raised,
    ):
        source.acquire_report_pdf(PRODUCT)
    assert not isinstance(raised.value, GaoReportFileUnavailableError)
    # This route is keyless, so the host's 403 body is the publisher's answer and
    # is kept as evidence; it still aborts, because this host answers 403 for an
    # object it does not have, so absence is never established here.
    assert raised.value.refused_response.response_bytes == ACCESS_DENIED
    assert raised.value.refused_response.unavailable_reason == "access-refused"


def test_acquire_report_file_reads_the_index_then_the_pdf_it_states():
    """acquire_report_file reads the index and then the PDF it states, in two requests."""
    transport = Transport(index_response(), response())
    with GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report_file(PRODUCT)
    assert [str(call.url) for call in transport.calls] == [INDEX_URL, PDF_URL]
    assert result.index is not None and result.index.pdf_url == PDF_URL
    assert result.index_capture is not None and result.index_capture.body == INDEX
    assert result.pdf_capture.body == PDF and result.request_count == 2


def test_acquire_report_file_stops_when_the_index_does_not_prove_the_product():
    """acquire_report_file stops when the index does not prove the product."""
    transport = Transport(index_response(b"<html><title>other</title></html>"))
    with (
        GaoReportFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(GaoReportFileSourceError, match="report PDF") as raised,
    ):
        source.acquire_report_file(PRODUCT)
    assert len(transport.calls) == 1
    assert raised.value.gao_report_file_acquisition["operation"] == "report-index"


def test_budget_and_client_configuration_are_explicit():
    """Invalid budget values raise ValueError and a wrong transport type raises TypeError."""
    fields = {
        "max_requests": 3,
        "max_index_bytes": 4096,
        "max_pdf_bytes": 4096,
        "timeout_seconds": 7,
        "min_request_interval_seconds": 0,
    }
    for override in (
        {"max_requests": 0},
        {"max_index_bytes": MAX_REPORT_FILE_BYTES + 1},
        {"max_pdf_bytes": 0},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ):
        with pytest.raises(ValueError):
            GaoReportFileBudget(**{**fields, **override})
    with pytest.raises(TypeError):
        GaoReportFileAcquirer(budget=(3, 4096, 4096, 7, 0), transport=Transport())
