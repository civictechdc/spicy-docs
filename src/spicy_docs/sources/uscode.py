"""Explicit OLRC U.S. Code sources: release points, annual archives, popular names and Table III.

The Office of the Law Revision Counsel publishes the Code itself, keyless, with
no API and no content negotiation. Four families arrive here and each proves its
own identity from its own bytes:

* **Release point.** One edition of the Code current through a public law. Each
  title is a one-member zip of United States Legislative Markup whose ``<meta>``
  states the title (``docNumber``) and the release point (``docPublicationName``,
  spelled ``Online@119-103``). ``xml_uscAll`` is the same 58 documents in one
  zip of about 108 MB.
* **Annual historical archive.** One year of the Code as XHTML. Every title
  member states its edition, year, title and currency in ``AUTHORITIES-*`` HTML
  comments, so a member proves its own year without its file name.
* **Popular Name Tool.** One generated page, about 11 MB, one flat
  ``<div class='popular-name-table-entry'>`` per name with the identifying facts
  in attributes. It also links each name's own Table III page, so the Table III
  file name is read rather than derived.
* **Table III.** Which act section went to which Code section: one page per act,
  and one bulk zip whose member is a bare concatenation of ``<act>`` fragments
  rather than a well-formed document.

This publisher's USLM is **not** GovInfo's. OLRC serves USLM 1.0 in
``http://xml.house.gov/schemas/uslm/1.0`` under a ``uscDoc`` root;
:mod:`spicy_docs.sources.govinfo.uslm` serves USLM 2.x in
``http://schemas.gpo.gov/xml/uslm`` under ``pLaw`` and ``statuteCompilation``.
The two share no element name, but they do share the document shape, so this
module binds that module's :class:`~spicy_docs.sources.govinfo.uslm.UslmScan` to
this namespace, root and body sections rather than scanning twice.

Three publisher behaviours shape every check below, all measured on 2026-09-14
and retained in ``corpora/supply-2026-09-02/receipts/port-P01-uscode-2026-09-14/``:

1. **An absent Table III act answers HTTP 200 and a truncated page.** The server
   sends 16,134 bytes of site furniture and closes the stream. It carries no
   rows, so a reader that trusted the status would record "this act classified
   nothing". :func:`parse_table3_page` therefore requires the page to state the
   requested act and to be closed, and refuses the truncated answer by name.
2. **A title the publisher lists but does not serve answers 302**, to
   ``/docnotfound.xhtml``. Title 53 is listed on the download page and answers
   that way. A redirect is neither data nor absence; it is refused with its
   status.
3. **The zip routes carry no ``Content-Type`` and no ``Content-Length``.** The
   shape is proved from the bytes: a local file header, a CRC check, then the
   native identity of every member.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element

from spicy_docs.reading.xml import parse_xml
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member

from .govinfo.uslm import UslmScan

OLRC = "https://uscode.house.gov"
USLM_NAMESPACE = "http://xml.house.gov/schemas/uslm/1.0"
DUBLIN_CORE_NAMESPACE = "http://purl.org/dc/elements/1.1/"
DUBLIN_CORE_TERMS_NAMESPACE = "http://purl.org/dc/terms/"

#: The title codes the publisher's own download page links, in its spelling and
#: order. ``53`` is listed and answers 302; that is a fact about the route, not
#: about this vocabulary, so the code stays here and the refusal names the status.
TITLES: tuple[str, ...] = (
    "01", "02", "03", "04", "05", "05a", "06", "07", "08", "09", "10", "11", "11a", "12", "13", "14",
    "15", "16", "17", "18", "18a", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "28a",
    "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44",
    "45", "46", "47", "48", "49", "50", "50a", "51", "52", "53", "54",
)  # fmt: skip

#: The publisher's own annual span. 1994 is the first XHTML archive offered.
FIRST_ANNUAL_YEAR = 1994

# The largest title is 42 at 113,732,787 bytes of XML; the largest annual member
# is 2024's title 42 at 78,766,785 bytes of XHTML; the whole-corpus zip is about
# 108 MB and the Table III bulk member is 126,260,704 bytes.
MAX_USCODE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_XML_BYTES = 128 * 1024 * 1024
# Every zip this publisher serves fits here with headroom: the corpus at 108.6
# MB is the largest, then the 2024 annual archive at 87.8 MB.
DEFAULT_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_PAGE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_TABLE3_MEMBER_BYTES = 192 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 128
DEFAULT_MAX_ENTRIES_PER_PAGE = 65_536

#: Where an annual member's identity comments sit. The furthest observed is 842
#: bytes into the file across all 1,781 title members of the 31 retained zips.
ANNUAL_HEADER_BYTES = 16 * 1024

type UsCodeSource = Literal["release-point-title", "annual-title", "popular-names", "table3-act", "table3-bulk"]

_BULK_MEMBER = re.compile(r"fulldump@(?P<release_point>[0-9]+-[0-9]+)\.xml")
_RELEASE_POINT = re.compile(r"(?P<congress>[1-9][0-9]{0,2})-(?P<law>[1-9][0-9]{0,4})")
#: A Table III key is a public law (``90-148``) or a pre-1957 session-law
#: chapter (``1955:360``). The Congress is bounded so the two shapes cannot
#: overlap: ``1955-360`` would otherwise read as Public Law 1955-360.
_TABLE3_KEY = re.compile(r"(?:[1-9][0-9]{0,2}-[1-9][0-9]*|(?:1[789]|20)[0-9]{2}:[1-9][0-9]*)")
_STATVIEWER_PAGE = re.compile(r"(?P<volume>[0-9]+)\s+Stat\.\s+(?P<page>[0-9]+)")
_DIVISION = re.compile(r"\bdiv\.\s*(?P<division>[A-Z]{1,3})\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class UsCodeSourceError(ValueError):
    """The request or response cannot establish the selected OLRC source."""


def _limit(max_bytes: object, name: str = "max_bytes") -> int:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_USCODE_BYTES:
        raise UsCodeSourceError(f"{name} must be a positive integer no greater than 512 MiB")
    return max_bytes


def _count(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise UsCodeSourceError(f"{name} must be a positive integer")
    return value


def _body(value: object, max_bytes: int, label: str) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > max_bytes:
        raise UsCodeSourceError(f"{label} must be nonempty bytes within max_bytes")
    return value


def _comparable(citation: str) -> str:
    """The publisher spells one key two ways: ``111-226`` in a URL, ``111–226`` in the page."""
    return re.sub(r"\s+", " ", citation.replace("–", "-").replace("—", "-")).strip()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# selections and locators
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReleasePoint:
    """One edition of the Code, named by the last public law folded into it."""

    congress: int
    law: int

    def __post_init__(self) -> None:
        for name, value, ceiling in (("congress", self.congress, 999), ("law", self.law, 99_999)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise UsCodeSourceError(f"{name} must be an integer from 1 to {ceiling}")

    @property
    def label(self) -> str:
        """The publisher's own spelling, as it appears in file names and in ``docPublicationName``."""
        return f"{self.congress}-{self.law}"

    @property
    def path(self) -> str:
        return f"{self.congress}/{self.law}"

    @classmethod
    def from_label(cls, value: str) -> ReleasePoint:
        match = _RELEASE_POINT.fullmatch(value or "")
        if match is None:
            raise UsCodeSourceError("release point label is unsupported")
        return cls(int(match["congress"]), int(match["law"]))


@dataclass(frozen=True, slots=True)
class TitleSelection:
    """One title at one release point, in the publisher's own two-digit code."""

    release_point: ReleasePoint
    title: str

    def __post_init__(self) -> None:
        if not isinstance(self.release_point, ReleasePoint):
            raise UsCodeSourceError("release_point must be a ReleasePoint")
        if self.title not in TITLES:
            raise UsCodeSourceError("title must be one of the codes the publisher lists")

    @property
    def doc_number(self) -> str:
        """The native ``docNumber`` spelling: ``01`` states ``1`` and ``05a`` states ``5a``."""
        return self.title.lstrip("0")

    @property
    def is_appendix(self) -> bool:
        return self.title.endswith("a")

    @property
    def file_name(self) -> str:
        return f"xml_usc{self.title}@{self.release_point.label}.zip"

    @property
    def identifier(self) -> str:
        """The USLM identifier the document carries on its root, when it carries one."""
        return f"/us/usc/t{self.doc_number}"


def title_xml_locator(selection: TitleSelection) -> str:
    """One title's USLM zip at one release point."""
    if not isinstance(selection, TitleSelection):
        raise UsCodeSourceError("selection must be a TitleSelection")
    return f"{OLRC}/download/releasepoints/us/pl/{selection.release_point.path}/{selection.file_name}"


def corpus_xml_locator(release_point: ReleasePoint) -> str:
    """Every title at one release point in one zip of about 108 MB."""
    if not isinstance(release_point, ReleasePoint):
        raise UsCodeSourceError("release_point must be a ReleasePoint")
    return f"{OLRC}/download/releasepoints/us/pl/{release_point.path}/xml_uscAll@{release_point.label}.zip"


def annual_archive_locator(year: int) -> str:
    """One year of the Code as XHTML; the publisher offers 1994 onwards."""
    if type(year) is not int or not FIRST_ANNUAL_YEAR <= year <= 2100:
        raise UsCodeSourceError(f"year must be an integer from {FIRST_ANNUAL_YEAR} to 2100")
    return f"{OLRC}/download/annualhistoricalarchives/XHTML/{year}.zip"


def popular_names_locator() -> str:
    """The whole Popular Name Tool, one generated page of about 11 MB."""
    return f"{OLRC}/popularnames/popularnames.htm"


def table3_file_name(key: str) -> str:
    """The Table III file name for an act key, by the rule the publisher's own page applies.

    ``table3years.htm`` ships ``getActFileName()``: replace the *first* ``-``,
    then the ``:``, with ``_``, drop spaces and periods, append ``.htm``. Both
    key shapes contain exactly one separator, so the single replacement is
    total; the rule is transcribed rather than re-derived.
    """
    if not isinstance(key, str) or _TABLE3_KEY.fullmatch(key) is None:
        raise UsCodeSourceError("Table III key must be a public law or a pre-1957 chapter key")
    return key.replace("-", "_", 1).replace(":", "_", 1) + ".htm"


def table3_act_locator(key: str) -> str:
    """One act's Table III page."""
    return f"{OLRC}/table3/{table3_file_name(key)}"


def table3_bulk_locator() -> str:
    """The whole of Table III in one zip, as ``table3years.htm`` links it."""
    return f"{OLRC}/table3/table3-xml-bulk.zip"


# --------------------------------------------------------------------------- #
# release-point USLM
# --------------------------------------------------------------------------- #


def _u(tag: str) -> str:
    return "{" + USLM_NAMESPACE + "}" + tag


def _dc(tag: str) -> str:
    return "{" + DUBLIN_CORE_NAMESPACE + "}" + tag


def _dcterms(tag: str) -> str:
    return "{" + DUBLIN_CORE_TERMS_NAMESPACE + "}" + tag


_USC_META_FIELDS = (
    _dc("title"),
    _dc("type"),
    _dc("publisher"),
    _dc("creator"),
    _dcterms("created"),
    _u("docNumber"),
    _u("docPublicationName"),
    _u("property"),
)


@dataclass(frozen=True, slots=True)
class UsCodeTitleMetadata:
    """Native ``<meta>`` facts of one title. Publisher spellings are kept; nothing is normalized."""

    source: UsCodeSource
    title: str
    doc_number: str
    release_point: str
    document_type: str
    heading: str
    publisher: str | None
    converter: str | None
    created: str | None
    positive_law: str | None
    schema_location: str | None
    identifier: str | None
    identity_basis: tuple[str, ...]
    body_present: bool = True


def _usc_scan() -> UslmScan:
    """The shared USLM scan bound to OLRC's namespace, root, body sections and refusals.

    A title's text lives in ``main`` and an appendix title's in ``appendix``;
    both are the document's own text, so this publisher has no section that
    states a body it does not carry.
    """
    return UslmScan(
        "uscDoc",
        namespace=USLM_NAMESPACE,
        body_sections=("main", "appendix"),
        referring_sections=(),
        meta_fields=_USC_META_FIELDS,
        error_type=UsCodeSourceError,
        label="U.S. Code USLM",
        root_refusal="U.S. Code USLM root is not uscDoc in the OLRC namespace",
    )


def _property(scan: UslmScan, role: str) -> str | None:
    """The one value the meta block states for a property role, or None where it states none."""
    values = scan.values.get(scan.meta_path + (_u("property"),), [])
    stated = [value.strip() for found, value in zip(scan.property_roles, values, strict=True) if found == role]
    if len(stated) > 1:
        raise UsCodeSourceError(f"U.S. Code USLM repeats the {role} property")
    return stated[0] if stated else None


def validate_title_xml(
    body: bytes,
    *,
    selection: TitleSelection,
    final_url: str | None = None,
    max_bytes: int = DEFAULT_MAX_XML_BYTES,
) -> UsCodeTitleMetadata:
    """Prove the title's native number and release point match the request.

    ``docNumber`` and ``docPublicationName`` are the identity; the file name is
    not consulted, because the publisher's own names disagree with themselves
    (``xml_usc05a@…zip`` carries ``usc05A.xml``, and ``11a`` stays lower case).
    ``identifier`` is a second native witness and is checked where the document
    states one.
    """
    if not isinstance(selection, TitleSelection):
        raise UsCodeSourceError("selection must be a TitleSelection")
    if final_url is not None and final_url != title_xml_locator(selection):
        raise UsCodeSourceError("U.S. Code title response URL differs from the requested title")
    _limit(max_bytes)
    scan = _usc_scan()
    scan.read(body, max_bytes)
    doc_number = scan.meta(_u("docNumber"), required=True) or ""
    if doc_number != selection.doc_number:
        raise UsCodeSourceError("U.S. Code title native number differs from the request")
    release_point = scan.meta(_u("docPublicationName"), required=True) or ""
    if release_point != f"Online@{selection.release_point.label}":
        raise UsCodeSourceError("U.S. Code title native release point differs from the request")
    document_type = scan.meta(_dc("type"), required=True) or ""
    expected_type = "USCTitleAppendix" if selection.is_appendix else "USCTitle"
    if document_type != expected_type:
        raise UsCodeSourceError("U.S. Code title document type differs from the requested title kind")
    if scan.identifier is not None and scan.identifier != selection.identifier:
        raise UsCodeSourceError("U.S. Code title native identifier differs from the request")
    basis = ["doc-number:native", "release-point:native", "document-type:native"]
    if scan.identifier is not None:
        basis.append("identifier:native")
    return UsCodeTitleMetadata(
        "release-point-title",
        selection.title,
        doc_number,
        release_point,
        document_type,
        scan.meta(_dc("title"), required=True) or "",
        scan.meta(_dc("publisher")),
        scan.meta(_dc("creator")),
        scan.meta(_dcterms("created")),
        _property(scan, "is-positive-law"),
        scan.schema_location,
        scan.identifier,
        tuple(basis),
        body_present=scan.body_text,
    )


# --------------------------------------------------------------------------- #
# annual historical archives
# --------------------------------------------------------------------------- #

#: Every comment an annual title member states about itself. All ten are present
#: in all 1,781 title members of the 31 retained zips.
ANNUAL_FIELDS = (
    "AUTHORITIES-PUBLICATION-NAME",
    "AUTHORITIES-PUBLICATION-ID",
    "AUTHORITIES-PUBLICATION-YEAR",
    "AUTHORITIES-LAWS-ENACTED-THROUGH-DATE",
    "SEARCHABLE-LAWS-ENACTED-THROUGH-DATE",
    "AUTHORITIES-USC-TITLE-NAME",
    "AUTHORITIES-USC-TITLE-ENUM",
    "AUTHORITIES-USC-TITLE-STATUS",
    "CONVERSION-PROGRAM",
    "CONVERSION-DATETIME",
)
_ANNUAL_COMMENT = re.compile(r"\s*(?P<name>[A-Z][A-Z0-9-]*):(?P<value>.*)", re.DOTALL)


@dataclass(frozen=True, slots=True)
class AnnualTitleMetadata:
    """What one annual XHTML title member says about itself, in the publisher's spelling."""

    source: UsCodeSource
    publication_name: str
    publication_id: str
    publication_year: str
    laws_enacted_through: str
    laws_enacted_through_stated: str
    title_name: str
    title_enum: str
    title_status: str
    conversion_program: str
    conversion_datetime: str
    identity_basis: tuple[str, ...] = ("publication-year:native", "title-enum:native")


class _AnnualHeaderReader(HTMLParser):
    """Read only the identity comments the generator writes above ``<body>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self.repeated: set[str] = set()

    def handle_comment(self, data: str) -> None:
        match = _ANNUAL_COMMENT.fullmatch(data)
        if match is None or match["name"] not in ANNUAL_FIELDS:
            return
        name = match["name"]
        if name in self.fields:
            self.repeated.add(name)
        self.fields[name] = match["value"].strip()


def _annual_header(body: bytes) -> dict[str, str]:
    # Identity sits in the first kilobyte; the body beyond it is not decoded at
    # all, because the 1994 edition is not valid UTF-8 (0xFF at 14,644,597 in
    # 1994usc42.htm) and reading 75 MB to learn a year would be waste besides.
    reader = _AnnualHeaderReader()
    reader.feed(body[:ANNUAL_HEADER_BYTES].decode("utf-8", "replace"))
    reader.close()
    if reader.repeated:
        raise UsCodeSourceError("U.S. Code annual title repeats an identity comment")
    missing = [name for name in ANNUAL_FIELDS if not reader.fields.get(name)]
    if missing:
        raise UsCodeSourceError(f"U.S. Code annual title lacks an identity comment: {missing[0]}")
    for name, value in reader.fields.items():
        if not value.isascii() or _CONTROL.search(value):
            raise UsCodeSourceError(f"U.S. Code annual title identity comment is not printable ASCII: {name}")
    return reader.fields


def validate_annual_title_html(
    body: bytes, *, year: int | None = None, max_bytes: int = DEFAULT_MAX_XML_BYTES
) -> AnnualTitleMetadata:
    """Prove one annual member's own edition and title from its ``AUTHORITIES-*`` comments.

    ``year`` checks the stated publication year when the caller has one to check
    against. It is optional because the publisher's own archives carry members
    that state an earlier year: the eliminated Title 50 Appendix is reissued
    unchanged, so 2016 and 2017 both ship a member stating 2015.
    """
    _limit(max_bytes)
    data = _body(body, max_bytes, "U.S. Code annual title")
    if not data.lstrip()[:15].lower().startswith(b"<!doctype html"):
        raise UsCodeSourceError("U.S. Code annual title does not begin with an XHTML doctype")
    if b"</html>" not in data[-4096:]:
        raise UsCodeSourceError("U.S. Code annual title is not closed by </html>")
    fields = _annual_header(data)
    stated_year = fields["AUTHORITIES-PUBLICATION-YEAR"]
    if not stated_year.isdigit() or len(stated_year) != 4:
        raise UsCodeSourceError("U.S. Code annual title publication year is not a four-digit year")
    if year is not None and stated_year != str(year):
        raise UsCodeSourceError("U.S. Code annual title publication year differs from the request")
    return AnnualTitleMetadata("annual-title", *(fields[name] for name in ANNUAL_FIELDS))


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


def _visible(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()


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
_TABLE3_CURRENCY = re.compile(r"Table III Tool \[Current through (?P<release_point>[0-9]+-[0-9]+)")


@dataclass(frozen=True, slots=True)
class Table3Record:
    """One act section and the Code place it was classified to.

    ``usc_section`` is empty where the section was repealed, omitted or
    classified nowhere: the row exists and says so, and dropping it would turn
    "we know this went nowhere" into "we do not know".
    """

    act_section: str
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
            if self._row.get("actsection"):
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

    An act the table does not hold answers HTTP 200 and a page cut off inside
    the site menu. It states no act and is not closed, so both checks refuse it;
    a row count of zero is never read as "this act classified nothing".
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
        records.append(
            Table3Record(
                act_section=row["actsection"],
                statutes_at_large_volume=volume,
                statutes_at_large_page=page or row.get("statutesatlargepage") or None,
                usc_title=row.get("unitedstatescodetitle") or None,
                usc_section=row.get("unitedstatescodesection") or None,
                status=row.get("unitedstatescodestatus") or None,
            )
        )
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
