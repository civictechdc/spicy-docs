"""Table III: per-act pages, the chain of acts they link, and the bare-fragment bulk member.

Absence is read from the chain, never from a page's bytes. Each served page
names the act before and after it, and those links skip exactly the acts the
table serves no page for. An act without a page answers ``200``, the first
16,134 or 16,209 bytes of the site template (the site menu opens at about
2.3 KB and the page's content at about 27 KB), and a dropped connection.
Session id aside, every such answer is a byte-exact prefix of a served page,
so a served page dropped between those two points reads the same. The
measurements are in
``~/Work/corpora/fork-execution-2026-09-21/table3-walk-2026-09-24/spicy-docs/``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Container, Generator, Iterator
from dataclasses import astuple, dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element

from spicy_docs.reading.xml import parse_xml
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member
from spicy_docs.sources.uscode.core import (
    _BULK_MEMBER,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ENTRIES_PER_PAGE,
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    ReleasePoint,
    UsCodeSource,
    UsCodeSourceError,
    _body,
    _comparable,
    _count,
    _digest,
    _limit,
    _visible,
    table3_file_name,
)

if TYPE_CHECKING:
    from spicy_docs.sources.uscode.acquisition import UsCodeAcquisition

# --------------------------------------------------------------------------- #
# Table III
# --------------------------------------------------------------------------- #

_TABLE3_COLUMNS = (
    "actsection",
    "statutesatlargepage",
    "unitedstatescodetitle",
    "unitedstatescodesection",
    "unitedstatescodestatus",
)
_TABLE3_CONTEXT = ("congress", "statutesatlargevolume", "textdate", "prioract", "act", "nextact")
#: Caption furniture, not part of a caption's value: the jump-to-index arrows
#: (``&uarr;``) and the act's scanned-PDF link, which renders as "(pdf)" inside
#: the very span that states the act key.
_TABLE3_NAVIGATION = ("table3congresses.htm", "table3statutesatlarge.htm", "table3years.htm", ".pdf")
_TABLE3_ROW_CLASS = re.compile(r"table3row_(?:odd|even)")
TABLE3_READER_VERSION = "table3-native-rows-v2"

_TABLE3_CURRENCY = re.compile(r"Table III Tool \[Current through (?P<release_point>[0-9]+-[0-9]+)")


@dataclass(frozen=True, slots=True)
class Table3Record:
    """One act section and the Code place it was classified to.

    ``usc_section`` is empty where the section was repealed, omitted or
    classified nowhere: the row exists and says so, and dropping it would turn
    "we know this went nowhere" into "we do not know".
    """

    act_section: str | None
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class Table3Page:
    """One act's Table III page, with the act key and currency the page states itself."""

    source: UsCodeSource
    key: str
    stated_key: str
    release_point: str | None
    congress: str | None
    statutes_at_large_volume: str | None
    act_date: str | None
    prior_act: str | None
    next_act: str | None
    records: tuple[Table3Record, ...]
    identity_basis: tuple[str, ...] = ("act-key:native",)


class _Table3Reader(HTMLParser):
    """Read the act caption and the flat classification rows."""

    def __init__(self, max_rows: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_rows = max_rows
        self.context: dict[str, str] = {}
        self.rows: list[dict[str, str]] = []
        self.row_links: list[list[str]] = []
        self._row: dict[str, str] | None = None
        self._links: list[str] = []
        self._cell: str | None = None
        self._span: str | None = None
        self._text: list[str] = []
        self._navigation = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "tr" and any(_TABLE3_ROW_CLASS.fullmatch(name) for name in classes):
            self._row = {}
            self._links = []
        elif tag == "td" and self._row is not None:
            found = [name for name in classes if name in _TABLE3_COLUMNS]
            self._cell = found[0] if found else None
            self._text = []
        elif tag == "span" and self._row is None:
            found = [name for name in classes if name in _TABLE3_CONTEXT]
            self._span = found[0] if found else None
            self._text = []
        elif tag == "a":
            href = values.get("href") or ""
            if self._cell is not None and href:
                self._links.append(href)
            if self._span is not None and href.endswith(_TABLE3_NAVIGATION):
                self._navigation = True

    def handle_data(self, data: str) -> None:
        if not self._navigation and (self._cell is not None or self._span is not None):
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        # Only the element that opened a collection closes it. Both a cell and a
        # caption span wrap an <a>, and clearing on every end tag would drop the
        # act key and every linked section number with it.
        if tag == "a":
            self._navigation = False
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row[self._cell] = _visible(self._text)
            self._cell = None
            self._text = []
        elif tag == "span" and self._span is not None:
            self.context.setdefault(self._span, _visible(self._text))
            self._span = None
            self._text = []
        elif tag == "tr" and self._row is not None:
            # Native row structure supplies identity; a missing act label must not
            # erase a stated Code reference (for example the retained 119-37 page).
            if any(self._row.values()) or self._links:
                if len(self.rows) >= self.max_rows:
                    raise UsCodeSourceError("Table III page states more rows than max_rows")
                self.rows.append(self._row)
                self.row_links.append(self._links)
            self._row = None
            self._text = []


def parse_table3_page(
    body: bytes, *, key: str, max_bytes: int = DEFAULT_MAX_PAGE_BYTES, max_rows: int = DEFAULT_MAX_ENTRIES_PER_PAGE
) -> Table3Page:
    """Read one act's Table III page, proving the act it states is the act requested.

    The bytes of an act the table serves no page for stop inside the site menu:
    they state no act and are not closed, so both checks refuse them, and a
    row count of zero is never read as "this act classified nothing".
    """
    table3_file_name(key)
    _limit(max_bytes)
    _count(max_rows, "max_rows")
    data = _body(body, max_bytes, "Table III page")
    if b"</html>" not in data[-4096:]:
        raise UsCodeSourceError("Table III page is not closed by </html>; the publisher truncated it")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UsCodeSourceError("Table III page is not the UTF-8 the publisher declares") from error
    reader = _Table3Reader(max_rows)
    reader.feed(text)
    reader.close()
    stated = reader.context.get("act")
    if not stated:
        raise UsCodeSourceError("Table III page states no act of its own")
    # The page spells a public law key with an en dash where the URL spells a
    # hyphen; the comparison tolerates that and the stated form is kept.
    if _comparable(stated) != _comparable(key):
        raise UsCodeSourceError("Table III page states another act than the request")
    currency = _TABLE3_CURRENCY.search(text)
    records = []
    for row, links in zip(reader.rows, reader.row_links, strict=True):
        volume = page = None
        for href in links:
            parsed = urlsplit(href)
            if parsed.path.endswith("/statviewer.htm"):
                query = parse_qs(parsed.query, keep_blank_values=True)
                volume = (query.get("volume") or [""])[0] or None
                page = (query.get("page") or [""])[0] or None
                break
        record = Table3Record(
            act_section=row.get("actsection") or None,
            statutes_at_large_volume=volume,
            statutes_at_large_page=page or row.get("statutesatlargepage") or None,
            usc_title=row.get("unitedstatescodetitle") or None,
            usc_section=row.get("unitedstatescodesection") or None,
            status=row.get("unitedstatescodestatus") or None,
        )
        # A row whose only content is a link to something other than the
        # Statutes viewer states no observation; publishing it would be an
        # all-NULL record with a position of its own.
        if any(value is not None for value in astuple(record)):
            records.append(record)
    return Table3Page(
        "table3-act",
        key,
        stated,
        currency["release_point"] if currency else None,
        reader.context.get("congress"),
        reader.context.get("statutesatlargevolume"),
        reader.context.get("textdate"),
        reader.context.get("prioract"),
        reader.context.get("nextact"),
        tuple(records),
    )


#: A public law as a key or a page states it: ``119-4``, or ``119–4`` with the page's en dash.
_PUBLIC_LAW = re.compile(r"(?P<congress>[1-9][0-9]{0,2})-(?P<number>[1-9][0-9]*)")


def _public_law(stated: str | None) -> tuple[int, int] | None:
    match = _PUBLIC_LAW.fullmatch(_comparable(stated or ""))
    return (int(match["congress"]), int(match["number"])) if match else None


def iter_table3_chain(
    acquire: Callable[[str], UsCodeAcquisition],
    start: str,
    *,
    max_acts: int,
    within: Container[str] | None = None,
) -> Generator[UsCodeAcquisition, None, str]:
    """Walk one Congress's chain: request ``start``, then each act a page names next, yielding every acquisition.

    ``acquire`` is :meth:`~spicy_docs.sources.uscode.acquisition.UsCodeAcquirer.acquire_table3_act`
    or a wrapper around it. The acts a link passes over are the ones the table
    serves no page for: on 2026-09-24 ``119-12`` named ``119-18`` next, and
    ``119-13`` to ``119-17`` each answered only the site template.

    The walk requests nothing more, and returns why, after ``max_acts`` pages or
    at a page that names no next public law, or names one in another Congress,
    one that does not follow the act it is on, one outside ``within`` (the
    caller's own bound, such as the public laws it lists, spelled ``119-4``;
    pass a set, since membership is tested once per act), or one past the
    release point the page states itself current through, in that order. The
    last served page of 2026-09-24, ``119-73`` at ``119-73``, named ``119-74``,
    which answered only the template.

    A named act that fails raises from ``acquire`` as it would alone, retried
    and refused the same way. The walk ends there, since only that page names
    the next act, and nothing it received becomes an absence. ``start`` is
    requested like any other act, so it must be one the table serves: a
    Congress whose lowest act has no page cannot start from it. The previous
    Congress's walk should end at a page naming an act in this one, which could
    seed it; that is inferred from ``119-1`` naming ``118-273`` as its prior
    act, not yet observed.

    A page's stop rules run inside the ``next()`` that follows it, so that
    call can end the walk without a request. Spend a per-run cap or check a
    deadline inside ``acquire``, once per request, not before each ``next()``:
    a count taken there also spends one at every natural end and reports the
    cap instead of the chain's end. ``acquire`` stops the walk by raising.
    """
    _count(max_acts, "max_acts")
    current = _public_law(start)
    if current is None:
        raise UsCodeSourceError("Table III chain starts at a public-law key such as 119-4")
    key = f"{current[0]}-{current[1]}"
    for _ in range(max_acts):
        acquired = acquire(key)
        yield acquired
        page = acquired.result
        following = _public_law(page.next_act)
        if following is None:
            return "names no next public law"
        if following[0] != current[0]:
            return "names an act in another Congress"
        if following[1] <= current[1]:
            return "names an act that does not follow it"
        key = f"{following[0]}-{following[1]}"
        if within is not None and key not in within:
            return "names an act outside the caller's bound"
        stated = _public_law(page.release_point)
        if stated is not None and following > stated:
            return "names an act past the release point it states"
        current = following
    return "reached max_acts"


_ACT_OPEN = b"<act "
_ACT_CLOSE = b"</act>"


#: Every name an ``<act>`` and a ``<record>`` state, counted over all 48,973
#: acts and 317,590 records of ``fulldump@119-73.xml``. Each has a field below,
#: so nothing the file states is discarded; a name absent from these sets
#: refuses, because a vocabulary this reader has not seen is a reason to stop
#: rather than to drop a fact in silence.
_ACT_ATTRIBUTES = frozenset(
    {
        "id",
        "search-key",
        "congress",
        "date",
        "statutes-at-large-volume",
        "sequence",
        "insertion",
        "format",
        "print-in-supplement",
        "include-in-online-release-point",
    }
)
_ACT_CHILDREN = frozenset({"num", "public-law", "record"})
_RECORD_ATTRIBUTES = frozenset({"id", "sequence", "usckey", "print-in-supplement"})
_RECORD_CHILDREN = frozenset(
    {
        "act-section",
        "statutes-at-large-page",
        "united-states-code-status",
        "united-states-code-title",
        "united-states-code-section",
    }
)


@dataclass(frozen=True, slots=True)
class Table3ActRecord:
    """One classification record: an act section and where it landed, or why it did not.

    ``usc_status`` carries what a pre-codification act states instead of a title
    and section (``R.S. Sec 28``); 81,283 records state one. 15,434 records
    state no ``act-section`` at all, which is the file speaking and is kept.
    ``record_id`` and ``usc_key`` are stated on every record and are *empty* on
    one each -- one record of the Homeland Security Act states no ``id`` and one
    of the Families First Coronavirus Response Act states no ``usckey`` -- so
    they are optional here rather than refusing two real publisher records.
    """

    record_id: str | None
    sequence: str
    usc_key: str | None
    act_section: str | None
    statutes_at_large_page: str | None
    usc_title: str | None
    usc_section: str | None
    usc_status: str | None
    print_in_supplement: str | None = None


@dataclass(frozen=True, slots=True)
class Table3Act:
    """One ``<act>`` of the bulk file, with every attribute and child it states.

    ``public_law`` is the session's public-law number for a pre-1957 chapter
    act: chapter 3 of January 22, 1902 was Public Law 3. 10,406 acts state one.
    """

    act_id: str
    search_key: str
    num: str
    congress: str
    date: str
    statutes_at_large_volume: str
    sequence: str
    insertion: str
    format: str
    print_in_supplement: str
    include_in_online_release_point: str
    public_law: str | None
    records: tuple[Table3ActRecord, ...]


def iter_act_fragments(member: bytes) -> Iterator[bytes]:
    """Every ``<act>`` element of the bulk member, one at a time.

    The member has no root element, so the second ``<act>`` is junk after the
    document element and no XML parser will read the file whole. The split on
    ``</act>`` is therefore the reader, and it is *checked*: a byte between two
    fragments or after the last one that is not whitespace refuses, so a shape
    this reader has not proved cannot be read as if it had.
    """
    position = 0
    while (cut := member.find(_ACT_CLOSE, position)) >= 0:
        end = cut + len(_ACT_CLOSE)
        start = member.find(_ACT_OPEN, position)
        if start < 0 or start > cut:
            raise UsCodeSourceError("Table III bulk member closes an act it never opened")
        if member[position:start].strip():
            raise UsCodeSourceError("Table III bulk member carries bytes between two act elements")
        yield member[start:end]
        position = end
    if member[position:].strip():
        raise UsCodeSourceError("Table III bulk member carries bytes after the last act element")


def _known(element: Element, attributes: frozenset[str], children: frozenset[str], label: str) -> None:
    for name in element.attrib:
        if name not in attributes:
            raise UsCodeSourceError(f"Table III {label} states an attribute this reader has no field for: {name}")
    for child in element:
        if child.tag not in children:
            raise UsCodeSourceError(f"Table III {label} states an element this reader has no field for: {child.tag}")


def _single(element: Element, tag: str, *, required: bool, label: str) -> str | None:
    found = element.findall(tag)
    if len(found) > 1:
        raise UsCodeSourceError(f"Table III {label} repeats its {tag} element")
    value = (found[0].text or "").strip() if found else None
    if not value:
        if required:
            raise UsCodeSourceError(f"Table III {label} lacks a {tag} element")
        return None
    return value


def parse_act_fragment(fragment: bytes, *, max_bytes: int) -> Table3Act:
    """One ``<act>`` fragment, with every attribute and child the file states."""
    element = parse_xml(fragment, max_bytes=max_bytes, error_type=UsCodeSourceError, label="Table III act")
    if element.tag != "act":
        raise UsCodeSourceError("Table III bulk fragment is not an act element")
    _known(element, _ACT_ATTRIBUTES, _ACT_CHILDREN, "act")

    def attribute(source: Element, name: str, label: str) -> str:
        value = source.get(name)
        if value is None or not value.strip():
            raise UsCodeSourceError(f"Table III {label} lacks the {name} attribute")
        return value

    records = []
    for record in element.iterfind("record"):
        _known(record, _RECORD_ATTRIBUTES, _RECORD_CHILDREN, "record")
        records.append(
            Table3ActRecord(
                (record.get("id") or "").strip() or None,
                attribute(record, "sequence", "record"),
                (record.get("usckey") or "").strip() or None,
                _single(record, "act-section", required=False, label="record"),
                _single(record, "statutes-at-large-page", required=False, label="record"),
                _single(record, "united-states-code-title", required=False, label="record"),
                _single(record, "united-states-code-section", required=False, label="record"),
                _single(record, "united-states-code-status", required=False, label="record"),
                record.get("print-in-supplement"),
            )
        )
    return Table3Act(
        attribute(element, "id", "act"),
        attribute(element, "search-key", "act"),
        _single(element, "num", required=True, label="act") or "",
        attribute(element, "congress", "act"),
        attribute(element, "date", "act"),
        attribute(element, "statutes-at-large-volume", "act"),
        attribute(element, "sequence", "act"),
        attribute(element, "insertion", "act"),
        attribute(element, "format", "act"),
        attribute(element, "print-in-supplement", "act"),
        attribute(element, "include-in-online-release-point", "act"),
        _single(element, "public-law", required=False, label="act"),
        tuple(records),
    )


@dataclass(frozen=True, slots=True)
class Table3Bulk:
    """The whole of Table III as one file, with the release point its member names."""

    source: UsCodeSource
    release_point: str
    member: str
    member_byte_size: int
    member_sha256: str
    act_count: int
    record_count: int
    identity_basis: tuple[str, ...] = ("release-point:member-name",)


def read_table3_bulk_member(
    body: bytes, *, max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES, max_member_bytes: int = DEFAULT_MAX_TABLE3_MEMBER_BYTES
) -> tuple[str, str, bytes]:
    """The bulk zip's single member: its name, the release point it names, and its bytes."""
    _limit(max_bytes)
    _limit(max_member_bytes, "max_member_bytes")
    label = "Table III bulk archive"
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=2,
        max_entry_bytes=max_member_bytes,
        bound="max_member_bytes",
        error_type=UsCodeSourceError,
        label=label,
    ) as archive:
        members = archive_members(archive, max_entries=2, error_type=UsCodeSourceError, label=label)
        if len(members) != 1:
            raise UsCodeSourceError("Table III bulk archive must hold exactly one member")
        info = members[0]
        match = _BULK_MEMBER.fullmatch(info.filename.rsplit("/", 1)[-1])
        if match is None:
            raise UsCodeSourceError("Table III bulk archive member is not a fulldump file")
        return (
            info.filename,
            match["release_point"],
            read_member(
                archive,
                info,
                max_bytes=max_member_bytes,
                error_type=UsCodeSourceError,
                label=label,
                bound="max_member_bytes",
            ),
        )


def iter_table3_acts(
    body: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    max_act_bytes: int = 4 * 1024 * 1024,
) -> Iterator[Table3Act]:
    """Stream the bulk zip's acts. 48,973 acts and 317,590 records are not held at once."""
    _limit(max_act_bytes, "max_act_bytes")
    _name, _release_point, member = read_table3_bulk_member(
        body, max_bytes=max_bytes, max_member_bytes=max_member_bytes
    )
    for fragment in iter_act_fragments(member):
        yield parse_act_fragment(fragment, max_bytes=max_act_bytes)


def read_table3_bulk_archive(
    body: bytes,
    *,
    release_point: str | None = None,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    max_act_bytes: int = 4 * 1024 * 1024,
) -> Table3Bulk:
    """Read the bulk zip and census it: every act parsed, none retained.

    Table III lags the Code. On 2026-09-14 the Code stood at release point
    119-103 and this file at 119-73, which the member's own name states; pass
    ``release_point`` to require a particular one.
    """
    _limit(max_act_bytes, "max_act_bytes")
    name, stated, member = read_table3_bulk_member(body, max_bytes=max_bytes, max_member_bytes=max_member_bytes)
    if release_point is not None and stated != ReleasePoint.from_label(release_point).label:
        raise UsCodeSourceError("Table III bulk archive states another release point than the request")
    acts = records = 0
    for fragment in iter_act_fragments(member):
        acts += 1
        records += len(parse_act_fragment(fragment, max_bytes=max_act_bytes).records)
    if not acts:
        raise UsCodeSourceError("Table III bulk archive states no act")
    return Table3Bulk("table3-bulk", stated, name, len(member), _digest(member), acts, records)
