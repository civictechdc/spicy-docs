"""The one injected model seam the two model-backed interpretation modules share.

``section_classification`` and ``bill_summaries`` both send a prompt and read
back structured output with token counts. Neither owns a client: the caller
passes a ``ModelCall``, exactly as ``spicy_docs.extraction.gemini`` takes an
injected ``GenerationClient``, so the rules stay pure and a test needs no
network. What the modules own is the prompt, the sealed vocabulary and the
provenance the answer is stored with.

``AnswerField`` is the other half of that seam, and it exists because of a
measured failure. The bill-summary prompt asked for its three items in prose
and never named the JSON keys ``_read_answer`` required; the first live call
(2026-09-19, receipt ``c1-provenance.json``) came back with
``affected_audience`` and ``notable_provisions`` where the reader wanted
``audience`` and ``topThreeProvisions``, and every row would have been refused.
A prompt and its reader must therefore be **one statement**: each module
declares its answer's keys, types and counts once as ``AnswerField`` records,
``answer_shape_block`` turns that declaration into the lines the prompt sends,
and the reader looks its values up through the same records. Neither side can
name a key the other does not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class ModelCallError(RuntimeError):
    """The model's answer does not satisfy the prompt's stated shape."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """``data`` is the parsed structured answer; token counts are provenance, kept when reported."""

    data: Any
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelCall(Protocol):
    def __call__(self, *, model: str, prompt: str) -> ModelResponse: ...


@dataclass(frozen=True, slots=True)
class AnswerField:
    """One key the prompt asks for and the reader requires, declared once.

    ``kind`` states the type and any count the reader actually enforces, in
    the words the prompt sends, so the request cannot promise a shape the
    reader refuses. ``aliases`` are spellings the reader also accepts but the
    prompt does not offer: a one-directional tolerance for a model that
    snake-cases a camelCase key, never a second name the answer may choose
    between.
    """

    key: str
    kind: str
    describes: str
    aliases: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Every spelling the reader accepts, canonical first."""
        return (self.key, *self.aliases)

    def present_in(self, data: Mapping[str, Any]) -> bool:
        return any(name in data for name in self.names)

    def value_in(self, data: Mapping[str, Any]) -> Any:
        """The answer's value under the first spelling it used, or ``None``."""
        for name in self.names:
            if name in data:
                return data[name]
        return None


def answer_shape_block(fields: Sequence[AnswerField]) -> str:
    """The prompt's key list, generated from the fields the reader reads."""
    return "\n".join(f'- "{field.key}" ({field.kind}): {field.describes}' for field in fields)


def require_fields(data: Mapping[str, Any], fields: Sequence[AnswerField], *, what: str) -> None:
    """Refuse an answer missing any declared key, naming **every** one it left out.

    Named together rather than one per call: the measured failure was missing
    two keys, and a reader that reports only the first makes the second look
    like a new defect after the first is fixed.
    """
    missing = [field.key for field in fields if not field.present_in(data)]
    if missing:
        raise ModelCallError(f"{what} is missing {', '.join(missing)}", details=data)


__all__ = [
    "AnswerField",
    "ModelCall",
    "ModelCallError",
    "ModelResponse",
    "answer_shape_block",
    "require_fields",
]
