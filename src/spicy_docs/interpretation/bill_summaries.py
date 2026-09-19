"""Plain-language summary of one bill version, with the provenance it is stored under.

Publisher fact in: one bill version's text, its label, the bill's title,
identity and latest-action status, plus the money-bill kind this package's
``money_bills`` module derived.

Interpretation out: a ``BillSummaryResult`` carrying the summary, the audience
phrase and up to three provisions, and the provenance columns BillTrax's
``bill_summaries`` table already held and this port keeps exactly -- model id,
prompt version, content hash and token counts -- plus the request and
completion timestamps that make a slow or partial run readable afterwards.

Same shape as ``section_classification``: the framing table and the prompt are
the sealed part, the model call is injected, and nothing here reads a database
or a network. Idempotency is a decision, not a lookup: ``needs_regeneration``
answers it from a cached hash and prompt version, and the caller does the
storing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from spicy_docs.interpretation.model_call import ModelCall, ModelCallError
from spicy_docs.sources.congress.bill_status import BillIdentity
from spicy_docs.transport.source_acquirer import utc_now

PROMPT_VERSION = "v1"
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
            "This is a consolidated / omnibus appropriations package - a single bill bundling multiple "
            "annual appropriations bills."
        ),
        "supplemental": (
            "This is a supplemental appropriations bill - emergency or one-time funding outside the regular "
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
            "spending levels - it does NOT appropriate the money. Actual money flows from a separate Defense "
            "Appropriations bill. Make this distinction clear."
        ),
        "other_money": (
            "This bill is money-related (referred to an appropriations committee or similar) but doesn't fit "
            "the major categories."
        ),
    }
)

SUMMARY_PROMPT_TEMPLATE = """You are summarizing a U.S. congressional bill for an ordinary citizen \
- someone who does not work in government and does not have a policy background.

Bill: {display_number} - {title}
Version: {version_label}
Current legislative status: {status}

Framing: {frame}

Write:
1. A single paragraph (4-6 sentences) explaining what this bill does, in plain English. Avoid jargon. \
Lead with what is funded, by whom, for what period. End with the current legislative status.
2. A short phrase describing the most-affected audience.
3. Up to three notable provisions in plain language.

Bill text (may be truncated):
{body}"""


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
    audience: str | None
    top_provisions: tuple[str, ...]
    model: str
    prompt_version: str
    content_hash: str
    input_tokens: int | None
    output_tokens: int | None
    requested_at: str
    completed_at: str


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
        body=version.text[:TEXT_CHARS],
    )


def needs_regeneration(*, cached_content_hash: str | None, cached_prompt_version: str | None, digest: str) -> bool:
    """A cached summary stands only when both its content hash and its prompt version still hold."""
    return cached_content_hash != digest or cached_prompt_version != PROMPT_VERSION


def _read_answer(data: object) -> tuple[str, str | None, tuple[str, ...]]:
    if not isinstance(data, Mapping):
        raise ModelCallError("summary answer must be a mapping", details=data)
    summary = data.get("summary")
    if not isinstance(summary, str) or not SUMMARY_CHARS[0] <= len(summary) <= SUMMARY_CHARS[1]:
        raise ModelCallError(
            f"summary must be a string of {SUMMARY_CHARS[0]}-{SUMMARY_CHARS[1]} characters", details=data
        )
    audience = data.get("audience")
    provisions = data.get("topThreeProvisions", data.get("top_provisions", ()))
    if isinstance(provisions, str) or not isinstance(provisions, Sequence):
        raise ModelCallError("summary provisions must be a list", details=data)
    if len(provisions) > MAX_PROVISIONS:
        raise ModelCallError(f"summary may name at most {MAX_PROVISIONS} provisions", details=data)
    if any(not isinstance(entry, str) for entry in provisions):
        raise ModelCallError("each summary provision must be a string", details=data)
    return summary, audience if isinstance(audience, str) else None, tuple(str(entry) for entry in provisions)


def summarize_bill(
    version: BillVersionText,
    call: ModelCall,
    *,
    model: str,
    clock: Callable[[], datetime] = utc_now,
) -> BillSummaryResult | None:
    """Summarize one version, or return ``None`` when its text is too short to summarize.

    ``MIN_TEXT_CHARS`` is the original's floor: a stub version with a few
    words of boilerplate produces a confident summary of nothing, which is
    worse than no row at all.
    """
    if len(version.text.strip()) < MIN_TEXT_CHARS:
        return None
    digest = content_hash(version.text)
    prompt = build_prompt(version)
    requested_at = clock().isoformat()
    response = call(model=model, prompt=prompt)
    completed_at = clock().isoformat()
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


__all__ = [
    "DEFAULT_FRAME",
    "MAX_PROVISIONS",
    "MIN_TEXT_CHARS",
    "MONEY_BILL_FRAMES",
    "PROMPT_VERSION",
    "SUMMARY_CHARS",
    "SUMMARY_PROMPT_TEMPLATE",
    "TEXT_CHARS",
    "BillSummaryResult",
    "BillVersionText",
    "build_prompt",
    "content_hash",
    "display_number",
    "frame_for_kind",
    "needs_regeneration",
    "summarize_bill",
]
