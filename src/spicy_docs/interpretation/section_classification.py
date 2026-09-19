"""Label each bill section with one of five sealed classifications.

Publisher fact in: parsed bill sections (id, heading, body) as the published
section table holds them.

Interpretation out: one ``SectionClassification`` per section carrying the
label, the model's confidence, and the provenance that says how the label was
produced -- model id, prompt version, the hash of the exact prompt sent, the
batch it belonged to, and when the call was requested and answered.

The five labels and their definitions are the sealed vocabulary, and the
definitions live **only** in the prompt in the original
(``BillTrax/src/lib/classifications.ts:79-84``), which is why they are a
table here and the prompt is generated from that table: one home, and a label
can never drift from the definition the model was given.

One addition. BillTrax stored ``section_classifications`` with no model and no
prompt version (``migrations/006``), so a stored label could not be attributed
to the prompt that produced it while ``bill_summaries`` next door recorded
both. Every result here carries them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from spicy_docs.interpretation.model_call import ModelCall, ModelCallError, ModelResponse
from spicy_docs.transport.source_acquirer import utc_now

PROMPT_VERSION = "v1"
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

CLASSIFY_PROMPT_TEMPLATE = """Classify each of the following bill sections. For each section, assign one label:
{labels}

Return a JSON array with sectionId, label, and confidence (0-1).

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
    return CLASSIFY_PROMPT_TEMPLATE.format(labels=label_block(), sections=section_block(sections))


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _rows(response: ModelResponse) -> Sequence[object]:
    data = response.data
    if isinstance(data, Mapping):
        data = data.get("classifications")
    if isinstance(data, str) or not isinstance(data, Sequence):
        raise ModelCallError("classification answer must be a list of rows", details=response.data)
    return data


def _read_row(row: object, allowed: frozenset[str]) -> tuple[str, str, float]:
    if not isinstance(row, Mapping):
        raise ModelCallError("classification row must be a mapping", details=row)
    section_id = row.get("sectionId", row.get("section_id"))
    label = row.get("label")
    confidence = row.get("confidence")
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
    clock: Callable[[], datetime] = utc_now,
) -> tuple[SectionClassification, ...]:
    """Classify sections in batches, returning one labelled row per answered section.

    The model's answer is checked against the batch it was asked about: a row
    naming a section that was not sent, a label outside the five, or a
    confidence outside 0-1 is refused rather than stored, because an answer
    that agrees with itself is what an unchecked answer looks like.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    ordered = tuple(sections)
    results: list[SectionClassification] = []
    for batch_index, start in enumerate(range(0, len(ordered), batch_size)):
        batch = ordered[start : start + batch_size]
        allowed = frozenset(section.section_id for section in batch)
        prompt = build_prompt(batch)
        digest = prompt_hash(prompt)
        requested_at = clock().isoformat()
        response = call(model=model, prompt=prompt)
        completed_at = clock().isoformat()
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
