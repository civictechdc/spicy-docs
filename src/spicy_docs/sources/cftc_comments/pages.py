"""CFTC comment-portal pages as comments.cftc.gov states them, read in one linear pass.

The portal is a server-rendered ASP.NET WebForms application behind Cloudflare;
there is no JSON API, and the pages' own GET-reachable anchors carry the whole
walk. Three shapes, all read from the portal's bytes (capture dates and
provenance in ``docs/sources/cftc-comments.md``):

* **The releases listing** at ``/PublicComments/ReleasesWithComments.aspx?Type=ListAll&Year=YYYY``
  names its year in the ``<title>``, states one ``div.row`` per release inside
  ``pnlReleaseRepeater``, and links the other years it offers. Each item states
  a release-type span (``spanReleaseType_{n}``), a Federal Register citation
  anchor (``hlReleaseLink_{n}``), an optional FR-document PDF anchor
  (``hlPDFLink_{n}``), a title paragraph, labelled Open/Closing date divs
  (``pnlOpenDate_{n}`` / ``pnlClosingDate_{n}``), and SEO anchors whose
  ``hlViewComment_{n}`` href names the rule identity
  (``CommentList.aspx?id={ruleId}``). The sibling ``/FederalRegister/*.aspx``
  routes render the same releases behind postback buttons with no SEO anchors,
  so they are not walkable by GET and are not read here.
* **A comment listing** at ``/PublicComments/CommentList.aspx?id={ruleId}`` is a
  Telerik RadGrid (``gvCommentList``): header labels ``Date Received``,
  ``Release``, ``First Name``, ``Last Name``, ``Organization`` and ``Edit``;
  rows ``rgRow``/``rgAltRow`` with the comment's identity in a hidden
  ``hlViewComment`` anchor (``ViewComment.aspx?id={commentId}``). Rows are read
  from the right -- actions cell, organization, names -- with the release text
  left over, because the search-all listing spells the release as two cells
  (citation beside the linked title). The search-all route itself reaches the
  same grid with a bare numeric query token (``?3098``) in place of ``id=``,
  a spelling the publisher's own pager preserves; both spellings name the
  listing being served, and rows belong to the listing the URL names. The
  pager is SEO-rendered: ``rgCurrentPage`` states the page served, the
  ``Next Page`` / ``Last Page`` anchors name the continuation and the end
  (``...ChangePage={page}``), and ``rgInfoPart`` states the item and page
  totals. A listing without a pager is one page.
* **A comment detail** at ``/PublicComments/ViewComment.aspx?id={commentId}``
  states ``From:``, ``Organization(s):``, ``Comment No:``, ``Date:`` and
  ``Comment Text:`` as labelled paragraphs, a return anchor
  (``lnkReturnToReleaseComments``) naming its own rule, and a ``gvAttachments``
  grid whose rows link the letter files
  (``../Handlers/PdfHandler.ashx?id={fileId}``, link text the publisher's file
  name).

A page is evidence, never absence: an empty grid is an observation the caller
keeps, a page without its grid (or carrying the portal's error sentence) is a
challenge or error wearing the URL and refuses, and the page's own statements
-- title year, current pager page, the Next anchor's arithmetic -- must agree
with the request before its rows are read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urljoin, urlsplit

from spicy_docs.reading.markup import decode_html_page, feed_html, joined_text

if TYPE_CHECKING:
    from spicy_docs.transport.captured import CapturedBodyResponse

CFTC_SITE = "https://comments.cftc.gov"
CFTC_HOST = "comments.cftc.gov"
RELEASES_PATH = "/PublicComments/ReleasesWithComments.aspx"
COMMENT_LIST_PATH = "/PublicComments/CommentList.aspx"
VIEW_COMMENT_PATH = "/PublicComments/ViewComment.aspx"
PDF_HANDLER_PATH = "/Handlers/PdfHandler.ashx"
HTML_MEDIA_TYPE = "text/html"
#: The RadGrid pager's page parameter, spelled as the publisher renders it.
CHANGE_PAGE_PARAM = "ctl00_ctl00_cphContentMain_MainContent_gvCommentListChangePage"
#: Releases renders ran 60-100 KB, comment listings 130-150 KB and details ~70 KB
#: on the captures named in docs/sources/cftc-comments.md.
DEFAULT_MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_BYTES = 16 * 1024 * 1024
#: Runaway guards, not publisher bounds: the widest observed listing page held
#: ten rows, and one year of releases fit one render.
MAX_PAGE_ROWS = 5000
MAX_FIELD_LENGTH = 4096
MAX_TEXT_LENGTH = 200_000
#: RadGrid page size observed on every captured listing page.
ROWS_PER_PAGE = 10
_DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
_ID = re.compile(r"[1-9][0-9]{0,9}")
#: WebForms repeater control ids are 0-indexed, unlike the portal's own ids.
_SUFFIX = re.compile(r"[0-9]{1,10}")
_YEAR_LINK = re.compile(r"ReleasesWithComments\.aspx\?Type=ListAll&(?:amp;)?Year=(\d{4})")
_ERROR_MARKER = "An error occurred while performing your request"
#: The WebForms content placeholder every portal page renders (releases,
#: listings, details and the portal's own error page in every retained
#: 2026-09-24/25 capture); no block page carries it.
PORTAL_PAGE_MARKER = b"cphContentMain_MainContent"


class CftcCommentsSourceError(ValueError):
    """The locator or the response cannot establish the requested portal page."""


class CftcCommentsUnavailableError(CftcCommentsSourceError):
    """Only the exact requested locator answered 404/410; it never means comments are absent."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"CFTC comments portal answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def is_portal_page(body: bytes) -> bool:
    """Whether these bytes are the portal's own page, so a comment quoting a block-page phrase is never a wall."""
    return PORTAL_PAGE_MARKER in body


def _rule_id(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10**10:
        raise CftcCommentsSourceError(f"{label} must be a positive portal id")
    return value


def _checked_year(year: object) -> int:
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise CftcCommentsSourceError("year must be a four-digit calendar year")
    return year


def releases_url(*, year: int | None = None) -> str:
    """The releases listing: upcoming deadlines by default, or every release of one year.

    ``?Type=ListAll&Year=YYYY`` is the only spelling the walk uses: the form
    the page's own year anchors state.
    """
    if year is None:
        return f"{CFTC_SITE}{RELEASES_PATH}"
    return f"{CFTC_SITE}{RELEASES_PATH}?Type=ListAll&Year={_checked_year(year)}"


def comment_list_url(rule_id: int, *, page: int | None = None) -> str:
    """One rule's comment listing, optionally an explicit page of its pager."""
    _rule_id(rule_id, "rule_id")
    url = f"{CFTC_SITE}{COMMENT_LIST_PATH}?id={rule_id}"
    if page is None:
        return url
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise CftcCommentsSourceError("page must be a positive integer")
    return f"{url}&{CHANGE_PAGE_PARAM}={page}"


def view_comment_url(comment_id: int) -> str:
    """One comment's detail page."""
    return f"{CFTC_SITE}{VIEW_COMMENT_PATH}?id={_rule_id(comment_id, 'comment_id')}"


def pdf_url(file_id: int) -> str:
    """The letter file's download route, spelled as the detail page's own links state it."""
    return f"{CFTC_SITE}{PDF_HANDLER_PATH}?id={_rule_id(file_id, 'file_id')}"


def pdf_file_id(file_url: object) -> int:
    """The file id a detail-page PDF link names; the grammar is checked, not trusted."""
    if not isinstance(file_url, str):
        raise CftcCommentsSourceError("CFTC PDF link must be the detail page's own link")
    return _query_id(file_url, PDF_HANDLER_PATH, "id", "CFTC PDF link")


def _query_id(url: str, path: str, param: str, label: str) -> int:
    """The single numeric ``param`` a portal URL names; the grammar is checked, not trusted."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname != CFTC_HOST or parts.path != path:
        raise CftcCommentsSourceError(f"{label} must be an HTTPS comments.cftc.gov route")
    values = [value for name, value in parse_qsl(parts.query, keep_blank_values=True) if name == param]
    if len(values) != 1 or _ID.fullmatch(values[0]) is None:
        raise CftcCommentsSourceError(f"{label} must name exactly one {param}")
    return int(values[0])


def _listing_id(url: str, label: str) -> int:
    """The listing a comment-list URL names: ``id={n}``, or the bare numeric token the
    search-all route spells and its own pager preserves.

    Both spellings are the publisher's: the per-rule page's links say
    ``?id={ruleId}`` and the search-all pager's say ``?{searchId}&``. Anything
    else -- no token, a repeated one, a non-numeric one -- refuses rather than
    guessing which listing was served.
    """
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname != CFTC_HOST or parts.path != COMMENT_LIST_PATH:
        raise CftcCommentsSourceError(f"{label} must be an HTTPS comments.cftc.gov CommentList route")
    pairs = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name == "id"]
    if len(pairs) == 1 and _ID.fullmatch(pairs[0][1]) is not None:
        return int(pairs[0][1])
    tokens = [name for name, _value in parse_qsl(parts.query, keep_blank_values=True) if name.isdigit() and name != "0"]
    if not pairs and len(tokens) == 1 and _ID.fullmatch(tokens[0]) is not None:
        return int(tokens[0])
    raise CftcCommentsSourceError(f"{label} must name exactly one listing id")


def _change_page(url: str) -> int:
    """The listing URL's own page statement; page 1 is the default."""
    values = [
        value for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True) if name == CHANGE_PAGE_PARAM
    ]
    if len(values) > 1:
        raise CftcCommentsSourceError("CFTC comment listing URL repeats its pager parameter")
    if not values:
        return 1
    if not values[0].isdigit() or int(values[0]) < 1:
        raise CftcCommentsSourceError("CFTC comment listing URL pager parameter is not a page number")
    return int(values[0])


def _text(parts: object, label: str, *, bound: int = MAX_FIELD_LENGTH) -> str:
    return joined_text(parts, label=f"CFTC comments page {label}", bound=bound, error_type=CftcCommentsSourceError)


def _lines(parts: list[str], label: str) -> tuple[str, ...]:
    """The nonempty lines a cell states: a joint letter's organizations break at ``<br>`` or a raw newline."""
    return tuple(line for line in (_text(part, label) for part in "".join(parts).split("\n")) if line)


@dataclass(frozen=True, slots=True)
class CftcRelease:
    """One releases-listing item in the publisher's spellings.

    ``rule_id`` is read from the item's own ``hlViewComment`` anchor.
    ``deadline`` is the left-hand date column; ``open_date`` and
    ``closing_date`` and ``extended_date`` the labelled dates inside the item. ``fr_citation``
    (``90 FR 55858``) is the citation anchor's text and ``fr_url`` its target;
    ``fr_pdf_url`` is the PDF-version anchor when the item states one.
    """

    rule_id: int
    title: str
    release_type: str | None
    fr_citation: str | None
    fr_url: str | None
    fr_pdf_url: str | None
    deadline: str | None
    open_date: str | None
    closing_date: str | None
    comment_list_url: str
    extended_date: str | None = None


@dataclass(frozen=True, slots=True)
class CftcReleasesPage:
    """One render of the releases listing.

    ``years_stated`` names every year the page states it serves: the title's
    year first, then the years its own links offer (the current year is not
    linked).
    """

    url: str
    stated_year: int | None
    years_stated: tuple[int, ...]
    releases: tuple[CftcRelease, ...]


@dataclass(frozen=True, slots=True)
class CftcCommentRow:
    """One comment-listing row in the publisher's spellings.

    ``comment_id`` is read from the row's own hidden ViewComment anchor.
    ``rule_id`` is the listing the URL names -- on a per-rule page every row is
    that rule's. The names and organization are the grid's cells;
    ``organizations`` keeps each line the cell states, because a joint letter
    can name several.
    """

    comment_id: int
    rule_id: int
    date_received: str | None
    release_text: str | None
    first_name: str | None
    last_name: str | None
    organizations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CftcCommentListPage:
    """One render of one listing, or one page of it.

    ``total_items`` and ``total_pages`` are ``rgInfoPart``'s own statements,
    present only when the grid paginates. ``current_page`` is the
    ``rgCurrentPage`` item's number, and ``next_page_url`` the ``Next Page``
    anchor -- all absent on a single-page render, where the grid itself states
    the whole listing.
    """

    url: str
    rule_id: int
    rows: tuple[CftcCommentRow, ...]
    total_items: int | None
    total_pages: int | None
    current_page: int | None
    next_page_url: str | None
    last_page_url: str | None


@dataclass(frozen=True, slots=True)
class CftcCommentFile:
    """One letter file the detail page links, in the publisher's spelling."""

    file_id: int
    file_name: str
    url: str


@dataclass(frozen=True, slots=True)
class CftcCommentDetail:
    """One comment's detail in the publisher's spellings.

    ``rule_id`` is read from the page's own return-to-listing anchor, so the
    detail states which rule it belongs to rather than trusting the walk.
    ``text`` is the ``Comment Text`` block; a letter that says only "attached"
    still states its file under ``files``.
    """

    url: str
    comment_id: int
    rule_id: int
    rule_citation: str | None
    submitter: str | None
    organizations: tuple[str, ...]
    date: str | None
    text: str
    files: tuple[CftcCommentFile, ...]


def _decode(body: bytes, max_bytes: int, label: str) -> str:
    text = decode_html_page(body, max_bytes, label=label, cap=MAX_PAGE_BYTES, error_type=CftcCommentsSourceError)
    if _ERROR_MARKER in text:
        raise CftcCommentsSourceError(f"{label} is the portal's own error sentence wearing the requested URL")
    return text


def _id_suffix(element_id: object, stem: str) -> str | None:
    """The ``{n}`` of a WebForms ``..._{stem}_{n}`` control id, or ``None``; indices start at 0."""
    if not isinstance(element_id, str):
        return None
    marker = f"{stem}_"
    at = element_id.rfind(marker)
    if at < 0:
        return None
    suffix = element_id[at + len(marker) :]
    return suffix if _SUFFIX.fullmatch(suffix) else None


def _strip_label(label: str, parts: list[str]) -> str:
    value = _text(parts, label.replace(" ", "-"))
    prefix = f"{label}:"
    return value[len(prefix) :].strip() if value.startswith(prefix) else value


class _ReleasesHtml(HTMLParser):
    """Read the title year, the year anchors and one item per ``row`` div in one pass."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title: list[str] = []
        self.years: list[int] = []
        self.items: list[dict] = []
        self.saw_repeater = False
        self._in_title = False
        self._repeater_depth: int | None = None
        self._div_depth = 0
        self._row_depth: int | None = None
        self._item: dict | None = None
        self._date_field: str | None = None
        self._date_parts: list[str] = []
        self._in_column = False
        self._p_index = 0
        self._in_title_paragraph = False
        self._anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        element_id = values.get("id") or ""
        if tag == "title":
            self._in_title = True
            return
        if tag == "div":
            self._div_depth += 1
            if "pnlReleaseRepeater" in element_id and self._repeater_depth is None:
                self._repeater_depth = self._div_depth
                self.saw_repeater = True
            elif self._repeater_depth is not None and self._row_depth is None and classes == {"row"}:
                self._row_depth = self._div_depth
                self._item = {
                    "type": [],
                    "citation": None,
                    "fr_url": None,
                    "pdf_url": None,
                    "title": [],
                    "open": [],
                    "close": [],
                    "extended": [],
                    "deadline": [],
                    "list_href": None,
                }
                self._in_column, self._p_index, self._date_field = False, 0, None
            elif self._item is not None:
                if "column-date" in classes and self._date_field is None:
                    self._date_field = "deadline"
                    self._date_parts = []
                elif "column-item" in classes:
                    self._in_column = True
                    self._p_index = 0
                elif (
                    name := "open"
                    if "pnlOpenDate" in element_id
                    else "close"
                    if "pnlClosingDate" in element_id
                    else "extended"
                    if "pnlExtendedDate" in element_id
                    else None
                ) and self._date_field is None:
                    self._date_field = name
                    self._date_parts = []
            return
        if tag == "p" and self._in_column and self._item is not None:
            self._p_index += 1
            self._in_title_paragraph = self._p_index == 2
            return
        if (
            tag == "span"
            and self._item is not None
            and self._in_column
            and self._p_index == 1
            and _id_suffix(element_id, "spanReleaseType") is not None
        ):
            self._anchor = {"kind": "type", "href": None, "parts": []}
            return
        if tag == "a":
            kind = None
            if self._item is not None and self._in_column and self._p_index == 1:
                if _id_suffix(element_id, "hlReleaseLink") is not None:
                    kind = "citation"
                elif _id_suffix(element_id, "hlPDFLink") is not None:
                    kind = "pdf"
            if self._item is not None and _id_suffix(element_id, "hlViewComment") is not None:
                kind = "view"
            if self._item is not None:
                # Field links are read separately; inline links inside the title
                # paragraph also contribute their visible text in handle_data.
                self._anchor = {"kind": kind, "href": values.get("href"), "parts": []}
            elif self._repeater_depth is None:
                self._anchor = {"kind": "year", "href": values.get("href"), "parts": []}

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag == "p":
            self._in_title_paragraph = False
            return
        if tag == "div":
            if self._item is not None and self._div_depth == self._row_depth:
                self._close_row()
            elif self._date_field is not None and self._item is not None:
                self._item[self._date_field].extend(self._date_parts)
                self._date_field, self._date_parts = None, []
            if self._in_column and self._item is not None and self._div_depth - 1 == self._row_depth:
                self._in_column = False
            self._div_depth -= 1
            if self._repeater_depth is not None and self._div_depth < self._repeater_depth:
                self._repeater_depth = None
            return
        if tag == "span" and self._anchor is not None and self._anchor["kind"] == "type":
            self._close_anchor()
            return
        if tag == "a" and self._anchor is not None:
            self._close_anchor()
            return

    def _close_row(self) -> None:
        assert self._item is not None
        if len(self.items) >= MAX_PAGE_ROWS:
            raise CftcCommentsSourceError("CFTC releases listing lists more items than supported")
        self.items.append(self._item)
        self._item, self._row_depth = None, None
        self._in_column, self._p_index, self._date_field = False, 0, None
        self._in_title_paragraph = False

    def _close_anchor(self) -> None:
        anchor, self._anchor = self._anchor, None
        if anchor is None:
            return
        text = _text(anchor["parts"], "releases anchor")
        href = anchor["href"]
        if anchor["kind"] == "type" and self._item is not None:
            self._item["type"].append(text)
        elif anchor["kind"] == "citation" and self._item is not None and href:
            self._item["citation"] = text
            self._item["fr_url"] = urljoin(self.base_url, href)
        elif anchor["kind"] == "pdf" and self._item is not None and href:
            self._item["pdf_url"] = urljoin(self.base_url, href)
        elif anchor["kind"] == "view" and self._item is not None and href:
            self._item["list_href"] = urljoin(self.base_url, href)
        elif anchor["kind"] == "year" and href:
            match = _YEAR_LINK.search(href)
            if match is not None and text == match.group(1):
                year = int(match.group(1))
                if year not in self.years:
                    self.years.append(year)

    def handle_data(self, data):
        if self._in_title:
            self.title.append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)
        if self._item is not None:
            if self._date_field is not None and self._anchor is None:
                self._date_parts.append(data)
            elif self._in_title_paragraph:
                self._item["title"].append(data)


def _release(row: dict) -> CftcRelease:
    href = row["list_href"]
    if not isinstance(href, str) or not href:
        raise CftcCommentsSourceError("CFTC releases item states no comment-listing link")
    rule_id = _query_id(href, COMMENT_LIST_PATH, "id", "CFTC releases item comment link")
    title = _text(row["title"], "release title")
    if not title:
        raise CftcCommentsSourceError("CFTC releases item states no title")
    deadline = _strip_label("Deadline", row["deadline"]) or None
    open_date = _strip_label("Open Date", row["open"]) or None
    closing_date = _strip_label("Closing Date", row["close"]) or None
    extended_date = _strip_label("Extended Date", row["extended"]) or None
    for label, value in (
        ("deadline", deadline),
        ("open date", open_date),
        ("closing date", closing_date),
        ("extended date", extended_date),
    ):
        if value is not None and _DATE.fullmatch(value) is None:
            raise CftcCommentsSourceError(f"CFTC releases item states a {label} that is not M/D/YYYY")
    return CftcRelease(
        rule_id=rule_id,
        title=title,
        release_type=_text(row["type"], "release type") or None,
        fr_citation=row["citation"],
        fr_url=row["fr_url"],
        fr_pdf_url=row["pdf_url"],
        deadline=deadline,
        open_date=open_date,
        closing_date=closing_date,
        comment_list_url=comment_list_url(rule_id),
        extended_date=extended_date,
    )


def parse_releases_page(body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> CftcReleasesPage:
    """Read one releases render. O(B) in the response bytes; one pass.

    The render must state the year the URL requested in its own title, so a
    render of another year refuses instead of being read as this year's
    releases. A page that states no repeater container is a challenge or error
    page wearing the URL and refuses; a repeater with no items is an
    observation the caller keeps.
    """
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname != CFTC_HOST or parts.path != RELEASES_PATH:
        raise CftcCommentsSourceError("CFTC releases URL must be an HTTPS comments.cftc.gov ReleasesWithComments route")
    years = [value for name, value in parse_qsl(parts.query, keep_blank_values=True) if name == "Year"]
    requested = _checked_year(int(years[0])) if years and years[0].isdigit() else None
    text = _decode(body, max_bytes, "CFTC releases listing")
    parser = _ReleasesHtml(base_url=url)
    feed_html(parser, text, label="CFTC releases listing", error_type=CftcCommentsSourceError)
    if not parser.saw_repeater:
        raise CftcCommentsSourceError("CFTC releases listing states no release repeater")
    stated = None
    match = re.search(r"\b(20\d{2})\b", _text(parser.title, "listing title"))
    if match is not None:
        stated = int(match.group(1))
    if requested is not None and stated != requested:
        raise CftcCommentsSourceError(
            f"CFTC releases listing states it is the {stated} page, not the requested {requested}"
        )
    # The portal links the years it offers other than the one it is rendering,
    # so the stated year joins its links to name the whole year walk.
    years_stated = (
        (stated,) + tuple(year for year in parser.years if year != stated)
        if stated is not None
        else tuple(parser.years)
    )
    return CftcReleasesPage(
        url=url,
        stated_year=stated,
        years_stated=years_stated,
        releases=tuple(_release(row) for row in parser.items),
    )


class _CommentListHtml(HTMLParser):
    """Read the RadGrid's header labels, rows and SEO pager in one pass."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.headers: list[str] = []
        self.rows: list[dict] = []
        self.current_page: int | None = None
        self.next_url: str | None = None
        self.last_url: str | None = None
        self.total_items: int | None = None
        self.total_pages: int | None = None
        self._master_depth: int | None = None
        self._table_depth = 0
        self._in_head = False
        self._head_parts: list[str] | None = None
        self._row: dict | None = None
        self._cell: list[str] | None = None
        self._anchor_href: str | None = None
        self._anchor_title: str | None = None
        self._anchor_classes: set[str] = set()
        self._anchor_parts: list[str] = []
        self._is_current = False
        self._info_parts: list[str] | None = None
        self._info_strongs: list[str] = []
        self._in_info_strong = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        element_id = values.get("id") or ""
        if tag == "table":
            self._table_depth += 1
            if self._master_depth is None and "rgMasterTable" in classes and "gvCommentList" in element_id:
                self._master_depth = self._table_depth
        elif tag == "thead" and self._master_depth == self._table_depth:
            self._in_head = True
        elif tag == "th" and self._in_head:
            self._head_parts = []
        elif (
            self._row is None
            and self._master_depth == self._table_depth
            and tag == "tr"
            and classes & {"rgRow", "rgAltRow"}
        ):
            self._row = {"cells": [], "comment_href": None}
        elif tag == "td" and self._row is not None:
            if self._cell is not None:
                raise CftcCommentsSourceError("CFTC comment listing nests its cells")
            self._cell = []
        elif tag == "a":
            self._anchor_href = values.get("href")
            self._anchor_title = values.get("title")
            self._anchor_classes = classes
            self._anchor_parts = []
            self._is_current = "rgCurrentPage" in classes
        elif tag == "div" and "rgInfoPart" in classes:
            self._info_parts = []
            self._info_strongs = []
        elif tag == "strong" and self._info_parts is not None:
            self._in_info_strong = True
            self._info_strongs.append("")
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag == "table":
            if self._master_depth == self._table_depth:
                self._master_depth = None
            self._table_depth -= 1
        elif tag == "thead":
            self._in_head = False
        elif tag == "th" and self._in_head and self._head_parts is not None:
            self.headers.append(_text(self._head_parts, "column header"))
            self._head_parts = None
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                if len(self.rows) >= MAX_PAGE_ROWS:
                    raise CftcCommentsSourceError("CFTC comment listing lists more rows than supported")
                self.rows.append(self._row)
            self._row = None
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(self._cell)
            self._cell = None
        elif tag == "a" and self._anchor_href is not None:
            self._close_anchor()
        elif tag == "div" and self._info_parts is not None:
            self._read_info()
        elif tag == "strong" and self._in_info_strong:
            self._in_info_strong = False

    def _close_anchor(self) -> None:
        href = urljoin(self.base_url, self._anchor_href or "")
        title = self._anchor_title or ""
        text = _text(self._anchor_parts, "listing anchor")
        if self._is_current:
            if not text.isdigit():
                raise CftcCommentsSourceError("CFTC comment listing current pager item states no page number")
            self.current_page = int(text)
        elif title == "Next Page" and self._row is None:
            self.next_url = href
        elif title == "Last Page" and self._row is None:
            self.last_url = href
        elif self._row is not None and "ViewComment.aspx" in href:
            self._row["comment_href"] = href
        self._anchor_href, self._anchor_title, self._anchor_parts = None, None, []
        self._anchor_classes, self._is_current = set(), False

    def _read_info(self) -> None:
        """The pager's stated totals; a totals block this parser cannot read refuses rather than going unchecked."""
        strongs = [value for value in self._info_strongs if value.strip().isdigit()]
        sentence = _text(self._info_parts or [], "pager totals")
        if len(strongs) >= 2:
            self.total_items, self.total_pages = int(strongs[0]), int(strongs[1])
        elif sentence.isdigit():
            self.total_items = int(sentence)
        else:
            raise CftcCommentsSourceError("CFTC comment listing states pager totals this module cannot read")
        self._info_parts, self._info_strongs, self._in_info_strong = None, [], False

    def handle_data(self, data):
        if self._in_head and self._head_parts is not None and self._row is None:
            self._head_parts.append(data)
        if self._cell is not None:
            # Anchor text belongs to its cell too: the release cell's link text
            # is the release spelling the row states.
            self._cell.append(data)
        if self._anchor_href is not None:
            self._anchor_parts.append(data)
        if self._info_parts is not None:
            if self._in_info_strong and self._info_strongs:
                self._info_strongs[-1] += data
            else:
                self._info_parts.append(data)


def _listing_row(row: dict, rule_id: int) -> CftcCommentRow:
    href = row["comment_href"]
    if not isinstance(href, str) or not href:
        raise CftcCommentsSourceError("CFTC comment listing row states no comment link")
    comment_id = _query_id(href, VIEW_COMMENT_PATH, "id", "CFTC comment listing row")
    cells = row["cells"]
    if len(cells) < 6:
        raise CftcCommentsSourceError("CFTC comment listing row states fewer cells than its shape requires")
    date_cell = _text(cells[0], "date received")
    if _DATE.fullmatch(date_cell) is None:
        raise CftcCommentsSourceError("CFTC comment listing row's first cell is not its M/D/YYYY date")
    organization, last_name, first_name = cells[-2], cells[-3], cells[-4]
    release = " ".join(part for cell in cells[1:-4] for part in [_text(cell, "release text")] if part) or None
    organizations = _lines(organization, "organization")
    return CftcCommentRow(
        comment_id=comment_id,
        rule_id=rule_id,
        date_received=date_cell,
        release_text=release,
        first_name=_text(first_name, "first name") or None,
        last_name=_text(last_name, "last name") or None,
        organizations=organizations,
    )


def parse_comment_list_page(body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> CftcCommentListPage:
    """Read one listing render, or one page of it. O(B) in the response bytes, one pass.

    The grid's master table with its header labels must be present -- a render
    without them is a challenge or error page wearing the URL -- but
    present-and-empty is an observation the caller keeps, never a refusal and
    never source absence. The pager's current item must name the page the URL
    requested, and the Next anchor must advance this listing's pager parameter
    by exactly one page, because both are the render's own statements about
    what it served.
    """
    rule_id = _listing_id(url, "CFTC comment listing URL")
    requested_page = _change_page(url)
    text = _decode(body, max_bytes, "CFTC comment listing")
    parser = _CommentListHtml(base_url=url)
    feed_html(parser, text, label="CFTC comment listing", error_type=CftcCommentsSourceError)
    if not {"Date Received", "Organization"} <= set(parser.headers):
        raise CftcCommentsSourceError("CFTC comment listing states no RadGrid header")
    if parser.current_page is not None and parser.current_page != requested_page:
        raise CftcCommentsSourceError(
            f"CFTC comment listing states it is page {parser.current_page}, not the requested page {requested_page}"
        )
    next_url = parser.next_url
    if next_url is not None:
        if _listing_id(next_url, "CFTC comment listing continuation") != rule_id:
            raise CftcCommentsSourceError("CFTC comment listing continuation leaves its listing")
        if _change_page(next_url) != requested_page + 1:
            raise CftcCommentsSourceError("CFTC comment listing continuation does not advance the pager by one page")
    elif (
        parser.total_pages is not None and parser.current_page is not None and parser.current_page < parser.total_pages
    ):
        raise CftcCommentsSourceError("CFTC comment listing ended before its own stated page count")
    return CftcCommentListPage(
        url=url,
        rule_id=rule_id,
        rows=tuple(_listing_row(row, rule_id) for row in parser.rows),
        total_items=parser.total_items,
        total_pages=parser.total_pages,
        current_page=parser.current_page,
        next_page_url=next_url,
        last_page_url=parser.last_url,
    )


class _ViewCommentHtml(HTMLParser):
    """Read the labelled detail paragraphs and the attachments grid in one pass.

    A ``<strong>`` whose text is one of the page's labels opens that field;
    its value ends at the next label or its enclosing div. Comment text keeps
    inline formatting text and links, but excludes scripts, styles and the
    attachment grid outside its div.
    """

    _LABELS = ("From:", "Organization(s):", "Comment No:", "Date:", "Comment Text:")

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.return_href: str | None = None
        self.return_text: list[str] = []
        self.fields: dict[str, list[str]] = {label: [] for label in self._LABELS}
        self.files: list[dict] = []
        self._field: str | None = None
        self._strong_parts: list[str] = []
        self._in_strong = False
        self._anchor: dict | None = None
        self._div_depth = 0
        self._field_depth: int | None = None
        self._ignored_tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if self._ignored_tag is not None:
            return
        if tag in ("script", "style"):
            self._ignored_tag = tag
            return
        if tag == "div":
            self._div_depth += 1
        values = dict(attrs)
        element_id = values.get("id") or ""
        if tag == "br" and self._field is not None:
            self.fields[self._field].append("\n")
        elif tag == "strong":
            self._in_strong = True
            self._strong_parts = []
        elif tag == "a":
            kind = None
            if "lnkReturnToReleaseComments" in element_id:
                kind = "return"
            elif "hlPdfStaticLink" in element_id:
                kind = "file"
            self._anchor = {"kind": kind, "href": values.get("href"), "parts": []}

    def handle_endtag(self, tag):
        if self._ignored_tag is not None:
            if tag == self._ignored_tag:
                self._ignored_tag = None
            return
        if tag == "strong":
            self._in_strong = False
            label = _text(self._strong_parts, "detail label")
            if label in self.fields and self._field != "Comment Text:":
                self._field = label
                self._field_depth = self._div_depth
            elif self._field is not None and self._field != "Comment Text:" and self._anchor is None:
                self.fields[self._field].extend(self._strong_parts)
        elif tag == "a" and self._anchor is not None:
            anchor, self._anchor = self._anchor, None
            if anchor["kind"] is None:
                if self._field is not None and self._field != "Comment Text:":
                    self.fields[self._field].extend(anchor["parts"])
                return
            text = _text(anchor["parts"], "detail anchor")
            href = urljoin(self.base_url, anchor["href"] or "")
            if anchor["kind"] == "return":
                self.return_href = href
                self.return_text = list(anchor["parts"])
            else:
                self.files.append({"href": href, "name": text})
        elif tag in ("p", "div", "li", "span") and self._field == "Comment Text:":
            if self.fields["Comment Text:"] and not self.fields["Comment Text:"][-1].endswith("\n"):
                self.fields["Comment Text:"].append("\n")
        if tag == "div":
            if self._div_depth == self._field_depth:
                self._field = None
                self._field_depth = None
            self._div_depth -= 1

    def handle_data(self, data):
        if self._ignored_tag is not None:
            return
        if self._in_strong:
            self._strong_parts.append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)
        if self._field == "Comment Text:" or (self._field is not None and not self._in_strong and self._anchor is None):
            self.fields[self._field].append(data)


def parse_view_comment_page(body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> CftcCommentDetail:
    """Read one comment detail. O(B) in the response bytes, one pass.

    The page must state its ``Comment No:`` -- the one label every detail
    states -- and that number must be the comment the URL requested; its
    return anchor must name the rule the detail belongs to, so a detail served
    for another comment refuses rather than mis-attributing a letter.
    """
    comment_id = _query_id(url, VIEW_COMMENT_PATH, "id", "CFTC comment detail URL")
    text = _decode(body, max_bytes, "CFTC comment detail")
    parser = _ViewCommentHtml(base_url=url)
    feed_html(parser, text, label="CFTC comment detail", error_type=CftcCommentsSourceError)
    stated_number = _text(parser.fields["Comment No:"], "comment number")
    if not stated_number.isdigit() or int(stated_number) != comment_id:
        raise CftcCommentsSourceError("CFTC comment detail does not state the requested comment's number")
    if not isinstance(parser.return_href, str) or not parser.return_href:
        raise CftcCommentsSourceError("CFTC comment detail states no return-to-listing link")
    rule_id = _query_id(parser.return_href, COMMENT_LIST_PATH, "id", "CFTC comment detail return link")
    citation = _text(parser.return_text, "return link")
    prefix = "View all comments for "
    rule_citation = citation[len(prefix) :].strip() if citation.startswith(prefix) else None
    date = _text(parser.fields["Date:"], "comment date") or None
    if date is not None and _DATE.fullmatch(date) is None:
        raise CftcCommentsSourceError("CFTC comment detail states a date that is not M/D/YYYY")
    organizations = _lines(parser.fields["Organization(s):"], "organization")
    files = []
    for entry in parser.files:
        file_id = _query_id(entry["href"], PDF_HANDLER_PATH, "id", "CFTC comment detail file link")
        # This is publisher display metadata, not a local path. Live letters
        # include names such as 113989JiríKról.pdf; the locator is validated
        # independently and the PDF acquirer checks the actual file bytes.
        if not entry["name"]:
            raise CftcCommentsSourceError("CFTC comment detail file link states no file name")
        files.append(CftcCommentFile(file_id=file_id, file_name=entry["name"], url=entry["href"]))
    return CftcCommentDetail(
        url=url,
        comment_id=comment_id,
        rule_id=rule_id,
        rule_citation=rule_citation,
        submitter=_text(parser.fields["From:"], "submitter") or None,
        organizations=organizations,
        date=date,
        text=_text(parser.fields["Comment Text:"], "comment text", bound=MAX_TEXT_LENGTH),
        files=tuple(files),
    )
