"""The eighteen money-bill cases from BillTrax, plus the rule and reason codes the port keeps."""

import pytest

from spicy_docs.interpretation.money_bills import (
    COMMITTEE_CODES,
    MONEY_BILL_KINDS,
    SUBCOMMITTEES,
    classify_money_bill,
    referrals_from_committee_codes,
)

APPROPS = ("appropriations",)
BUDGET = ("budget",)

# Every case from BillTrax/src/lib/money-bills.test.ts, in its order.
PORTED_CASES = [
    ("National Defense Authorization Act for Fiscal Year 2026", (), "ndaa", None, "FY2026"),
    ("Continuing Appropriations Act, 2026", (), "continuing_resolution", None, "FY2026"),
    ("Further Continuing Appropriations Act, 2026", (), "continuing_resolution", None, "FY2026"),
    ("Ukraine Supplemental Appropriations Act, 2026", (), "supplemental", None, "FY2026"),
    ("Rescissions Act of 2026", (), "rescission", None, None),
    ("Consolidated Appropriations Act, 2026", (), "omnibus", None, "FY2026"),
    ("Budget Reconciliation Act of 2026", (), "reconciliation", None, None),
    ("Bill providing for reconciliation pursuant to S. Con. Res. 14", BUDGET, "reconciliation", None, None),
    (
        "Department of Defense Appropriations Act, 2026",
        APPROPS,
        "regular_appropriations",
        "Defense",
        "FY2026",
    ),
    (
        (
            "Departments of Labor, Health and Human Services, and Education, and Related Agencies "
            "Appropriations Act, 2026"
        ),
        APPROPS,
        "regular_appropriations",
        "Labor, HHS, Education",
        "FY2026",
    ),
    (
        "Transportation, Housing and Urban Development, and Related Agencies Appropriations Act, 2026",
        APPROPS,
        "regular_appropriations",
        "Transportation, HUD",
        "FY2026",
    ),
    (
        "To make technical corrections to certain prior appropriations",
        APPROPS,
        "regular_appropriations",
        None,
        None,
    ),
    ("To fund border security operations", APPROPS, "other_money", None, None),
    ("A bill to name a post office after John Smith", (), None, None, None),
    ("", (), None, None, None),
    ("To rename a post office in Boise, Idaho", APPROPS, None, None, None),
    ("National Defense Authorization Act of 2026 (and related appropriations)", APPROPS, "ndaa", None, None),
    (
        "Energy and Water Development Appropriations Act, 2026",
        APPROPS,
        "regular_appropriations",
        "Energy and Water Development",
        "FY2026",
    ),
]


@pytest.mark.parametrize(("title", "referrals", "kind", "subcommittee", "fiscal_year"), PORTED_CASES)
def test_ported_money_bill_cases(
    title: str, referrals: tuple[str, ...], kind: str | None, subcommittee: str | None, fiscal_year: str | None
) -> None:
    finding = classify_money_bill(title=title, congress=119, bill_type="HR", number=1, referrals=referrals)
    assert finding.kind == kind
    assert finding.subcommittee == subcommittee
    assert finding.fiscal_year == fiscal_year


def test_every_declared_kind_is_reachable_from_the_rule_table() -> None:
    reached = {kind for _, _, kind, _, _ in PORTED_CASES if kind is not None}
    # Only the manual-override table, empty on day one, can produce a kind no
    # title rule reaches; every other declared kind has a rule and a case.
    assert reached == set(MONEY_BILL_KINDS)


def test_the_finding_names_its_rule_and_reason_codes() -> None:
    finding = classify_money_bill(title="Department of Defense Appropriations Act, 2026", referrals=APPROPS)
    assert finding.rule == "approps_committee_plus_title"
    assert finding.reason_codes == ("approps_committee_plus_title", "subcommittee_match")

    unclaimed = classify_money_bill(title="To rename a post office in Boise, Idaho", referrals=APPROPS)
    assert (unclaimed.rule, unclaimed.reason_codes) == (None, ())


def test_only_regular_appropriations_carries_a_subcommittee() -> None:
    # A CR naming Defense is still a CR, and BillTrax deliberately dropped the
    # subcommittee on every rule but regular appropriations.
    finding = classify_money_bill(
        title="Continuing Appropriations for the Department of Defense Act, 2026", referrals=APPROPS
    )
    assert (finding.kind, finding.subcommittee) == ("continuing_resolution", None)


def test_identity_travels_with_the_finding() -> None:
    finding = classify_money_bill(title="Rescissions Act of 2026", congress=119, bill_type="hr", number=4366)
    assert (finding.congress, finding.bill_type, finding.number) == (119, "hr", 4366)


def test_the_twelve_statutory_subcommittees_are_all_present() -> None:
    assert len(SUBCOMMITTEES) == 12
    assert len({subcommittee.name for subcommittee in SUBCOMMITTEES}) == 12


def test_referrals_come_from_the_six_committee_system_codes() -> None:
    assert len(COMMITTEE_CODES) == 6
    assert referrals_from_committee_codes(("hsap00", "ssbu00")) == frozenset({"appropriations", "budget"})
    # A committee whose *name* contains "appropriations" but whose code is not
    # one of the six raises no signal: the code derivation is the one kept.
    assert referrals_from_committee_codes(("hsap12",)) == frozenset()


def test_an_unknown_referral_signal_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ValueError, match="unknown referral signals"):
        classify_money_bill(title="Anything", referrals=("apropriations",))


def test_armed_services_is_carried_but_claims_nothing_on_its_own() -> None:
    finding = classify_money_bill(title="To authorize a study of base housing", referrals=("armed_services",))
    assert finding.kind is None
