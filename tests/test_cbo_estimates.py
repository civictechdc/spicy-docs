"""The CBO letter rule: the recital gate, the located span, the publisher's reason, and the version.

Every fixture is a bounded excerpt of a real GovInfo CRPT body; the manifest
pins each cut and the rule version moves with any pattern, reject or threshold.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.interpretation import cbo_estimates as rules
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
from spicy_docs.schemas import COMMITTEE_REPORTS, DOCUMENT_CITATIONS, HEARING_TRANSCRIPTS
from spicy_docs.schemas.committee_report_tables import shape_committee_report
from spicy_docs.schemas.tables import digest

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_estimates"


def body(package: str) -> str:
    """The full text of one fixture excerpt."""
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
    """The cover recital is the gate: the finding's report_states_estimate follows it and carries the rule and
    version.
    """
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
    """The cover states the bill the report accompanies, and the bill key uses the package's Congress, never the
    print's.
    """
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.accompanies == "H.R. 801"
    assert recital_bill_id(finding, 118) == "118-hr-801"
    # The Congress is the package's, never the print's: the cover states none.
    assert recital_bill_id(finding, None) is None
    assert recital_bill_id(finding, 119) == "119-hr-801"


def test_a_cover_naming_no_measure_yields_no_bill_key() -> None:
    """A cover naming no measure yields no bill key."""
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
    """A declared letter is located end to end with its rule, signatory, span, digest and re-readable heading."""
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
    """The letter span ends after the Director attribution, not before it."""
    text = body("CRPT-118hrpt780")
    finding = read_cbo_estimate(text)
    tail = text[finding.letter_span[0] : finding.letter_span[1]]
    assert tail.rstrip().endswith("(For Phillip L. Swagel, Director, Congressional Budget Office).")


def test_a_heading_gpo_wrapped_across_two_lines_is_one_heading() -> None:
    """A heading GPO wrapped across two lines reads as one heading."""
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
    """The publisher's own absence reason is returned whole under its rule and span."""
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
    """A declared letter reports no absence reason or rule."""
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.absence_reason is None
    assert finding.absence_rule is None


def test_a_dropped_graphic_is_not_a_missing_estimate() -> None:
    """``[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]`` appears in most of these reports."""
    text = "A report.\n\n[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]\n\nThe Congressional Budget Office.\n"
    assert read_cbo_estimate(text).absence_reason is None


def test_a_reason_paragraph_that_never_names_cbo_is_not_one() -> None:
    """A reason paragraph that never names CBO is not an absence reason."""
    text = "A report.\n\n    The witness requested was not available on the scheduled date.\n"
    assert read_cbo_estimate(text).absence_reason is None


# --- the rules themselves -----------------------------------------------------------


@pytest.mark.parametrize("pattern", LETTER_PATTERNS, ids=lambda p: p.name)
def test_every_pattern_refuses_its_own_lookalikes(pattern: LetterPattern) -> None:
    """Every pattern refuses every one of its own lookalikes."""
    compiled = pattern.compiled(re.MULTILINE | re.IGNORECASE)
    for reject in pattern.rejects:
        assert compiled.search(reject) is None, f"{pattern.name} matched {reject!r}"


@pytest.mark.parametrize("pattern", LETTER_PATTERNS, ids=lambda p: p.name)
def test_every_pattern_states_why_it_exists(pattern: LetterPattern) -> None:
    """Every pattern states why it exists and uses a lowercase name."""
    assert pattern.reason.strip()
    assert pattern.name == pattern.name.lower()


def test_the_signatory_does_not_absorb_the_sentence_before_it() -> None:
    """The House block closes '...Deputy Director of Budget Analysis.' one line above the name."""
    finding = read_cbo_estimate(body("CRPT-118hrpt53"))
    assert finding.signatory == "Phillip L. Swagel"


def test_the_rule_version_moves_when_a_pattern_changes() -> None:
    """Widening a pattern moves the rule version."""
    widened = tuple(replace(p, pattern=p.pattern + "?") if p.name == "cover_recital" else p for p in LETTER_PATTERNS)
    assert _rule_version(widened) != CBO_ESTIMATE_RULE_VERSION


def test_the_rule_version_moves_when_a_reject_is_deleted() -> None:
    """Deleting a reject moves the rule version, since an unasserted reject cannot fail."""
    stripped = tuple(replace(p, rejects=()) if p.name == "cover_recital" else p for p in LETTER_PATTERNS)
    assert _rule_version(stripped) != CBO_ESTIMATE_RULE_VERSION


def test_the_rule_version_is_pinned() -> None:
    """The rule version is pinned to its digest."""
    assert CBO_ESTIMATE_RULE_VERSION == "cf790f0f814a"
    assert _rule_version() == "cf790f0f814a"


@pytest.mark.parametrize(
    ("name", "index"),
    [(name, None) for name in ("COVER_RECITAL", "ACCOMPANIES", "DIRECTOR_ATTRIBUTION", "SIGNATORY")]
    + [("HEADINGS", index) for index in range(len(HEADINGS))]
    + [("ABSENCE_REASONS", index) for index in range(len(ABSENCE_REASONS))],
)
@pytest.mark.parametrize("field", ["pattern", "flags", "rejects"])
def test_every_letter_rule_input_moves_the_version(monkeypatch, name, index, field) -> None:
    """Every letter-rule input moves the version."""
    current = getattr(rules, name)
    pattern = current if index is None else current[index]
    value = {
        "pattern": pattern.pattern + "(?:)",
        "flags": pattern.flags ^ re.IGNORECASE,
        "rejects": (*pattern.rejects, "another lookalike"),
    }[field]
    changed = replace(pattern, **{field: value})
    monkeypatch.setattr(rules, name, changed if index is None else (*current[:index], changed, *current[index + 1 :]))
    assert rules._rule_version() != CBO_ESTIMATE_RULE_VERSION


@pytest.mark.parametrize("name", ["_REASON_REQUIRES", "_NUMBERING", "_DOT_LEADER", "_WHITESPACE", "_PARAGRAPH_BREAK"])
@pytest.mark.parametrize("change_flags", [False, True])
def test_every_auxiliary_pattern_and_flags_move_the_version(monkeypatch, name, change_flags) -> None:
    """Every auxiliary pattern and flag moves the version."""
    pattern = getattr(rules, name)
    changed = re.compile(
        pattern.pattern if change_flags else pattern.pattern + "(?:)",
        pattern.flags ^ re.IGNORECASE if change_flags else pattern.flags,
    )
    monkeypatch.setattr(rules, name, changed)
    assert rules._rule_version() != CBO_ESTIMATE_RULE_VERSION


@pytest.mark.parametrize("name", ["_MIN_HEADING_INDENT", "_MAX_HEADING_LINES", "_MAX_HEADING_CHARS", "_RULE_REVISION"])
def test_every_threshold_and_revision_moves_the_version(monkeypatch, name) -> None:
    """Every threshold and revision moves the version."""
    monkeypatch.setattr(rules, name, getattr(rules, name) + 1)
    assert rules._rule_version() != CBO_ESTIMATE_RULE_VERSION


def test_heading_punctuation_moves_the_version(monkeypatch) -> None:
    """Heading punctuation moves the version."""
    monkeypatch.setattr(rules, "_HEADING_TRAILING_CHARS", ".:")
    assert rules._rule_version() != CBO_ESTIMATE_RULE_VERSION


def test_the_reason_guard_changes_the_finding_and_version_together(monkeypatch) -> None:
    """The reason guard changes the finding and the version together."""
    text = body("CRPT-118hrpt18")
    assert rules.read_cbo_estimate(text).absence_rule == "not_available"
    monkeypatch.setattr(rules, "_REASON_REQUIRES", re.compile("this text never appears"))
    assert rules.read_cbo_estimate(text).absence_reason is None
    assert rules._rule_version() != CBO_ESTIMATE_RULE_VERSION


def test_absence_scan_keeps_rule_priority_and_exact_paragraph_boundaries() -> None:
    """The absence scan keeps rule priority and exact paragraph boundaries."""
    first = "Congressional Budget Office: requested but not received."
    second = "  Congressional Budget Office: was not available.  "
    text = first + "\n\n\n" + second
    finding = read_cbo_estimate(text)
    assert finding.absence_rule == "not_available"
    assert finding.absence_reason == second.strip()
    assert finding.absence_span == (len(first) + 3, len(text))


@pytest.mark.parametrize(
    ("package", "span", "signatory"),
    [
        ("CRPT-118hrpt53", (5333, 8974), "PHILLIP L. SWAGEL"),
        ("CRPT-118hrpt276", (6922, 8651), "PHILLIP L. SWAGEL"),
        ("CRPT-118hrpt930", (10896, 22673), "Phillip L. Swagel"),
        ("CRPT-118srpt289", (14332, 19670), "Phillip L. Swagel"),
    ],
)
def test_four_retained_pdf_texts_locate_the_declared_letter(package, span, signatory) -> None:
    """Four retained PDF texts locate the declared letter with the pinned span, digest, signatory and end rule."""
    text = (FIXTURES / "pdf" / f"{package}.txt").read_text()
    pins = json.loads((FIXTURES / "pdf" / "sources.json").read_text())[package]
    assert digest(text) == pins["textSha256"]
    assert len(text) == pins["textChars"]
    finding = read_cbo_estimate(text)
    assert finding.report_states_estimate is True
    assert finding.letter_span == span
    assert finding.letter_sha256 == pins["letterSha256"]
    assert finding.letter_end_rule == "director_attribution"
    assert finding.signatory == signatory
    assert text[span[0] : span[1]].startswith(finding.heading) or text[span[0] :].startswith("VI. ")
    assert text[span[0] : span[1]].endswith("Budget Office.")


@pytest.mark.parametrize(
    "lookalike",
    [
        "CONGRESSIONAL BUDGET OFFICE COST ESTIMATE.............. 4",
        "THE CONGRESSIONAL BUDGET OFFICE COST ESTIMATE WAS NOT AVAILABLE.",
        "Congressional Budget Office Cost Estimate",
    ],
)
def test_flush_heading_rule_refuses_contents_prose_and_mixed_case(lookalike) -> None:
    """The flush heading rule refuses contents prose and mixed case."""
    text = "[Including cost estimate of the Congressional Budget Office]\n" + lookalike
    assert read_cbo_estimate(text).heading is None


def test_a_flush_uppercase_heading_and_signature_cannot_replace_the_recital() -> None:
    """A flush uppercase heading and signature cannot replace the recital."""
    text = "CONGRESSIONAL BUDGET OFFICE COST ESTIMATE\nDirector, Congressional Budget Office."
    finding = read_cbo_estimate(text)
    assert finding.report_states_estimate is False
    assert finding.letter_span is None


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
    """Heading blocks skip indented body paragraphs, which match no heading."""
    text = "    The Committee finds that the bill\nwould result in no new budget authority.\n"
    assert [block.text for block in heading_blocks(text)] == ["The Committee finds that the bill"]
    # ...and that one-line block matches no heading in the vocabulary.
    assert read_cbo_estimate(text).heading is None


def test_heading_blocks_read_the_numbering_series() -> None:
    """Heading blocks read the numbering series."""
    text = "\n      VI. Congressional Budget Office Cost Estimate\n\n\n     C. Something Else\n\n     7. A Third\n"
    assert [(b.text, b.series) for b in heading_blocks(text)] == [
        ("Congressional Budget Office Cost Estimate", "roman"),
        ("Something Else", "letter"),
        ("A Third", "arabic"),
    ]


@pytest.mark.parametrize("value", [None, 17, b"bytes"])
def test_the_rule_refuses_anything_that_is_not_text(value: object) -> None:
    """The rule refuses non-text input."""
    with pytest.raises(CboEstimateError, match="text must be a string"):
        read_cbo_estimate(value)


def test_the_recital_pattern_is_the_statutory_line_and_not_a_substring() -> None:
    """The recital pattern matches the statutory line, not an inline substring."""
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


# --- the link: the estimate columns on the package-keyed report row ------------------


class _Capture:
    """A minimal capture over one response body."""

    body = b""
    requested_url = "https://www.govinfo.gov/content/pkg/CRPT-118hrpt53/html/CRPT-118hrpt53.htm"
    resolved_url = requested_url
    byte_size = 21080
    sha256 = "sha256:" + "0" * 64
    observed_at = "2026-09-20T14:57:19Z"


class _Identity:
    """A minimal package identity."""

    package_id = "CRPT-118hrpt53"
    collection = "CRPT"
    congress = 118
    document_type = "hrpt"
    number = "53"


class _Summary:
    """A minimal package summary."""

    title = "Securing the Border for Public Health Act of 2023"
    date_issued = "2023-05-11"
    last_modified = "2023-05-12T00:00:00Z"


class _Body:
    """The three things ``_package_row`` reads, and nothing this test does not need."""

    identity = _Identity()
    summary = _Summary()
    body_capture = _Capture()
    format = "htm"

    class body:
        media_type = "text/html"


def report_row(package: str, **kwargs: object) -> dict[str, str | None]:
    """Shape one committee-report row over the given text and capture."""
    text = body(package)
    finding = read_cbo_estimate(text)
    return COMMITTEE_REPORTS.checked(
        shape_committee_report(
            _Body(),
            text_sha256=digest(text),
            estimate=finding,
            recital_bill_id=recital_bill_id(finding, 118),
            **kwargs,
        )
    )


def test_a_reprinted_letter_lands_on_the_report_row_with_its_span() -> None:
    """A reprinted letter lands on the report row with its span, rule fields and self-checking digests."""
    text = body("CRPT-118hrpt53")
    row = report_row("CRPT-118hrpt53")
    assert row["report_states_estimate"] == "true"
    assert row["recital_bill_id"] == "118-hr-801"
    assert row["estimate_rule"] == CBO_ESTIMATE_RULE
    assert row["estimate_rule_version"] == CBO_ESTIMATE_RULE_VERSION
    assert row["estimate_heading_rule"] == "cbo_estimate"
    assert row["letter_end_rule"] == "director_attribution"
    assert row["letter_signatory"] == "Phillip L. Swagel"
    assert row["estimate_absence_reason"] is None
    # The span indexes into the text text_sha256 digests, so the row is self-checking.
    letter = text[int(row["letter_span_start"]) : int(row["letter_span_end"])]
    assert row["letter_text_sha256"] == digest(letter)
    assert row["text_sha256"] == digest(text)


def test_a_refused_estimate_lands_with_the_publishers_reason_and_no_span() -> None:
    """A refused estimate lands with the publisher's reason and no span or digest."""
    row = report_row("CRPT-118hrpt18")
    assert row["report_states_estimate"] == "false"
    assert row["letter_span_start"] is None
    assert row["letter_span_end"] is None
    assert row["letter_text_sha256"] is None
    assert row["estimate_absence_rule"] == "not_available"
    assert "was not available" in " ".join(row["estimate_absence_reason"].split())


def test_no_rule_run_is_null_and_not_false() -> None:
    """A row with no rule run is NULL, not false."""
    row = COMMITTEE_REPORTS.checked(shape_committee_report(_Body()))
    assert row["report_states_estimate"] is None
    assert row["estimate_rule"] is None
    assert row["estimate_absence_reason"] is None


def test_the_nineteen_package_columns_keep_their_order_and_the_rest_are_appended() -> None:
    """The nineteen package columns keep their order, with every estimate column appended after them."""
    assert COMMITTEE_REPORTS.columns[:19] == (
        "package_id",
        "collection",
        "congress",
        "report_type",
        "report_number",
        "chamber",
        "title",
        "date_issued",
        "last_modified",
        "bill_id",
        "format",
        "media_type",
        "requested_url",
        "resolved_url",
        "byte_size",
        "sha256",
        "observed_at",
        "page_count",
        "text_sha256",
    )
    assert COMMITTEE_REPORTS.identity == ("package_id",)
    assert COMMITTEE_REPORTS.version_column == "last_modified"
    assert len(COMMITTEE_REPORTS.columns) == 32


def test_the_hearing_table_did_not_take_the_estimate_columns() -> None:
    """The hearing table did not take the estimate columns."""
    assert not set(COMMITTEE_REPORTS.columns[19:]) & set(HEARING_TRANSCRIPTS.columns)


def test_no_citation_kind_was_added_for_the_estimate() -> None:
    """No citation kind was added for the estimate; the link is a bill join."""
    assert "cbo" not in " ".join(DOCUMENT_CITATIONS.columns)
    assert "cbo_cost_estimate" not in DOCUMENT_CITATIONS.descriptions["cite_kind"]
    for package in sorted(json.loads((FIXTURES / "sources.json").read_text())):
        assert "cbo.gov/publication/" not in body(package)
