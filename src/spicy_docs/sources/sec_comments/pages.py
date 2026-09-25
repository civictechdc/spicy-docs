"""SEC rulemaking and comment-listing pages as sec.gov states them, read in one linear pass.

Three HTML shapes, the first two Drupal renders measured live on 2026-09-24
with the declared fair-access user agent (see ``acquisition.py``):

* **The rulemaking index** at ``/rules-regulations/rulemaking-activity`` is one
  ``cols-4`` table whose rows state a publish date, a release/file-number cell
  that can be empty, a title, and a status anchor into the per-rule page. The
  file-number cell is where the comment docket key lives (``S7-11-23``); rows
  without one are addressed by a slug and state no file number in that row.
  Their rule pages can still state comment-listing links. File-number classes
  are read from the page, not hard-coded: the probed pages carried ``S7-`` numbers, and the publisher's
  other classes (SRO ``sr-`` filings, PCAOB, numbered releases) reach this same
  table through its filters. The index paginates with a ``usa-pagination`` nav:
  a ``usa-current`` item states the page being served and a
  ``usa-pagination__next-page`` anchor names the next page as a bare
  ``?page=N`` query. Twenty-nine pages on 2026-09-24.
* **A comment listing** at ``/comments/{docket}/{docket-without-dashes}.htm``
  states an ``h1`` title, a ``cols-1`` table of letter-type sections
  (``{stem}-typea.htm``, ``...typec.pdf`` -- form-letter template documents,
  not continuation pages), and a ``cols-3`` table of comment rows, each linking
  one file (``{stem}-{n}-{n}.pdf``, ``.htm`` or ``.html``) under the same
  ``/comments/{docket}/`` directory. The listing paginates the way the index
  does (``?page=N``, thirty rows to a page; four pages for ``S7-11-23`` on
  2026-09-24). There is **no** ``-1.htm`` continuation grammar; continuation is
  the query.
* **A rule page** at ``/rules-regulations/{year}/{month}/{slug}`` -- the index
  status anchor's target -- states an ``h1`` title and, through Drupal fields
  the publisher marks with ``field--name-`` machine names, its file number
  (``field-file-number``), release numbers (``field-release-number``) and
  Federal Register citations (``field-document-citation``), each value in its
  own ``field__item`` div beside a ``field__label`` (``File Number``,
  ``Release Number``, ``Document Citation``). The live S7-11-23 page
  (2026-09-24) additionally states one citation in prose -- the extension
  block's ``at 90 FR 2837`` sentence -- so the visible text is scanned for
  citations too. The label is part of the identity check: the live page
  reuses the ``field-release-number`` template for ``Title`` fields, so only
  a field whose own label names the statement is read. The
  ``field-comments-received`` field states the comment-listing URLs to
  follow; their filenames are preserved, never rebuilt from a file number.
  SRO rule pages remain unmeasured -- see ``tests/fixtures/sec_comments/README.md``.

Identity is checked from the page's own statements, never from the request URL
alone: the pager's current item must name the page requested, and every
comment-file and section link must stay inside the listing's own
``/comments/{docket}/`` directory with a known extension. A present-but-empty
table is an observation the caller keeps, never a refusal and never source
absence; a missing table is a refusal, because a challenge or error page wears
the URL the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal, cast
from urllib.parse import parse_qsl, urljoin, urlsplit

from spicy_docs.reading.markup import decode_html_page, feed_html, joined_text
from spicy_docs.transport.captured import CapturedBodyResponse

SEC_SITE = "https://www.sec.gov"
SEC_HOST = "www.sec.gov"
RULEMAKING_INDEX_PATH = "/rules-regulations/rulemaking-activity"
COMMENTS_PATH_PREFIX = "/comments/"
#: Index renders ran 247-258 KB and listing renders 85-104 KB on 2026-09-24.
DEFAULT_MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_BYTES = 16 * 1024 * 1024
#: Runaway guards, not publisher bounds: the widest observed index held 29 pages and the
#: widest observed listing (S7-11-23) 4 pages of 30 rows on 2026-09-24.
DEFAULT_MAX_INDEX_PAGES = 200
DEFAULT_MAX_LISTING_PAGES = 100
MAX_PAGE_ROWS = 5000
MAX_FIELD_LENGTH = 4096
#: Comment and section files observed on 2026-09-24: .htm, .html and .pdf under the docket directory.
COMMENT_EXTENSIONS = ("htm", "html", "pdf")
type CommentFormat = Literal["htm", "html", "pdf"]
#: Docket identity uses dashed lowercase alphanumerics; source URL case is retained.
_DOCKET = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*", re.IGNORECASE)
#: Tags whose open/close pairs bracket the pager's anchors.
_NAV_CONTAINERS = frozenset({"nav", "div", "ul", "li"})
#: A rule-page slug as the publisher spells it: lowercase alphanumerics and dashes.
_RULE_PAGE_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
#: One Federal Register citation, the grammar pages and the join share: ``89 FR 45894`` or
#: ``71 FR 159`` -- a volume without a leading zero, an uppercase ``FR``, a one- to six-digit page.
FR_CITATION_PATTERN = r"\b([1-9]\d{0,2})\s+FR\s+(\d{1,6})\b"
_FR_CITATION = re.compile(FR_CITATION_PATTERN)
#: One release number as SEC states it: ``34-103320``, ``IA-6885``, ``39-2566``, or ``34-77617A``
#: (the Federal Register release's ``docket_ids`` carry the lettered spelling). The numbered series
#: are the acts' years; beside a release statement, any other numbered prefix is a file number
#: (``812-``, ``811-``, ``70-``), measured in the Federal Register release on 2026-09-25.
RELEASE_NUMBER_PATTERN = r"(?<![A-Z0-9-])(?:[A-Z]{1,4}|33|34|35|39)-\d{2,6}[A-Z]?(?![A-Z0-9-])"
_RELEASE_NUMBER = re.compile(RELEASE_NUMBER_PATTERN)
#: The act-name spellings of a release series the Federal Register release's ``docket_ids`` use
#: (measured 2026-09-25), and the prefix each keys on: ``Investment Company Act Release No. 35635``
#: is ``IC-35635``.
RELEASE_SERIES_NAMES = {
    "securities act": "33",
    "securities exchange act": "34",
    "investment company act": "IC",
    "investment company": "IC",
    "investment advisers act": "IA",
    "international series": "IS",
    "international securities": "IS",
    "int'l series": "IS",
    "international": "IS",
}
#: A series name, optionally its act's year, then one bare number: ``Securities Exchange Act of 1934,
#: Release No. 34885/October 24, 1994``. Group 1 is the name, group 2 the number.
NAMED_RELEASE_PATTERN = (
    r"(?i:\b("
    + "|".join(
        r"\s+".join(map(re.escape, name.split())) for name in sorted(RELEASE_SERIES_NAMES, key=len, reverse=True)
    )
    + r")(?:\s+of\s+\d{4})?[,:]?\s+Release\s+No\.)\s*(\d{2,6}[A-Z]?)(?![\w-])"
)


def named_release_number(name: str, number: str) -> str:
    """The standard spelling of an act-named release: ``Investment Company Act`` and ``35635`` are ``IC-35635``."""
    return f"{RELEASE_SERIES_NAMES[' '.join(name.casefold().split())]}-{number}"


#: Runaway guard for release statements; a rule page names a handful at most.
_MAX_RELEASE_NUMBERS = 64
#: The rule page's statement fields, by the Drupal machine name the publisher marks them with,
#: and the ``field__label`` each must state for its items to be read (the live page reuses the
#: release-number template for ``Title`` fields, so the label is part of the identity check).
_RULE_PAGE_STATEMENT_FIELDS = {
    "field-file-number": "file number",
    "field-release-number": "release number",
    "field-document-citation": "document citation",
}
#: Runaway guard for citation statements; a rule page names a handful at most.
_MAX_FR_CITATIONS = 64
#: Runaway guard, not a limit on the publisher's comment population.
_MAX_COMMENT_LISTINGS = 64
#: The index row's release numbers live inside the info-button's ``regulation-node-release-number`` span.
_RELEASE_SPAN_CLASS = "regulation-node-release-number"


class SecCommentsSourceError(ValueError):
    """The locator or the response cannot establish the requested SEC comments page or file."""


class SecCommentsUnavailableError(SecCommentsSourceError):
    """Only the exact requested locator answered 404/410; it never means the comments are absent.

    A 404 on a comment-index URL built by :func:`comment_index_url` says the
    derived locator has no listing: the rulemaking may have no comment file
    open, or its file number may not follow the measured grammar. Neither is
    an observation that no comments exist.
    """

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"SEC comments source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def requested_page_number(url: str) -> int:
    """The ``page`` query parameter a walk URL carries; page 0 is the default and needs none."""
    values = [value for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True) if name == "page"]
    if len(values) > 1:
        raise SecCommentsSourceError("SEC comments page URL repeats its page parameter")
    if not values:
        return 0
    if not values[0].isdigit():
        raise SecCommentsSourceError("SEC comments page URL page parameter is not a number")
    return int(values[0])


def _walk_route(url: str) -> tuple[str, str, str, str, list[tuple[str, str]]]:
    parts = urlsplit(url)
    rest = sorted((name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name != "page")
    return parts.scheme, parts.netloc, parts.path, parts.fragment, rest


def check_continuation(start: str, next_url: str, label: str) -> None:
    """Refuse a pager's next link unless it is the walk's start URL with only its ``page`` parameter changed."""
    if _walk_route(next_url) != _walk_route(start):
        raise SecCommentsSourceError(f"{label} pager continues outside the walk's own route")
    requested_page_number(next_url)


def rulemaking_index_url(*, page: int | None = None) -> str:
    """The rulemaking index, optionally one explicit page of its pager."""
    if page is None:
        return f"{SEC_SITE}{RULEMAKING_INDEX_PATH}"
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise SecCommentsSourceError("page must be a non-negative integer")
    return f"{SEC_SITE}{RULEMAKING_INDEX_PATH}?page={page}"


def comment_index_url(file_number: str) -> str:
    """The comment listing for one file number, spelled by the publisher's directory grammar.

    ``S7-11-23`` lives at ``/comments/s7-11-23/s71123.htm``: the file number
    lowercased keeps its dashes as the directory and loses them as the file
    stem. Verified 2026-09-24 against the ``S7-11-23`` per-rule page, whose own
    comments link is byte-identical to this spelling; the grammar is the
    publisher's, but a locator it builds is still derived, and a 404 there is
    an observation about the locator, never that no comments exist.
    """
    value = file_number if isinstance(file_number, str) else ""
    if not value or value != value.strip() or _DOCKET.fullmatch(value.lower()) is None:
        raise SecCommentsSourceError("file number must be the publisher's dashed spelling, e.g. S7-11-23")
    low = value.lower()
    return f"{SEC_SITE}{COMMENTS_PATH_PREFIX}{low}/{low.replace('-', '')}.htm"


def _text(parts: list[str], label: str) -> str:
    return joined_text(
        parts, label=f"SEC comments page {label}", bound=MAX_FIELD_LENGTH, error_type=SecCommentsSourceError
    )


@dataclass(frozen=True, slots=True)
class SecPager:
    """One render's own statement of where it sits: its current page and its next page, if any.

    ``current_page`` is the ``usa-current`` pager item's own ``?page=N`` and
    ``next_url`` the absolute ``usa-pagination__next-page`` target; a page with
    no pager states neither.
    """

    current_page: int | None
    next_url: str | None


@dataclass(frozen=True, slots=True)
class SecRulemaking:
    """One index row in the publisher's spellings.

    ``file_number`` is the release/file-number cell and is the comment docket
    key when the row states one; multi-release rulemakings leave it empty and
    are addressed by their ``rule_url`` slug, keyed by :attr:`docket_key` as
    ``slug:<path-segment>``. ``published`` is the row's
    ``<time datetime>`` instant. ``rule_url`` is the status anchor's target
    with its fragment dropped: the fragment names an anchor on the page, not
    the resource. ``release_numbers`` are the row's own
    ``regulation-node-release-number`` statements, in the page's order (empty
    when the row states none).
    """

    index: int
    file_number: str | None
    title: str
    status: str | None
    published: str | None
    rule_url: str | None
    release_numbers: tuple[str, ...] = ()

    @property
    def comment_index_url(self) -> str | None:
        """The docket's comment listing, by the grammar :func:`comment_index_url` documents.

        Absent when the row states no file number. The spelling is derived --
        verified once against the publisher's own link -- so a 404 there is an
        observation about the locator, never that no comments exist.
        """
        return comment_index_url(self.file_number) if self.file_number is not None else None

    @property
    def docket_key(self) -> str:
        """The stable key this row is addressed and enumerated by.

        A row that states a file number keys on it (``S7-11-23``, the comment
        docket's own name). A row whose file-number cell is empty -- a
        multi-release rulemaking the publisher addresses by a slug -- keys on
        ``slug:<path-segment>`` of its rule URL, so every index row has one
        stable key and none is unaddressable. The prefix names the namespace
        and keeps the two kinds disjoint. The empty cell itself is retained:
        ``file_number`` stays None, and the key states that no comment file
        number was stated, never a derived one.
        """
        if self.file_number is not None:
            return self.file_number
        if self.rule_url is None:
            raise SecCommentsSourceError("SEC rulemaking index row states neither a file number nor a rule page slug")
        slug = urlsplit(self.rule_url).path.rstrip("/").rsplit("/", 1)[-1]
        return f"slug:{slug}"


@dataclass(frozen=True, slots=True)
class SecRulePage:
    """One rule page's own statements, read from its visible title and its publisher-marked fields.

    ``file_number`` is the page's ``File Number`` field, checked against the
    docket grammar and absent when the page states none. ``release_numbers``
    are every ``Release Number`` field value and ``fr_citations`` every FR
    citation the page states -- in a ``Document Citation`` field or in prose
    -- each spelled as the page spells it (``89 FR 45894``). The page's URL,
    not the page's text, is the locator. ``comment_listing_urls`` comes from
    the received-comments field and stays empty when that page offers none.
    Identity checks follow the index
    reader's: a render without a title, or a URL outside the rulemaking
    route, refuses.
    """

    url: str
    title: str
    file_number: str | None
    release_numbers: tuple[str, ...]
    fr_citations: tuple[str, ...]
    #: Links in the publisher's received-comments field, in first-seen order.
    #: Empty means this page offered none, not that comments do not exist.
    comment_listing_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecRulemakingIndexPage:
    """One render of the rulemaking index, or one page of it."""

    url: str
    rulemakings: tuple[SecRulemaking, ...]
    pager: SecPager


@dataclass(frozen=True, slots=True)
class SecCommentSection:
    """One letter-type document the listing states: a form-letter template, not a comment.

    ``label`` is the link text (``A: 2``); the URL is the document itself, in
    the listing's own directory, as an HTM page or a PDF.
    """

    docket: str
    label: str
    url: str
    format: CommentFormat


@dataclass(frozen=True, slots=True)
class SecCommentFile:
    """One comment file the listing states, in the publisher's spellings.

    ``link_text`` is the commenter name as the listing spells it, ``date`` the
    row's ``<time datetime>`` instant, ``letter_type`` the row's own label
    (``Public Comment``). ``format`` is the extension the URL names; the bytes
    are proved at download, not here.
    """

    docket: str
    url: str
    file_name: str
    link_text: str
    format: CommentFormat
    letter_type: str | None
    date: str | None


@dataclass(frozen=True, slots=True)
class SecCommentListingPage:
    """One render of one docket's comment listing, or one page of it."""

    url: str
    docket: str
    title: str
    sections: tuple[SecCommentSection, ...]
    comments: tuple[SecCommentFile, ...]
    pager: SecPager


class _SecCommentsHtml(HTMLParser):
    """The shared reader: the ``usa-pagination`` nav, with content tags delegated out.

    Inside the pager nav only its anchors matter, so every other tag is
    tracked as depth and ignored. A subclass implements ``_content_starttag``
    and ``_content_endtag`` for everything outside it; ``handle_data`` routes
    to ``_pager_free_data`` only outside the nav.
    """

    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.current_page: int | None = None
        self.next_url: str | None = None
        self._nav_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if self._nav_depth:
            if tag in _NAV_CONTAINERS:
                self._nav_depth += 1
            elif tag == "a":
                self._pager_anchor(classes, values.get("href"))
            return
        if tag == "nav" and "usa-pagination" in classes:
            self._nav_depth = 1
            return
        self._content_starttag(tag, values, classes)

    def handle_endtag(self, tag: str) -> None:
        if self._nav_depth and tag in _NAV_CONTAINERS:
            self._nav_depth -= 1
            return
        if not self._nav_depth:
            self._content_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self._nav_depth:
            self._content_data(data)

    def _pager_anchor(self, classes: set[str], href: str | None) -> None:
        if "usa-current" in classes:
            if self.current_page is not None:
                raise SecCommentsSourceError("SEC comments pager states more than one current page")
            values = [v for _, v in parse_qsl(urlsplit(urljoin(self.base_url, href or "")).query) if _ == "page"]
            if len(values) > 1:
                raise SecCommentsSourceError("SEC comments pager current item repeats its page parameter")
            if values and not values[0].isdigit():
                raise SecCommentsSourceError("SEC comments pager current item states a page that is not a number")
            self.current_page = int(values[0]) if values else 0
        if "usa-pagination__next-page" in classes:
            if self.next_url is not None:
                raise SecCommentsSourceError("SEC comments pager states more than one next page")
            if not isinstance(href, str) or not href:
                raise SecCommentsSourceError("SEC comments pager next-page link states no target")
            self.next_url = urljoin(self.base_url, href)

    def _content_starttag(self, tag: str, values: dict[str, str | None], classes: set[str]) -> None: ...

    def _content_endtag(self, tag: str) -> None: ...

    def _content_data(self, data: str) -> None: ...


class _RulemakingIndexHtml(_SecCommentsHtml):
    """Read the ``cols-4`` rulemaking table: dated rows, their status anchors and their titles."""

    def __init__(self, *, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self.rows: list[dict] = []
        self.saw_table = False
        self._table_depth = 0
        self._row: dict | None = None
        self._cell: dict | None = None
        self._time_datetime: str | None = None
        self._anchor: dict | None = None
        self._top_depth = 0
        self._node_title_depth = 0
        self._release_depth = 0

    def _content_starttag(self, tag: str, values: dict[str, str | None], classes: set[str]) -> None:
        if tag == "table":
            self._table_depth += 1
            if "cols-4" in classes and "views-table" in classes:
                if self.saw_table:
                    raise SecCommentsSourceError("SEC rulemaking index states a second rulemaking table")
                self.saw_table = True
            return
        if not self.saw_table:
            return
        if tag == "tr" and self._table_depth == 1:
            if self._row is not None:
                raise SecCommentsSourceError("SEC rulemaking index nests its rows")
            self._row = {"cells": [], "links": []}
        elif tag == "td" and self._row is not None:
            if self._cell is not None:
                raise SecCommentsSourceError("SEC rulemaking index nests its cells")
            self._cell = {"parts": [], "classes": classes}
        elif tag == "time" and self._cell is not None:
            self._time_datetime = values.get("datetime")
        elif tag == "a" and self._cell is not None:
            if self._anchor is not None:
                raise SecCommentsSourceError("SEC rulemaking index nests its links")
            self._anchor = {
                "href": values.get("href"),
                "classes": classes,
                "top": [],
                "node_title": [],
                "release": [],
                "parts": [],
            }
        elif self._anchor is not None and tag in ("span", "div"):
            # The status line sits in a span.info-button__top, the title in a
            # div.regulation-node-title and the release numbers in a
            # span.regulation-node-release-number, each possibly holding nested markup.
            if "info-button__top" in classes and tag == "span":
                self._top_depth += 1
            elif "regulation-node-title" in classes and tag == "div":
                self._node_title_depth += 1
            elif _RELEASE_SPAN_CLASS in classes and tag == "span":
                self._release_depth += 1
            elif self._top_depth or self._node_title_depth or self._release_depth:
                self._top_depth += self._top_depth > 0
                self._node_title_depth += self._node_title_depth > 0
                self._release_depth += self._release_depth > 0

    def _content_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._cell["datetime"] = self._time_datetime
            self._row["cells"].append(self._cell)
            self._cell, self._time_datetime = None, None
        elif tag == "a" and self._anchor is not None:
            if self._row is not None and self._cell is not None:
                self._row["links"].append(self._anchor)
            self._anchor, self._top_depth, self._node_title_depth, self._release_depth = None, 0, 0, 0
        elif self._anchor is not None and tag in ("span", "div"):
            self._top_depth -= self._top_depth > 0
            self._node_title_depth -= self._node_title_depth > 0
            self._release_depth -= self._release_depth > 0
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                if len(self.rows) >= MAX_PAGE_ROWS:
                    raise SecCommentsSourceError("SEC rulemaking index lists more rows than supported")
                self.rows.append(self._row)
            self._row = None

    def _content_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)
        if self._anchor is not None:
            if self._top_depth:
                self._anchor["top"].append(data)
            elif self._node_title_depth:
                self._anchor["node_title"].append(data)
            elif self._release_depth:
                self._anchor["release"].append(data)
            else:
                self._anchor["parts"].append(data)


class _CommentListingHtml(_SecCommentsHtml):
    """Read the ``h1``, the ``cols-1`` section table and the ``cols-3`` comment table."""

    def __init__(self, *, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self.title: list[str] = []
        self.sections: list[dict] = []
        self.comments: list[dict] = []
        self.saw_sections_table = False
        self.saw_comments_table = False
        self._saw_h1 = False
        self._in_h1 = False
        self._table_depth = 0
        self._kind: str | None = None
        self._row: dict | None = None
        self._cell: dict | None = None
        self._time_datetime: str | None = None
        self._anchor: dict | None = None

    def _content_starttag(self, tag: str, values: dict[str, str | None], classes: set[str]) -> None:
        if tag == "h1":
            if not self._saw_h1:
                self._saw_h1, self._in_h1 = True, True
        elif tag == "table":
            self._table_depth += 1
            if self._table_depth > 1:
                return
            if "views-table" not in classes:
                return
            if "cols-1" in classes:
                if self.saw_sections_table:
                    raise SecCommentsSourceError("SEC comment listing states a second section table")
                self._kind, self.saw_sections_table = "section", True
            elif "cols-3" in classes:
                if self.saw_comments_table:
                    raise SecCommentsSourceError("SEC comment listing states a second comment table")
                self._kind, self.saw_comments_table = "comment", True
        elif tag == "tr" and self._kind is not None and self._table_depth == 1:
            if self._row is not None:
                raise SecCommentsSourceError("SEC comment listing nests its rows")
            self._row = {"cells": [], "links": []}
        elif tag == "td" and self._row is not None:
            if self._cell is not None:
                raise SecCommentsSourceError("SEC comment listing nests its cells")
            self._cell = {"parts": [], "classes": classes}
        elif tag == "time" and self._cell is not None:
            self._time_datetime = values.get("datetime")
        elif tag == "a" and self._row is not None and self._cell is not None:
            if self._anchor is not None:
                raise SecCommentsSourceError("SEC comment listing nests its links")
            self._anchor = {"href": values.get("href"), "parts": []}

    def _content_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._kind = None
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._cell["datetime"] = self._time_datetime
            self._row["cells"].append(self._cell)
            self._cell, self._time_datetime = None, None
        elif tag == "a" and self._anchor is not None:
            if self._row is not None and self._cell is not None:
                self._row["links"].append(self._anchor)
            self._anchor = None
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                target = self.sections if self._kind == "section" else self.comments
                if len(target) >= MAX_PAGE_ROWS:
                    raise SecCommentsSourceError("SEC comment listing lists more rows than supported")
                target.append(self._row)
            self._row = None

    def _content_data(self, data: str) -> None:
        if self._in_h1:
            self.title.append(data)
        if self._cell is not None:
            self._cell["parts"].append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)


def _read_page(parser: HTMLParser, body: bytes, max_bytes: int, label: str) -> None:
    """Decode one bounded page and feed it to ``parser``."""
    text = decode_html_page(body, max_bytes, label=label, cap=MAX_PAGE_BYTES, error_type=SecCommentsSourceError)
    feed_html(parser, text, label=label, error_type=SecCommentsSourceError)


def _assert_pager_agrees(label: str, url: str, pager: SecPager) -> None:
    """The page's own statement of which page it is must match the page the URL requested.

    A render of another page -- the condition the salvaged Supreme Court
    reader was bitten by -- refuses instead of being read as this page's rows.
    A page with no pager is the only page: requesting a later one through a
    URL that no longer exists is a refusal, not a quiet empty answer.
    """
    requested = requested_page_number(url)
    if pager.current_page is not None and pager.current_page != requested:
        raise SecCommentsSourceError(
            f"{label} states it is page {pager.current_page}, not the requested page {requested}"
        )
    if pager.current_page is None and pager.next_url is None and requested > 0:
        raise SecCommentsSourceError(f"{label} serves its only page where page {requested} was requested")


def _rule_url(href: object, base_url: str) -> str:
    if not isinstance(href, str) or not href:
        raise SecCommentsSourceError("SEC rulemaking index status link states no target")
    return rule_page_url(urljoin(base_url, href))


def _rulemaking(index: int, row: dict, base_url: str) -> SecRulemaking:
    """One row: cells read by their exact class tokens, then the status anchor's own statements."""
    by_class: dict[str, dict] = {}
    for cell in row["cells"]:
        for token in cell["classes"]:
            by_class.setdefault(token, cell)
    published = None
    if cell := by_class.get("views-field-field-publish-date"):
        published = cell["datetime"] if isinstance(cell["datetime"], str) else None
    file_number = None
    if cell := by_class.get("views-field-field-release-file-number"):
        file_number = _text(cell["parts"], "file number") or None
    title = (
        _text(by_class["views-field-nothing-1"]["parts"], "rulemaking title")
        if "views-field-nothing-1" in by_class
        else ""
    )
    status = rule_url = None
    release_numbers: tuple[str, ...] = ()
    # A row states its status through one ``info-button`` anchor; a second
    # anchor also occurs, the row's ``View Related Activity`` search link, and
    # it is not a status statement. Only the info-button anchor is read.
    links = [link for link in row["links"] if "info-button" in link["classes"]]
    if len(links) > 1:
        raise SecCommentsSourceError("SEC rulemaking index row states more than one status link")
    if links:
        status = _text(links[0]["top"], "status") or None
        rule_url = _rule_url(links[0]["href"], base_url)
        title = title or _text(links[0]["node_title"], "rulemaking title")
        release_numbers = _release_numbers(_text(links[0]["release"], "release numbers"))
    if not title:
        raise SecCommentsSourceError("SEC rulemaking index row states no title")
    return SecRulemaking(
        index=index,
        file_number=file_number,
        title=title,
        status=status,
        published=published,
        rule_url=rule_url,
        release_numbers=release_numbers,
    )


def _release_numbers(text: str) -> tuple[str, ...]:
    """The release numbers one statement carries, in the page's order, deduplicated."""
    numbers: dict[str, None] = {}
    for match in _RELEASE_NUMBER.finditer(text):
        numbers[match[0]] = None
        if len(numbers) > _MAX_RELEASE_NUMBERS:
            raise SecCommentsSourceError("SEC release-number statement names more numbers than supported")
    return tuple(numbers)


def _index_page_url(url: str) -> str:
    parts = urlsplit(url) if isinstance(url, str) else None
    if (
        parts is None
        or parts.scheme != "https"
        or parts.hostname != SEC_HOST
        or parts.path.rstrip("/") != RULEMAKING_INDEX_PATH
        or parts.fragment
    ):
        raise SecCommentsSourceError("SEC rulemaking index URL must be the publisher's rulemaking-activity route")
    return url


def parse_rulemaking_index_page(
    body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES
) -> SecRulemakingIndexPage:
    """Read one index render, or one page of it. O(B) in the response bytes; one pass, no per-row rescan."""
    url = _index_page_url(url)
    parser = _RulemakingIndexHtml(base_url=url)
    _read_page(parser, body, max_bytes, "SEC rulemaking index")
    if not parser.saw_table:
        raise SecCommentsSourceError("SEC rulemaking index states no rulemaking table")
    pager = SecPager(parser.current_page, parser.next_url)
    _assert_pager_agrees("SEC rulemaking index", url, pager)
    return SecRulemakingIndexPage(
        url=url,
        rulemakings=tuple(_rulemaking(number, row, url) for number, row in enumerate(parser.rows)),
        pager=pager,
    )


def listing_docket(url: str) -> str:
    """The docket directory a listing URL names; the URL's grammar is checked, not trusted."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if (
        parts is None
        or parts.scheme != "https"
        or parts.netloc != SEC_HOST
        or not parts.path.startswith(COMMENTS_PATH_PREFIX)
    ):
        raise SecCommentsSourceError("SEC comment listing URL must be an HTTPS sec.gov /comments/ route")
    segments = parts.path.lstrip("/").split("/")
    if len(segments) != 3 or segments[0] != "comments" or not all(segments[1:]):
        raise SecCommentsSourceError("SEC comment listing URL path must be /comments/{docket}/{file}")
    docket, file_name = segments[1], segments[2]
    if _DOCKET.fullmatch(docket.lower()) is None or _FILE_NAME.fullmatch(file_name) is None:
        raise SecCommentsSourceError("SEC comment listing URL does not follow the publisher's docket grammar")
    return docket.lower()


def _docket_file(href: object, docket: str, base_url: str) -> tuple[str, str, CommentFormat]:
    """Resolve one listing link and prove it stays in this docket's directory with a known format."""
    if not isinstance(href, str) or not href:
        raise SecCommentsSourceError("SEC comment listing link states no target")
    parts = urlsplit(urljoin(base_url, href))
    if parts.scheme != "https" or parts.netloc != SEC_HOST or parts.query or parts.fragment:
        raise SecCommentsSourceError("SEC comment listing link is not a plain HTTPS sec.gov file")
    segments = parts.path.lstrip("/").split("/")
    # The live S7-08-23 listing links a PDF through /comments/S7-08-23/.
    # Compare the docket spelling without case, but retain the exact stated URL.
    if len(segments) != 3 or segments[0] != "comments" or segments[1].lower() != docket.lower():
        raise SecCommentsSourceError("SEC comment listing link leaves its docket's directory")
    file_name = segments[2]
    if _FILE_NAME.fullmatch(file_name) is None or "." not in file_name:
        raise SecCommentsSourceError("SEC comment listing link does not name a file")
    extension = file_name.rsplit(".", 1)[1].lower()
    if extension not in COMMENT_EXTENSIONS:
        raise SecCommentsSourceError("SEC comment listing link names a format this route does not read")
    return f"https://{parts.netloc}{parts.path}", file_name, cast(CommentFormat, extension)


def _section(row: dict, docket: str, base_url: str) -> SecCommentSection:
    links = list(row["links"])
    if len(links) != 1:
        raise SecCommentsSourceError("SEC comment section row must state exactly one link")
    url, _file_name, extension = _docket_file(links[0]["href"], docket, base_url)
    return SecCommentSection(docket, _text(links[0]["parts"], "section label"), url, extension)


def _comment(row: dict, docket: str, base_url: str) -> SecCommentFile:
    links = list(row["links"])
    if len(links) != 1:
        raise SecCommentsSourceError("SEC comment row must state exactly one link")
    by_class: dict[str, dict] = {}
    for cell in row["cells"]:
        for token in cell["classes"]:
            by_class.setdefault(token, cell)
    date = None
    if cell := by_class.get("views-field-field-comment-date"):
        date = cell["datetime"] if isinstance(cell["datetime"], str) else None
    letter_type = None
    if cell := by_class.get("views-field-field-comment-letter-type-1"):
        letter_type = _text(cell["parts"], "letter type") or None
    url, file_name, extension = _docket_file(links[0]["href"], docket, base_url)
    return SecCommentFile(
        docket=docket,
        url=url,
        file_name=file_name,
        link_text=_text(links[0]["parts"], "commenter name"),
        format=extension,
        letter_type=letter_type,
        date=date,
    )


def parse_comment_listing_page(
    body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES
) -> SecCommentListingPage:
    """Read one listing render, or one page of it. O(B) in the response bytes, one pass.

    The comments table must be present -- a render without it is a challenge
    or error page wearing the URL -- but present-and-empty is an observation
    the caller keeps: requested-empty is never source absence.
    """
    docket = listing_docket(url)
    parser = _CommentListingHtml(base_url=url)
    _read_page(parser, body, max_bytes, "SEC comment listing")
    if not parser.saw_comments_table:
        raise SecCommentsSourceError("SEC comment listing states no comment table")
    pager = SecPager(parser.current_page, parser.next_url)
    _assert_pager_agrees("SEC comment listing", url, pager)
    return SecCommentListingPage(
        url=url,
        docket=docket,
        title=_text(parser.title, "listing title"),
        sections=tuple(_section(row, docket, url) for row in parser.sections),
        comments=tuple(_comment(row, docket, url) for row in parser.comments),
        pager=pager,
    )


class _RulePageHtml(HTMLParser):
    """Collect a rule page's own statements: the first ``h1`` title, the publisher's statement fields,
    and the page's prose for citation statements the fields do not repeat.

    The live page (S7-11-23, 2026-09-24) states the file number, each release
    number and each document citation through Drupal fields marked with
    ``field--name-`` machine names, each value in its own ``field__item`` div
    beside a ``field__label``. A field is read only when its label names the
    statement (``File Number``, ``Release Number``, ``Document Citation``):
    the live page reuses the release-number template for ``Title`` fields, so
    the label, not the machine name alone, is the publisher's witness. Text
    outside the fields is kept as prose -- the extension block states its
    citation in a sentence (``at 90 FR 2837``) rather than a field. Script
    and style contents are not the page's statements.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.text: list[str] = []
        self.file_numbers: list[str] = []
        self.release_numbers: list[str] = []
        self.citations: list[str] = []
        self.comment_links: list[str | None] = []
        self._comments_depth = 0
        self._saw_h1 = False
        self._in_h1 = False
        self._skip_depth = 0
        self._field: str | None = None
        self._field_depth = 0
        self._label_depth = 0
        self._item_depth = 0
        self._label_parts: list[str] = []
        self._item_parts: list[str] = []

    @property
    def unclosed(self) -> bool:
        """Whether a statement or received-comments field was still open when the page ended."""
        return bool(self._field is not None or self._label_depth or self._item_depth or self._comments_depth)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag == "br":
            # A line break separates words; like every void element it has no end tag to count.
            self.handle_data(" ")
            return
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "div":
            if self._comments_depth:
                self._comments_depth += 1
            elif "field--name-field-comments-received" in classes:
                self._comments_depth = 1
        if tag == "a" and self._comments_depth:
            if len(self.comment_links) >= _MAX_COMMENT_LISTINGS:
                raise SecCommentsSourceError("SEC rule page states more comment listings than supported")
            self.comment_links.append(values.get("href"))
        # Depth counts divs only: void and implicitly closed tags (``img``, ``p``) have no reliable end tag.
        if self._label_depth or self._item_depth:
            if tag == "div":
                self._label_depth += self._label_depth > 0
                self._item_depth += self._item_depth > 0
            return
        if tag == "h1":
            self._in_h1 = not self._saw_h1
            self._saw_h1 = True
            return
        if tag == "div":
            if self._field is not None:
                self._field_depth += 1
                if "field__label" in classes:
                    self._label_depth = 1
                    self._label_parts = []
                elif "field__item" in classes:
                    self._item_depth = 1
                    self._item_parts = []
                return
            for name in _RULE_PAGE_STATEMENT_FIELDS:
                if f"field--name-{name}" in classes:
                    self._field, self._field_depth, self._label_parts = name, 1, []
                    return

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "h1":
            self._in_h1 = False
            return
        if tag != "div":
            return
        if self._comments_depth:
            self._comments_depth -= 1
        if self._label_depth:
            self._label_depth -= 1
            self._field_depth -= self._label_depth == 0
            return
        if self._item_depth:
            self._item_depth -= 1
            if self._item_depth == 0 and self._field is not None:
                self._field_depth -= 1
                expected = _RULE_PAGE_STATEMENT_FIELDS[self._field]
                if " ".join("".join(self._label_parts).split()).casefold() == expected:
                    target = {
                        "field-file-number": "file_numbers",
                        "field-release-number": "release_numbers",
                        "field-document-citation": "citations",
                    }[self._field]
                    getattr(self, target).append(" ".join("".join(self._item_parts).split()))
            return
        if self._field is not None:
            self._field_depth -= 1
            if self._field_depth == 0:
                self._field = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._label_depth:
            self._label_parts.append(data)
        elif self._item_depth:
            self._item_parts.append(data)
        elif self._in_h1:
            self.title.append(data)
        else:
            self.text.append(data)


def rule_page_url(url: str) -> str:
    """The per-rule page route: ``/rules-regulations/{year}/{month}/{slug}``, fragment dropped.

    The index's status anchors carry a fragment (``#34-103320final``) naming
    an anchor on the page, not the resource; like :func:`_rule_url`, the
    canonical locator keeps the path only.
    """
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        parts = None
    if parts is None or parts.scheme != "https" or parts.netloc != SEC_HOST or parts.query:
        raise SecCommentsSourceError("SEC rule page URL must be a plain HTTPS sec.gov rulemaking route")
    segments = parts.path.rstrip("/").lstrip("/").split("/")
    if (
        len(segments) != 4
        or segments[0] != "rules-regulations"
        or len(segments[1]) != 4
        or not segments[1].isdigit()
        or len(segments[2]) != 2
        or not segments[2].isdigit()
        or _RULE_PAGE_SLUG.fullmatch(segments[3]) is None
    ):
        raise SecCommentsSourceError("SEC rule page URL must be /rules-regulations/{year}/{month}/{slug}")
    return f"https://{parts.netloc}{parts.path}"


def _comment_listing_urls(parser: _RulePageHtml, base_url: str) -> tuple[str, ...]:
    """Read only the received-comments field; an unusable stated link is a refusal."""
    urls: list[str] = []
    for href in parser.comment_links:
        if (
            not isinstance(href, str)
            or not href
            or any(char.isspace() for char in href)
            or len(href) > MAX_FIELD_LENGTH
        ):
            raise SecCommentsSourceError("SEC rule page comment-listing link states no bounded target")
        try:
            parts = urlsplit(urljoin(base_url, href))
        except ValueError:
            raise SecCommentsSourceError("SEC rule page comment-listing link has an invalid URL") from None
        if (
            parts.scheme != "https"
            or parts.netloc != SEC_HOST
            or parts.query
            or parts.fragment
            or not parts.path.lower().endswith((".htm", ".html"))
        ):
            raise SecCommentsSourceError(
                "SEC rule page comment-listing link must name a plain HTTPS sec.gov HTML listing"
            )
        url = f"{SEC_SITE}{parts.path}"
        listing_docket(url)
        if url not in urls:
            urls.append(url)
    return tuple(urls)


def _file_number(parser: _RulePageHtml) -> str | None:
    """The ``File Number`` field's one value, lowercased; None when the page states none.

    A value that does not follow the docket grammar refuses: a broken spelling
    is a statement this reader cannot honor, never an observation that the
    page states no file number. Conflicting values refuse for the same reason.
    """
    numbers = {item.strip().lower() for item in parser.file_numbers}
    if any(_DOCKET.fullmatch(number) is None for number in numbers):
        raise SecCommentsSourceError("SEC rule page file-number statement does not follow the docket grammar")
    if len(numbers) > 1:
        raise SecCommentsSourceError("SEC rule page states conflicting file numbers")
    return next(iter(numbers), None)


def _release_number_items(parser: _RulePageHtml) -> tuple[str, ...]:
    """Every ``Release Number`` field item, checked whole against the release-number grammar, in page order."""
    numbers: dict[str, None] = {}
    for item in parser.release_numbers:
        if _RELEASE_NUMBER.fullmatch(value := item.strip()) is None:
            raise SecCommentsSourceError("SEC rule page release-number statement is not a release number")
        numbers[value] = None
        if len(numbers) > _MAX_RELEASE_NUMBERS:
            raise SecCommentsSourceError("SEC rule page states more release numbers than supported")
    return tuple(numbers)


def _citation_items(parser: _RulePageHtml, prose: str) -> tuple[str, ...]:
    """Every FR citation the page states: the ``Document Citation`` fields first, then the prose, deduplicated.

    A ``Document Citation`` field item that states no citation refuses: a
    broken statement is never read as absence. The prose scan exists because
    the live page states the extension's citation in a sentence rather than a
    field. The `` | `` separator keeps a citation from spanning two statements.
    """
    if any(_FR_CITATION.search(item) is None for item in parser.citations):
        raise SecCommentsSourceError("SEC rule page citation field states no FR citation")
    citations: dict[str, None] = {}
    for match in _FR_CITATION.finditer(" | ".join((*parser.citations, prose))):
        citations[f"{match[1]} FR {match[2]}"] = None
        if len(citations) > _MAX_FR_CITATIONS:
            raise SecCommentsSourceError("SEC rule page states more FR citations than supported")
    return tuple(citations)


def parse_rule_page(body: bytes, *, url: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> SecRulePage:
    """Read one rule page's own statements. O(B) in the response bytes, one pass.

    The title is the first ``h1``; the file number, release numbers and
    document citations are the publisher's ``field--name-`` statement fields,
    each read only when its own label names the statement; FR citations in the
    page's prose are read too. The identity discipline is the index reader's:
    a render without a title refuses, because a challenge or error page wears
    the URL the same way. Received-comments links are read only inside their
    publisher-marked field. A page that states no file number, releases,
    citations or comment-listing links is an observation the caller keeps.
    """
    page_url = rule_page_url(url)
    parser = _RulePageHtml()
    _read_page(parser, body, max_bytes, "SEC rule page")
    if parser.unclosed:
        raise SecCommentsSourceError("SEC rule page leaves a statement field open; its statements cannot be read")
    title = _text(parser.title, "rule page title")
    if not title:
        raise SecCommentsSourceError("SEC rule page states no title")
    prose = " ".join("".join(parser.text).split())
    return SecRulePage(
        url=page_url,
        title=title,
        file_number=_file_number(parser),
        release_numbers=_release_number_items(parser),
        fr_citations=_citation_items(parser, prose),
        comment_listing_urls=_comment_listing_urls(parser, page_url),
    )
