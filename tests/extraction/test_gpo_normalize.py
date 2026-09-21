"""Port of BillTrax's ``pdf-normalize.test.ts`` (27 cases, 9 describes), re-derived for PyMuPDF's line layout:
a GPO gutter number arrives as its own physical line and the print-shop footer spans several lines, unlike
pdf-parse's glued shapes. Three more groups follow -- real-document fixtures with exact ``GpoCleanupRecord``
counts, PDF-vs-PDF and PDF-vs-XML concordance checks, and one integration-marked live refetch -- and ported
fixtures under the 50-content-line floor are padded with ``gutter_filler`` so they keep exercising the
adjacency/rejoin mechanism rather than the floor (see ``docs/extraction-gpo.md``).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from spicy_docs.extraction.gpo_normalize import (
    GpoCleanupRecord,
    GpoPageCleanup,
    is_gpo_layout,
    normalize_gpo_pages,
)

FIXTURES = Path(__file__).parents[1] / "fixtures/gpo_pdf_text"
GOVINFO_BILLS = Path(__file__).parents[1] / "fixtures/govinfo_bills"


def page(*lines: str) -> tuple[str, ...]:
    """One page built from physical lines, the shape ``PageResult.text`` has."""
    return ("\n".join(lines),)


def gutter_filler(n: int) -> tuple[str, ...]:
    """``n`` extra gutter-numbered content lines, each line followed by its own bare 1-2 digit number.
    Appending these clears ``gpo_normalize._MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` (50 content lines, ported
    from DeltaTrack's ``_MIN_LINES_FOR_GUARD``) while keeping the numbered/content ratio realistic, so most of
    BillTrax's tiny ported fixtures still exercise the adjacency/rejoin mechanism rather than the floor."""
    filler: list[str] = []
    for i in range(n):
        filler.append(f"Additional statutory text for measurement, clause {i}.")
        filler.append(str((i % 25) + 1))
    return tuple(filler)


def unnumbered_filler(n: int) -> tuple[str, ...]:
    """``n`` plain content lines with no adjacent gutter number, the shape a resolution's unnumbered "Whereas"
    preamble takes; used to push a synthetic document's content-line count at or above the floor while driving
    its numbered/content ratio down, independently of ``gutter_filler``, which keeps that ratio high.
    """
    return tuple(f"Whereas clause number {i} of the preamble recites a finding." for i in range(n))


# ---------------------------------------------------------------------------
# is_gpo_layout (BillTrax: detectLineNumbered) -- 4 cases
# ---------------------------------------------------------------------------


def test_true_when_content_lines_are_each_followed_by_a_bare_gutter_number():
    """Adapted: the detector reads PyMuPDF's adjacent bare-number line instead of pdf-parse's trailing-digit
    suffix ("Representa-1"). Below ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` the ratio alone is not enough, but
    this excerpt's digits (1-5) are a consecutive run starting at 1 -- real GPO numbering restarts at 1 on every
    page, so a genuinely short numbered bill is still recognized (see ``_starts_consecutive_run_from_one``);
    contrast the two run-failure cases below."""
    text = page(
        "Be  it  enacted  by  the  Senate  and  House  of  Representa-",
        "1",
        "tives of the United States of America in Congress assembled,",
        "2",
        "SECTION 1. SHORT TITLE.",
        "3",
        "This Act may be cited as the National Defense Authorization",
        "4",
        "Act for Fiscal Year 2026.",
        "5",
    )
    assert is_gpo_layout(text) is True


def test_false_for_a_run_that_does_not_start_at_one():
    """New (B3, refined in review): a page whose gutter digits are 1, 2, 4 -- not a consecutive run -- is not
    GPO-numbered evidence below the floor, even though its 3/3 ratio is as strong as it can be; the prefix run
    breaks at the third digit, so its length is 2, under ``_MIN_GUTTER_RUN_LENGTH``."""
    text = page("enacted", "1", "by the", "2", "Senate", "4")
    assert is_gpo_layout(text) is False


def test_false_for_a_run_split_across_pages_that_never_restarts_at_one():
    """New (B3, refined in review): five footnote-style markers numbered straight through two pages (1, 2 then
    3, 4, 5) rather than restarting at 1 the way GPO gutter numbering does; neither page alone has a
    ``_MIN_GUTTER_RUN_LENGTH`` run starting at 1 -- the residual a single page cannot see."""
    pages = (
        page(
            "First paragraph of the memo carries a note.",
            "1",
            "Second paragraph continues the point here.",
            "2",
        )[0],
        page(
            "Third paragraph keeps the numbering going.",
            "3",
            "Fourth paragraph adds one more citation.",
            "4",
            "Fifth and final paragraph wraps up the memo.",
            "5",
        )[0],
    )
    assert is_gpo_layout(pages) is False


def test_false_for_enr_text_without_gutter_numbers():
    text = page(
        "Be  it  enacted  by  the  Senate  and  House  of  Representatives",
        "of the United States of America in Congress assembled,",
        "SECTION 1. SHORT TITLE.",
        "This Act may be cited as the National Defense Authorization Act.",
        "SECTION 2. ORGANIZATION OF ACT INTO DIVISIONS.",
    )
    assert is_gpo_layout(text) is False


def test_false_for_two_content_lines_each_followed_by_its_own_gutter_number_line():
    """Adapted: two content lines, each still followed by its own gutter number line, rather than pdf-parse's
    two inline-numbered lines."""
    text = page("enacted", "1", "Section", "2")
    assert is_gpo_layout(text) is False


def test_filters_a_tail_verdate_footer_and_a_real_2025_job_code_line_before_counting_content():
    """Adapted: the footer sits at the real tail of the page (a VerDate line is always followed only by more
    footer, never real content) and the job-code line uses a real 2025 shape (no literal "DSK" prefix, no
    trailing "$"), both filtered before counting content."""
    text = page(
        "normal line no number",
        "another normal line",
        "third normal line",
        "VerDate Sep 11 2014",
        "ssavage on LAPJG3WLY3PROD with BILLS",
    )
    assert is_gpo_layout(text) is False


# ---------------------------------------------------------------------------
# Layout verdict fixes from the gap B6 corpus validation -- 3 cases
# (docs/extraction-gpo.md, "Corpus validation"; see _layout_verdict's own
# docstring in gpo_normalize.py for the two real documents that caught these)
# ---------------------------------------------------------------------------


def test_true_below_the_floor_on_an_exact_thirty_percent_ratio():
    """New (gap B6 corpus validation): a strict ``> 0.3`` made two real GPO-numbered documents
    (``BILLS-119sjres141is``, ``BILLS-119hconres11eh``) fail on a ratio that landed exactly at 30% even with a
    real per-page run confirming genuine numbering; reproduced synthetically as 10 content lines, 3 numbered
    (a valid 1-2-3 run), ratio exactly 0.3."""
    text = page(
        "Resolved by the Senate and House of Representatives",
        "1",
        "of the United States of America in Congress assembled,",
        "2",
        "That Congress disapproves the rule submitted by the agency",
        "3",
        "relating to a matter of significant public interest today,",
        "which was published in the Federal Register on this date,",
        "and which the agency described in its own submitted filing,",
        "concerning matters within the jurisdiction of this committee,",
        "as further explained in the accompanying committee report,",
        "and no additional gutter numbers appear on the lines below,",
        "since this excerpt intentionally stops short of the full text.",
    )
    assert is_gpo_layout(text) is True


def test_true_at_or_above_the_floor_when_a_long_unnumbered_preamble_dilutes_the_ratio_but_a_page_shows_a_real_run():
    """New (gap B6 corpus validation): the per-page run test now decides independently once the document clears
    the floor, so a six-page unnumbered "Whereas" preamble that dilutes ``BILLS-119hconres26ih`` to ratio 0.268
    despite four pages of unambiguous numbering -- one run 25 long -- is still line-numbered; reproduced
    synthetically as 55 unnumbered lines plus a real run of 5 (ratio 0.083)."""
    text = page(
        *unnumbered_filler(55),
        "Resolved by the Senate and House of Representatives",
        "1",
        "of the United States of America in Congress assembled,",
        "2",
        "That the previously recited findings are hereby affirmed,",
        "3",
        "and the Congress further declares its support for the matter,",
        "4",
        "concluding the operative text of this resolution today.",
        "5",
    )
    normalized, record = normalize_gpo_pages(text)
    assert record.line_numbers is True
    assert "Representatives" in normalized[0]


def test_false_below_the_floor_when_a_real_run_exists_but_the_ratio_is_too_low():
    """Regression guard for the conservative half of the fix above: below the floor both signals stay required,
    so three gutter-adjacent lines out of seventeen (ratio 0.176) is not enough despite a valid run from 1 --
    BillTrax's own concern that "a two-page memo should not be declared GPO-numbered on three lines just because
    they happen to be numbered"."""
    text = page(
        "Resolved by the Senate and House of Representatives",
        "1",
        "of the United States of America in Congress assembled,",
        "2",
        "That the following findings are affirmed by the Congress,",
        "3",
        "and no further line in this excerpt carries a gutter number,",
        "since the remainder is entirely unnumbered narrative text,",
        "continuing across several more lines of plain prose content,",
        "each one just as unnumbered as the line that came before it,",
        "padding this excerpt out to twenty total lines of content,",
        "still without a second gutter number anywhere in the text,",
        "so the document-wide ratio stays well under the 0.3 mark,",
        "even though the first three lines still form a real run,",
        "which is exactly the shape this test exists to distinguish,",
        "from a genuinely numbered document like the one tested above,",
        "where the numbered lines make up a much larger share of it,",
        "not just a small fraction buried in an otherwise plain page,",
        "and this line and the next both stay plain narrative text,",
        "ending the excerpt here without any further gutter numbers.",
    )
    _normalized, record = normalize_gpo_pages(text)
    assert record.line_numbers is False


def test_true_at_or_above_the_floor_across_pages_and_the_rejoin_blast_radius_on_an_unrelated_page():
    """New (gap B6 corpus review): ``_layout_verdict`` sums content and gutter-adjacent lines across pages while
    checking structural runs per page, so a minimal three-line run (1, 2, 3) on one page clears a 56-line
    document at ratio 0.071. On a fourth, unrelated page the document-wide verdict strips its coincidental bare
    "7" as bare-digit metadata (``bare_page_number_evidence`` is ``"gutter_layout"`` there too) but does not
    rejoin "cross-refer-" -- ``_rejoin_hyphens`` requires the line's own next raw line to be the digit -- so the
    verdict's blast radius on hyphen-rejoin stays bounded by each line's local corroboration."""
    pages = (
        page(*unnumbered_filler(25))[0],
        page(*unnumbered_filler(25))[0],
        page(
            "Resolved by the Senate and House of Representatives",
            "1",
            "of the United States of America in Congress assembled,",
            "2",
            "That the operative text of this resolution concludes today.",
            "3",
        )[0],
        page(
            "A statutory cross-refer-",
            "ence continues on this unrelated page,",
            "7",
            "and the page ends here without further numbering.",
        )[0],
    )
    assert is_gpo_layout(pages) is True

    normalized, record = normalize_gpo_pages(pages)
    assert record.line_numbers is True
    assert record.hyphen_rejoin_count == 0
    assert record.pages[3].hyphen_rejoin_count == 0
    assert record.pages[3].bare_page_number_lines == 1
    assert record.pages[3].bare_page_number_evidence == "gutter_layout"
    assert "cross-refer-" in normalized[3]
    assert "cross-reference" not in normalized[3]
    assert "7" not in normalized[3].split("\n")


# ---------------------------------------------------------------------------
# GPO metadata stripping -- 5 cases
# ---------------------------------------------------------------------------


def test_strips_the_multiline_verdate_footer_pymupdf_splits_across_lines():
    """Re-derived: PyMuPDF splits pdf-parse's one fused footer line into ~9 physical lines always at the tail of
    the page, so the whole tail is dropped once VerDate matches, not just the line VERDATE_RE itself matches."""
    text = page(
        "enacted by the Senate",
        "1",
        "and House of Representatives",
        "2",
        "of the United States.",
        "3",
        "VerDate Sep 11 2014",
        "00:08 Jan 21, 2026",
        "Jkt 069200",
        "PO 00000",
        "Frm 00002",
        "Fmt 6652",
        "Sfmt 6201",
        "E:\\BILLS\\H",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "enacted by the Senate" in normalized[0]
    assert "and House of Representatives" in normalized[0]
    assert "of the United States." in normalized[0]
    for token in ("VerDate", "Jkt", "PO 00000", "Frm 00002", "Fmt 6652", "Sfmt 6201", "E:\\BILLS"):
        assert token not in normalized[0]
    assert record.gpo_footers is True


def test_strips_job_code_lines_without_the_literal_dsk_prefix_or_dollar_suffix():
    """Re-derived: real 2025 GovInfo output has neither BillTrax's literal "DSK" machine-id prefix nor its
    trailing "$" ("ssavage on LAPJG3WLY3PROD with BILLS"), so the rule generalizes to any machine id ending
    "PROD" and any trailing job-code token."""
    text = page(
        "enacted by the Senate",
        "1",
        "ssavage on LAPJG3WLY3PROD with BILLS",
        "and House",
        "2",
        "of the United States.",
        "3",
    )
    normalized, _record = normalize_gpo_pages(text)
    assert "LAPJG3WLY3PROD" not in normalized[0]
    assert "ssavage" not in normalized[0]


def test_strips_bare_gutter_and_page_number_lines():
    """This page carries no VerDate/DSK/running-footer evidence, so digit stripping depends entirely on the
    document-level layout verdict -- cleared by the structural run test, since the three content lines' gutter
    digits (1, 2, 3) are a consecutive run starting at 1 (see ``_starts_consecutive_run_from_one``)."""
    text = page(
        "end of page text",
        "1",
        "3",
        "start of next page",
        "2",
        "more content here",
        "3",
    )
    normalized, _record = normalize_gpo_pages(text)
    lines = [line for line in normalized[0].split("\n") if line]
    assert all(not re.fullmatch(r"\d+", line) for line in lines)


def test_strips_bullet_bill_identifier_lines():
    text = page(
        "end of page content",
        "1",
        "\u2022HR  7148  IH",
        "start of next section",
        "2",
        "more text here",
        "3",
    )
    normalized, _record = normalize_gpo_pages(text)
    assert "\u2022HR" not in normalized[0]
    assert "7148  IH" not in normalized[0]


def test_strips_unbulleted_running_bill_stage_footer_lines():
    """New (B2): a print-stage tag like "HR 5895 PCS" that GPO does not bullet, ported verbatim from
    DeltaTrack's ``_RUNNING_FOOTER``; self-evidencing and independent of the layout floor, but it strips only
    when the *next* line is not itself a bare gutter number -- see the test below for why."""
    text = page(
        "end of page content",
        "1",
        "HR 5895 PCS",
        "start of next section",
        "2",
        "more text here",
        "3",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "HR 5895 PCS" not in normalized[0]
    assert "start of next section" in normalized[0]
    assert record.running_footer_lines == 1
    assert record.pages[0].running_footer_lines == 1


def test_does_not_strip_a_bill_number_mentioned_mid_sentence():
    """The running-footer pattern matches a WHOLE line, like upstream's own ``re.MULTILINE`` anchors, so prose
    that happens to mention a bill number is not a print-stage tag and must survive."""
    text = page("This section amends H.R. 1234 PCS references in prior law.")
    normalized, _record = normalize_gpo_pages(text)
    assert "H.R. 1234 PCS" in normalized[0]


def test_keeps_a_running_footer_shaped_content_line_when_followed_by_its_own_gutter_number():
    """Refined in review: a genuine running footer is page furniture followed by prose, never by its own gutter
    number, so a real numbered content line that merely shares the shape -- plausible in a bill discussing its
    own designation -- is restored as ordinary gutter-numbered content instead of being deleted with its digit."""
    text = page(
        "some preceding content here",
        "1",
        "HR 5895 PCS",
        "2",
        "more content after that line",
        "3",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "HR 5895 PCS" in normalized[0]
    assert record.running_footer_lines == 0
    assert record.pages[0].running_footer_lines == 0
    assert record.pages[0].content_lines == 3


def test_gpo_footers_false_when_no_footer_lines_present():
    text = page(
        "enacted by the Senate",
        "1",
        "and House of Representatives",
        "2",
        "of the United States.",
        "3",
    )
    _normalized, record = normalize_gpo_pages(text)
    assert record.gpo_footers is False


# ---------------------------------------------------------------------------
# Gutter number stripping (BillTrax: "trailing line number stripping") -- 4 cases
# ---------------------------------------------------------------------------


def test_strips_gutter_number_lines_while_preserving_content_text():
    """Adapted: under PyMuPDF a gutter number is never attached to its line, so BillTrax's space-versus-hyphen
    suffix distinction does not apply -- only "a bare number line follows". Digits 2, 3, 4 continue
    mid-document rather than starting at 1, so ``gutter_filler`` padding past the floor lets the ratio decide."""
    text = page(
        "tives of the United States of America in Congress assembled,",
        "2",
        "SECTION 1. SHORT TITLE.",
        "3",
        "This Act may be cited as the Defense Authorization Act.",
        "4",
        *gutter_filler(50),
    )
    normalized, record = normalize_gpo_pages(text)
    assert "tives of the United States of America in Congress assembled," in normalized[0]
    assert "SECTION 1. SHORT TITLE." in normalized[0]
    assert not re.search(r"^\d+$", normalized[0], re.MULTILINE)
    assert record.line_numbers is True


def test_strips_two_digit_gutter_numbers():
    """This page carries no footer evidence and its digits (17-20) do not start at 1, so digit stripping
    depends entirely on the document-level ratio verdict, cleared by ``gutter_filler`` padding past the floor."""
    text = page(
        "permanent  change  of  station  travel  (including  all",
        "17",
        "expenses  thereof  for  organizational",
        "18",
        "movements).",
        "19",
        "Additional content here today.",
        "20",
        *gutter_filler(50),
    )
    normalized, _record = normalize_gpo_pages(text)
    for n in ("17", "18", "19", "20"):
        assert not re.search(rf"^{n}$", normalized[0], re.MULTILINE)


def test_preserves_inline_numbers_in_non_gpo_layout_text():
    """ENR text has no gutter-number lines at all, so section references and dollar amounts that happen to
    contain digits are never touched -- this rule only ever drops a line that is *entirely* a 1-4 digit number."""
    text = page(
        "Be it enacted by the Senate",
        "and House of Representatives",
        "of the United States in section 1",
        "The amount is not to exceed $22",
    )
    normalized, record = normalize_gpo_pages(text)
    assert record.line_numbers is False
    assert "section 1" in normalized[0]
    assert "$22" in normalized[0]


def test_line_numbers_false_when_no_gutter_numbers_present():
    text = page(
        "The quick brown fox jumps over the lazy dog.",
        "Nothing in this section shall be construed as limiting.",
        "All amounts are expressed in thousands of dollars.",
        "The Secretary shall report within 90 days.",
    )
    _normalized, record = normalize_gpo_pages(text)
    assert record.line_numbers is False


# ---------------------------------------------------------------------------
# Hyphenated word rejoin -- 4 cases
# ---------------------------------------------------------------------------


def test_rejoins_hyphen_wrap_corroborated_by_a_following_gutter_number():
    """Rejoin runs only once the document layout verdict is True -- cleared here by the structural run test
    (gutter digits 1, 2, 3, a consecutive run starting at 1), below the minimum-content-line floor."""
    text = page(
        "Be  it  enacted  by  the  Senate  and  House  of  Representa-",
        "1",
        "tives of the United States of America in Congress assembled,",
        "2",
        "SECTION 1. SHORT TITLE.",
        "3",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "Representatives of the United States of America" in normalized[0]
    assert record.hyphen_rejoin_count > 0


def test_rejoins_sta_hyphen_to_station():
    """This excerpt's own digits (18-20) do not start at 1, so ``gutter_filler`` padding past the
    minimum-content-line floor lets the ratio alone decide the rejoin."""
    text = page(
        "permanent  change  of  sta-",
        "18",
        "tion  travel  (including  all  expenses).",
        "19",
        "Additional content on this line here.",
        "20",
        *gutter_filler(50),
    )
    normalized, _record = normalize_gpo_pages(text)
    assert "station" in normalized[0]
    assert "sta-" not in normalized[0]


def test_handles_chained_multiline_hyphen_splits():
    """Gutter digits 1, 2, 3, 4 -- a consecutive run starting at 1 -- clear the structural run test below the
    minimum-content-line floor."""
    text = page(
        "appro-",
        "1",
        "pria-",
        "2",
        "tions.",
        "3",
        "More content here today.",
        "4",
    )
    normalized, _record = normalize_gpo_pages(text)
    assert "appropriations." in normalized[0]


def test_records_hyphen_rejoin_count():
    """Gutter digits 1, 2, 3 clear the structural run test below the minimum-content-line floor, so this
    fixture's one real rejoin is counted."""
    text = page(
        "Repre-",
        "1",
        "sentatives assembled",
        "2",
        "SEC. 2. AUTHORIZATION.",
        "3",
    )
    _normalized, record = normalize_gpo_pages(text)
    assert record.hyphen_rejoin_count == 1


# ---------------------------------------------------------------------------
# Small-caps single-letter merge -- 3 cases
# ---------------------------------------------------------------------------


def test_merges_lone_capital_letter_with_following_capitalized_line():
    text = page(
        "M",
        "ILITARYPERSONNEL, AIRFORCE",
        "16",
        "appropriation amount",
        "17",
        "for fiscal year 2026.",
        "18",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "MILITARYPERSONNEL" in normalized[0]
    assert record.small_caps_merges == 1


def test_does_not_merge_lone_capital_before_lowercase_line():
    text = page(
        "I",
        "n this section",
        "1",
        "the amount",
        "2",
        "is specified.",
        "3",
    )
    normalized, _record = normalize_gpo_pages(text)
    assert "In\nthis" not in normalized[0]


def test_records_small_caps_merge_count():
    text = page(
        "S",
        "ENATE APPROPRIATIONS",
        "1",
        "H",
        "OUSE APPROPRIATIONS",
        "2",
        "funding amount",
        "3",
    )
    _normalized, record = normalize_gpo_pages(text)
    assert record.small_caps_merges == 2


# ---------------------------------------------------------------------------
# Multiple space collapse -- 2 cases
# ---------------------------------------------------------------------------


def test_collapses_multiple_internal_spaces_to_single_spaces():
    """Doubled internal spaces measured zero occurrences under PyMuPDF across all three real fixtures in
    tests/fixtures/gpo_pdf_text/, so the rule is kept for compatibility (like BillTrax's own always-true
    spacingNormalized field) and exercised here with a synthetic case rather than a real one."""
    text = page(
        "Be  it  enacted  by  the  Senate  and  House",
        "of  Representatives  of  the  United  States",
        "in  Congress  assembled.",
    )
    normalized, record = normalize_gpo_pages(text)
    assert not re.search(r"  ", normalized[0])
    assert "Be it enacted by the Senate and House" in normalized[0]
    assert record.spacing_normalized is True


def test_collapses_spaces_regardless_of_gpo_layout():
    text = page("Be  it  enacted  by  the  Senate", "and  House  of  Representatives.")
    normalized, _record = normalize_gpo_pages(text)
    assert not re.search(r"  ", normalized[0])


# ---------------------------------------------------------------------------
# Encoding normalization -- 3 cases
# ---------------------------------------------------------------------------


def test_converts_curly_quotes_to_straight_quotes():
    text = page("\u2018quoted\u2019 and \u201cdouble\u201d text", "more text here", "final line.")
    normalized, _record = normalize_gpo_pages(text)
    assert "'quoted'" in normalized[0]
    assert '"double"' in normalized[0]


def test_collapses_gpos_doubled_single_quote_into_one_double_quote():
    """New, added from real data (CRPT-119hrpt105 renders a double quote as two adjacent single curly quotes,
    ``''Review of Final Rule ...''``), which the single-quote replacement alone leaves as two straight single
    quotes; the pair collapses to one double quote, the same collapse DeltaTrack's independently derived,
    extractor-agnostic ``normalize_glyphs`` reaches."""
    text = page("relating to \u2018\u2018Review of Final Rule\u2019\u2019 today.")
    normalized, _record = normalize_gpo_pages(text)
    assert '"Review of Final Rule"' in normalized[0]
    assert "''" not in normalized[0]


def test_converts_non_breaking_spaces_to_regular_spaces():
    text = page("enacted by the Senate\u00a0", "and House.", "more text.")
    normalized, _record = normalize_gpo_pages(text)
    assert "\u00a0" not in normalized[0]


def test_normalizes_crlf_to_lf():
    text = ("line one\r\nline two\r\nline three",)
    normalized, _record = normalize_gpo_pages(text)
    assert "\r" not in normalized[0]
    assert len(normalized[0].split("\n")) > 1


# ---------------------------------------------------------------------------
# Full IH document simulation -- 1 case
# ---------------------------------------------------------------------------


def test_cleans_a_realistic_ih_page_excerpt_end_to_end():
    """Adapted: gutter numbers on their own lines, a real 2025-shaped job-code line and the footer at the true
    page tail (a VerDate line is always the last thing PyMuPDF emits). The digit sequence (16, 17, 1-5) does
    not start at 1, so ``gutter_filler`` inserted before the VerDate line -- anything after it is swallowed into
    the footer's tail -- clears the floor for the ratio to decide."""
    text = page(
        "\u2022HR  7148  IH",
        "M",
        "ILITARY  PERSONNEL,",
        "16",
        "appropriation  amount  for  2026.",
        "17",
        "Be  it  enacted  by  the  Senate  and  House  of  Representa-",
        "1",
        "tives of the United States of America in Congress assembled,",
        "2",
        "SECTION 1. SHORT TITLE.",
        "3",
        "This Act may be cited as the \u201cNational Defense Author-",
        "4",
        "ization Act for Fiscal Year 2026\u201d.",
        "5",
        *gutter_filler(50),
        "VerDate Sep 11 2014",
        "00:08 Jan 21, 2026",
        "Jkt 069200",
        "PO 00000",
        "Frm 00002",
        "Fmt 6652",
        "Sfmt 6201",
        "E:\\BILLS\\H",
        "H0000",
        "kjohnson on LAPJG3WLY3PROD with BILLS",
    )
    normalized, record = normalize_gpo_pages(text)
    result = normalized[0]

    assert "VerDate" not in result
    assert "kjohnson" not in result
    assert "\u2022HR" not in result

    assert record.line_numbers is True

    assert "Representatives of the United States" in result
    assert "National Defense Authorization Act" in result

    assert "MILITARY" in result

    assert not re.search(r"  ", result)
    assert not re.search(r"^\d+$", result, re.MULTILINE)


# ---------------------------------------------------------------------------
# ENR document (no line numbers) -- 1 case
# ---------------------------------------------------------------------------


def test_cleans_enr_format_and_leaves_hyphen_wraps_unrejoined_without_gutter_numbers():
    """Adapted: BillTrax's original ENR fixture had no hyphen-wrapped word, so this makes the scope decision
    baked into normalizePdfText explicit -- without a gutter number there is no signal to tell a print-wrap
    hyphen from a real hyphenated compound ending a line by coincidence, so the real fixture's genuine wraps
    ("concur-\\nring),", "President-\\nelect") stay split."""
    text = page(
        "Be  it  enacted  by  the  Senate  and  House  of  Representatives",
        "of the United States of America in Congress assembled, That",
        "SECTION 1. The amount appropriated in section 22 of Public Law",
        "119-47 shall not exceed $2,500,000,000 for fiscal year 2026.",
        "SECTION 2. AUTHORIZATION OF APPROPRIATIONS.",
        "There is authorized to be appropriated $1,000,000,000, sub-",
        "ject to the availability of future appropriations.",
    )
    normalized, record = normalize_gpo_pages(text)
    result = normalized[0]

    assert record.line_numbers is False
    assert "section 22" in result
    assert "$2,500,000,000" in result
    assert not re.search(r"  ", result)
    assert "Be it enacted" in result

    # Preserved BillTrax scope: no gutter number corroborates the wrap, so it
    # is left split rather than guessed at.
    assert "sub-" in result
    assert "subject" not in result
    assert record.hyphen_rejoin_count == 0


# ---------------------------------------------------------------------------
# Bare-digit stripping is evidence-gated per page (not one of BillTrax's 27;
# added directly for non-GPO safety -- see the module docstring)
# ---------------------------------------------------------------------------


def test_non_gpo_page_keeps_a_standalone_digit_line_without_gpo_evidence():
    """A standalone 1-4 digit line is not GPO-specific by its own text -- it could be a year or a footnote
    number -- so without this page's own VerDate footer or the document-level gutter layout it must not be
    dropped."""
    text = page(
        "The fiscal year in question is as follows.",
        "2024",
        "Total appropriations remained unchanged from the prior year.",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "2024" in normalized[0].split("\n")
    assert record.pages[0].bare_page_number_lines == 1
    assert record.pages[0].bare_page_number_evidence == "none"


def test_gpo_page_strips_the_same_standalone_digit_line():
    """Same shape as above, but this page carries a VerDate footer -- GPO evidence -- so the otherwise
    identical standalone digit line is stripped (``bare_page_number_evidence`` ``"page_footer"``)."""
    text = page(
        "The fiscal year in question is as follows.",
        "2024",
        "Total appropriations remained unchanged from the prior year.",
        "VerDate Sep 11 2014",
        "00:08 Jan 21, 2026",
    )
    normalized, record = normalize_gpo_pages(text)
    assert "2024" not in normalized[0].split("\n")
    assert record.pages[0].bare_page_number_lines == 1
    assert record.pages[0].bare_page_number_evidence == "page_footer"


# ---------------------------------------------------------------------------
# Real-document fixtures: measured GpoCleanupRecord counts
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> tuple[str, ...]:
    return tuple(json.loads((FIXTURES / f"{name}.json").read_text()))


def test_introduced_house_bill_fixture_measured_counts():
    """BILLS-119hr4727ih: 1 page, genuinely gutter-numbered (6 of its 19 content lines carry line numbers 1-6, a
    consecutive run starting at 1) and under ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT``, so the structural run
    test clears ``line_numbers`` and both real hyphen wraps ("Representa-/tives", "relat-/ing") rejoin; one GPO
    footer, no small-caps splits, no running footer (not an RFS/RDS/PCS print)."""
    pages = _load_fixture("BILLS-119hr4727ih")
    normalized, record = normalize_gpo_pages(pages)

    assert record == GpoCleanupRecord(
        line_numbers=True,
        gpo_footers=True,
        spacing_normalized=True,
        running_footer_lines=0,
        small_caps_merges=0,
        hyphen_rejoin_count=2,
        pages=(
            GpoPageCleanup(
                page=1,
                verdate_footer_lines=1,
                footer_continuation_lines=8,
                dsk_user_lines=1,
                running_footer_lines=0,
                bare_page_number_lines=6,
                bare_page_number_evidence="both",
                bullet_bill_lines=0,
                content_lines=19,
                small_caps_merges=0,
                hyphen_rejoin_count=2,
            ),
        ),
    )

    assert "Representatives of the United States" in normalized[0]
    assert "relating to restoring public service loan forgiveness" in normalized[0]
    assert "VerDate" not in normalized[0]
    assert not re.search(r"^\d+$", normalized[0], re.MULTILINE)


def test_enrolled_bill_fixture_measured_counts():
    """BILLS-119sconres1enr: 1 page, not gutter-numbered (no line carries a corroborating digit, so neither the
    ratio nor the structural run test finds anything), no GPO footer, no rejoin -- its own genuine hyphen wraps
    ("concur-ring),", "President-elect") stay split."""
    pages = _load_fixture("BILLS-119sconres1enr")
    normalized, record = normalize_gpo_pages(pages)

    assert record == GpoCleanupRecord(
        line_numbers=False,
        gpo_footers=False,
        spacing_normalized=True,
        running_footer_lines=0,
        small_caps_merges=0,
        hyphen_rejoin_count=0,
        pages=(
            GpoPageCleanup(
                page=1,
                verdate_footer_lines=0,
                footer_continuation_lines=0,
                dsk_user_lines=0,
                running_footer_lines=0,
                bare_page_number_lines=0,
                bare_page_number_evidence="none",
                bullet_bill_lines=0,
                content_lines=30,
                small_caps_merges=0,
                hyphen_rejoin_count=0,
            ),
        ),
    )

    assert "concur-\nring)," in normalized[0]
    assert "President-\nelect" in normalized[0]


def test_committee_report_fixture_measured_counts():
    """CRPT-119hrpt105: 3 pages, not gutter-numbered (committee-report prose never is), a GPO footer with its
    multi-line continuation and job-code line on every page, no rejoin -- hyphen-wrapped headings
    ("DEPART-MENT", "RE-PORTED") stay split. Pages 2 and 3 each carry a real page-number header stripped by that
    page's own VerDate footer, since the document-level gutter layout is False."""
    pages = _load_fixture("CRPT-119hrpt105")
    normalized, record = normalize_gpo_pages(pages)

    assert record.line_numbers is False
    assert record.gpo_footers is True
    assert record.small_caps_merges == 0
    assert record.hyphen_rejoin_count == 0
    assert len(record.pages) == 3
    for page_record in record.pages:
        assert page_record.verdate_footer_lines == 1
        assert page_record.footer_continuation_lines == 8
        assert page_record.dsk_user_lines == 1

    # Pages 2 and 3 each carry a real page-number header ("2", "3") that
    # must still be stripped -- by this page's own VerDate footer, since the
    # document-level gutter layout is False (record.line_numbers above).
    assert record.pages[1].bare_page_number_lines == 1
    assert record.pages[1].bare_page_number_evidence == "page_footer"
    assert record.pages[2].bare_page_number_lines == 1
    assert record.pages[2].bare_page_number_evidence == "page_footer"
    assert "\n2\n" not in normalized[1]
    assert "\n3\n" not in normalized[2]

    assert "DEPART-\nMENT OF THE TREASURY" in normalized[0]
    assert "RE-\nPORTED FROM THE COMMITTEE ON RULES" in normalized[0]


def test_rfs_bill_fixture_measured_counts():
    """BILLS-119hr1009rfs: the fourth fixture, added to exercise the ported unbulleted running-footer rule (B2)
    since none of the other three is a PCS/RDS/RFS print. Page 2 opens with the unbulleted "HR 1009 RFS"
    footer, stripped once; page 1's run is only 2 long but page 2's is 10, enough on its own (aggregated the way
    ``page_has_footer`` is), and both real wraps ("Representa-/tives", "reg-/ulation") rejoin."""
    pages = _load_fixture("BILLS-119hr1009rfs")
    normalized, record = normalize_gpo_pages(pages)

    assert record == GpoCleanupRecord(
        line_numbers=True,
        gpo_footers=True,
        spacing_normalized=True,
        running_footer_lines=1,
        small_caps_merges=0,
        hyphen_rejoin_count=2,
        pages=(
            GpoPageCleanup(
                page=1,
                verdate_footer_lines=1,
                footer_continuation_lines=8,
                dsk_user_lines=1,
                running_footer_lines=0,
                bare_page_number_lines=2,
                bare_page_number_evidence="both",
                bullet_bill_lines=0,
                content_lines=13,
                small_caps_merges=0,
                hyphen_rejoin_count=1,
            ),
            GpoPageCleanup(
                page=2,
                verdate_footer_lines=1,
                footer_continuation_lines=8,
                dsk_user_lines=1,
                running_footer_lines=1,
                bare_page_number_lines=11,
                bare_page_number_evidence="both",
                bullet_bill_lines=0,
                content_lines=15,
                small_caps_merges=0,
                hyphen_rejoin_count=1,
            ),
        ),
    )

    assert "HR 1009 RFS" not in normalized[1]
    assert "Representatives of the United States" in normalized[0]
    assert "map, regulation, document" in normalized[1]
    assert "SECTION 1. PAUL PIPERATO POST OFFICE BUILDING." in normalized[1]
    assert "VerDate" not in normalized[0]
    assert "VerDate" not in normalized[1]
    assert not re.search(r"^\d+$", normalized[1], re.MULTILINE)


# ---------------------------------------------------------------------------
# Concordance checks
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"\s+", text) if token]


def _concordance(text_a: str, text_b: str) -> float:
    """BillTrax's own measure (validate-pdf-pdf-concordance.ts): the fraction
    of tokens in ``a`` matched, position-insensitively, against ``b``,
    divided by the larger token count."""
    tokens_a, tokens_b = _tokenize(text_a), _tokenize(text_b)
    if not tokens_a and not tokens_b:
        return 1.0
    remaining: dict[str, int] = {}
    for token in tokens_b:
        remaining[token] = remaining.get(token, 0) + 1
    matched = 0
    for token in tokens_a:
        if remaining.get(token, 0) > 0:
            matched += 1
            remaining[token] -= 1
    return matched / max(len(tokens_a), len(tokens_b))


@pytest.mark.parametrize(
    "fixture_name", ["BILLS-119hr4727ih", "BILLS-119sconres1enr", "CRPT-119hrpt105", "BILLS-119hr1009rfs"]
)
def test_pdf_pdf_concordance_normalizing_the_same_extraction_twice_is_deterministic(fixture_name):
    """PDF-vs-PDF self-comparison, offline half: BillTrax's scenario 1 (~100% expected) re-run over the same
    captured extraction rather than a second live download -- normalizing twice is deterministic and the token
    concordance is 1.0; the ``integration`` test below is the live two-extractions version."""
    pages = _load_fixture(fixture_name)
    normalized_a, record_a = normalize_gpo_pages(pages)
    normalized_b, record_b = normalize_gpo_pages(pages)
    assert normalized_a == normalized_b
    assert record_a == record_b
    concordance = _concordance("\n".join(normalized_a), "\n".join(normalized_b))
    assert concordance == 1.0


def _matching_xml_text_fixture(package_id: str) -> Path | None:
    """A bill-text XML fixture for the same package, if one happens to exist."""
    match = re.fullmatch(r"BILLS-(\d+)([a-z]+)(\d+)([a-z0-9]+)", package_id)
    if match is None:
        return None
    congress, bill_type, number, version = match.groups()
    candidate = GOVINFO_BILLS / f"text-{congress}{bill_type}{number}{version}.xml"
    return candidate if candidate.exists() else None


@pytest.mark.parametrize("fixture_name", ["BILLS-119hr4727ih", "BILLS-119sconres1enr", "BILLS-119hr1009rfs"])
def test_pdf_xml_concordance_against_the_sidecars_bill_text_sample(fixture_name):
    """PDF-vs-XML: normalized PDF text and the bill's own XML text agree above BillTrax's retroactive
    criterion ("beta.5 >=95%" mean heading concordance). Skipped per fixture when no matching bill-text XML
    sample exists in this repo or the sidecar, with the reason stated rather than silently passed."""
    xml_path = _matching_xml_text_fixture(fixture_name)
    if xml_path is None:
        pytest.skip(
            f"no bill-text XML fixture or sidecar sample for {fixture_name}; "
            f"tests/fixtures/govinfo_bills/ has XML text only for other bills "
            f"(119hr6028ih/eh, 119hjres25enr, 119s5enr)"
        )
    pages = _load_fixture(fixture_name)
    normalized, _record = normalize_gpo_pages(pages)
    xml_text = xml_path.read_text()
    concordance = _concordance("\n".join(normalized), xml_text)
    assert concordance >= 0.95


# ---------------------------------------------------------------------------
# Integration: one bounded, keyless, live refetch of the smallest fixture
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_ih_bill_pdf_matches_the_captured_fixture_after_independent_extraction():
    """Bounded (one ~220 KB PDF), keyless live refetch from the URL tests/fixtures/gpo_pdf_text/README.md
    states; its independent extraction doubles as the live PDF-vs-PDF concordance check -- agreement is evidence
    the normalizer's output is not an artifact of one particular PyMuPDF run."""
    import httpx

    from spicy_docs.extraction import DocumentExtractor, NativeText
    from spicy_docs.sources.govinfo.bodies import package_body_locator

    url = package_body_locator("BILLS-119hr4727ih", "pdf")
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
    response.raise_for_status()
    assert str(response.url) == url
    payload = response.content
    assert len(payload) <= 24 * 1024 * 1024
    assert hashlib.sha256(payload).hexdigest() == "3f3620d2c4f597a0a04a930e79977f5fec6a37a3ecc9e0765c40aa994a209a3d"

    live_pages = tuple(
        result.text for result in DocumentExtractor(NativeText()).extract(payload, media_type="application/pdf")
    )
    fixture_pages = _load_fixture("BILLS-119hr4727ih")
    assert live_pages == fixture_pages

    live_normalized, live_record = normalize_gpo_pages(live_pages)
    fixture_normalized, fixture_record = normalize_gpo_pages(fixture_pages)
    assert live_normalized == fixture_normalized
    assert live_record == fixture_record
