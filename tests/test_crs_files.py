"""A CRS report file is one explicit version, proved by its media type, magic and final URL."""

import hashlib
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.markup import read_html_events
from spicy_docs.sources.congress.crs_files import (
    CRS_EXTERNAL_PRODUCTS,
    CrsFileAcquirer,
    CrsFileAcquisition,
    CrsFileBudget,
    CrsFileSelection,
    CrsFileSourceError,
    CrsFileUnavailableError,
    CrsHtmlAcquisition,
    CrsHtmlSelection,
    crs_file_locator,
    crs_file_selection,
    crs_html_locator,
    crs_html_selection,
    family_from_report_id,
    read_crs_html,
    read_crs_pdf,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

#: First 2,048 bytes of IF11830.5.pdf: a real header and a real truncated capture.
PREFIX = (Path(__file__).parent / "fixtures" / "crs_files" / "IF11830.5.prefix.pdf").read_bytes()
#: The length IF11830.5.pdf's own signature states, and the length the publisher served.
IF11830_BYTES = 406_818
#: The real header and signature, padded to the length that signature states. Constructed, not served.
COMPLETE = PREFIX + b"\x00" * (IF11830_BYTES - len(PREFIX) - 6) + b"%%EOF\n"
SELECTION = CrsFileSelection("IF", "IF11830", 5)
LOCATOR = f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11830.5.pdf"
BUDGET = CrsFileBudget(3, 8 * 1024 * 1024, 7, 0)
#: Publisher-stated PDF URLs, as the CRS detail rows spell them in ``formats``.
STATED = (
    (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11830.5.pdf", "IF", "IF11830", 5),
    (f"{CRS_EXTERNAL_PRODUCTS}/LSB/PDF/LSB10059/LSB10059.3.pdf", "LSB", "LSB10059", 3),
    (f"{CRS_EXTERNAL_PRODUCTS}/R/PDF/R49346/R49346.1.pdf", "R", "R49346", 1),
    (f"{CRS_EXTERNAL_PRODUCTS}/RA/PDF/RL31312/RL31312.6.pdf", "RA", "RL31312", 6),
    (f"{CRS_EXTERNAL_PRODUCTS}/RS/PDF/98-807/98-807.12.pdf", "RS", "98-807", 12),
)

#: The complete, unmodified HTML body congress.gov served for IF12853 on 2026-09-19
#: (tests/fixtures/crs_files/README.md). No synthesis: the whole report.
HTML_BODY = (Path(__file__).parent / "fixtures" / "crs_files" / "IF12853.html").read_bytes()
HTML_SELECTION = CrsHtmlSelection("IF", "IF12853")
HTML_LOCATOR = f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF12853.html"
#: The version congress.gov paired with this HTML in the same ``formats[]`` response.
PDF_SELECTION_FOR_HTML_REPORT = CrsFileSelection("IF", "IF12853", 10)
PDF_LOCATOR_FOR_HTML_REPORT = f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF12853/IF12853.10.pdf"
#: Publisher-stated HTML URLs, as the CRS detail rows spell them in ``formats``: no per-id
#: directory and no version segment, unlike the PDF route.
HTML_STATED = (
    (f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF12853.html", "IF", "IF12853"),
    (f"{CRS_EXTERNAL_PRODUCTS}/LSB/HTML/LSB10059.html", "LSB", "LSB10059"),
    (f"{CRS_EXTERNAL_PRODUCTS}/R/HTML/R49346.html", "R", "R49346"),
    (f"{CRS_EXTERNAL_PRODUCTS}/RA/HTML/RL31312.html", "RA", "RL31312"),
    (f"{CRS_EXTERNAL_PRODUCTS}/RS/HTML/98-807.html", "RS", "98-807"),
)


def signed_pdf(*, delta: int = 0, pad: int = 64) -> bytes:
    """A constructed PDF whose signature states its own length, or misstates it by ``delta``."""
    body = b"%PDF-1.5\n<</ByteRange [0 142 100 0000000]>>\n" + b"x" * pad + b"%%EOF\n"
    return body.replace(b"0000000", f"{len(body) - 100 + delta:07d}".encode())


def response(body=COMPLETE, status=200, *, content_type="application/pdf"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


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


@pytest.mark.parametrize("url,family,report_id,version", STATED)
def test_stated_url_round_trips_through_the_selection(url, family, report_id, version):
    selection = crs_file_selection(url)
    assert (selection.family, selection.report_id, selection.version) == (family, report_id, version)
    assert selection.file_name == f"{report_id}.{version}.pdf"
    assert crs_file_locator(selection) == url


def test_family_inference_follows_the_prefix_and_refuses_what_it_cannot_state():
    assert family_from_report_id("IF11830") == "IF" and family_from_report_id("LSB10059") == "LSB"
    # RL31312 is filed under RA: the inference is an inference, and answered 404 live.
    assert family_from_report_id("RL31312") == "RL" != crs_file_selection(STATED[3][0]).family
    with pytest.raises(CrsFileSourceError, match="legacy CRS id states no family"):
        family_from_report_id("98-807")


@pytest.mark.parametrize(
    "url,message",
    [
        (f"{CRS_EXTERNAL_PRODUCTS}/if/PDF/IF11830/IF11830.5.pdf", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11830.5.PDF", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF11830/IF11830.5.pdf", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11830.pdf", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11830.5.pdf?download=1", "not a congress.gov"),
        ("http://www.congress.gov/crs_external_products/IF/PDF/IF11830/IF11830.5.pdf", "not a congress.gov"),
        ("https://congress.gov/crs_external_products/IF/PDF/IF11830/IF11830.5.pdf", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF11830/IF11831.5.pdf", "different report ids"),
        (b"bytes", "must be a string"),
    ],
)
def test_stated_url_refusals_name_the_failed_check(url, message):
    with pytest.raises(CrsFileSourceError, match=message):
        crs_file_selection(url)


@pytest.mark.parametrize(
    "fields,message",
    [
        ({"family": "if"}, "uppercase path segment"),
        ({"family": "IFPDFX"}, "uppercase path segment"),
        ({"family": None}, "uppercase path segment"),
        ({"report_id": "if11830"}, "report_id"),
        ({"report_id": "IF11830.5"}, "report_id"),
        ({"report_id": ""}, "report_id"),
        ({"version": 0}, "version"),
        ({"version": True}, "version"),
        ({"version": "5"}, "version"),
        ({"version": 10_000}, "version"),
    ],
)
def test_selection_refusals_name_the_failed_check(fields, message):
    with pytest.raises(CrsFileSourceError, match=message):
        CrsFileSelection(**{"family": "IF", "report_id": "IF11830", "version": 5, **fields})


def test_locator_requires_a_selection():
    with pytest.raises(CrsFileSourceError, match="must be a CrsFileSelection"):
        crs_file_locator(LOCATOR)


def read(body, selection=SELECTION, **kwargs):
    kwargs.setdefault("final_url", LOCATOR)
    return read_crs_pdf(body, selection, **kwargs)


def test_complete_file_states_its_pdf_version_and_signed_length():
    file = read(COMPLETE)
    assert file.pdf_version == "1.7" and file.byte_size == IF11830_BYTES
    # The publisher's own /ByteRange, read from the retained header bytes.
    assert file.signed_byte_range_total == IF11830_BYTES and file.selection == SELECTION


def test_unsigned_pdf_keeps_its_absent_signature_absent():
    file = read(b"%PDF-2.0\n" + b"x" * 32 + b"\n%%EOF\n")
    assert file.signed_byte_range_total is None and file.pdf_version == "2.0"


def test_signature_length_must_agree_with_the_capture():
    assert read(signed_pdf()).signed_byte_range_total == len(signed_pdf())
    with pytest.raises(CrsFileSourceError, match="signature states"):
        read(signed_pdf(delta=1))


@pytest.mark.parametrize(
    "body,message",
    [
        (PREFIX, "incomplete"),
        (b"", "empty"),
        (b"<!DOCTYPE html><html>Congress.gov | Library of Congress</html>", "PDF- magic"),
        (b" %PDF-1.7\n%%EOF\n", "PDF- magic"),
        (b"%PDF1.7\n%%EOF\n", "PDF- magic"),
        (b"%PDF-1.7\n" + b"x" * 2048, "incomplete"),
        (b"%PDF-1.7\n%%EOF\n" + b"x" * 2048, "incomplete"),
        ("%PDF-1.7\n%%EOF\n", "must be bytes"),
    ],
)
def test_body_refusals_name_the_failed_check(body, message):
    with pytest.raises(CrsFileSourceError, match=message):
        read(body)


@pytest.mark.parametrize(
    "final_url",
    [
        LOCATOR.replace("IF11830.5", "IF11830.4"),
        LOCATOR.replace("https://", "http://"),
        LOCATOR + "?download=1",
        LOCATOR.replace("www.congress.gov", "congress.gov.example.invalid"),
    ],
)
def test_a_final_url_other_than_the_locator_is_refused(final_url):
    with pytest.raises(CrsFileSourceError, match="final URL"):
        read(COMPLETE, final_url=final_url)


@pytest.mark.parametrize("max_bytes", [0, True, 64 * 1024**2 + 1, "8192"])
def test_read_bounds_are_explicit(max_bytes):
    with pytest.raises(CrsFileSourceError, match="max_bytes"):
        read(COMPLETE, max_bytes=max_bytes)
    with pytest.raises(CrsFileSourceError, match="byte bound"):
        read(COMPLETE, max_bytes=IF11830_BYTES - 1)


def test_acquirer_captures_exact_pdf_bytes_keyless():
    transport = Transport(response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report_pdf(SELECTION)
    assert result.capture.body == COMPLETE and result.capture.requested_url == LOCATOR
    assert result.capture.sha256 == "sha256:" + hashlib.sha256(COMPLETE).hexdigest()
    assert result.file.byte_size == IF11830_BYTES and result.selection == SELECTION
    assert result.request_count == 1 and result.budget == BUDGET
    request = transport.calls[0]
    # Keyless and GET only: HEAD answered 403 on this route.
    assert request.method == "GET" and "x-api-key" not in request.headers
    assert "api_key" not in str(request.url) and request.headers["accept-encoding"] == "identity"
    assert str(request.url) == LOCATOR


def test_narrowed_byte_bound_refuses_a_larger_file_with_its_evidence():
    transport = Transport(response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(CrsFileSourceError) as raised:
        source.acquire_report_pdf(SELECTION, max_bytes=4096)
    assert raised.value.crs_file_acquisition["budget"]["max_bytes"] == 4096
    assert raised.value.refused_response.unavailable_reason == "response-byte-limit"


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(b"<!DOCTYPE html><html>error</html>", content_type="text/html"), CrsFileSourceError, "Content-Type"),
        (response(b"<!DOCTYPE html><html>error</html>"), CrsFileSourceError, "PDF- magic"),
        (response(PREFIX), CrsFileSourceError, "incomplete"),
        (response(b"<!DOCTYPE html>404", 404, content_type="text/html"), CrsFileUnavailableError, "HTTP 404"),
        (response(b"", 410), CrsFileUnavailableError, "HTTP 410"),
    ],
)
def test_wrong_shape_or_missing_file_never_succeeds(answer, error, message):
    transport = Transport(answer)
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire_report_pdf(SELECTION)
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.crs_file_acquisition["operation"] == "crs-report-pdf"
    assert raised.value.crs_file_acquisition["selection"] == {"family": "IF", "report_id": "IF11830", "version": 5}
    assert raised.value.crs_file_acquisition["url"] == LOCATOR
    assert len(transport.calls) == 1


def test_budget_and_client_configuration_are_explicit():
    for fields in ({"max_requests": 0}, {"max_bytes": 64 * 1024**2 + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            CrsFileBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        CrsFileAcquirer(budget=(3, 4096, 7, 0), transport=Transport())


# --- HTML: preferred, no version, with fallback to the versioned PDF -------------------------


@pytest.mark.parametrize("url,family,report_id", HTML_STATED)
def test_html_stated_url_round_trips_through_the_selection(url, family, report_id):
    selection = crs_html_selection(url)
    assert (selection.family, selection.report_id) == (family, report_id)
    assert selection.file_name == f"{report_id}.html"
    assert crs_html_locator(selection) == url


@pytest.mark.parametrize(
    "url,message",
    [
        (f"{CRS_EXTERNAL_PRODUCTS}/if/HTML/IF12853.html", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/html/IF12853.html", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/PDF/IF12853.html", "not a congress.gov"),
        # The PDF route nests a per-id directory; the HTML route does not.
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF12853/IF12853.html", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF12853.10.html", "not a congress.gov"),
        (f"{CRS_EXTERNAL_PRODUCTS}/IF/HTML/IF12853.html?download=1", "not a congress.gov"),
        ("http://www.congress.gov/crs_external_products/IF/HTML/IF12853.html", "not a congress.gov"),
        (b"bytes", "must be a string"),
    ],
)
def test_html_stated_url_refusals_name_the_failed_check(url, message):
    with pytest.raises(CrsFileSourceError, match=message):
        crs_html_selection(url)


@pytest.mark.parametrize(
    "fields,message",
    [
        ({"family": "if"}, "uppercase path segment"),
        ({"family": "IFHTMLX"}, "uppercase path segment"),
        ({"family": None}, "uppercase path segment"),
        ({"report_id": "if12853"}, "report_id"),
        ({"report_id": "IF12853.10"}, "report_id"),
        ({"report_id": ""}, "report_id"),
    ],
)
def test_html_selection_refusals_name_the_failed_check(fields, message):
    with pytest.raises(CrsFileSourceError, match=message):
        CrsHtmlSelection(**{"family": "IF", "report_id": "IF12853", **fields})


def test_html_locator_requires_a_selection():
    with pytest.raises(CrsFileSourceError, match="must be a CrsHtmlSelection"):
        crs_html_locator(HTML_LOCATOR)


def read_html(body, selection=HTML_SELECTION, **kwargs):
    kwargs.setdefault("final_url", HTML_LOCATOR)
    return read_crs_html(body, selection, **kwargs)


def test_the_real_html_body_states_its_report_id_twice_independently():
    html = read_html(HTML_BODY)
    assert html.selection == HTML_SELECTION and html.byte_size == len(HTML_BODY)
    assert b"(IF12853)" in HTML_BODY
    assert b'data-prod-type="IF"' in HTML_BODY


@pytest.mark.parametrize(
    "body,message",
    [
        (b"<html><body>no report id here</body></html>", "does not state the requested report id"),
        (b"<html>(IF12853) but no prod-type marker</html>", "does not state the requested report family"),
        (b"", "does not state the requested report id"),
        ("(IF12853)", "must be bytes"),
    ],
)
def test_html_body_refusals_name_the_failed_check(body, message):
    with pytest.raises(CrsFileSourceError, match=message):
        read_html(body)


@pytest.mark.parametrize(
    "final_url",
    [
        HTML_LOCATOR.replace("IF12853", "IF12852"),
        HTML_LOCATOR.replace("https://", "http://"),
        HTML_LOCATOR + "?download=1",
    ],
)
def test_html_final_url_other_than_the_locator_is_refused(final_url):
    with pytest.raises(CrsFileSourceError, match="final URL"):
        read_html(HTML_BODY, final_url=final_url)


def test_html_read_bounds_are_explicit():
    with pytest.raises(CrsFileSourceError, match="max_bytes"):
        read_html(HTML_BODY, max_bytes="8192")
    with pytest.raises(CrsFileSourceError, match="byte bound"):
        read_html(HTML_BODY, max_bytes=len(HTML_BODY) - 1)


def test_html_fixture_parses_as_markup_through_the_shared_reader():
    """The route's identity proof and the module's own markup reader agree on the same bytes."""
    result = read_html_events(HTML_BODY)
    assert result.root_name == "head" and result.element_count == 168
    report_id_text = [e.text for e in result.events if e.kind == "text" and e.text and "(IF12853)" in e.text]
    assert report_id_text and "Updated" in report_id_text[0]


def html_response(body=HTML_BODY, status=200, *, content_type="text/html"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


def test_acquirer_captures_exact_html_bytes_keyless():
    transport = Transport(html_response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report_html(HTML_SELECTION)
    assert result.capture.body == HTML_BODY and result.capture.requested_url == HTML_LOCATOR
    assert result.html.byte_size == len(HTML_BODY) and result.selection == HTML_SELECTION
    assert result.request_count == 1 and result.budget == BUDGET
    request = transport.calls[0]
    assert request.method == "GET" and "x-api-key" not in request.headers
    assert "api_key" not in str(request.url) and request.headers["accept-encoding"] == "identity"
    assert str(request.url) == HTML_LOCATOR


def test_acquire_report_prefers_html_when_it_is_offered():
    transport = Transport(html_response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report(PDF_SELECTION_FOR_HTML_REPORT, html_selection=HTML_SELECTION)
    assert isinstance(result, CrsHtmlAcquisition)
    assert result.html.byte_size == len(HTML_BODY) and result.request_count == 1
    assert len(transport.calls) == 1 and str(transport.calls[0].url) == HTML_LOCATOR


def test_acquire_report_without_html_selection_behaves_like_the_pdf_route_alone():
    transport = Transport(response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report(SELECTION)
    assert isinstance(result, CrsFileAcquisition) and result.request_count == 1
    assert len(transport.calls) == 1 and str(transport.calls[0].url) == LOCATOR


@pytest.mark.parametrize(
    "refusal",
    [
        # The keyless bot wall: a 403, kept as evidence, not this module's own error.
        html_response(b"<html>Request Rejected</html>", status=403),
        # Served, but not the shape read_crs_html proves: no report-id marker.
        html_response(b"<html><body>the wrong page</body></html>"),
        # Served as the wrong media type entirely.
        html_response(b"<!DOCTYPE html>", content_type="application/octet-stream"),
    ],
)
def test_acquire_report_falls_back_to_pdf_on_any_html_refusal(refusal):
    # Paired the way a real caller pairs them: both from IF12853's formats[].
    transport = Transport(refusal, response())
    with CrsFileAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_report(PDF_SELECTION_FOR_HTML_REPORT, html_selection=HTML_SELECTION)
    assert isinstance(result, CrsFileAcquisition)
    assert result.file.byte_size == IF11830_BYTES and result.request_count == 2
    assert len(transport.calls) == 2
    assert str(transport.calls[0].url) == HTML_LOCATOR
    assert str(transport.calls[1].url) == PDF_LOCATOR_FOR_HTML_REPORT


def test_acquire_report_raises_when_the_pdf_fallback_also_fails():
    transport = Transport(html_response(status=403), response(b"<!DOCTYPE html>404", 404, content_type="text/html"))
    with (
        CrsFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CrsFileUnavailableError, match="HTTP 404"),
    ):
        source.acquire_report(PDF_SELECTION_FOR_HTML_REPORT, html_selection=HTML_SELECTION)


def test_html_credential_refusal_carries_its_evidence_when_no_fallback_is_offered():
    transport = Transport(html_response(b"<html>Request Rejected</html>", status=403))
    with (
        CrsFileAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CredentialRefusedError) as raised,
    ):
        source.acquire_report_html(HTML_SELECTION)
    assert raised.value.refused_response.response_bytes == b"<html>Request Rejected</html>"
