"""Money-bill classification from a bill's title and its committee referrals.

Reads the bill's title, its identity and which of the six appropriations,
budget and armed-services committee system codes the publisher referred it to,
and returns one ``MoneyBillFinding`` -- kind, appropriations subcommittee,
fiscal year, the rule that fired and its reason codes -- with a ``kind`` of
``None`` when no rule claims the bill. The ten rules are read in order, most
specific first, as the original read them, and the asymmetry that only the
manual override and the regular-appropriations rule set a subcommittee is
deliberate: a continuing resolution naming Defense is still a continuing
resolution. Referral signals come from the publisher's committee **system
codes**, never from committee-name substrings, which also match
subcommittees, select committees and renamings -- a narrowing that lets a bill
referred only to an appropriations subcommittee classify as nothing rather
than as ``other_money``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

MONEY_BILL_KINDS: tuple[str, ...] = (
    "regular_appropriations",
    "continuing_resolution",
    "omnibus",
    "supplemental",
    "rescission",
    "reconciliation",
    "ndaa",
    "other_money",
)

MONEY_BILL_KIND_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "regular_appropriations": "Regular appropriations",
        "continuing_resolution": "Continuing resolution",
        "omnibus": "Omnibus / consolidated",
        "supplemental": "Supplemental",
        "rescission": "Rescissions",
        "reconciliation": "Reconciliation",
        "ndaa": "Defense authorization (NDAA)",
        "other_money": "Other money bill",
    }
)

REFERRAL_SIGNALS: tuple[str, ...] = ("appropriations", "budget", "armed_services")


@dataclass(frozen=True, slots=True)
class CommitteeCode:
    """One Congress.gov committee system code and the referral signal it raises."""

    code: str
    chamber: str
    signal: str


# The six full-committee system codes money-bill discovery crawls.
COMMITTEE_CODES: tuple[CommitteeCode, ...] = (
    CommitteeCode("hsap00", "house", "appropriations"),
    CommitteeCode("ssap00", "senate", "appropriations"),
    CommitteeCode("hsbu00", "house", "budget"),
    CommitteeCode("ssbu00", "senate", "budget"),
    CommitteeCode("hsas00", "house", "armed_services"),
    CommitteeCode("ssas00", "senate", "armed_services"),
)


@dataclass(frozen=True, slots=True)
class Subcommittee:
    """One of the twelve statutory appropriations subcommittees, and the titles that name it."""

    name: str
    title: re.Pattern[str]


SUBCOMMITTEES: tuple[Subcommittee, ...] = (
    Subcommittee(
        "Agriculture, Rural Development, FDA",
        re.compile(r"agriculture[,\s]+rural\s+development|agriculture\s+and\s+related", re.IGNORECASE),
    ),
    Subcommittee("Commerce, Justice, Science", re.compile(r"commerce[,\s]+justice[,\s]+science", re.IGNORECASE)),
    Subcommittee(
        "Defense",
        re.compile(r"\bdepartment\s+of\s+defense\b|^defense\b|\bdefense\s+appropriations", re.IGNORECASE),
    ),
    Subcommittee("Energy and Water Development", re.compile(r"energy\s+and\s+water", re.IGNORECASE)),
    Subcommittee(
        "Financial Services and General Government",
        re.compile(r"financial\s+services\s+and\s+general\s+government", re.IGNORECASE),
    ),
    Subcommittee("Homeland Security", re.compile(r"homeland\s+security", re.IGNORECASE)),
    Subcommittee("Interior, Environment", re.compile(r"interior[,\s]+environment", re.IGNORECASE)),
    Subcommittee(
        "Labor, HHS, Education",
        re.compile(r"labor[,\s]+health\s+and\s+human\s+services|labor[,\s]+hhs", re.IGNORECASE),
    ),
    Subcommittee("Legislative Branch", re.compile(r"legislative\s+branch", re.IGNORECASE)),
    Subcommittee(
        "Military Construction, Veterans Affairs",
        re.compile(r"military\s+construction[,\s]+(veterans|and\s+veterans)", re.IGNORECASE),
    ),
    Subcommittee("State, Foreign Operations", re.compile(r"state[,\s]+foreign\s+operations", re.IGNORECASE)),
    Subcommittee("Transportation, HUD", re.compile(r"transportation[,\s]+housing", re.IGNORECASE)),
)

FISCAL_YEAR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"fiscal\s+year\s+(\d{4})", re.IGNORECASE),
    re.compile(r"appropriations\s+act,?\s+(\d{4})", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class MoneyBillRule:
    """``name`` is also the reason code the finding records."""

    name: str
    kind: str
    title: re.Pattern[str]
    referral: str | None = None
    sets_subcommittee: bool = False


# Rules 2 through 10; rule 1 is the manual override, which is a lookup rather
# than a pattern and is applied before the table.
MONEY_BILL_RULES: tuple[MoneyBillRule, ...] = (
    # Before every appropriations test: the NDAA authorizes, it does not appropriate.
    MoneyBillRule("title_ndaa", "ndaa", re.compile(r"national\s+defense\s+authorization", re.IGNORECASE)),
    MoneyBillRule(
        "title_continuing_resolution",
        "continuing_resolution",
        re.compile(r"continuing\s+(resolution|appropriations)", re.IGNORECASE),
    ),
    MoneyBillRule("title_supplemental", "supplemental", re.compile(r"supplemental\s+appropriations", re.IGNORECASE)),
    MoneyBillRule("title_rescissions", "rescission", re.compile(r"rescissions?\s+act|^rescissions?\b", re.IGNORECASE)),
    MoneyBillRule(
        "title_omnibus",
        "omnibus",
        re.compile(
            r"(consolidated|further\s+consolidated|further\s+continuing)\s+appropriations|\bomnibus\b",
            re.IGNORECASE,
        ),
    ),
    MoneyBillRule(
        "title_reconciliation",
        "reconciliation",
        re.compile(r"budget\s+reconciliation|reconciliation\s+act", re.IGNORECASE),
    ),
    MoneyBillRule(
        "budget_committee_reconciliation",
        "reconciliation",
        re.compile(r"reconciliation", re.IGNORECASE),
        referral="budget",
    ),
    MoneyBillRule(
        "approps_committee_plus_title",
        "regular_appropriations",
        re.compile(r"appropriations", re.IGNORECASE),
        referral="appropriations",
        sets_subcommittee=True,
    ),
    # A bare appropriations referral is too noisy on its own -- a post-office
    # renaming can collect one -- so a money keyword in the title is required.
    MoneyBillRule(
        "approps_committee_plus_money_keyword",
        "other_money",
        re.compile(
            r"\b(appropriat|fund|rescind|rescission|transfer|reprogram|spend|outlay|budget|fiscal)\w*",
            re.IGNORECASE,
        ),
        referral="appropriations",
    ),
)

# Force-classification for shell-and-strip vehicles, keyed
# ``{congress}-{lowercase type}-{number}``. Empty until one is measured.
MANUAL_OVERRIDES: Mapping[str, str] = MappingProxyType({})

SUBCOMMITTEE_REASON_CODE = "subcommittee_match"
MANUAL_OVERRIDE_RULE = "manual_override"


@dataclass(frozen=True, slots=True)
class MoneyBillFinding:
    """``kind`` and ``rule`` are ``None`` together: no rule claimed the bill."""

    kind: str | None
    subcommittee: str | None
    fiscal_year: str | None
    rule: str | None
    reason_codes: tuple[str, ...]
    congress: int | None
    bill_type: str | None
    number: int | str | None
    title: str


def referrals_from_committee_codes(codes: Iterable[str]) -> frozenset[str]:
    """Map committee system codes to referral signals, ignoring codes outside the six."""
    by_code = {entry.code: entry.signal for entry in COMMITTEE_CODES}
    return frozenset(by_code[code] for code in codes if code in by_code)


def detect_subcommittee(title: str) -> str | None:
    """First of the twelve whose pattern the title matches."""
    for subcommittee in SUBCOMMITTEES:
        if subcommittee.title.search(title):
            return subcommittee.name
    return None


def detect_fiscal_year(title: str) -> str | None:
    """``FY{year}`` from either accepted spelling."""
    for pattern in FISCAL_YEAR_PATTERNS:
        match = pattern.search(title)
        if match:
            return f"FY{match.group(1)}"
    return None


def override_key(congress: int | None, bill_type: str | None, number: int | str | None) -> str:
    return f"{congress}-{'' if bill_type is None else bill_type.lower()}-{number}"


def classify_money_bill(
    *,
    title: str | None,
    congress: int | None = None,
    bill_type: str | None = None,
    number: int | str | None = None,
    referrals: Iterable[str] = (),
) -> MoneyBillFinding:
    """Apply the ten rules in order and return the first that claims the bill.

    ``referrals`` names the committee families the publisher referred this bill
    to, from ``REFERRAL_SIGNALS``. ``armed_services`` is accepted and carried
    because it is how defense bills are discovered, but no rule reads it: the
    NDAA is recognised by its title, and an armed-services referral alone says
    nothing about money. Raises ``ValueError`` for an unknown referral signal.
    """
    text = title or ""
    signals = frozenset(referrals)
    unknown = signals - frozenset(REFERRAL_SIGNALS)
    if unknown:
        raise ValueError(f"unknown referral signals: {sorted(unknown)}")

    fiscal_year = detect_fiscal_year(text)
    subcommittee = detect_subcommittee(text)

    key = override_key(congress, bill_type, number)
    if key in MANUAL_OVERRIDES:
        return MoneyBillFinding(
            MANUAL_OVERRIDES[key],
            subcommittee,
            fiscal_year,
            MANUAL_OVERRIDE_RULE,
            (MANUAL_OVERRIDE_RULE,),
            congress,
            bill_type,
            number,
            text,
        )

    for rule in MONEY_BILL_RULES:
        if rule.referral is not None and rule.referral not in signals:
            continue
        if not rule.title.search(text):
            continue
        reasons = [rule.name]
        matched_subcommittee = None
        if rule.sets_subcommittee:
            matched_subcommittee = subcommittee
            if subcommittee:
                reasons.append(SUBCOMMITTEE_REASON_CODE)
        return MoneyBillFinding(
            rule.kind,
            matched_subcommittee,
            fiscal_year,
            rule.name,
            tuple(reasons),
            congress,
            bill_type,
            number,
            text,
        )

    return MoneyBillFinding(None, None, fiscal_year, None, (), congress, bill_type, number, text)


__all__ = [
    "COMMITTEE_CODES",
    "FISCAL_YEAR_PATTERNS",
    "MANUAL_OVERRIDES",
    "MANUAL_OVERRIDE_RULE",
    "MONEY_BILL_KINDS",
    "MONEY_BILL_KIND_LABELS",
    "MONEY_BILL_RULES",
    "REFERRAL_SIGNALS",
    "SUBCOMMITTEES",
    "SUBCOMMITTEE_REASON_CODE",
    "CommitteeCode",
    "MoneyBillFinding",
    "MoneyBillRule",
    "Subcommittee",
    "classify_money_bill",
    "detect_fiscal_year",
    "detect_subcommittee",
    "override_key",
    "referrals_from_committee_codes",
]
