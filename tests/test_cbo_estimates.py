"""The CBO letter rule: the recital gate, the located span, the publisher's reason, the version.

Every fixture is a bounded excerpt of a real GovInfo CRPT body; see
``tests/fixtures/cbo_estimates/README.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.interpretation.cbo_estimates import (
    ABSENCE_REASONS,
    ACCOMPANIES,
    CBO_ESTIMATE_RULE,
    CBO_ESTIMATE_RULE_VERSION,
    COVER_RECITAL,
    DIRECTOR_ATTRIBUTION,
    HEADINGS,
    LETTER_PATTERNS,
    CboEstimateError,
    LetterPattern,
    _rule_version,
    heading_blocks,
    read_cbo_estimate,
    recital_bill_id,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_estimates"


def body(package: str) -> str:
    return (FIXTURES / f"{package}.txt").read_text(encoding="utf-8")


# --- branch (a): the recital decides, and nothing else does -------------------------


@pytest.mark.parametrize(
    ("package", "declared"),
    [
        ("CRPT-118hrpt53", True),
        ("CRPT-118hrpt780", True),
        ("CRPT-118hrpt951", True),
        ("CRPT-118srpt298", True),
        ("CRPT-118hrpt18", False),
        ("CRPT-118hrpt111", False),
        ("CRPT-118srpt99", False),
    ],
)
def test_the_cover_recital_is_the_gate(package: str, declared: bool) -> None:
    finding = read_cbo_estimate(body(package))
    assert finding.report_states_estimate is declared
    assert finding.rule == CBO_ESTIMATE_RULE
    assert finding.rule_version == CBO_ESTIMATE_RULE_VERSION


def test_a_heading_over_a_missing_estimate_is_not_an_estimate() -> None:
    """CRPT-118hrpt18 prints a CBO heading and then says the estimate was not available."""
    finding = read_cbo_estimate(body("CRPT-118hrpt18"))
    assert finding.heading_rule == "cbo_estimate"
    assert finding.report_states_estimate is False
    assert finding.letter_span is None


def test_a_signature_and_a_dateline_outside_the_gate_are_not_a_letter() -> None:
    """CRPT-118srpt99's Director line is a witness list and its dateline is the committee's own."""
    text = body("CRPT-118srpt99")
    assert "Director, Congressional Budget Office." in text
    assert "Washington, DC, March 1, 2023." in text
    finding = read_cbo_estimate(text)
    assert finding.report_states_estimate is False
    assert finding.letter_span is None
    assert finding.signatory is None


def test_the_cover_states_the_bill_the_report_accompanies() -> None:
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.accompanies == "H.R. 801"
    assert recital_bill_id(finding, 118) == "118-hr-801"
    # The Congress is the package's, never the print's: the cover states none.
    assert recital_bill_id(finding, None) is None
    assert recital_bill_id(finding, 119) == "119-hr-801"


def test_a_cover_naming_no_measure_yields_no_bill_key() -> None:
    finding = read_cbo_estimate(body("CRPT-118srpt99"))
    assert finding.accompanies is None
    assert recital_bill_id(finding, 118) is None


# --- branch (b): the located span ---------------------------------------------------


@pytest.mark.parametrize(
    ("package", "heading_rule", "chars", "end_rule", "signatory"),
    [
        ("CRPT-118hrpt53", "cbo_estimate", 3791, "director_attribution", "Phillip L. Swagel"),
        ("CRPT-118hrpt780", "cbo_cost_estimate", 1488, "director_attribution", "Phillip L. Swagel"),
        ("CRPT-118hrpt951", "cost_estimate_prepared_by_cbo", 5869, "director_attribution", "Phillip L. Swagel"),
        ("CRPT-118srpt298", "cbo_cost_estimate", 3042, "next_heading_in_series", None),
    ],
)
def test_a_declared_letter_is_located_end_to_end(
    package: str, heading_rule: str, chars: int, end_rule: str, signatory: str | None
) -> None:
    text = body(package)
    finding = read_cbo_estimate(text)
    assert finding.heading_rule == heading_rule
    assert finding.letter_end_rule == end_rule
    assert finding.signatory == signatory
    start, end = finding.letter_span
    assert end - start == chars
    letter = text[start:end]
    assert finding.letter_sha256 == "sha256:" + hashlib.sha256(letter.encode("utf-8")).hexdigest()
    # The span opens on the heading the rule named, so it is re-readable from it.
    assert finding.heading.casefold() in re.sub(r"\s+", " ", letter[:120]).casefold()


def test_the_span_ends_after_the_attribution_not_before_it() -> None:
    text = body("CRPT-118hrpt780")
    finding = read_cbo_estimate(text)
    tail = text[finding.letter_span[0] : finding.letter_span[1]]
    assert tail.rstrip().endswith("(For Phillip L. Swagel, Director, Congressional Budget Office).")


def test_a_heading_gpo_wrapped_across_two_lines_is_one_heading() -> None:
    text = body("CRPT-118hrpt951")
    assert "PREPARED BY THE CONGRESSIONAL\n" in text
    finding = read_cbo_estimate(text)
    assert finding.heading == "COST ESTIMATE PREPARED BY THE CONGRESSIONAL BUDGET OFFICE"


def test_the_fallback_end_stops_at_the_next_heading_in_the_same_series() -> None:
    """CRPT-118srpt298's estimate is a table with no attribution; VI. ends where VII. begins."""
    text = body("CRPT-118srpt298")
    finding = read_cbo_estimate(text)
    assert text[finding.letter_span[1] :].lstrip().startswith("VII. Changes in Existing Law")


def test_a_table_of_contents_entry_is_not_a_heading() -> None:
    """A contents page names the CBO section on every one of these reports.

    Two guards keep it out: GPO prints those entries at indent 0 to 2, below
    the paragraph indent, and they carry dot leaders.  The fixtures are cut
    past the contents pages, so this is constructed from the shapes the whole
    bodies print -- CRPT-118hrpt53 line 59, -118hrpt951 line 63 and
    -118srpt289 line 113, all of which the rule skipped when it was run over
    the 17 retained bodies whole.
    """
    flush = "\nCongressional Budget Office Estimate.............................     4\n\n"
    indented = "\n       VI. Congressional Budget Office Cost Estimate........................ 3\n\n"
    for contents in (flush, indented):
        recital = "\n      [Including cost estimate of the Congressional Budget Office]\n\n"
        finding = read_cbo_estimate(recital + contents)
        assert finding.report_states_estimate is True
        assert finding.heading is None
        assert finding.letter_span is None


# --- branch (c): requested-empty, with the publisher's reason -----------------------


@pytest.mark.parametrize(
    ("package", "rule", "phrase"),
    [
        ("CRPT-118hrpt18", "not_available", "Congressional Budget Act of 1974 was not available"),
        ("CRPT-118hrpt111", "not_received", "The Committee has requested but not received"),
    ],
)
def test_the_publishers_own_reason_is_returned_whole(package: str, rule: str, phrase: str) -> None:
    text = body(package)
    finding = read_cbo_estimate(text)
    assert finding.absence_rule == rule
    start, end = finding.absence_span
    assert finding.absence_reason == text[start:end].strip()
    assert phrase in " ".join(finding.absence_reason.split())
    assert "Congressional Budget Office" in finding.absence_reason


def test_a_reason_is_read_under_a_heading_no_pattern_matched() -> None:
    """The reason is not gated on a heading: CRPT-118hrpt111's heading is in the set only after this build."""
    finding = read_cbo_estimate(body("CRPT-118hrpt111"))
    assert finding.absence_reason is not None
    assert finding.report_states_estimate is False


def test_a_declared_letter_reports_no_absence_reason() -> None:
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.absence_reason is None
    assert finding.absence_rule is None


def test_a_dropped_graphic_is_not_a_missing_estimate() -> None:
    """``[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]`` appears in most of these reports."""
    text = "A report.\n\n[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]\n\nThe Congressional Budget Office.\n"
    assert read_cbo_estimate(text).absence_reason is None


def test_a_reason_paragraph_that_never_names_cbo_is_not_one() -> None:
    text = "A report.\n\n    The witness requested was not available on the scheduled date.\n"
    assert read_cbo_estimate(text).absence_reason is None


# --- the rules themselves -----------------------------------------------------------


@pytest.mark.parametrize("pattern", LETTER_PATTERNS, ids=lambda p: p.name)
def test_every_pattern_refuses_its_own_lookalikes(pattern: LetterPattern) -> None:
    compiled = pattern.compiled(re.MULTILINE | re.IGNORECASE)
    for reject in pattern.rejects:
        assert compiled.search(reject) is None, f"{pattern.name} matched {reject!r}"


@pytest.mark.parametrize("pattern", LETTER_PATTERNS, ids=lambda p: p.name)
def test_every_pattern_states_why_it_exists(pattern: LetterPattern) -> None:
    assert pattern.reason.strip()
    assert pattern.name == pattern.name.lower()


def test_the_signatory_does_not_absorb_the_sentence_before_it() -> None:
    """The House block closes '...Deputy Director of Budget Analysis.' one line above the name."""
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.signatory == "Phillip L. Swagel"


def test_the_rule_version_moves_when_a_pattern_changes() -> None:
    widened = tuple(replace(p, pattern=p.pattern + "?") if p.name == "cover_recital" else p for p in LETTER_PATTERNS)
    assert _rule_version(widened) != CBO_ESTIMATE_RULE_VERSION


def test_the_rule_version_moves_when_a_reject_is_deleted() -> None:
    """A reject that is no longer asserted cannot fail, so deleting one changes the rule."""
    stripped = tuple(replace(p, rejects=()) if p.name == "cover_recital" else p for p in LETTER_PATTERNS)
    assert _rule_version(stripped) != CBO_ESTIMATE_RULE_VERSION


def test_the_rule_version_is_pinned() -> None:
    """Moves deliberately with the patterns; a surprise here is an unrecorded rule change."""
    assert CBO_ESTIMATE_RULE_VERSION == _rule_version(LETTER_PATTERNS)
    assert len(CBO_ESTIMATE_RULE_VERSION) == 12


def test_the_heading_vocabulary_is_a_floor_and_says_so() -> None:
    """Six spellings, and the set exists only to locate a span the recital already declared."""
    assert len(HEADINGS) == 6
    assert {p.name for p in HEADINGS} == {
        "cbo_cost_estimate",
        "cbo_estimate",
        "cost_estimate_prepared_by_cbo",
        "committee_cost_estimate",
        "estimated_costs",
        "cost_of_legislation",
    }


def test_heading_blocks_skip_body_paragraphs() -> None:
    """A GPO paragraph indents its first line and starts every continuation at column zero."""
    text = "    The Committee finds that the bill\nwould result in no new budget authority.\n"
    assert [block.text for block in heading_blocks(text)] == ["The Committee finds that the bill"]
    # ...and that one-line block matches no heading in the vocabulary.
    assert read_cbo_estimate(text).heading is None


def test_heading_blocks_read_the_numbering_series() -> None:
    text = "\n      VI. Congressional Budget Office Cost Estimate\n\n\n     C. Something Else\n\n     7. A Third\n"
    assert [(b.text, b.series) for b in heading_blocks(text)] == [
        ("Congressional Budget Office Cost Estimate", "roman"),
        ("Something Else", "letter"),
        ("A Third", "arabic"),
    ]


@pytest.mark.parametrize("value", [None, 17, b"bytes"])
def test_the_rule_refuses_anything_that_is_not_text(value: object) -> None:
    with pytest.raises(CboEstimateError, match="text must be a string"):
        read_cbo_estimate(value)


def test_the_recital_pattern_is_the_statutory_line_and_not_a_substring() -> None:
    inline = "The report says [Including cost estimate of the Congressional Budget Office] in passing.\n"
    assert read_cbo_estimate(inline).report_states_estimate is False
    printed = "\n      [Including cost estimate of the Congressional Budget Office]\n\n"
    assert read_cbo_estimate(printed).report_states_estimate is True


# --- the fixtures' own provenance ---------------------------------------------------


def test_retained_fixture_pins() -> None:
    """Each excerpt is what its manifest says it is, and names the source it was cut from."""
    manifest = json.loads((FIXTURES / "sources.json").read_text())
    assert set(manifest) == {path.stem for path in FIXTURES.glob("*.txt")}
    for package, pins in manifest.items():
        excerpt = body(package)
        assert len(excerpt) == pins["excerptChars"]
        assert hashlib.sha256(excerpt.encode("utf-8")).hexdigest() == pins["excerptSha256"]
        assert pins["excerptChars"] < pins["fullTextChars"]
        assert pins["url"].endswith(f"/{package}.htm")
        assert len(pins["sourceSha256"]) == 64
        assert pins["why"].strip()


def test_the_recital_and_attribution_patterns_are_spelled_once() -> None:
    """The two load-bearing markers are constants, not literals repeated in the reader."""
    source = (Path(__file__).parents[1] / "src/spicy_docs/interpretation/cbo_estimates.py").read_text()
    assert source.count(r"\[Including cost estimate of the Congressional Budget Office\]") == 1
    assert source.count(COVER_RECITAL.pattern) == 1
    assert source.count(DIRECTOR_ATTRIBUTION.pattern) == 1
    assert source.count(ACCOMPANIES.pattern) == 1
    assert {p.name for p in ABSENCE_REASONS} == {"not_available", "not_received"}
