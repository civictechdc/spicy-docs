"""The Popular Name Tool page: one record per stated fact, defects named rather than dropped."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from spicy_docs.sources.uscode.core import (
    _DIVISION,
    _STATVIEWER_PAGE,
    DEFAULT_MAX_ENTRIES_PER_PAGE,
    DEFAULT_MAX_PAGE_BYTES,
    UsCodeSource,
    UsCodeSourceError,
    _body,
    _count,
    _limit,
    _visible,
)

# --------------------------------------------------------------------------- #
# Popular Name Tool
# --------------------------------------------------------------------------- #

#: Every way this reader declines to read something the page states. Codes are
#: data: the result carries one defect per refusal and counts them.
POPULAR_NAME_DEFECTS = ("entry_without_a_name", "information_without_a_content_type", "usc_key_unparsable")

_USC_KEY = re.compile(r"(?P<title>[1-9][0-9]*):(?P<section>[^\s:]+)")
_ENTRY_CLASS = "popular-name-table-entry"
#: Elements that never close. The page writes them XHTML style (``<br />``), but
#: a generator that stopped would otherwise drift the element depth upward and
#: leave an entry open forever.
_VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"})
_ENTRY_ATTRIBUTES = ("id", "release-point", "item")
_INFORMATION_ATTRIBUTES = ("content-type", "t3searchkey", "usckey", "datekey")


@dataclass(frozen=True, slots=True)
class PopularNameRecord:
    """One popular name and one thing the tool says about it.

    ``content_type`` is the tool's own vocabulary (``cite``, ``see``,
    ``also-known-as``, ``renamed``, ``short-title-ref``), kept verbatim: the
    difference between "this act is" and "this name means" is the difference
    between an identity and a redirect. ``table3_href`` is the link the page
    itself writes to the act's Table III page, so the file name is read rather
    than derived from the key.
    """

    name: str
    content_type: str
    stated: str
    entry_id: str | None = None
    item: str | None = None
    release_point: str | None = None
    table3_key: str | None = None
    table3_href: str | None = None
    date_key: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    usc_key: str | None = None
    division: str | None = None
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None
    #: Which statement supplied the Statutes at Large place: the page's own
    #: statviewer query, its prose, ``both`` where they agree, or
    #: ``disagreement`` where they do not. A disagreement is reported, never
    #: resolved.
    statutes_at_large_witness: str | None = None


@dataclass(frozen=True, slots=True)
class PopularNameDefect:
    """One stated fact this reader refused to read, carrying a declared reason code and the value refused."""

    reason: str
    name: str
    raw_value: str | None = None

    def __post_init__(self) -> None:
        if self.reason not in POPULAR_NAME_DEFECTS:
            raise UsCodeSourceError("undeclared popular name defect")


@dataclass(frozen=True, slots=True)
class PopularNames:
    """What the page said, including what it said nothing readable about."""

    source: UsCodeSource
    entries: int
    records: tuple[PopularNameRecord, ...]
    defects: tuple[PopularNameDefect, ...]
    release_points: tuple[str, ...]
    #: Attribute name -> how many times the page stated it without a field here.
    stated_but_not_carried: dict[str, int] = field(default_factory=dict)


class _PopularNamesReader(HTMLParser):
    """Read the flat entry and information elements the generator emits.

    The page carries no tree to walk: one ``<div>`` per name and one ``<p>`` per
    thing the tool says about it, with the identifying facts in attributes. The
    element stack is tracked anyway, so a future nested element cannot silently
    end an entry early the way a ``</div>`` expression would.
    """

    def __init__(self, max_entries: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_entries = max_entries
        self.entries = 0
        self.records: list[PopularNameRecord] = []
        self.defects: list[PopularNameDefect] = []
        self.release_points: list[str] = []
        self.uncarried: dict[str, int] = {}
        self._depth = 0
        self._entry: dict[str, str | None] | None = None
        self._entry_depth = 0
        self._name: list[str] | None = None
        self._information: dict[str, str | None] | None = None
        self._text: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID_ELEMENTS:
            self._depth += 1
        values = dict(attrs)
        if len(values) != len(attrs):
            raise UsCodeSourceError("Popular Name Tool repeats an attribute")
        classes = (values.get("class") or "").split()
        if tag == "div" and _ENTRY_CLASS in classes:
            if self._entry is not None:
                raise UsCodeSourceError("Popular Name Tool nests entries")
            self.entries += 1
            if self.entries > self.max_entries:
                raise UsCodeSourceError("Popular Name Tool states more entries than max_entries")
            self._entry = {name: values.get(name) for name in _ENTRY_ATTRIBUTES}
            self._entry_depth = self._depth
            self._name = None
            self._count_uncarried(values, _ENTRY_ATTRIBUTES)
            point = values.get("release-point")
            if point and point not in self.release_points:
                self.release_points.append(point)
        elif tag == "p" and self._entry is not None:
            if "popular-name" in classes:
                self._name = []
                self._text = []
            elif "popular-name-information" in classes:
                self._information = {name: values.get(name) for name in _INFORMATION_ATTRIBUTES}
                self._count_uncarried(values, _INFORMATION_ATTRIBUTES)
                self._text = []
                self._links = []
        elif tag == "a" and self._information is not None:
            href = values.get("href")
            if href:
                self._links.append(href)

    def _count_uncarried(self, values: dict[str, str | None], carried: tuple[str, ...]) -> None:
        for name in values:
            if name not in carried and name != "class":
                self.uncarried[name] = self.uncarried.get(name, 0) + 1

    def handle_data(self, data: str) -> None:
        if self._information is not None or self._name is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._entry is not None:
            if self._information is not None:
                self._finish_information()
            elif self._name is not None:
                self._name = [_visible(self._text)]
            self._text = []
        elif tag == "div" and self._entry is not None and self._depth == self._entry_depth:
            if not (self._name and self._name[0]):
                self.defects.append(PopularNameDefect("entry_without_a_name", "", self._entry.get("id") or None))
            self._entry = None
        if tag not in _VOID_ELEMENTS:
            self._depth = max(self._depth - 1, 0)

    def _finish_information(self) -> None:
        assert self._entry is not None and self._information is not None
        information, self._information = self._information, None
        name = self._name[0] if self._name else ""
        stated = _visible(self._text)
        content_type = information.get("content-type")
        if not name:
            return
        if not content_type:
            self.defects.append(PopularNameDefect("information_without_a_content_type", name, stated or None))
            return
        usc_key = information.get("usckey")
        anchor = _USC_KEY.fullmatch(usc_key) if usc_key else None
        if usc_key and anchor is None:
            # The appendix titles state "18A:1" and "28A:Rule"; 18A is not
            # title 18, so the key is kept and no anchor is minted from it.
            self.defects.append(PopularNameDefect("usc_key_unparsable", name, usc_key))
        is_cite = content_type == "cite"
        volume, page, witness = self._statutes_at_large(stated) if is_cite else (None, None, None)
        division = _DIVISION.search(stated) if is_cite else None
        self.records.append(
            PopularNameRecord(
                name=name,
                content_type=content_type,
                stated=stated,
                entry_id=self._entry.get("id"),
                item=self._entry.get("item"),
                release_point=self._entry.get("release-point"),
                table3_key=information.get("t3searchkey") or None,
                table3_href=next((link for link in self._links if link.startswith("/table3/")), None),
                date_key=information.get("datekey") or None,
                usc_title=anchor["title"] if anchor else None,
                usc_section=anchor["section"] if anchor else None,
                usc_key=usc_key or None,
                division=division["division"] if division else None,
                statutes_at_large_volume=volume,
                statutes_at_large_page=page,
                statutes_at_large_witness=witness,
            )
        )

    def _statutes_at_large(self, stated: str) -> tuple[str | None, str | None, str | None]:
        """The place the page states twice: once as a link query, once as prose.

        The query is preferred because it is the machine-stated fact and it
        carries the volume the link text can omit. Where both are present they
        are compared; a disagreement is named rather than resolved.
        """
        linked = None
        for href in self._links:
            parsed = urlsplit(href)
            if parsed.path.endswith("/statviewer.htm"):
                query = parse_qs(parsed.query)
                volume = (query.get("volume") or [""])[0]
                page = (query.get("page") or [""])[0]
                if volume.isdigit() and page.isdigit():
                    linked = (volume, page)
                break
        prose = _STATVIEWER_PAGE.search(stated)
        spoken = (prose["volume"], prose["page"]) if prose else None
        if linked is None and spoken is None:
            return None, None, None
        if linked is None:
            return spoken[0], spoken[1], "stated"
        if spoken is None:
            return linked[0], linked[1], "statviewer"
        return linked[0], linked[1], "both" if linked == spoken else "disagreement"


def parse_popular_names(
    body: bytes, *, max_bytes: int = DEFAULT_MAX_PAGE_BYTES, max_entries: int = DEFAULT_MAX_ENTRIES_PER_PAGE
) -> PopularNames:
    """Read the whole Popular Name Tool page into one record per stated fact."""
    _limit(max_bytes)
    _count(max_entries, "max_entries")
    data = _body(body, max_bytes, "Popular Name Tool page")
    if b"</html>" not in data[-4096:]:
        raise UsCodeSourceError("Popular Name Tool page is not closed by </html>")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UsCodeSourceError("Popular Name Tool page is not the UTF-8 the publisher declares") from error
    reader = _PopularNamesReader(max_entries)
    reader.feed(text)
    reader.close()
    if not reader.entries:
        raise UsCodeSourceError("Popular Name Tool page states no entry")
    return PopularNames(
        "popular-names",
        reader.entries,
        tuple(reader.records),
        tuple(reader.defects),
        tuple(reader.release_points),
        dict(sorted(reader.uncarried.items())),
    )
