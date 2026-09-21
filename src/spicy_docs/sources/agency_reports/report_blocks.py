"""Split committee-report text into header-led blocks; a pure, dependency-free port of BillTrax's report-parser.ts.

Despite its name this is a heading splitter, not an agency detector: all-caps section titles
(``REPORT``, ``R E P O R T``, ``C O N T E N T S``, ``HURRICANE SANDY``) fire exactly as often as
``DEPARTMENT OF THE ARMY``, so a block's ``agency`` field is not a verified agency name and the
table shaper leaves agency identity columns NULL. Input must already be normalized (GPO line
numbers, ``VerDate``/``DSK`` footers and hyphenated line-wrap rejoining applied); feeding raw
extraction text reproduces BillTrax's hyphen-wrap fragments, so a line is never treated as a header
when the line immediately before it ends with a word character followed by a hyphen.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from spicy_docs.extraction.model import PageResult

# BillTrax's isAgencyHeader() length gate (report-parser.ts:23); applied before
# any pattern is tried, and to every line, headers included.
MIN_HEADER_CHARS = 5
MAX_HEADER_CHARS = 100

# A line ending in a word character then a hyphen is a mid-word line break, not
# a header start. Not part of BillTrax's parser; ported from the measured gap
# above (raw-data doc §6) rather than from any BillTrax source line.
_MID_WORD_BREAK = re.compile(r"[A-Za-z]-\s*$")

# Sentinels for blocks that do not come from a matched header pattern.
FULL_REPORT_PATTERN = "full_report"
"""Whole-text fallback (report-parser.ts:61-63): no line in the text matched any pattern."""

PREAMBLE_PATTERN = "preamble"
"""Text before the first matched header; BillTrax silently discards it (report-parser.ts:38-51),
while this port keeps it as its own unlabeled block so front matter is not lost."""


@dataclass(frozen=True, slots=True)
class HeaderPattern:
    """One named entry from BillTrax's ``KNOWN_PATTERNS``/``isAgencyHeader`` (report-parser.ts:4-28).

    ``extra``, when given, is an additional condition a matched line must also satisfy; it ports
    BillTrax's two-or-more-words check (:26) that the ``all_caps_multiword`` regex alone cannot
    express, so the ``generic_agency_header`` fallback below can still catch a single all-caps word.
    """

    name: str
    regex: re.Pattern[str]
    reason: str
    extra: Callable[[str], bool] | None = None


# BillTrax's twelve KNOWN_PATTERNS (report-parser.ts:6-19), in their original
# precedence order, plus the two fallbacks isAgencyHeader tries afterward
# (:26, :27). One table, per pattern: a name (used to attribute which pattern
# matched a given block) and the reason it exists. Ordering is load-bearing:
# `_match_header` returns the first name whose regex matches.
HEADER_PATTERNS: tuple[HeaderPattern, ...] = (
    HeaderPattern(
        "department",
        re.compile(r"^(DEPARTMENT OF [A-Z\s,&'-]+)$"),
        "the most common cabinet-level heading in appropriations reports, e.g. DEPARTMENT OF DEFENSE, "
        "DEPARTMENT OF THE ARMY (measured: fires correctly on CRPT-113hrpt135's DEPARTMENT OF THE ARMY)",
    ),
    HeaderPattern(
        "office",
        re.compile(r"^(OFFICE OF [A-Z\s,&'-]+)$"),
        "sub-cabinet and executive offices given their own heading, e.g. OFFICE OF MANAGEMENT AND BUDGET "
        "(measured: fires correctly on CRPT-113srpt77's OFFICE OF THE SECRETARY AND EXECUTIVE MANAGEMENT)",
    ),
    HeaderPattern(
        "bureau",
        re.compile(r"^(BUREAU OF [A-Z\s,&'-]+)$"),
        "bureaus that head their own appropriations account apart from a parent department, e.g. "
        "BUREAU OF INDIAN AFFAIRS, BUREAU OF LAND MANAGEMENT; unmeasured -- neither real report names one",
    ),
    HeaderPattern(
        "agency_for",
        re.compile(r"^(AGENCY FOR [A-Z\s,&'-]+)$"),
        "agencies named with the 'Agency for' construction, e.g. AGENCY FOR INTERNATIONAL DEVELOPMENT; "
        "unmeasured -- neither real report names one",
    ),
    HeaderPattern(
        "national",
        re.compile(r"^(NATIONAL [A-Z\s,&'-]+ (ADMINISTRATION|AGENCY|FOUNDATION|INSTITUTE|SERVICE|COUNCIL))$"),
        "independent agencies named 'National ... <org-type>', e.g. NATIONAL AERONAUTICS AND SPACE "
        "ADMINISTRATION; the trailing org-type word disambiguates from a program or account line that "
        "merely starts with National (e.g. NATIONAL DEFENSE PROGRAMS, seen in CRPT-113hrpt135, correctly "
        "does not match)",
    ),
    HeaderPattern(
        "corps_of",
        re.compile(r"^(CORPS OF [A-Z\s,&'-]+)$"),
        "unmeasured -- neither real report contains a bare CORPS OF ... line, though CRPT-113hrpt135 is "
        "entirely about Army Corps of Engineers civil works and mentions 'the Corps of Engineers' in body text",
    ),
    HeaderPattern(
        "united_states",
        re.compile(r"^(UNITED STATES [A-Z\s,&'-]+)$"),
        "agencies spelled out with 'United States', e.g. UNITED STATES COURT OF APPEALS, UNITED STATES "
        "INSTITUTE OF PEACE; unmeasured -- neither real report names one",
    ),
    HeaderPattern(
        "food_and",
        re.compile(r"^(FOOD AND [A-Z\s,&'-]+)$"),
        "FOOD AND DRUG ADMINISTRATION, FOOD AND NUTRITION SERVICE; unmeasured -- neither real report names one",
    ),
    HeaderPattern(
        "general_services",
        re.compile(r"^(GENERAL SERVICES [A-Z\s,&'-]+)$"),
        "GENERAL SERVICES ADMINISTRATION; unmeasured -- neither real report names it",
    ),
    HeaderPattern(
        "small_business",
        re.compile(r"^(SMALL BUSINESS [A-Z\s,&'-]+)$"),
        "SMALL BUSINESS ADMINISTRATION; unmeasured -- neither real report names it",
    ),
    HeaderPattern(
        "environmental",
        re.compile(r"^(ENVIRONMENTAL [A-Z\s,&'-]+)$"),
        "ENVIRONMENTAL PROTECTION AGENCY; unmeasured as its own heading in the two measured reports, though "
        "CRPT-119hrpt105's body text names 'THE RULE SUBMITTED BY THE ENVIRONMENTAL PROTECTION AGENCY'",
    ),
    HeaderPattern(
        "federal",
        re.compile(r"^(FEDERAL [A-Z\s,&'-]+ (AGENCY|COMMISSION|BOARD|AUTHORITY))$"),
        "independent agencies named 'Federal ... <org-type>', e.g. FEDERAL COMMUNICATIONS COMMISSION, FEDERAL "
        "TRADE COMMISSION; does not match FEDERAL DEPOSIT INSURANCE CORPORATION (ends in CORPORATION, not one "
        "of the four trailing words) -- that name still matches the all_caps_multiword fallback below, so "
        "nothing is lost, it is just not attributed to this named pattern",
    ),
    # Fallbacks, in BillTrax's order (isAgencyHeader :26 then :27). Both share
    # AGENCY_HEADER's character class; all_caps_multiword adds the two-or-more-
    # word requirement, so generic_agency_header's only unique catch is a
    # single all-caps word of 5+ characters standing alone.
    HeaderPattern(
        "all_caps_multiword",
        re.compile(r"^[A-Z][A-Z\s,()&/'-]+$"),
        "any other all-caps line of two or more words that isn't one of the twelve named formats -- measured "
        "as the single largest source of blocks on both real reports: REPORT, R E P O R T, C O N T E N T S, "
        "HOUSE OF REPRESENTATIVES, HURRICANE SANDY, INTRODUCTION are all section titles, not agencies",
        extra=lambda trimmed: len(trimmed.split()) >= 2,
    ),
    HeaderPattern(
        "generic_agency_header",
        re.compile(r"^([A-Z][A-Z\s,()&/'-]{4,})\s*$"),
        "last resort: drops the two-or-more-word requirement, so it catches a single all-caps word of 5+ "
        "characters standing alone on a line, e.g. a department name split across lines by the PDF layout",
    ),
)


def _match_header(line: str) -> str | None:
    """The name of the first pattern (in precedence order) that matches this line, or None."""
    trimmed = line.strip()
    if not (MIN_HEADER_CHARS <= len(trimmed) <= MAX_HEADER_CHARS):
        return None
    for spec in HEADER_PATTERNS:
        if spec.regex.match(trimmed) and (spec.extra is None or spec.extra(trimmed)):
            return spec.name
    return None


def _normalize_agency_key(agency: str) -> str:
    """BillTrax's exact normalization for matching an agency label (committee-reports.ts:140): upper-case, then trim."""
    return agency.upper().strip()


@dataclass(frozen=True, slots=True)
class AgencyBlock:
    """One block of a parsed report: BillTrax's stored fields, plus what its ``text`` input discarded.

    ``agency``/``body`` match BillTrax's stored ``report_sections.agency_label``/``.body`` values
    (join-and-trim; report-parser.ts:43-44, :55-56), or the ``"Full Report"`` sentinel (:62) when no
    header matched; ``agency``/``agency_key`` are ``None`` for a ``preamble`` block. ``char_span`` is
    a half-open ``(start, end)`` pair into the flattened input, and every block's span is contiguous
    with its neighbors, so spans partition the whole input even where ``body`` is narrower than its
    span; ``page_span`` is the inclusive ``(first_page, last_page)``, or ``None`` for plain text.
    """

    agency: str | None
    agency_key: str | None
    body: str
    pattern: str
    char_span: tuple[int, int]
    page_span: tuple[int, int] | None


def _flatten(text_or_pages: str | Sequence[PageResult]) -> tuple[str, tuple[tuple[int, int, int], ...] | None]:
    """Return the joined text and, for a page sequence, each page's ``(number, start, end)`` half-open span.

    Pages join with ``"\\n"`` exactly as ``PageContent.text`` joins blocks within one page, so a page
    boundary is visible only as a line break and does not prevent a header match spanning two pages;
    duplicate page numbers raise ValueError.
    """
    if isinstance(text_or_pages, str):
        return text_or_pages, None
    pages = list(text_or_pages)
    numbers = [page.metadata["page"] for page in pages]
    if len(set(numbers)) != len(numbers):
        raise ValueError("parse_agency_blocks needs distinct page numbers")
    texts = [page.text for page in pages]
    starts: list[int] = []
    position = 0
    for text in texts:
        starts.append(position)
        position += len(text) + 1  # +1 for the "\n" joining this page to the next
    joined = "\n".join(texts)
    ends = [*starts[1:], len(joined)]
    return joined, tuple(zip(numbers, starts, ends, strict=True))


def _page_at(offset: int, page_ranges: tuple[tuple[int, int, int], ...]) -> int:
    """The page number whose half-open range contains ``offset``; the last page if ``offset`` is the text's end.

    A linear scan over the document's own page count, not the block count, so it stays cheap when
    called once per emitted block.
    """
    for number, start, end in page_ranges:
        if start <= offset < end:
            return number
    return page_ranges[-1][0]


def _page_span(start: int, end: int, page_ranges: tuple[tuple[int, int, int], ...] | None) -> tuple[int, int] | None:
    if page_ranges is None:
        return None
    return (_page_at(start, page_ranges), _page_at(max(start, end - 1), page_ranges))


def parse_agency_blocks(text_or_pages: str | Sequence[PageResult]) -> tuple[AgencyBlock, ...]:
    """Split text (or a sequence of ``extraction.model.PageResult``) into header-led blocks.

    Ports BillTrax's ``parseAgencyBlocks`` (report-parser.ts:30-66) and adds char/page span tracking it
    never had. A line matching ``_match_header`` (and not a mid-word line break -- see the module
    docstring) starts a block, and everything until the next header is its body; a block is emitted
    only when its stripped body is non-blank (report-parser.ts:40, :53), but its raw span is absorbed
    into an adjacent emitted block rather than vanishing, so the returned blocks' ``char_span`` slices
    partition the complete input with no gap and no overlap. Text before the first header becomes a
    ``PREAMBLE_PATTERN`` block with ``agency=None``; a text that emits no block at all returns one
    ``FULL_REPORT_PATTERN`` block; duplicate page numbers raise ValueError.
    """
    text, page_ranges = _flatten(text_or_pages)
    if not text.strip():
        return ()

    lines = text.split("\n")
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1

    blocks: list[AgencyBlock] = []
    pending_start = 0
    current_label: str | None = None
    current_pattern: str | None = None
    current_body_lines: list[str] = []
    preamble_lines: list[str] = []

    def flush(end_offset: int) -> None:
        nonlocal pending_start
        if current_label is not None:
            body = "\n".join(current_body_lines).strip()
            if not body:
                return
            blocks.append(
                AgencyBlock(
                    agency=current_label,
                    agency_key=_normalize_agency_key(current_label),
                    body=body,
                    pattern=current_pattern,
                    char_span=(pending_start, end_offset),
                    page_span=_page_span(pending_start, end_offset, page_ranges),
                )
            )
        else:
            body = "\n".join(preamble_lines).strip()
            if not body:
                return
            blocks.append(
                AgencyBlock(
                    agency=None,
                    agency_key=None,
                    body=body,
                    pattern=PREAMBLE_PATTERN,
                    char_span=(pending_start, end_offset),
                    page_span=_page_span(pending_start, end_offset, page_ranges),
                )
            )
        pending_start = end_offset

    for i, line in enumerate(lines):
        previous_line = lines[i - 1] if i > 0 else ""
        matched = _match_header(line) if not _MID_WORD_BREAK.search(previous_line.strip()) else None
        if matched is not None:
            flush(offsets[i])
            current_label = line.strip()
            current_pattern = matched
            current_body_lines = []
        elif current_label is not None:
            current_body_lines.append(line)
        else:
            preamble_lines.append(line)

    if current_label is not None:
        # Only flush a trailing header block here. A text with no header at all (current_label still
        # None) falls through to the "Full Report" sentinel below instead of becoming an unlabeled
        # preamble block -- that zero-header case is BillTrax's own sentinel, not this port's addition.
        flush(len(text))

    if not blocks:
        return (
            AgencyBlock(
                agency="Full Report",
                agency_key=_normalize_agency_key("Full Report"),
                body=text.strip(),
                pattern=FULL_REPORT_PATTERN,
                char_span=(0, len(text)),
                page_span=_page_span(0, len(text), page_ranges),
            ),
        )

    if pending_start < len(text):
        # Trailing header(s) with a blank body: absorb the unclaimed tail into the last real block.
        last = blocks[-1]
        new_span = (last.char_span[0], len(text))
        blocks[-1] = replace(last, char_span=new_span, page_span=_page_span(*new_span, page_ranges))

    return tuple(blocks)
