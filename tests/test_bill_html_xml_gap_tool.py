"""The HTML/XML gap tool renders its block from the saved measurement, and its rules hold on print samples.

Two kinds of case, kept apart. The render cases prove the committed sidecar and
the document's generated block agree, so the numbers a reader sees are the
numbers that were measured. The rule cases run the scanner over small
constructed print samples spelled the way GPO spells them, so a rule that
regressed is named by the case rather than by a moved percentage: every one
reproduces a convention the run measured, and the docstring says which.

No case makes a network request or reads a publisher body; the corpus itself
lives outside this repository with its receipt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis.bill_html_xml_gap import (
    KINDS,
    MARK_END,
    MARK_START,
    OBSERVATIONS,
    SELECTION,
    aggregate,
    dtd_content_models,
    dtd_form_particles,
    fidelity,
    normalized_words,
    precision_recall,
    render,
    scan_html,
    select_pairs,
    sequence_check,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs" / "research" / "bill-html-xml-gap-2026-09-19.json"
DOCUMENT = ROOT / "docs" / "research" / "bill-html-xml-gap-2026-09-19.md"


@pytest.fixture(scope="module")
def measures() -> dict:
    if not SIDECAR.exists():  # pragma: no cover - the sidecar is committed
        pytest.skip("no saved measurement")
    return json.loads(SIDECAR.read_text())


# --- the generated block is the saved measurement ---------------------------------------


def test_the_block_renders_from_the_sidecar_and_matches_the_document(measures: dict) -> None:
    """The committed block is exactly what the committed sidecar renders."""
    block = render(measures)
    assert block.startswith(MARK_START) and block.endswith(MARK_END)
    text = DOCUMENT.read_text()
    start, end = text.find(MARK_START), text.find(MARK_END)
    assert start >= 0 and end > start
    assert text[start : end + len(MARK_END)] == block


def test_every_paired_document_has_a_row_and_a_digest(measures: dict) -> None:
    block = render(measures)
    assert len(measures["paired"]) == 30
    for document in measures["paired"]:
        assert f"`{document['packageId']}`" in block
        assert len(document["xmlSha256"]) == 64 and len(document["htmlSha256"]) == 64


def test_the_block_reports_every_structure_kind_and_observation(measures: dict) -> None:
    block = render(measures)
    for kind in KINDS:
        assert f"| {kind} |" in block
    for _, label in OBSERVATIONS:
        assert label in block


def test_the_sidecar_carries_no_credential(measures: dict) -> None:
    """The one check AGENTS.md makes non-negotiable, run against the committed bytes."""
    text = SIDECAR.read_text()
    assert "api_key=" not in text
    assert "X-Api-Key" not in text.lower().replace("x-api-key", "X-Api-Key")
    assert "api.congress.gov/v3/bill" not in text


def test_the_document_states_the_retained_receipt(measures: dict) -> None:
    assert "supply-2026-09-02/receipts/bill-html-xml-gap-2026-09-19" in render(measures)


def test_the_aggregate_is_recomputable_from_the_per_document_rows(measures: dict) -> None:
    """The summary is derived, not stored: recomputing it from the rows must agree.

    Compared through JSON, because that is the shape the sidecar holds: the
    word lists are tuples in memory and arrays on disk, and the check is about
    the numbers, not about which Python type carried them.
    """
    assert json.loads(json.dumps(aggregate(measures["paired"]))) == measures["aggregate"]


# --- the rules, on constructed print samples --------------------------------------------

# Spelled the way GPO spells them in the `htm` rendition, after
# `extraction.body_text` has normalized the quotes. Constructed, not captured:
# they establish what a rule does with a shape, never what the publisher serves.

UPPERCASE_BILL = """SECTION 1. SHORT TITLE.

    This Act may be cited as the "Example Act".

SEC. 2. FINDINGS.

    (a) In General.--The Congress finds as follows:
    (b) Effect.--Nothing changes.
"""

APPROPRIATIONS = """    Sec. 1201.  Any appropriations provided to the Department shall
be available.

    Sec. 2101. (a) In General.--Section 251 is amended.
    (b) Disaster funding.--Section 251(b) is amended.
"""

REPORTED_WITH_STRUCK = """<DELETED>SECTION 1. SHORT TITLE.</DELETED>

<DELETED>    (a) Amendment.--Section 1122 is amended.</DELETED>

SECTION 1. SHORT TITLE.

    (a) In General.--Section 1122 is amended.
"""

CONTENTS_LIST = """SEC. 2. TABLE OF CONTENTS.

    The table of contents for this Act is as follows:

                  DIVISION A--APPROPRIATIONS PROVISIONS

TITLE I--AGRICULTURE
Sec. 101. Something.
Sec. 102. Something else.

                  DIVISION A--APPROPRIATIONS PROVISIONS

TITLE I--AGRICULTURE

SEC. 101. SOMETHING.

    (a) In General.--Text.
"""

QUOTED_TERMS = """SEC. 2. ACCOUNTS.

    The Secretary shall transfer amounts between the
"Operation and Maintenance" and "Military Personnel" accounts for
the fiscal year, as needed.

SEC. 3. NEXT PROVISION.

    (a) In General.--Text.
"""

QUOTED_BLOCK = """SEC. 2. AMENDMENT.

    Section 319 is amended by inserting the following:

    "SEC. 319A. NEW SECTION.
    "(a) Prohibition.--It shall be unlawful.".

SEC. 3. NEXT PROVISION.

    (a) In General.--Text.
"""


def test_uppercase_headings_and_indented_subsections() -> None:
    """The commonest shape: `SEC. n.` at column 0, `(a)` at the four-space indent."""
    found = scan_html(UPPERCASE_BILL)
    assert [number for number, _ in found.sections] == ["1", "2"]
    assert found.subsections == [("2", "a"), ("2", "b")]
    assert [header for _, header in found.sections] == ["SHORT TITLE", "FINDINGS"]


def test_an_appropriations_run_in_heading_is_a_section() -> None:
    """39 of the 104 headings measured are this form; a rule knowing only the uppercase form loses them."""
    found = scan_html(APPROPRIATIONS)
    assert [number for number, _ in found.sections] == ["1201", "2101"]
    assert found.runin_sections == 2
    # The run-in form carries no catchline of its own, and its first subsection
    # opens on the heading line rather than under it.
    assert [header for _, header in found.sections] == ["", ""]
    assert found.subsections == [("2101", "a"), ("2101", "b")]
    assert found.inline_enum_headings == 1


def test_struck_text_is_read_like_live_text_and_counted_apart() -> None:
    """GPO's `<DELETED>` markers wrap a reported bill's superseded text; they arrive as text, not markup."""
    found = scan_html(REPORTED_WITH_STRUCK)
    assert [number for number, _ in found.sections] == ["1", "1"]
    assert found.struck_sections == 1
    # The marker sits outside the subsection's own indent, and never rides
    # along in the heading.
    assert found.subsections == [("1", "a"), ("1", "a")]
    assert [header for _, header in found.sections] == ["SHORT TITLE", "SHORT TITLE"]


def test_a_contents_list_contributes_no_section_and_no_banner() -> None:
    """A column-0 `Sec. n.` entry is the witness; banners above it are contents, not provisions."""
    found = scan_html(CONTENTS_LIST)
    assert [number for number, _ in found.sections] == ["2", "101"]
    assert found.toc_entries == 2
    # Both the DIVISION and the TITLE banner of the contents list are excluded;
    # only the body's own pair is kept.
    assert found.toc_banners == 2
    assert found.divisions == ["A"]
    assert found.titles == ["I"]


def test_an_inline_quoted_term_does_not_open_a_block() -> None:
    """The defect this rule exists for: a quote-opening prose line swallowed five headings before the lead-in rule."""
    found = scan_html(QUOTED_TERMS)
    assert found.quoted_blocks == 0
    assert found.quote_terms == 1
    assert [number for number, _ in found.sections] == ["2", "3"]


def test_a_colon_lead_in_opens_a_block_that_ends_at_its_close() -> None:
    found = scan_html(QUOTED_BLOCK)
    assert found.quoted_blocks == 1
    assert [number for number, _ in found.sections] == ["2", "3"]
    # The quoted SEC. 319A belongs to the law being amended, not to this bill.
    assert "319A" not in {number for number, _ in found.sections}


def test_a_block_whose_close_is_missed_stops_at_the_next_heading() -> None:
    """Without the stop rule an unclosed block runs to the end of the document."""
    unclosed = 'SEC. 2. AMENDMENT.\n\n    It is amended by inserting the following:\n\n    "SEC. 9. ORPHAN.\n\nSEC. 3. NEXT.\n\n    (a) In General.--Text.\n'
    found = scan_html(unclosed)
    assert [number for number, _ in found.sections] == ["2", "3"]
    assert found.subsections == [("3", "a")]


def test_the_body_anchor_falls_back_to_the_resolving_clause() -> None:
    """A simple resolution states no section heading at all, so its body begins at `Resolved,`."""
    resolution = "[Congressional Bills]\n\nWhereas something;\n\n    Resolved, That the Senate--\n            (1) does a thing.\n"
    found = scan_html(resolution)
    assert found.sections == []
    assert found.first_heading_line is None
    assert found.body_start == found.resolving_clause_line
    assert resolution.split("\n")[found.body_start].strip().startswith("Resolved,")


def test_banners_are_the_bracketed_lines_at_the_top_only() -> None:
    document = "[Congressional Bills 113th Congress]\n[From the U.S. Government Publishing Office]\n[H.R. 1 Introduced in House (IH)]\n\nSEC. 1. A.\n\n    Text [bracketed mid-document] here.\n"
    found = scan_html(document)
    assert len(found.banners) == 3
    assert [number for number, _ in found.sections] == ["1"]


# --- scoring ----------------------------------------------------------------------------


def test_precision_and_recall_are_multiset_agreement() -> None:
    """A repeated enumerator pairs only as often as both sides carry it."""
    row = precision_recall(["1", "2", "2"], ["1", "2"])
    assert (row["matched"], row["html"], row["xml"]) == (2, 3, 2)
    # Rounded where it is computed, so the sidecar and the rendered table carry
    # the same figure rather than one rounding the other's full precision.
    assert row["precision"] == round(2 / 3, 4)
    assert row["recall"] == 1.0
    empty = precision_recall([], [])
    assert empty["precision"] is None and empty["recall"] is None


def test_normalization_treats_gpo_dashes_as_separators() -> None:
    """`--` is GPO's em dash in print and must not weld two words into one token."""
    assert normalized_words("In General.--The Congress") == ["in", "general", "the", "congress"]
    assert normalized_words("a—b") == ["a", "b"]


def test_fidelity_reports_the_words_only_one_side_has() -> None:
    row = fidelity(["a", "b", "c"], ["a", "b"])
    assert row["ratio"] == pytest.approx(0.8)
    assert row["htmlOnly"] == {"count": 1, "top": [("c", 1)]}
    assert row["xmlOnly"]["count"] == 0


def test_sequence_check_counts_restarts_and_repeats() -> None:
    """A division restarts section numbering; the check reports it rather than refusing it."""
    assert sequence_check(["1", "2", "1", "2"]) == {"nonIncreasing": 1, "duplicates": 2}
    assert sequence_check(["1", "2", "3"]) == {"nonIncreasing": 0, "duplicates": 0}


# --- corpus selection and the DTD --------------------------------------------------------


def test_selection_takes_the_declared_files_per_listing() -> None:
    """Version codes by descending file count, each at the median then the 95th percentile."""
    entries = [
        {"fileExtension": "xml", "justFileName": f"BILLS-113hr{n}{code}.xml", "size": n * 100}
        for code, count in (("ih", 20), ("enr", 10), ("rh", 5))
        for n in range(1, count + 1)
    ] + [{"fileExtension": "zip", "justFileName": "BILLS-113-1-hr.zip", "size": 9}]
    picks = select_pairs(entries)
    assert len(picks) == SELECTION.picks_per_listing
    assert len(set(picks)) == len(picks)
    # Three codes at two quantiles each: the commonest code leads, and the
    # first pass takes one of every code before the second pass runs.
    assert picks[0].endswith("ih")
    assert {pick.removeprefix("BILLS-113hr").lstrip("0123456789") for pick in picks} == {"ih", "enr", "rh"}


def test_selection_stops_when_a_listing_has_fewer_codes_than_picks() -> None:
    """A listing with one version code yields its two quantiles, not a padded six."""
    entries = [{"fileExtension": "xml", "justFileName": f"BILLS-113hr{n}ih.xml", "size": n * 100} for n in range(1, 21)]
    picks = select_pairs(entries)
    assert len(picks) == len(SELECTION.quantiles)
    assert len(set(picks)) == len(picks)


def test_selection_skips_a_name_the_package_grammar_refuses() -> None:
    entries = [
        {"fileExtension": "xml", "justFileName": "BILLS-113hr1ih.xml", "size": 10},
        {"fileExtension": "xml", "justFileName": "not-a-package.xml", "size": 10},
    ]
    assert select_pairs(entries) == ["BILLS-113hr1ih"]


def test_dtd_reading_names_the_required_form_children() -> None:
    """The requirement comes from the publisher's DTD, not from a list kept in the tool."""
    dtd = (
        '<!ENTITY % form-model   "distribution-code?, calendar?, congress, session, '
        'legis-num, action*, legis-type, official-title" >\n'
        "<!ELEMENT  form  (%form-model;)+ >\n"
        "<!ELEMENT  metadata  (dublinCore) >\n"
    )
    particles = dtd_form_particles(dtd)
    assert particles["congress"] is True
    assert particles["official-title"] is True
    assert particles["distribution-code"] is False
    assert particles["action"] is False
    assert dtd_content_models(dtd)["metadata"] == "(dublinCore)"
    assert dtd_form_particles(None) == {} and dtd_content_models(None) == {}


def test_the_measured_dtd_requires_the_fields_the_document_reports(measures: dict) -> None:
    """The judgment's required-field list is the DTD's, so it must still read that way."""
    particles = measures.get("dtdFormParticles") or {}
    if not particles:  # pragma: no cover - the DTD is pinned in the sidecar
        pytest.skip("no DTD in the saved measurement")
    required = {name for name, is_required in particles.items() if is_required}
    assert required == {"congress", "session", "legis-num", "current-chamber", "legis-type", "official-title"}
