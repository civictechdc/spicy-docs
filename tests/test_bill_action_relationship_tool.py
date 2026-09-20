"""The bill-action measurement's readings, and the sidecar its report is written from.

The verdict this measurement reaches -- that a House activity report's
bill-action relationship is not extractable well enough to host -- rests on
four things being right: which text a phrase rule runs over, where a sentence
ends, which bill an action attaches to, and what the publisher's own BILLSTATUS
guide already states a code for. Each is pinned here on bytes spelled the way
these prints spell them, because a widened reading would otherwise quietly
raise the yield instead of failing anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis.bill_action_relationship import (
    GUIDE_CODES,
    MARK_END,
    MARK_START,
    PRINT_ACTION_RULE_SET_VERSION,
    PRINT_ACTION_RULES,
    RelationshipError,
    _phrase_matches,
    _rule_set_version,
    flatten,
    guide_action_codes,
    measure_document,
    print_dates,
    read_hand_check,
    render_block,
    score,
    sealed_stage,
    sentence_at,
    sentence_starts,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs/research/bill-action-relationship-2026-09-20.json"
REPORT = ROOT / "docs/research/bill-action-relationship-2026-09-20.md"
GUIDE = ROOT / "tests/fixtures/billstatus_codes/guide-2026-08-03.md"


# --- the flattened matching text -----------------------------------------------------


def test_a_line_wrap_hyphen_is_closed_and_every_span_still_points_at_the_retained_text() -> None:
    """The prints are not gutter-numbered, so ``normalize_gpo_pages`` leaves these in."""
    retained = "the Subcommittee on Health held a hear-\ning on H.R. 2691."
    flat = flatten(retained)

    assert "held a hearing on H.R. 2691." in flat.flat
    start = flat.flat.index("hearing")
    assert retained[flat.to_retained(start) : flat.to_retained(start) + 5] == "hear-"


def test_a_newline_becomes_a_space_and_does_not_move_the_offsets() -> None:
    flat = flatten("ordered H.R. 1432\nfavorably reported")

    assert flat.flat == "ordered H.R. 1432 favorably reported"
    assert flat.to_flat(flat.retained.index("favorably")) == flat.flat.index("favorably")


# --- sentences -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("retained", "expected"),
    [
        # A vote tally is not a list marker. Reading it as one merged the House
        # passage into the sentence after it, which is how an action reaches
        # the wrong bill.
        (
            "the House passed H.R. 1121 by a vote of 229 to 118. On March 21, 2024, the bill was received.",
            2,
        ),
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
    flat = flatten(retained)

    assert len(sentence_starts(flat.flat)) == expected, flat.flat


def test_a_sentence_is_located_by_offset() -> None:
    flat = flatten("First one. Second one here.")
    starts = sentence_starts(flat.flat)

    begin, end = sentence_at(starts, flat.flat, flat.flat.index("Second"))
    assert flat.flat[begin:end] == "Second one here."


# --- the print's phrasings -----------------------------------------------------------


def test_precedence_gives_an_overlapping_span_to_the_first_rule_that_claims_it() -> None:
    """``discharged from further consideration`` is a discharge, not also a consideration,
    and ``declined to mark up`` is a refusal, not a markup."""
    assert [key for key, _, _, _ in _phrase_matches("was discharged from further consideration of H.R. 783")] == [
        "discharged"
    ]
    assert [key for key, _, _, _ in _phrase_matches("Committee Republicans declined to mark up H.R. 4440.")] == [
        "declined_markup"
    ]


def test_the_reported_rule_reads_the_verb_and_not_the_noun_in_a_bill_title() -> None:
    """Measured: the plural noun produced 23 false rows against 162 real ones."""
    assert [key for key, _, _, _ in _phrase_matches("to require periodic reviews and updated reports")] == []
    assert [key for key, _, _, _ in _phrase_matches("the Committee reported the bill to the House")] == ["reported"]


def test_the_public_law_spelling_is_the_citation_rule_s_and_not_a_second_copy() -> None:
    """Four spellings, all of which these prints set."""
    for spelling in ("Public Law 118-15", "P.L. 118–63", "PL 118-31", "Pub. L. No. 118-5"):
        assert [key for key, _, _, _ in _phrase_matches(spelling)] == ["became_public_law"], spelling


@pytest.mark.parametrize(
    ("phrase", "stage", "matcher"),
    [
        ("ordered favorably reported", "committee", "reported"),
        ("referred", "other_chamber", "referred"),
        ("became Public Law", "law", "public law"),
        # The print writes "passed the House"; the sealed matcher is "passed
        # house". One word apart, and the rung is unreachable because of it.
        ("passed the House", None, None),
        ("held a hearing", None, None),
        ("favorably forwarded", None, None),
    ],
)
def test_a_print_phrasing_maps_to_a_rung_only_where_a_sealed_matcher_reads_it(
    phrase: str, stage: str | None, matcher: str | None
) -> None:
    """Derived from ``bill_stage``, never asserted beside it: an unmapped phrasing is
    reported unmapped rather than given a parallel code of its own."""
    assert sealed_stage(phrase) == (stage, matcher)


def test_the_rule_set_version_moves_when_a_pattern_does() -> None:
    edited = (*PRINT_ACTION_RULES[:-1], type(PRINT_ACTION_RULES[-1])("considered", r"\bconsidered\b"))

    assert _rule_set_version(PRINT_ACTION_RULES) == PRINT_ACTION_RULE_SET_VERSION
    assert _rule_set_version(edited) != PRINT_ACTION_RULE_SET_VERSION


# --- dates ---------------------------------------------------------------------------


def test_both_date_spellings_this_family_sets_read_as_iso() -> None:
    assert print_dates("On June 13, 2023, the Committee held a markup") == ("2023-06-13",)
    assert print_dates("3/24/23 FOREIGN AFFAIRS MARKUP SUMMARY") == ("2023-03-24",)
    assert print_dates("no date here") == ()


# --- attachment ----------------------------------------------------------------------


def test_an_action_attaches_to_the_nearest_designator_and_says_so() -> None:
    measured = measure_document(
        "CRPT-118test",
        ["On March 12, 2024, the Committee held a markup of H.R. 1657 and ordered it reported."],
    )
    rows = measured["rows"]

    assert {row["bill_id"] for row in rows} == {"118-hr-1657"}
    assert {row["attachment"] for row in rows} == {"sole"}
    assert measured["mentions"] == 1


def test_a_multi_bill_sentence_is_counted_as_one_and_the_sentence_scoped_variant_beside_it() -> None:
    """The difference between the two row counts *is* the exposure, so both are published."""
    measured = measure_document(
        "CRPT-118test",
        ["On March 19, 2024, the Rules Committee reported H. Res. 1085, providing for consideration of H.R. 1121."],
    )

    assert measured["mentions_in_multi_bill_sentence"] == 2
    assert measured["action_rows"] == 2
    assert measured["sentence_scoped_rows"] == 4


def test_a_phrase_in_a_sentence_naming_no_bill_is_counted_as_an_orphan_and_published_for_nobody() -> None:
    """The en-bloc disposition: 116 of one print's 125 such phrases are shaped like this."""
    page = (
        "6. H.R. 1149, Countering Untrusted Telecommunications Abroad Act (Wild). "
        "The measures considered en bloc were ordered favorably reported to the House by voice vote."
    )
    measured = measure_document("CRPT-118test", [page])

    assert measured["orphan_phrasings"] == {"ordered_reported": 1, "considered": 1}
    assert measured["action_rows"] == 0


# --- what BILLSTATUS already states --------------------------------------------------


def test_every_code_this_tool_claims_is_in_the_publisher_s_own_retained_guide() -> None:
    """The duplication argument rests on this mapping, so it is checked against the
    fixture rather than trusted."""
    stated = guide_action_codes(GUIDE)
    claimed = {code for codes in GUIDE_CODES.values() for code in codes}

    assert claimed <= stated, sorted(claimed - stated)


def test_the_guide_states_a_code_for_a_house_committee_hearing_and_a_house_markup() -> None:
    """The two the print's "committee narrative" was supposed to be the only source for."""
    stated = guide_action_codes(GUIDE)

    assert {"72", "74", "77", "H12200", "H12300"} <= stated


def test_the_phrasings_with_no_billstatus_code_are_the_committee_s_own_voice() -> None:
    """These five, and only these five, are what the print adds that the publisher's
    vocabulary has no code for. A sixth appearing here means the mapping moved."""
    uncoded = {rule.key for rule in PRINT_ACTION_RULES if rule.key not in GUIDE_CODES}

    assert uncoded == {"favorably_forwarded", "declined_markup", "not_considered", "included_in", "vetoed"}


def test_a_missing_guide_is_refused_rather_than_read_as_an_empty_vocabulary(tmp_path: Path) -> None:
    with pytest.raises(RelationshipError):
        guide_action_codes(tmp_path / "absent.md")


# --- the hand check ------------------------------------------------------------------


def test_recall_is_re_weighted_by_the_two_strata_and_not_read_off_the_sample() -> None:
    """The sample is deliberately not uniform, so an unweighted rate would overstate it."""
    rows = [
        {
            "stratum": "with_action",
            "phrase_correct": "yes",
            "bill_correct": "yes",
            "bills_in_sentence": "1",
            "reader_actions": "2",
            "captured_actions": "2",
        },
        {
            "stratum": "without_action",
            "phrase_correct": "",
            "bill_correct": "",
            "bills_in_sentence": "",
            "reader_actions": "2",
            "captured_actions": "0",
        },
    ]

    scored = score(rows, {"with_action": 100, "without_action": 900})
    assert scored["recall"]["per_stratum"]["with_action"]["recall"] == 1.0
    assert scored["recall"]["per_stratum"]["without_action"]["recall"] == 0.0
    # Unweighted this would be 0.5; the larger stratum is the one that misses.
    assert scored["recall"]["recall"] == 0.1


def test_attachment_is_scored_only_where_the_reading_was_right() -> None:
    """A phrase read off the wrong text has no attachment question to answer, and
    folding the two together would hide which one failed."""
    rows = [
        {
            "stratum": "with_action",
            "phrase_correct": "no",
            "bill_correct": "",
            "bills_in_sentence": "1",
            "reader_actions": "1",
            "captured_actions": "0",
        }
    ]

    scored = score(rows, {"with_action": 1, "without_action": 0})
    assert scored["classification"] == {"judged": 1, "correct": 0, "precision": 0.0}
    assert scored["attachment"]["judged"] == 0


def test_a_half_filled_hand_check_sheet_is_refused(tmp_path: Path) -> None:
    from tools.analysis.bill_action_relationship import HAND_CHECK_COLUMNS

    sheet = tmp_path / "hand-check.tsv"
    blank = ["CRPT-118test:1", *[""] * (len(HAND_CHECK_COLUMNS) - 1)]
    sheet.write_text("\t".join(HAND_CHECK_COLUMNS) + "\n" + "\t".join(blank) + "\n")

    with pytest.raises(RelationshipError, match="no verdict"):
        read_hand_check(tmp_path)


# --- the committed sidecar and report ------------------------------------------------


@pytest.fixture(scope="module")
def sidecar() -> dict:
    return json.loads(SIDECAR.read_text())


def test_the_measurement_made_no_request(sidecar: dict) -> None:
    """Everything it read was already retained; a non-zero count means that changed."""
    assert sidecar["requests"] == 0


def test_the_sidecar_was_produced_by_the_rules_committed_beside_it(sidecar: dict) -> None:
    """A sidecar describing a different vocabulary from the one in the tree fails here."""
    assert sidecar["rule_set_version"] == PRINT_ACTION_RULE_SET_VERSION
    assert {row["phrasing"] for row in sidecar["phrasings"]} == {rule.key for rule in PRINT_ACTION_RULES}


def test_the_three_numbers_the_verdict_turns_on(sidecar: dict) -> None:
    """Named one by one, so a silent drift in any of them fails instead of being believed."""
    check = sidecar["hand_check"]

    assert check["mentions_checked"] == 60
    assert check["classification"] == {"judged": 40, "correct": 36, "precision": 0.9}
    assert check["attachment"]["precision"] == 0.8889
    assert check["attachment"]["multi_bill_sentence"] == {"judged": 4, "correct": 2}
    assert check["recall"]["recall"] == 0.596
    assert sidecar["totals"]["rows_whose_phrasing_billstatus_has_no_code_for"] == 280


def test_the_sample_is_one_congress_which_is_what_the_verdict_leaves_open(sidecar: dict) -> None:
    """The pre-108th question is the one thing that would reverse it, and this sample
    cannot ask it."""
    assert sidecar["overlap"]["print_congresses"] == ["118"]


def test_the_report_block_renders_from_the_sidecar_and_matches_what_is_committed(sidecar: dict) -> None:
    """A report drifting from its own measurement fails here instead of being believed."""
    block = render_block(sidecar)
    assert block.startswith(MARK_START) and block.endswith(MARK_END)

    committed = REPORT.read_text()
    start, end = committed.find(MARK_START), committed.find(MARK_END) + len(MARK_END)
    assert start >= 0, "the report carries no generated-block markers"
    assert committed[start:end] == block, "run `render` to bring the report back in line with its sidecar"


def test_the_rendered_block_states_every_number_a_reader_would_act_on(sidecar: dict) -> None:
    block = render_block(sidecar)

    for number in ("0 requests", "1,249 pages", "6,365 bill mentions", "978 distinct bills", "4,456 action rows"):
        assert number in block, number
    for rate in ("**90.0%**", "**88.9%**", "**80.0%**", "**59.6%**", "50.0%"):
        assert rate in block, rate
    assert "**280 rows**" in block
    assert "no pre-108th bill at all" in block


def test_the_prose_numbers_agree_with_the_measurement_too(sidecar: dict) -> None:
    """Numbers the report states in its own words still have to match the sidecar."""
    report = REPORT.read_text()
    totals = sidecar["totals"]

    assert f"{totals['orphan_phrases']:,} further phrase occurrences" in report
    assert f"{totals['sentence_scoped_rows']:,} rows against {totals['action_rows']:,}" in report
    assert f"**{totals['rows_whose_phrasing_billstatus_has_no_code_for']} of {totals['action_rows']:,} rows" in report
    uncoded = [row["phrasing"] for row in sidecar["phrasings"] if not row["billstatus_codes"]]
    coded = len(sidecar["phrasings"]) - len(uncoded)
    assert f"{coded} have an action code" in report
    assert f"{sidecar['overlap']['bills_asked']} of {sidecar['overlap']['bills_asked']}" in report


def test_the_sidecar_carries_no_credential() -> None:
    """The committed bytes, checked the way the sibling measurements check their own."""
    text = SIDECAR.read_text()

    assert "api_key=" not in text
    assert "x-api-key" not in text.casefold()
    assert "<redacted>" not in text, "a redaction in the sidecar means a credential reached it first"
