"""The bill-action rules and the publisher vocabulary behind ``bill_committee_actions``.

The vocabulary scoping is pinned twice: section-3 action codes stay separate
from section-5 ``<versionCode>`` summaries values (72/74), and House
hearing/markup codes are shown to exist in the publisher's responses while the
retained guide omits them. The rest pins flattened matching text, sentence
boundaries this family sets, phrasing precedence, chamber attribution, the
attachment classes and the precision the contract publishes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_actions import (
    ATTACHMENT_MULTI,
    ATTACHMENT_SINGLE,
    BILLSTATUS_ACTION_CODES,
    FROM_THE_WIRE,
    GUIDE_LISTED_CODES,
    HOUSE,
    HOUSE_CODES_ABSENT_FROM_THE_GUIDE,
    PRINT_ACTION_RULE_SET_VERSION,
    PRINT_ACTION_RULES,
    PRINT_ACTION_VOCABULARY_VERSION,
    SENATE,
    UNCODED_IN_THE_GUIDE,
    BillActionError,
    PrintAction,
    _rule_set_version,
    chamber_of,
    find_bill_actions,
    flatten,
    guide_codes_for,
    phrase_matches,
    print_dates,
    sealed_stage,
    sentence_at,
    sentence_starts,
)
from spicy_docs.interpretation.citations import find_citations
from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.bill_action_tables import shape_bill_committee_action
from tools.analysis.bill_action_relationship import (
    GUIDE_SUMMARIES_VERSION_CODES,
    RelationshipError,
    guide_action_codes,
)

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "tests/fixtures/billstatus_codes/guide-2026-08-03.md"
SIDECAR = ROOT / "docs/research/bill-action-relationship-2026-09-20.json"
CITATION_FIXTURES = ROOT / "tests/fixtures/document_citations"


# --- the publisher's action-code vocabulary, scoped ----------------------------------


def test_the_guide_scan_reads_the_action_code_table_and_not_the_whole_document() -> None:
    """Section 3 has 36 codes.  An unscoped scan reached 123 across three tables."""
    codes = guide_action_codes(GUIDE)

    assert len(codes) == 36
    assert {"H12200", "H12300", "13100", "13200", "36000", "8000"} <= codes


def test_the_summaries_version_codes_are_not_action_codes() -> None:
    """Section-5 ``<versionCode>`` values (72, 74, 77, 79, 81, 49) stay out of the action-code set even though they
    appear in the document -- reading them as action codes inverted the first conclusion.
    """
    codes = guide_action_codes(GUIDE)

    assert not (codes & GUIDE_SUMMARIES_VERSION_CODES), sorted(codes & GUIDE_SUMMARIES_VERSION_CODES)
    for absent in ("72", "74", "77", "79", "81", "49"):
        assert absent not in codes, absent
    # ...and they really are in the document, just not in that table.
    assert "| **74** | HOUSE | Markup in House |" in GUIDE.read_text()


def test_every_guide_sourced_code_is_in_the_guide_and_the_wire_codes_are_marked_as_such() -> None:
    """Every guide-sourced code appears in the guide, and the four wire-sourced codes are real but absent from it --
    the distinction the ``source`` field exists for.
    """
    stated = guide_action_codes(GUIDE)

    assert GUIDE_LISTED_CODES <= stated, sorted(GUIDE_LISTED_CODES - stated)
    observed = {
        entry.code for codes in BILLSTATUS_ACTION_CODES.values() for entry in codes if entry.source == FROM_THE_WIRE
    }
    assert observed == {"H21000", "H15000-B", "H15001", "H22000"}
    # ...and every one of them is real and absent from the guide, which is the
    # whole reason the source field exists.
    assert not (observed & stated)


def test_a_house_committee_hearing_and_markup_are_coded_by_a_code_the_guide_omits() -> None:
    """House hearings and markups do have publisher codes (H21000; H15000-B, H15001, H22000); the guide simply omits
    them, which is a gap in the document, not the vocabulary.
    """
    assert guide_codes_for("held_hearing", HOUSE) == ("H21000",)
    assert guide_codes_for("held_markup", HOUSE) == ("H15000-B", "H15001", "H22000")
    assert guide_codes_for("held_hearing", SENATE) == ("13100",)
    assert HOUSE_CODES_ABSENT_FROM_THE_GUIDE == {"held_hearing", "held_markup"}


def test_a_phrasing_with_no_known_code_is_a_different_set_from_one_the_guide_omits() -> None:
    """Phrasings with no code at all stay distinct from phrasings the guide omits; conflating them double-counted
    both.
    """
    assert UNCODED_IN_THE_GUIDE == {
        "vetoed",
        "not_considered",
        "declined_markup",
        "favorably_forwarded",
        "included_in",
    }
    assert not (UNCODED_IN_THE_GUIDE & HOUSE_CODES_ABSENT_FROM_THE_GUIDE)


def test_a_missing_guide_is_refused_rather_than_read_as_an_empty_vocabulary(tmp_path: Path) -> None:
    """A missing guide file raises rather than yielding an empty vocabulary."""
    with pytest.raises(RelationshipError):
        guide_action_codes(tmp_path / "absent.md")


@pytest.mark.parametrize(
    ("phrasing", "matched", "designator", "chamber"),
    [
        # The phrase names the chamber: a Senate passage stated in a House print.
        ("passed_senate", "the Senate passed", "H.R. 2365", SENATE),
        ("received_in_chamber", "received in the Senate", "H.R. 2365", SENATE),
        # Otherwise the measure's own type decides, never the document's.
        ("ordered_reported", "ordered favorably reported", "S. 3475", SENATE),
        ("reported", "reported", "H. Res. 1085", HOUSE),
    ],
)
def test_the_chamber_is_read_off_the_row_and_not_off_the_document(
    phrasing: str, matched: str, designator: str, chamber: str
) -> None:
    """The phrasing's named chamber or the measure's own type decides, never the document's chamber."""
    assert chamber_of(phrasing, matched, designator) == chamber


@pytest.mark.parametrize(
    ("designator", "committee_chamber", "chamber"),
    [
        # A House committee's hearing is a House committee action whatever the
        # measure is. Falling through to the measure's type published `13100`
        # *Senate committee hearings* for a House committee hearing on a Senate
        # bill -- latent today (0 of 639 rows) and wrong whenever it fires.
        ("S. 1234", HOUSE, HOUSE),
        ("H.R. 2365", HOUSE, HOUSE),
        ("S. 1234", SENATE, SENATE),
        # With no stating committee it is left unresolved rather than guessed.
        ("S. 1234", None, None),
    ],
)
def test_a_committee_actor_phrasing_takes_the_committee_s_chamber_not_the_measure_s(
    designator: str, committee_chamber: str | None, chamber: str | None
) -> None:
    """The stating committee's chamber wins for committee-actor phrasings; with none stated it stays unresolved."""
    assert chamber_of("held_hearing", "held a hearing", designator, committee_chamber) == chamber
    assert chamber_of("held_markup", "Markup of", designator, committee_chamber) == chamber


# --- the flattened matching text -----------------------------------------------------


def test_a_line_wrap_hyphen_is_closed_and_every_span_still_points_at_the_retained_text() -> None:
    """A hyphen across a line wrap is closed in the flat text while span offsets still map back to the retained
    ``hear-`` text.
    """
    retained = "the Subcommittee on Health held a hear-\ning on H.R. 2691."
    flat = flatten(retained)

    assert "held a hearing on H.R. 2691." in flat.flat
    start = flat.flat.index("hearing")
    assert retained[flat.to_retained(start) : flat.to_retained(start) + 5] == "hear-"


# --- sentences -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("retained", "expected"),
    [
        # A vote tally is not a list marker. Reading it as one merged the House
        # passage into the sentence after it, which is how an action reaches
        # the wrong bill.
        ("the House passed H.R. 1121 by a vote of 229 to 118. On March 21, 2024, the bill was received.", 2),
        # A sentence may close inside its own quotation marks: a hearing on a
        # discussion draft was attached to the bill named after it.
        ('held a hearing on a draft entitled the "PHE Act of 2023." H.R. 4381 was introduced.', 2),
        # A bill designator is never a sentence end.
        ("The House approved H.J. Res 30 by a vote of 216 to 204. The Senate approved it.", 2),
        ("The Committee filed H. Rept. 118-287 on December 1, 2023.", 1),
        # A real list marker at the head of its own sentence still joins.
        ("1. H.R. 1093, To direct the Secretary (McCaul) 2. H.R. 1159, To amend the Act", 2),
    ],
)
def test_the_sentence_splitter_holds_on_the_shapes_this_family_sets(retained: str, expected: int) -> None:
    """Vote tallies, quoted sentence ends and bill designators never split; real list markers at sentence heads do."""
    flat = flatten(retained)

    assert len(sentence_starts(flat.flat)) == expected, flat.flat


def test_a_sentence_is_located_by_offset() -> None:
    """sentence_at returns the full sentence containing an offset."""
    flat = flatten("First one. Second one here.")
    starts = sentence_starts(flat.flat)

    begin, end = sentence_at(starts, flat.flat, flat.flat.index("Second"))
    assert flat.flat[begin:end] == "Second one here."


# --- the print's phrasings -----------------------------------------------------------


def test_precedence_gives_an_overlapping_span_to_the_first_rule_that_claims_it() -> None:
    """``discharged from further consideration`` is a discharge, not also a consideration,
    and ``declined to mark up`` is a refusal, not a markup."""
    assert [key for key, _, _, _ in phrase_matches("was discharged from further consideration of H.R. 783")] == [
        "discharged"
    ]
    assert [key for key, _, _, _ in phrase_matches("Committee Republicans declined to mark up H.R. 4440.")] == [
        "declined_markup"
    ]


def test_the_reported_rule_reads_the_verb_and_not_the_noun_in_a_bill_title() -> None:
    """Measured: the plural noun produced 23 false rows against 162 real ones."""
    assert [key for key, _, _, _ in phrase_matches("to require periodic reviews and updated reports")] == []
    assert [key for key, _, _, _ in phrase_matches("the Committee reported the bill to the House")] == ["reported"]


def test_the_public_law_spelling_is_the_citation_rule_s_and_not_a_second_copy() -> None:
    """All four public-law spellings map only to became_public_law, via the citation rule."""
    for spelling in ("Public Law 118-15", "P.L. 118–63", "PL 118-31", "Pub. L. No. 118-5"):
        assert [key for key, _, _, _ in phrase_matches(spelling)] == ["became_public_law"], spelling


@pytest.mark.parametrize(
    ("phrase", "stage", "matcher"),
    [
        ("ordered favorably reported", "committee", "reported"),
        ("referred", "other_chamber", "referred"),
        ("became Public Law", "law", "public law"),
        # The print writes "passed the House"; the sealed matcher is "passed
        # house". One word apart, and the rung is unreachable because of it --
        # recorded NULL rather than closed by widening STAGE_RULES.
        ("passed the House", None, None),
        ("held a hearing", None, None),
        ("favorably forwarded", None, None),
    ],
)
def test_a_print_phrasing_maps_to_a_rung_only_where_a_sealed_matcher_reads_it(
    phrase: str, stage: str | None, matcher: str | None
) -> None:
    """A phrasing reaches a stage only through a sealed matcher; unmatched print spellings stay NULL."""
    assert sealed_stage(phrase) == (stage, matcher)


def test_the_vocabulary_is_sealed_and_its_versions_move_with_it() -> None:
    """A published ``print_phrasing`` cannot be renamed, so both versions are pinned."""
    assert PRINT_ACTION_VOCABULARY_VERSION == "001"
    assert _rule_set_version(PRINT_ACTION_RULES) == PRINT_ACTION_RULE_SET_VERSION
    edited = (*PRINT_ACTION_RULES[:-1], PrintAction("considered", r"\bconsidered\b"))
    assert _rule_set_version(edited) != PRINT_ACTION_RULE_SET_VERSION


def test_both_date_spellings_this_family_sets_read_as_iso() -> None:
    """Long and numeric date spellings both yield ISO dates; undated text yields none."""
    assert print_dates("On June 13, 2023, the Committee held a markup") == ("2023-06-13",)
    assert print_dates("3/24/23 FOREIGN AFFAIRS MARKUP SUMMARY") == ("2023-03-24",)
    assert print_dates("no date here") == ()


# --- attachment ----------------------------------------------------------------------


def _actions(text: str):
    """Read bill actions from text under the shared citation rules."""
    citations = find_citations(text, kinds=("bill_number",), congress=118)
    return find_bill_actions(text, citations)


def test_a_one_bill_sentence_is_the_trusted_class() -> None:
    """A one-bill sentence yields ATTACHMENT_SINGLE with ``bills_in_sentence`` 1."""
    reading = _actions("On March 12, 2024, the Committee held a markup of H.R. 1657 and ordered it reported.")

    assert {action.bill_id for action in reading.findings} == {"118-hr-1657"}
    assert {action.attachment for action in reading.findings} == {ATTACHMENT_SINGLE}
    assert {action.bills_in_sentence for action in reading.findings} == {1}


def test_a_multi_bill_sentence_is_marked_rather_than_dropped() -> None:
    """50% precision on the hand check, and kept as evidence a consumer verifies."""
    reading = _actions(
        "On March 19, 2024, the Rules Committee reported H. Res. 1085, providing for consideration of H.R. 1121."
    )

    assert {action.attachment for action in reading.findings} == {ATTACHMENT_MULTI}
    assert {action.bills_in_sentence for action in reading.findings} == {2}
    assert reading.mentions_in_multi_bill_sentence == 2


def test_a_phrase_in_a_sentence_naming_no_bill_is_an_orphan_and_is_published_for_nobody() -> None:
    """A sentence naming no bill yields orphan phrasings and no findings; 116 of one print's 125 such phrases are
    shaped this way.
    """
    reading = _actions(
        "6. H.R. 1149, Countering Untrusted Telecommunications Abroad Act (Wild). "
        "The measures considered en bloc were ordered favorably reported to the House by voice vote."
    )

    assert reading.orphan_phrasings == {"considered": 1, "ordered_reported": 1}
    assert reading.findings == ()


def test_one_sentence_stating_two_phrasings_of_one_event_is_two_rows_with_distinct_spans() -> None:
    """Two phrasings in one sentence yield two rows with distinct spans, which is why identity keys on the phrase
    offset.
    """
    reading = _actions("On September 26, H.R. 9747 was signed by the President and became Public Law No. 118-83.")
    rows = [action for action in reading.findings if action.phrasing == "became_public_law"]

    assert len(rows) == 2
    assert len({row.span_start for row in rows}) == 2


def test_text_that_is_not_text_is_refused() -> None:
    """Non-text input raises BillActionError."""
    with pytest.raises(BillActionError):
        find_bill_actions(b"bytes", ())  # type: ignore[arg-type]


# --- the fixtures, against the committed measurement ---------------------------------


def _fixture_reading(package: str):
    """The retained fixture text and its action reading."""
    text = (CITATION_FIXTURES / f"{package}.txt").read_text()
    lengths = json.loads((CITATION_FIXTURES / f"{package}.json").read_text())["page_lengths"]
    pages, cursor = [], 0
    for length in lengths:
        pages.append(text[cursor : cursor + length])
        cursor += length + 1
    citations = find_citations(text, pages=tuple(pages), kinds=("bill_number",), congress=118)
    # These are House committee activity reports, and a hearing or a markup is
    # the committee's own act, so the committee's chamber is what its code
    # follows.
    return text, find_bill_actions(text, citations, committee_chamber=HOUSE)


@pytest.fixture(scope="module")
def sidecar() -> dict:
    """The committed measurement sidecar."""
    return json.loads(SIDECAR.read_text())


@pytest.mark.parametrize("package", ["CRPT-118hrpt965", "CRPT-118hrpt968"])
def test_the_fixture_rows_reproduce_the_committed_measurement(package: str, sidecar: dict) -> None:
    """The loader and the measurement read one set of bytes, so these cannot drift."""
    _text, reading = _fixture_reading(package)
    expected = sidecar["fixtures"][package]

    assert len(reading.findings) == expected["action_rows"]
    assert sum(1 for a in reading.findings if a.attachment == ATTACHMENT_SINGLE) == expected["trusted_rows"]
    assert sum(reading.orphan_phrasings.values()) == expected["orphan_phrases"]
    assert len({a.bill_id for a in reading.findings}) == expected["distinct_bills_with_an_action"]


def test_the_complete_fixture_reproduces_its_whole_document_row_for_row(sidecar: dict) -> None:
    """``CRPT-118hrpt968`` is 56 pages of 56, so its fixture rows are the document's."""
    _text, reading = _fixture_reading("CRPT-118hrpt968")
    document = next(d for d in sidecar["documents"] if d["package_id"] == "CRPT-118hrpt968")

    assert len(reading.findings) == document["action_rows"]
    assert document["pages"] == sidecar["fixtures"]["CRPT-118hrpt968"]["pages"]
    # The fixture text IS the document the measurement read, not another
    # extraction of it: same bytes, same digest, so the offsets are the same.
    assert sidecar["fixtures"]["CRPT-118hrpt968"]["text_sha256"] == document["text_sha256"]


def test_the_capped_fixture_is_a_prefix_subset_of_the_full_read(sidecar: dict) -> None:
    """``CRPT-118hrpt965`` reads 60 of 282 pages, and every capped row is also a full-read row at the same offset,
    showing offsets are stable under a shorter read.
    """
    _text, reading = _fixture_reading("CRPT-118hrpt965")
    full = next(d for d in sidecar["documents"] if d["package_id"] == "CRPT-118hrpt965")
    counts = sidecar["fixtures"]["CRPT-118hrpt965"]

    assert counts["pages"] == 60 and full["pages"] == 282
    assert len(reading.findings) == counts["action_rows"] < full["action_rows"]
    # `report` holds both reads and records how many of the capped rows are
    # also rows of the full one, keyed on (bill, phrasing, phrase offset).
    # Anything but equality means a shorter read moved an offset.
    assert counts["rows_also_in_the_full_read"] == counts["action_rows"]


# --- the hosted contract -------------------------------------------------------------


def test_a_house_hearing_row_carries_the_wire_code_and_the_contract_says_it_is_off_guide() -> None:
    """The column is not NULL for a House hearing, and the prose has to say the code
    comes from the publisher's responses rather than from a committed fixture."""
    _text, reading = _fixture_reading("CRPT-118hrpt965")
    hearings = [action for action in reading.findings if action.phrasing == "held_hearing"]

    assert hearings, "the fixture states at least one hearing"
    assert all(action.billstatus_action_codes == ("H21000",) for action in hearings)
    assert all(action.chamber == HOUSE for action in hearings)

    description = TABLE_CONTRACTS["bill_committee_actions"].descriptions["billstatus_action_code"]
    assert "not in the retained user guide" in description
    assert "H21000" in description


def test_the_shaped_row_keys_on_the_phrase_offset_so_two_events_do_not_collide() -> None:
    """Two rows from one sentence get distinct contract identity keys, and every shaped row carries exactly the
    contract columns.
    """

    class _Provenance:
        document_key = "CRPT-118test"
        document_kind = "govinfo_package"
        body_rendition = "pdf"
        body_derivation = "pdf-extraction-gpo-normalized"
        text_sha256 = "sha256:abc"

    reading = _actions("On September 26, H.R. 9747 was signed by the President and became Public Law No. 118-83.")
    rows = [shape_bill_committee_action(a, _Provenance(), citation_rule_version="001") for a in reading.findings]
    contract = TABLE_CONTRACTS["bill_committee_actions"]
    keys = {tuple(row[column] for column in contract.identity) for row in rows}

    assert len(keys) == len(rows)
    assert all(set(row) == set(contract.columns) for row in rows)


def test_the_contract_publishes_the_predicate_and_the_measured_precision(sidecar: dict) -> None:
    """A consumer filters on a column, so the column and the number behind it are pinned
    together."""
    contract = TABLE_CONTRACTS["bill_committee_actions"]
    single = sidecar["hand_check"]["published_row_precision"][ATTACHMENT_SINGLE]

    assert "bills_in_sentence" in contract.columns
    assert "attachment_confidence" in contract.columns
    assert single["precision"] == 0.8333
    assert "83.3%" in contract.descriptions["attachment_confidence"]
    assert "4,089 of 4,456" in contract.descriptions["attachment_confidence"]
