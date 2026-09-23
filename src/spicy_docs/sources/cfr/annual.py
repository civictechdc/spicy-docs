"""Annual CFR bulk volumes, their sections' printed PART ancestry, and explicitly selected GovInfo section granules."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from ._xml import IdentityXmlScan
from .models import DEFAULT_MAX_BYTES, AnnualCfrSelection, CfrSourceError, CfrXmlMetadata, _date

# GovInfo spells a section granule from the printed number with `§`, whitespace
# and parentheses dropped and dashes and periods folded to `-`: `§ 1.1(h)-1` is
# `sec1-1h-1`, `Sec. 1-1` is `secSec-1-1`. Over the 262 volumes behind the
# published table only appendix, TOC and four content granules stay unmatched
# (docs/research/parsing-survey-2026-09-23.md §4).
_GRANULE_DROP = re.compile(r"[\s§()]")
_GRANULE_FOLD = str.maketrans("—–.", "---")

# `PART` elements carry no attributes: the part exists only as heading text.
# `\s*` admits headings that begin with a newline (12 CFR 326). Matching before
# any dash folding keeps `PART 8—4-H CLUB` at 8 and `PART 124—8(a)` at 124;
# `-(?=[A-Za-z])` ends `PART 1-POSTAL POLICY` at 1 and keeps compound `50-201`.
_PART_NUMBER = r"[0-9]+[A-Za-z]?(?:-[0-9]+[A-Za-z]?)*"
_HEADINGS = {
    tag: re.compile(rf"\s*{tag}\s+({_PART_NUMBER})(?=[—–\s]|-(?=[A-Za-z])|$)", re.IGNORECASE)
    for tag in ("PART", "SUBPART")
}
_PRINTED_PART = re.compile(rf"({_PART_NUMBER})\.")
_JOINED = re.compile(r"through|\bto\b|[—–,]", re.IGNORECASE)
_REVISIONS = frozenset({"EFFDNOT", "EFFDNOTP", "REVTXT"})
_TITLE_HEADING = re.compile(r"\s*Title\s+([0-9]+)(?=\s|[—–:-]|$)")
# 40 CFR vol 9 prints `<PARTS>Part 60 (Appendices)</PARTS>` and no SECTION: its
# source content is APPENDIX text, admitted only when the title page says so.
_APPENDICES = re.compile(r"\(Appendices\)\s*$")
_CONTENT = frozenset({"P", "FP", "PSPACE", "ENTRY", "ENT", "TD", "RESERVED"})


def annual_cfr_granule_token(number: str) -> str:
    """Spell a printed section number as GovInfo's granule id does after ``-sec``."""
    return _GRANULE_DROP.sub("", number).translate(_GRANULE_FOLD)


def annual_cfr_xml_locator(identity: AnnualCfrSelection) -> str:
    """Name the requested edition; older printed revision dates may remain inside."""
    if not isinstance(identity, AnnualCfrSelection):
        raise CfrSourceError("identity must be an AnnualCfrSelection")
    package = f"CFR-{identity.year}-title{identity.title}-vol{identity.volume}"
    if identity.section is not None:
        granule = package + "-sec" + annual_cfr_granule_token(identity.section)
        return f"https://www.govinfo.gov/content/pkg/{package}/xml/{granule}.xml"
    return f"https://www.govinfo.gov/bulkdata/CFR/{identity.year}/title-{identity.title}/{package}.xml"


@dataclass(frozen=True, slots=True)
class AnnualCfrSectionNumber:
    """A printed section number split into the citation parts of its heading part.

    ``number`` drops ``§``, whitespace and one trailing period. ``printed_part``
    is its own leading part (1601 for ``1601.0-1``), ``None`` for unprefixed
    forms such as ``Section 01`` and ``Sec. 1-1``. ``section`` is the number
    less its heading ``{part}.`` prefix when it has one, else the whole number.
    ``range`` marks two numbers joined by ``through``, ``to``, a dash or a
    comma, and repeated-prefix spans (``§ 1.404(a)-4-1.404(a)-7``); the double
    sign alone does not (``§§ 2.188`` is one section), but after it any hyphen
    joins (``§§ 97-97.106``). ``mismatch`` marks a printed part that is neither
    the heading part nor the enclosing subpart's number: publisher typos
    (``§ 206.253`` under ``PART 1206``) and Title 14 Part 241's ``19-8.1``. ``citation`` is ``number`` when it cites one section
    under a known heading part, else ``None``. Title 43 numbers sections by
    subpart (§ 1601.0-1 in ``PART 1600``, ``Subpart 1601``); its printed number
    is the citation while the part stays 1600. A numbered subpart counts only at
    the heading part's width, as Title 43 prints it; NASA's ``Subpart 1`` in
    ``PART 1201`` never does.

    ``citation_joins`` is false when ``citation`` keeps parentheses: the Federal
    Register side's ``cfr_section`` key reads ``26 CFR 1.401(k)-1`` as
    ``26-1.401``, so a consumer joining on that key sets ``cfr_ref`` NULL until
    the shared citation grammar (consolidation plan B4) decides one spelling.
    """

    number: str
    printed_part: str | None
    section: str
    citation: str | None
    citation_joins: bool
    range: bool
    mismatch: bool


def split_annual_cfr_section(number: str, part: str | None, subpart: str | None) -> AnnualCfrSectionNumber:
    """Split a printed SECTNO under its heading ``part`` and numbered ``subpart`` (see ``AnnualCfrSection``)."""
    bare = re.sub(r"[\s§]", "", number).removesuffix(".")
    printed = _PRINTED_PART.match(bare)
    printed_part = printed[1] if printed else None
    section = bare.removeprefix(f"{part}.") if part is not None else bare
    # Measured: every Title 43 subpart citation has the part's width; none of
    # the 271 other numbered-subpart sections (NASA, 48 CFR 719) does.
    series = subpart if part is not None and subpart is not None and len(subpart) == len(part) else None
    # A later number restating a part prefix is a span (`§ 141.15-141.19`,
    # `1509.203-1519.204` under PART 1519); any `-N.` is not: `109-38.301-1.50`.
    rest = bare[printed.end() :] if printed else ""
    joined = _JOINED.search(number) is not None or ("§§" in number and "-" in bare)
    spans = joined or any(f"-{p}." in rest for p in (printed_part, part, series) if p)
    mismatch = printed_part is not None and part is not None and printed_part not in (part, series)
    citation = bare if printed_part is not None and part is not None and not spans and not mismatch else None
    joins = citation is not None and "(" not in citation
    return AnnualCfrSectionNumber(bare, printed_part, section, citation, joins, spans, mismatch)


@dataclass(frozen=True, slots=True)
class AnnualCfrSection:
    """One SECTION of an annual CFR volume and the PART heading that encloses it.

    ``number`` is its first SECTNO's text as printed, which can be whitespace
    only (two em spaces in 17 CFR vol 5), and empty when it prints none.
    ``part`` is the innermost enclosing PART's heading number (``PART
    50-201—…`` gives ``50-201``), ``None`` where that PART prints no numbered
    heading or no PART encloses the section (back-matter reprints of OMB
    sections). The running head never substitutes: some are wrong (``Pt. 1208``
    over ``PART 1209``), so ``running_head`` keeps that PART's EAR text for
    diagnostics only. ``subpart`` is the number in the innermost SUBPART heading
    inside that PART, when it prints one (Title 43's ``Subpart 1601``, NASA's
    ``Subpart 1``). ``granule`` is GovInfo's section token for ``number``.

    ``nested`` sections sit inside another SECTION, ``wrapped`` ones with a
    PART between them and it, ``revised`` ones inside revised text or an
    effective-date note, and ``reserved`` ones hold a RESERVED element. Neither
    ``nested`` nor ``revised`` means "not current": unclosed publisher elements
    swallow the parts that follow (every part after 6 in 15 CFR vol 1 prints
    inside § 6.5's revised text; one wrapper section holds 41 CFR vol 4). Look
    sections up by ``granule`` among the ``canonical`` ones, never by filtering
    on these flags. Per token, the copy with the lowest (nested, revised,
    document position) is ``canonical``; an empty token (a whitespace-only
    number) never is. ``repeated`` marks every copy of a nonempty token that
    more than one un-nested SECTION prints. Split ``number`` for citation with
    ``split_annual_cfr_section(number, part, subpart)``.
    """

    number: str
    part: str | None
    subpart: str | None
    running_head: str | None
    granule: str
    nested: bool
    wrapped: bool
    revised: bool
    reserved: bool
    canonical: bool
    repeated: bool


@dataclass(slots=True)
class _PrintedTitle:
    heading: str | None = None
    sections: int = 0


@dataclass(slots=True)
class _Division:
    depth: int
    heading: str | None = None
    running_head: str | None = None
    number: str | None = None


@dataclass(slots=True)
class _Section:
    depth: int
    part: _Division | None
    subpart: _Division | None
    nested: bool
    wrapped: bool
    revised: bool
    number: str | None = None
    reserved: bool = False


class _AnnualScan(IdentityXmlScan):
    def __init__(self, expected_root: str) -> None:
        self.expected_root = expected_root
        self.header = (self.expected_root, "FDSYS")
        self.front = (self.expected_root, "FMTR", "TITLEPG")
        self.heading = (self.expected_root, "TITLE", "CFRTITLE", "TITLEHD", "HD")
        super().__init__(
            {
                *(self.header + (field,) for field in ("CFRTITLE", "CFRTITLETEXT", "VOL", "DATE")),
                *(self.front + (field,) for field in ("TITLENUM", "SUBJECT", "PARTS", "REVISED", "DATE")),
                self.heading,
                (self.expected_root, "AMDDATE"),
                (self.expected_root, "SECTION", "SECTNO"),
            }
        )
        self.sections = 0
        # Title-page TITLENUMs followed by RESERVED, and the sections after each
        # CFRTITLE heading: what `_requested_titles` needs to admit a combined volume.
        self.reserved: list[str] = []
        self.titles: list[_PrintedTitle] = []
        self.appendices = False
        self._front_last = ""

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        if len(self.stack) == 1 and tag != self.expected_root:
            raise CfrSourceError("annual CFR XML root differs from the requested scope")
        if len(self.stack) > 1 and tag in {"CFRDOC", "CFRGRANULE", "DLPSTEXTCLASS", "ECFR"}:
            raise CfrSourceError("annual CFR XML contains a nested document root")
        if tag == "SECTION":
            self.sections += 1
            if self.titles:
                self.titles[-1].sections += 1
        elif tag == "CFRTITLE" and self.path == self.heading[:3]:
            self.titles.append(_PrintedTitle())
        elif len(self.stack) == len(self.front) + 1 and self.path[:-1] == self.front:
            if tag == "RESERVED" and self._front_last == "TITLENUM":
                self.reserved.append(self.values[(*self.front, "TITLENUM")][-1])
            self._front_last = tag

    def observe_text(self, text: str) -> None:
        # Once found, stop rebuilding the path per text node: a volume has millions.
        if self.body_found or not text.strip():
            return
        path = self.path
        if "SECTION" not in path and not (self.appendices and "APPENDIX" in path):
            return
        if any(tag in _CONTENT for tag in path) or path[-2:] == ("GPH", "GID"):
            self.body_found = True

    def observe_end(self, tag: str) -> None:
        if tag == "HD" and len(self.stack) == len(self.heading) and self.path == self.heading:
            self.titles[-1].heading = self.values[self.heading][-1]
        elif tag == "PARTS" and self.path == (*self.front, "PARTS"):
            self.appendices = _APPENDICES.search(self.values[self.path][-1]) is not None


class _AncestryScan(_AnnualScan):
    """Keep open PART, SUBPART and SECTION frames; capture only their heading and number text."""

    def __init__(self) -> None:
        super().__init__("CFRDOC")
        self.divisions: dict[str, list[_Division]] = {"PART": [], "SUBPART": []}
        self.open: list[_Section] = []
        self.found: list[_Section] = []
        self.revisions = 0
        self.capture: tuple[_Division | _Section, str, int, list[str]] | None = None

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        super().observe_start(tag, attributes)
        parent = self.stack[-2][0] if len(self.stack) > 1 else ""
        if tag in self.divisions:
            self.divisions[tag].append(_Division(len(self.stack)))
        elif tag == "SECTION":
            parts, subparts = self.divisions["PART"], self.divisions["SUBPART"]
            part = parts[-1] if parts else None
            subpart = subparts[-1] if subparts and (part is None or subparts[-1].depth > part.depth) else None
            wrapped = bool(self.open) and part is not None and part.depth > self.open[-1].depth
            section = _Section(len(self.stack), part, subpart, bool(self.open), wrapped, self.revisions > 0)
            self.open.append(section)
            self.found.append(section)
        elif tag in _REVISIONS:
            self.revisions += 1
        if parent == "SECTION" and tag == "RESERVED":
            self.open[-1].reserved = True
        if self.capture is not None:
            return
        target: _Division | _Section | None = None
        if parent in self.divisions and (tag == "HD" or (tag == "EAR" and parent == "PART")):
            target = self.divisions[parent][-1]
        elif parent == "SECTION" and tag == "SECTNO":
            target = self.open[-1]
        field = {"HD": "heading", "EAR": "running_head", "SECTNO": "number"}.get(tag)
        if target is not None and field is not None and getattr(target, field) is None:
            self.capture = (target, field, len(self.stack), [])

    def observe_text(self, text: str) -> None:
        super().observe_text(text)
        if self.capture is not None:
            self.capture[3].append(text)

    def observe_end(self, tag: str) -> None:
        super().observe_end(tag)
        if self.capture is not None and self.capture[2] == len(self.stack):
            target, field, _depth, pieces = self.capture
            setattr(target, field, "".join(pieces))
            if isinstance(target, _Division) and field == "heading":
                match = _HEADINGS[self.stack[-2][0]].match(target.heading or "")
                target.number = match[1] if match else None
            self.capture = None
        if tag in self.divisions:
            self.divisions[tag].pop()
        elif tag == "SECTION":
            self.open.pop()
        elif tag in _REVISIONS:
            self.revisions -= 1


def scan_annual_cfr_sections(xml: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[AnnualCfrSection, ...]:
    """Every SECTION of one annual volume (CFRDOC) in document order, in one streaming pass.

    Reads the heading, never the section number or granule id, for the part:
    Title 43 numbers sections by subpart, Title 41's compound parts contain a
    hyphen and Title 14 Part 241 prints ``19-8.1``. Nested and repeated copies
    stay; ``canonical`` picks one per granule token. Pass ``max_bytes`` with
    room to spare: the largest retained 2025 volume is 12 MiB against the 16 MiB
    default (see docs/sources/cfr.md). Identity is the
    acquisition's job (``validate_annual_cfr_xml``); this refuses only a
    non-volume root, nested document roots and unsafe or oversized XML.
    """
    scan = _AncestryScan()
    scan.read(xml, max_bytes)
    tokens = [annual_cfr_granule_token(section.number or "") for section in scan.found]
    best: dict[str, int] = {}
    outer = Counter(token for token, section in zip(tokens, scan.found, strict=True) if token and not section.nested)
    for index, (token, section) in enumerate(zip(tokens, scan.found, strict=True)):
        held = scan.found[best[token]] if token in best else None
        if token and (held is None or (section.nested, section.revised) < (held.nested, held.revised)):
            best[token] = index
    return tuple(
        AnnualCfrSection(
            section.number or "",
            section.part.number if section.part else None,
            section.subpart.number if section.subpart else None,
            section.part.running_head if section.part else None,
            token,
            section.nested,
            section.wrapped,
            section.revised,
            section.reserved,
            best.get(token) == index,
            outer[token] > 1,
        )
        for index, (token, section) in enumerate(zip(tokens, scan.found, strict=True))
    )


def _title_number(value: str) -> int:
    match = _TITLE_HEADING.match(value)
    if match is None:
        raise CfrSourceError("annual CFR title heading lacks its title number")
    return int(match[1])


def _requested_titles(scan: _AnnualScan) -> list[int]:
    """Title numbers from the title page and title headings, less reserved titles bound in with the volume's own.

    2025 Title 34 vol 4 also prints Title 35: `<TITLENUM>Title 35</TITLENUM>
    <RESERVED>[Reserved]</RESERVED>` on the title page and a last CFRTITLE
    heading `Title 35 [Reserved]` with no section after it. A title marked that
    way must print such a heading, and is then dropped; a second remaining title
    in either place is refused. A lone blank value states nothing, as a missing
    one does; a blank beside another value is refused.
    """
    reserved = {_title_number(value) for value in scan.reserved}
    sections: dict[int, int] = {}
    for title in scan.titles:
        if title.heading is not None and title.heading.strip():
            number = _title_number(title.heading)
            sections[number] = sections.get(number, 0) + title.sections
    if any(sections.get(number) != 0 for number in reserved):
        raise CfrSourceError("annual CFR reserved title needs a heading with no section after it")
    found = []
    for values in (scan.values.get((*scan.front, "TITLENUM"), []), scan.values.get(scan.heading, [])):
        if len(values) == 1 and not values[0].strip():
            continue
        numbers = [number for number in map(_title_number, values) if number not in reserved]
        if len(numbers) > 1:
            raise CfrSourceError("annual CFR XML repeats its title")
        found += numbers
    return found


def _integer(value: str, label: str) -> int:
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value) is None:
        raise CfrSourceError(f"annual CFR native {label} must be an integer")
    return int(value)


def validate_annual_cfr_xml(
    body: bytes,
    *,
    identity: AnnualCfrSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> CfrXmlMetadata:
    """Check native fields without treating a requested edition as a printed date.

    Full volumes need not state their volume number. The canonical response URL
    establishes that requested coordinate; it does not independently verify it
    inside the body. Section granules carry stronger FDSYS identity fields.
    """
    if final_url != annual_cfr_xml_locator(identity):
        raise CfrSourceError("annual CFR response URL differs from the requested edition and scope")
    scan = _AnnualScan("CFRGRANULE" if identity.section is not None else "CFRDOC")
    scan.read(body, max_bytes)
    if not scan.body_found:
        raise CfrSourceError("annual CFR XML lacks source section content")
    granule = identity.section is not None
    native_title = scan.field((*scan.header, "CFRTITLE"), required=granule)
    native_volume = scan.field((*scan.header, "VOL"), required=granule)
    title_numbers = [] if native_title is None else [_integer(native_title, "title")]
    title_numbers += _requested_titles(scan)
    if not title_numbers or any(number != identity.title for number in title_numbers):
        raise CfrSourceError("annual CFR native title differs from the request or is absent")
    volume = _integer(native_volume, "volume") if native_volume is not None else None
    if volume is not None and volume != identity.volume:
        raise CfrSourceError("annual CFR native volume differs from the request")
    section = scan.field((scan.root, "SECTION", "SECTNO"), required=granule)
    if granule and (
        section is None or section.strip().removeprefix("§").strip() != identity.section or scan.sections != 1
    ):
        raise CfrSourceError("annual CFR XML must contain exactly the requested section")
    stated_date = scan.field((*scan.header, "DATE"), required=granule)
    if stated_date is not None:
        _date(stated_date.strip())
    else:
        stated_date = scan.field((*scan.front, "DATE"))
    basis = ["title:native", "volume:native" if volume is not None else "volume:request-url", "edition:request-url"]
    if granule:
        basis.append("section:native")
    revision = scan.field((*scan.front, "REVISED"))
    return CfrXmlMetadata(
        "annual-cfr",
        identity.title,
        volume,
        None,
        identity.section,
        scan.root,
        scan.field((*scan.header, "CFRTITLETEXT")) or scan.field((*scan.front, "SUBJECT")),
        stated_date,
        revision,
        tuple(scan.values.get((scan.root, "AMDDATE"), [])),
        tuple(basis),
    )
