"""Legislative events, independent source cases, and display-progress boundaries."""

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_stage import (
    OUTCOME_STAGES,
    STAGE_KEYS,
    STAGE_RULES,
    STAGES,
    infer_stage,
    infer_stage_from_action,
    infer_stage_from_text,
    signed_date,
    stage_index,
    stage_progress,
)
from spicy_docs.sources.congress.bill_status import BillAction, BillIdentity, parse_bill_status

# Cases originally ported from BillTrax/src/lib/congress-api.test.ts. Failed
# passage, enrollment and reprinting now follow the observed event rather than
# preserve the original false success labels; see docs/sources/bill-stage.md.
PORTED_CASES = [
    (None, "introduced"),
    ("", "introduced"),
    ("Became Public Law No: 119-12.", "law"),
    ("Presented to President.", "presented"),
    ("Resolving differences -- House actions: agreed to House amendment.", "conference"),
    ("Received in the Senate and read twice.", "other_chamber"),
    ("Passed/agreed to in House: On passage agreed to.", "passed_chamber"),
    ("Passed House by recorded vote: 217-212.", "passed_chamber"),
    ("Reported by the Committee on Appropriations. H. Rept. 119-101.", "committee"),
    ("Introduced in House", "introduced"),
    ("Became Public Law; previously engrossed", "law"),
    ("Conference report H. Rept. 119-200 filed.", "conference"),
    ("Message on Senate action sent to the House. (Enrolled.)", "passed_chamber"),
    ("Message on House action received in Senate and at desk: House requests a conference.", "conference"),
    ("Returned to House from Senate with amendments.", "conference"),
    ("Senate insisted on its amendment.", "conference"),
    ("Failed of passage in House.", "failed"),
    ("Agreed to in House without objection.", "passed_chamber"),
    ("Passed by recorded vote: 240 - 190.", "passed_chamber"),
    ("Held at the desk.", "other_chamber"),
    (
        "Read the second time. Placed on Senate Legislative Calendar under General Orders. Calendar No. 140.",
        "other_chamber",
    ),
    ("Placed on the Union Calendar, Calendar No. 548.", "other_chamber"),
    ("Motion to proceed to consideration of measure made in Senate.", "other_chamber"),
    (
        "Cloture on the motion to proceed to the measure not invoked in Senate by Yea-Nay Vote. 54 - 45.",
        "other_chamber",
    ),
    ("Star Print ordered on the bill.", "introduced"),
    ("Approved by President.", "law"),
    ("Became Public Law No: 119-86.", "law"),
]


@pytest.mark.parametrize(("text", "expected"), PORTED_CASES)
def test_ported_stage_cases(text: str | None, expected: str) -> None:
    """Each ported action or version-type text infers its pinned stage."""
    assert infer_stage_from_text(text).stage == expected


def test_ladder_order_and_progress() -> None:
    """The ladder keeps its order and ``stage_progress`` runs 0.0 to 1.0; an unknown stage raises ``ValueError``."""
    assert [stage.key for stage in STAGES] == [
        "introduced",
        "committee",
        "passed_chamber",
        "other_chamber",
        "conference",
        "presented",
        "law",
    ]
    assert stage_index("law") == 6
    assert stage_progress("introduced") == 0.0
    assert stage_progress("law") == 1.0
    with pytest.raises(ValueError, match="unknown stage"):
        stage_progress("vetoed")


def test_rule_order_is_the_published_order() -> None:
    """``STAGE_RULES`` is read in the published order, law through introduced."""
    assert [rule.stage for rule in STAGE_RULES] == [
        "law",
        "presented",
        "conference",
        "passed_chamber",
        "other_chamber",
        "committee",
        "introduced",
    ]


def test_finding_names_the_rule_and_the_matcher() -> None:
    """A finding names the rule and matcher that fired and echoes the source text."""
    finding = infer_stage_from_text("Became Public Law No: 119-12.")
    assert (finding.rule, finding.matcher) == ("law", "became public law")
    assert finding.source_text == "Became Public Law No: 119-12."


def test_no_rule_fires_leaves_the_default_unattributed() -> None:
    """Text no rule matches falls to ``introduced`` with no rule or matcher attributed."""
    finding = infer_stage_from_text("Sponsor withdrew the measure.")
    assert (finding.stage, finding.rule, finding.matcher) == ("introduced", None, None)


# --- Correction 1: untruncated action text (fix ledger item 1) ---

# A real NDAA-class conference action whose only stage word sits past character
# 100, which is where sync-govinfo.ts:248 cut the status before inferring.
LONG_ACTION = (
    "Message on House action received in Senate and at desk: House amendment to Senate amendment "
    "to the bill, with an amendment in the nature of a substitute, agreed to by the Yeas and Nays, "
    "and the bill was then presented to President."
)


def test_truncating_to_100_characters_would_change_the_stage() -> None:
    """The long action reads as ``presented`` whole, but the same text cut at 100 characters falls to ``introduced``."""
    assert len(LONG_ACTION) > 100
    assert infer_stage_from_text(LONG_ACTION).stage == "presented"
    # The behaviour being corrected, shown rather than asserted about in prose:
    # cutting at 100 characters loses every stage word and falls to the floor.
    assert infer_stage_from_text(LONG_ACTION[:100]).stage == "introduced"


def test_infer_stage_reads_actions_whole_and_names_the_action() -> None:
    """``infer_stage`` reads whole action text and reports the matched action's index, date and text."""
    actions = (
        BillAction("Introduced in House", "2025-01-03", None, "Intro-H", None, None, None),
        BillAction(LONG_ACTION, "2025-07-01", None, None, None, None, None),
    )
    finding = infer_stage(actions)
    assert finding.stage == "presented"
    assert finding.action_index == 1
    assert finding.action_date == "2025-07-01"
    assert finding.source_text == LONG_ACTION


# The fold is the stage of the latest classified action. Referrals establish
# committee consideration, not a transition to the other chamber.
REFERRAL = "Referred to the House Committee on Ways and Means."
FOLD_CASES = [
    (("Introduced in House", REFERRAL, "Reported by the Committee on Ways and Means. H. Rept. 119-101."), "committee"),
    (("Introduced in House", REFERRAL, "Passed House by recorded vote: 217-212."), "passed_chamber"),
    (("Introduced in House", REFERRAL), "committee"),
]


@pytest.mark.parametrize(("actions", "expected"), FOLD_CASES)
def test_the_fold_takes_the_latest_classified_action(actions: tuple[str, ...], expected: str) -> None:
    """The fold returns the stage of the latest classified action, not the highest display stage."""
    assert infer_stage(actions).stage == expected


def test_display_order_is_not_progress_order() -> None:
    """``other_chamber`` outranks ``committee`` and ``passed_chamber`` in display order,
    while a referral alone establishes committee consideration.
    """
    # The disagreement the fold must not read as a ladder.
    assert stage_index("other_chamber") > stage_index("committee")
    assert stage_index("other_chamber") > stage_index("passed_chamber")
    assert infer_stage_from_text(REFERRAL).stage == "committee"


def test_an_unclassified_action_leaves_the_stage_alone() -> None:
    """An action no rule matches does not change the stage set by earlier classified actions."""
    actions = ("Introduced in House", REFERRAL, "Sponsor's remarks inserted in the Record.")
    assert infer_stage(actions).stage == "committee"


def test_enactment_is_terminal_and_a_later_star_print_does_not_demote_it() -> None:
    """A public law stays enacted; a later reprint supplies no new legislative stage."""
    assert infer_stage_from_text("Star Print ordered on the bill.").rule is None
    actions = (
        {"text": "Introduced in House", "actionDate": "2025-01-03"},
        {"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04"},
        {"text": "Star Print ordered on the bill.", "actionDate": "2025-07-09"},
    )
    finding = infer_stage(actions)
    assert (finding.stage, finding.action_index, finding.action_date) == ("law", 1, "2025-07-04")


def test_a_newest_first_list_reads_the_same_as_a_chronological_one() -> None:
    """The same actions in reversed order infer the same stage."""
    chronological = (
        {"text": "Introduced in House", "actionDate": "2025-01-03"},
        {"text": REFERRAL, "actionDate": "2025-01-04"},
        {"text": "Reported by the Committee on Ways and Means.", "actionDate": "2025-03-01"},
    )
    assert infer_stage(chronological).stage == "committee"
    assert infer_stage(tuple(reversed(chronological))).stage == "committee"


def test_an_undated_action_never_outranks_a_dated_one() -> None:
    """An action with no date cannot displace the stage of a dated action."""
    actions = (
        {"text": "Reported by the Committee on Ways and Means.", "actionDate": "2025-03-01"},
        {"text": REFERRAL},
    )
    assert infer_stage(actions).stage == "committee"


def test_bare_strings_and_an_action_without_text_are_both_accepted() -> None:
    """Bare strings and textless ``BillAction`` records are accepted, and an empty action list yields no rule."""
    assert infer_stage(("Introduced in House", "Reported by Committee")).stage == "committee"
    assert infer_stage((BillAction(None, "2025-01-03", None, None, None, None, None),)).stage == "introduced"
    assert infer_stage(()).rule is None


# --- Correction 2: one signed-date derivation (fix ledger item 2) ---

LAW_ACTIONS = (
    {"text": "Introduced in House", "actionDate": "2025-01-03", "actionCode": "Intro-H"},
    {"text": "Signed by President.", "actionDate": "2025-07-04", "actionCode": "E30000", "type": "President"},
    {"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04", "actionCode": "36000", "type": "BecameLaw"},
    {"text": "Star Print ordered on the bill.", "actionDate": "2025-07-09"},
)


def test_signed_date_comes_from_the_laws_field_and_the_coded_action() -> None:
    """The signed date comes from the laws entry and the coded became-law action, with rule and action code named."""
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": LAW_ACTIONS})
    assert finding.signed_date == "2025-07-04"
    assert finding.public_law_number == "119-21"
    assert finding.rule == "public_law_and_became_law_action"
    assert (finding.action_index, finding.action_code) == (2, "36000")


def test_a_later_action_does_not_suppress_the_signing_date() -> None:
    """The latest action being an unrelated star print does not suppress the signing date."""
    # congress-api.ts:245-252 keyed on latestAction, so the Star Print action
    # above -- the latest one -- returned no signed date at all.
    assert LAW_ACTIONS[-1]["text"] == "Star Print ordered on the bill."
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": LAW_ACTIONS})
    assert finding.signed_date == "2025-07-04"


def test_the_executive_became_law_code_is_accepted_too() -> None:
    """The executive ``E40000`` code also yields the signing date."""
    actions = ({"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04", "actionCode": "E40000"},)
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": actions})
    assert (finding.signed_date, finding.action_code) == ("2025-07-04", "E40000")


def test_no_public_law_entry_means_no_signing_date() -> None:
    """Without a public-law entry, the rule is ``no_public_law`` and no date or number is reported."""
    finding = signed_date({"laws": [], "actions": LAW_ACTIONS})
    assert (finding.signed_date, finding.public_law_number, finding.rule) == (None, None, "no_public_law")


def test_a_private_law_is_not_a_public_law() -> None:
    """A private law does not satisfy the public-law rule."""
    finding = signed_date({"laws": [{"type": "Private Law", "number": "119-3"}], "actions": LAW_ACTIONS})
    assert finding.rule == "no_public_law"


def test_a_public_law_without_a_coded_action_keeps_the_number_and_names_the_outcome() -> None:
    """A public law without a coded action keeps its number, reports no date, and names that outcome."""
    # Deliberately no fallback to a prose keyword scan: the count of this rule
    # is what would say a fallback is needed.
    actions = ({"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04"},)
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": actions})
    assert finding.signed_date is None
    assert finding.public_law_number == "119-21"
    assert finding.rule == "public_law_without_became_law_action"


@pytest.mark.parametrize(
    "text",
    [
        "Public Print",
        "Star Print ordered on the bill.",
        "Rule H. Res. 456 passed House.",
        "On motion to recommit Failed by the Yeas and Nays: 210 - 218.",
        "DEBATE - The House proceeded with one hour of debate on the question on passage.",
        "A report discussing Public Law 118-5 and signed by President statements.",
    ],
)
def test_printing_other_bills_and_procedural_votes_do_not_establish_success(text):
    assert infer_stage_from_text(text).rule is None


def test_an_executive_code_does_not_turn_a_real_veto_into_enactment():
    finding = infer_stage_from_action({"text": "Vetoed by President.", "actionCode": "E30000"})
    assert finding.stage == "vetoed"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ({"actionCode": "36000"}, ("law", "became_law_code", "36000")),
        ({"actionCode": "E40000"}, ("law", "became_law_code", "E40000")),
        ({"type": "BecameLaw"}, ("law", "became_law_code", "BecameLaw")),
        ({"actionCode": "8000"}, ("passed_chamber", "action_code", "8000")),
        ({"actionCode": "17000"}, ("passed_chamber", "action_code", "17000")),
        ({"actionCode": "28000"}, ("presented", "action_code", "28000")),
        ({"actionCode": "E20000"}, ("presented", "action_code", "E20000")),
        # An unknown code manufactures nothing; the text decides.
        ({"actionCode": "H11100", "text": REFERRAL}, ("committee", "committee", "referred")),
        ({"actionCode": "H8D000"}, ("introduced", None, None)),
    ],
)
def test_only_qualified_publisher_codes_supply_an_event(action, expected):
    """The guide's enactment, passage and presentation codes stand on their own; other codes defer to text."""
    finding = infer_stage_from_action({"text": "Recorded action.", **action})
    assert (finding.stage, finding.rule, finding.matcher) == expected


@pytest.mark.parametrize(
    ("text", "stage"),
    [
        (
            "On motion to suspend the rules and pass the bill, as amended Agreed to by the Yeas and Nays: 400 - 20.",
            "passed_chamber",
        ),
        (
            "On motion to suspend the rules and agree to the resolution Failed by the Yeas and Nays: 250 - 170.",
            "failed",
        ),
        ("On passage Passed by recorded vote: 220 - 207 (Roll no. 123).", "passed_chamber"),
        ("On agreeing to the resolution Agreed to by voice vote.", "passed_chamber"),
        ("Failed of passage in Senate over veto by Yea-Nay Vote. 54 - 45.", "vetoed"),
    ],
)
def test_explicit_vote_results_decide_passage(text, stage):
    """A passage vote is read by its stated result, suspension votes included."""
    assert infer_stage_from_text(text).stage == stage


@pytest.mark.parametrize("text", ["Vetoed by President.", "Pocket Vetoed by President."])
def test_a_veto_names_the_phrase_it_matched(text):
    finding = infer_stage_from_text(text)
    assert (finding.stage, finding.matcher) == ("vetoed", text.lower().rstrip("."))


def test_failure_can_be_reconsidered_but_an_incomplete_override_keeps_the_veto():
    failed = {
        "text": "On motion to suspend the rules and pass the bill Failed by the Yeas and Nays: 200 - 230.",
        "actionDate": "2023-09-18",
    }
    assert infer_stage([failed]).stage == "failed"
    assert (
        infer_stage([failed, {"text": "Passed House by voice vote.", "actionDate": "2023-12-11"}]).stage
        == "passed_chamber"
    )
    actions = [
        {"text": "Vetoed by President.", "actionDate": "2020-12-23"},
        {"text": "Passed House over veto.", "actionDate": "2020-12-28"},
    ]
    assert infer_stage(actions).stage == "vetoed"
    actions.append({"text": "Became Public Law No: 116-283.", "actionDate": "2021-01-01"})
    assert infer_stage(actions).stage == "law"


SAME_DAY_CASES = [
    # Introduction and referral share a date and neither states a time.
    (("Introduced in House", REFERRAL), "committee"),
    # A timed House vote, then the untimed Senate receipt that followed it.
    (
        (
            {"text": "Passed House by recorded vote: 217-212.", "actionTime": "14:10:59"},
            {"text": "Received in the Senate."},
        ),
        "other_chamber",
    ),
    # An untimed introduction, then a timed agreement.
    (
        (
            {"text": "Introduced in House"},
            {"text": "On agreeing to the resolution Agreed to by voice vote.", "actionTime": "19:08:48"},
        ),
        "passed_chamber",
    ),
]


@pytest.mark.parametrize(("chronological", "expected"), SAME_DAY_CASES)
def test_one_days_actions_follow_the_list_order_the_caller_declares(chronological, expected):
    """The same day's actions are ordered by the list, read in the direction the caller states."""
    actions = [
        {"actionDate": "2023-01-09", **action}
        if isinstance(action, dict)
        else {"text": action, "actionDate": "2023-01-09"}
        for action in chronological
    ]
    assert infer_stage(actions).stage == expected
    assert infer_stage(actions[::-1], newest_first=True).stage == expected
    # Read the wrong way round, the earliest action wins: the direction is the caller's to state.
    assert infer_stage(actions[::-1]).stage != expected


@pytest.mark.parametrize("stage", ["failed", "vetoed"])
def test_non_progress_outcomes_have_labels_but_no_false_progress_percentage(stage):
    assert stage in {item.key for item in OUTCOME_STAGES}
    assert stage not in STAGE_KEYS
    assert stage_index(stage) == -1
    with pytest.raises(ValueError, match="unknown stage"):
        stage_progress(stage)


def test_explicit_failure_beats_a_contradictory_passage_code():
    finding = infer_stage_from_action({"text": "Failed of passage in House.", "actionCode": "8000"})
    assert finding.stage == "failed"


_SOURCE_CASES = Path(__file__).parent / "fixtures" / "bill_stage"


@pytest.mark.parametrize("case", json.loads((_SOURCE_CASES / "provenance.json").read_text())["files"])
def test_official_billstatus_event_histories(case):
    status = parse_bill_status(
        (_SOURCE_CASES / case["file"]).read_bytes(),
        identity=BillIdentity(case["congress"], case["bill_type"], case["number"]),
    )
    assert infer_stage(status.actions, newest_first=True).stage == case["expected_stage"]
    assert infer_stage(reversed(status.actions)).stage == case["expected_stage"]
