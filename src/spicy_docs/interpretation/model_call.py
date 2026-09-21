"""The one injected model seam the two model-backed interpretation modules share.

``section_classification`` and ``bill_summaries`` each own their prompt, their
sealed vocabulary and their answer's provenance, but neither owns a client:
the caller passes a ``ModelCall``, exactly as ``extraction.gemini`` takes an
injected ``GenerationClient``, so the rules stay pure and a test needs no
network. ``AnswerField`` exists because a measured failure showed a prompt and
its reader must be one statement: the ``v1`` summary prompt asked for its
items in prose and never named the JSON keys the reader required, and the
first live call's answer was refused, so each module declares its answer's
keys, types and counts once, ``answer_shape_block`` turns that declaration
into the prompt's lines, and the reader looks its values up through the same
records -- neither side can name a key the other does not. Since 2026-09-20
that one declaration also states the shape on the request, as a draft 2020-12
JSON Schema from :func:`answer_schema` sent as Gemini's ``responseJsonSchema``
(where BillTrax's zod schemas sat), but that is a request and not the
contract: :func:`require_fields` and each module's reader still refuse.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
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
    """``response_schema`` is the answer's shape stated on the request.

    It comes from the same ``AnswerField`` tuple the prompt and the reader do,
    by :func:`answer_schema`. An adapter whose provider has no equivalent may
    ignore it: it is a request, not the contract -- a schema the provider
    accepts is still a shape the answer may arrive outside of, and only
    :func:`require_fields` and the module's own checks keep a wrong-shaped
    answer out of a stored row.
    """

    def __call__(
        self, *, model: str, prompt: str, response_schema: Mapping[str, Any] | None = None
    ) -> ModelResponse: ...


@dataclass(frozen=True, slots=True)
class _Shape:
    """One value type, stated once for both halves of the request.

    ``schema`` is what the request carries and ``phrase`` is what the prompt
    says, so neither can be added without the other; ``bound_keys`` are the
    schema keys a reader-enforced bound goes under, and ``bounds_stated`` is
    which end of a bound ``phrase`` actually puts into words -- a bound the
    prompt cannot say is refused when the field is declared, so the request
    never enforces more than it states.
    """

    schema: Mapping[str, Any]
    bound_keys: tuple[str, str]
    bounds_stated: tuple[bool, bool]
    phrase: Callable[[float | None, float | None], str]


#: Every value type a declaration can state. A fourth one cannot be added
#: without saying how the prompt pronounces it, which is the whole point: the
#: words and the schema are one statement, not two that agree today.
_SHAPES: Mapping[str, _Shape] = MappingProxyType(
    {
        "string": _Shape(
            {"type": "string"},
            ("minLength", "maxLength"),
            (True, True),
            lambda lower, upper: f"string, {lower}–{upper} characters",
        ),
        "array of strings": _Shape(
            {"type": "array", "items": {"type": "string"}},
            ("minItems", "maxItems"),
            (False, True),
            lambda lower, upper: f"array of at most {upper} strings",
        ),
        "number": _Shape(
            {"type": "number"},
            ("minimum", "maximum"),
            (True, True),
            lambda lower, upper: f"number from {lower} to {upper}",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class AnswerField:
    """One key the prompt asks for and the reader requires, declared once.

    ``shape`` and ``bounds`` are the type and the range **the reader actually
    enforces**, and everything else is derived from them: ``kind`` is the words
    the prompt sends and ``schema`` is the subschema the request carries, so
    the request cannot promise a shape the reader refuses and the words and
    the schema cannot drift apart. ``choices`` is a sealed vocabulary the
    reader refuses a value outside of, so the schema states it as an ``enum``
    while the prompt states it elsewhere (the classification prompt's label
    block); ``aliases`` are spellings the reader also accepts but the prompt
    does not offer and the schema does not allow -- a one-directional
    tolerance, never a second name the answer may choose between.
    """

    key: str
    shape: str
    describes: str
    bounds: tuple[float | None, float | None] | None = None
    choices: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.shape not in _SHAPES:
            raise ValueError(f"{self.key}: unknown answer shape {self.shape!r}")
        if self.choices and self.shape != "string":
            raise ValueError(f"{self.key}: only a string is drawn from a fixed vocabulary")
        if self.bounds is None:
            return
        if len(self.bounds) != 2:
            raise ValueError(f"{self.key}: bounds is a (lower, upper) pair")
        stated = _SHAPES[self.shape].bounds_stated
        if tuple(value is not None for value in self.bounds) != stated:
            raise ValueError(f"{self.key}: a {self.shape!r} bound the prompt cannot state would go unsaid")

    @property
    def kind(self) -> str:
        """The prompt's words for this value's type and the range the reader enforces."""
        return self.shape if self.bounds is None else _SHAPES[self.shape].phrase(*self.bounds)

    @property
    def schema(self) -> dict[str, Any]:
        """This value's draft 2020-12 subschema: its type, the reader's bounds, its vocabulary."""
        shape = _SHAPES[self.shape]
        schema = copy.deepcopy(dict(shape.schema))
        if self.bounds is not None:
            for value, bound_key in zip(self.bounds, shape.bound_keys, strict=True):
                if value is not None:
                    schema[bound_key] = value
        if self.choices:
            schema["enum"] = list(self.choices)
        return schema

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


def answer_schema(fields: Sequence[AnswerField], *, wrapper: str | None = None) -> dict[str, Any]:
    """The draft 2020-12 schema for the answer object ``fields`` declares.

    What :func:`answer_shape_block` puts into the prompt's words, this puts
    into the request's own constraint: every declared key required, nothing
    else allowed, each value's type and the reader's own bounds. **No alias
    appears here**, exactly as none appears in the prompt: an alias is what the
    reader tolerates on the way in, and offering it on the request would make
    it a second name the answer may choose between. ``wrapper`` nests an array
    of these objects under one key (BillTrax's own ``ClassifySchema`` shape,
    which ``section_classification._rows`` still unwraps); nothing requests
    that form, and it is derived here so the tolerated shape is never restated
    by hand.
    """
    answer: dict[str, Any] = {
        "type": "object",
        "properties": {field.key: field.schema for field in fields},
        "required": [field.key for field in fields],
        "additionalProperties": False,
    }
    if wrapper is None:
        return answer
    return {
        "type": "object",
        "properties": {wrapper: {"type": "array", "items": answer}},
        "required": [wrapper],
        "additionalProperties": False,
    }


def require_fields(data: Mapping[str, Any], fields: Sequence[AnswerField], *, what: str) -> None:
    """Refuse an answer missing any declared key, naming **every** one it left out.

    Named together rather than one per call, because the measured failure was
    missing two keys and a reader that reports only the first makes the second
    look like a new defect after the first is fixed. This stays the contract
    now that the request carries a schema too: the schema is what was asked
    for, this is what is accepted.
    """
    missing = [field.key for field in fields if not field.present_in(data)]
    if missing:
        raise ModelCallError(f"{what} is missing {', '.join(missing)}", details=data)


__all__ = [
    "AnswerField",
    "ModelCall",
    "ModelCallError",
    "ModelResponse",
    "answer_schema",
    "answer_shape_block",
    "require_fields",
]
