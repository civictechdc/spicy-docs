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

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.extraction.body_text import rendition_text
from spicy_docs.transport.credentials import CredentialRefusedError
from tools.analysis.bill_html_xml_gap import (
    HELD_OUT,
    KINDS,
    MARK_END,
    MARK_START,
    OBSERVATIONS,
    SELECTION,
    DtdPin,
    XmlStructure,
    _header_agreement,
    _parse_listing,
    _refusal,
    aggregate,
    dtd_content_models,
    dtd_declares,
    dtd_form_particles,
    fidelity,
    main,
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
FIXTURES = ROOT / "tests" / "fixtures" / "govinfo_bill_html"


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


# --- the two print conventions, on real publisher bytes ----------------------------------


def _fixture_text(name: str) -> str:
    return rendition_text((FIXTURES / name).read_bytes(), rendition="htm").text


def test_struck_markers_on_publisher_bytes() -> None:
    """A real reported bill: GPO's escaped `<DELETED>` wrapping a committee substitute.

    Pinned to publisher bytes because this is the one rule with no publisher
    documentation behind it (the DTD declares no such element) and because the
    held-out draw contains no two-body document to exercise it.
    """
    found = scan_html(_fixture_text("BILLS-113s2113rs.htm"))
    assert found.struck_sections == 5
    assert [number for number, _ in found.sections] == ["1", "2", "3", "4", "5", "1", "2", "3"]
    # The marker never rides along in a catchline, and never blocks a
    # subsection sitting inside the marker's own indent.
    assert all("DELETED" not in header for _, header in found.sections)
    assert found.subsections == [
        ("2", "a"),
        ("2", "b"),
        ("5", "a"),
        ("5", "b"),
        ("5", "c"),
        ("2", "a"),
        ("2", "b"),
        ("3", "a"),
        ("3", "b"),
    ]


def test_struck_markers_are_a_lower_bound_not_an_assumption() -> None:
    """If GPO stopped escaping the marker the count would fall silently to zero.

    The escaped form is what the rules read. Feeding the same document with the
    marker gone reproduces exactly that failure -- the headings are still found,
    so nothing looks wrong -- which is why `struck_expected` asserts the bound
    against the XML's body count rather than trusting the marker.
    """
    text = _fixture_text("BILLS-113s2113rs.htm")
    assert scan_html(text).struck_sections == 5
    unmarked = text.replace("<DELETED>", "").replace("</DELETED>", "")
    silent = scan_html(unmarked)
    assert silent.struck_sections == 0
    assert len(silent.sections) == 8


def test_run_in_headings_on_publisher_bytes() -> None:
    """A real continuing resolution: general provisions set as `    Sec. n.` at the body indent."""
    found = scan_html(_fixture_text("BILLS-113hjres72fph.htm"))
    assert [number for number, _ in found.sections] == ["101", "102", "103", "104"]
    assert found.runin_sections == 4
    assert [header for _, header in found.sections] == ["", "", "", ""]
    # Its body begins at the resolving clause: the resolution states no
    # uppercase heading at all before its first general provision.
    assert found.resolving_clause_line is not None


def test_the_committed_fixtures_are_the_bytes_the_readme_pins() -> None:
    """The README states each fixture's digest; a silently edited fixture must fail here."""
    pinned = {
        "BILLS-113s2113rs.htm": "8edf42039fc61cb6a9dd7b0e5bfc53e012ed610588a3d916b0e62becae54b9a7",
        "BILLS-113hjres72fph.htm": "17e88256e57f6a571052447b0560c034718f9d816067eaf2048e7af2d94d136d",
    }
    readme = (FIXTURES / "README.md").read_text()
    for name, digest in pinned.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest
        assert digest in readme


# --- the two corpora ----------------------------------------------------------------------


def test_the_held_out_corpus_is_disjoint_from_the_tuning_corpus(measures: dict) -> None:
    """The claim the headline rests on: the rules had never seen these documents."""
    held = measures.get("heldOut")
    if not held:  # pragma: no cover - both draws are committed
        pytest.skip("no held-out measurement")
    tuning = {document["packageId"] for document in measures["paired"]}
    unseen = {document["packageId"] for document in held["paired"]}
    assert tuning and unseen
    assert not (tuning & unseen)
    assert HELD_OUT.quantiles != SELECTION.quantiles
    assert HELD_OUT.listings == SELECTION.listings


def test_the_selector_steps_past_an_excluded_file() -> None:
    """Disjointness is enforced, not hoped for: a code with few files must not re-pick."""
    entries = [{"fileExtension": "xml", "justFileName": f"BILLS-113hr{n}ih.xml", "size": n * 100} for n in range(1, 5)]
    first = select_pairs(entries, SELECTION)
    second = select_pairs(entries, HELD_OUT, exclude=frozenset(first))
    assert first and second
    assert not (set(first) & set(second))


def test_the_block_leads_with_the_held_out_score(measures: dict) -> None:
    block = render(measures)
    held_at = block.find("### Held-out score")
    tuning_at = block.find("### Tuning corpus")
    assert 0 < held_at < tuning_at
    assert "**This is the headline.**" in block
    assert "in-sample" in block.lower()


def test_a_missing_held_out_block_says_so_rather_than_implying_one() -> None:
    """Without a held-out draw the block must not let an in-sample figure read as a score."""
    block = render({"paired": [], "pre113": [], "aggregate": aggregate([])})
    assert "**Not measured.**" in block
    assert "upper bound" in block


# --- the DTD pin --------------------------------------------------------------------------


def test_the_sidecar_pins_the_dtd_by_digest(measures: dict) -> None:
    pin = measures.get("dtdPin") or {}
    if not pin:  # pragma: no cover - the DTD is pinned in the sidecar
        pytest.skip("no DTD pin in the saved measurement")
    assert pin["dtdUrl"].startswith("https://")
    assert pin["dtdBytes"] > 0
    assert len(pin["dtdSha256"]) == 64
    block = render(measures)
    assert pin["dtdSha256"] in block
    # Cited, not validated against: the block must not claim otherwise.
    assert "not validated against" in block


def test_the_deleted_marker_is_recorded_as_an_inference_not_a_dtd_element(measures: dict) -> None:
    """What the schema actually declares, read from the schema rather than remembered."""
    if measures.get("dtdDeclaresDeleted") is None:  # pragma: no cover - the DTD is pinned
        pytest.skip("no DTD in the saved measurement")
    assert measures["dtdDeclaresDeleted"] is False
    assert measures["dtdDeclaresDeletedPhrase"] is True
    assert "print convention inferred from this corpus" in render(measures)


def test_dtd_declares_reads_the_schema() -> None:
    pin = DtdPin("https://example.invalid/bill.dtd", 3, "x" * 64, "<!ELEMENT  deleted-phrase  (#PCDATA)*>")
    assert dtd_declares(pin, "deleted-phrase") is True
    assert dtd_declares(pin, "DELETED") is False
    assert dtd_declares(None, "DELETED") is None


def test_the_struck_marker_invariant_held_on_every_multi_body_document(measures: dict) -> None:
    for block in (measures, measures.get("heldOut") or {"aggregate": {}}):
        aggregated = block.get("aggregate") or {}
        assert aggregated.get("struckMarkerHeld", []) == []


# --- catchline agreement -------------------------------------------------------------------


def test_catchline_agreement_separates_the_empty_pairings() -> None:
    """An agreement of "" against "" is not evidence a catchline was recovered."""
    html = scan_html(APPROPRIATIONS + "\nSEC. 9. REAL CATCHLINE.\n\n    Text.\n")
    xml = XmlStructure(
        sections=[("1201", ""), ("2101", ""), ("9", "Real catchline")],
        unnumbered_sections=0,
        subsections=[],
        titles=[],
        divisions=[],
        quoted_blocks=0,
    )
    row = _header_agreement(html, xml)
    assert row == {"comparedWithCatchline": 1, "agreed": 1, "comparedEmpty": 2}


def test_the_block_reports_both_catchline_figures(measures: dict) -> None:
    block = render(measures)
    assert "where neither" in block
    assert "agrees trivially" in block


# --- credential hygiene ---------------------------------------------------------------------


def test_a_refusal_is_scrubbed_before_it_is_truncated() -> None:
    """Scrub-then-truncate: the other order can cut a key in half and leave its front standing."""
    key = "k" * 40
    error = ValueError(f"route https://api.example.gov/v3/bill?api_key={key}&format=json failed")
    row = _refusal("BILLS-113hr1ih", error, key)
    assert key not in row["reason"]
    assert "api_key=<redacted>" in row["reason"]
    assert row["packageId"] == "BILLS-113hr1ih"


def test_a_refusal_scrubs_a_key_the_pattern_alone_would_miss() -> None:
    """The literal pass: the configured key echoed outside an `api_key=` query still has to go.

    Only the literal pass can catch this one, because there is no `api_key=`
    for the pattern to anchor on.
    """
    key = "z" * 40
    row = _refusal("BILLS-113hr1ih", ValueError(f"upstream echoed X-Api-Key {key} in its body"), key)
    assert key not in row["reason"]
    assert "<redacted>" in row["reason"]


def test_a_refusal_scrubs_a_key_it_was_not_handed() -> None:
    """The pattern pass, which the literal pass cannot cover.

    Written because mutation said it was needed: every other credential case
    here passes the configured key as the literal, so deleting the pattern pass
    left all of them green and the claim that both passes earn their place was
    unbacked. A refusal can carry a credential this run was never told about --
    a redirect to another keyed host, or a nested URL quoted inside a publisher
    message -- and that is the half only the pattern sees.
    """
    other = "SOME-OTHER-SECRET"
    error = ValueError(f"redirected to https://other.example/v3/x?api_key={other}&format=json")
    row = _refusal("BILLS-113hr1ih", error, "the-configured-key")
    assert other not in row["reason"]
    assert "api_key=<redacted>" in row["reason"]


def test_a_long_refusal_is_scrubbed_before_it_is_truncated_not_after() -> None:
    """The order is the whole point, so the case is built to fail if it is reversed.

    The key is placed so the 200-character cut falls *inside* it, and it is
    echoed in a form only the literal pass catches (no ``api_key=``, which the
    pattern pass would still redact after truncation). Scrub-then-truncate
    removes the whole key; truncate-then-scrub leaves its first 20 characters
    standing, which is exactly the hole AGENTS.md names.
    """
    key = "q" * 40
    # Place the key so that 25 of its characters fall before the 200-character
    # cut and the rest after it, accounting for the "ValueError: " the refusal
    # prepends, so the straddle cannot drift if that wording changes.
    tail = "upstream echoed X-Api-Key "
    lead = len(f"{ValueError.__name__}: ") + len(tail)
    error = ValueError("." * (200 - 25 - lead) + tail + key)
    built = f"{type(error).__name__}: {error}"
    assert built[:200].count("q") == 25, "the cut must fall inside the key for this to test anything"

    row = _refusal("BILLS-113hr1ih", error, key)
    assert len(row["reason"]) <= 200
    assert key not in row["reason"]
    assert "q" * 25 not in row["reason"]


def test_a_credential_refusal_stops_the_run_without_a_traceback(tmp_path, monkeypatch, capsys) -> None:
    """401/403 aborts; it is never skipped as a bad row, and the message carries no key."""
    key = "s" * 40
    env = tmp_path / ".env"
    env.write_text(f"API_GOV={key}\n")
    output = tmp_path / "out.json"
    doc = tmp_path / "doc.md"
    doc.write_text(f"{MARK_START}\n{MARK_END}\n")

    def refuse(*_args, **_kwargs):
        raise CredentialRefusedError(f"GovInfo answered HTTP 403 for api_key={key}")

    monkeypatch.setattr("tools.analysis.bill_html_xml_gap.measure", refuse)
    status = main(
        [
            "--output",
            str(output),
            "--doc",
            str(doc),
            "--cache",
            str(tmp_path / "cache"),
            "--env-file",
            str(env),
        ]
    )
    assert status == 1
    message = capsys.readouterr().err
    assert key not in message
    assert "credential refused" in message
    assert not output.exists()


# --- the CLI ---------------------------------------------------------------------------------


def test_listing_overrides_are_parsed_as_the_bulk_route_spells_them() -> None:
    assert _parse_listing("113:1:hr") == (113, 1, "hr")
    for bad in ("113:1", "113:1:hr:x", "abc:1:hr", "113:x:hr", "113:1:9"):
        with pytest.raises(ValueError):
            _parse_listing(bad)
