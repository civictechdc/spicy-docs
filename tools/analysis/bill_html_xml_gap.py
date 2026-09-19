"""Measure how far a bill's HTML rendition is from its XML, to size the ``bill_dtd`` profile.

Bills before the 113th Congress offer HTML and PDF only, so the proposal in
``docs/research/closing-the-gaps-2026-09-19.md`` (gap B1, section 3.1) wants to
reconstruct the bill DTD from the HTML rendition. Before any of that is built,
this tool asks the paired question on Congresses that have both: hide the XML,
read the HTML, and count what deterministic rules recover. Run from the
repository root:

  uv run --frozen python -m tools.analysis.bill_html_xml_gap \\
      --env-file .env --cache <scratchpad>/bill-gap \\
      --output docs/research/bill-html-xml-gap-2026-09-19.json \\
      --doc docs/research/bill-html-xml-gap-2026-09-19.md

``--offline`` rewrites the document's generated block from the saved output
without the network. Bytes land in ``--cache`` and are reused on a rerun, so a
second run with a full cache makes no request at all.

Four measurements, each stated with what it cannot see:

1. **Text fidelity.** Both renditions go through ``extraction.body_text`` (the
   one derivation per rendition this repository already uses), then the same
   normalization: casefold, GPO's ``--`` and the em dash as separators, word
   tokens only. The difflib ratio over the word sequences, and the words only
   one side has, are reported for the whole document and for the body alone
   (the XML's ``legis-body``/``resolution-body`` against the HTML from its
   first section heading). Casefolding hides that the HTML sets headings in
   capitals and quoted headers in lowercase; the case is lost, and the profile
   has to restore it from the XML's conventions, not from the HTML.
2. **Structure by rule.** Section headings in both spellings GPO uses --
   ``SEC. n.``/``SECTION n.`` in capitals at the line start, and an
   appropriations general provision's run-in ``    Sec. n.`` at the body
   indent -- plus the ``<DELETED>`` markers that wrap a reported bill's struck
   committee-substitute text; subsections (``(a)`` at the four-space indent, or
   opening on a run-in heading's own line); titles and divisions (their
   banners, with a contents list excluded when a column-0 ``Sec. n.`` line
   follows within three lines); and quoted blocks (a quote-opening line whose
   lead-in ends in ``:``, through the line that closes the quote). Each is
   counted against the XML's own elements as ``parse_bill_tree`` reads them,
   and precision and recall are per kind. Matching is on the enumerator, as a
   multiset, so a bill whose divisions restart section numbering still pairs
   one-to-one; matching on the enumerator cannot see a heading recovered under
   the wrong number when the same number exists elsewhere. A body ``<section>``
   the XML carries with no ``<enum>`` prints no heading at all and is held out
   of the section denominator and counted on its own.
3. **Inventory.** The XML's elements, split into what the engine keeps and what
   ``BillDocument.discarded_elements`` reports, against the HTML's tags and
   the text-only features the HTML carries that the XML never spells (the
   three bracketed banner lines, the enacting clause, the ``<all>`` marker).
4. **Drift before the 113th.** The same rules on ten pre-113th HTML bodies,
   one per Congress from the 103rd to the 112th, with no XML to score against:
   structure counts, a section-number sequence check, and the banner shape.
   Two of the ten are read by hand in the document.

The corpus is thirty pairs chosen by rule from five GovInfo bulk listings
(``SELECTION``): the version codes of each listing in descending file count,
and for each the file at the listing's median size and then its 95th
percentile, six per listing. Thirty documents cannot see a shape that is rare
in the population, and one Congress per pre-113th sample cannot see variation
within a Congress. A credential refusal (401/403 on the keyed route) aborts the
run; the sidecar carries no credential and no URL with one.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from spicy_docs.extraction.body_text import rendition_text
from spicy_docs.reading.markup import read_html_events
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.reading.xml import parse_xml
from spicy_docs.sources.congress.bill_tree import BillDocument, parse_bill_tree
from spicy_docs.sources.congress.listing import CongressListingReader
from spicy_docs.sources.govinfo.bodies import PACKAGE_BODY_FORMATS, package_body_locator, parse_package_id
from spicy_docs.sources.govinfo.error_page import check_not_error_page
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential
from tools.analysis.legislative_data_map import CONGRESS_API, GOVINFO_BULK, JSON_TYPES, KeylessProbe, ProbeError

MARK_START = "<!-- generated by tools/analysis/bill_html_xml_gap.py: start -->"
MARK_END = "<!-- generated by tools/analysis/bill_html_xml_gap.py: end -->"
MAX_REQUESTS = 90
#: ``KeylessProbe`` allows itself two attempts per operation.
PROBE_ATTEMPTS = 2
BODY_MAX_BYTES = 24 * 1024 * 1024
LISTING_MAX_BYTES = 16 * 1024 * 1024
DTD_URL = "https://xml.house.gov/bill.dtd"
DTD_MEDIA_TYPES = ("application/xml-dtd", "text/plain", "text/xml", "application/octet-stream")
#: Where the run's command, its full output and the per-document digests are
#: retained, outside this repository, per AGENTS.md. The JSON sidecar is the
#: committed pin; the receipt is the evidence that produced it.
RECEIPTS = "~/Work/corpora/supply-2026-09-02/receipts/bill-html-xml-gap-2026-09-19/"
REQUESTS: Counter[str] = Counter()


# --- the corpus, as data ----------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """How the paired corpus is drawn: which listings, and which files of each."""

    listings: tuple[tuple[int, int, str], ...]
    quantiles: tuple[float, ...]
    picks_per_listing: int


SELECTION = Selection(
    listings=((113, 1, "hr"), (113, 2, "s"), (113, 1, "hjres"), (114, 2, "hr"), (114, 1, "sres")),
    quantiles=(0.5, 0.95),
    picks_per_listing=6,
)

#: Pre-113th bodies. Two package ids were proved on 2026-09-19 by
#: ``GovInfoBodyAcquirer`` in the PDF-only census (``offered=('htm','pdf')``);
#: the rest are H.R. 1 of each other Congress, whose newest text version is
#: read from the keyed Congress.gov text route so the package id is the
#: publisher's own statement rather than a guess. H.R. 1 because every
#: Congress introduces one and most reach a later printing.
PRE_113_PROVEN = ("BILLS-103hr1enr", "BILLS-109s256enr")
PRE_113_LOOKUPS = tuple((congress, "hr", 1) for congress in (104, 105, 106, 107, 108, 110, 111, 112))


# --- fetching, cached -----------------------------------------------------------------


class RequestBudgetExhausted(RuntimeError):
    """The run reached ``MAX_REQUESTS``; what is cached is measured, the rest is refused."""


def _guarded[Result](client: Any, kind: str, attempts: int, call: Callable[[], Result]) -> Result:
    """One operation against the run's budget, counting every attempt it makes, refusal or not.

    The client retries a transport failure up to its own ``max_requests``, so
    the guard reserves that many before the call and reads the count the
    client reports afterwards, which is the attempts actually made.
    """
    if sum(REQUESTS.values()) + attempts > MAX_REQUESTS:
        raise RequestBudgetExhausted(f"{MAX_REQUESTS}-request budget would be exceeded")
    try:
        return call()
    finally:
        REQUESTS[kind] += client.request_count


def _cached(path: Path, fetch: Callable[[], bytes]) -> bytes:
    if not path.exists():
        body = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return path.read_bytes()


def fetch_listing(probe: KeylessProbe, cache: Path, congress: int, session: int, bill_type: str) -> list[dict]:
    body = _cached(
        cache / "listings" / f"BILLS-{congress}-{session}-{bill_type}.json",
        lambda: _guarded(
            probe,
            "keyless",
            PROBE_ATTEMPTS,
            lambda: (
                probe.get(
                    f"{GOVINFO_BULK}/BILLS/{congress}/{session}/{bill_type}",
                    media_types=JSON_TYPES,
                    max_bytes=LISTING_MAX_BYTES,
                    accept="application/json",
                ).body
            ),
        ),
    )
    return json.loads(body).get("files", [])


def fetch_body(probe: KeylessProbe, cache: Path, package_id: str, rendition: str) -> bytes:
    """One keyless rendition, refused if the publisher answered with its error page."""
    body_format = PACKAGE_BODY_FORMATS[rendition]

    def fetch() -> bytes:
        capture = _guarded(
            probe,
            "keyless",
            PROBE_ATTEMPTS,
            lambda: probe.get(
                package_body_locator(package_id, rendition),
                media_types=body_format.media_types,
                max_bytes=BODY_MAX_BYTES,
            ),
        )
        check_not_error_page(
            capture.body,
            capture.resolved_url,
            error_type=ProbeError,
            message=f"{package_id} {rendition}: govinfo answered its error page",
        )
        return capture.body

    return _cached(cache / "bodies" / f"{package_id}.{body_format.extension}", fetch)


def fetch_text_versions(
    reader: CongressListingReader, cache: Path, congress: int, bill_type: str, number: int
) -> list[Mapping[str, Any]]:
    """The keyed text route's ``textVersions``; the credential travels as a header and is never cached."""

    def fetch() -> bytes:
        page = _guarded(
            reader,
            "keyed",
            reader.budget.max_requests,
            lambda: reader.page(
                f"{CONGRESS_API}/bill/{congress}/{bill_type}/{number}/text?format=json", records_key="textVersions"
            ),
        )
        return json.dumps([dict(row) for row in page.records], indent=1, sort_keys=True, default=str).encode()

    return json.loads(_cached(cache / "text-routes" / f"{congress}-{bill_type}-{number}.json", fetch))


def fetch_dtd(probe: KeylessProbe, cache: Path) -> str | None:
    """The target DTD, so the required elements are read from the schema rather than remembered."""
    try:
        body = _cached(
            cache / "bill.dtd",
            lambda: _guarded(
                probe,
                "keyless",
                PROBE_ATTEMPTS,
                lambda: probe.get(DTD_URL, media_types=DTD_MEDIA_TYPES, max_bytes=1 << 20).body,
            ),
        )
    except (ProbeError, RequestBudgetExhausted):
        return None
    return body.decode(errors="replace")


def stated_package_id(versions: Sequence[Mapping[str, Any]]) -> str | None:
    """The newest version whose stated format URL carries a BILLS package id in its stem."""
    for version in versions:
        for item in version.get("formats") or ():
            url = item.get("url")
            if not isinstance(url, str):
                continue
            stem = Path(urlsplit(url).path).stem
            try:
                parse_package_id(stem)
            except ValueError:
                continue
            return stem
    return None


# --- corpus selection ------------------------------------------------------------------


def _version_code(package_id: str) -> str:
    return parse_package_id(package_id).version or ""


def select_pairs(entries: Iterable[Mapping[str, Any]], selection: Selection = SELECTION) -> list[str]:
    """Package ids from one listing: codes by descending count, the median then the 95th percentile of each."""
    by_code: dict[str, list[tuple[int, str]]] = {}
    for entry in entries:
        if entry.get("fileExtension") != "xml":
            continue
        package_id = str(entry.get("justFileName", "")).removesuffix(".xml")
        try:
            code = _version_code(package_id)
        except ValueError:
            continue
        by_code.setdefault(code, []).append((int(entry.get("size") or 0), package_id))
    codes = sorted(by_code, key=lambda code: (-len(by_code[code]), code))
    picks: list[str] = []
    for quantile in selection.quantiles:
        for code in codes:
            if len(picks) >= selection.picks_per_listing:
                return picks
            files = sorted(by_code[code])
            _, package_id = files[min(len(files) - 1, int(quantile * (len(files) - 1)))]
            if package_id not in picks:
                picks.append(package_id)
    return picks


# --- text fidelity ---------------------------------------------------------------------

_DASHES = re.compile(r"--|[—–]")
_WORD = re.compile(r"[^\W_]+")


def normalized_words(text: str) -> list[str]:
    """The one normalization both sides get: casefold, dashes as separators, word tokens."""
    return _WORD.findall(_DASHES.sub(" ", text.casefold()))


def fidelity(html_words: Sequence[str], xml_words: Sequence[str], *, top: int = 12) -> dict[str, Any]:
    ratio = (
        difflib.SequenceMatcher(None, html_words, xml_words, autojunk=False).ratio()
        if html_words and xml_words
        else 0.0
    )
    html_only = Counter(html_words) - Counter(xml_words)
    xml_only = Counter(xml_words) - Counter(html_words)
    return {
        "ratio": round(ratio, 4),
        "htmlWords": len(html_words),
        "xmlWords": len(xml_words),
        "htmlOnly": {"count": sum(html_only.values()), "top": html_only.most_common(top)},
        "xmlOnly": {"count": sum(xml_only.values()), "top": xml_only.most_common(top)},
    }


# --- structure rules over the HTML rendition's text -------------------------------------

#: GPO's marker for a reported bill's struck committee-substitute text. It is
#: not markup here: GPO escapes it in the ``htm`` rendition, so the markup
#: reader hands it back as text. It wraps a whole provision and sits *outside*
#: that provision's own indentation (``<DELETED>    (a) Amendment.--``), so it
#: is stripped from every line once, before any rule runs, rather than being
#: spelled as an optional prefix and suffix in four separate patterns.
#: Recovering it is what recovers the second ``<legis-body>`` the engine
#: reports for a reported bill.
STRUCK_MARKER = re.compile(r"</?DELETED>")
#: A displayed section heading: ``SEC. 3.`` or ``SECTION 1.`` in capitals at
#: the line start.
SECTION_UPPER = re.compile(r"^(?:SECTION|SEC\.)\s+(\d+[A-Z]?)\.\s*(.*)$")
#: An appropriations general provision, which GPO sets as a run-in at the same
#: four-space indent as body prose: ``    Sec. 1201.  Any appropriations…``.
#: Measured on the paired corpus: every document is either all-uppercase or
#: all-run-in, never both, and the run-in form carries no separate catchline.
SECTION_RUNIN = re.compile(r"^ {4}Sec\.\s+(\d+[A-Z]?)\.\s+(.*)$")
#: A subsection at the ``<pre>`` rendition's four-space indent.
SUBSECTION = re.compile(r"^ {4}\(([a-z]+)\)\s")
#: A subsection opening on the same line as a run-in section heading.
INLINE_SUBSECTION = re.compile(r"^\(([a-z]+)\)\s")
TITLE = re.compile(r"^\s*TITLE\s+([IVXLCDM]+)\b")
DIVISION = re.compile(r"^\s*DIVISION\s+([A-Z]+)\b")
#: A table-of-contents entry, which GPO sets at column 0 with its continuation
#: indented -- the one place ``Sec. n.`` appears outside a provision.
TOC_ENTRY = re.compile(r"^Sec\.\s+\d+[A-Z]?\.\s")
QUOTE_START = re.compile(r'^\s*"')
QUOTE_END = re.compile(r'"[.;,]?(?: (?:and|or))?$')
#: GPO introduces block amendment payload with a colon (``…by inserting the
#: following:``) and a blank line. The lead-in is what separates a block from
#: an inline quoted term, which the XML spells ``<quote>``, not
#: ``<quoted-block>`` -- and only a block may run past its own line. Measured:
#: a line merely *opening* with a quote is ordinary prose naming two quoted
#: account titles, and letting it open a span swallowed five section headings
#: of BILLS-113hjres91enr before a later line happened to close it.
QUOTE_LEAD_IN = re.compile(r":$")
#: Where a document's body begins when it states no numbered section: the
#: enacting or resolving clause. A simple resolution has no section heading at
#: all, and anchoring its body at the top of the file would compare its whole
#: printed preamble against a ``resolution-body`` that starts after the clause.
RESOLVING_CLAUSE = re.compile(r"^\s*(?:Be it enacted|Resolved)\b")
BANNER = re.compile(r"^\[.*\]$")
RULE_LINE = re.compile(r"^_{10,}$")
PAGE_MARKER = re.compile(r"\[\[Page \d+\]\]")
HEADER_CONTINUATION = re.compile(r"^ {6,}\S")
#: DeltaTrack's ``_valid_subsection_enum`` rejects these as roman lookalikes
#: when it has only the enumerator to go on; the indent rule does not need to.
ROMAN_LOOKALIKES = re.compile(r"^(?:[ivx]|[a-z]{2})$")
TOC_WINDOW = 3


@dataclass
class HtmlStructure:
    """What the rules found in one HTML body."""

    sections: list[tuple[str, str]] = field(default_factory=list)
    subsections: list[tuple[str, str]] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    divisions: list[str] = field(default_factory=list)
    quoted_blocks: int = 0
    toc_banners: int = 0
    toc_entries: int = 0
    roman_subsections: int = 0
    inline_enum_headings: int = 0
    runin_sections: int = 0
    struck_sections: int = 0
    quote_terms: int = 0
    banners: list[str] = field(default_factory=list)
    markers: dict[str, int] = field(default_factory=dict)
    first_heading_line: int | None = None
    resolving_clause_line: int | None = None

    @property
    def body_start(self) -> int:
        """The line the printed body begins on: its first section heading, else its resolving clause."""
        for candidate in (self.first_heading_line, self.resolving_clause_line):
            if candidate is not None:
                return candidate
        return 0

    def counts(self) -> dict[str, int]:
        return {
            "section": len(self.sections),
            "subsection": len(self.subsections),
            "title": len(self.titles),
            "division": len(self.divisions),
            "quotedBlock": self.quoted_blocks,
        }


def _is_toc_banner(lines: Sequence[str], index: int) -> bool:
    """Whether this TITLE or DIVISION banner is a contents-list entry rather than the real thing.

    The witness is a column-0 ``Sec. n.`` entry close below it. Other banners
    in between do not end the search and do not spend the window: a contents
    list sets every level it covers, so a DIVISION banner is routinely followed
    by its TITLE banners before the first section entry, and counting those
    against the window is what let a contents list's own divisions through as
    real ones.
    """
    seen = 0
    for line in lines[index + 1 :]:
        if not line.strip() or TITLE.match(line) or DIVISION.match(line):
            continue
        if TOC_ENTRY.match(line):
            return True
        seen += 1
        if seen >= TOC_WINDOW:
            break
    return False


def _section_header(lines: Sequence[str], index: int, first: str) -> str:
    parts = [first]
    for line in lines[index + 1 :]:
        stripped = line.strip()
        if not stripped or not HEADER_CONTINUATION.match(line) or any(c.islower() for c in stripped):
            break
        parts.append(stripped)
    return " ".join(parts).rstrip(".").strip()


def _is_section_line(line: str) -> bool:
    """Whether a line is a section heading in either spelling; the quote span's stop rule."""
    return bool(SECTION_UPPER.match(line) or SECTION_RUNIN.match(line))


def scan_html(text: str) -> HtmlStructure:
    """One pass over the lines; ``O(L)`` for ``L`` lines plus the bounded TOC look-ahead.

    Order is load-bearing. A quoted line is settled first, because amendment
    payload spells every structure this document does and belongs to the law
    being amended, not to this bill -- the same self-exclusion DeltaTrack's own
    anchor matcher makes. A table-of-contents entry is settled next, so a
    contents list never contributes a section.

    ``<DELETED>`` markers come off every line before any rule runs, so a struck
    provision is read exactly like a live one and is only *counted* apart.
    """
    raw = text.split("\n")
    struck_lines = [STRUCK_MARKER.search(line) is not None for line in raw]
    lines = [STRUCK_MARKER.sub("", line) for line in raw]
    found = HtmlStructure()
    section = ""
    in_quote = False
    at_top = True
    previous = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # The banners are the bracketed lines before anything else; a
        # bracketed line further down is content.
        if at_top and BANNER.match(stripped):
            found.banners.append(stripped)
            continue
        at_top = False
        if RULE_LINE.match(stripped):
            found.markers["ruleLine"] = found.markers.get("ruleLine", 0) + 1
        if stripped == "<all>":
            found.markers["<all>"] = found.markers.get("<all>", 0) + 1
        found.markers["[[Page]]"] = found.markers.get("[[Page]]", 0) + len(PAGE_MARKER.findall(line))
        if found.resolving_clause_line is None and RESOLVING_CLAUSE.match(line):
            found.resolving_clause_line = index
        if in_quote:
            # A block ends at its closing quote, or at the next unquoted
            # section heading -- amendment payload never continues through one,
            # and without that stop a block whose close is missed runs to the
            # end of the document. The heading itself is then read normally.
            if not _is_section_line(line):
                in_quote = not QUOTE_END.search(stripped)
                previous = stripped
                continue
            in_quote = False
        elif QUOTE_START.match(line):
            # Only a block opened by GPO's ``:`` lead-in spans lines; a line
            # merely opening with a quote is prose carrying a quoted term.
            if QUOTE_LEAD_IN.search(previous):
                found.quoted_blocks += 1
                in_quote = not QUOTE_END.search(stripped)
            else:
                found.quote_terms += 1
            previous = stripped
            continue
        if TOC_ENTRY.match(line):
            found.toc_entries += 1
        elif (match := SECTION_UPPER.match(line)) or (runin := SECTION_RUNIN.match(line)):
            number, rest = (match[1], match[2]) if match else (runin[1], runin[2])
            section = number
            if found.first_heading_line is None:
                found.first_heading_line = index
            found.struck_sections += struck_lines[index]
            found.runin_sections += match is None
            # The uppercase form sets its catchline on the heading line and
            # may wrap; the run-in form has none, its text starts immediately.
            header = _section_header(lines, index, rest) if match else ""
            if inline := INLINE_SUBSECTION.match(rest):
                found.inline_enum_headings += 1
                found.subsections.append((number, inline[1]))
            found.sections.append((section, header))
        elif match := SUBSECTION.match(line):
            found.subsections.append((section, match[1]))
            if ROMAN_LOOKALIKES.match(match[1]):
                found.roman_subsections += 1
        elif match := DIVISION.match(line):
            if _is_toc_banner(lines, index):
                found.toc_banners += 1
            else:
                found.divisions.append(match[1])
        elif match := TITLE.match(line):
            if _is_toc_banner(lines, index):
                found.toc_banners += 1
            else:
                found.titles.append(match[1])
        previous = stripped
    found.markers = {name: count for name, count in found.markers.items() if count}
    return found


def sequence_check(numbers: Sequence[str]) -> dict[str, int]:
    """How often a detected section number fails to advance; restarts under a new division are expected."""
    previous = 0
    non_increasing = 0
    for number in numbers:
        value = int(re.match(r"\d+", number)[0])
        if value <= previous:
            non_increasing += 1
        previous = value
    return {"nonIncreasing": non_increasing, "duplicates": sum(count - 1 for count in Counter(numbers).values())}


# --- the XML reference ------------------------------------------------------------------

_XML_BODIES = ("legis-body", "resolution-body", "engrossed-amendment-body")
_SECTION_NUMBER = re.compile(r"^Sec\.\s*(\S+)")
_ENUM = re.compile(r"^\(([a-z]+)\)")
_TITLE_LABEL = re.compile(r"^TITLE\s+(\S+?)(?:[—–—]|$)")
_DIVISION_LABEL = re.compile(r"^Division\s+(\S+?):?(?:\s|$)")


@dataclass(frozen=True)
class XmlStructure:
    """The engine's nodes in the keys the HTML rules produce.

    ``unnumbered_sections`` are body ``<section>`` elements the engine emits
    with no ``<enum>``: a resolution's resolving-clause body and a trailing
    short-title section. They print with **no heading of any kind**, so they
    are held apart from ``sections`` rather than counted as headings the rules
    missed -- a heading rule cannot find what was never set as a heading. What
    that separation cannot see is whether a boundary rule would place them
    correctly; nothing here tests one.
    """

    sections: list[tuple[str, str]]
    unnumbered_sections: int
    subsections: list[tuple[str, str]]
    titles: list[str]
    divisions: list[str]
    quoted_blocks: int

    def counts(self) -> dict[str, int]:
        return {
            "section": len(self.sections),
            "unnumberedSection": self.unnumbered_sections,
            "subsection": len(self.subsections),
            "title": len(self.titles),
            "division": len(self.divisions),
            "quotedBlock": self.quoted_blocks,
        }


def _section_number(node: Any) -> str:
    match = _SECTION_NUMBER.match(node.section_number or "")
    return (match[1] if match else node.section_number or "").rstrip(".")


def xml_structure(document: BillDocument) -> XmlStructure:
    """What the engine's own nodes say the document holds, in the same keys the HTML rules produce."""
    sections: list[tuple[str, str]] = []
    unnumbered = 0
    subsections: list[tuple[str, str]] = []
    titles: dict[tuple[str, str], None] = {}
    divisions: dict[str, None] = {}
    for node in document.sections:
        if node.tag == "section":
            number = _section_number(node)
            if number:
                sections.append((number, " ".join(node.header_text.split())))
            else:
                unnumbered += 1
        elif node.tag == "subsection":
            enum = _ENUM.match(node.display_path[-1] if node.display_path else "")
            if enum:
                subsections.append((_section_number(node), enum[1]))
        for label in node.display_path[:-1]:
            if _TITLE_LABEL.match(label):
                titles.setdefault((node.division_label, label))
        if node.division_label:
            divisions.setdefault(node.division_label)
    title_enums = [m[1] for _, label in titles if (m := _TITLE_LABEL.match(label))]
    division_enums = [m[1] for label in divisions if (m := _DIVISION_LABEL.match(label))]
    return XmlStructure(
        sections, unnumbered, subsections, title_enums, division_enums, document.element_counts.get("quoted-block", 0)
    )


#: Elements whose text the reconstruction has to place somewhere, whether the
#: DTD requires them (``form``'s children) or only permits them
#: (``metadata/dublinCore``). Read from the document, so an element a file does
#: not carry is never scored.
_FRONT_MATTER_PARENTS = ("form", "metadata")
#: Attributes that are identifiers or rendering instructions rather than text.
#: A print rendition has no place to put any of them, which is what makes them
#: the profile's generated-value problem.
IDENTIFIER_ATTRIBUTES = (
    "id",
    "dms-id",
    "name-id",
    "committee-id",
    "bill-type",
    "public-private",
    "key",
    "style",
    "display",
    "display-inline",
    "date",
    "section-type",
)


def _contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """Whether the normalized word sequence appears contiguously; ``O(len(haystack))`` per call."""
    if not needle:
        return False
    first, span = needle[0], len(needle)
    return any(
        haystack[index : index + span] == list(needle)
        for index, word in enumerate(haystack)
        if word == first and index + span <= len(haystack)
    )


def front_matter_coverage(xml_bytes: bytes, html_words: Sequence[str]) -> dict[str, bool]:
    """For each front-matter element the XML carries, whether the HTML prints its words.

    The test is one-directional on purpose and says so: finding the words in the
    print proves the reconstruction *could* place them, not that a rule would
    pick the right span. Not finding them proves the print does not carry the
    element at all, which is the direction that decides what has to be marked
    generated.
    """
    root = parse_xml(
        xml_bytes, max_bytes=BODY_MAX_BYTES, error_type=ProbeError, label="bill XML", allow_external_doctype=True
    )
    found: dict[str, bool] = {}
    for parent_tag in _FRONT_MATTER_PARENTS:
        for parent in root.iter(parent_tag):
            for element in parent.iter():
                if element is parent:
                    continue
                words = normalized_words("".join(element.itertext()))
                if words:
                    name = _local_name(element.tag)
                    found[name] = found.get(name, False) or _contains(html_words, words)
    return found


def identifier_coverage(xml_bytes: bytes, html_text: str) -> dict[str, dict[str, int]]:
    """Distinct values of each identifier attribute, and how many appear anywhere in the print."""
    root = parse_xml(
        xml_bytes, max_bytes=BODY_MAX_BYTES, error_type=ProbeError, label="bill XML", allow_external_doctype=True
    )
    values: dict[str, set[str]] = {}
    for element in root.iter():
        for name, value in element.attrib.items():
            if _local_name(name) in IDENTIFIER_ATTRIBUTES and value:
                values.setdefault(_local_name(name), set()).add(value)
    return {
        name: {"distinct": len(found), "inHtml": sum(1 for value in found if value in html_text)}
        for name, found in sorted(values.items())
    }


def xml_body_text(xml_bytes: bytes) -> str:
    """The body elements' text, one chunk per line so a header never runs into the text after it."""
    root = parse_xml(
        xml_bytes, max_bytes=BODY_MAX_BYTES, error_type=ProbeError, label="bill XML", allow_external_doctype=True
    )
    return "\n".join(chunk for tag in _XML_BODIES for body in root.iter(tag) for chunk in body.itertext())


# --- scoring ------------------------------------------------------------------------------


def agreement(matched: int, found: int, reference: int) -> dict[str, Any]:
    """Precision is of what the rules found, recall of what the XML holds; ``None`` where there is nothing to divide."""
    return {
        "html": found,
        "xml": reference,
        "matched": matched,
        "precision": round(matched / found, 4) if found else None,
        "recall": round(matched / reference, 4) if reference else None,
    }


def precision_recall(found: Sequence[Any], reference: Sequence[Any]) -> dict[str, Any]:
    """Multiset agreement on the key, so a repeated enumerator pairs only as often as both sides carry it."""
    return agreement(sum((Counter(found) & Counter(reference)).values()), len(found), len(reference))


def _header_agreement(html: HtmlStructure, xml: XmlStructure) -> dict[str, int]:
    """Among sections paired by number, how many headings read the same once casefolded."""
    xml_headers: dict[str, list[str]] = {}
    for number, header in xml.sections:
        xml_headers.setdefault(number, []).append(" ".join(normalized_words(header)))
    agreed = compared = 0
    for number, header in html.sections:
        candidates = xml_headers.get(number)
        if not candidates:
            continue
        compared += 1
        if " ".join(normalized_words(header)) in candidates:
            agreed += 1
    return {"compared": compared, "agreed": agreed}


#: What each rule saw beyond its own count, so a number in the tables can be
#: traced to the print convention that produced it.
OBSERVATIONS = (
    ("runinSections", "a run-in `Sec. n.` heading at the appropriations indent"),
    ("struckSections", "a heading inside GPO's `<DELETED>` markers (a reported bill's struck text)"),
    ("tocEntries", "a table-of-contents entry at column 0, excluded from every count"),
    ("tocBanners", "a TITLE or DIVISION banner inside a contents list, excluded"),
    ("quoteTerms", "a quote-opening line with no `:` lead-in, read as an inline term, not a block"),
    ("romanSubsections", "a subsection the indent rule kept that an enumerator-only rule calls a roman lookalike"),
    ("inlineEnumHeadings", "a subsection opening on its section's own heading line"),
)


def _observations(html: HtmlStructure) -> dict[str, int]:
    return {
        "runinSections": html.runin_sections,
        "struckSections": html.struck_sections,
        "tocEntries": html.toc_entries,
        "tocBanners": html.toc_banners,
        "quoteTerms": html.quote_terms,
        "romanSubsections": html.roman_subsections,
        "inlineEnumHeadings": html.inline_enum_headings,
    }


def measure_pair(package_id: str, xml_bytes: bytes, html_bytes: bytes) -> dict[str, Any]:
    """Everything one paired document yields; no request, no file."""
    identity = parse_package_id(package_id)
    document = parse_bill_tree(xml_bytes, version=identity.version or "")
    xml_text = rendition_text(xml_bytes, rendition="xml").text
    html_text = rendition_text(html_bytes, rendition="htm").text
    html = scan_html(html_text)
    xml = xml_structure(document)
    html_words = normalized_words(html_text)
    html_lines = html_text.split("\n")
    body_start = html.body_start
    body_html = "\n".join(html_lines[body_start:])
    tags = sorted({event.name for event in read_html_events(html_bytes).events if event.kind in ("start", "empty")})
    return {
        "packageId": package_id,
        "congress": identity.congress,
        "billType": identity.document_type,
        "version": identity.version,
        "stage": document.stage,
        "rootTag": document.root_tag,
        "xmlBytes": len(xml_bytes),
        "htmlBytes": len(html_bytes),
        "xmlSha256": hashlib.sha256(xml_bytes).hexdigest(),
        "htmlSha256": hashlib.sha256(html_bytes).hexdigest(),
        "fidelity": fidelity(html_words, normalized_words(xml_text)),
        "bodyFidelity": fidelity(normalized_words(body_html), normalized_words(xml_body_text(xml_bytes))),
        "frontMatter": front_matter_coverage(xml_bytes, html_words),
        "identifiers": identifier_coverage(xml_bytes, html_text),
        "structure": {
            "section": precision_recall([n for n, _ in html.sections], [n for n, _ in xml.sections]),
            "subsection": precision_recall(html.subsections, xml.subsections),
            "title": precision_recall(html.titles, xml.titles),
            "division": precision_recall(html.divisions, xml.divisions),
            # Quoted blocks have no enumerator to pair on, so this is agreement
            # of counts: it cannot see one block found where another was missed.
            "quotedBlock": agreement(min(html.quoted_blocks, xml.quoted_blocks), html.quoted_blocks, xml.quoted_blocks),
        },
        "headerAgreement": _header_agreement(html, xml),
        "sequence": sequence_check([n for n, _ in html.sections]),
        "unnumberedSections": xml.unnumbered_sections,
        "observations": _observations(html),
        "banners": html.banners,
        "markers": html.markers,
        "htmlTags": tags,
        "xmlElements": dict(document.element_counts),
        "discardedElements": dict(document.discarded_elements),
    }


def measure_html_only(package_id: str, html_bytes: bytes) -> dict[str, Any]:
    identity = parse_package_id(package_id)
    html = scan_html(rendition_text(html_bytes, rendition="htm").text)
    return {
        "packageId": package_id,
        "congress": identity.congress,
        "billType": identity.document_type,
        "version": identity.version,
        "htmlBytes": len(html_bytes),
        "htmlSha256": hashlib.sha256(html_bytes).hexdigest(),
        "structure": html.counts(),
        "sequence": sequence_check([n for n, _ in html.sections]),
        "observations": _observations(html),
        "banners": html.banners,
        "markers": html.markers,
    }


# --- aggregates ------------------------------------------------------------------------

KINDS = ("section", "subsection", "title", "division", "quotedBlock")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def aggregate(paired: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"documents": len(paired), "structure": {}, "fidelity": {}, "inventory": {}}
    for kind in KINDS:
        rows = [doc["structure"][kind] for doc in paired]
        html, xml, matched = (sum(row[key] for row in rows) for key in ("html", "xml", "matched"))
        precisions = [row["precision"] for row in rows if row["precision"] is not None]
        recalls = [row["recall"] for row in rows if row["recall"] is not None]
        out["structure"][kind] = {
            "html": html,
            "xml": xml,
            "matched": matched,
            "microPrecision": round(matched / html, 4) if html else None,
            "microRecall": round(matched / xml, 4) if xml else None,
            "macroPrecision": round(statistics.fmean(precisions), 4) if precisions else None,
            "macroRecall": round(statistics.fmean(recalls), 4) if recalls else None,
            "documentsWithKind": sum(1 for row in rows if row["xml"]),
            "documentsExact": sum(1 for row in rows if row["html"] == row["xml"] == row["matched"] and row["xml"]),
        }
    for key in ("fidelity", "bodyFidelity"):
        ratios = [doc[key]["ratio"] for doc in paired]
        html_only: Counter[str] = Counter()
        xml_only: Counter[str] = Counter()
        for doc in paired:
            html_only.update(dict(doc[key]["htmlOnly"]["top"]))
            xml_only.update(dict(doc[key]["xmlOnly"]["top"]))
        out["fidelity"][key] = {
            "mean": round(statistics.fmean(ratios), 4) if ratios else None,
            "median": round(statistics.median(ratios), 4) if ratios else None,
            "min": min(ratios) if ratios else None,
            "htmlOnlyTop": html_only.most_common(20),
            "xmlOnlyTop": xml_only.most_common(20),
        }
    headers = [doc["headerAgreement"] for doc in paired]
    out["headerAgreement"] = {
        "compared": sum(row["compared"] for row in headers),
        "agreed": sum(row["agreed"] for row in headers),
    }
    present: Counter[str] = Counter()
    discarded: Counter[str] = Counter()
    for doc in paired:
        present.update({_local_name(tag) for tag in doc["xmlElements"]})
        discarded.update({_local_name(tag) for tag, count in doc["discardedElements"].items() if count})
    out["unnumberedSections"] = sum(doc["unnumberedSections"] for doc in paired)
    out["observations"] = {name: sum(doc["observations"][name] for doc in paired) for name, _ in OBSERVATIONS}
    carried: Counter[str] = Counter()
    printed: Counter[str] = Counter()
    for doc in paired:
        for name, in_html in doc["frontMatter"].items():
            carried[name] += 1
            printed[name] += in_html
    out["frontMatter"] = {
        name: {"documents": carried[name], "inHtml": printed[name]}
        for name in sorted(carried, key=lambda n: -carried[n])
    }
    identifiers: dict[str, dict[str, int]] = {}
    for doc in paired:
        for name, counts in doc["identifiers"].items():
            row = identifiers.setdefault(name, {"documents": 0, "distinct": 0, "inHtml": 0})
            row["documents"] += 1
            row["distinct"] += counts["distinct"]
            row["inHtml"] += counts["inHtml"]
    out["identifiers"] = dict(sorted(identifiers.items(), key=lambda item: -item[1]["distinct"]))
    out["inventory"] = {
        "xmlElementsByDocuments": dict(present.most_common()),
        "discardedByDocuments": dict(discarded.most_common()),
        "htmlTags": sorted({tag for doc in paired for tag in doc["htmlTags"]}),
        "bannerLines": {str(n): count for n, count in sorted(Counter(len(doc["banners"]) for doc in paired).items())},
        "markers": dict(sum((Counter(doc["markers"]) for doc in paired), Counter())),
    }
    return out


_DTD_ELEMENT = re.compile(r"<!ELEMENT\s+(bill|form|metadata|dublinCore|legis-body|section)\s+(.*?)>", re.DOTALL)
_DTD_ENTITY = re.compile(r"<!ENTITY\s+%\s+form-model\s+\"(.*?)\"", re.DOTALL)
_DTD_PARTICLE = re.compile(r"([A-Za-z][\w:.-]*)\s*([?*+]?)")


def dtd_content_models(dtd: str | None) -> dict[str, str]:
    """The content models the profile has to satisfy, as the DTD spells them."""
    if not dtd:
        return {}
    return {name: " ".join(model.split()) for name, model in _DTD_ELEMENT.findall(dtd)}


def dtd_form_particles(dtd: str | None) -> dict[str, bool]:
    """Each ``<form>`` child the DTD names, and whether it is required there.

    Read from the DTD's own ``%form-model;`` entity rather than from a list
    kept here, so the requirement the profile must satisfy is the publisher's
    statement and moves when the publisher's does.
    """
    entity = _DTD_ENTITY.search(dtd or "")
    if entity is None:
        return {}
    return {name: occurrence not in ("?", "*") for name, occurrence in _DTD_PARTICLE.findall(entity[1])}


# --- rendering -----------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _pr(row: Mapping[str, Any]) -> str:
    return f"{row['matched']}/{row['html']}/{row['xml']}"


def _words(pairs: Sequence[Sequence[Any]], limit: int = 12) -> str:
    return ", ".join(f"`{word}`×{count}" for word, count in pairs[:limit]) or "—"


def render(measures: Mapping[str, Any]) -> str:
    paired = measures.get("paired", [])
    pre = measures.get("pre113", [])
    agg = measures.get("aggregate") or aggregate(paired)
    requests = measures.get("requests", {})
    lines = [
        MARK_START,
        "",
        (
            f"Measured {measures.get('generatedAt', '')[:10]} by `tools/analysis/bill_html_xml_gap.py` at spicy-docs "
            f"`{measures.get('revision', 'unknown')}`; "
            f"{requests.get('cumulative', requests.get('total', 0))} publisher requests to build this corpus, "
            f"{len(paired)} paired documents, {len(pre)} pre-113th HTML bodies. "
            "Per-kind cells read `matched/found in HTML/in XML`. The command, the run's full output and every "
            f"document's digest are retained outside this repository in `{RECEIPTS}`; this document's sidecar "
            "`bill-html-xml-gap-2026-09-19.json` is the committed pin."
        ),
        "",
        "### Paired corpus: fidelity and structure per document",
        "",
        "| Package | Stage | XML B | HTML B | Ratio | Body ratio | HTML-only | XML-only | Sections | Unnum. | Subsections | Titles | Divisions | Quoted | Headers agree |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|---|---|---|",
    ]
    for doc in paired:
        s = doc["structure"]
        lines.append(
            f"| `{doc['packageId']}` | {doc['version']} | {doc['xmlBytes']:,} | {doc['htmlBytes']:,} | "
            f"{_pct(doc['fidelity']['ratio'])} | {_pct(doc['bodyFidelity']['ratio'])} | "
            f"{doc['fidelity']['htmlOnly']['count']} | {doc['fidelity']['xmlOnly']['count']} | "
            f"{_pr(s['section'])} | {doc['unnumberedSections']} | {_pr(s['subsection'])} | {_pr(s['title'])} | "
            f"{_pr(s['division'])} | {_pr(s['quotedBlock'])} | "
            f"{doc['headerAgreement']['agreed']}/{doc['headerAgreement']['compared']} |"
        )
    lines += [
        "",
        "### Structure recovered by rule, over the paired corpus",
        "",
        "| Kind | Found in HTML | In XML | Matched | Micro precision | Micro recall | Macro precision | Macro recall | Docs with kind | Docs exact |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for kind in KINDS:
        row = agg["structure"][kind]
        lines.append(
            f"| {kind} | {row['html']} | {row['xml']} | {row['matched']} | {_pct(row['microPrecision'])} | "
            f"{_pct(row['microRecall'])} | {_pct(row['macroPrecision'])} | {_pct(row['macroRecall'])} | "
            f"{row['documentsWithKind']} | {row['documentsExact']} |"
        )
    inv = agg["inventory"]
    header = agg["headerAgreement"]
    lines += [
        "",
        (
            f"Section headings paired by number whose text agrees once casefolded: {header['agreed']} of "
            f"{header['compared']}. Body `<section>` elements the XML carries with no `<enum>`, which print with no "
            f"heading and so are held out of the section denominator: {agg['unnumberedSections']}."
        ),
        "",
        "What each rule saw, over the paired corpus:",
        "",
        "| Observation | Count |",
        "|---|---:|",
    ]
    lines += [f"| {label} | {agg['observations'][name]} |" for name, label in OBSERVATIONS]
    lines += [
        "",
        "### Text fidelity",
        "",
        "| Scope | Mean ratio | Median | Min | Words only the HTML has (top) | Words only the XML has (top) |",
        "|---|---:|---:|---:|---|---|",
    ]
    for key, label in (("fidelity", "whole document"), ("bodyFidelity", "body only")):
        row = agg["fidelity"][key]
        lines.append(
            f"| {label} | {_pct(row['mean'])} | {_pct(row['median'])} | {_pct(row['min'])} | "
            f"{_words(row['htmlOnlyTop'])} | {_words(row['xmlOnlyTop'])} |"
        )
    lines += [
        "",
        "### Inventory: what each rendition carries",
        "",
        (
            f"HTML tags across the corpus: {', '.join(f'`{t}`' for t in inv['htmlTags'])}. Bracketed banner lines per "
            f"document: {inv['bannerLines']}. Text-only markers: {inv['markers'] or 'none'}."
        ),
        "",
        "| XML element | Documents | Engine keeps its text | Documents where dropped |",
        "|---|---:|---|---:|",
    ]
    for tag, count in inv["xmlElementsByDocuments"].items():
        dropped = inv["discardedByDocuments"].get(tag, 0)
        keeps = "no" if dropped == count else ("partly" if dropped else "yes")
        lines.append(f"| `{tag}` | {count} | {keeps} | {dropped} |")
    models = measures.get("dtdContentModels") or {}
    particles = measures.get("dtdFormParticles") or {}
    if models:
        lines += ["", "### The bill DTD's content models the profile must satisfy", ""]
        for name, model in models.items():
            lines.append(f"- `{name}`: `{model}`")
    front = agg.get("frontMatter") or {}
    if front:
        lines += [
            "",
            "### Front matter: what the DTD asks for and what the print carries",
            "",
            (
                "`Required` is the DTD's own `%form-model;`. `Print carries it` counts the documents whose HTML "
                "holds that element's words contiguously; it proves the words are available to place, not that a "
                "rule would choose the right span."
            ),
            "",
            "| Element | In XML | Print carries it | DTD requires it in `form` |",
            "|---|---:|---:|---|",
        ]
        for name, row in front.items():
            required = particles.get(name)
            mark = "—" if required is None else ("required" if required else "optional")
            lines.append(f"| `{name}` | {row['documents']} | {row['inHtml']} | {mark} |")
    identifiers = agg.get("identifiers") or {}
    if identifiers:
        lines += [
            "",
            "Identifiers and rendering attributes, which a print rendition has nowhere to put:",
            "",
            "| Attribute | Documents | Distinct values | Found in the print |",
            "|---|---:|---:|---:|",
        ]
        for name, row in identifiers.items():
            lines.append(f"| `{name}` | {row['documents']} | {row['distinct']} | {row['inHtml']} |")
    lines += [
        "",
        "### Pre-113th HTML: the same rules with no XML reference",
        "",
        "| Package | Congress | Bytes | Sections | Run-in | Non-incr. | Dup. | Subsections | Titles | Divisions | Quoted | TOC entries | TOC banners | Banners | Markers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for doc in pre:
        s, o = doc["structure"], doc["observations"]
        lines.append(
            f"| `{doc['packageId']}` | {doc['congress']} | {doc['htmlBytes']:,} | {s['section']} | "
            f"{o['runinSections']} | {doc['sequence']['nonIncreasing']} | {doc['sequence']['duplicates']} | "
            f"{s['subsection']} | {s['title']} | {s['division']} | {s['quotedBlock']} | {o['tocEntries']} | "
            f"{o['tocBanners']} | {len(doc['banners'])} | {doc['markers'] or '—'} |"
        )
    refused = measures.get("refused", [])
    if refused:
        lines += ["", "Refused or unavailable: " + "; ".join(f"`{r['packageId']}` ({r['reason']})" for r in refused)]
    lines += ["", MARK_END]
    return "\n".join(lines)


def rewrite_doc(path: Path, block: str) -> None:
    text = path.read_text()
    start, end = text.find(MARK_START), text.find(MARK_END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(f"{path} lacks the generated-block markers")
    path.write_text(text[:start] + block + text[end + len(MARK_END) :])


# --- main ------------------------------------------------------------------------------------


def _revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


def _refusal(package_id: str, error: Exception, api_key: str) -> dict[str, str]:
    return {"packageId": package_id, "reason": scrub_credential(f"{type(error).__name__}: {error}", api_key)[:200]}


def measure(cache: Path, api_key: str, *, timeout: float, interval: float) -> dict[str, Any]:
    measures: dict[str, Any] = {"paired": [], "pre113": [], "refused": []}
    budget = PagedJsonBudget(
        max_requests=3, max_page_bytes=4 * 1024 * 1024, timeout_seconds=timeout, min_request_interval_seconds=interval
    )
    with (
        KeylessProbe(timeout_seconds=timeout, min_request_interval_seconds=interval) as probe,
        CongressListingReader(budget=budget, api_key=api_key) as congress,
    ):
        pairs: list[str] = []
        for congress_number, session, bill_type in SELECTION.listings:
            pairs.extend(select_pairs(fetch_listing(probe, cache, congress_number, session, bill_type)))
        measures["selection"] = {**asdict(SELECTION), "pairs": pairs}
        for package_id in pairs:
            try:
                xml_bytes = fetch_body(probe, cache, package_id, "xml")
                html_bytes = fetch_body(probe, cache, package_id, "htm")
                measures["paired"].append(measure_pair(package_id, xml_bytes, html_bytes))
                print(f"paired {package_id}: {measures['paired'][-1]['fidelity']['ratio']}", file=sys.stderr)
            except (ProbeError, ValueError, RequestBudgetExhausted) as error:
                measures["refused"].append(_refusal(package_id, error, api_key))
                print(f"refused {package_id}: {error}", file=sys.stderr)
        pre_ids: list[str] = list(PRE_113_PROVEN)
        for congress_number, bill_type, number in PRE_113_LOOKUPS:
            try:
                stated = stated_package_id(fetch_text_versions(congress, cache, congress_number, bill_type, number))
            except (ProbeError, ValueError, RequestBudgetExhausted) as error:
                measures["refused"].append(_refusal(f"{congress_number} {bill_type} {number}", error, api_key))
                continue
            if stated:
                pre_ids.append(stated)
            else:
                measures["refused"].append(
                    {"packageId": f"{congress_number} {bill_type} {number}", "reason": "no stated BILLS package id"}
                )
        measures["selection"]["pre113"] = pre_ids
        for package_id in pre_ids:
            try:
                measures["pre113"].append(measure_html_only(package_id, fetch_body(probe, cache, package_id, "htm")))
            except (ProbeError, ValueError, RequestBudgetExhausted) as error:
                measures["refused"].append(_refusal(package_id, error, api_key))
        dtd = fetch_dtd(probe, cache)
        measures["dtdContentModels"] = dtd_content_models(dtd)
        measures["dtdFormParticles"] = dtd_form_particles(dtd)
    measures["aggregate"] = aggregate(measures["paired"])
    return measures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output", type=Path, required=True, help="measurement JSON; read instead of measured with --offline"
    )
    parser.add_argument(
        "--doc", type=Path, required=True, help="the research document whose generated block is rewritten"
    )
    parser.add_argument("--cache", type=Path, help="where fetched bytes live; reused on a rerun")
    parser.add_argument("--env-file", type=Path, help="file holding the api.data.gov key")
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--min-interval-seconds", type=float, default=0.3)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if args.offline:
        measures = json.loads(args.output.read_text())
    else:
        if args.env_file is None or args.cache is None:
            parser.error("--env-file and --cache are required unless --offline")
        api_key = read_api_key(args.env_file, args.env_var)
        try:
            measures = measure(args.cache, api_key, timeout=args.timeout, interval=args.min_interval_seconds)
        except CredentialRefusedError as error:
            print(f"credential refused; stopping: {scrub_credential(str(error), api_key)}", file=sys.stderr)
            return 1
        measures["generatedAt"] = datetime.now(UTC).isoformat()
        measures["revision"] = _revision(root)
        # A rerun against a full cache makes no request, which would report a
        # corpus that cost nothing. The cumulative figure is what the
        # measurement actually spent at the publisher, and it is the one the
        # document states.
        previous = json.loads(args.output.read_text()).get("requests", {}) if args.output.exists() else {}
        measures["requests"] = {
            **REQUESTS,
            "total": sum(REQUESTS.values()),
            "cumulative": int(previous.get("cumulative") or previous.get("total") or 0) + sum(REQUESTS.values()),
        }
        text = json.dumps(measures, indent=2, sort_keys=True) + "\n"
        if api_key in text or "api_key=" in text or "X-Api-Key" in text:
            raise SystemExit("refusing to write a sidecar that carries a credential")
        args.output.write_text(text)
        # Render from the bytes just written, so a later --offline run and the
        # fixture test produce the same block from the same JSON shapes.
        measures = json.loads(text)
    rewrite_doc(args.doc, render(measures))
    print(json.dumps({"output": str(args.output), "doc": str(args.doc), "requests": measures.get("requests")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
