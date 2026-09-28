"""Legislative stage and signing date from a bill's retained actions.

The progress ladder keeps its existing keys. Failed passage and veto are
separate outcomes, not positions on that ladder. The latest classified action
wins, except that enactment is terminal and a veto remains until enactment is
recorded. Full source text, matched rule, and action location stay inspectable.

The unitedstates/congress action tests supplied independent veto, failed-vote,
and resolution cases; see docs/sources/bill-stage.md for source pins and the
bounded BILLSTATUS comparison. Only narrowly qualified publisher codes override
prose: the executive E30000 code occurs on both signatures and vetoes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

DEFAULT_STAGE = "introduced"
LAW_STAGE = "law"


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
    Stage("law", "Became law", "Law"),
)
STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in STAGES)
# These have no numerical progress value: a failed vote may later pass, and a
# veto may be overridden. Callers can display their labels beside the ladder.
OUTCOME_STAGES: tuple[Stage, ...] = (
    Stage("failed", "Passage failed", "Failed"),
    Stage("vetoed", "Vetoed", "Veto"),
)
_OUTCOME_KEYS = frozenset(stage.key for stage in OUTCOME_STAGES)


@dataclass(frozen=True, slots=True)
class StageRule:
    """Lowercase substrings; the first rule with any hit wins."""

    stage: str
    matchers: tuple[str, ...]


# Order is load-bearing and each comment says why, as the original did.
STAGE_RULES: tuple[StageRule, ...] = (
    # An enactment statement is checked at the start of the action below;
    # mentioning another public law or ordering a public print is not enactment.
    StageRule(
        "law",
        (
            "became public law",
            "became private law",
            "became law without",
            "signed by president",
            "approved by president",
        ),
    ),
    StageRule(
        "presented",
        ("presented to president", "sent to the president", "transmitted to president"),
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
            "enrolled",
            "passed house",
            "passed senate",
            "passed/agreed to",
            "on passage passed",
            "on passage agreed",
            "agreed to in house",
            "agreed to in senate",
            "passed by recorded vote",
            "passed by voice vote",
        ),
    ),
    StageRule(
        "other_chamber",
        (
            "received in the senate",
            "received in the house",
            "placed on calendar",
            "placed on the union calendar",
            "placed on senate legislative calendar",
            "calendar",
            "held at the desk",
            "motion to proceed",
            "cloture",
        ),
    ),
    # Before "introduced": "reported" can appear alongside "introduced" and is
    # the more advanced stage.
    StageRule("committee", ("reported", "ordered to be reported", "markup", "referred")),
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
    """Position in **display** order; -1 for a stage outside the vocabulary.

    This is where the rung is drawn, not how far the bill has got -- do not
    compare two stages with it.
    """
    return STAGE_KEYS.index(stage) if stage in STAGE_KEYS else -1


def stage_progress(stage: str) -> float:
    """Fraction of the **display** ladder drawn, 0.0 at ``introduced`` and 1.0 at ``law``.

    A declared change from the original, whose ``stageProgress`` returned
    ``-1 / 6`` for an unknown stage: a stage outside the vocabulary raises
    ``ValueError`` here.
    """
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


_VETO_PREFIXES = ("vetoed by president", "pocket vetoed by president")
# Match the vote being decided, not a procedural motion or a quoted bill.
_PASSAGE_VOTE = re.compile(
    r"^(?:on passage\b|on motion to suspend the rules and (?:pass|agree to)\b|"
    r"on (?:agreeing to|adoption of) (?:the )?(?:resolution|concurrent resolution)\b)",
    re.IGNORECASE,
)
_VOTE_FAILED = re.compile(r"\b(?:failed|rejected|not agreed to)\b", re.IGNORECASE)
_VOTE_PASSED = re.compile(r"\b(?:passed|agreed to)\b", re.IGNORECASE)


def infer_stage_from_text(text: str | None) -> StageFinding:
    """Classify an action or version description, retaining explicit non-progress outcomes."""
    if not text:
        return StageFinding(DEFAULT_STAGE, None, None, text, None, None)
    lowered = text.lower().strip()
    for prefix in _VETO_PREFIXES:
        if lowered.startswith(prefix):
            return StageFinding("vetoed", "vetoed", prefix, text, None, None)
    passage_vote = _PASSAGE_VOTE.search(lowered)
    failed = lowered.startswith("failed of passage") or (passage_vote and _VOTE_FAILED.search(lowered))
    if failed:
        stage = "vetoed" if "veto" in lowered or "objections of the president" in lowered else "failed"
        return StageFinding(stage, "failed_passage", "failed passage vote", text, None, None)
    if passage_vote and _VOTE_PASSED.search(lowered):
        return StageFinding("passed_chamber", "passed_chamber", "successful passage vote", text, None, None)
    # These actions describe a rule or a procedural question, not passage of
    # this bill. Upstream distinguishes vote-aux actions for the same reason.
    if lowered.startswith(("rule ", "on motion to recommit", "on motion to commit")):
        return StageFinding(DEFAULT_STAGE, None, None, text, None, None)
    for rule in STAGE_RULES:
        for matcher in rule.matchers:
            if matcher in lowered and (rule.stage != "law" or lowered.startswith(matcher)):
                return StageFinding(rule.stage, rule.stage, matcher, text, None, None)
    return StageFinding(DEFAULT_STAGE, None, None, text, None, None)


# The passage and presentation rows of ``bill_actions.BILLSTATUS_ACTION_CODES``
# (passed/agreed to in House or Senate; presented to President).
_QUALIFIED_ACTION_CODES = {
    "8000": "passed_chamber",
    "17000": "passed_chamber",
    "28000": "presented",
    "E20000": "presented",
}


def infer_stage_from_action(action: object) -> StageFinding:
    """Read qualified BILLSTATUS codes, then the action's complete text.

    The GPO guide warns that action codes were reused. E30000 is deliberately
    absent here: real veto and signature records both carry it. Failed/veto
    text wins over a contradictory passage code. Unknown codes fall back to
    text and do not manufacture a known event.
    """
    finding = infer_stage_from_text(_action_text(action))
    code = _field(action, "action_code", "actionCode")
    if _is_became_law(action):
        matcher = code or _field(action, "action_type", "type")
        return replace(finding, stage=LAW_STAGE, rule="became_law_code", matcher=str(matcher))
    if finding.stage in _OUTCOME_KEYS:
        return finding
    stage = _QUALIFIED_ACTION_CODES.get(code) if isinstance(code, str) else None
    return finding if stage is None else replace(finding, stage=stage, rule="action_code", matcher=code)


def infer_stage(actions: Iterable[object], *, newest_first: bool = False) -> StageFinding:
    """Return the stage of the latest action any rule classifies.

    ``actions`` holds ``BillAction`` records, mappings shaped like published
    action rows, or bare action-text strings, and text is read whole. "Latest"
    is the later ``actionDate``, then the later place in the list; an undated
    action never outranks a dated one. A BILLSTATUS list runs newest first, so
    its caller passes ``newest_first=True`` and a day's first classified action
    is that day's latest. The list's order, not ``actionTime``, orders one
    day's actions: the publisher's order already follows the stated times and
    places the untimed Library of Congress actions among them, where the time
    alone would put a timed House vote after the untimed Senate receipt that
    followed it. Measured on the live ``bill_actions`` generation
    (``c28ed5b1…``, 930,779 actions, 2026-09-28): no adjacent pair runs
    forward in date, and none of 106,013 same-day timed pairs runs forward in
    time (receipt ``unitedstates-reuse-20260928/release-0.51.0/stage-replay/``).
    An action no rule classifies leaves the stage alone, enactment is terminal,
    and a veto remains until enactment is recorded.
    """
    latest: tuple[tuple[str, int], StageFinding] | None = None
    enacted: tuple[tuple[str, int], StageFinding] | None = None
    vetoed: tuple[tuple[str, int], StageFinding] | None = None
    for position, action in enumerate(actions):
        finding = infer_stage_from_action(action)
        if finding.rule is None:
            continue
        date = _action_date(action)
        located = replace(finding, action_index=position, action_date=date)
        key = (date or "", -position if newest_first else position)
        if located.stage == LAW_STAGE and (enacted is None or key > enacted[0]):
            enacted = (key, located)
        if located.stage == "vetoed" and (vetoed is None or key > vetoed[0]):
            vetoed = (key, located)
        if latest is None or key > latest[0]:
            latest = (key, located)
    chosen = enacted or vetoed or latest
    return chosen[1] if chosen else StageFinding(DEFAULT_STAGE, None, None, None, None, None)


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

    ``status`` is a ``BillStatus`` -- which reads ``<laws>`` and each action's
    code -- or a mapping shaped like a published bill row carrying ``actions``
    and ``laws``. A public law entry without a coded action keeps the law
    number and reports ``public_law_without_became_law_action`` rather than
    falling back to a keyword scan of prose: measured zero on the 118th
    Congress's ``hr``/``s`` bulk zips, but an absent action is not a promise no
    future one will lack the code.
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
    "LAW_STAGE",
    "OUTCOME_STAGES",
    "SIGNED_DATE_RULES",
    "STAGES",
    "STAGE_KEYS",
    "STAGE_RULES",
    "SignedDateFinding",
    "Stage",
    "StageFinding",
    "StageRule",
    "infer_stage",
    "infer_stage_from_action",
    "infer_stage_from_text",
    "signed_date",
    "stage_index",
    "stage_progress",
]
