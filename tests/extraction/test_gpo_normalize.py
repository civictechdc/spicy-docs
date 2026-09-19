"""Port of BillTrax's pdf-normalize.test.ts (27 cases, 9 describes), re-derived.

BillTrax's fixtures assumed pdf-parse's line layout, where a GPO gutter line
number is glued onto the end of its content line ("Representa-1") and a GPO
print-shop footer is one fused line. This repo's PDF extraction is PyMuPDF's
line-grouped native text (``extraction.DocumentExtractor(extraction.
NativeText())``, see ``extraction/pages.py``), which never glues a gutter
number onto content text -- it emits the number as its own physical line
immediately after the content line -- and splits GPO's footer across several
physical lines. Every fixture below is rewritten to that shape; each test
name and docstring says what changed and why (see also
``gpo_normalize``'s module docstring and ``docs/extraction-gpo.md``).

Padded ported cases use ``gutter_filler`` (defined below) to clear
``gpo_normalize._MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT``, a floor ported later
from DeltaTrack (see that constant's docstring and
``docs/research/deltatrack-upstream-issues-2026-09-19.md``, claim B3): most of
BillTrax's own tiny fixtures sit under it, so padding keeps them exercising
what they always did (the adjacency/rejoin mechanism) rather than the floor.

Three more test groups follow the ported 27:
 - real-document fixtures from ``tests/fixtures/gpo_pdf_text/`` with their
   measured ``GpoCleanupRecord`` counts asserted exactly -- three from
   BillTrax's original port plus a fourth (``BILLS-119hr1009rfs``) added to
   exercise the ported running-footer rule, which none of the first three
   carries;
 - a PDF-vs-PDF concordance check (normalizing the same extracted text twice
   is deterministic) and a PDF-vs-XML concordance check (skipped per fixture
   when no matching bill-text XML sample exists, per the task's rule);
 - one ``integration``-marked, bounded, keyless live refetch of the smallest
   fixture's own PDF, which also serves as a *real* two-independent-
   extractions PDF-vs-PDF concordance check.
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
    """``n`` extra gutter-numbered content lines.

    ``gpo_normalize._MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` (ported from
    DeltaTrack's ``_MIN_LINES_FOR_GUARD``, see that constant's docstring)
    withholds the layout verdict below 50 content lines, which most of
    BillTrax's own small ported fixtures sit under. Appending this keeps a
    test's line count realistic -- clearing the floor -- without disturbing
    what it actually asserts; each line is followed by its own bare 1-2 digit
    gutter number, keeping the numbered/content ratio high the way a real
    numbered page's does.
    """
    filler: list[str] = []
    for i in range(n):
        filler.append(f"Additional statutory text for measurement, clause {i}.")
        filler.append(str((i % 25) + 1))
    return tuple(filler)


def unnumbered_filler(n: int) -> tuple[str, ...]:
    """``n`` plain content lines with no adjacent gutter number at all --
    the shape a resolution's unnumbered "Whereas" preamble takes (see
    ``test_true_at_or_above_the_floor_when_a_long_unnumbered_preamble_
    dilutes_the_ratio_but_a_page_shows_a_real_run`` below), used to push a
    synthetic document's content-line count at or above the floor while
    driving its numbered/content ratio down, independently of
    ``gutter_filler``, which keeps that ratio high.
    """
    return tuple(f"Whereas clause number {i} of the preamble recites a finding." for i in range(n))


# ---------------------------------------------------------------------------
# is_gpo_layout (BillTrax: detectLineNumbered) -- 4 cases
# ---------------------------------------------------------------------------


def test_true_when_content_lines_are_each_followed_by_a_bare_gutter_number():
    """Adapted: pdf-parse glued the number onto the line ("Representa-1");
    PyMuPDF emits it as the next physical line. The detector now reads that
    adjacency instead of a trailing-digit suffix. Below
    ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` (5 content lines here), the
    ratio alone is not enough evidence, but this excerpt's gutter digits are
    a consecutive run starting at 1 (1, 2, 3, 4, 5) -- real GPO numbering
    restarts at 1 on every page, so a genuinely short numbered bill does not
    need to be padded out to look like a long one to be recognized (see
    ``_starts_consecutive_run_from_one``); contrast
    ``test_false_for_a_run_that_does_not_start_at_one`` and
    ``test_false_for_a_run_split_across_pages_that_never_restarts_at_one``
    below, where the digits exist but do not form that run."""
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
    """New (B3, ``docs/research/deltatrack-upstream-issues-2026-09-19.md``,
    refined in review): a page whose gutter digits are 1, 2, 4 -- not a
    consecutive run -- is not GPO-numbered evidence below the floor, even
    though the ratio (3/3) is as strong as it can be. The prefix run breaks
    at the third digit (index 2 expects 3, sees 4), so its length is 2, under
    ``_MIN_GUTTER_RUN_LENGTH``."""
    text = page("enacted", "1", "by the", "2", "Senate", "4")
    assert is_gpo_layout(text) is False


def test_false_for_a_run_split_across_pages_that_never_restarts_at_one():
    """New (B3, refined in review): five footnote-style markers across two
    pages, numbered straight through (1, 2 on page one; 3, 4, 5 on page two)
    rather than restarting at 1 on the second page the way GPO's own gutter
    numbering does. Neither page alone has a consecutive run starting at 1 of
    at least ``_MIN_GUTTER_RUN_LENGTH``: page one's run (1, 2) is one short,
    and page two's digits (3, 4, 5) never reach 1 at all. This is the
    residual the run test cannot see from a single page in isolation --
    stated in ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT``'s docstring."""
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
    """Adapted: two content lines, each still followed by its own gutter
    number line, rather than two inline-numbered lines."""
    text = page("enacted", "1", "Section", "2")
    assert is_gpo_layout(text) is False


def test_filters_a_tail_verdate_footer_and_a_real_2025_job_code_line_before_counting_content():
    """Adapted: the footer sits at the real tail of the page (a VerDate line
    is always followed only by more footer, never real content -- see
    test_strips_the_multiline_verdate_footer_* below), and the job-code line
    uses a real 2025 shape (no literal "DSK" prefix, no trailing "$") -- see
    test_strips_job_code_lines_* below."""
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
    """New (gap B6 corpus validation): a strict ``> 0.3`` made two real
    GPO-numbered documents (``BILLS-119sjres141is``, ``BILLS-119hconres11eh``)
    fail on a ratio that landed exactly at 30%, even with a real per-page
    consecutive run confirming genuine numbering. Reproduced synthetically:
    10 content lines, 3 numbered (a valid run, 1-2-3) -- ratio exactly 0.3."""
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
    """New (gap B6 corpus validation): the per-page run test used to run
    only below the floor, gated behind the same ratio check. A real 10-page
    House concurrent resolution (``BILLS-119hconres26ih``) has a six-page
    unnumbered "Whereas" preamble before its "Resolved" operative text
    begins, diluting its whole-document ratio to 0.268 despite four pages
    of unambiguous gutter numbering -- one of them a run 25 long. Reproduced
    synthetically: 55 unnumbered preamble lines (``unnumbered_filler``)
    followed by a short numbered "Resolved" section with its own real run of
    5 -- ratio 5/60 = 0.083, far under 0.3, but the run test now decides the
    verdict independently once the document clears the floor."""
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
    """Regression guard for the more conservative half of the fix above:
    below the floor, both signals stay required together, unchanged from
    the original design (BillTrax's own concern, quoted in
    ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT``'s docstring: "a two-page memo
    should not be declared GPO-numbered on three lines just because they
    happen to be numbered"). Only three of this excerpt's seventeen content
    lines are gutter-adjacent; even though those three form a valid run from
    1, the ratio (3/17 = 0.176) sits well under 0.3, and unlike the case
    above this excerpt never clears the 50-line floor, so the run alone
    must not decide it."""
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


# ---------------------------------------------------------------------------
# GPO metadata stripping -- 5 cases
# ---------------------------------------------------------------------------


def test_strips_the_multiline_verdate_footer_pymupdf_splits_across_lines():
    """Re-derived: pdf-parse's single fused footer line becomes ~9 physical
    lines under PyMuPDF (time+date, Jkt, PO, Frm, Fmt, Sfmt, file path),
    always the tail of the page -- so the whole tail is dropped once VerDate
    matches, not just the line VERDATE_RE itself matches."""
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
    """Re-derived: BillTrax's DSK_USER_RE required a literal "DSK" machine-id
    prefix and a trailing "$"; real 2025 GovInfo output has neither
    ("ssavage on LAPJG3WLY3PROD with BILLS"). The rule is generalized to any
    machine id ending "PROD" and any trailing job-code token."""
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
    """This page carries no VerDate/DSK/running-footer evidence, so digit
    stripping here depends entirely on the document-level layout verdict --
    cleared by the structural run test, since the three content lines'
    gutter digits (1, 2, 3) are a consecutive run starting at 1 (see
    ``_starts_consecutive_run_from_one``)."""
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
    """New (B2, ``docs/research/deltatrack-upstream-issues-2026-09-19.md``):
    ported verbatim from DeltaTrack's ``_RUNNING_FOOTER``
    (``parsers/pdf_text.py:68-71``, built for its own #140) -- a print-stage
    tag like "HR 5895 PCS" that GPO does not bullet, so neither
    ``_BULLET_BILL_RE`` above nor BillTrax's original rule catches it. Self-
    evidencing and independent of the layout-verdict floor (unlike
    gutter-number/hyphen handling elsewhere in this file), but not
    unconditional: it strips only when the *next* line is not itself a bare
    gutter number -- see
    ``test_keeps_a_running_footer_shaped_content_line_when_followed_by_its_
    own_gutter_number`` below for why."""
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
    """The running-footer pattern matches a WHOLE line, like upstream's own
    ``re.MULTILINE`` anchors -- prose that happens to mention a bill number
    is not a print-stage tag and must survive."""
    text = page("This section amends H.R. 1234 PCS references in prior law.")
    normalized, _record = normalize_gpo_pages(text)
    assert "H.R. 1234 PCS" in normalized[0]


def test_keeps_a_running_footer_shaped_content_line_when_followed_by_its_own_gutter_number():
    """Refined in review: a genuine running footer is page furniture followed
    by prose (as in BILLS-119hr1009rfs's real "HR 1009 RFS"), never by its
    own gutter number. Reproduced without the guard: a real numbered content
    line that happens to share the running-footer's shape -- unlikely in
    practice, but not impossible in a bill discussing its own designation --
    was being deleted along with its digit. The next-line check restores it
    as ordinary gutter-numbered content instead."""
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
    """Adapted: BillTrax distinguished a space-separated suffix from a
    hyphen-embedded one on the same line. Under PyMuPDF the number is never
    attached to the line at all, so that distinction does not apply -- there
    is only "a bare number line follows". This excerpt's own digits (2, 3, 4)
    continue mid-document rather than starting at 1, so they do not clear the
    structural run test on their own; padded with ``gutter_filler`` (see that
    helper) past the minimum-content-line floor instead, where the ratio
    alone decides."""
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
    """This page carries no VerDate/DSK/running-footer evidence, and its own
    digits (17-20) do not start at 1, so digit stripping depends entirely on
    the document-level ratio verdict; padded with ``gutter_filler`` (see that
    helper) past the minimum-content-line floor to clear it."""
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
    """ENR text has no gutter-number lines at all, so section references and
    dollar amounts that happen to contain digits are never touched -- this
    rule only ever drops a line that is *entirely* a 1-4 digit number."""
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
    """Rejoin only runs once the document layout verdict is True -- cleared
    here by the structural run test (gutter digits 1, 2, 3, a consecutive
    run starting at 1), below the minimum-content-line floor."""
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
    """This excerpt's own digits (18-20) do not start at 1, so padded with
    ``gutter_filler`` (see that helper) past the minimum-content-line floor,
    where the ratio alone decides."""
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
    """Gutter digits 1, 2, 3, 4 -- a consecutive run starting at 1 -- clear
    the structural run test below the minimum-content-line floor."""
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
    """Gutter digits 1, 2, 3 clear the structural run test below the
    minimum-content-line floor, so this fixture's one real rejoin is
    counted."""
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
    """Doubled internal spaces from kerning were measured at zero
    occurrences under PyMuPDF across all three real fixtures in
    tests/fixtures/gpo_pdf_text/ -- the rule is kept for compatibility (like
    BillTrax's own always-true spacingNormalized field) and exercised here
    with a synthetic case rather than a real one."""
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
    """New: not one of BillTrax's 27 (pdf-parse's fixtures never exercised
    it), added directly from real data -- CRPT-119hrpt105 renders a double
    quote as two adjacent single curly quotes
    ("\u2018\u2018Review of Final Rule ...\u2019\u2019"), which the
    single-curly-quote replacement alone leaves as two straight single
    quotes. Same collapse DeltaTrack's independently-derived, extractor-
    agnostic ``normalize_glyphs`` reaches (parsers/pdf_text.py:
    ``text.replace("''", '"')``)."""
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
    """Adapted: gutter numbers on their own lines, a real 2025-shaped
    job-code line, and the footer moved to the true tail of the page --
    running header first, footer last, matching a real page's top-to-bottom
    order (a VerDate line is always the last thing PyMuPDF emits for a page;
    see the two re-derived rules above). This excerpt's own digit sequence
    (16, 17, 1, 2, 3, 4, 5 -- an appropriations heading's line numbers ahead
    of the bill text's own 1-5) does not start at 1, so it does not clear
    the structural run test on its own; padded with ``gutter_filler`` (see
    that helper), inserted before the VerDate line since anything after it is
    swallowed into the footer's tail, not counted as content."""
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
    """Adapted: BillTrax's original ENR fixture had no hyphen-wrapped word,
    so it never exercised the scope decision baked into normalizePdfText --
    hyphen-rejoin only runs for a document with gutter numbers, because
    without one there is no signal to tell a print-wrap hyphen from a real
    hyphenated compound word ending a line by coincidence. The real ENR
    fixture (tests/fixtures/gpo_pdf_text/BILLS-119sconres1enr.json) does
    contain genuine wraps ("concur-\\nring),", "President-\\nelect"), and
    they stay split; this makes that BillTrax-original scope explicit."""
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
    """A standalone 1-4 digit line is not GPO-specific by its own text -- it
    could be a year or a footnote number. Without this page's own VerDate
    footer or the document-level gutter layout, it must not be dropped."""
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
    """Same shape as above, but this page carries a VerDate footer -- GPO
    evidence -- so the otherwise-identical standalone digit line is
    stripped."""
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
    """BILLS-119hr4727ih: 1 page, genuinely gutter-numbered (6 of its 19
    content lines are each followed by their own line number, 1-6, a
    consecutive run starting at 1) and under
    ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` (50), so it is the structural
    run test, not the ratio alone, that clears ``line_numbers`` here (see
    ``_starts_consecutive_run_from_one``) -- both real hyphen wraps
    ("Representa-/tives", "relat-/ing") correctly rejoin. One GPO footer, no
    small-caps splits, no running footer (not an RFS/RDS/PCS print)."""
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
    """BILLS-119sconres1enr: 1 page, not gutter-numbered (no line carries a
    corroborating digit at all, so neither the ratio nor the structural run
    test finds anything), no GPO footer on this page, no rejoin (see the ENR
    scope test above) -- its own genuine hyphen wraps ("concur-ring),",
    "President-elect") stay split."""
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
    """CRPT-119hrpt105: 3 pages, not gutter-numbered (committee-report prose
    is never GPO line-numbered), a GPO footer on every page including its
    own multi-line continuation and job-code line, no rejoin -- its own
    hyphen-wrapped headings ("DEPART-MENT", "RE-PORTED") stay split, matching
    docs/research/billtrax-raw-data-2026-09-19.md §6's own conclusion that
    running the normalizer here is "safe" precisely because its line-number
    branch stays off."""
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
    """BILLS-119hr1009rfs: the fourth fixture, added to exercise the ported
    unbulleted running-footer rule (B2,
    ``docs/research/deltatrack-upstream-issues-2026-09-19.md``) -- none of
    the other three fixtures is a PCS/RDS/RFS print stage. 2 pages, a
    Senate-received postal-naming act: page 2 opens with the unbulleted
    running footer "HR 1009 RFS" (no bullet character, so neither
    ``_BULLET_BILL_RE`` nor BillTrax's original rule would have caught it),
    stripped once by the new rule. Genuinely gutter-numbered (12 of its 28
    content lines are each followed by their own line number) and under
    ``_MIN_CONTENT_LINES_FOR_LAYOUT_VERDICT`` (50), so the structural run
    test decides: page 1's own run is only 2 long (1, 2 -- insufficient
    alone), but page 2's is 10 long (1 through 10), which is enough on its
    own (aggregated the same way ``page_has_footer`` is -- any one page's
    evidence suffices). Both real hyphen wraps rejoin: "Representa-/tives"
    on page 1, and "reg-/ulation" on page 2 (missed in an earlier pass over
    this fixture -- ``(b) REFERENCES.-- Any reference in a law, map, reg-``
    wraps to "regulation")."""
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
    """PDF-vs-PDF self-comparison, offline half: BillTrax's scenario 1 (self-
    comparison, ~100% expected) re-run over the same captured extraction
    rather than a second live download -- see the ``integration`` test below
    for the live two-extractions version of this same check."""
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
    """PDF-vs-XML: normalized PDF text and the bill's own XML text agree
    above BillTrax's retroactive criterion (validate-pdf-xml-concordance.ts:
    "beta.5 >=95%" mean heading concordance). None of this module's three
    bill fixtures has a matching bill-text XML sample in this repo or in the
    sidecar (docs/research/billtrax-raw-data-2026-09-19.json only recorded
    line-count statistics for the first two, and knows nothing of the
    fourth, added later) -- skipped per the task's own fallback, with the
    reason stated below rather than silently passed."""
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
    """Bounded (one ~220 KB PDF), keyless, from the URL
    tests/fixtures/gpo_pdf_text/README.md states. Doubles as the live half of
    the PDF-vs-PDF concordance check: this extraction and the one captured
    into the fixture are independent (different process, same source bytes),
    so agreement here is evidence the normalizer's output is not an artifact
    of one particular PyMuPDF run."""
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
