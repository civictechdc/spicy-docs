"""OLRC per-Congress classification tables: which Code sections each new public law touched.

The Office of the Law Revision Counsel publishes, for the current Congress,
one "Table of Classifications for Public Laws" per session in two orders --
by public law (``tbl{congress}pl_{session}.htm``) and by Code citation
(``tbl{congress}cd_{session}.htm``) -- linked from one index page,
``classification/tables.shtml``. Table III (``spicy_docs.sources.uscode``) is
the historical act-section view of the same facts, one page per act; this
table is the per-Congress view, one page per session, and is what a rollup
reads to say which sections a *new* law touched before Table III catches up.

Everything here was measured on 2026-09-19 against the 119th Congress, 2nd
session table (``corpora/supply-2026-09-02/receipts/olrc-classification-2026-09-19/``):

* **The rows are a fixed-width ``<PRE>`` block, not an HTML table.** The
  page has exactly one ``<PRE>``; its header line names six columns (``Title``,
  ``Section``, ``Description``, ``Pub. L.``, ``Sec.``, ``NNN Stat.``) and the
  column offsets are read from that header line, never assumed: 583 of 583
  data lines sliced at those offsets on 2026-09-19 with none left over.
* **The page states its own identity in its caption**: ``119th Congress, 2nd
  Session`` and the laws it covers, ``(Public Law 119-70 and Public Laws
  119-74 through 119-110)``, plus a "Prepared by ... September 16, 2026"
  line. :func:`parse_classification_table` proves the stated Congress and
  session against the request before any row is taken, and every row's own
  law number must carry that Congress too.
* **Column 3 is the publisher's action vocabulary, kept verbatim.** The page's
  legend says a blank entry or a bare ``nt`` means the section or note is
  amended; ``new``, ``nt new``, ``nt [tbl]``, ``prec``, ``repealed``,
  ``gen amd``, ``omitted``, ``fr``, ``to``, ``ed chg`` are the others. The
  blank is kept as ``None`` and the legend is the reader's, not this module's.
* **The Statutes at Large column is two facts.** Most rows link the page
  through ``/statviewer.htm?volume=140&page=3`` (573 of 583); ten rows print a
  page span such as ``637, 638`` or ``762-764`` with no link. The printed
  text is kept whole and the link's volume and page are kept beside it.
* **The two orders hold the same rows.** The public-law-order and Code-order
  tables for one session are the same 583-row multiset; one row (``20 1411
  nt new 119-75`` at 140 Stat. 297) appears twice in both, so a row's
  identity is its position in the page (``seq``), not its content.
* **The index links the current Congress only**: four ``tbl`` links (two
  sessions in two orders) plus the editorial-change tables. Its ``<title>``
  is ``UNITED STATES CODE CLASSIFICATION TABLES`` and that is what proves the
  page is the index rather than a challenge page or a redirect target.

The legislative data map's ``law→classification`` edge only checked that the
table body contains the string ``119-1`` -- true of ``119-100`` through
``119-110`` as well, so it was a formatting assertion, not a measurement of
the shape. This module is the measurement.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from spicy_docs.sources.uscode import (
    DEFAULT_MAX_ENTRIES_PER_PAGE,
    DEFAULT_MAX_PAGE_BYTES,
    OLRC,
    UsCodeSourceError,
    _body,
    _count,
    _limit,
)

CLASSIFICATION_INDEX_URL = f"{OLRC}/classification/tables.shtml"
INDEX_TITLE = "UNITED STATES CODE CLASSIFICATION TABLES"

type TableOrder = Literal["public-law", "code"]

#: The publisher's own file-name grammar, read from the index's hrefs.
_ORDER_CODES: dict[TableOrder, str] = {"public-law": "pl", "code": "cd"}
_SESSION_CODES = {1: "1st", 2: "2nd"}
_TABLE_FILE = re.compile(r"tbl(?P<congress>[1-9][0-9]{0,2})(?P<order>pl|cd)_(?P<session>1st|2nd)\.htm")
_HREF = re.compile(r'href="([^"]+)"')
_TITLE = re.compile(r"<title>\s*(.*?)\s*</title>", re.DOTALL | re.IGNORECASE)
_CENTER = re.compile(r"<CENTER>(.*?)</CENTER>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_PRE = re.compile(r"<PRE[^>]*>(.*?)</PRE>", re.DOTALL | re.IGNORECASE)
_FONT = re.compile(r"</?FONT[^>]*>", re.IGNORECASE)
_CAPTION = re.compile(
    r"(?P<congress>[1-9][0-9]{0,2})(?:st|nd|rd|th) Congress, (?P<session>1st|2nd) Session\s*"
    r"\((?P<laws>Public Law[^)]*)\)"
)
_HEADINGS: dict[TableOrder, str] = {
    "public-law": "TABLE OF CLASSIFICATIONS FOR PUBLIC LAWS",
    "code": "TABLE OF SECTIONS AMENDED, ENACTED, OMITTED, REPEALED, OR TRANSFERRED",
}
_PREPARED = re.compile(
    r"Prepared by\s+Office of the Law Revision Counsel\s+U\.S\. House of Representatives\s+(?P<date>[^<]+?)\s*$"
)
_VOLUME_HEADER = re.compile(r"(?P<volume>[0-9]+) Stat\.")
_LAW_NUMBER = re.compile(r"(?P<congress>[1-9][0-9]{0,2})-(?P<number>[1-9][0-9]*)")
_STAT_LINK = re.compile(r'<a href="(?P<href>/statviewer\.htm\?[^"]*)">(?P<text>[^<]*)</a>', re.IGNORECASE)
_STATED_RANGE = re.compile(r"(?P<first>[1-9][0-9]{0,2}-[1-9][0-9]*)(?: through (?P<last>[1-9][0-9]{0,2}-[1-9][0-9]*))?")
_COLUMNS = ("Title", "Section", "Description", "Pub. L.", "Sec.")


def _session_code(session: object) -> str:
    if session not in _SESSION_CODES:
        raise UsCodeSourceError("session must be 1 or 2")
    return _SESSION_CODES[session]  # type: ignore[index]


def _congress(congress: object) -> int:
    if type(congress) is not int or not 1 <= congress <= 999:
        raise UsCodeSourceError("congress must be an integer from 1 to 999")
    return congress  # type: ignore[return-value]


def classification_table_file_name(congress: int, session: int, order: TableOrder = "public-law") -> str:
    """``tbl119pl_2nd.htm``: the grammar every ``tbl`` href on the index follows (four of four, 2026-09-19)."""
    if order not in _ORDER_CODES:
        raise UsCodeSourceError("order must be 'public-law' or 'code'")
    return f"tbl{_congress(congress)}{_ORDER_CODES[order]}_{_session_code(session)}.htm"


def classification_table_locator(congress: int, session: int, order: TableOrder = "public-law") -> str:
    return f"{OLRC}/classification/{classification_table_file_name(congress, session, order)}"


@dataclass(frozen=True, slots=True)
class ClassificationTableLink:
    """One session table the index links, as the index spells it."""

    congress: int
    session: int
    order: TableOrder
    href: str

    @property
    def url(self) -> str:
        return f"{OLRC}/classification/{self.href}"


@dataclass(frozen=True, slots=True)
class ClassificationIndex:
    """The index page's title and every session table it links, in page order."""

    source: Literal["classification-index"]
    title: str
    tables: tuple[ClassificationTableLink, ...]
    identity_basis: tuple[str, ...] = ("title:native",)


def parse_classification_index(body: bytes, *, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> ClassificationIndex:
    """Read ``tables.shtml``: prove its title, then list every ``tbl`` link it carries.

    A page with the right title and no table links is refused rather than read
    as "no tables exist": the index has linked four since it was first
    measured, and zero is the shape of a truncated or replaced page.
    """
    _limit(max_bytes)
    text = _text(_body(body, max_bytes, "classification index"), "classification index")
    title = _TITLE.search(text)
    stated = html.unescape(re.sub(r"\s+", " ", title[1])) if title else ""
    if stated != INDEX_TITLE:
        raise UsCodeSourceError("classification index does not state the expected title")
    tables: list[ClassificationTableLink] = []
    for href in _HREF.findall(text):
        match = _TABLE_FILE.fullmatch(href.rsplit("/", 1)[-1])
        if match is None:
            continue
        order: TableOrder = "public-law" if match["order"] == "pl" else "code"
        session = 1 if match["session"] == "1st" else 2
        tables.append(ClassificationTableLink(int(match["congress"]), session, order, href))
    if not tables:
        raise UsCodeSourceError("classification index links no session tables")
    return ClassificationIndex("classification-index", stated, tuple(tables))


@dataclass(frozen=True, slots=True)
class ClassificationRecord:
    """One line of the table: a Code place, what happened to it, and the law section that did it.

    ``description`` is column 3 verbatim and ``None`` where the page left it
    blank, which the page's own legend reads as "amended"; that reading is
    the consumer's. ``statutes_at_large_page`` is the printed column text --
    one page, or a span like ``637, 638`` -- and the two ``link_*`` fields are
    the ``statviewer`` link's own volume and page where the row carries one.
    """

    seq: int
    usc_title: str
    usc_section: str
    description: str | None
    law_number: str
    act_section: str | None
    statutes_at_large_page: str | None
    link_volume: str | None = None
    link_page: str | None = None


@dataclass(frozen=True, slots=True)
class ClassificationTable:
    """One session table, with the Congress, session, law range and currency the page states itself."""

    source: Literal["classification-table"]
    congress: int
    session: int
    order: TableOrder
    heading: str
    stated_laws: str
    stated_law_numbers: tuple[str, ...]
    statutes_at_large_volume: str | None
    prepared_date: str | None
    records: tuple[ClassificationRecord, ...]
    identity_basis: tuple[str, ...] = ("congress:native", "session:native")


def _text(data: bytes, label: str) -> str:
    if b"</html>" not in data[-4096:]:
        raise UsCodeSourceError(f"{label} is not closed by </html>; the publisher truncated it")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UsCodeSourceError(f"{label} is not the UTF-8 the publisher declares") from error


def _visible(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", _TAG.sub(" ", fragment))).strip()


def _stated_law_numbers(stated: str) -> tuple[str, ...]:
    """Expand ``Public Law 119-70 and Public Laws 119-74 through 119-110`` to every number it names."""
    numbers: list[str] = []
    for match in _STATED_RANGE.finditer(stated):
        first, last = match["first"], match["last"]
        if last is None:
            numbers.append(first)
            continue
        first_law, last_law = _LAW_NUMBER.fullmatch(first), _LAW_NUMBER.fullmatch(last)
        if first_law is None or last_law is None or first_law["congress"] != last_law["congress"]:
            raise UsCodeSourceError("classification table states a law range across two Congresses")
        congress = first_law["congress"]
        numbers.extend(f"{congress}-{n}" for n in range(int(first_law["number"]), int(last_law["number"]) + 1))
    return tuple(numbers)


def _offsets(header: str) -> tuple[dict[str, int], str | None]:
    offsets: dict[str, int] = {}
    for column in _COLUMNS:
        position = header.find(column)
        if position < 0:
            raise UsCodeSourceError(f"classification table header lacks the {column!r} column")
        offsets[column] = position
    volume = _VOLUME_HEADER.search(header)
    if volume is None:
        raise UsCodeSourceError("classification table header lacks the Statutes at Large column")
    offsets["Stat."] = volume.start()
    if list(offsets.values()) != sorted(offsets.values()):
        raise UsCodeSourceError("classification table header columns are out of order")
    return offsets, volume["volume"]


def _record(line: str, seq: int, offsets: dict[str, int], congress: int) -> ClassificationRecord:
    link_volume = link_page = None
    link = _STAT_LINK.search(line)
    if link is not None:
        query = parse_qs(urlsplit(link["href"]).query, keep_blank_values=True)
        link_volume = (query.get("volume") or [""])[0] or None
        link_page = (query.get("page") or [""])[0] or None
        line = line[: link.start()] + link["text"] + line[link.end() :]
    if "<" in line:
        raise UsCodeSourceError(f"classification table row {seq} carries markup other than a statviewer link")
    columns = ("Title", "Section", "Description", "Pub. L.", "Sec.", "Stat.")
    stops = [offsets[name] for name in columns] + [len(line)]
    cells = [html.unescape(line[stops[i] : stops[i + 1]]).strip() for i in range(len(columns))]
    title, section, description, law_number, act_section, page = cells
    law = _LAW_NUMBER.fullmatch(law_number)
    if law is None:
        raise UsCodeSourceError(f"classification table row {seq} states no public law number")
    if int(law["congress"]) != congress:
        raise UsCodeSourceError(f"classification table row {seq} names a law of another Congress")
    if not title or not section:
        raise UsCodeSourceError(f"classification table row {seq} lacks a Code title or section")
    return ClassificationRecord(
        seq=seq,
        usc_title=title,
        usc_section=section,
        description=description or None,
        law_number=law_number,
        act_section=act_section or None,
        statutes_at_large_page=page or None,
        link_volume=link_volume,
        link_page=link_page,
    )


def parse_classification_table(
    body: bytes,
    *,
    congress: int,
    session: int,
    order: TableOrder = "public-law",
    max_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    max_rows: int = DEFAULT_MAX_ENTRIES_PER_PAGE,
) -> ClassificationTable:
    """Read one session table, proving the Congress and session it states are the ones requested.

    The caption is proved before the ``<PRE>`` block is looked at, so a page
    for another session, an index page, or a challenge page served with
    status 200 is refused by name. Zero rows is likewise a refusal: every
    session table measured carries hundreds, and an empty block is the shape
    of a cut-off page, not of a session that classified nothing.
    """
    classification_table_file_name(congress, session, order)
    _limit(max_bytes)
    _count(max_rows, "max_rows")
    text = _text(_body(body, max_bytes, "classification table"), "classification table")
    captions = [_visible(fragment) for fragment in _CENTER.findall(text)]
    caption = next((c for c in captions if _HEADINGS[order] in c), None)
    if caption is None:
        raise UsCodeSourceError("classification table page states no table heading")
    stated = _CAPTION.search(caption)
    if stated is None:
        raise UsCodeSourceError("classification table page states no Congress and session")
    if (int(stated["congress"]), stated["session"]) != (congress, _session_code(session)):
        raise UsCodeSourceError("classification table page states another Congress or session than the request")
    prepared = next((m["date"] for c in captions if (m := _PREPARED.search(c)) is not None), None)
    blocks = _PRE.findall(text)
    if len(blocks) != 1:
        raise UsCodeSourceError("classification table page must carry exactly one <PRE> block")
    lines = [line.rstrip() for line in _FONT.sub("", blocks[0]).split("\n")]
    header_index = next((i for i, line in enumerate(lines) if "Title" in line and "Stat." in line), None)
    if header_index is None:
        raise UsCodeSourceError("classification table lacks its column header line")
    offsets, volume = _offsets(lines[header_index])
    records: list[ClassificationRecord] = []
    for line in lines[header_index + 1 :]:
        if not line.strip() or set(line.strip()) <= {"-", " "}:
            continue
        if len(records) >= max_rows:
            raise UsCodeSourceError("classification table states more rows than max_rows")
        records.append(_record(line, len(records), offsets, congress))
    if not records:
        raise UsCodeSourceError("classification table states no rows")
    return ClassificationTable(
        "classification-table",
        congress,
        session,
        order,
        _HEADINGS[order],
        stated["laws"],
        _stated_law_numbers(stated["laws"]),
        volume,
        prepared,
        tuple(records),
    )


__all__ = [
    "CLASSIFICATION_INDEX_URL",
    "INDEX_TITLE",
    "ClassificationIndex",
    "ClassificationRecord",
    "ClassificationTable",
    "ClassificationTableLink",
    "TableOrder",
    "classification_table_file_name",
    "classification_table_locator",
    "parse_classification_index",
    "parse_classification_table",
]
