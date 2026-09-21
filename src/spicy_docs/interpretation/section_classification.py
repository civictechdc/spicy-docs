"""Label each bill section with one of five sealed classifications.

Reads parsed bill sections (id, heading, body) as the published section table
holds them and returns one ``SectionClassification`` per section carrying the
label, the model's confidence and the provenance that says how the label was
produced -- model id, prompt version, the hash of the exact prompt sent, the
batch, and when the call was requested and answered -- which the original
stored without. The five labels and their definitions are the sealed
vocabulary, and because the definitions live only in the prompt in the
original they are a table here from which the prompt is generated: one home,
so a label can never drift from the definition the model was given. The
answer's keys, types and ranges are declared once
(``CLASSIFICATION_FIELDS``) and both the prompt and the reader use that
declaration; the same declaration now also states the shape on the request
(``CLASSIFICATION_ANSWER_SCHEMA``), though the reader still refuses, because a
provider may accept a schema and answer around it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from spicy_docs.interpretation.model_call import (
    AnswerField,
    ModelCall,
    ModelCallError,
    ModelResponse,
    answer_schema,
    answer_shape_block,
    require_fields,
)

#: v3 (2026-09-20): the ``sectionId`` field says which part of the bracketed
#: line it wants. Under ``v2`` it asked for "the bracketed id, copied exactly
#: as given below" and the model copied the brackets too -- measured live,
#: twice, zero rows stored. v2 (2026-09-19): the prompt states each row's key,
#: type and range rather than listing the names in a sentence. See
#: ``docs/decisions.md``.
PROMPT_VERSION = "v3"
BATCH_SIZE = 30
BODY_CHARS = 500


@dataclass(frozen=True, slots=True)
class ClassificationLabel:
    """One sealed label and the definition the model is given for it."""

    name: str
    definition: str


CLASSIFICATION_LABELS: tuple[ClassificationLabel, ...] = (
    ClassificationLabel("funding_opportunity", "allocates funds, makes appropriations, authorizes spending"),
    ClassificationLabel("directive", "mandates an action or behavior by an agency or entity"),
    ClassificationLabel("deadline", "sets a due date, reporting requirement, or time limit"),
    ClassificationLabel("restriction", "prohibits or limits an action"),
    ClassificationLabel("other", "doesn't fit the above"),
)
LABEL_NAMES: tuple[str, ...] = tuple(label.name for label in CLASSIFICATION_LABELS)

#: Each answered row's keys, types and ranges, stated once: ``build_prompt``
#: sends them and ``_read_row`` enforces them. ``section_id`` is a spelling the
#: reader accepts and the prompt does not offer -- kept from the ``v1`` reader
#: (``row.get("sectionId", row.get("section_id"))``), where it was tolerance for
#: a model that snake-cases a camelCase key rather than an observed answer. No
#: live answer has used it; it is covered by a test, which is the only thing
#: that keeps an unused tolerance honest.
CLASSIFICATION_FIELDS: tuple[AnswerField, ...] = (
    # v3: `section_block` renders each section as `[<id>] <heading>`, which is
    # BillTrax's own line and stays byte-faithful. What moved is this phrase.
    # "the bracketed id, copied exactly as given below" was this repository's
    # 2026-09-19 wording, and a model that copies exactly what it is shown
    # returns `[introduced-in-house|govinfo|0]` -- measured live on 2026-09-19
    # and again on 2026-09-20, both refused by the batch guard, zero rows
    # either time. The phrase now names the part of the line it wants.
    AnswerField(
        "sectionId",
        "string",
        "the section's id: the text inside the square brackets below, without the brackets",
        aliases=("section_id",),
    ),
    # The vocabulary reaches the prompt through the label block above and the
    # request through the schema's `enum`, both from `CLASSIFICATION_LABELS`.
    # `classifications.ts:21-29` enforced it as `z.enum([...the five...])` on
    # the request; `_read_row` has always enforced it on the way back.
    AnswerField("label", "string", "one of the labels above, spelled exactly", choices=LABEL_NAMES),
    AnswerField("confidence", "number", "how certain the label is", bounds=(0, 1)),
)

CLASSIFY_PROMPT_TEMPLATE = """Classify each of the following bill sections. For each section, assign one label:
{labels}

Answer with a JSON array holding one object per section, each carrying exactly these keys:
{answer_shape}

Sections:
{sections}"""


@dataclass(frozen=True, slots=True)
class ClassifiableSection:
    section_id: str
    body: str
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class SectionClassification:
    """The label plus the provenance a hosted row stores beside it."""

    section_id: str
    label: str
    confidence: float
    model: str
    prompt_version: str
    prompt_hash: str
    batch_index: int
    requested_at: str
    completed_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def label_block() -> str:
    """The prompt's label list, generated from the one label table."""
    return "\n".join(f"- {label.name}: {label.definition}" for label in CLASSIFICATION_LABELS)


def section_block(sections: Sequence[ClassifiableSection]) -> str:
    """One batch's sections, each body truncated to ``BODY_CHARS`` as the original did."""
    return "\n\n---\n\n".join(
        f"[{section.section_id}] {section.heading or '(no heading)'}\n{section.body[:BODY_CHARS]}"
        for section in sections
    )


def build_prompt(sections: Sequence[ClassifiableSection]) -> str:
    return CLASSIFY_PROMPT_TEMPLATE.format(
        labels=label_block(),
        answer_shape=answer_shape_block(CLASSIFICATION_FIELDS),
        sections=section_block(sections),
    )


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


#: A wrapping the reader accepts and the prompt does not ask for. Not a guess
#: about model behaviour: it is the original's own answer shape --
#: ``ClassifySchema`` is ``z.object({ classifications: z.array(...) })``
#: (``classifications.ts:21-29``), so every answer BillTrax read arrived
#: wrapped, while its prompt asked for a bare array. The prompt here asks for
#: the array; the wrapper stays readable, in one direction only, like
#: ``AnswerField.aliases``.
CLASSIFICATIONS_WRAPPER_KEY = "classifications"

#: What the prompt asks for, as a constraint on the request: a bare array of
#: row objects. The wrapper is *not* offered here either --
#: ``answer_schema(CLASSIFICATION_FIELDS, wrapper=CLASSIFICATIONS_WRAPPER_KEY)``
#: derives the tolerated shape from the same declaration for anyone who needs
#: to name it, and nothing sends it.
#:
#: The row's ``sectionId`` is **not** narrowed to the batch's own ids, although
#: ``_read_row`` refuses one outside them. BillTrax enforced only
#: ``z.string()`` there. Leaving it open is what let the 2026-09-20 run *see*
#: what the ``v2`` phrasing provoked -- ids returned with the prompt's brackets
#: still around them -- rather than force a match and store rows from a prompt
#: that was asking for the wrong thing. It stays open for the same reason
#: going forward: the batch guard in ``_read_row`` is the contract, and an
#: ``enum`` on the request would make a badly worded prompt look correct.
CLASSIFICATION_ANSWER_SCHEMA = {"type": "array", "items": answer_schema(CLASSIFICATION_FIELDS)}


def _rows(response: ModelResponse) -> Sequence[object]:
    data = response.data
    if isinstance(data, Mapping):
        data = data.get(CLASSIFICATIONS_WRAPPER_KEY)
    if isinstance(data, str) or not isinstance(data, Sequence):
        raise ModelCallError("classification answer must be a list of rows", details=response.data)
    return data


def _read_row(row: object, allowed: frozenset[str]) -> tuple[str, str, float]:
    if not isinstance(row, Mapping):
        raise ModelCallError("classification row must be a mapping", details=row)
    require_fields(row, CLASSIFICATION_FIELDS, what="classification row")
    id_field, label_field, confidence_field = CLASSIFICATION_FIELDS
    section_id = id_field.value_in(row)
    label = label_field.value_in(row)
    confidence = confidence_field.value_in(row)
    if not isinstance(section_id, str) or section_id not in allowed:
        raise ModelCallError("classification names a section outside its batch", details=row)
    if not isinstance(label, str) or label not in LABEL_NAMES:
        raise ModelCallError("classification label is outside the sealed vocabulary", details=row)
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        raise ModelCallError("classification confidence must be a number from 0 to 1", details=row)
    return section_id, label, float(confidence)


def classify_sections(
    sections: Iterable[ClassifiableSection],
    call: ModelCall,
    *,
    model: str,
    batch_size: int = BATCH_SIZE,
    clock: Callable[[], datetime] | None = None,
) -> tuple[SectionClassification, ...]:
    """Classify sections in batches, returning one labelled row per answered section.

    The model's answer is checked against the batch it was asked about: a row
    naming a section that was not sent, a label outside the five, or a
    confidence outside 0-1 is refused rather than stored, because an answer
    that agrees with itself is what an unchecked answer looks like. Raises
    ``ValueError`` for a non-positive batch size.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    now = clock if clock is not None else _now
    ordered = tuple(sections)
    results: list[SectionClassification] = []
    for batch_index, start in enumerate(range(0, len(ordered), batch_size)):
        batch = ordered[start : start + batch_size]
        allowed = frozenset(section.section_id for section in batch)
        prompt = build_prompt(batch)
        digest = prompt_hash(prompt)
        requested_at = now().isoformat()
        response = call(model=model, prompt=prompt, response_schema=CLASSIFICATION_ANSWER_SCHEMA)
        completed_at = now().isoformat()
        for row in _rows(response):
            section_id, label, confidence = _read_row(row, allowed)
            results.append(
                SectionClassification(
                    section_id=section_id,
                    label=label,
                    confidence=confidence,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    prompt_hash=digest,
                    batch_index=batch_index,
                    requested_at=requested_at,
                    completed_at=completed_at,
                )
            )
    return tuple(results)


__all__ = [
    "BATCH_SIZE",
    "BODY_CHARS",
    "CLASSIFICATIONS_WRAPPER_KEY",
    "CLASSIFICATION_ANSWER_SCHEMA",
    "CLASSIFICATION_FIELDS",
    "CLASSIFICATION_LABELS",
    "CLASSIFY_PROMPT_TEMPLATE",
    "LABEL_NAMES",
    "PROMPT_VERSION",
    "ClassifiableSection",
    "ClassificationLabel",
    "SectionClassification",
    "build_prompt",
    "classify_sections",
    "label_block",
    "prompt_hash",
    "section_block",
]
