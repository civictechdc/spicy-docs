"""The measurement's sidecar, and the report that is written from it.

The rules themselves are pinned in ``tests/test_bill_actions.py``, which is
where they live now: this tool imports them rather than restating them, so
there is one home and one set of assertions for them. What is left here is the
measurement's own bookkeeping -- the figures the doc leads with, the strata the
hand check was drawn from, and the byte-comparison that stops the report from
drifting away from the numbers it quotes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_actions import (
    ATTACHMENT_MULTI,
    ATTACHMENT_SINGLE,
    PRINT_ACTION_RULE_SET_VERSION,
    PRINT_ACTION_RULES,
)
from tools.analysis.bill_action_relationship import (
    HAND_CHECK_COLUMNS,
    MARK_END,
    MARK_START,
    RelationshipError,
    read_hand_check,
    render_block,
    score,
)

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs/research/bill-action-relationship-2026-09-20.json"
REPORT = ROOT / "docs/research/bill-action-relationship-2026-09-20.md"


@pytest.fixture(scope="module")
def sidecar() -> dict:
    return json.loads(SIDECAR.read_text())


# --- the hand check's arithmetic -----------------------------------------------------


def test_published_row_precision_counts_a_misread_phrase_against_its_own_class() -> None:
    """A row whose phrase was misread is a wrong published row whatever its
    attachment, so it stays in the denominator of the class it would be published
    under.  Dropping it would flatter the figure a consumer filters on."""
    rows = [
        {
            "stratum": "with_action",
            "phrase_correct": "no",
            "bill_correct": "",
            "bills_in_sentence": "1",
            "reader_actions": "1",
            "captured_actions": "0",
        },
        {
            "stratum": "with_action",
            "phrase_correct": "yes",
            "bill_correct": "yes",
            "bills_in_sentence": "1",
            "reader_actions": "1",
            "captured_actions": "1",
        },
    ]

    scored = score(rows, {"with_action": 2, "without_action": 0})
    assert scored["published_row_precision"][ATTACHMENT_SINGLE] == {"judged": 2, "correct": 1, "precision": 0.5}


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
    # Unweighted this would be 0.5; the larger stratum is the one that misses.
    assert scored["recall"]["recall"] == 0.1


def test_a_half_filled_hand_check_sheet_is_refused(tmp_path: Path) -> None:
    sheet = tmp_path / "hand-check.tsv"
    blank = ["CRPT-118test:1", *[""] * (len(HAND_CHECK_COLUMNS) - 1)]
    sheet.write_text("\t".join(HAND_CHECK_COLUMNS) + "\n" + "\t".join(blank) + "\n")

    with pytest.raises(RelationshipError, match="no verdict"):
        read_hand_check(tmp_path)


# --- the committed sidecar -----------------------------------------------------------


def test_the_offline_phases_made_no_request_and_the_keyed_one_is_bounded(sidecar: dict) -> None:
    """Every figure but the row-for-row overlap comes from retained bytes; that one
    cost 20 keyed requests and the bound is part of the claim."""
    assert sidecar["requests"] == 0
    assert sidecar["billstatus_overlap"]["bills_requested"] == 20


def test_the_sidecar_was_produced_by_the_rules_committed_beside_it(sidecar: dict) -> None:
    assert sidecar["rule_set_version"] == PRINT_ACTION_RULE_SET_VERSION
    assert {row["phrasing"] for row in sidecar["phrasings"]} == {rule.key for rule in PRINT_ACTION_RULES}


def test_the_figures_the_verdict_turns_on(sidecar: dict) -> None:
    """Named one by one, so a silent drift fails here instead of being believed."""
    check = sidecar["hand_check"]
    totals = sidecar["totals"]

    assert check["mentions_checked"] == 60
    assert check["published_row_precision"][ATTACHMENT_SINGLE] == {"judged": 36, "correct": 30, "precision": 0.8333}
    assert check["published_row_precision"][ATTACHMENT_MULTI] == {"judged": 4, "correct": 2, "precision": 0.5}
    assert check["recall"]["recall"] == 0.596
    assert totals["action_rows"] == 4456
    assert totals["trusted_rows"] == 4089
    assert totals["orphan_phrases"] == 2952


def test_the_row_for_row_overlap_reads_the_publisher_s_own_codes(sidecar: dict) -> None:
    """The claim rests on what the publisher's responses say, not on this repository's
    mapping.  The earlier version asserted ``code_matched == 0``, which was an identity:
    the mapping for these two phrasings was empty by construction, so the branch that
    would have read ``actionCode`` never ran."""
    overlap = sidecar["billstatus_overlap"]
    hearing = overlap["per_phrasing"]["held_hearing"]
    markup = overlap["per_phrasing"]["held_markup"]

    # Read off the response, matched on the event's wording.
    assert hearing["publisher_codes_on_matched_wording"] == ["H21000"]
    assert markup["publisher_codes_on_matched_wording"] == ["H15000-B", "H15001", "H22000"]
    # ...and none of the four is in the retained guide, which is how the guide
    # was shown to be an incomplete document rather than the vocabulary.
    absent = set(overlap["wire_codes_absent_from_the_guide"])
    assert {"H21000", "H15000-B", "H15001", "H22000"} <= absent
    assert len(absent) == 13 and overlap["publisher_distinct_codes"] == 35

    # The narrower claim the table is built on.
    assert hearing["rows"] - hearing["stated_by_any_wording"] == 10
    assert markup["stated_by_any_wording"] == markup["rows"]
    assert overlap["publisher_source_systems"]["House committee actions"] > 0


def test_the_sample_is_one_congress_which_is_what_the_verdict_leaves_open(sidecar: dict) -> None:
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

    for number in ("0 requests", "1,249 pages", "6,365 bill mentions", "4,456 action rows", "4,089 of 4,456"):
        assert number in block, number
    for rate in ("**83.3%**", "**50.0%**", "**59.6%**"):
        assert rate in block, rate
    assert "13 of the 35 distinct codes" in block
    assert "10 of 15 subcommittee hearings" in block
    assert "`H21000`" in block and "`H15000-B`" in block
    assert "no pre-108th bill at all" in block


def test_the_sidecar_carries_no_credential() -> None:
    text = SIDECAR.read_text()

    assert "api_key=" not in text
    assert "x-api-key" not in text.casefold()
    assert "<redacted>" not in text, "a redaction in the sidecar means a credential reached it first"
