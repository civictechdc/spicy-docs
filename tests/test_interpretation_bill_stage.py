"""Stage rules ported case for case, plus the two corrections the port makes."""

import pytest

from spicy_docs.interpretation.bill_stage import (
    STAGE_RULES,
    STAGES,
    infer_stage,
    infer_stage_from_text,
    signed_date,
    stage_index,
    stage_progress,
)
from spicy_docs.sources.congress.bill_status import BillAction

# Every case from BillTrax/src/lib/congress-api.test.ts, which tested
# inferStageFromAction and nothing else. Version-agnostic: each is action or
# version-type prose, matched by the same rules through the same entry point.
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
    ("Message on Senate action sent to the House. (Enrolled.)", "presented"),
    ("Message on House action received in Senate and at desk: House requests a conference.", "conference"),
    ("Returned to House from Senate with amendments.", "conference"),
    ("Senate insisted on its amendment.", "conference"),
    ("Failed of passage in House.", "passed_chamber"),
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
    ("Star Print ordered on the bill.", "other_chamber"),
    ("Approved by President.", "law"),
    ("Became Public Law No: 119-86.", "law"),
]


@pytest.mark.parametrize(("text", "expected"), PORTED_CASES)
def test_ported_stage_cases(text: str | None, expected: str) -> None:
    assert infer_stage_from_text(text).stage == expected


def test_ladder_order_and_progress() -> None:
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
    finding = infer_stage_from_text("Became Public Law No: 119-12.")
    assert (finding.rule, finding.matcher) == ("law", "public law")
    assert finding.source_text == "Became Public Law No: 119-12."


def test_no_rule_fires_leaves_the_default_unattributed() -> None:
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
    assert len(LONG_ACTION) > 100
    assert infer_stage_from_text(LONG_ACTION).stage == "presented"
    # The behaviour being corrected, shown rather than asserted about in prose:
    # cutting at 100 characters loses every stage word and falls to the floor.
    assert infer_stage_from_text(LONG_ACTION[:100]).stage == "introduced"


def test_infer_stage_reads_actions_whole_and_names_the_action() -> None:
    actions = (
        BillAction("Introduced in House", "2025-01-03", None, "Intro-H", None, None, None),
        BillAction(LONG_ACTION, "2025-07-01", None, None, None, None, None),
    )
    finding = infer_stage(actions)
    assert finding.stage == "presented"
    assert finding.action_index == 1
    assert finding.action_date == "2025-07-01"
    assert finding.source_text == LONG_ACTION


# The fold is the stage of the latest classified action. Display order must
# never stand in for progress: "referred" is a matcher of other_chamber, whose
# display index (3) is above committee (1) and passed_chamber (2), and every
# bill's introduction is a referral.
REFERRAL = "Referred to the House Committee on Ways and Means."
FOLD_CASES = [
    (("Introduced in House", REFERRAL, "Reported by the Committee on Ways and Means. H. Rept. 119-101."), "committee"),
    (("Introduced in House", REFERRAL, "Passed House by recorded vote: 217-212."), "passed_chamber"),
    (("Introduced in House", REFERRAL), "other_chamber"),
]


@pytest.mark.parametrize(("actions", "expected"), FOLD_CASES)
def test_the_fold_takes_the_latest_classified_action(actions: tuple[str, ...], expected: str) -> None:
    assert infer_stage(actions).stage == expected


def test_display_order_is_not_progress_order() -> None:
    # The disagreement the fold must not read as a ladder.
    assert stage_index("other_chamber") > stage_index("committee")
    assert stage_index("other_chamber") > stage_index("passed_chamber")
    assert infer_stage_from_text(REFERRAL).stage == "other_chamber"


def test_an_unclassified_action_leaves_the_stage_alone() -> None:
    actions = ("Introduced in House", REFERRAL, "Sponsor's remarks inserted in the Record.")
    assert infer_stage(actions).stage == "other_chamber"


def test_enactment_is_terminal_and_a_later_star_print_does_not_demote_it() -> None:
    # A star print is not an unclassified action: "star print" is a matcher of
    # other_chamber, so only the terminal-law rule protects the bill here.
    assert infer_stage_from_text("Star Print ordered on the bill.").stage == "other_chamber"
    actions = (
        {"text": "Introduced in House", "actionDate": "2025-01-03"},
        {"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04"},
        {"text": "Star Print ordered on the bill.", "actionDate": "2025-07-09"},
    )
    finding = infer_stage(actions)
    assert (finding.stage, finding.action_index, finding.action_date) == ("law", 1, "2025-07-04")


def test_a_newest_first_list_reads_the_same_as_a_chronological_one() -> None:
    chronological = (
        {"text": "Introduced in House", "actionDate": "2025-01-03"},
        {"text": REFERRAL, "actionDate": "2025-01-04"},
        {"text": "Reported by the Committee on Ways and Means.", "actionDate": "2025-03-01"},
    )
    assert infer_stage(chronological).stage == "committee"
    assert infer_stage(tuple(reversed(chronological))).stage == "committee"


def test_an_undated_action_never_outranks_a_dated_one() -> None:
    actions = (
        {"text": "Reported by the Committee on Ways and Means.", "actionDate": "2025-03-01"},
        {"text": REFERRAL},
    )
    assert infer_stage(actions).stage == "committee"


def test_bare_strings_and_an_action_without_text_are_both_accepted() -> None:
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
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": LAW_ACTIONS})
    assert finding.signed_date == "2025-07-04"
    assert finding.public_law_number == "119-21"
    assert finding.rule == "public_law_and_became_law_action"
    assert (finding.action_index, finding.action_code) == (2, "36000")


def test_a_later_action_does_not_suppress_the_signing_date() -> None:
    # congress-api.ts:245-252 keyed on latestAction, so the Star Print action
    # above -- the latest one -- returned no signed date at all.
    assert LAW_ACTIONS[-1]["text"] == "Star Print ordered on the bill."
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": LAW_ACTIONS})
    assert finding.signed_date == "2025-07-04"


def test_the_executive_became_law_code_is_accepted_too() -> None:
    actions = ({"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04", "actionCode": "E40000"},)
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": actions})
    assert (finding.signed_date, finding.action_code) == ("2025-07-04", "E40000")


def test_no_public_law_entry_means_no_signing_date() -> None:
    finding = signed_date({"laws": [], "actions": LAW_ACTIONS})
    assert (finding.signed_date, finding.public_law_number, finding.rule) == (None, None, "no_public_law")


def test_a_private_law_is_not_a_public_law() -> None:
    finding = signed_date({"laws": [{"type": "Private Law", "number": "119-3"}], "actions": LAW_ACTIONS})
    assert finding.rule == "no_public_law"


def test_a_public_law_without_a_coded_action_keeps_the_number_and_names_the_outcome() -> None:
    # Deliberately no fallback to a prose keyword scan: the count of this rule
    # is what would say a fallback is needed.
    actions = ({"text": "Became Public Law No: 119-21.", "actionDate": "2025-07-04"},)
    finding = signed_date({"laws": [{"type": "Public Law", "number": "119-21"}], "actions": actions})
    assert finding.signed_date is None
    assert finding.public_law_number == "119-21"
    assert finding.rule == "public_law_without_became_law_action"
