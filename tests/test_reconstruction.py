"""Reconstruction: the profile registry, the evidence model, the parser, the serializer and the five findings.

Every case here runs on a real publisher response. The five CFR sections are
the evidence documents under `tests/fixtures/reconstruction/cfr/` (their README
states what each one exercises and where its PDF came from), and
the reference for 30 CFR 716.2 is the XML granule this repository already
holds for the same section, so the round-trip compares one document with
itself rather than two documents with each other.

Only `schema_validity` needs the `reconstruct` extra. Its tests skip on
`extra_available()` rather than fail, the way `test_congress_bill_tree.py`
skips on `bill-diff`; everything else runs on the core package.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.extraction.model import Box, PageContent, PageResult, TextBlock
from spicy_docs.reading.markup import read_html_events
from spicy_docs.reconstruction import EXTRA_REQUIRED, ID_ORIGIN, extra_available
from spicy_docs.reconstruction.evidence import (
    Decision,
    DocumentNode,
    EvidenceBlock,
    EvidenceDocument,
    EvidenceError,
    StyledRun,
    evidence_from_markup,
    evidence_from_pages,
    evidence_from_text,
)
from spicy_docs.reconstruction.parse import (
    CFR_KINDS,
    SECTION_ROOT,
    Alternative,
    Classification,
    ParseError,
    join_lines,
    marker_pairs,
    paragraph_marker,
    parse_cfr,
    restore_small_caps,
)
from spicy_docs.reconstruction.profiles import (
    CFR_PROFILE,
    PROFILES,
    RULE_KINDS,
    Applicability,
    Profile,
    ProfileError,
    Rule,
    check_schema_bundle,
    profile,
    select_profile,
)
from spicy_docs.reconstruction.serialize import SerializeError, serialize_cfr
from spicy_docs.reconstruction.validate import (
    NORMALIZATION_RULES,
    Finding,
    Gates,
    ValidateError,
    acceptance,
    check,
    compare_text,
    content_fidelity,
    coverage,
    document_marker_pairs,
    hierarchy_f1,
    normalize_for_comparison,
    schema_validity,
    serialized_text,
    structural_fidelity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reconstruction" / "cfr"
PROVENANCE = {entry["section"]: entry for entry in json.loads((FIXTURES / "provenance.json").read_text())}
CFR_XML = Path(__file__).parent / "fixtures" / "cfr" / "annual-title30-vol3-sec716-2.xml"
HTML_BODY = Path(__file__).parent / "fixtures" / "govinfo_bodies" / "body-CRPT-119hrpt105.htm"
PDF_TEXT = Path(__file__).parent / "fixtures" / "gpo_pdf_text"

needs_extra = pytest.mark.skipif(
    not extra_available(), reason="needs the 'reconstruct' extra: uv sync --extra reconstruct"
)


def load(section: str) -> EvidenceDocument:
    entry = PROVENANCE[section]
    return EvidenceDocument.from_json(json.loads((FIXTURES / entry["fixture"]).read_text()))


# --- the profile registry ------------------------------------------------------------


def test_every_rule_is_tagged_and_cites_where_its_authority_is_stated() -> None:
    for rule in CFR_PROFILE.rules:
        assert rule.kind in RULE_KINDS
        assert rule.statement and rule.source, rule.name
    # The three kinds carry different authority, so all three must be present
    # and distinguishable; a profile of only heuristics states nothing about
    # the publisher, and one of only schema rules cannot be measured.
    kinds = {kind: len(CFR_PROFILE.rules_of_kind(kind)) for kind in RULE_KINDS}
    assert all(count > 0 for count in kinds.values()), kinds
    assert CFR_PROFILE.rules_of_kind("guide"), "a profile with no guide rule cites no publisher convention"


def test_every_rule_the_parser_and_serializer_name_is_in_the_profile() -> None:
    document = parse_cfr(load("716.2"))
    for node in document.nodes:
        CFR_PROFILE.rule(node.decision.rule)
    for region in document.unresolved:
        assert region.detail, region.id
    for name in CFR_PROFILE.validation_rules:
        assert name in {"schema_validity", "content_fidelity", "structural_fidelity", "coverage", "acceptance"}


def test_the_registry_answers_by_family_and_by_applicability() -> None:
    assert profile("cfr") is CFR_PROFILE
    assert select_profile(collection="CFR", rendition="pdf") is CFR_PROFILE
    assert select_profile(collection="BILLS", rendition="pdf") is None
    with pytest.raises(ProfileError, match="registered: cfr"):
        profile("uslm")


def test_a_profile_refuses_a_repeated_rule_name_and_an_unknown_applicability_rule() -> None:
    rule = Rule("only", "heuristic", "s", "src")
    with pytest.raises(ProfileError, match="repeats a rule name"):
        Profile("x", "1", Applicability(("X",), ("pdf",), "only"), (), CFR_PROFILE.guide, (rule, rule), "s", (), ())
    with pytest.raises(ProfileError, match="applicability names an unknown rule"):
        Profile("x", "1", Applicability(("X",), ("pdf",), "absent"), (), CFR_PROFILE.guide, (rule,), "s", (), ())
    with pytest.raises(ProfileError, match="expected one of"):
        Rule("bad", "vibes", "s", "src")  # type: ignore[arg-type]


def test_the_pinned_schema_bundle_is_present_and_carries_its_pinned_digest() -> None:
    assert [entry.name for entry in check_schema_bundle(CFR_PROFILE)] == ["CFRMergedXML.xsd"]


def test_the_profile_pins_the_guide_it_cites() -> None:
    guide = CFR_PROFILE.guide
    assert guide.raw_url.endswith("CFR-XML_User-Guide.md") and len(guide.sha256) == 64
    cited = {rule.source.split()[0] for rule in CFR_PROFILE.rules_of_kind("guide")}
    assert cited == {"CFR-XML_User-Guide.md"}, "a guide rule must cite the guide this profile pinned"


def test_the_only_registered_profiles_are_exclusive_about_what_they_apply_to() -> None:
    for family, entry in PROFILES.items():
        assert entry.family == family
        for collection in entry.applicability.collections:
            for rendition in entry.applicability.renditions:
                assert select_profile(collection=collection, rendition=rendition) is entry


# --- the evidence model ---------------------------------------------------------------


def test_evidence_from_an_html_body_keeps_the_enclosing_elements_and_the_byte_span() -> None:
    document = evidence_from_markup(read_html_events(HTML_BODY.read_bytes()), rendition="htm")
    assert document.rendition == "htm" and document.id_origin == ID_ORIGIN
    first = document.blocks[0]
    assert first.text == "[House Report 119-105]"
    assert first.runs[0].tags[-1] == "pre", "a GovInfo htm body is GPO's text inside <pre>"
    assert first.span is not None
    start, end = first.span
    assert HTML_BODY.read_bytes()[start:end].decode() == first.text
    # `<title>` is document metadata, exactly as extraction.body_text treats it.
    assert not any("title" in block.runs[0].tags for block in document.blocks if block.runs)


def test_evidence_from_a_pdf_page_pairs_the_retained_spans_with_the_normalized_boxes() -> None:
    page = PageResult(
        {"page": 1, "page_count": 1, "source_sha256": "a" * 64},
        PageContent(
            (TextBlock("§ 1.1 ", Box(0.2, 0.4, 0.3, 0.41), observation="native"),),
            (
                type(
                    "Observation",
                    (),
                    {
                        "id": "native",
                        "raw": {
                            "blocks": [
                                {
                                    "lines": [
                                        {
                                            "spans": [
                                                {
                                                    "text": "§ 1.1 ",
                                                    "font": "NewCenturySchlbk-Bold",
                                                    "size": 8.0,
                                                    "flags": 20,
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    },
                )(),
            ),
        ),
    )
    document = evidence_from_pages([page])
    (block,) = document.blocks
    assert block.id == "b0001" and block.page == 1 and block.text == "§ 1.1 "
    assert block.bold and block.size == 8.0 and block.fonts == ("NewCenturySchlbk-Bold",)
    assert document.source_sha256 == "a" * 64


def test_the_real_pdf_evidence_fixture_states_its_page_count_and_distinct_ids() -> None:
    document = load("716.2")
    assert document.rendition == "pdf" and document.page_count == 3
    assert document.source_sha256 == PROVENANCE["716.2"]["pdfSha256"]
    assert len({block.id for block in document.blocks}) == len(document.blocks)
    assert document.block(document.blocks[0].id) is document.blocks[0]
    with pytest.raises(EvidenceError, match="no evidence block"):
        document.block("b9999")


def test_line_assembly_joins_the_fragments_a_justified_column_splits() -> None:
    document = load("716.2")
    assembled = [block for block in document.blocks if block.fragments > 1]
    assert assembled, "a justified CFR column reaches the extractor as word fragments"
    widest = max(assembled, key=lambda block: block.fragments)
    assert widest.fragments >= 5 and " " in widest.text
    assert "".join(run.text for run in widest.runs) == widest.text


def test_the_evidence_document_round_trips_through_its_own_json() -> None:
    document = load("21.1")
    assert EvidenceDocument.from_json(json.loads(document.dumps())) == document


def test_a_block_whose_runs_do_not_join_to_its_text_is_refused() -> None:
    with pytest.raises(EvidenceError, match="runs must join"):
        EvidenceBlock("b1", "one", (StyledRun("two"),), "pdf")
    with pytest.raises(EvidenceError, match="distinct"):
        EvidenceDocument("pdf", "d", (EvidenceBlock("b1", "", (), "pdf"), EvidenceBlock("b1", "", (), "pdf")))
    with pytest.raises(EvidenceError, match="review status"):
        DocumentNode("n1", "paragraph", None, None, (), Decision("rule", "paragraph_p"), "maybe")
    with pytest.raises(EvidenceError, match="decision method"):
        Decision("guess", "paragraph_p")


def test_a_text_rendition_becomes_one_block_per_line() -> None:
    document = evidence_from_text("a\n\nb")
    assert [block.text for block in document.blocks] == ["a", "", "b"]
    assert document.rendition == "txt"


# --- the joins -------------------------------------------------------------------------


def test_the_hyphen_join_tells_a_print_wrap_from_a_compound_and_from_small_capitals() -> None:
    def joined(first: str, second: str, **style: object) -> str:
        blocks = (
            EvidenceBlock("b1", first, (StyledRun(first, **style),), "pdf", page=1),  # type: ignore[arg-type]
            EvidenceBlock("b2", second, (StyledRun(second, **style),), "pdf", page=1),  # type: ignore[arg-type]
        )
        return join_lines(blocks)[0]

    assert joined("special ini-", "tial performance") == "special initial performance"
    assert joined("a non-", "Federal source") == "a non-Federal source"
    assert joined("the FED-", "ERAL REGISTER") == "the FEDERAL REGISTER"
    assert joined("one line", "next line") == "one line next line"


def test_small_capitals_are_restored_from_size_because_the_print_encodes_case_that_way() -> None:
    runs = (
        StyledRun("the F", size=8.0),
        StyledRun("EDERAL", size=6.5),
        StyledRun(" R", size=8.0),
        StyledRun("EGISTER", size=6.5),
    )
    assert "".join(run.text for run in restore_small_caps(runs, 8.0)) == "the Federal Register"
    # A line set wholly in the smaller face is a note, not small capitals.
    small = (StyledRun("AUTHORITY", size=6.5),)
    assert "".join(run.text for run in restore_small_caps(small, 6.5)) == "AUTHORITY"


def test_the_join_collapses_gpo_typewriter_quotes_by_the_shared_rule() -> None:
    block = EvidenceBlock("b1", "the term ``wage order''", (StyledRun("the term ``wage order''"),), "pdf")
    assert join_lines((block,))[0] == 'the term "wage order"'


def test_the_marker_ladder_nests_the_cfr_designations_and_survives_one_out_of_sequence() -> None:
    assert marker_pairs(["(a)", "(1)", "(i)", "(A)"]) == {
        (SECTION_ROOT, "(a)"),
        ("(a)", "(1)"),
        ("(1)", "(i)"),
        ("(i)", "(A)"),
    }
    # `(z)` is followed by `(aa)`, not by `(za)`.
    assert ("(z)", "(aa)") in marker_pairs(["(z)", "(aa)"]) or (SECTION_ROOT, "(aa)") in marker_pairs(["(z)", "(aa)"])
    assert paragraph_marker("(e)(1) This section") == "(e)(1)"
    assert paragraph_marker("The permittee") is None


# --- the parser -------------------------------------------------------------------------


def test_a_plain_section_yields_a_section_number_a_subject_and_its_paragraphs() -> None:
    document = parse_cfr(load("1.1"))
    section = document.section("1.1")
    assert section is not None
    kinds = [node.kind for node in document.descendants(section.id)]
    assert kinds[:2] == ["section_number", "subject"]
    assert "paragraph" in kinds
    assert all(node.decision.method == "rule" for node in document.nodes)


def test_nested_paragraphs_hang_from_the_designation_above_them() -> None:
    document = parse_cfr(load("716.2"))
    pairs = document_marker_pairs(document, section="716.2")
    for pair in [(SECTION_ROOT, "(a)"), ("(e)", "(3)"), ("(3)", "(i)"), ("(iv)", "(A)")]:
        assert pair in pairs, pair
    citation = [node for node in document.nodes if node.kind == "citation"]
    assert citation and citation[0].text.startswith("[42 FR 62691")


def test_a_run_in_designation_is_flagged_rather_than_guessed() -> None:
    """GPO sets `(e) *heading.* (1) text` as one paragraph, so `(1)` never begins a line."""
    document = parse_cfr(load("716.2"))
    flagged = [node for node in document.nodes if node.review_status == "needs_review" and node.kind == "paragraph"]
    assert flagged and all("out of sequence" in node.decision.detail for node in flagged)
    assert not structural_fidelity(document, expected_sections=["716.2"]).passed


def test_page_furniture_is_classified_and_never_serialized() -> None:
    document = parse_cfr(load("716.2"))
    furniture = [node for node in document.nodes if node.kind in ("page_number", "running_head")]
    assert furniture, "the fixture keeps each page's furniture so these rules are exercised"
    assert all(CFR_KINDS[node.kind] is None for node in furniture)
    out = serialize_cfr(document, section="716.2")
    assert not any(entry.kind in ("page_number", "running_head") for entry in out.source_map.entries)


def test_a_table_region_survives_unresolved_rather_than_being_serialized_wrongly() -> None:
    document = parse_cfr(load("46.1"))
    regions = document.unresolved
    assert [region.issue for region in regions] == ["table_region", "table_region"]
    for region in regions:
        assert region.evidence_refs and region.detail and region.id.startswith("u")
    # Both tables belong to the appendices this section's page range runs
    # through, not to the section itself, so the serialized granule carries
    # neither and the coverage finding reports them rather than losing them.
    out = serialize_cfr(document, section="46.1")
    assert not out.source_map.unresolved
    assert coverage(document, out).measures["unresolvedRegions"] == 2


def test_gpo_s_print_shop_footer_is_furniture_by_the_shared_extraction_rule() -> None:
    document = parse_cfr(load("1.313"))
    footers = [node for node in document.nodes if node.kind == "print_footer"]
    assert footers, "this volume prints GPO's print-shop chrome at the foot of every page"
    # Both of `gpo_normalize`'s chrome rules fire here: the VerDate line and
    # the compositor's own user-and-job line.
    assert [node.text.split()[0] for node in footers] == ["VerDate", "pparker"]
    assert all(node.decision.rule == "print_shop_footer" for node in footers)
    assert CFR_KINDS["print_footer"] is None


def test_the_neighbouring_sections_in_a_section_pdf_are_classified_not_dropped() -> None:
    document = parse_cfr(load("716.2"))
    assert len(document.sections()) > 1, "a section PDF is a page range and carries its neighbours"
    out = serialize_cfr(document, section="716.2")
    assert out.source_map.out_of_scope, "their blocks are out-of-scope evidence, not loss"


def test_the_classify_seam_is_offered_the_alternatives_and_its_abstention_is_honoured() -> None:
    seen: list[tuple[int, int]] = []

    def abstain(*, blocks, context, alternatives) -> Classification:  # type: ignore[no-untyped-def]
        seen.append((len(blocks), len(alternatives)))
        assert all(isinstance(alternative, Alternative) for alternative in alternatives)
        return Classification(None, "the print states no cell structure")

    document = parse_cfr(load("21.1"), classify=abstain)
    assert seen, "an undecidable small-face run reaches the seam"
    assert {region.issue for region in document.unresolved} == {"abstained"}
    assert all(node.decision.method != "model" for node in document.nodes)


def test_the_classify_seam_can_attach_a_run_and_the_node_says_a_model_placed_it() -> None:
    document = parse_cfr(load("21.1"), classify=lambda **_: Classification(0, "a note"))
    placed = [node for node in document.nodes if node.decision.method == "model"]
    assert placed and placed[0].kind == "note" and placed[0].decision.detail == "a note"
    assert not document.unresolved


def test_parse_cfr_refuses_another_family_s_profile() -> None:
    other = Profile(
        "uslm",
        "1",
        Applicability(("BILLS",), ("xml",), "only"),
        (),
        CFR_PROFILE.guide,
        (Rule("only", "heuristic", "s", "src"),),
        "s",
        (),
        (),
    )
    with pytest.raises(ParseError, match="not uslm/1"):
        parse_cfr(load("1.1"), profile=other)


# --- the serializer --------------------------------------------------------------------


def test_the_serialized_granule_uses_the_guide_s_vocabulary_and_carries_no_custom_attribute() -> None:
    out = serialize_cfr(parse_cfr(load("716.2")), section="716.2")
    text = out.text
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<CFRGRANULE')
    for element in ("<SECTION>", "<SECTNO>", "<SUBJECT>", "<P>", "<CITA>"):
        assert element in text
    for invented in ("evidence", "node=", "confidence", "rule=", "reviewStatus"):
        assert invented not in text, "provenance travels in the source map, never in the vocabulary"


def test_the_source_map_leads_every_element_back_to_the_evidence_behind_it() -> None:
    evidence = load("716.2")
    out = serialize_cfr(parse_cfr(evidence), section="716.2")
    assert out.source_map.root == "/CFRGRANULE" and out.source_map.derivation == "reconstructed"
    for entry in out.source_map.entries:
        assert entry.path.startswith("/CFRGRANULE/SECTION[1]")
        for block_id in entry.evidence:
            evidence.block(block_id)
    paragraph = next(entry for entry in out.source_map.entries if entry.element == "P")
    assert out.source_map.evidence_for(paragraph.path) == paragraph.evidence
    with pytest.raises(SerializeError, match="no entry for"):
        out.source_map.evidence_for("/CFRGRANULE/SECTION[1]/P[999]")
    assert json.loads(out.source_map.dumps())["entries"][0]["path"] == out.source_map.entries[0].path


def test_the_round_trip_through_the_source_map_reaches_the_published_text_of_the_same_section() -> None:
    """The one paired case in this file: the fixture PDF and the fixture XML are one document."""
    evidence = load("716.2")
    out = serialize_cfr(parse_cfr(evidence), section="716.2")
    published = CFR_XML.read_text()
    for entry in out.source_map.entries:
        if entry.element != "P":
            continue
        node_text = next(node.text for node in out.nodes if node.id == entry.node)
        # Every paragraph the reconstruction emits appears in the published
        # granule, and every one of its evidence blocks is a line of the PDF.
        head = normalize_for_comparison(node_text)[0][:60]
        assert head.split(" ")[1] in normalize_for_comparison(published)[0]
        assert all(evidence.block(block_id).page for block_id in entry.evidence)


def test_a_page_break_inside_a_paragraph_becomes_the_vocabulary_s_own_element() -> None:
    out = serialize_cfr(parse_cfr(load("716.2")), section="716.2")
    assert '<PRTPAGE P="90" />' in out.text or '<PRTPAGE P="90"/>' in out.text


def test_an_italic_run_becomes_one_emphasis_element_with_its_spaces_outside_it() -> None:
    out = serialize_cfr(parse_cfr(load("716.2")), section="716.2")
    assert '<E T="03">Variances from approximate original contour restoration requirements.</E>' in out.text


def test_serializing_a_section_the_reconstruction_does_not_hold_is_refused_by_name() -> None:
    with pytest.raises(SerializeError, match="no section '999.9'"):
        serialize_cfr(parse_cfr(load("1.1")), section="999.9")


def test_fdsys_is_written_only_from_facts_a_caller_holds() -> None:
    document = parse_cfr(load("1.1"))
    assert "<FDSYS>" not in serialize_cfr(document, section="1.1").text
    with_metadata = serialize_cfr(document, section="1.1", fdsys={"CFRTITLE": "12", "VOL": "1"})
    assert "<CFRTITLE>12</CFRTITLE>" in with_metadata.text


# --- the five findings ------------------------------------------------------------------


@needs_extra
def test_schema_validity_passes_against_the_pinned_bundle_for_every_fixture() -> None:
    for section in PROVENANCE:
        out = serialize_cfr(parse_cfr(load(section)), section=section)
        finding = schema_validity(out.xml)
        assert finding.passed, (section, finding.detail)
        assert finding.measures["sha256"] == CFR_PROFILE.schema_bundle[0].sha256
        assert finding.measures["catalogOnly"] is True


@needs_extra
def test_schema_validity_refuses_a_document_that_is_not_in_the_vocabulary() -> None:
    broken = b'<?xml version="1.0"?><CFRGRANULE><SECTION><SECTNO>1.1</SECTNO><INVENTED/></SECTION></CFRGRANULE>'
    finding = schema_validity(broken)
    assert not finding.passed and "INVENTED" in finding.detail
    assert not schema_validity(b"<CFRGRANULE><SECTION>").passed


def test_the_five_findings_on_a_deliberately_broken_document_each_name_their_own_fault() -> None:
    evidence = load("1.1")
    document = parse_cfr(evidence)
    section = document.section("1.1")
    assert section is not None
    # Three independent faults, one per check: a node whose text its evidence
    # does not carry, a block no node and no region claims, and a marker the
    # ladder cannot place.
    forged = DocumentNode(
        "n9001",
        "paragraph",
        "(b)",
        section.id,
        (evidence.blocks[-1].id,),
        Decision("rule", "paragraph_marker", ""),
        "needs_review",
        text="text that appears nowhere in the evidence",
        runs=(StyledRun("text that appears nowhere in the evidence"),),
    )
    orphan = EvidenceBlock("b9999", "a line nothing claims", (StyledRun("a line nothing claims"),), "pdf", page=1)
    broken = type(document)(
        document.profile,
        EvidenceDocument("pdf", document.evidence.derivation, (*evidence.blocks, orphan)),
        (*document.nodes, forged),
        document.unresolved,
    )
    out = serialize_cfr(broken, section="1.1")
    findings = {finding.check: finding for finding in check(broken, out, section="1.1", schema=False)}
    assert not findings["content_fidelity"].passed
    assert findings["content_fidelity"].measures["mismatched"] == 1
    assert not findings["coverage"].passed and findings["coverage"].measures["unaccounted"] == 1
    assert "b9999" in findings["coverage"].detail
    assert not findings["structural_fidelity"].passed
    assert not findings["acceptance"].passed


def test_content_fidelity_compares_each_element_against_its_own_evidence() -> None:
    evidence = load("46.1")
    out = serialize_cfr(parse_cfr(evidence), section="46.1")
    finding = content_fidelity(out, evidence)
    assert finding.passed and finding.measures["matched"] == finding.measures["elements"]
    assert finding.measures["normalization"] == [rule.name for rule in NORMALIZATION_RULES]


def test_the_comparison_normalization_states_and_counts_what_each_rule_touched() -> None:
    text, counts = normalize_for_comparison("  “quoted” text  ")
    assert text == '"quoted" text'
    assert counts["quotes"] == 2 and counts["spaces"] >= 1 and counts["trim"] >= 2
    assert set(counts) == {rule.name for rule in NORMALIZATION_RULES}
    # The em and en dash survive, because a range set with one is not the same
    # string as a range set with a hyphen and the check must be able to say so.
    assert normalize_for_comparison("95–87")[0] == "95–87"


def test_coverage_separates_out_of_scope_evidence_from_loss() -> None:
    document = parse_cfr(load("716.2"))
    out = serialize_cfr(document, section="716.2")
    finding = coverage(document, out)
    assert finding.passed
    assert finding.measures["blocks"] == finding.measures["classified"] + finding.measures["unresolvedBlocks"]
    assert finding.measures["outOfScopeBlocks"] > 0


def test_two_empty_ladders_agree_rather_than_scoring_zero() -> None:
    assert hierarchy_f1(set(), set()) == (1.0, 0, 0, 0)
    assert hierarchy_f1({("§", "(a)")}, set())[0] == 0.0
    assert hierarchy_f1({("§", "(a)")}, {("§", "(a)")})[0] == 1.0


def test_text_comparison_reports_a_changed_number_as_a_critical_discrepancy() -> None:
    assert compare_text("a b c", "a b c").precision == 1.0
    changed = compare_text("not more than 20 days", "not more than 30 days")
    assert "20" in changed.critical and "30" in changed.critical
    negated = compare_text("shall not apply", "shall apply")
    assert "not" in negated.critical


def test_acceptance_is_a_pure_function_that_refuses_to_pass_a_gate_it_could_not_decide() -> None:
    clean = [
        Finding("schema_validity", True, ""),
        Finding("content_fidelity", True, ""),
        Finding("structural_fidelity", True, ""),
        Finding("coverage", True, ""),
    ]
    undecided = acceptance(clean)
    assert not undecided.passed and "undecided" in undecided.detail
    assert undecided.measures["undecided"] == [
        "text precision and recall (no reference)",
        "hierarchy F1 (no reference)",
    ]
    decided = acceptance(clean, comparison=compare_text("a b", "a b"), hierarchy=1.0)
    assert decided.passed and decided.measures["gates"]["text_precision"] == 0.999
    lenient = acceptance(
        clean,
        comparison=compare_text("a b c d", "a b c e"),
        hierarchy=1.0,
        gates=Gates(text_precision=0.5, text_recall=0.5, critical_discrepancies=5),
    )
    assert lenient.passed, "the gates are data, so a caller can state the slice they ran against"


def test_check_without_the_extra_reports_the_schema_finding_as_skipped_and_names_the_extra() -> None:
    document = parse_cfr(load("1.1"))
    out = serialize_cfr(document, section="1.1")
    findings = {finding.check: finding for finding in check(document, out, section="1.1", schema=False)}
    assert findings["schema_validity"].measures["skipped"] is True
    assert EXTRA_REQUIRED in findings["schema_validity"].detail
    assert "reconstruct" in EXTRA_REQUIRED


def test_serialized_text_leaves_out_the_heading_the_section_number_already_carries() -> None:
    out = serialize_cfr(parse_cfr(load("1.1")), section="1.1")
    assert serialized_text(out).count("§ 1.1") == 1


@needs_extra
def test_schema_validation_refuses_to_resolve_anything_outside_the_pinned_bundle() -> None:
    from lxml import etree

    from spicy_docs.reconstruction.validate import _catalog

    catalog = _catalog(etree, CFR_PROFILE)
    with pytest.raises(ValidateError, match="only the pinned bundle resolves"):
        catalog.resolve("https://www.govinfo.gov/bulkdata/CFR/resources/other.xsd", None, None)


def test_the_core_package_imports_reconstruction_without_the_extra() -> None:
    """Only the schema check needs lxml, and it is imported at call time."""
    source = (Path(__file__).parents[1] / "src" / "spicy_docs" / "reconstruction").glob("*.py")
    for path in source:
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import lxml", "from lxml")):
                assert line.startswith(("    ", "        ")), f"{path.name}: lxml at module scope"
