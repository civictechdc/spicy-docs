"""GAO's Month in Review and Annual Index: the publisher's own list of the products it issued, by month and year.

GAO states the listing on its Month in Review page: "GAO makes monthly and annual lists of our reports, grouped by
topic". Probed 2026-09-28 (``corpora/mcp-chaos-2026-09-28/gao-sitemap/``), month pages
(``/reports-testimonies/month-in-review/2026/August``) and year pages (``.../2025``; ``.../2009`` answers though the
landing page links only 2015 on) are one Drupal view of 25 teasers a page, paged with ``?page=N`` and grouped under
GAO's topic headings, then its legal-product headings. A year page is a calendar year of releases, although its
title says "(FY2025)". A product sits under every topic it carries, so it can appear on several pages. Each teaser
states the product number, its product link, a label and a heading (GAO's title is ``label: heading``), and
"Published" and "Publicly Released" dates. A month's list can hold a product released in the month before, so no date
is checked against the scope.

``www.gao.gov`` refuses plain clients, so pages come through Zyte, as product pages do. ``robots.txt`` disallows
``/reports-testimonies`` by prefix and asks for a 420-second ``Crawl-delay``. The library default honours that delay:
one worker, one request every 420 seconds, under a hard Zyte budget, resuming from its own receipts. For the backfill
of 2009-2025 and January-August 2026 (2026-09-28) the owner overrode it with run flags; see ``docs/decisions.md``.

The number decides the class: ``GAO-`` is a product, ``B-`` a legal decision (its numbers split, one teaser can name
several), anything else is kept apart. One named exception, the owner's: every Federal Agency Major Rule Report is a
product, GAO-numbered up to February 2017 and B-numbered from April 2017, keyed on its page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote
from uuid import uuid4

from spicy_docs.reading.markup import HTML_VOID_TAGS, decode_html_page, feed_html, joined_text
from spicy_docs.sources.gao.native import GaoProductSourceError, gao_product_url
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import SourceAcquirer, check_byte_bound, check_timing, utc_now

if TYPE_CHECKING:
    import httpx

    from spicy_docs.transport.zyte import ZyteBudget, ZyteProxyRecord

LISTING_URL: Final = "https://www.gao.gov/reports-testimonies/month-in-review"
MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
#: ``robots.txt`` asks every agent for this ``Crawl-delay`` (read 2026-09-28); it is the walk's default spacing.
CRAWL_DELAY_SECONDS: Final = 420.0
#: Pages measured 45-75 KB on 2026-09-28.
DEFAULT_MAX_PAGE_BYTES: Final = 4 * 1024 * 1024
MAX_PAGE_BYTES: Final = 16 * 1024 * 1024
#: The deepest pager seen was 2009's, last page index 87; a deeper one is refused rather than walked.
DEFAULT_MAX_LAST_PAGE_INDEX: Final = 199
#: GAO's label and heading for a major-rule report. Every one of the 1,655 on the 2009-2026 walk carries both.
MAJOR_RULE_REPORT: Final = "Federal Agency Major Rule Report"
#: Workers a walk may run. The 2026-09-28 backfill stalled at six (requests hanging to the 180 s timeout) and
#: finished at three with a 60 s timeout.
MAX_CONCURRENCY: Final = 8
#: The longest pause between failures in a row; the pause doubles from the backoff up to this.
MAX_BACKOFF_SECONDS: Final = 900.0
#: A scope whose listing moves while it is read is restarted from its first page this many times, then stopped.
MAX_SCOPE_RESTARTS: Final = 1
_MAX_TEXT: Final = 4_000
_LABEL: Final = "GAO listing page"
_PAGE_HREF = re.compile(r"\?page=(\d+)")
#: HTML's own whitespace. A non-breaking space is text GAO wrote, and the feed's titles keep it.
_HTML_WHITESPACE = re.compile(r"[\t\n\f\r ]+")
#: One B-number as GAO states it: its file number, then whatever suffix older decisions carry (``B-235577.2-O.M.``,
#: a bare ``B-414056.``). Decisions are kept apart and keyed on their whole stated number, so each part need only
#: be a B-number, not a checked one.
_DECISION_NUMBER = re.compile(r"B-\d+[A-Z0-9.\-]*")
#: Older decisions list their numbers with commas or semicolons, with stray spaces and a trailing separator.
_DECISION_SEPARATOR = re.compile(r"[,;]")
_TOKENS = re.compile(r"[a-z0-9]+")
_PRERELEASE = re.compile(r"/prerelease/[a-z0-9]+")
#: Drupal's suffix for a path alias already taken: 2015 links GAO-16-75SP as ``/products/gao-16-75sp-0``.
_DUPLICATE_PATH = re.compile(r"-\d+")
_TRAILING_DUPLICATE_PATH = re.compile(r"-\d+\Z")
_FIELD_CLASSES: Final = {
    "field--name-field-product-number": "number",
    "field--name-field-issue-date": "published",
    "field--name-field-docdate": "released",
}
_DATE_PREFIXES: Final = {"published": "Published:", "released": "Publicly Released:"}
_CAPTURED: Final = frozenset({"label", "heading", "number", "published", "released"})


class GaoListingSourceError(ValueError):
    """A listing page cannot establish the products GAO listed for its scope."""


class GaoListingMovedError(GaoListingSourceError):
    """A page disagrees with its scope's first page on the last page or the page size: the listing moved."""


class GaoListingUnavailableError(GaoListingSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"GAO listing answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class GaoListingScope:
    """One year's Annual Index (``month`` None) or one month's Month in Review."""

    year: int
    month: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.year, bool) or not isinstance(self.year, int) or not 1900 <= self.year <= 2999:
            raise GaoListingSourceError("GAO listing year must be a four-digit year")
        if self.month is not None and (
            isinstance(self.month, bool) or not isinstance(self.month, int) or not 1 <= self.month <= 12
        ):
            raise GaoListingSourceError("GAO listing month must be 1 to 12")

    @classmethod
    def parse(cls, value: str) -> GaoListingScope:
        """``YYYY`` names a year's index, ``YYYY-MM`` a month's review."""
        match = re.fullmatch(r"(\d{4})(?:-(\d{2}))?", value)
        if match is None:
            raise GaoListingSourceError(f"GAO listing scope must be YYYY or YYYY-MM, not {value!r}")
        return cls(int(match[1]), None if match[2] is None else int(match[2]))

    @property
    def key(self) -> str:
        return f"{self.year}" if self.month is None else f"{self.year}-{self.month:02d}"

    @property
    def url(self) -> str:
        """The page's own canonical URL; GAO spells the month by name."""
        return f"{LISTING_URL}/{self.year}" + ("" if self.month is None else f"/{MONTHS[self.month - 1]}")

    def page_url(self, page_index: int) -> str:
        """The first page is the bare URL GAO links; later pages add the pager's ``?page=N``."""
        return self.url if page_index == 0 else f"{self.url}?page={page_index}"

    @property
    def title(self) -> str:
        if self.month is None:
            return f"U.S. GAO - Annual Index of Reports, Testimony and Correspondence (FY{self.year})"
        return f"U.S. GAO - Month in Review, {MONTHS[self.month - 1]} {self.year}"


@dataclass(frozen=True, slots=True)
class GaoListingEntry:
    """One teaser as GAO spelled it: a product (``product_id``), a decision (``decision_numbers``), or neither, for a
    number of another form or none (``product_number`` None)."""

    position: int
    topic: str
    product_number: str | None
    link: str
    label: str
    heading: str
    published: str | None
    released: str | None
    product_id: str | None
    decision_numbers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GaoListingPage:
    scope: GaoListingScope
    page_index: int
    last_page_index: int
    entries: tuple[GaoListingEntry, ...]


class _ListingHtml(HTMLParser):
    """The head's title and canonical link; inside ``<main>``, headings, teasers and pager links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[list[str]] = []
        self.canonicals: list[str] = []
        self.pagers = 0
        self.pager_links: list[tuple[str, str | None, str | None]] = []
        self.teasers: list[dict] = []
        self._head = self._main = 0
        self._title: list[str] | None = None
        self._heading: list[str] | None = None
        self._topic: str | None = None
        self._in_pager = False
        self._teaser: dict | None = None
        #: Open elements inside the current teaser, each with the role its text takes, if any.
        self._stack: list[tuple[str, str | None]] = []

    @property
    def unclosed(self) -> bool:
        return self._title is not None or self._heading is not None or self._teaser is not None or self._in_pager

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "head":
            self._head += 1
        elif tag == "title" and self._head:
            self._title = []
        elif tag == "link" and (attributes.get("rel") or "").casefold() == "canonical":
            self.canonicals.append(attributes.get("href") or "")
        elif tag == "main":
            self._main += 1
        if not self._main or tag in HTML_VOID_TAGS:
            return
        if self._teaser is not None:
            self._teaser_start(tag, attributes, classes)
        elif tag == "article":
            if "node--type-product" not in classes:
                raise GaoListingSourceError(f"{_LABEL} lists a teaser that is not a product")
            self._teaser = {"topic": self._topic, "fields": {}, "links": {}}
        elif tag == "h2":
            self._heading = []
        elif tag == "nav" and attributes.get("aria-label") == "Pagination":
            self.pagers += 1
            self._in_pager = True
        elif tag == "a" and self._in_pager:
            self.pager_links.append(
                (attributes.get("href") or "", attributes.get("aria-label"), attributes.get("aria-current"))
            )

    def _teaser_start(self, tag: str, attributes: dict[str, str | None], classes: set[str]) -> None:
        if tag == "article":
            raise GaoListingSourceError(f"{_LABEL} nests one teaser inside another")
        assert self._teaser is not None
        parent = next((role for _, role in reversed(self._stack) if role), None)
        role = None
        if tag == "div" and "teaser-search--bookmark" in classes:
            role = "bookmark"
        elif tag == "h3" and "heading" in classes:
            role = "headline"
        elif tag == "a" and parent in ("bookmark", "headline"):
            role = "label" if parent == "bookmark" else "heading"
            self._teaser["links"][role] = attributes.get("href") or ""
        elif tag == "div":
            role = next((name for css, name in _FIELD_CLASSES.items() if css in classes), None)
        if role in _CAPTURED:
            if role in self._teaser["fields"]:
                raise GaoListingSourceError(f"{_LABEL} teaser repeats its {role}")
            self._teaser["fields"][role] = []
        self._stack.append((tag, role))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head" and self._head:
            self._head -= 1
        elif tag == "title" and self._title is not None:
            self.titles.append(self._title)
            self._title = None
        elif tag == "main" and self._main:
            self._main -= 1
        if self._teaser is not None:
            if tag == "article":
                self.teasers.append(self._teaser)
                self._teaser, self._stack = None, []
                return
            for index in range(len(self._stack) - 1, -1, -1):
                if self._stack[index][0] == tag:
                    del self._stack[index:]
                    break
        elif tag == "h2" and self._heading is not None:
            self._topic = _spelled(self._heading, "topic heading")
            self._heading = None
        elif tag == "nav" and self._in_pager:
            self._in_pager = False

    def handle_data(self, data: str) -> None:
        if self._title is not None:
            self._title.append(data)
        if self._teaser is not None:
            role = next((role for _, role in reversed(self._stack) if role in _CAPTURED), None)
            if role is not None:
                self._teaser["fields"][role].append(data)
        elif self._heading is not None:
            self._heading.append(data)


def _text(parts: list[str] | None, name: str) -> str:
    return joined_text(parts or [], label=f"{_LABEL} {name}", bound=_MAX_TEXT, error_type=GaoListingSourceError)


def _spelled(parts: list[str] | None, name: str) -> str:
    """Text as GAO wrote it: references decoded, runs of HTML whitespace one space, non-breaking spaces kept."""
    value = _HTML_WHITESPACE.sub(" ", "".join(parts or [])).strip("\t\n\f\r ")
    if len(value) > _MAX_TEXT:
        raise GaoListingSourceError(f"{_LABEL} {name} exceeds its length bound")
    return value


def _date(parts: list[str] | None, name: str) -> str | None:
    """GAO's ``Published: Jul 14, 2026.`` as ``2026-07-14``; an absent field stays None, an unreadable one refuses."""
    if parts is None:
        return None
    value = _text(parts, name)
    prefix = _DATE_PREFIXES[name]
    if not value.startswith(prefix):
        raise GaoListingSourceError(f"{_LABEL} {name} date does not begin {prefix!r}")
    try:
        return (
            datetime.strptime(value.removeprefix(prefix).strip().rstrip("."), "%b %d, %Y")
            .replace(tzinfo=UTC)
            .date()
            .isoformat()
        )
    except ValueError as error:
        raise GaoListingSourceError(f"{_LABEL} {name} date is not GAO's 'Mon DD, YYYY'") from error


def _same_letters(slug: str, number: str) -> bool:
    """A link names a number when their letter-and-digit tokens agree, less a trailing duplicate-path ``-N``.

    Tokens, not the letters run together: ``B-4241292`` and ``b-424129.2`` share every character but name two files.
    """
    wanted = _TOKENS.findall(number.lower())
    if _TOKENS.findall(slug) == wanted:
        return True
    suffix = _TRAILING_DUPLICATE_PATH.search(slug)
    return suffix is not None and _TOKENS.findall(slug[: suffix.start()]) == wanted


def _entry(position: int, teaser: dict) -> GaoListingEntry:
    """One teaser, classed by its number, with the owner's one exception for major-rule reports.

    ``GAO-`` is a product and ``B-`` a decision wherever GAO files it: major-rule reports numbered ``GAO-14-253R``
    sit under a legal heading (2009 to February 2017), and three B-numbered decisions sit under topic headings
    (B-310950.2 in 2009, B-318897 in 2010, B-333501 in 2021). Any other number (a Contract Appeals Board docket,
    ``2020-02``; a ``P`` number) or none is set apart. The exception: a teaser labelled Federal Agency Major Rule
    Report is a product whatever its number, so the B-numbered ones from April 2017 on are products too, keyed on
    their page like the others.
    """
    fields, links = teaser["fields"], teaser["links"]
    label, heading = _spelled(fields.get("label"), "label"), _spelled(fields.get("heading"), "heading")
    number = _text(fields.get("number"), "number") or None
    if not (label and heading):
        raise GaoListingSourceError(f"{_LABEL} teaser {position} lacks a label or heading")
    if not teaser["topic"]:
        raise GaoListingSourceError(f"{_LABEL} lists a teaser before any heading")
    link = links.get("label", "")
    gao_numbered = number is not None and number.upper().startswith("GAO-")
    b_numbered = number is not None and number.startswith("B-")
    major_rule = label == MAJOR_RULE_REPORT and (gao_numbered or b_numbered)
    # 2020-2023 link some products by their prerelease path (``/prerelease/3mpz``); the product's page is still
    # ``/products/`` and its number lowercased, checked for GAO-21-584 on 2026-09-28.
    prerelease = gao_numbered and _PRERELEASE.fullmatch(link) is not None
    if link != links.get("heading") or not (link.startswith("/products/") or prerelease):
        raise GaoListingSourceError(f"{_LABEL} teaser {position} does not link one product page")
    slug = number.lower() if prerelease and number is not None else unquote(link.removeprefix("/products/"))
    # A GAO number's link is the number lowercased, or that with Drupal's duplicate-path suffix. Any other number's
    # link need only agree with it token for token: older decisions link ``b-402003-b-402003.2`` for
    # ``B-402003; B-402003.2``, and a docket's second page is ``2020-02-0``.
    if number is not None and not (
        slug == number.lower() or (slug.startswith(number.lower()) and _DUPLICATE_PATH.fullmatch(slug[len(number) :]))
        if gao_numbered
        else _same_letters(slug, number)
    ):
        raise GaoListingSourceError(f"{_LABEL} teaser {position} links a page other than its product number")
    product_id: str | None = None
    decisions: tuple[str, ...] = ()
    if gao_numbered or major_rule:
        try:
            gao_product_url(slug)
        except GaoProductSourceError as error:
            raise GaoListingSourceError(f"{_LABEL} teaser {position} names no product id") from error
        product_id = slug
    elif b_numbered and number is not None:
        # The whole stated number keys a decision. Its parts are what of it reads as B-numbers: GAO cut one long
        # 2010 list mid-number ("...,B-403648,B"), and a fragment is not a number.
        parts = (part.strip() for part in _DECISION_SEPARATOR.split(number))
        decisions = tuple(part for part in parts if _DECISION_NUMBER.fullmatch(part))
        if not decisions:
            raise GaoListingSourceError(f"{_LABEL} teaser {position} names no B-number")
    return GaoListingEntry(
        position,
        teaser["topic"],
        number,
        link,
        label,
        heading,
        _date(fields.get("published"), "published"),
        _date(fields.get("released"), "released"),
        product_id,
        decisions,
    )


def _last_page_index(reader: _ListingHtml, page_index: int) -> int:
    """The pager's last page; its current page must be the one requested, and every link a ``?page=N``."""
    if not reader.pagers:
        if page_index:
            raise GaoListingSourceError(f"{_LABEL} {page_index} has no pager")
        return 0
    if reader.pagers > 1:
        raise GaoListingSourceError(f"{_LABEL} has more than one pager")
    numbered, current, last = [], [], []
    for href, label, marker in reader.pager_links:
        match = _PAGE_HREF.fullmatch(href)
        if match is None:
            raise GaoListingSourceError(f"{_LABEL} pager links something other than a page")
        index = int(match[1])
        if label is not None and label.startswith("Page "):
            if label != f"Page {index + 1}":
                raise GaoListingSourceError(f"{_LABEL} pager numbers a page inconsistently")
            numbered.append(index)
        if marker == "page":
            current.append(index)
        if label == "Last page":
            last.append(index)
    if current != [page_index]:
        raise GaoListingSourceError(f"{_LABEL} pager does not mark page {page_index} as current")
    if last:
        if len(last) != 1 or last[0] <= page_index:
            raise GaoListingSourceError(f"{_LABEL} pager states an impossible last page")
        return last[0]
    if not numbered or max(numbered) != page_index:
        raise GaoListingSourceError(f"{_LABEL} pager has no last page and page {page_index} is not the last")
    return page_index


def parse_listing_page(
    body: bytes,
    *,
    scope: GaoListingScope,
    page_index: int,
    max_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    max_last_page_index: int = DEFAULT_MAX_LAST_PAGE_INDEX,
    expected_last_page_index: int | None = None,
    expected_page_size: int | None = None,
) -> GaoListingPage:
    """One page, refused unless it is its scope's page ``page_index`` and agrees with the pages already read.

    ``expected_last_page_index`` and ``expected_page_size`` come from the scope's first page: a pager that
    changes its last page, or a page before the last holding a different number of teasers, means the listing
    moved while it was read.
    """
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
        raise GaoListingSourceError("page_index must be a nonnegative integer")
    text = decode_html_page(body, max_bytes, label=_LABEL, cap=MAX_PAGE_BYTES, error_type=GaoListingSourceError)
    reader = _ListingHtml()
    feed_html(reader, text, label=_LABEL, error_type=GaoListingSourceError)
    if reader.unclosed:
        raise GaoListingSourceError(f"{_LABEL} markup is incomplete")
    if [_text(parts, "title") for parts in reader.titles] != [scope.title]:
        raise GaoListingSourceError(f"{_LABEL} is not titled {scope.title!r}")
    if reader.canonicals != [scope.url]:
        raise GaoListingSourceError(f"{_LABEL} does not name {scope.url} as its canonical URL")
    entries = tuple(_entry(position, teaser) for position, teaser in enumerate(reader.teasers))
    if not entries:
        # An empty page is not an empty listing: nothing on it establishes that GAO listed nothing.
        raise GaoListingSourceError(f"{_LABEL} lists no teaser")
    last = _last_page_index(reader, page_index)
    if last > max_last_page_index:
        raise GaoListingSourceError(f"{_LABEL} pager runs past page index {max_last_page_index}")
    if expected_last_page_index is not None and last != expected_last_page_index:
        raise GaoListingMovedError(
            f"{_LABEL} pager changed shape: last page {last}, not {expected_last_page_index}; the listing moved"
        )
    if expected_page_size is not None and (
        len(entries) > expected_page_size or (page_index < last and len(entries) != expected_page_size)
    ):
        raise GaoListingMovedError(
            f"{_LABEL} {page_index} holds {len(entries)} teasers where the first page held {expected_page_size}"
        )
    return GaoListingPage(scope, page_index, last, entries)


@dataclass(frozen=True, slots=True)
class GaoListingBudget:
    """Bounds for one page's capture; the total Zyte spend is the transport's ``ZyteBudget``."""

    max_page_bytes: int = DEFAULT_MAX_PAGE_BYTES
    timeout_seconds: float = 180.0
    min_request_interval_seconds: float = CRAWL_DELAY_SECONDS
    max_last_page_index: int = DEFAULT_MAX_LAST_PAGE_INDEX

    def __post_init__(self) -> None:
        check_byte_bound(self.max_page_bytes, "max_page_bytes", MAX_PAGE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)
        check_byte_bound(self.max_last_page_index, "max_last_page_index", 10_000)


class GaoListingAcquirer(SourceAcquirer):
    """One page per operation, one attempt each, paced; the transport is Zyte's, injected by the caller."""

    def __init__(
        self,
        *,
        budget: GaoListingBudget,
        transport: httpx.BaseTransport,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, GaoListingBudget):
            raise TypeError("budget must be a GaoListingBudget")
        self.budget = budget
        super().__init__(
            max_requests=1,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-gao-listing/1.0",
            label="GAO listing",
            error_type=GaoListingSourceError,
            context_key="gao_listing_acquisition",
            transport=transport,
            clock=clock,
        )

    def acquire_page(
        self,
        scope: GaoListingScope,
        page_index: int,
        *,
        expected_last_page_index: int | None = None,
        expected_page_size: int | None = None,
    ) -> tuple[GaoListingPage, CapturedBodyResponse]:
        url = scope.page_url(page_index)

        def parse(response: CapturedBodyResponse, limit: int) -> GaoListingPage:
            if response.status_code != 200:
                raise GaoListingSourceError(f"GAO listing answered HTTP {response.status_code}")
            return parse_listing_page(
                response.body,
                scope=scope,
                page_index=page_index,
                max_bytes=limit,
                max_last_page_index=self.budget.max_last_page_index,
                expected_last_page_index=expected_last_page_index,
                expected_page_size=expected_page_size,
            )

        return self.capture_validated(
            url,
            media_types=("text/html",),
            parse=parse,
            max_bytes=self.budget.max_page_bytes,
            unavailable=GaoListingUnavailableError,
            context={"operation": "listing-page", "scope": scope.key, "page_index": page_index, "url": url},
        )


@dataclass
class _Progress:
    last: int | None = None
    size: int | None = None
    rows: dict[int, dict] = field(default_factory=dict)
    #: Times the scope's listing moved and it was restarted from page 0.
    restarts: int = 0
    #: The first page not yet known to be retained; pages are retained in order, so it only moves forward.
    cursor: int = 0

    def add(self, row: dict) -> None:
        last, index = row["last_page_index"], row["page_index"]
        if self.last is not None and last != self.last:
            raise GaoListingSourceError(f"receipts disagree on scope {row['scope']}'s last page")
        self.last = last
        if index == 0:
            self.size = row["entries"]
        self.rows[index] = row

    def next_page(self) -> int | None:
        while self.cursor in self.rows:
            self.cursor += 1
        if self.last is None:
            return self.cursor if self.cursor == 0 else None
        return self.cursor if self.cursor <= self.last else None

    @property
    def stopped(self) -> bool:
        """Moved more often than a restart allows: walk it no more until someone looks at it."""
        return self.restarts > MAX_SCOPE_RESTARTS


def _read_receipts(receipts: Path) -> tuple[dict[str, _Progress], datetime | None]:
    """Each scope's retained pages, a later row for a page superseding an earlier one, and the last contact.

    A scope a walk was asked for is present even before any of its pages is retained, so it reads as unfinished.
    A ``moved`` row drops the scope's pages so far and counts a restart.
    """
    progress: dict[str, _Progress] = {}
    contact: datetime | None = None
    if not receipts.exists():
        return progress, None
    for line in receipts.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        stamp = row.get("observed_at") or row.get("attempted_at")
        if stamp:
            instant = datetime.fromisoformat(stamp)
            contact = instant if contact is None else max(contact, instant)
        if row.get("kind") == "started":
            for key in row.get("scopes", ()):
                progress.setdefault(key, _Progress())
        elif row.get("kind") == "page":
            progress.setdefault(row["scope"], _Progress()).add(row)
        elif row.get("kind") == "moved":
            progress[row["scope"]] = _Progress(restarts=progress.get(row["scope"], _Progress()).restarts + 1)
    return progress, contact


def _iso(instant: datetime) -> str:
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class _Walk:
    """What the workers of one walk share, read and written only under ``lock``."""

    lock: threading.Lock
    halt: threading.Event
    queue: deque[GaoListingScope]
    #: The receipts' last recorded contact: every worker's first request waits out the spacing from it.
    contact: datetime | None
    begun: int = 0
    failed: int = 0
    consecutive_failures: int = 0
    pause_until: datetime | None = None
    stop: str | None = None


def walk_listing(
    scopes: Sequence[GaoListingScope],
    *,
    acquirers: Callable[[], GaoListingAcquirer],
    store: Path,
    receipts: Path,
    zyte_budget: ZyteBudget,
    proxy_record: Callable[[str], ZyteProxyRecord | None] = lambda _url: None,
    credential: str = "",
    concurrency: int = 1,
    spacing_seconds: float = CRAWL_DELAY_SECONDS,
    failure_backoff_seconds: float = CRAWL_DELAY_SECONDS,
    max_consecutive_failures: int = 1,
    clock: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Walk each scope's pages in order, resuming from ``receipts``; 0 when done or stopped at budget, 1 after a failure.

    Every page's exact bytes go to ``store`` and one row to ``receipts`` (appended). A retained page is never
    fetched again, and a scope named twice is walked once. Up to ``concurrency`` workers (no more than the scopes,
    at most :data:`MAX_CONCURRENCY`) each take whole scopes in turn with their own acquirer from ``acquirers``, so a
    scope is still read page by page against its first page. A failure is recorded and stops its scope, which the
    next run retries; the other scopes' pages are kept. Each failure pauses every worker for
    ``failure_backoff_seconds``, doubling with each failure in a row up to :data:`MAX_BACKOFF_SECONDS`, and
    ``max_consecutive_failures`` in a row stop the walk. A listing that moves mid-scope writes a ``moved`` row and
    restarts the scope from page 0, once; moving again stops it, named, for this and every later run. The Zyte
    budget is an exact ceiling: a request is counted before it starts. Each worker spaces its own request starts by
    ``spacing_seconds``, its first from the last contact the receipts record, so stopping and resuming never shortens
    the spacing; this is the only pacing, so a caller's acquirers carry none. The default, one worker 420 seconds
    apart stopping at the first failure, is the site's stated crawl delay. On an interrupt the workers are stopped
    and joined and a ``stopped`` row is written before it propagates.
    """
    from rulespec_artifacts import LocalBlobWriter

    from spicy_docs.reading.refusals import retain_refused_response
    from spicy_docs.transport.credentials import scrub_credential

    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"concurrency must be an integer from 1 to {MAX_CONCURRENCY}")
    if (
        isinstance(max_consecutive_failures, bool)
        or not isinstance(max_consecutive_failures, int)
        or max_consecutive_failures < 1
    ):
        raise ValueError("max_consecutive_failures must be a positive integer")
    check_timing(1, spacing_seconds)
    check_timing(1, failure_backoff_seconds)
    scopes = list(dict.fromkeys(scopes))
    progress, contact = _read_receipts(receipts)
    writer = LocalBlobWriter(store)
    run_id = str(uuid4())
    spent_before = zyte_budget.spent
    shared = _Walk(threading.Lock(), threading.Event(), deque(scopes), contact)
    pause = sleep if sleep is not None else shared.halt.wait
    with receipts.open("a", encoding="utf-8") as sink:

        def emit(kind: str, **value: object) -> None:
            """Append one row; callers hold ``shared.lock``, so rows from different workers never interleave."""
            sink.write(
                scrub_credential(json.dumps({"kind": kind, "run_id": run_id, **value}, ensure_ascii=False), credential)
                + "\n"
            )
            sink.flush()

        def begin() -> datetime | None:
            """Reserve one request under the budget, or stop the walk; returns the pause to wait out, if any."""
            with shared.lock:
                if shared.stop is None and spent_before + shared.begun >= zyte_budget.max_requests:
                    shared.stop = "Zyte request budget reached; run again to resume"
                if shared.stop is not None:
                    raise _Stopped
                shared.begun += 1
                return shared.pause_until

        def refusal(
            scope: GaoListingScope, page_index: int, attempted: datetime, error: Exception, max_bytes: int
        ) -> dict:
            detail: dict[str, object] = {
                "scope": scope.key,
                "page_index": page_index,
                "attempted_at": _iso(attempted),
                "error_type": type(error).__name__,
                # Scrub before truncating, or a credential's prefix could survive.
                "error": scrub_credential(str(error), credential)[:1000],
                "zyte_requests": zyte_budget.spent,
            }
            refused = retain_refused_response(error, store=store, max_bytes=max_bytes, credential=credential)
            if refused is not None:
                detail["refused_evidence"] = refused
            return detail

        def failed(detail: dict) -> None:
            """Record a failure; the caller holds the lock."""
            emit("failed", **detail)
            shared.failed += 1
            shared.consecutive_failures += 1
            backoff = min(failure_backoff_seconds * 2 ** (shared.consecutive_failures - 1), MAX_BACKOFF_SECONDS)
            shared.pause_until = clock() + timedelta(seconds=backoff)
            if shared.consecutive_failures >= max_consecutive_failures:
                shared.stop = f"{shared.consecutive_failures} consecutive failures; run again to retry"

        def walk_scope(acquirer: GaoListingAcquirer, scope: GaoListingScope, last: datetime | None) -> datetime | None:
            """One scope, page after page; returns this worker's last request start."""
            with shared.lock:
                state = progress.setdefault(scope.key, _Progress())
            if state.stopped:
                return last
            while (page_index := state.next_page()) is not None:
                until = begin()
                waits = [spacing_seconds - (clock() - last).total_seconds()] if last is not None else []
                if until is not None:
                    waits.append((until - clock()).total_seconds())
                if (wait := max(waits, default=0)) > 0:
                    pause(wait)
                    if shared.halt.is_set():
                        raise _Stopped
                last = clock()
                try:
                    page, capture = acquirer.acquire_page(
                        scope, page_index, expected_last_page_index=state.last, expected_page_size=state.size
                    )
                    with shared.lock:
                        stored = writer.put(
                            [capture.body], max_bytes=acquirer.budget.max_page_bytes, expected_digest=capture.sha256
                        )
                except Exception as error:  # noqa: BLE001 - recorded with its evidence, then retried on resume
                    with shared.lock:
                        detail = refusal(scope, page_index, last, error, acquirer.budget.max_page_bytes)
                        if isinstance(error, GaoListingMovedError):
                            # Every move is a ``moved`` row, so a later run counts it too; past the allowance the
                            # scope stops here and in every later run, named, until someone looks at it.
                            emit("moved", **detail)
                            state = progress[scope.key] = _Progress(restarts=state.restarts + 1)
                            if not state.stopped:
                                continue
                        failed(detail)
                    return last
                record = proxy_record(capture.requested_url)
                row = {
                    "scope": scope.key,
                    "page_index": page_index,
                    "last_page_index": page.last_page_index,
                    "entries": len(page.entries),
                    "request_url": capture.requested_url,
                    "resolved_url": capture.resolved_url,
                    "status": capture.status_code,
                    "content_type": capture.content_type,
                    "observed_at": capture.observed_at,
                    "bytes": capture.byte_size,
                    "sha256": capture.sha256,
                    "blob_path": stored.object_key,
                    "proxied_client": None if record is None else record.proxied_client,
                    "proxy_mode": None if record is None else record.mode,
                    "zyte_request_id": None if record is None else record.zyte_request_id,
                }
                with shared.lock:
                    emit("page", **row)
                    state.add({**row, "kind": "page"})
                    shared.consecutive_failures = 0
            return last

        def worker() -> None:
            try:
                with acquirers() as acquirer:
                    last = shared.contact
                    while True:
                        with shared.lock:
                            if shared.stop is not None or not shared.queue:
                                return
                            scope = shared.queue.popleft()
                        last = walk_scope(acquirer, scope, last)
            except _Stopped:
                return
            except Exception as error:  # noqa: BLE001 - a worker that cannot run stops the walk, recorded
                with shared.lock:
                    shared.failed += 1
                    shared.stop = f"a worker could not run: {type(error).__name__}"
                    emit(
                        "failed", error_type=type(error).__name__, error=scrub_credential(str(error), credential)[:1000]
                    )

        def unfinished() -> list[str]:
            return [scope.key for scope in scopes if progress.get(scope.key, _Progress()).next_page() is not None]

        with shared.lock:
            emit(
                "started",
                scopes=[scope.key for scope in scopes],
                max_zyte_requests=zyte_budget.max_requests,
                spacing_seconds=spacing_seconds,
                concurrency=concurrency,
            )
        workers = [
            threading.Thread(target=worker, name=f"gao-listing-{index}")
            for index in range(min(concurrency, len(scopes)))
        ]
        try:
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join()
        except BaseException:
            with shared.lock:
                shared.stop = "interrupted; run again to resume" + (f" (after: {shared.stop})" if shared.stop else "")
            shared.halt.set()
            for thread in workers:
                if thread.is_alive():
                    thread.join()
            with shared.lock:
                emit("stopped", reason=shared.stop, unfinished=unfinished(), zyte_requests=zyte_budget.spent)
            raise
        left = unfinished()
        with shared.lock:
            if not left:
                emit("complete", scopes=[scope.key for scope in scopes], zyte_requests=zyte_budget.spent)
            else:
                moved = [key for key in left if progress.get(key, _Progress()).stopped]
                reason = shared.stop or "a scope stopped at a failure; run again to retry it"
                if moved:
                    reason = f"{reason}; listing moved while read, stopped until checked: {', '.join(moved)}"
                emit("stopped", reason=reason, unfinished=left, zyte_requests=zyte_budget.spent)
    return 1 if shared.failed or any(progress.get(key, _Progress()).stopped for key in left) else 0


class _Stopped(Exception):
    """The walk has stopped; a worker starts no further request."""


@dataclass(frozen=True, slots=True)
class GaoListedProduct:
    """One product, once, with every topic heading it sat under and every scope that listed it."""

    product_id: str
    product_number: str
    label: str
    heading: str
    published: str | None
    released: str | None
    topics: tuple[str, ...]
    scopes: tuple[str, ...]

    @property
    def title(self) -> str:
        """GAO's title for the product, ``label: heading``, as its product page and feed spell it."""
        return f"{self.label}: {self.heading}"


@dataclass(frozen=True, slots=True)
class GaoListedDecision:
    """One B-numbered legal decision's page, its numbers split; outside the product listing.

    Keyed on its page, not its number: 2019-2021 give one B-number two pages (``b-331093`` and ``b-331093-0``),
    released months apart, and B-333110's second is an update with its own heading.
    """

    product_number: str
    decision_numbers: tuple[str, ...]
    link: str
    label: str
    heading: str
    published: str | None
    released: str | None
    topics: tuple[str, ...]
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GaoListedOther:
    """One page listed with no product or B-number, by its link: a docket-numbered Contract Appeals Board decision,
    a ``P`` number, or no number at all (an Antideficiency Act report, forum materials); outside the products."""

    product_number: str | None
    link: str
    label: str
    heading: str
    published: str | None
    released: str | None
    topics: tuple[str, ...]
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetainedListingPage:
    page: GaoListingPage
    capture: CapturedBodyResponse
    blob_path: str
    zyte_request_id: str | None


@dataclass(frozen=True, slots=True)
class GaoListingRun:
    """The verified pages of every complete scope, and the products and decisions they list."""

    pages: tuple[RetainedListingPage, ...]
    products: tuple[GaoListedProduct, ...]
    decisions: tuple[GaoListedDecision, ...]
    others: tuple[GaoListedOther, ...]
    complete_scopes: tuple[str, ...]
    incomplete_scopes: tuple[str, ...]


def collect_listing(
    pages: Iterable[GaoListingPage],
) -> tuple[tuple[GaoListedProduct, ...], tuple[GaoListedDecision, ...], tuple[GaoListedOther, ...]]:
    """Each product once by its id, each decision and other page once by its page, in first-listed order.

    One listed twice with differing fields refuses. A product's link is not among them: 2020-2023 link one product
    by its prerelease path in one place and its page in another. A product listed on a suffixed twin page too
    (``gao-16-75sp`` and ``gao-16-75sp-0``) is one product, on the base page, when every other field agrees; a twin
    that differs (``gao-14-280r-0``, a VA major-rule report beside Defense's ``gao-14-280r``) is its own product.
    """
    found: dict[tuple[str, str], tuple[GaoListingEntry, list[str], list[str]]] = {}
    for page in pages:
        for entry in page.entries:
            key = ("product", entry.product_id) if entry.product_id else ("page", unquote(entry.link))
            held = found.setdefault(key, (entry, [], []))
            if _fixed(held[0]) != _fixed(entry):
                raise GaoListingSourceError(
                    f"GAO listing states {entry.product_number or entry.link} with differing fields"
                )
            for values, value in ((held[1], entry.topic), (held[2], page.scope.key)):
                if value not in values:
                    values.append(value)
    for key in [key for key in found if key[0] == "product"]:
        suffix = _TRAILING_DUPLICATE_PATH.search(key[1])
        base = ("product", key[1][: suffix.start()]) if suffix else None
        if base in found and _same_product(found[base][0], found[key][0]):
            _, topics, scopes = found.pop(key)
            for held, values in ((found[base][1], topics), (found[base][2], scopes)):
                held.extend(value for value in values if value not in held)
    products, decisions, others = [], [], []
    for entry, topics, scopes in found.values():
        seen = (entry.published, entry.released, tuple(topics), tuple(scopes))
        if entry.product_id is not None:
            products.append(
                GaoListedProduct(entry.product_id, entry.product_number or "", entry.label, entry.heading, *seen)
            )
        elif entry.decision_numbers:
            decisions.append(
                GaoListedDecision(
                    entry.product_number or "", entry.decision_numbers, entry.link, entry.label, entry.heading, *seen
                )
            )
        else:
            others.append(GaoListedOther(entry.product_number, entry.link, entry.label, entry.heading, *seen))
    return tuple(products), tuple(decisions), tuple(others)


def _same_product(base: GaoListingEntry, twin: GaoListingEntry) -> bool:
    """A suffixed twin states its base page's product: every fixed field but the page agrees."""
    return _fixed(base)[1:] == _fixed(twin)[1:]


def _fixed(entry: GaoListingEntry) -> tuple:
    """What must agree wherever GAO lists the same teaser; its topic, position and a product's link may differ."""
    return (
        entry.product_id,
        entry.product_number,
        None if entry.product_id else entry.link,
        entry.decision_numbers,
        entry.label,
        entry.heading,
        entry.published,
        entry.released,
    )


def read_listing_run(
    receipts: Path,
    store: Path,
    *,
    max_page_bytes: int = MAX_PAGE_BYTES,
    max_last_page_index: int = DEFAULT_MAX_LAST_PAGE_INDEX,
) -> GaoListingRun:
    """Re-read a walk's retained pages: each digest re-checked, each page re-parsed against its scope's first page.

    Only a scope whose every page is retained counts; the others are named in ``incomplete_scopes`` and read
    nothing. Bytes come from ``store`` and must equal what ``receipts`` recorded.
    """
    from rulespec_artifacts import LocalBlobSource

    progress, _ = _read_receipts(receipts)
    source = LocalBlobSource(store)
    pages: list[RetainedListingPage] = []
    complete, incomplete = [], []
    for key, state in progress.items():
        last = state.last
        if state.next_page() is not None or last is None:  # a scope with no page yet has no last page either
            incomplete.append(key)
            continue
        scope = GaoListingScope.parse(key)
        for index in range(last + 1):
            row = state.rows[index]
            with source.open(row["sha256"]) as stream:
                body = stream.read(max_page_bytes + 1)
            capture = CapturedBodyResponse(
                requested_url=row["request_url"],
                resolved_url=row["resolved_url"],
                status_code=row["status"],
                content_type=row["content_type"],
                observed_at=row["observed_at"],
                body=body,
            )
            if capture.sha256 != row["sha256"] or capture.byte_size != row["bytes"]:
                raise GaoListingSourceError(f"retained page {key}/{index} differs from its receipt")
            if capture.requested_url != scope.page_url(index):
                raise GaoListingSourceError(f"retained page {key}/{index} was requested at another URL")
            page = parse_listing_page(
                body,
                scope=scope,
                page_index=index,
                max_bytes=max_page_bytes,
                max_last_page_index=max_last_page_index,
                expected_last_page_index=last,
                expected_page_size=state.size,
            )
            pages.append(RetainedListingPage(page, capture, row["blob_path"], row.get("zyte_request_id")))
        complete.append(key)
    products, decisions, others = collect_listing(retained.page for retained in pages)
    return GaoListingRun(tuple(pages), products, decisions, others, tuple(complete), tuple(incomplete))


def _walk(args: argparse.Namespace) -> int:
    from spicy_docs.sources.zyte import HTTP_RESPONSE_BODY, ZyteHttpFetcher, require_zyte_token_from_environment
    from spicy_docs.transport.credentials import scrub_credential
    from spicy_docs.transport.zyte import ZyteBudget, ZyteTransport

    token = ""
    try:
        scopes = [GaoListingScope.parse(value) for value in args.scope]
        # The walk spaces requests itself, from the receipts' last contact across runs; the acquirer adds none.
        budget = GaoListingBudget(
            max_page_bytes=args.max_page_bytes, timeout_seconds=args.timeout_seconds, min_request_interval_seconds=0
        )
        token = require_zyte_token_from_environment()
        zyte_budget = ZyteBudget(args.max_zyte_requests)
        transport = ZyteTransport(
            ZyteHttpFetcher(token=token),
            max_bytes=budget.max_page_bytes,
            timeout_seconds=budget.timeout_seconds,
            mode=HTTP_RESPONSE_BODY,
            budget=zyte_budget,
        )
        return walk_listing(
            scopes,
            acquirers=lambda: GaoListingAcquirer(budget=budget, transport=transport),
            store=args.store,
            receipts=args.receipts,
            zyte_budget=zyte_budget,
            proxy_record=transport.record_for,
            credential=token,
            concurrency=args.concurrency,
            spacing_seconds=args.delay_seconds,
            failure_backoff_seconds=args.failure_backoff_seconds,
            max_consecutive_failures=args.max_consecutive_failures,
        )
    except (ValueError, OSError) as error:
        print(scrub_credential(str(error), token), file=sys.stderr)
        return 1


def _read(args: argparse.Namespace) -> int:
    run = read_listing_run(args.receipts, args.store)
    with args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout) as out:
        for item in (*run.products, *run.decisions, *run.others):
            kind = {GaoListedProduct: "product", GaoListedDecision: "decision"}.get(type(item), "other")
            value = {name: getattr(item, name) for name in item.__dataclass_fields__}
            out.write(json.dumps({"kind": kind, **value}, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "pages": len(run.pages),
                "products": len(run.products),
                "decisions": len(run.decisions),
                "others": len(run.others),
                "complete_scopes": run.complete_scopes,
                "incomplete_scopes": run.incomplete_scopes,
            }
        ),
        file=sys.stderr,
    )
    return 0


def parser() -> argparse.ArgumentParser:
    """The command's arguments; its defaults are the polite walk, one worker 420 seconds apart."""
    parser = argparse.ArgumentParser(description="Walk or read GAO's Month in Review and Annual Index pages")
    commands = parser.add_subparsers(dest="command", required=True)
    walk = commands.add_parser("walk", help="Capture listing pages through Zyte, resuming from the receipts")
    walk.add_argument("--scope", action="append", required=True, help="YYYY for a year's index, YYYY-MM for a month")
    walk.add_argument("--store", type=Path, required=True, help="Content-addressed page store")
    walk.add_argument("--receipts", type=Path, required=True, help="JSONL receipts, appended; the resume state")
    walk.add_argument("--max-zyte-requests", type=int, required=True, help="Hard ceiling on Zyte calls this run")
    walk.add_argument(
        "--delay-seconds", type=float, default=CRAWL_DELAY_SECONDS, help="Seconds between one worker's requests"
    )
    walk.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=f"Workers, each walking whole scopes in turn (at most {MAX_CONCURRENCY})",
    )
    walk.add_argument(
        "--failure-backoff-seconds",
        type=float,
        default=CRAWL_DELAY_SECONDS,
        help="Pause every worker this long after a failure, doubling for each failure in a row",
    )
    walk.add_argument(
        "--max-consecutive-failures", type=int, default=1, help="Failures in a row that stop the whole walk"
    )
    walk.add_argument("--timeout-seconds", type=float, default=180.0)
    walk.add_argument("--max-page-bytes", type=int, default=DEFAULT_MAX_PAGE_BYTES)
    read = commands.add_parser("read", help="Verify retained pages offline and print products and decisions as JSONL")
    read.add_argument("--store", type=Path, required=True)
    read.add_argument("--receipts", type=Path, required=True)
    read.add_argument("--output", type=Path, help="Create a new JSONL file; defaults to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return _walk(args) if args.command == "walk" else _read(args)


__all__ = [
    "CRAWL_DELAY_SECONDS",
    "DEFAULT_MAX_LAST_PAGE_INDEX",
    "DEFAULT_MAX_PAGE_BYTES",
    "LISTING_URL",
    "MAJOR_RULE_REPORT",
    "MAX_BACKOFF_SECONDS",
    "MAX_CONCURRENCY",
    "MAX_PAGE_BYTES",
    "MAX_SCOPE_RESTARTS",
    "GaoListedDecision",
    "GaoListedOther",
    "GaoListedProduct",
    "GaoListingAcquirer",
    "GaoListingBudget",
    "GaoListingEntry",
    "GaoListingMovedError",
    "GaoListingPage",
    "GaoListingRun",
    "GaoListingScope",
    "GaoListingSourceError",
    "GaoListingUnavailableError",
    "RetainedListingPage",
    "collect_listing",
    "parse_listing_page",
    "parser",
    "read_listing_run",
    "walk_listing",
]


if __name__ == "__main__":
    raise SystemExit(main())
