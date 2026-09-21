"""Header precedence, full char-span coverage, page attribution, and the mid-word hyphen guard.

BillTrax's report-parser.ts has no test of its own, so these cases are built from the ported code's precedence rules
and the three real committee-report fixtures rather than ported test cases."""

import hashlib
import json
import re
from itertools import pairwise
from pathlib import Path

import pytest

from spicy_docs.extraction.model import PageContent, PageResult, TextBlock
from spicy_docs.sources.agency_reports.report_blocks import (
    FULL_REPORT_PATTERN,
    HEADER_PATTERNS,
    MAX_HEADER_CHARS,
    MIN_HEADER_CHARS,
    PREAMBLE_PATTERN,
    parse_agency_blocks,
)

FIXTURES = Path(__file__).parent / "fixtures/agency_reports"

# One real example per named pattern, in BillTrax's precedence order (report-parser.ts:6-19, :26, :27).
HEADER_EXAMPLES = {
    "department": "DEPARTMENT OF DEFENSE",
    "office": "OFFICE OF MANAGEMENT AND BUDGET",
    "bureau": "BUREAU OF LAND MANAGEMENT",
    "agency_for": "AGENCY FOR INTERNATIONAL DEVELOPMENT",
    "national": "NATIONAL SCIENCE FOUNDATION",
    "corps_of": "CORPS OF ENGINEERS",
    "united_states": "UNITED STATES INSTITUTE OF PEACE",
    "food_and": "FOOD AND DRUG ADMINISTRATION",
    "general_services": "GENERAL SERVICES ADMINISTRATION",
    "small_business": "SMALL BUSINESS ADMINISTRATION",
    "environmental": "ENVIRONMENTAL PROTECTION AGENCY",
    "federal": "FEDERAL TRADE COMMISSION",
    "all_caps_multiword": "SECURITIES AND EXCHANGE COMMISSION",
    "generic_agency_header": "TREASURY",
}


def _page(number: int, text: str) -> PageResult:
    return PageResult({"page": number}, PageContent((TextBlock(text),), ()))


def _coverage(text: str, blocks) -> str:
    return "".join(text[start:end] for start, end in (block.char_span for block in blocks))


def test_header_pattern_table_is_the_twelve_known_patterns_then_the_two_fallbacks_in_order():
    assert [pattern.name for pattern in HEADER_PATTERNS] == list(HEADER_EXAMPLES)
    assert len(HEADER_PATTERNS) - 2 == 12  # the twelve named KNOWN_PATTERNS, plus the two fallbacks
    assert all(pattern.reason for pattern in HEADER_PATTERNS)  # every pattern names its reason


@pytest.mark.parametrize("name, header", HEADER_EXAMPLES.items())
def test_each_named_pattern_matches_its_own_example(name, header):
    blocks = parse_agency_blocks(f"{header}\nSome ordinary body text follows the heading.")
    assert len(blocks) == 1
    block = blocks[0]
    assert block.agency == header
    assert block.agency_key == header.upper()
    assert block.pattern == name
    assert block.char_span == (0, len(f"{header}\nSome ordinary body text follows the heading."))


def test_precedence_prefers_the_named_department_pattern_over_the_generic_fallbacks():
    # DEPARTMENT OF DEFENSE also satisfies all_caps_multiword and generic_agency_header;
    # HEADER_PATTERNS order means the named "department" pattern wins.
    blocks = parse_agency_blocks("DEPARTMENT OF DEFENSE\nbody")
    assert blocks[0].pattern == "department"


def test_federal_pattern_misses_a_corporation_suffix_but_the_multiword_fallback_still_catches_it():
    # FEDERAL DEPOSIT INSURANCE CORPORATION: "federal" requires AGENCY/COMMISSION/BOARD/AUTHORITY,
    # not CORPORATION -- documented as a measured gap in the pattern's own `reason`.
    blocks = parse_agency_blocks("FEDERAL DEPOSIT INSURANCE CORPORATION\nbody")
    assert blocks[0].pattern == "all_caps_multiword"
    assert blocks[0].agency == "FEDERAL DEPOSIT INSURANCE CORPORATION"


@pytest.mark.parametrize("line", ["AB", "ABCD", "A" * (MAX_HEADER_CHARS + 1), "A" * (MAX_HEADER_CHARS + 50)])
def test_length_gate_rejects_lines_outside_five_to_one_hundred_characters(line):
    assert not (MIN_HEADER_CHARS <= len(line) <= MAX_HEADER_CHARS)
    blocks = parse_agency_blocks(f"{line}\nmore plain text, still no real header anywhere")
    assert len(blocks) == 1 and blocks[0].pattern == FULL_REPORT_PATTERN


def test_lowercase_and_mixed_case_lines_never_match_any_pattern():
    blocks = parse_agency_blocks("Department of Defense\nbody text in a normal sentence")
    assert blocks[0].pattern == FULL_REPORT_PATTERN


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n", "\t \n "])
def test_blank_input_returns_no_blocks(text):
    assert parse_agency_blocks(text) == ()


def test_no_header_anywhere_returns_the_full_report_sentinel_spanning_everything():
    text = "just some\nplain prose\nwith no headers at all"
    blocks = parse_agency_blocks(text)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.agency == "Full Report" and block.agency_key == "FULL REPORT"
    assert block.pattern == FULL_REPORT_PATTERN
    assert block.body == text
    assert block.char_span == (0, len(text))


def test_preamble_before_the_first_header_becomes_its_own_unlabeled_block():
    text = "Title page prose.\nMore front matter.\nDEPARTMENT OF DEFENSE\nReal body content here."
    blocks = parse_agency_blocks(text)
    assert len(blocks) == 2
    preamble, department = blocks
    assert preamble.agency is None and preamble.agency_key is None
    assert preamble.pattern == PREAMBLE_PATTERN
    assert preamble.body == "Title page prose.\nMore front matter."
    assert preamble.char_span == (0, len("Title page prose.\nMore front matter.\n"))
    assert department.agency == "DEPARTMENT OF DEFENSE"
    assert department.char_span == (preamble.char_span[1], len(text))


def test_no_preamble_block_when_the_first_line_is_already_a_header():
    text = "DEPARTMENT OF DEFENSE\nbody"
    blocks = parse_agency_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].char_span[0] == 0


def test_a_header_immediately_followed_by_another_header_is_dropped_and_its_span_absorbed():
    # BillTrax never stores a row for a header with no body (report-parser.ts:40); its raw span
    # (the dropped header line) is folded into the following block instead of vanishing.
    text = "DEPARTMENT OF DEFENSE\nOFFICE OF MANAGEMENT AND BUDGET\nreal body"
    blocks = parse_agency_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].agency == "OFFICE OF MANAGEMENT AND BUDGET"
    assert blocks[0].char_span == (0, len(text))


def test_a_trailing_header_with_a_blank_body_is_absorbed_into_the_previous_block():
    text = "DEPARTMENT OF DEFENSE\nreal body\nOFFICE OF MANAGEMENT AND BUDGET\n   \n"
    blocks = parse_agency_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].agency == "DEPARTMENT OF DEFENSE"
    assert blocks[0].char_span == (0, len(text))


def test_mid_word_hyphen_break_is_never_treated_as_a_header():
    # The exact fragment measured in CRPT-119hrpt105 (raw-data doc §6): a heading that legitimately
    # wraps onto the next line via a hyphen, which would otherwise itself satisfy "office"/all-caps.
    text = (
        "OFFICE OF THE COMPTROLLER OF THE CURRENCY OF THE DEPART-\n"
        "MENT OF THE TREASURY RELATING TO THE REVIEW OF APPLICATIONS\n"
        "DEPARTMENT OF DEFENSE\n"
        "real body"
    )
    blocks = parse_agency_blocks(text)
    assert [block.agency for block in blocks] == [
        "OFFICE OF THE COMPTROLLER OF THE CURRENCY OF THE DEPART-",
        "DEPARTMENT OF DEFENSE",
    ]
    assert "MENT OF THE TREASURY RELATING TO THE REVIEW OF APPLICATIONS" in blocks[0].body


def test_mid_word_hyphen_fragment_would_satisfy_a_pattern_without_the_guard():
    # Proves the guard is doing the work above, not the length gate or character class.
    fragment = "MENT OF THE TREASURY RELATING TO THE REVIEW OF APPLICATIONS"
    assert MIN_HEADER_CHARS <= len(fragment) <= MAX_HEADER_CHARS
    assert any(pattern.regex.match(fragment) for pattern in HEADER_PATTERNS)


def test_page_span_attributes_a_block_confined_to_one_page():
    pages = [_page(12, "DEPARTMENT OF DEFENSE\nbody line one\nbody line two"), _page(13, "more body on the next page")]
    blocks = parse_agency_blocks(pages)
    assert len(blocks) == 1
    assert blocks[0].page_span == (12, 13)  # the block's body continues onto page 13


def test_page_span_is_none_for_plain_text_input():
    blocks = parse_agency_blocks("DEPARTMENT OF DEFENSE\nbody")
    assert blocks[0].page_span is None


def test_page_span_separates_two_blocks_on_two_pages():
    pages = [
        _page(1, "DEPARTMENT OF DEFENSE\nfirst body"),
        _page(2, "OFFICE OF MANAGEMENT AND BUDGET\nsecond body"),
    ]
    blocks = parse_agency_blocks(pages)
    assert len(blocks) == 2
    assert blocks[0].page_span == (1, 1)
    assert blocks[1].page_span == (2, 2)


def test_flatten_rejects_duplicate_page_numbers():
    pages = [_page(1, "DEPARTMENT OF DEFENSE\nbody"), _page(1, "OFFICE OF MANAGEMENT AND BUDGET\nbody")]
    with pytest.raises(ValueError, match="distinct page numbers"):
        parse_agency_blocks(pages)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no headers here at all, just prose",
        "DEPARTMENT OF DEFENSE\nbody",
        "Preamble text.\nDEPARTMENT OF DEFENSE\nbody\nOFFICE OF MANAGEMENT AND BUDGET\n\nSMALL BUSINESS ADMINISTRATION\nmore body",
        "DEPARTMENT OF DEFENSE\nOFFICE OF MANAGEMENT AND BUDGET\n   \nSMALL BUSINESS ADMINISTRATION\nreal body",
    ],
)
def test_block_spans_partition_synthetic_input_with_nothing_lost(text):
    blocks = parse_agency_blocks(text)
    assert _coverage(text, blocks) == text
    for previous, current in pairwise(blocks):
        assert previous.char_span[1] == current.char_span[0]
    if blocks:
        assert blocks[0].char_span[0] == 0
        assert blocks[-1].char_span[1] == len(text)


def test_retained_fixture_pins():
    for row in json.loads((FIXTURES / "sources.json").read_bytes()):
        raw = (FIXTURES / row["file"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


@pytest.mark.parametrize(
    "fixture",
    ["crpt-119hrpt105.txt", "crpt-113hrpt135.txt", "crpt-113srpt77.txt"],
)
def test_real_report_block_spans_cover_the_fixture_with_nothing_lost(fixture):
    text = (FIXTURES / fixture).read_text()
    blocks = parse_agency_blocks(text)
    assert blocks  # every fixture contains at least one header
    assert _coverage(text, blocks) == text
    for previous, current in pairwise(blocks):
        assert previous.char_span[1] == current.char_span[0]
    assert blocks[0].char_span[0] == 0
    assert blocks[-1].char_span[1] == len(text)


def test_real_reports_fire_on_section_titles_as_often_as_agencies():
    # Measured: this is a heading splitter, not an agency detector (raw-data doc §6). REPORT,
    # R E P O R T, HOUSE OF REPRESENTATIVES and COMMITTEE VOTES are section titles that satisfy
    # all_caps_multiword, exactly like a real DEPARTMENT OF ... heading does.
    blocks = parse_agency_blocks((FIXTURES / "crpt-119hrpt105.txt").read_text())
    labels = [block.agency for block in blocks]
    assert "REPORT" in labels
    assert "HOUSE OF REPRESENTATIVES" in labels
    assert "COMMITTEE VOTES" in labels
    assert any(label and label.startswith("OFFICE OF") for label in labels)  # a real heading is also present


def _header_line_count(text: str, *, guarded: bool) -> int:
    """Count lines `_match_header`'s length gate + HEADER_PATTERNS would treat as a header start.

    Rebuilt from the module's public pattern table and length-gate constants (not from a private
    helper), so this measures the same precedence rules `parse_agency_blocks` uses. `guarded=False`
    omits the mid-word-hyphen check entirely -- BillTrax's own unguarded behavior -- to measure what
    the guard removes.
    """
    lines = text.split("\n")
    count = 0
    for i, line in enumerate(lines):
        previous = lines[i - 1].strip() if i > 0 else ""
        if guarded and re.search(r"[A-Za-z]-\s*$", previous):
            continue
        trimmed = line.strip()
        if MIN_HEADER_CHARS <= len(trimmed) <= MAX_HEADER_CHARS and any(
            p.regex.match(trimmed) for p in HEADER_PATTERNS
        ):
            count += 1
    return count


@pytest.mark.parametrize(
    "fixture, before, after",
    [
        # `before`/`after` are header-line matches on this exact fixture file, with and without the
        # mid-word-hyphen guard. The drop (2, 1, 0) matches `hyphenWrapFragmentHeaders` in
        # docs/research/billtrax-raw-data-2026-09-19.json for these three packages exactly, even
        # though `crpt-113hrpt135.txt`/`crpt-113srpt77.txt` are bounded excerpts of the full report
        # (see tests/fixtures/agency_reports/README.md) with correspondingly smaller total counts.
        ("crpt-119hrpt105.txt", 11, 9),
        ("crpt-113hrpt135.txt", 30, 29),
        ("crpt-113srpt77.txt", 139, 139),
    ],
)
def test_the_hyphen_guard_measurably_drops_header_matches_on_real_reports(fixture, before, after):
    text = (FIXTURES / fixture).read_text()
    assert _header_line_count(text, guarded=False) == before
    assert _header_line_count(text, guarded=True) == after
