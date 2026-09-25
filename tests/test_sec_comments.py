"""SEC comment pages keep the publisher's spellings, prove their identity from their own statements, and
never read an empty or missing answer as absence; a comment file must be the format and docket it claims."""

import hashlib
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.sec_comments.acquisition import (
    CONTACT_EMAIL_ENVVAR,
    DEFAULT_CONTACT_EMAIL,
    SecCommentsAcquirer,
    SecCommentsBudget,
    SecCommentsRefusedError,
    SecCommentsUnavailableError,
    declared_user_agent,
    read_comment_file,
)
from spicy_docs.sources.sec_comments.pages import (
    SEC_SITE,
    SecCommentsSourceError,
    comment_index_url,
    parse_comment_listing_page,
    parse_rule_page,
    parse_rulemaking_index_page,
    requested_page_number,
    rulemaking_index_url,
)
from spicy_docs.sources.sec_comments.reader import SecCommentsReader
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "sec_comments"
#: Four rows of the 2026-09-24 rulemaking index render: a numbered proposal, a slug row with no
#: file number, a final S7 rule, and a multi-release rule whose link is a slug.
INDEX = (FIXTURES / "rulemaking-index.html").read_bytes()
RULE = (FIXTURES / "rule-page.html").read_bytes()
#: The same rows under a terminal pager (current page 1, a previous link, no next).
INDEX_TERMINAL = (FIXTURES / "rulemaking-index-terminal.html").read_bytes()
#: Page 0 of the S7-11-23 comment listing: h1, three letter-type sections, five comment rows
#: (four PDF and one HTML), pager current 0 with a next link.
LISTING = (FIXTURES / "comment-listing.html").read_bytes()
#: The listing's terminal page, trimmed and re-paged to page 1 so the fixture pair walks:
#: four .htm comment rows -- one of them the single-number ``s71123-542242.htm`` shape.
LISTING_TERMINAL = (FIXTURES / "comment-listing-terminal.html").read_bytes()
#: The same listing with its pager removed: a one-page docket.
LISTING_SINGLE = LISTING[: LISTING.index(b'<nav class="usa-pagination"')] + b"</div></body></html>\n"
#: One retained comment letter (HTML), trimmed; it states ``File No. S7-11-23`` in its own words.
COMMENT_HTML = (FIXTURES / "comment-file.html").read_bytes()
#: One retained letter-type A document, trimmed; its title states the file number too.
LETTER_TYPE_A = (FIXTURES / "comment-letter-type-a.htm").read_bytes()
#: First 1,024 bytes of s71123-279699-683202.pdf: a real header and a real truncated capture.
PDF_HEAD = (FIXTURES / "comment-file.pdf.head").read_bytes()
#: The length that PDF's own linearization dictionary states, and the length served.
PDF_BYTES = 84_116
#: The first-page cross-reference stream the head carries; a complete linearized file's last ``startxref`` names it.
FIRST_PAGE_XREF = PDF_HEAD.index(b"43 0 obj")
_PDF_END = f"startxref\n{FIRST_PAGE_XREF}\n%%EOF\n".encode()
#: The real header, padded to the length it states and ending on that pointer. Constructed, not served.
PDF_COMPLETE = PDF_HEAD + b"\x00" * (PDF_BYTES - len(PDF_HEAD) - len(_PDF_END)) + _PDF_END
_PLAIN_HEAD = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
#: A PDF that is not linearized, ending on a cross-reference table its own ``startxref`` names.
PDF_PLAIN = _PLAIN_HEAD + b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 1 >>\n"
PDF_PLAIN += f"startxref\n{len(_PLAIN_HEAD)}\n%%EOF\n".encode()
INDEX_URL = rulemaking_index_url()
RULE_URL = f"{SEC_SITE}/rules-regulations/2025/06/s7-11-23"
INDEX_PAGE_1 = rulemaking_index_url(page=1)
LISTING_URL = comment_index_url("S7-11-23")
LISTING_PAGE_1 = f"{LISTING_URL}?page=1"
COMMENT_PDF_URL = f"{SEC_SITE}/comments/s7-11-23/s71123-580435-1668442.pdf"
COMMENT_HTML_URL = f"{SEC_SITE}/comments/s7-11-23/s71123-420279-1002982.html"
SECTION_A_URL = f"{SEC_SITE}/comments/s7-11-23/s71123-typea.htm"
SECTION_C_URL = f"{SEC_SITE}/comments/s7-11-23/s71123-typec.pdf"
BUDGET = SecCommentsBudget(64, 4 * 1024 * 1024, 16 * 1024 * 1024, 7, 0)


def index_page(body=INDEX, url=INDEX_URL, **kwargs):
    return parse_rulemaking_index_page(body, url=url, **kwargs)


def listing_page(body=LISTING, url=LISTING_URL, **kwargs):
    return parse_comment_listing_page(body, url=url, **kwargs)


def read_file(body=PDF_COMPLETE, *, url=COMMENT_PDF_URL, media_type="application/pdf", final_url=None, **kwargs):
    return read_comment_file(
        body, url=url, media_type=media_type, final_url=url if final_url is None else final_url, **kwargs
    )


def response(body=INDEX, status=200, *, content_type="text/html; charset=utf-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class RoutingTransport(httpx.MockTransport):
    """Serves one canned response per exact URL, and records every call."""

    def __init__(self, routes):
        self.routes = dict(routes)
        self.calls = []

        def handle(request):
            self.calls.append(request)
            return self.routes[str(request.url)]

        super().__init__(handle)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_the_index_locator_and_the_docket_grammar_are_the_publishers_own():
    assert INDEX_URL == f"{SEC_SITE}/rules-regulations/rulemaking-activity"
    assert rulemaking_index_url(page=0) == f"{INDEX_URL}?page=0"
    assert requested_page_number(INDEX_URL) == 0 and requested_page_number(f"{INDEX_URL}?page=3") == 3
    for value in (-1, True, "3", 1.0):
        with pytest.raises(SecCommentsSourceError, match="page"):
            rulemaking_index_url(page=value)
    # S7-11-23's own rule page linked exactly this spelling on 2026-09-24.
    assert comment_index_url("S7-11-23") == f"{SEC_SITE}/comments/s7-11-23/s71123.htm"
    assert comment_index_url("SR-NASDAQ-2026-001") == f"{SEC_SITE}/comments/sr-nasdaq-2026-001/srnasdaq2026001.htm"
    for value in ("", " S7-11-23", "S7 11 23", "S7/11-23", None, 7):
        with pytest.raises(SecCommentsSourceError, match="dashed spelling"):
            comment_index_url(value)


def test_the_pinned_index_keeps_the_publisher_spellings():
    page = index_page()
    first, slug, final, multi = page.rulemakings
    assert first.file_number == "S7-2026-33" and first.status == "Proposed Rule"
    assert first.published == "2026-09-16T14:01:00Z"
    assert first.rule_url == f"{SEC_SITE}/rules-regulations/2026/09/s7-2026-33"
    assert first.title == "Proxy Solicitation Modernization"
    # A slug row states no file number; its rule page must be checked for comment links.
    assert slug.file_number is None and slug.rule_url == f"{SEC_SITE}/rules-regulations/2026/09/33-11438"
    assert final.file_number == "S7-11-23" and final.published == "2025-06-25T21:18:49Z"
    # A multi-release rulemaking is addressed by a descriptive slug, not its file number.
    assert multi.file_number == "S7-04-23"
    assert multi.rule_url == f"{SEC_SITE}/rules-regulations/2025/06/safeguarding-advisory-client-assets"
    assert page.pager.current_page == 0
    assert page.pager.next_url == INDEX_PAGE_1
    # The comment-index URL is derived per the measured grammar, and only a row with a file number has one.
    assert first.comment_index_url == f"{SEC_SITE}/comments/s7-2026-33/s7202633.htm"
    assert final.comment_index_url == LISTING_URL and slug.comment_index_url is None


def test_a_terminal_index_page_states_no_next_page():
    page = index_page(INDEX_TERMINAL, url=INDEX_PAGE_1)
    assert page.pager.current_page == 1 and page.pager.next_url is None
    assert [row.file_number for row in page.rulemakings] == ["S7-2026-33", None]


def test_every_index_row_has_a_stable_docket_key_and_slug_rows_keep_the_empty_cell():
    page = index_page()
    first, slug, final, multi = page.rulemakings
    # A row stating a file number keys on it; the multi-release row's descriptive
    # slug link still carries its file number cell, which is its key.
    assert first.docket_key == "S7-2026-33" and final.docket_key == "S7-11-23"
    assert multi.docket_key == "S7-04-23"
    # A row with an empty file-number cell keys on its rule-page slug, namespaced.
    assert slug.docket_key == "slug:33-11438"
    assert slug.file_number is None  # the empty cell is retained, never replaced
    assert slug.docket_key.startswith("slug:") and final.docket_key == final.file_number
    # The two namespaces are disjoint: a slug key can never collide with a file number.
    assert {row.docket_key for row in page.rulemakings} == {
        "S7-2026-33",
        "slug:33-11438",
        "S7-11-23",
        "S7-04-23",
    }


def test_a_row_stating_neither_a_file_number_nor_a_slug_refuses_a_key():
    from spicy_docs.sources.sec_comments.pages import SecRulemaking

    row = SecRulemaking(index=0, file_number=None, title="Bare row", status=None, published=None, rule_url=None)
    with pytest.raises(SecCommentsSourceError, match="neither a file number nor a rule page slug"):
        _ = row.docket_key


INDEX_REFUSALS = {
    "another page is served": (INDEX, INDEX_PAGE_1, "page 0, not the requested page 1"),
    "no rulemaking table": (b"<html><body>Checking your browser</body></html>", INDEX_URL, "no rulemaking table"),
    "an empty body": (b"", INDEX_URL, "empty"),
    "invalid UTF-8": (INDEX + b"\xff", INDEX_URL, "not the UTF-8"),
    "a row without a title": (INDEX.replace(b"Proxy Solicitation Modernization", b""), INDEX_URL, "no title"),
    "a second rulemaking table": (
        INDEX.replace(b"</table>", b"</table>" + INDEX[: INDEX.index(b"<tbody>")] + b"<tbody></table>"),
        INDEX_URL,
        "second rulemaking table",
    ),
    "a foreign status link": (
        INDEX.replace(
            b'href="/rules-regulations/2026/09/s7-2026-33', b'href="https://example.invalid/2026/09/s7-2026-33'
        ),
        INDEX_URL,
        "plain HTTPS sec.gov",
    ),
    "a cleartext status link": (
        INDEX.replace(b'href="/rules-regulations/', b'href="http://www.sec.gov/rules-regulations/', 1),
        INDEX_URL,
        "plain HTTPS sec.gov",
    ),
    "a query on a status link": (
        INDEX.replace(b"s7-2026-33#33-11439proposed", b"s7-2026-33?x=1"),
        INDEX_URL,
        "plain HTTPS sec.gov",
    ),
    "an off-site status link": (
        INDEX.replace(b"/rules-regulations/2026/09/", b"/elsewhere/2026/09/", 1),
        INDEX_URL,
        "/rules-regulations/",
    ),
    "a status link with credentials": (
        INDEX.replace(
            b'href="/rules-regulations/2026/09/s7-2026-33',
            b'href="https://user:pw@www.sec.gov/rules-regulations/2026/09/s7-2026-33',
        ),
        INDEX_URL,
        "plain HTTPS sec.gov",
    ),
    "two status links in one row": (
        INDEX.replace(
            b'<a class="more-link" href="?search=S7-11-23">View Related Activity</a>',
            b'<a class="info-button" href="/rules-regulations/2025/06/s7-11-23">View Related Activity</a>',
        ),
        INDEX_URL,
        "more than one status link",
    ),
    "nested status links": (
        INDEX.replace(
            b'<a class="node node--type-regulation node--view-mode-teaser info-button" href="/rules-regulations/2026/09/s7-2026-33#33-11439proposed">',
            b'<a class="node info-button" href="/rules-regulations/2026/09/s7-2026-33#33-11439proposed">'
            b'<a class="node info-button" href="/rules-regulations/2026/09/s7-2026-33#x">',
            1,
        ),
        INDEX_URL,
        "nests its links",
    ),
    "a repeated page parameter": (INDEX, f"{INDEX_URL}?page=1&page=2", "repeats its page parameter"),
}


@pytest.mark.parametrize("case", INDEX_REFUSALS, ids=list(INDEX_REFUSALS))
def test_index_refusals_name_the_failed_check(case):
    body, url, message = INDEX_REFUSALS[case]
    with pytest.raises(SecCommentsSourceError, match=message):
        index_page(body, url=url)


@pytest.mark.parametrize("max_bytes", [0, True, 16 * 1024**2 + 1, "4096"])
def test_index_bounds_are_explicit(max_bytes):
    with pytest.raises(SecCommentsSourceError, match="byte bound"):
        index_page(max_bytes=max_bytes)
    with pytest.raises(SecCommentsSourceError, match=f"exceeds its {len(INDEX) - 1}-byte bound"):
        index_page(max_bytes=len(INDEX) - 1)


def test_the_pinned_listing_states_its_title_sections_and_comment_files():
    page = listing_page()
    assert page.docket == "s7-11-23"
    assert page.title == (
        "Comments on Daily Computation of Customer and Broker-Dealer Reserve Requirements"
        " under the Broker-Dealer Customer Protection Rule"
    )
    assert [(s.label, s.format) for s in page.sections] == [("A: 2", "htm"), ("B: 3", "htm"), ("C: 5", "pdf")]
    assert page.sections[0].url == SECTION_A_URL and page.sections[2].url == SECTION_C_URL
    first, html = page.comments[0], page.comments[4]
    assert first.file_name == "s71123-580435-1668442.pdf" and first.format == "pdf"
    assert first.url == COMMENT_PDF_URL
    assert first.link_text == "Kevin A. Zambrowicz, Deputy General Counsel, (Institutional) & Managing Director, SIFMA"
    assert first.letter_type == "Public Comment" and first.date == "2025-02-27T12:00:00Z"
    # The listing's own row label distinguishes a meeting memorandum from a public comment.
    assert page.comments[2].letter_type == "Meeting with SEC Officials"
    assert html.format == "html" and html.link_text == "Cory" and html.date == "2024-02-02T12:00:00Z"
    assert page.pager.current_page == 0 and page.pager.next_url == LISTING_PAGE_1


def test_a_terminal_listing_page_and_a_single_page_listing():
    terminal = listing_page(LISTING_TERMINAL, url=LISTING_PAGE_1)
    assert terminal.pager.current_page == 1 and terminal.pager.next_url is None
    # File names are not all two-number stems: this page states single-number .htm files.
    assert {c.format for c in terminal.comments} == {"htm"}
    assert [c.file_name for c in terminal.comments] == [
        "s71123-542242.htm",
        "s71123-523702.htm",
        "s71123-505202.htm",
        "s71123-226239-473922.htm",
    ]
    assert terminal.comments[0].link_text == "Anonymous"
    # A docket with one page states no pager at all, and page 0 is still what it serves.
    single = listing_page(LISTING_SINGLE)
    assert single.pager.current_page is None and single.pager.next_url is None


def _listing_with_comments_tbody(inner: bytes) -> bytes:
    """Rebuild the listing with the comments table's tbody holding exactly ``inner``."""
    table = LISTING.index(b"cols-3")
    start = LISTING.index(b"<tbody>", table) + len(b"<tbody>")
    end = LISTING.index(b"</tbody>", start)
    return LISTING[:start] + inner + LISTING[end:]


#: The listing with an emptied comments tbody: present, and stating no comment rows.
LISTING_EMPTY_COMMENTS = _listing_with_comments_tbody(b"")


def test_a_listing_that_states_no_comment_rows_is_an_observation_not_absence():
    page = listing_page(LISTING_EMPTY_COMMENTS)
    assert page.comments == () and page.sections and page.pager.next_url == LISTING_PAGE_1


LISTING_REFUSALS = {
    "another page is served": (LISTING, LISTING_PAGE_1, "page 0, not the requested page 1"),
    "no comment table": (
        LISTING[: LISTING.rindex(b"<table", 0, LISTING.index(b"cols-3"))] + b"</div></body></html>",
        LISTING_URL,
        "no comment table",
    ),
    "a challenge page": (b"<html><body>Access denied</body></html>", LISTING_URL, "no comment table"),
    "an empty body": (b"", LISTING_URL, "empty"),
    "a link outside its docket": (
        LISTING.replace(b"/comments/s7-11-23/s71123-typeb.htm", b"/comments/s7-12-23/s71123-typeb.htm"),
        LISTING_URL,
        "leaves its docket",
    ),
    "a foreign file host": (
        LISTING.replace(
            b'href="/comments/s7-11-23/s71123-typea.htm"', b'href="https://example.invalid/s71123-typea.htm"'
        ),
        LISTING_URL,
        "plain HTTPS sec.gov",
    ),
    "a link with a query": (
        LISTING.replace(b"s71123-typeb.htm", b"s71123-typeb.htm?x=1"),
        LISTING_URL,
        "plain HTTPS sec.gov",
    ),
    "an unknown format": (
        LISTING.replace(b"s71123-typea.htm", b"s71123-typea.docx"),
        LISTING_URL,
        "format this route does not read",
    ),
    "a row without its link": (
        LISTING.replace(b'<a href="/comments/s7-11-23/s71123-580455-1668442.pdf">', b""),
        LISTING_URL,
        "exactly one link",
    ),
    "a link with no target": (
        LISTING.replace(b'<a href="/comments/s7-11-23/s71123-typea.htm">', b"<a>"),
        LISTING_URL,
        "states no target",
    ),
    "nested links": (
        LISTING.replace(
            b'<td headers="view-nothing-table-column" class="views-field views-field-nothing"><a href="/comments/s7-11-23/s71123-580435-1668442.pdf">',
            b'<td headers="view-nothing-table-column" class="views-field views-field-nothing"><a href="/comments/s7-11-23/s71123-580435-1668442.pdf"><a href="/comments/s7-11-23/x.pdf">',
            1,
        ),
        LISTING_URL,
        "nests its links",
    ),
    "a pager with no page on a later request": (LISTING_SINGLE, LISTING_PAGE_1, "only page where page 1"),
}


@pytest.mark.parametrize("case", LISTING_REFUSALS, ids=list(LISTING_REFUSALS))
def test_listing_refusals_name_the_failed_check(case):
    body, url, message = LISTING_REFUSALS[case]
    with pytest.raises(SecCommentsSourceError, match=message):
        listing_page(body, url=url)


def test_a_listing_url_outside_the_comments_grammar_is_refused():
    for url in (
        INDEX_URL,
        f"{SEC_SITE}/comments/s7-11-23/",
        f"{SEC_SITE}/comments/",
        "http://www.sec.gov/comments/s7-11-23/s71123.htm",
        "https://user:secret@www.sec.gov/comments/s7-11-23/s71123.htm",
        "https://www.sec.gov:444/comments/s7-11-23/s71123.htm",
    ):
        with pytest.raises(SecCommentsSourceError):
            listing_page(url=url)


@pytest.mark.parametrize("authority", ["user:secret@www.sec.gov", "www.sec.gov:444"])
def test_file_locators_cannot_add_credentials_or_a_port(authority):
    transport = RoutingTransport({})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsSourceError, match="HTTPS sec.gov"),
    ):
        source.acquire_comment_file(COMMENT_PDF_URL.replace("www.sec.gov", authority))
    assert transport.calls == []


def test_the_real_pdf_header_states_its_own_length_and_the_truncated_capture_is_refused():
    form, version, length = read_file()
    assert (form, version, length) == ("pdf", "1.6", PDF_BYTES)
    assert b"%%EOF" in PDF_HEAD  # the trailer alone cannot see this truncation
    with pytest.raises(SecCommentsSourceError, match="shorter than its stated length"):
        read_file(PDF_HEAD)


@pytest.mark.parametrize("pointer", [b"0", str(FIRST_PAGE_XREF).encode()])
def test_a_first_page_section_cut_at_its_own_eof_is_refused_whatever_its_pointer(pointer):
    # The linearized first-page section ends ``startxref 0 %%EOF``; a producer that wrote the
    # first-page xref offset instead would pass the pointer check, so the stated length decides.
    cut = PDF_HEAD[: PDF_HEAD.index(b"%%EOF") + len(b"%%EOF\r\n")]
    with pytest.raises(SecCommentsSourceError, match="shorter than its stated length"):
        read_file(cut.replace(b"startxref\r\n0\r\n", b"startxref\r\n" + pointer + b"\r\n"))


def test_real_incrementally_updated_pdf_preserves_its_stale_linearization_hint():
    body = (FIXTURES / "comment-file-incremental.pdf").read_bytes()
    assert len(body) == 69_393
    assert read_file(body) == ("pdf", "1.6", 65_314)
    # A stated length past the capture is truncation, never a stale hint.
    with pytest.raises(SecCommentsSourceError, match="shorter than its stated length"):
        read_file(body.replace(b"/L 65314", b"/L 99999", 1))
    # Past /L, the last pointer must name the appended revision's xref, not the original's.
    with pytest.raises(SecCommentsSourceError, match="runs past its stated length"):
        read_file(body + f"startxref\n{FIRST_PAGE_XREF}\n%%EOF\n".encode())
    # A cut exactly at the original revision's end is that complete original file.
    assert read_file(body[:65_314]) == ("pdf", "1.6", 65_314)


@pytest.mark.parametrize(
    "body",
    [
        PDF_COMPLETE + b"1 0 obj\n<< /Contents (unfinished update)",
        PDF_COMPLETE + b"\nstartxref\n0\n%%EOF\n",
        PDF_COMPLETE + b"\nstartxref\n999999\n%%EOF\n",
        PDF_COMPLETE + b"\nstartxref\n1000\n%%EOF\n",
    ],
)
def test_stale_linearization_does_not_accept_an_incomplete_appended_revision(body):
    with pytest.raises(SecCommentsSourceError, match="terminal cross-reference"):
        read_file(body)


def test_stale_linearization_accepts_an_ordinary_cross_reference_table():
    # A bounded constructed tail covers the table alternative to the real xref-stream fixture.
    body = PDF_COMPLETE + b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 1 >>\n"
    body += f"startxref\n{len(PDF_COMPLETE)}\n%%EOF\n".encode()
    assert read_file(body) == ("pdf", "1.6", PDF_BYTES)


@pytest.mark.parametrize(
    "object_body",
    [
        b"2 0 obj <</Type/Catalog>> endobj\n3 0 obj <</Type/XRef>> stream\nx\nendstream\nendobj\n",
        b"2 0 obj /Type/XRef stream\nx\nendstream\nendobj\n",
        b"2 0 obj <</Type/XRef-malformed>> stream\nx\nendstream\nendobj\n",
    ],
)
def test_terminal_pointer_must_name_its_own_cross_reference_stream(object_body):
    body = PDF_COMPLETE + object_body + f"startxref\n{len(PDF_COMPLETE)}\n%%EOF\n".encode()
    with pytest.raises(SecCommentsSourceError, match="terminal cross-reference"):
        read_file(body)


@pytest.mark.parametrize(
    "body,message",
    [
        (b"<!DOCTYPE html><html>Access denied</html>", "%PDF- magic"),
        (b"%PDF1.6\n%%EOF\n", "%PDF- magic"),
        (b"%PDF-1.6\n" + b"x" * 2048, "trailer"),
        (b"", "empty"),
    ],
)
def test_pdf_refusals_name_the_failed_check(body, message):
    with pytest.raises(SecCommentsSourceError, match=message):
        read_file(body)


def test_a_pdf_that_states_no_length_is_read_but_its_end_is_still_proved():
    assert read_file(PDF_PLAIN) == ("pdf", "1.4", None)
    # A revision cut short inside the last KiB keeps the old %%EOF there; the final pointer refuses it.
    with pytest.raises(SecCommentsSourceError, match="terminal cross-reference"):
        read_file(PDF_PLAIN + b"2 0 obj\n<< /Contents (unfinished update")
    with pytest.raises(SecCommentsSourceError, match="terminal cross-reference"):
        read_file(b"%PDF-1.4\n" + b"x" * 64 + b"\n%%EOF\n")


def test_an_html_comment_states_its_docket_in_its_own_words():
    assert read_file(COMMENT_HTML, url=COMMENT_HTML_URL, media_type="text/html") == ("html", None, None)
    assert read_file(LETTER_TYPE_A, url=SECTION_A_URL, media_type="text/html") == ("htm", None, None)


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"media_type": "text/plain"}, "not served as text/html"),
        ({"media_type": "application/pdf"}, "not served as text/html"),
        ({"body": PDF_HEAD}, "does not begin as HTML"),
        ({"body": COMMENT_HTML.replace(b"File No. S7-11-23", b"File No. S7-12-23")}, "does not state the docket"),
        ({"body": b""}, "empty"),
        ({"final_url": COMMENT_HTML_URL + "?x=1"}, "final URL"),
    ],
)
def test_html_comment_refusals_name_the_failed_check(kwargs, message):
    defaults = {"body": COMMENT_HTML, "url": COMMENT_HTML_URL, "media_type": "text/html"}
    with pytest.raises(SecCommentsSourceError, match=message):
        read_file(**{**defaults, **kwargs})


def test_the_media_type_must_agree_with_the_locators_format():
    with pytest.raises(SecCommentsSourceError, match="not served as application/pdf"):
        read_file(COMMENT_HTML, media_type="text/html")


@pytest.mark.parametrize("max_bytes", [0, True, 512 * 1024**2 + 1, "4096"])
def test_file_bounds_are_explicit(max_bytes):
    with pytest.raises(SecCommentsSourceError, match="max_bytes"):
        read_file(max_bytes=max_bytes)
    with pytest.raises(SecCommentsSourceError, match=f"exceeds its {PDF_BYTES - 1}-byte bound"):
        read_file(max_bytes=PDF_BYTES - 1)


def test_the_user_agent_declares_the_project_and_a_contact_mailbox():
    default = declared_user_agent()
    assert default.startswith("spicy-docs-sec-comments/1.0 (SpicyDocs SEC rulemaking comments; contact: ")
    assert DEFAULT_CONTACT_EMAIL in default
    assert declared_user_agent("ops@example.org").endswith("ops@example.org)")
    assert "Mozilla" not in default  # never a browser spoof
    for bad in ("ops@example.org\nInjected: x", "a b", "ops@localhost"):
        with pytest.raises(SecCommentsSourceError, match="contact email"):
            declared_user_agent(bad)


def test_a_live_acquirer_refuses_the_reserved_placeholder_mailbox(monkeypatch):
    monkeypatch.delenv(CONTACT_EMAIL_ENVVAR, raising=False)
    with pytest.raises(SecCommentsSourceError, match=CONTACT_EMAIL_ENVVAR):
        SecCommentsAcquirer(budget=BUDGET)
    with pytest.raises(SecCommentsSourceError, match=CONTACT_EMAIL_ENVVAR):
        SecCommentsAcquirer(budget=BUDGET, user_agent=declared_user_agent("crawler@sec.invalid"))
    monkeypatch.setenv(CONTACT_EMAIL_ENVVAR, "crawler@example.org")
    SecCommentsAcquirer(budget=BUDGET).close()  # a real mailbox; no request is made


@pytest.mark.parametrize(
    "agent",
    [
        " ",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "spicy-docs/1.0 (no contact stated)",
        "spicy-docs/1.0 (SEC comments; contact: ops@example.org)\r\nX-Injected: 1",
    ],
)
def test_a_user_agent_override_must_declare_a_contact(agent):
    with pytest.raises(SecCommentsSourceError, match="user_agent must declare"):
        SecCommentsAcquirer(budget=BUDGET, user_agent=agent, transport=RoutingTransport({}))


def test_acquirer_sends_the_declared_agent_and_captures_exact_index_bytes():
    transport = RoutingTransport({INDEX_URL: response(INDEX)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_rulemaking_index_page()
    assert result.capture.body == INDEX and result.capture.requested_url == INDEX_URL
    assert result.capture.sha256 == "sha256:" + hashlib.sha256(INDEX).hexdigest()
    assert len(result.page.rulemakings) == 4 and result.request_count == 1 and result.budget == BUDGET
    request = transport.calls[0]
    assert request.method == "GET" and str(request.url) == INDEX_URL
    assert request.headers["user-agent"].startswith("spicy-docs-sec-comments/1.0")
    assert "contact:" in request.headers["user-agent"]
    assert request.headers["accept-encoding"] == "identity"


def test_an_operator_mailbox_travels_through_the_environment(monkeypatch):
    monkeypatch.setenv(CONTACT_EMAIL_ENVVAR, "crawler@example.org")
    transport = RoutingTransport({INDEX_URL: response(INDEX)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        source.acquire_rulemaking_index_page()
    assert "crawler@example.org" in transport.calls[0].headers["user-agent"]


def test_the_index_walk_follows_the_pagers_own_links_to_a_terminal_page():
    transport = RoutingTransport({INDEX_URL: response(INDEX), INDEX_PAGE_1: response(INDEX_TERMINAL)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        acquisitions = list(source.walk_rulemaking_index())
    assert [a.page.pager.current_page for a in acquisitions] == [0, 1]
    assert [a.page.url for a in acquisitions] == [INDEX_URL, INDEX_PAGE_1]
    assert len(transport.calls) == 2


def test_a_walk_that_repeats_its_continuation_refuses():
    repeating = INDEX.replace(b'href="?page=1"', b'href="?page=0"')
    routes = {INDEX_URL: response(repeating), f"{INDEX_URL}?page=0": response(repeating)}
    transport = RoutingTransport(routes)
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsSourceError, match="repeated its continuation"),
    ):
        list(source.walk_rulemaking_index())


@pytest.mark.parametrize(
    "walk,start,body,continuation",
    [
        ("walk_comment_listing", LISTING_URL, LISTING, b'href="/comments/s7-12-23/s71223.htm?page=1"'),
        ("walk_rulemaking_index", INDEX_URL, INDEX, b'href="?page=1&amp;search=other"'),
        (
            "walk_rulemaking_index",
            INDEX_URL,
            INDEX,
            b'href="http://www.sec.gov/rules-regulations/rulemaking-activity?page=1"',
        ),
    ],
)
def test_a_walk_refuses_a_continuation_outside_its_own_route(walk, start, body, continuation):
    transport = RoutingTransport({start: response(body.replace(b'href="?page=1"', continuation))})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsSourceError, match="outside the walk's own route"),
    ):
        list(getattr(source, walk)(start))
    assert [str(call.url) for call in transport.calls] == [start]


def test_the_listing_walk_reaches_the_terminal_page():
    transport = RoutingTransport({LISTING_URL: response(LISTING), LISTING_PAGE_1: response(LISTING_TERMINAL)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        pages = list(source.walk_comment_listing(LISTING_URL))
    assert [p.page.pager.current_page for p in pages] == [0, 1]
    assert pages[1].page.comments[0].file_name == "s71123-542242.htm"


def test_a_page_bound_reached_with_a_next_page_outstanding_refuses():
    always_next = RoutingTransport({LISTING_URL: response(LISTING)})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=always_next) as source,
        pytest.raises(SecCommentsSourceError, match="page bound reached"),
    ):
        list(source.walk_comment_listing(LISTING_URL, max_pages=1))


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(b"<html>404</html>", 404), SecCommentsUnavailableError, "HTTP 404"),
        (response(b"", 410), SecCommentsUnavailableError, "HTTP 410"),
        (response(b"<html>403</html>", 403), SecCommentsRefusedError, "refused"),
        (response(b"<html>401</html>", 401), SecCommentsRefusedError, "refused"),
        (response(b"{}", content_type="application/json"), SecCommentsSourceError, "Content-Type"),
        (
            response(b"<html>Challenge</html>", content_type="text/html; charset=utf-8"),
            SecCommentsSourceError,
            "no rulemaking table",
        ),
    ],
)
def test_wrong_shape_or_missing_pages_never_succeed(answer, error, message):
    transport = RoutingTransport({INDEX_URL: answer})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(error, match=message) as raised,
    ):
        source.acquire_rulemaking_index_page()
    assert raised.value.sec_comments_acquisition["operation"] == "rulemaking-index-page"
    assert raised.value.sec_comments_acquisition["url"] == INDEX_URL


def test_a_refusal_keeps_its_bytes_and_never_names_absence():
    transport = RoutingTransport({COMMENT_PDF_URL: response(b"<html>Denied</html>", 403)})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsRefusedError, match="never an observation of absence") as raised,
    ):
        source.acquire_comment_file(url=COMMENT_PDF_URL)
    assert raised.value.refused_response.response_bytes == b"<html>Denied</html>"
    assert raised.value.sec_comments_acquisition["docket"] == "s7-11-23"


def test_one_comment_file_is_captured_with_its_proofs():
    transport = RoutingTransport({COMMENT_PDF_URL: response(PDF_COMPLETE, content_type="application/pdf")})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_comment_file(url=COMMENT_PDF_URL)
    assert result.format == "pdf" and result.pdf_version == "1.6"
    assert result.linearized_length == PDF_BYTES and result.capture.byte_size == PDF_BYTES
    assert result.capture.body == PDF_COMPLETE and result.request_count == 1
    assert result.sha256 == "sha256:" + hashlib.sha256(PDF_COMPLETE).hexdigest()


def test_a_letter_type_section_object_names_the_file_to_capture():
    section = listing_page().sections[0]
    transport = RoutingTransport({SECTION_A_URL: response(LETTER_TYPE_A)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_comment_file(section=section)
    assert result.format == "htm" and result.file_name == "s71123-typea.htm"
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(SecCommentsSourceError, match="exactly one"):
            source.acquire_comment_file(url=COMMENT_PDF_URL, section=section)
        with pytest.raises(SecCommentsSourceError, match="exactly one"):
            source.acquire_comment_file()


def test_a_file_answer_in_the_other_formats_shape_is_refused_with_its_bytes():
    transport = RoutingTransport({COMMENT_PDF_URL: response(COMMENT_HTML, content_type="application/pdf")})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsSourceError, match="%PDF- magic") as raised,
    ):
        source.acquire_comment_file(url=COMMENT_PDF_URL)
    assert raised.value.sec_comments_acquisition["operation"] == "comment-file"
    assert raised.value.refused_response.response_bytes == COMMENT_HTML


def test_a_narrowed_byte_bound_refuses_a_larger_response_with_its_evidence():
    transport = RoutingTransport({COMMENT_PDF_URL: response(PDF_COMPLETE, content_type="application/pdf")})
    acquirer = SecCommentsAcquirer(budget=BUDGET, transport=transport)
    with acquirer as source, pytest.raises(SecCommentsSourceError) as raised:
        source.acquire_comment_file(url=COMMENT_PDF_URL, max_bytes=512)
    assert raised.value.sec_comments_acquisition["maxBytes"] == 512
    assert raised.value.refused_response.unavailable_reason == "response-byte-limit"


def test_budget_and_client_configuration_are_explicit():
    base = {
        "max_requests": 4,
        "max_page_bytes": 4 * 1024**2,
        "max_comment_bytes": 16 * 1024**2,
        "timeout_seconds": 7,
        "min_request_interval_seconds": 0,
    }
    for field, value in (
        ("max_requests", 0),
        ("max_page_bytes", 16 * 1024**2 + 1),
        ("max_comment_bytes", 512 * 1024**2 + 1),
        ("timeout_seconds", 0),
        ("min_request_interval_seconds", -1),
    ):
        with pytest.raises(ValueError, match=field):
            SecCommentsBudget(**{**base, field: value})
    with pytest.raises(TypeError):
        SecCommentsAcquirer(budget=(4, 4, 16, 7, 0))
    with pytest.raises(ValueError, match="user_agent"):
        SecCommentsAcquirer(budget=BUDGET, user_agent=" ")


#: Every file the two fixture pages state that no route serves, so the pass observes their 404s.
UNANSWERED = tuple(
    f"{SEC_SITE}/comments/s7-11-23/{name}"
    for name in (
        "s71123-typeb.htm",
        "s71123-typec.pdf",
        "s71123-580455-1668442.pdf",
        "s71123-548455-1571682.pdf",
        "s71123-548295-1570963.pdf",
        "s71123-542242.htm",
        "s71123-523702.htm",
        "s71123-505202.htm",
        "s71123-226239-473922.htm",
    )
)


def _reader_routes():
    return {
        LISTING_URL: response(LISTING),
        LISTING_PAGE_1: response(LISTING_TERMINAL),
        COMMENT_PDF_URL: response(PDF_COMPLETE, content_type="application/pdf"),
        COMMENT_HTML_URL: response(COMMENT_HTML),
        SECTION_A_URL: response(LETTER_TYPE_A),
        **{url: response(b"<html>404</html>", 404) for url in UNANSWERED},
    }


def test_the_reader_captures_every_file_the_listing_stated_with_evidence():
    transport = RoutingTransport(_reader_routes())
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, dockets=["S7-11-23"])
        records = list(reader.iter_records())
    # Twelve files are stated across the two pages; three routes served bytes, nine answered 404.
    assert len(records) == 3 and len(reader.failed_keys) == 9
    kinds = [record["kind"] for record in records]
    assert kinds.count("sec-comment") == 2 and kinds.count("sec-comment-section") == 1
    first = records[0]
    assert first["url"] == SECTION_A_URL and first["format"] == "htm"
    assert first["docket"] == "s7-11-23" and first["rule_title"] == listing_page().title
    assert (
        first["body"] == LETTER_TYPE_A and first["body_sha256"] == "sha256:" + hashlib.sha256(LETTER_TYPE_A).hexdigest()
    )
    assert first["listing_sha256"] == "sha256:" + hashlib.sha256(LISTING).hexdigest()
    assert first["captured_at"] and first["byte_size"] == len(LETTER_TYPE_A)
    pdf = next(record for record in records if record["format"] == "pdf")
    assert pdf["pdf_version"] == "1.6" and pdf["linearized_length"] == PDF_BYTES
    html = next(record for record in records if record["format"] == "html")
    assert html["link_text"] == "Cory" and html["letter_type"] == "Public Comment"
    assert html["date"] == "2024-02-02T12:00:00Z" and html["content_type"].startswith("text/html")
    # Every record's listing digest names a render the reader retained.
    assert [page.capture.body for page in reader.listing_pages] == [LISTING, LISTING_TERMINAL]
    assert {record["listing_sha256"] for record in records} <= {p.capture.sha256 for p in reader.listing_pages}
    # Keys are exactly the captured file URLs; the unanswered ones failed and retry next run.
    assert reader.last_keys == [record["url"] for record in records]
    assert sorted(reader.failed_keys) == sorted(UNANSWERED)
    assert all("HTTP 404" in failure["reason"] for failure in reader.failures)


def test_processed_keys_skip_capture_and_a_docket_without_a_listing_is_not_zero():
    routes = {comment_index_url("S7-12-23"): response(b"<html>404</html>", 404), **_reader_routes()}
    transport = RoutingTransport(routes)
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, dockets=["S7-12-23", "S7-11-23"], processed_keys=[SECTION_A_URL])
        records = list(reader.iter_records())
    # The 404 docket left its listing URL in failed_keys and asserted nothing about its comments.
    assert comment_index_url("S7-12-23") in reader.failed_keys
    assert {record["docket"] for record in records} == {"s7-11-23"}
    assert SECTION_A_URL not in reader.last_keys and SECTION_A_URL not in reader.failed_keys


def test_a_mid_walk_refusal_leaves_the_docket_unresolved_for_the_next_run():
    broken_page = RoutingTransport({LISTING_URL: response(LISTING), LISTING_PAGE_1: response(b"<html>x</html>", 200)})
    with SecCommentsAcquirer(budget=BUDGET, transport=broken_page) as source:
        reader = SecCommentsReader(acquirer=source, dockets=["S7-11-23"])
        records = list(reader.iter_records())
    assert records == [] and reader.last_keys == []
    assert LISTING_PAGE_1 in reader.failed_keys and reader.failures[0]["url"] == LISTING_PAGE_1
    # The render captured before the walk failed is still retained.
    assert [page.capture.body for page in reader.listing_pages] == [LISTING]


def test_a_refusal_ends_the_pass_instead_of_skipping_a_row():
    refusing = RoutingTransport({LISTING_URL: response(b"<html>Denied</html>", 403)})
    with SecCommentsAcquirer(budget=BUDGET, transport=refusing) as source:
        reader = SecCommentsReader(acquirer=source, dockets=["S7-11-23"])
        with pytest.raises(SecCommentsRefusedError):
            list(reader.iter_records())
    assert reader.last_keys == [] and reader.failed_keys == []


def test_reader_configuration_is_explicit():
    with SecCommentsAcquirer(budget=BUDGET, transport=RoutingTransport({})) as source:
        with pytest.raises(TypeError):
            SecCommentsReader(acquirer="not an acquirer", dockets=["S7-11-23"])
        for bad in ([], [""]):
            with pytest.raises(ValueError, match="dockets"):
                SecCommentsReader(acquirer=source, dockets=bad)


def _rule_with_links(*hrefs):
    """Constructed rule without a file number, to isolate stated-link behavior."""
    links = "".join(f'<div class="field__item"><a href="{href}">View Received Comments</a></div>' for href in hrefs)
    return (
        "<html><body><h1>Rule with no file-number statement</h1>"
        '<div class="field field--name-field-comments-received field--label-hidden">' + links + "</div></body></html>"
    ).encode()


def test_rule_page_discovers_only_the_publishers_received_comments_field():
    page = parse_rule_page(RULE, url=RULE_URL)
    assert page.comment_listing_urls == (LISTING_URL,)
    outside = b'<nav><a href="https://outside.example/comments/ignored.htm">Comments</a></nav>'
    script = b'<script>"<div class=field--name-field-comments-received><a href=x>ignore</a></div>"</script>'
    body = (
        outside
        + script
        + _rule_with_links(
            "/comments/sr-nyse-2026-1/publisher-listing.html",
            "https://www.sec.gov/comments/sr-nyse-2026-1/publisher-listing.html",
            "/comments/s7-11-23/received.htm",
        )
    )
    page = parse_rule_page(body, url=RULE_URL)
    assert page.file_number is None
    assert page.comment_listing_urls == (
        f"{SEC_SITE}/comments/sr-nyse-2026-1/publisher-listing.html",
        f"{SEC_SITE}/comments/s7-11-23/received.htm",
    )


def test_live_slug_rule_fixtures_keep_stated_links_and_no_link_observations():
    url = (
        f"{SEC_SITE}/rules-regulations/2025/09/"
        "electronic-submission-certain-material-under-securities-exchange-act-1934-amendments-regarding-focus"
    )
    page = parse_rule_page((FIXTURES / "rule-page-slug.html").read_bytes(), url=url)
    assert page.file_number == "s7-08-23"
    assert page.comment_listing_urls == (f"{SEC_SITE}/comments/s7-08-23/s70823.htm",)
    url = f"{SEC_SITE}/rules-regulations/2026/07/modernization-delegations-authority-commission-staff"
    page = parse_rule_page((FIXTURES / "rule-page-no-listing.html").read_bytes(), url=url)
    assert page.file_number is None and page.comment_listing_urls == ()
    assert page.release_numbers == ("33-11431",)


def test_live_listing_keeps_the_publishers_uppercase_docket_path_through_acquisition():
    listing = parse_comment_listing_page(
        (FIXTURES / "comment-listing-case.html").read_bytes(),
        url=f"{SEC_SITE}/comments/s7-08-23/s70823.htm",
    )
    comment = listing.comments[0]
    assert comment.docket == "s7-08-23"
    assert comment.url == f"{SEC_SITE}/comments/S7-08-23/s70823-810619-2468353.pdf"
    transport = RoutingTransport({comment.url: response(PDF_COMPLETE, content_type="application/pdf")})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_comment_file(comment.url)
    assert result.url == comment.url and str(transport.calls[0].url) == comment.url


@pytest.mark.parametrize(
    "href",
    [
        "",
        " /comments/s7-11-23/s71123.htm",
        "/comme\nnts/s7-11-23/s71123.htm",
        "https://other.example/comments/s7-11-23/s71123.htm",
        "http://www.sec.gov/comments/s7-11-23/s71123.htm",
        "https://user:secret@www.sec.gov/comments/s7-11-23/s71123.htm",
        "https://www.sec.gov:444/comments/s7-11-23/s71123.htm",
        "/comments/s7-11-23/s71123.htm?key=secret",
        "/comments/s7-11-23/s71123.htm#section",
        "/comments/s7-11-23/s71123.pdf",
        "/outside/s7-11-23/s71123.htm",
        "/comments/s7-11-23/nested/s71123.htm",
        "https://[broken",
        "x" * 4097,
    ],
)
def test_an_unusable_stated_listing_link_refuses_instead_of_becoming_no_link(href):
    with pytest.raises(SecCommentsSourceError):
        parse_rule_page(_rule_with_links(href), url=RULE_URL)


def test_a_missing_listing_target_refuses_and_a_missing_field_remains_an_observation():
    with pytest.raises(SecCommentsSourceError, match="target"):
        parse_rule_page(_rule_with_links("x").replace(b'href="x"', b""), url=RULE_URL)
    page = parse_rule_page(b"<h1>Rule without an offered listing</h1>", url=RULE_URL)
    assert page.comment_listing_urls == ()
    with pytest.raises(SecCommentsSourceError, match="more comment listings"):
        parse_rule_page(_rule_with_links(*([LISTING_URL] * 65)), url=RULE_URL)


def test_rule_page_acquisition_retains_the_discovery_body_and_drops_the_anchor():
    transport = RoutingTransport({RULE_URL: response(RULE)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_rule_page(RULE_URL + "#release")
    assert result.page.comment_listing_urls == (LISTING_URL,)
    assert result.capture.body == RULE and result.capture.requested_url == RULE_URL
    assert result.request_count == 1 and len(transport.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        RULE_URL + "?key=secret",
        RULE_URL.replace("www.sec.gov", "user:secret@www.sec.gov"),
        RULE_URL.replace("www.sec.gov", "www.sec.gov:444"),
        "https://[broken",
        LISTING_URL,
    ],
)
def test_rule_page_locators_are_validated_before_sending_a_request(url):
    transport = RoutingTransport({})
    with (
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(SecCommentsSourceError, match="rule page URL"),
    ):
        source.acquire_rule_page(url)
    assert transport.calls == []


@pytest.mark.parametrize("status", [401, 403])
def test_rule_discovery_refusal_stops_before_another_selected_rule(status):
    transport = RoutingTransport({RULE_URL: response(b"Denied", status)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, rule_urls=[RULE_URL, RULE_URL.replace("s7-11-23", "s7-12-23")])
        with pytest.raises(SecCommentsRefusedError) as raised:
            list(reader.iter_records())
    assert raised.value.sec_comments_acquisition["operation"] == "rule-page"
    assert len(transport.calls) == 1 and reader.discovery_outcomes == []


def test_reader_uses_the_stated_listing_spelling_and_keeps_rule_evidence_on_files():
    stated_url = f"{SEC_SITE}/comments/s7-11-23/received-comments.html"
    rule = _rule_with_links(stated_url)
    routes = {**_reader_routes(), RULE_URL: response(rule), stated_url: response(LISTING_SINGLE)}
    del routes[LISTING_URL]
    transport = RoutingTransport(routes)
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, rule_urls=[RULE_URL, RULE_URL + "#release"])
        records = list(reader.iter_records())
    assert len(records) == 3
    assert [str(call.url) for call in transport.calls[:2]] == [RULE_URL, stated_url]
    assert all(record["listing_url"] == stated_url for record in records)
    assert all(record["listing_discovery"] == "publisher-stated" for record in records)
    assert all(record["rule_page_url"] == RULE_URL for record in records)
    assert all(record["rule_page_sha256"] == "sha256:" + hashlib.sha256(rule).hexdigest() for record in records)
    assert reader.last_keys == [record["url"] for record in records]
    assert reader.rule_pages[0].capture.body == rule and len(reader.rule_pages) == 1
    assert reader.discovery_outcomes[0]["comment_listing_urls"] == (stated_url,)
    assert reader.discovery_outcomes[0]["outcome"] == "links-stated"


def test_rule_reader_resume_skips_successes_and_retries_failed_files():
    routes = {**_reader_routes(), RULE_URL: response(_rule_with_links(LISTING_URL))}
    transport = RoutingTransport(routes)
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(
            acquirer=source, rule_urls=[RULE_URL], processed_keys=[SECTION_A_URL, COMMENT_PDF_URL]
        )
        records = list(reader.iter_records())
    assert [record["url"] for record in records] == [COMMENT_HTML_URL]
    assert sorted(reader.failed_keys) == sorted(UNANSWERED)
    assert SECTION_A_URL not in {str(call.url) for call in transport.calls}
    assert COMMENT_PDF_URL not in {str(call.url) for call in transport.calls}


def test_a_listing_two_rule_pages_state_is_walked_once():
    other_rule = RULE_URL.replace("s7-11-23", "s7-11-23-extension")
    routes = {
        **_reader_routes(),
        RULE_URL: response(_rule_with_links(LISTING_URL)),
        other_rule: response(_rule_with_links(LISTING_URL)),
    }
    transport = RoutingTransport(routes)
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, rule_urls=[RULE_URL, other_rule])
        records = list(reader.iter_records())
    urls = [str(call.url) for call in transport.calls]
    assert urls.count(LISTING_URL) == urls.count(LISTING_PAGE_1) == 1
    assert len(records) == 3 and len(reader.listing_pages) == 2
    assert [outcome["rule_page_url"] for outcome in reader.discovery_outcomes] == [RULE_URL, other_rule]


def test_rule_without_listing_links_keeps_its_capture_and_does_not_invent_a_locator():
    body = b"<h1>Rule that offers no comment-listing link</h1>"
    transport = RoutingTransport({RULE_URL: response(body)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, rule_urls=[RULE_URL])
        assert list(reader.iter_records()) == []
    assert reader.last_keys == reader.failed_keys == []
    assert reader.rule_pages[0].capture.body == body
    assert reader.discovery_outcomes == [
        {
            "rule_page_url": RULE_URL,
            "rule_page_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
            "comment_listing_urls": (),
            "outcome": "no-listing-link-stated",
        }
    ]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("body,status", [(b"missing", 404), (b"<html>Challenge</html>", 200)])
def test_failed_rule_discovery_remains_retryable(body, status):
    transport = RoutingTransport({RULE_URL: response(body, status)})
    with SecCommentsAcquirer(budget=BUDGET, transport=transport) as source:
        reader = SecCommentsReader(acquirer=source, rule_urls=[RULE_URL])
        assert list(reader.iter_records()) == []
    assert reader.failed_keys == [RULE_URL] and not reader.discovery_outcomes
    assert len(transport.calls) == 1


def test_rule_and_legacy_reader_selections_are_explicit_alternatives():
    with SecCommentsAcquirer(budget=BUDGET, transport=RoutingTransport({})) as source:
        for options in ({}, {"dockets": [], "rule_urls": [RULE_URL]}, {"rule_urls": []}, {"rule_urls": RULE_URL}):
            with pytest.raises(ValueError, match="dockets|rule_urls"):
                SecCommentsReader(acquirer=source, **options)
        with pytest.raises(ValueError, match="max_listing_pages"):
            SecCommentsReader(acquirer=source, rule_urls=[RULE_URL], max_listing_pages=0)
