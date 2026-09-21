"""Legislative stage and signing date from a bill's actions.

Reads a bill's ``<actions>`` (each action's text exactly as published, its
``actionCode``, ``type`` and ``actionDate``) and its ``<laws>`` entries, and
returns one rung of a seven-rung stage ladder plus one signing date, each
carrying the rule that produced it and the action it came from. ``STAGES`` is
display order and ``STAGE_RULES`` is precedence -- two different orders that
disagree, so neither may be read as the other. ``infer_stage`` returns the
stage of the latest action any rule classifies (by date, then position, so
publisher order does not matter), except that enactment is terminal because
becoming law happens once; action text is read untruncated, and the signing
date comes from the ``laws`` entry plus the publisher's own became-law code
rather than a keyword scan of prose, because codes beat prose in both
directions.
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


LAW_STAGE = "law"


def infer_stage(actions: Iterable[object]) -> StageFinding:
    """Return the stage of the latest action any rule classifies.

    ``actions`` holds ``BillAction`` records, mappings shaped like published
    action rows, or bare action-text strings, and text is read whole. "Latest"
    is ``(actionDate, position)``, so a newest-first publisher list and a
    chronological caller list give the same answer and an undated action never
    outranks a dated one; an action no rule classifies leaves the stage alone,
    and enactment is the one terminal rung.
    """
    latest: tuple[tuple[str, int], StageFinding] | None = None
    enacted: tuple[tuple[str, int], StageFinding] | None = None
    for position, action in enumerate(actions):
        finding = infer_stage_from_text(_action_text(action))
        if finding.rule is None:
            continue
        date = _action_date(action)
        located = replace(finding, action_index=position, action_date=date)
        key = (date or "", position)
        if located.stage == LAW_STAGE and (enacted is None or key > enacted[0]):
            enacted = (key, located)
        if latest is None or key > latest[0]:
            latest = (key, located)
    chosen = enacted or latest
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
