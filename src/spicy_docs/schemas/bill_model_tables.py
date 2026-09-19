"""The two model-backed tables, and the third that waits on a generator to port.

Both registered tables here carry a model answer *and* the provenance it was
produced under, because the ``interpretation`` package already returns it: model
id, prompt version, the hash of the exact prompt sent, the batch, and when the
call was requested and answered.  This layer flattens findings; it does not
invent provenance.

Both identities gained ``source`` (C5).  ``bill_versions`` is keyed
``(bill_id, version_code, source)`` -- the key BillTrax itself widened in
migration 020 -- and a child cannot say which of an XML row and its PDF twin it
classified without it.

``section_classifications`` carries ``vocabulary_hash`` so a change to the five
sealed labels is visible in the data rather than only in the code that produced
it.  ``bill_summaries`` carries ``frame``, because the framing sentence is what
makes the summary reproducible from the row: two summaries of the same text
under different frames are different answers, not drift.  ``diff_summaries``
carries no frame, because its prompt has none: the original sends only the diff
text, and the port keeps that sealed.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import (
    Row,
    json_column,
    table_contract,
    text,
)
from spicy_docs.schemas.tables import bill_id as bill_key

_SECTION_KEY_COLUMNS = ("bill_id", "version_code", "source", "match_path", "body_index")

SECTION_CLASSIFICATIONS = table_contract(
    "section_classifications",
    grain="One row per label a model assigned to one section of one printing.",
    identity=("bill_id", "version_code", "source", "match_path", "body_index", "label"),
    version_column="completed_at",
    columns={
        "bill_id": "The bill whose section was classified.",
        "version_code": "The printing whose section was classified.",
        "source": "Which acquisition path supplied that printing; without it an XML row and its PDF twin collide.",
        "match_path": "The section's normalized cross-version key, unit-separator joined.",
        "body_index": "Which body element the section came from.",
        "label": "One of the five sealed classification labels.",
        "confidence": "The model's own confidence, checked to be between 0 and 1 before it was stored.",
        "model": "The model id the call was made against.",
        "prompt_version": "The prompt version the label was produced under.",
        "prompt_hash": "Digest of the exact prompt sent, so a prompt edit is visible per row.",
        "batch_index": "Which batch of the run this section belonged to.",
        "requested_at": "When the call was made.",
        "completed_at": "When the answer came back; the merge prefers the larger value.",
        "vocabulary_hash": "Digest over the sealed label table, so a vocabulary change is visible in the data.",
    },
)

BILL_SUMMARIES = table_contract(
    "bill_summaries",
    grain="One row per plain-language summary of one printing of a bill.",
    identity=("bill_id", "version_code", "source"),
    version_column="completed_at",
    columns={
        "bill_id": "The bill this summary describes.",
        "version_code": "The printing this summary was written from.",
        "source": "Which acquisition path supplied that printing.",
        "summary": "The plain-language paragraph, length-checked before it was stored.",
        "audience": "The short phrase naming the most-affected audience.",
        "top_provisions_json": "Up to three notable provisions, as a JSON array in the model's order.",
        "model": "The model id the call was made against.",
        "prompt_version": "The prompt version this summary was produced under.",
        "content_hash": "Digest of the version text the summary was written from; what a cached summary is keyed on.",
        "input_tokens": "Input tokens the provider reported, where it reported any.",
        "output_tokens": "Output tokens the provider reported.",
        "requested_at": "When the call was made.",
        "completed_at": "When the answer came back; the merge prefers the larger value.",
        "money_bill_kind": "The money-bill kind that selected the framing sentence.",
        "frame": "The sealed framing sentence the prompt carried; without it the summary is not reproducible.",
    },
)

#: Design change C10 made this table conditional on BillTrax having a
#: diff-summary generator to port.  It does
#: (``src/app/api/bills/[id]/summarize/route.ts``: a sealed five-field answer --
#: headline, key changes, sections added, sections removed, dollar changes --
#: cached in its own ``diff_summaries`` table), and
#: ``interpretation.bill_summaries.summarize_diff`` is the port, so the table
#: ships.  Its identity is ``section_diffs``'s key: a diff summary describes
#: exactly one compared pair.
DIFF_SUMMARIES = table_contract(
    "diff_summaries",
    grain="One row per model-written summary of the change between two printings of a bill.",
    identity=("bill_id", "from_version_code", "from_source", "to_version_code", "to_source"),
    version_column="completed_at",
    columns={
        "bill_id": "The bill both printings belong to.",
        "from_version_code": "The earlier printing's version code.",
        "from_source": "Which acquisition path supplied the earlier printing.",
        "to_version_code": "The later printing's version code.",
        "to_source": "Which acquisition path supplied the later printing.",
        "headline": "One sentence naming the most important change.",
        "key_changes_json": (
            "The bullet points describing the most significant changes, as a JSON array in the model's order. "
            "The prompt asks for at most five and nothing enforces it -- unlike bill_summaries.top_provisions_json, "
            "whose cap is checked before the row is stored -- because the ported answer schema states no maximum "
            "either, so a longer list is the model's answer and not a defect to hide."
        ),
        "sections_added_json": "Section headings that were added, as a JSON array.",
        "sections_removed_json": "Section headings that were removed, as a JSON array.",
        "dollar_changes_json": "Notable dollar-amount changes in prose, as a JSON array.",
        "model": "The model id the call was made against.",
        "prompt_version": "The prompt version this summary was produced under.",
        "content_hash": "Digest of the diff text the summary was written from.",
        "input_tokens": "Input tokens the provider reported.",
        "output_tokens": "Output tokens the provider reported.",
        "requested_at": "When the call was made.",
        "completed_at": "When the answer came back; the merge prefers the larger value.",
    },
)


def shape_section_classification(result: object, *, section_key: Row, vocabulary_hash: str) -> Row:
    """One ``section_classifications`` row.

    ``section_key`` is the shaped ``bill_sections`` row this label belongs to;
    its identity columns are copied rather than rebuilt from the model's own
    ``section_id``, so a label can never be attached to a section the row does
    not name.  ``vocabulary_hash`` is computed by the caller, because the sealed
    label table lives in ``interpretation.section_classification``.
    """
    return {
        **{column: section_key[column] for column in _SECTION_KEY_COLUMNS},
        "label": text(result.label),
        "confidence": text(result.confidence),
        "model": text(result.model),
        "prompt_version": text(result.prompt_version),
        "prompt_hash": text(result.prompt_hash),
        "batch_index": text(result.batch_index),
        "requested_at": text(result.requested_at),
        "completed_at": text(result.completed_at),
        "vocabulary_hash": text(vocabulary_hash),
    }


def shape_bill_summary(
    result: object,
    *,
    source: str,
    money_bill_kind: str | None,
    frame: str,
) -> Row:
    """One ``bill_summaries`` row.

    ``frame`` is passed in rather than derived: ``MONEY_BILL_FRAMES`` lives in
    ``interpretation.bill_summaries`` and this module does not import it.  The
    design's signature omitted it; the column cannot be filled without it.
    """
    return {
        "bill_id": bill_key(result.identity),
        "version_code": text(result.version_id),
        "source": text(source),
        "summary": text(result.summary),
        "audience": text(result.audience),
        "top_provisions_json": json_column(list(result.top_provisions)),
        "model": text(result.model),
        "prompt_version": text(result.prompt_version),
        "content_hash": text(result.content_hash),
        "input_tokens": text(result.input_tokens),
        "output_tokens": text(result.output_tokens),
        "requested_at": text(result.requested_at),
        "completed_at": text(result.completed_at),
        "money_bill_kind": text(money_bill_kind),
        "frame": text(frame),
    }


def shape_diff_summary(result: object, *, from_source: str, to_source: str) -> Row:
    """One ``diff_summaries`` row from one ``DiffSummaryResult``.

    The result names both version codes itself; only the two sources come from
    the caller, because a version code is not unique across acquisition paths
    and ``section_diffs`` keys on both.
    """
    return {
        "bill_id": bill_key(result.identity),
        "from_version_code": text(result.from_version_id),
        "from_source": text(from_source),
        "to_version_code": text(result.to_version_id),
        "to_source": text(to_source),
        "headline": text(result.headline),
        "key_changes_json": json_column(list(result.key_changes)),
        "sections_added_json": json_column(list(result.sections_added)),
        "sections_removed_json": json_column(list(result.sections_removed)),
        "dollar_changes_json": json_column(list(result.dollar_changes)),
        "model": text(result.model),
        "prompt_version": text(result.prompt_version),
        "content_hash": text(result.content_hash),
        "input_tokens": text(result.input_tokens),
        "output_tokens": text(result.output_tokens),
        "requested_at": text(result.requested_at),
        "completed_at": text(result.completed_at),
    }


__all__ = [
    "BILL_SUMMARIES",
    "DIFF_SUMMARIES",
    "SECTION_CLASSIFICATIONS",
    "shape_bill_summary",
    "shape_diff_summary",
    "shape_section_classification",
]
