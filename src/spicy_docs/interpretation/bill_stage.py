"""Legislative stage and signing date from a bill's actions.

Publisher fact in: a bill's ``<actions>`` -- each action's text exactly as
published, its ``actionCode``, its ``type`` and its ``actionDate`` -- and the
bill's ``<laws>`` entries.

Interpretation out: one rung of a seven-rung stage ladder, and one signing
date, each carrying the rule that produced it and the index, code and date of
the action it came from, so a hosted row can be audited back to the action
that moved it.

Two corrections to the behaviour this was ported from
(``BillTrax/src/lib/congress-api.ts``, ``stages.ts``):

* **Stage inference reads untruncated action text.** ``sync-govinfo.ts:248``
  truncated the status to 100 characters and then inferred the stage from the
  truncated string, although ``migrations/021`` had widened that column to 500
  precisely because long actions exist. A matcher that sits past character 100
  -- "Presented to President", say, after a long conference recital -- was
  unreachable. Nothing here truncates.
* **One signing-date derivation, not two.** BillTrax derived ``signed_date``
  two incompatible ways: ``congress-api.ts:245-252`` read
  ``latestAction.actionDate`` gated on keywords in ``latestAction.text``, so
  any later action superseded the signing and the date went null;
  ``sync-govinfo.ts:225-232`` scanned every action for a ``/became.*public
  law/i`` text match. The surviving rule is neither keyword scan: the bill's
  ``laws`` entry establishes *that* it became law and supplies the public law
  number, and the action whose ``actionCode`` is the publisher's own
  "became public law" code supplies the date. Codes and a structured field
  beat prose in both directions -- prose is translated, reworded and
  occasionally absent, while ``actionCode`` is the publisher's identifier for
  the event.

``infer_stage`` takes the whole action list rather than only the latest
action, and returns the furthest rung reached, because the ladder is ordered
and a procedural action filed after a signing must not demote a law back to
``other_chamber``. Feeding a single action or a version-type string is
``infer_stage_from_text``, which is the rule set BillTrax exposed twice, once
per caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

DEFAULT_STAGE = "introduced"


@dataclass(frozen=True, slots=True)
class Stage:
    """One rung, with the display strings that travel with the vocabulary."""

    key: str
    label: str
    short: str


STAGES: tuple[Stage, ...] = (
    Stage("introduced", "Introduced", "Intro"),
    Stage("committee", "In committee", "Cmte"),
    Stage("passed_chamber", "Passed chamber", "Pass"),
    Stage("other_chamber", "Other chamber", "Other"),
    Stage("conference", "Conference", "Conf"),
    Stage("presented", "Presented to President", "Pres"),
    Stage("law", "Signed into law", "Law"),
)
STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in STAGES)


@dataclass(frozen=True, slots=True)
class StageRule:
    """Lowercase substrings; the first rule with any hit wins."""

    stage: str
    matchers: tuple[str, ...]


# Order is load-bearing and each comment says why, as the original did.
STAGE_RULES: tuple[StageRule, ...] = (
    # First: "public law" is a substring of many action texts that also carry
    # an earlier stage's wording.
    StageRule(
        "law",
        (
            "public law",
            "public print",
            "became public law",
            "signed by president",
            "approved by president",
        ),
    ),
    StageRule(
        "presented",
        ("enrolled", "presented to president", "sent to the president", "transmitted to president"),
    ),
    StageRule(
        "conference",
        (
            "conference report",
            "conference committee",
            "resolving differences",
            "requests a conference",
            "sent to conference",
            "appointed conferees",
            "returned to house from senate with amendment",
            "returned to senate from house with amendment",
            "house insisted on its amendment",
            "senate insisted on its amendment",
        ),
    ),
    StageRule(
        "passed_chamber",
        (
            "engrossed",
            "passed house",
            "passed senate",
            "passed/agreed to",
            "on passage",
            "agreed to in house",
            "agreed to in senate",
            "passed by recorded vote",
            "passed by voice vote",
            "failed of passage",
        ),
    ),
    StageRule(
        "other_chamber",
        (
            "received in the senate",
            "received in the house",
            "referred",
            "placed on calendar",
            "placed on the union calendar",
            "placed on senate legislative calendar",
            "calendar",
            "held at the desk",
            "motion to proceed",
            "cloture",
            "star print",
        ),
    ),
    # Before "introduced": "reported" can appear alongside "introduced" and is
    # the more advanced stage.
    StageRule("committee", ("reported", "ordered to be reported", "markup")),
    StageRule("introduced", ("introduced",)),
)


@dataclass(frozen=True, slots=True)
class StageFinding:
    """``rule`` and ``matcher`` are ``None`` when no rule fired and the default stood."""

    stage: str
    rule: str | None
    matcher: str | None
    source_text: str | None
    action_index: int | None
    action_date: str | None


def stage_index(stage: str) -> int:
    """Position on the ladder; -1 for a stage outside the vocabulary."""
    return STAGE_KEYS.index(stage) if stage in STAGE_KEYS else -1


def stage_progress(stage: str) -> float:
    """Fraction of the ladder travelled, 0.0 at ``introduced`` and 1.0 at ``law``."""
    index = stage_index(stage)
    if index < 0:
        raise ValueError(f"unknown stage {stage!r}")
    return index / (len(STAGES) - 1)


def _field(record: object, *names: str) -> object:
    """Read the first of ``names`` a mapping holds or an object carries."""
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return None
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    return None


def _action_text(action: object) -> str | None:
    if action is None or isinstance(action, str):
        return action
    value = _field(action, "text")
    return value if isinstance(value, str) else None


def _action_date(action: object) -> str | None:
    if action is None or isinstance(action, str):
        return None
    value = _field(action, "action_date", "actionDate")
    return value if isinstance(value, str) else None


def infer_stage_from_text(text: str | None) -> StageFinding:
    """Match one action text -- or one version-type string -- against the rules in order."""
    if not text:
        return StageFinding(DEFAULT_STAGE, None, None, text, None, None)
    lowered = text.lower()
    for rule in STAGE_RULES:
        for matcher in rule.matchers:
            if matcher in lowered:
                return StageFinding(rule.stage, rule.stage, matcher, text, None, None)
    return StageFinding(DEFAULT_STAGE, None, None, text, None, None)


def infer_stage(actions: Iterable[object]) -> StageFinding:
    """Return the furthest rung any action reaches, naming the action that reached it.

    ``actions`` holds ``BillAction`` records, mappings shaped like published
    action rows, or bare action-text strings. Text is read whole: an action is
    never shortened before matching.
    """
    best = StageFinding(DEFAULT_STAGE, None, None, None, None, None)
    best_index = -1
    for position, action in enumerate(actions):
        finding = infer_stage_from_text(_action_text(action))
        if finding.rule is None:
            continue
        index = stage_index(finding.stage)
        if index > best_index:
            best_index = index
            best = replace(finding, action_index=position, action_date=_action_date(action))
    return best


# The publisher's own identifiers for "became public law": ``36000`` is the
# Library of Congress code (``type`` "BecameLaw") and ``E40000`` the executive
# code carrying the same event; both appear on the same bill with the same
# date. ``type`` is checked too so a future code spelling still resolves.
BECAME_PUBLIC_LAW_ACTION_CODES = frozenset({"36000", "E40000"})
BECAME_PUBLIC_LAW_ACTION_TYPE = "BecameLaw"
PUBLIC_LAW_TYPE_TERM = "public"

SIGNED_DATE_RULES: tuple[str, ...] = (
    "public_law_and_became_law_action",
    "public_law_without_became_law_action",
    "no_public_law",
)


@dataclass(frozen=True, slots=True)
class SignedDateFinding:
    """``signed_date`` is ``None`` unless the coded action supplied one."""

    signed_date: str | None
    public_law_number: str | None
    rule: str
    action_index: int | None
    action_code: str | None


def _public_law_number(laws: object) -> str | None:
    if not isinstance(laws, Iterable) or isinstance(laws, str | Mapping):
        return None
    for entry in laws:
        law_type = _field(entry, "type")
        number = _field(entry, "number")
        if isinstance(law_type, str) and PUBLIC_LAW_TYPE_TERM in law_type.lower() and isinstance(number, str):
            return number
    return None


def _is_became_law(action: object) -> bool:
    code = _field(action, "action_code", "actionCode")
    if isinstance(code, str) and code in BECAME_PUBLIC_LAW_ACTION_CODES:
        return True
    action_type = _field(action, "action_type", "type")
    return isinstance(action_type, str) and action_type == BECAME_PUBLIC_LAW_ACTION_TYPE


def signed_date(status: object) -> SignedDateFinding:
    """Derive the signing date from the ``laws`` entry and the coded became-law action.

    ``status`` is a ``BillStatus``, or a mapping shaped like a published bill
    row, carrying ``actions`` and ``laws``. ``BillStatus`` does not yet read
    ``<laws>``; a caller holding that element passes a mapping until it does,
    and this function needs no change when it lands.

    A public law entry without a coded action keeps the law number and reports
    ``public_law_without_became_law_action`` rather than falling back to a
    keyword scan of prose -- the outcome BillTrax's two derivations disagreed
    about. The count of that rule is what says whether a fallback is ever
    needed, which a silent regex would have hidden.
    """
    number = _public_law_number(_field(status, "laws"))
    if number is None:
        return SignedDateFinding(None, None, "no_public_law", None, None)
    actions = _field(status, "actions")
    if isinstance(actions, Iterable) and not isinstance(actions, str | Mapping):
        for position, action in enumerate(actions):
            if not _is_became_law(action):
                continue
            date = _field(action, "action_date", "actionDate")
            code = _field(action, "action_code", "actionCode")
            return SignedDateFinding(
                date if isinstance(date, str) else None,
                number,
                "public_law_and_became_law_action",
                position,
                code if isinstance(code, str) else None,
            )
    return SignedDateFinding(None, number, "public_law_without_became_law_action", None, None)


__all__ = [
    "BECAME_PUBLIC_LAW_ACTION_CODES",
    "BECAME_PUBLIC_LAW_ACTION_TYPE",
    "DEFAULT_STAGE",
    "SIGNED_DATE_RULES",
    "STAGES",
    "STAGE_KEYS",
    "STAGE_RULES",
    "SignedDateFinding",
    "Stage",
    "StageFinding",
    "StageRule",
    "infer_stage",
    "infer_stage_from_text",
    "signed_date",
    "stage_index",
    "stage_progress",
]
