"""A Supreme Court term index is one render that must state its own term; its links are the documents."""

import hashlib
from datetime import date
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.supreme_court import (
    SUPREME_COURT_SITE,
    SupremeCourtAcquirer,
    SupremeCourtBudget,
    SupremeCourtRevision,
    SupremeCourtSourceError,
    SupremeCourtUnavailableError,
    current_term_year,
    parse_supreme_court_term_index,
    read_supreme_court_pdf,
    supreme_court_term_index_locator,
    term_code,
)
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "supreme_court"
#: Five of the 72 OT2025 rows: the five row shapes that term states.
INDEX_2025 = (FIXTURES / "term-index-2025.html").read_bytes()
#: Two of the 68 OT2020 rows: a slip PDF and a link into a preliminary print.
INDEX_2020 = (FIXTURES / "term-index-2020.html").read_bytes()
#: The label and table header with no data rows, cut from the OT2025 capture.
HEADER_ONLY = INDEX_2025[: INDEX_2025.index(b"</tr>") + 5]
#: First 1,024 bytes of 26a274_l537.pdf: a real header and a real truncated capture.
PREFIX = (FIXTURES / "opinion-26a274_l537.head.pdf").read_bytes()
#: The length that PDF's own linearization dictionary states, and the length served.
OPINION_BYTES = 66_165
#: The real header, padded to the length it states. Constructed, not served.
COMPLETE = PREFIX + b"\x00" * (OPINION_BYTES - len(PREFIX) - 6) + b"%%EOF\n"
OPINION_URL = f"{SUPREME_COURT_SITE}/opinions/25pdf/26a274_l537.pdf"
INDEX_URL = f"{SUPREME_COURT_SITE}/opinions/slipopinion/25"
BUDGET = SupremeCourtBudget(3, 4 * 1024 * 1024, 16 * 1024 * 1024, 7, 0)
#: The pre-2021 layout the salvaged SpicyRegs reader measured over OT2017-OT2019.
#: No index retained in this port states a bound volume, so this row is
#: constructed from that measurement and is not a publisher capture.
BOUND_VOLUME = (
    b'<span id="ctl00_lblListTitle"><b> Term Year: 2018</b></span><table><tr><th>R-</th></tr>'
    b"<tr><td>1</td><td>6/22/19</td><td>17-1091</td>"
    b"<td><a href='/opinions/boundvolumes/588bv.pdf#page=73' title=\"Held.\">United States v. Davis</a></td>"
    b"<td>NG</td><td>588 U.S. 445</td></tr></table>"
)


def parse(body=INDEX_2025, *, term_year=2025, **kwargs):
    return parse_supreme_court_term_index(body, term_year=term_year, **kwargs)


def read(body=COMPLETE, *, url=OPINION_URL, final_url=None, **kwargs):
    return read_supreme_court_pdf(body, url=url, final_url=url if final_url is None else final_url, **kwargs)


def response(body=INDEX_2025, status=200, *, content_type="text/html; charset=utf-8"):
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


def test_pinned_index_states_its_term_and_keeps_the_publisher_spellings():
    index = parse()
    assert index.stated_term == "Term Year: 2025" and index.term_code == "25"
    assert index.index_url == INDEX_URL and index.term_year == 2025
    assert [opinion.release_number for opinion in index.opinions] == ["71", "66", "55", "54", "D1"]
    first = index.opinions[0]
    assert first.index == 0 and first.date_decided == "9/04/26" and first.docket_number == "26A274"
    assert first.case_name == "National Republican Congressional Committee v. Brown"
    assert first.author_code == "PC" and first.citation == "609/2"
    assert first.pdf_url == OPINION_URL and first.pdf_kind == "slip-opinion" and first.page_start is None
    assert first.holding is not None and first.holding.startswith("Because the Fourth Circuit")
    # A decree: the R- column is not an integer and the citation is already final.
    assert index.opinions[4].docket_number == "141, Orig." and index.opinions[4].citation == "608 U.S. 346"
    # ``title=""`` is a stated but empty holding, which is absent, not "".
    assert index.opinions[4].holding is None


def test_a_revision_link_is_never_read_as_the_opinion():
    revised, revision_only, unlinked = parse().opinions[1], parse().opinions[2], parse().opinions[3]
    assert revised.case_name == "Trump v. Barbara"
    assert revised.pdf_url == f"{SUPREME_COURT_SITE}/opinions/25pdf/25-365_new_5if6.pdf"
    assert revised.revisions == (
        SupremeCourtRevision("7/01/26", f"{SUPREME_COURT_SITE}/opinions/25pdf/25-365_diff_ed9g.pdf"),
    )
    # The only link in this row is a revision diff; the case name is the plain text.
    assert revision_only.case_name.startswith("Landor v. Louisiana Dept")
    assert revision_only.pdf_url is None and revision_only.pdf_kind is None
    assert revision_only.revisions[0].label == "6/28/26"
    # A listed case with no link at all is still a row the publisher stated.
    assert unlinked.case_name == "Pung v. Isabella County" and unlinked.pdf_url is None
    assert unlinked.docket_number == "25-95" and unlinked.revisions == ()


def test_an_older_index_links_into_a_preliminary_print_with_its_page_anchor():
    index = parse(INDEX_2020, term_year=2020)
    assert index.stated_term == "Term Year: 2020"
    slip, volume = index.opinions
    assert slip.pdf_kind == "slip-opinion" and slip.page_start is None
    assert volume.pdf_kind == "preliminary-print" and volume.page_start == "41"
    # The fragment says where in the volume the opinion begins; the resource is the volume.
    assert volume.pdf_url == f"{SUPREME_COURT_SITE}/opinions/preliminaryprint/592US1PP_web.pdf"
    assert volume.case_name == "Mckesson v. Doe" and volume.citation == "592 U.S. 1"


def test_a_bound_volume_row_is_recognised_with_its_page_anchor():
    opinion = parse(BOUND_VOLUME, term_year=2018).opinions[0]
    assert opinion.pdf_kind == "bound-volume" and opinion.page_start == "73"
    assert opinion.pdf_url == f"{SUPREME_COURT_SITE}/opinions/boundvolumes/588bv.pdf"


def test_document_urls_are_what_the_render_stated_and_collapse_one_shared_volume():
    index = parse()
    assert index.document_urls == {
        OPINION_URL,
        f"{SUPREME_COURT_SITE}/opinions/25pdf/25-365_new_5if6.pdf",
        f"{SUPREME_COURT_SITE}/opinions/25pdf/25-365_diff_ed9g.pdf",
        f"{SUPREME_COURT_SITE}/opinions/25pdf/23-1197diff2_j4ek.pdf",
        f"{SUPREME_COURT_SITE}/opinions/25pdf/608us1r36d_febh.pdf",
    }
    # Fifteen OT2020 rows point into one volume file; two rows, two documents here.
    assert len(parse(INDEX_2020, term_year=2020).document_urls) == 2


#: Each case is one mutation of a real capture, the term asked for, and the check it must fail.
INDEX_REFUSALS = {
    "another term is stated": (INDEX_2025.replace(b"Term Year: 2025", b"Term Year: 2023"), 2025, "requested term 2025"),
    "no term is stated": (INDEX_2025.replace(b"Term Year: 2025", b"Opinions"), 2025, "requested term 2025"),
    # A page a whole term out: the link directory and the dates each say so alone.
    "another term's links": (INDEX_2025.replace(b"/opinions/25pdf/", b"/opinions/23pdf/"), 2025, "outside the reque"),
    "another term's dates": (INDEX_2025.replace(b">9/04/26<", b">9/04/28<"), 2025, "not the term that was requested"),
    "an unreadable date": (INDEX_2025.replace(b">9/04/26<", b">9/44/26<"), 2025, "unreadable decision date"),
    "no rows": (HEADER_ONLY, 2025, "states no opinion rows"),
    "a challenge page": (b"<html><body>Checking your browser</body></html>", 2025, "states no opinion rows"),
    "an empty body": (b"", 2025, "empty"),
    "invalid UTF-8": (INDEX_2025 + b"\xff", 2025, "not the UTF-8"),
    "a volume link with no anchor": (INDEX_2020.replace(b"#page=41", b""), 2020, "states no page anchor"),
    "a volume link at page 0": (INDEX_2020.replace(b"#page=41", b"#page=0"), 2020, "states no page anchor"),
    "a cleartext link": (
        INDEX_2025.replace(b"href='/opinions/25", b"href='http://www.supremecourt.gov/opinions/25"),
        2025,
        "own site",
    ),
    "another host": (
        INDEX_2025.replace(b"href='/opinions/25", b"href='https://example.invalid/opinions/25"),
        2025,
        "own site",
    ),
    "a query string": (INDEX_2025.replace(b"_l537.pdf'", b"_l537.pdf?download=1'"), 2025, "own site"),
    "not a PDF path": (INDEX_2025.replace(b"_l537.pdf'", b"_l537.html'"), 2025, "own site"),
    "a slip link with a page anchor": (
        INDEX_2025.replace(b"_l537.pdf'", b"_l537.pdf#page=2'"),
        2025,
        "unexpected fragment",
    ),
    "a link with no target": (
        INDEX_2025.replace(b"<a href='/opinions/25pdf/26a274_l537.pdf'", b"<a name='x'"),
        2025,
        "without a target",
    ),
    "two opinion links": (
        INDEX_2025.replace(b"<td><a href=", b"<td><a href='/opinions/25pdf/x_0000.pdf'>A</a><a href="),
        2025,
        "more than one",
    ),
    "nested links": (
        INDEX_2025.replace(b"<td><a href=", b"<td><a href='/opinions/25pdf/x_0000.pdf'><a href="),
        2025,
        "nests its links",
    ),
    "no case name": (INDEX_2025.replace(b">Pung v. Isabella County<", b"><"), 2025, "states no case name"),
    # A nested or unclosed row would drop the row that holds it, silently.
    "nested rows": (INDEX_2025.replace(b"<td><a href=", b"<tr><td><a href=", 1), 2025, "nests its rows"),
}


@pytest.mark.parametrize("case", INDEX_REFUSALS, ids=list(INDEX_REFUSALS))
def test_index_refusals_name_the_failed_check(case):
    body, term_year, message = INDEX_REFUSALS[case]
    with pytest.raises(SupremeCourtSourceError, match=message):
        parse(body, term_year=term_year)


@pytest.mark.parametrize("max_bytes", [0, True, 16 * 1024**2 + 1, "4096"])
def test_index_bounds_are_explicit(max_bytes):
    with pytest.raises(SupremeCourtSourceError, match="max_bytes"):
        parse(max_bytes=max_bytes)
    with pytest.raises(SupremeCourtSourceError, match="byte bound"):
        parse(max_bytes=len(INDEX_2025) - 1)


def test_the_term_code_is_the_year_the_publisher_navigates_by():
    assert term_code(2025) == "25" and term_code(2000) == "00"
    assert supreme_court_term_index_locator(2024) == f"{SUPREME_COURT_SITE}/opinions/slipopinion/24"
    for value in (1999, 2100, True, "25", None):
        with pytest.raises(SupremeCourtSourceError, match="term_year"):
            term_code(value)
    # A term opens in October and is named for that year.
    assert current_term_year(date(2026, 9, 30)) == 2025
    assert current_term_year(date(2026, 10, 1)) == 2026
    with pytest.raises(SupremeCourtSourceError, match="today"):
        current_term_year("2026-10-01")


def test_the_real_pdf_header_states_its_own_length_and_the_truncated_capture_is_refused():
    document = read()
    assert document.pdf_version == "1.6" and document.byte_size == OPINION_BYTES
    assert document.linearized_length == OPINION_BYTES and document.url == OPINION_URL
    # The trailer check alone cannot see this truncation: a linearized PDF carries
    # its first-page cross-reference and an early ``%%EOF`` inside the first KiB,
    # so the real 1,024-byte prefix ends in a trailer. The stated ``/L`` catches it.
    assert b"%%EOF" in PREFIX
    with pytest.raises(SupremeCourtSourceError, match="differs from the length it states"):
        read(PREFIX)


@pytest.mark.parametrize(
    "body,message",
    [
        (b"<!DOCTYPE html><html>Access denied</html>", "%PDF- magic"),
        (b" %PDF-1.6\n%%EOF\n", "%PDF- magic"),
        (b"%PDF1.6\n%%EOF\n", "%PDF- magic"),
        (b"%PDF-1.6\n" + b"x" * 2048, "capture is incomplete"),
        (b"%PDF-1.6\n%%EOF\n" + b"x" * 2048, "capture is incomplete"),
        (COMPLETE + b"x", "differs from the length it states"),
        (b"", "empty"),
        ("%PDF-1.6\n%%EOF\n", "must be bytes"),
    ],
)
def test_document_refusals_name_the_failed_check(body, message):
    with pytest.raises(SupremeCourtSourceError, match=message):
        read(body)


def test_a_pdf_that_states_no_length_is_read_but_not_guessed_at():
    # Not every PDF is linearized; an absent ``/L`` is absent, not a refusal.
    document = read(b"%PDF-1.4\n" + b"x" * 64 + b"\n%%EOF\n")
    assert document.pdf_version == "1.4" and document.linearized_length is None


@pytest.mark.parametrize(
    "final_url",
    [
        OPINION_URL.replace("26a274_l537", "26a274_0000"),
        OPINION_URL.replace("https://", "http://"),
        OPINION_URL + "?download=1",
        OPINION_URL.replace("www.supremecourt.gov", "supremecourt.gov.example.invalid"),
    ],
)
def test_a_final_url_other_than_the_stated_link_is_refused(final_url):
    with pytest.raises(SupremeCourtSourceError, match="final URL"):
        read(final_url=final_url)


@pytest.mark.parametrize("max_bytes", [0, True, 64 * 1024**2 + 1, "4096"])
def test_document_bounds_are_explicit(max_bytes):
    with pytest.raises(SupremeCourtSourceError, match="max_bytes"):
        read(max_bytes=max_bytes)
    with pytest.raises(SupremeCourtSourceError, match="byte bound"):
        read(max_bytes=OPINION_BYTES - 1)


def test_acquirer_captures_exact_index_bytes_keyless():
    transport = Transport(response())
    with SupremeCourtAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_term_index(2025)
    assert result.capture.body == INDEX_2025 and result.capture.requested_url == INDEX_URL
    assert result.capture.sha256 == "sha256:" + hashlib.sha256(INDEX_2025).hexdigest()
    assert len(result.index.opinions) == 5 and result.request_count == 1 and result.budget == BUDGET
    request = transport.calls[0]
    assert request.method == "GET" and str(request.url) == INDEX_URL
    assert "x-api-key" not in request.headers and "api_key" not in str(request.url)
    assert request.headers["accept-encoding"] == "identity"


def test_acquirer_captures_one_document_the_retained_index_stated():
    index = parse()
    transport = Transport(response(COMPLETE, content_type="application/pdf"))
    with SupremeCourtAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_document(index, OPINION_URL)
    assert result.capture.body == COMPLETE and result.document.byte_size == OPINION_BYTES
    assert result.capture.requested_url == OPINION_URL and result.request_count == 1
    assert transport.calls[0].method == "GET" and "x-api-key" not in transport.calls[0].headers


def test_a_document_the_retained_index_never_stated_is_refused_before_any_request():
    index = parse()
    transport = Transport(response(COMPLETE, content_type="application/pdf"))
    with SupremeCourtAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(SupremeCourtSourceError, match="does not state that document URL"):
            source.acquire_document(index, f"{SUPREME_COURT_SITE}/opinions/25pdf/26a274_0000.pdf")
        with pytest.raises(TypeError):
            source.acquire_document(INDEX_2025, OPINION_URL)
    assert transport.calls == []


def test_narrowed_byte_bound_refuses_a_larger_response_with_its_evidence():
    transport = Transport(response())
    acquirer = SupremeCourtAcquirer(budget=BUDGET, transport=transport)
    with acquirer as source, pytest.raises(SupremeCourtSourceError) as raised:
        source.acquire_term_index(2025, max_bytes=512)
    assert raised.value.supreme_court_acquisition["budget"]["max_index_bytes"] == 512
    assert raised.value.refused_response.unavailable_reason == "response-byte-limit"


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(COMPLETE, content_type="application/pdf"), SupremeCourtSourceError, "Content-Type"),
        (response(b"<html>Access Denied</html>"), SupremeCourtSourceError, "states no opinion rows"),
        (response(INDEX_2020), SupremeCourtSourceError, "not the requested term 2025"),
        (response(b"<html>404</html>", 404), SupremeCourtUnavailableError, "HTTP 404"),
        (response(b"", 410), SupremeCourtUnavailableError, "HTTP 410"),
    ],
)
def test_wrong_shape_or_missing_index_never_succeeds(answer, error, message):
    transport = Transport(answer)
    acquirer = SupremeCourtAcquirer(budget=BUDGET, transport=transport)
    with acquirer as source, pytest.raises(error, match=message) as raised:
        source.acquire_term_index(2025)
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.supreme_court_acquisition["operation"] == "term-index"
    assert raised.value.supreme_court_acquisition["termYear"] == 2025
    assert raised.value.supreme_court_acquisition["url"] == INDEX_URL
    assert len(transport.calls) == 1


def test_a_document_answer_that_is_not_a_pdf_is_refused_with_its_bytes():
    index = parse()
    transport = Transport(response(b"<html>Access Denied</html>", content_type="application/pdf"))
    acquirer = SupremeCourtAcquirer(budget=BUDGET, transport=transport)
    with acquirer as source, pytest.raises(SupremeCourtSourceError, match="%PDF- magic") as raised:
        source.acquire_document(index, OPINION_URL)
    assert raised.value.refused_response.response_bytes == b"<html>Access Denied</html>"
    assert raised.value.supreme_court_acquisition["operation"] == "opinion-document"
    assert raised.value.supreme_court_acquisition["indexUrl"] == INDEX_URL


def test_budget_and_client_configuration_are_explicit():
    for fields in (
        {"max_requests": 0},
        {"max_index_bytes": 16 * 1024**2 + 1},
        {"max_document_bytes": 64 * 1024**2 + 1},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ):
        with pytest.raises(ValueError):
            SupremeCourtBudget(
                **{
                    "max_requests": 3,
                    "max_index_bytes": 4096,
                    "max_document_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        SupremeCourtAcquirer(budget=(3, 4096, 4096, 7, 0), transport=Transport())
