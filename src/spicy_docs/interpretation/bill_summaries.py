"""Plain-language summaries: one bill version, and one section diff between two versions.

Reads a version's text, label, title, identity, latest-action status and the
money-bill kind ``money_bills`` derived, and returns a ``BillSummaryResult``
(summary, audience and up to three provisions) or a ``DiffSummaryResult``,
each carrying the provenance BillTrax stored -- model id, prompt version,
content hash, token counts and request/completion timestamps. The framing
table and the prompts are sealed and the model call is injected, so nothing
here reads a database or a network; idempotency is a decision
(``needs_regeneration``) over a cached hash and prompt version, and the caller
does the storing. Both prompts state the JSON object their reader parses from
the same declaration the reader enforces (``SUMMARY_FIELDS``,
``DIFF_SUMMARY_FIELDS``), which the ``v1`` prompts did not and the first live
call refused; the diff route's own guards (a procedural version pair, no diff
rows at all) read data this module is never handed and stay the caller's job,
while a diff of only ``unchanged`` items returns ``None``, the same contract
``summarize_bill`` uses for a version too short to summarize.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from spicy_docs.interpretation.model_call import (
    AnswerField,
    ModelCall,
    ModelCallError,
    answer_schema,
    answer_shape_block,
    require_fields,
)
from spicy_docs.sources.congress.bill_status import BillIdentity

#: v2 (2026-09-19): the prompt names the keys the reader requires. See the
#: module docstring and ``docs/decisions.md``.
PROMPT_VERSION = "v2"
# ~25K characters is roughly 6K tokens of body; the cap controls cost.
TEXT_CHARS = 25_000
MIN_TEXT_CHARS = 200
MAX_PROVISIONS = 3
SUMMARY_CHARS = (60, 1200)

DEFAULT_FRAME = "This is a general bill."

# One framing sentence per money-bill kind. Sealed: the NDAA line in
# particular exists to stop a summary calling an authorization an
# appropriation, which is the single distinction readers of these bills get
# wrong most often.
MONEY_BILL_FRAMES: Mapping[str, str] = MappingProxyType(
    {
        "regular_appropriations": (
            "This is a regular annual appropriations bill. Lead with the agencies funded and the fiscal year."
        ),
        "continuing_resolution": (
            "This is a continuing resolution (CR). Lead with the fact that it keeps agencies funded at "
            "prior-year levels through a specific date, and mention any anomalies."
        ),
        "omnibus": (
            "This is a consolidated / omnibus appropriations package — a single bill bundling multiple "
            "annual appropriations bills."
        ),
        "supplemental": (
            "This is a supplemental appropriations bill — emergency or one-time funding outside the regular "
            "annual cycle. Lead with what it's responding to (disaster, conflict, pandemic, etc.)."
        ),
        "rescission": (
            "This is a rescissions bill that claws back previously appropriated funds. Lead with the dollar "
            "amount and the programs affected."
        ),
        "reconciliation": (
            "This is a budget reconciliation bill. These typically modify tax law and mandatory spending. "
            "They are NOT regular appropriations."
        ),
        "ndaa": (
            "This is the National Defense Authorization Act (NDAA). Important: this AUTHORIZES defense "
            "spending levels — it does NOT appropriate the money. Actual money flows from a separate Defense "
            "Appropriations bill. Make this distinction clear."
        ),
        "other_money": (
            "This bill is money-related (referred to an appropriations committee or similar) but doesn't fit "
            "the major categories."
        ),
    }
)

#: The answer's keys, types and counts, stated once: ``build_prompt`` sends
#: them and ``_read_answer`` enforces them. The prose is the ``v1`` prompt's
#: own three items, now attached to the key each one belongs in.
SUMMARY_FIELDS: tuple[AnswerField, ...] = (
    AnswerField(
        "summary",
        "string",
        "A single paragraph (4–6 sentences) explaining what this bill does, in plain English. Avoid jargon. "
        "Lead with what is funded, by whom, for what period. End with the current legislative status.",
        bounds=SUMMARY_CHARS,
    ),
    AnswerField(
        "audience",
        "string",
        "A short phrase describing the most-affected audience.",
    ),
    AnswerField(
        "topThreeProvisions",
        "array of strings",
        "Up to three notable provisions in plain language, one per entry.",
        bounds=(None, MAX_PROVISIONS),
        # Kept from the v1 reader's own `elif "top_provisions" in data` branch:
        # tolerance for a model that snake-cases a camelCase key, not a spelling
        # any live answer has used. Covered by a test, which is the only thing
        # that keeps an unused tolerance honest.
        aliases=("top_provisions",),
    ),
)

SUMMARY_PROMPT_TEMPLATE = """You are summarizing a U.S. congressional bill for an ordinary citizen \
— someone who does not work in government and does not have a policy background.

Bill: {display_number} — {title}
Version: {version_label}
Current legislative status: {status}

Framing: {frame}

Answer with one JSON object carrying exactly these keys:
{answer_shape}

Bill text (may be truncated):
{body}"""

#: The same declaration as a constraint on the request, which is where
#: ``bill-summaries.ts:41-45`` put it. The prompt bytes do not change: this
#: travels in the request's generation config, not in the prompt.
SUMMARY_ANSWER_SCHEMA = answer_schema(SUMMARY_FIELDS)

#: v2 (2026-09-19): the prompt states the type of each of its five keys.
DIFF_SUMMARY_PROMPT_VERSION = "v2"
#: Diff items beyond this many (after dropping "unchanged" ones) are not sent (route.ts:104).
DIFF_ITEM_CAP = 40
#: Each item's body is excerpted to this many characters (route.ts:107).
DIFF_EXCERPT_CHARS = 300

#: The five keys `summarize/route.ts:119-129` asks for, in its order and its
#: words, now carrying the type each one's reader enforces. An empty array is
#: named on purpose for the three that can legitimately have nothing in them:
#: the reader refuses ``null``, and a prompt that does not say so leaves that
#: choice to the model, which is the whole defect this version fixes.
DIFF_SUMMARY_FIELDS: tuple[AnswerField, ...] = (
    AnswerField("headline", "string", "one sentence summary of the most important change"),
    AnswerField(
        "keyChanges",
        "array of strings",
        "up to 5 bullet points describing the most significant changes",
    ),
    AnswerField(
        "sectionsAdded",
        "array of strings",
        "section headings that were added; an empty array when none were",
    ),
    AnswerField(
        "sectionsRemoved",
        "array of strings",
        "section headings that were removed; an empty array when none were",
    ),
    AnswerField(
        "dollarChanges",
        "array of strings",
        'notable dollar amount changes (e.g. "Section X increased by $2M"); an empty array when none',
    ),
)

# `summarize/route.ts:119-129`'s template literal, kept in its wording and its
# order but no longer byte-for-byte: the answer's shape is now stated (see the
# module docstring). It still carries no non-ASCII bytes, so there are no
# typographic dashes to preserve here, unlike SUMMARY_PROMPT_TEMPLATE above.
DIFF_SUMMARY_PROMPT_TEMPLATE = """Summarize the following bill version diff. The diff shows changes between two versions of an appropriations bill.

Answer with one JSON object carrying exactly these keys:
{answer_shape}

Diff:
{diff_text}"""

#: ``summarize/route.ts:13-19``'s schema, back on the request. ``keyChanges``
#: carries no ``maxItems``: the prompt asks for up to five bullets and the
#: reader enforces no count, and a schema may only state what the reader does.
DIFF_SUMMARY_ANSWER_SCHEMA = answer_schema(DIFF_SUMMARY_FIELDS)


@dataclass(frozen=True, slots=True)
class BillVersionText:
    """One version's text and the bill facts the framing needs."""

    identity: BillIdentity
    version_id: str
    version_label: str
    title: str
    status: str
    text: str
    money_bill_kind: str | None = None


@dataclass(frozen=True, slots=True)
class BillSummaryResult:
    identity: BillIdentity
    version_id: str
    summary: str
    audience: str
    top_provisions: tuple[str, ...]
    model: str
    prompt_version: str
    content_hash: str
    input_tokens: int | None
    output_tokens: int | None
    requested_at: str
    completed_at: str


@dataclass(frozen=True, slots=True)
class DiffItemText:
    """One section-diff row's text-bearing fields -- what the diff-summary prompt reads.

    Mirrors the shape BillTrax's own query selected (``op``, both placements'
    heading and body), not the table-contract's diff family, so this module
    stays source-agnostic and asks only for what its prompt uses.
    """

    op: str
    from_heading: str | None
    to_heading: str | None
    from_body: str | None
    to_body: str | None


@dataclass(frozen=True, slots=True)
class DiffSummaryResult:
    identity: BillIdentity
    from_version_id: str
    to_version_id: str
    headline: str
    key_changes: tuple[str, ...]
    sections_added: tuple[str, ...]
    sections_removed: tuple[str, ...]
    dollar_changes: tuple[str, ...]
    model: str
    prompt_version: str
    content_hash: str
    input_tokens: int | None
    output_tokens: int | None
    requested_at: str
    completed_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def frame_for_kind(kind: str | None) -> str:
    """The sealed framing sentence, or the general-bill default."""
    return MONEY_BILL_FRAMES.get(kind, DEFAULT_FRAME) if kind else DEFAULT_FRAME


def display_number(identity: BillIdentity) -> str:
    return f"{identity.bill_type.upper()} {identity.number}"


def content_hash(text: str) -> str:
    """Hash of the version text, which is what a cached summary is keyed on."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_prompt(version: BillVersionText) -> str:
    return SUMMARY_PROMPT_TEMPLATE.format(
        display_number=display_number(version.identity),
        title=version.title,
        version_label=version.version_label,
        status=version.status,
        frame=frame_for_kind(version.money_bill_kind),
        answer_shape=answer_shape_block(SUMMARY_FIELDS),
        body=version.text[:TEXT_CHARS],
    )


def needs_regeneration(*, cached_content_hash: str | None, cached_prompt_version: str | None, digest: str) -> bool:
    """A cached summary stands only when both its content hash and its prompt version still hold."""
    return cached_content_hash != digest or cached_prompt_version != PROMPT_VERSION


def _read_answer(data: object) -> tuple[str, str, tuple[str, ...]]:
    if not isinstance(data, Mapping):
        raise ModelCallError("summary answer must be a mapping", details=data)
    require_fields(data, SUMMARY_FIELDS, what="summary answer")
    summary_field, audience_field, provisions_field = SUMMARY_FIELDS
    summary = summary_field.value_in(data)
    audience = audience_field.value_in(data)
    provisions = provisions_field.value_in(data)
    if not isinstance(summary, str) or not SUMMARY_CHARS[0] <= len(summary) <= SUMMARY_CHARS[1]:
        raise ModelCallError(
            f"summary must be a string of {SUMMARY_CHARS[0]}-{SUMMARY_CHARS[1]} characters", details=data
        )
    if not isinstance(audience, str) or not audience.strip():
        raise ModelCallError("summary audience must name the most-affected audience", details=data)
    if isinstance(provisions, str) or not isinstance(provisions, Sequence):
        raise ModelCallError("summary provisions must be a list", details=data)
    if len(provisions) > MAX_PROVISIONS:
        raise ModelCallError(f"summary may name at most {MAX_PROVISIONS} provisions", details=data)
    if any(not isinstance(entry, str) for entry in provisions):
        raise ModelCallError("each summary provision must be a string", details=data)
    return summary, audience, tuple(str(entry) for entry in provisions)


def summarize_bill(
    version: BillVersionText,
    call: ModelCall,
    *,
    model: str,
    clock: Callable[[], datetime] | None = None,
) -> BillSummaryResult | None:
    """Summarize one version, or return ``None`` when its text is too short to summarize.

    ``MIN_TEXT_CHARS`` is the original's floor: a stub version with a few words
    of boilerplate produces a confident summary of nothing, which is worse than
    no row at all.
    """
    now = clock if clock is not None else _now
    if len(version.text.strip()) < MIN_TEXT_CHARS:
        return None
    digest = content_hash(version.text)
    prompt = build_prompt(version)
    requested_at = now().isoformat()
    response = call(model=model, prompt=prompt, response_schema=SUMMARY_ANSWER_SCHEMA)
    completed_at = now().isoformat()
    summary, audience, provisions = _read_answer(response.data)
    return BillSummaryResult(
        identity=version.identity,
        version_id=version.version_id,
        summary=summary,
        audience=audience,
        top_provisions=provisions,
        model=model,
        prompt_version=PROMPT_VERSION,
        content_hash=digest,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        requested_at=requested_at,
        completed_at=completed_at,
    )


def _diff_item_line(item: DiffItemText) -> str:
    """One line of the diff text: ``[OP] heading: excerpt``.

    A placement's heading or body is read from the newer side first, older side
    second, exactly like the original's ``??`` chain: only ``None`` falls
    through, so an empty string heading or body is kept as sent, not replaced.
    """
    heading = item.to_heading if item.to_heading is not None else item.from_heading
    if heading is None:
        heading = "(unnamed)"
    body = item.to_body if item.to_body is not None else item.from_body
    excerpt = (body if body is not None else "")[:DIFF_EXCERPT_CHARS]
    return f"[{item.op.upper()}] {heading}: {excerpt}"


def diff_text_from_items(items: Sequence[DiffItemText]) -> str:
    """The ``${diffText}`` block the diff-summary prompt is built from (route.ts:102-110)."""
    changed = [item for item in items if item.op != "unchanged"]
    return "\n\n".join(_diff_item_line(item) for item in changed[:DIFF_ITEM_CAP])


def build_diff_prompt(diff_text: str) -> str:
    return DIFF_SUMMARY_PROMPT_TEMPLATE.format(
        answer_shape=answer_shape_block(DIFF_SUMMARY_FIELDS), diff_text=diff_text
    )


def _read_diff_answer(
    data: object,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(data, Mapping):
        raise ModelCallError("diff summary answer must be a mapping", details=data)
    require_fields(data, DIFF_SUMMARY_FIELDS, what="diff summary answer")
    headline_field, changes_field, added_field, removed_field, dollars_field = DIFF_SUMMARY_FIELDS
    headline = headline_field.value_in(data)
    if not isinstance(headline, str):
        raise ModelCallError("diff summary must state a headline", details=data)

    def _strings(field: AnswerField) -> tuple[str, ...]:
        value = field.value_in(data)
        if isinstance(value, str) or not isinstance(value, Sequence) or any(not isinstance(v, str) for v in value):
            raise ModelCallError(f"diff summary {field.key} must be a list of strings", details=data)
        return tuple(value)

    return (
        headline,
        _strings(changes_field),
        _strings(added_field),
        _strings(removed_field),
        _strings(dollars_field),
    )


def summarize_diff(
    identity: BillIdentity,
    *,
    from_version_id: str,
    to_version_id: str,
    items: Sequence[DiffItemText],
    call: ModelCall,
    model: str,
    clock: Callable[[], datetime] | None = None,
) -> DiffSummaryResult | None:
    """Summarize a section diff between two versions, or ``None`` when it carries nothing to summarize.

    The route's own two guards -- refuse a procedural-document version pair,
    and 404 on no diff rows at all -- read data this function is never handed,
    so they stay the caller's job; the one condition visible from ``items``
    alone -- every row is ``"unchanged"``, so the diff text is empty -- returns
    ``None``.
    """
    now = clock if clock is not None else _now
    diff_body = diff_text_from_items(items)
    if not diff_body:
        return None
    digest = content_hash(diff_body)
    prompt = build_diff_prompt(diff_body)
    requested_at = now().isoformat()
    response = call(model=model, prompt=prompt, response_schema=DIFF_SUMMARY_ANSWER_SCHEMA)
    completed_at = now().isoformat()
    headline, key_changes, sections_added, sections_removed, dollar_changes = _read_diff_answer(response.data)
    return DiffSummaryResult(
        identity=identity,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        headline=headline,
        key_changes=key_changes,
        sections_added=sections_added,
        sections_removed=sections_removed,
        dollar_changes=dollar_changes,
        model=model,
        prompt_version=DIFF_SUMMARY_PROMPT_VERSION,
        content_hash=digest,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        requested_at=requested_at,
        completed_at=completed_at,
    )


__all__ = [
    "DEFAULT_FRAME",
    "DIFF_EXCERPT_CHARS",
    "DIFF_ITEM_CAP",
    "DIFF_SUMMARY_ANSWER_SCHEMA",
    "DIFF_SUMMARY_FIELDS",
    "DIFF_SUMMARY_PROMPT_TEMPLATE",
    "DIFF_SUMMARY_PROMPT_VERSION",
    "MAX_PROVISIONS",
    "MIN_TEXT_CHARS",
    "MONEY_BILL_FRAMES",
    "PROMPT_VERSION",
    "SUMMARY_ANSWER_SCHEMA",
    "SUMMARY_CHARS",
    "SUMMARY_FIELDS",
    "SUMMARY_PROMPT_TEMPLATE",
    "TEXT_CHARS",
    "BillSummaryResult",
    "BillVersionText",
    "DiffItemText",
    "DiffSummaryResult",
    "build_diff_prompt",
    "build_prompt",
    "content_hash",
    "diff_text_from_items",
    "display_number",
    "frame_for_kind",
    "needs_regeneration",
    "summarize_bill",
    "summarize_diff",
]
