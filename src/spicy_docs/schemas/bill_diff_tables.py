"""The three tables one version-pair comparison fills: ``section_diffs``, its ``section_diff_items`` and its
``financial_changes``, shaped from ``interpretation.section_diff`` findings.

The engine name, version and pinned revision stand in for a rule name, and ``text_diff_json`` is published byte-capped
with ``text_diff_truncated`` because the diff stopped being recomputable from published rows once ``bill_versions``
dropped full text.  ``financial_changes`` rows exist only where a section's amounts actually changed and the caller
asked for pairs, and ``pairing_claim`` states that the two figures share a word-alignment position -- never that they
are the same account.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import (
    Row,
    digest,
    flag,
    joined,
    json_column,
    table_contract,
    text,
)

#: Default byte cap on ``section_diff_items.text_diff_json``.  A word diff of a
#: rewritten appropriations title is unbounded; the published column is not.
TEXT_DIFF_CAP_BYTES = 64 * 1024

#: The one pairing rule the family builder applies when choosing version pairs:
#: neighbours in ``sources.congress.bill_versions.printing_order``, which places a
#: dateless enrolled printing by its stage.  Its predecessor, ``consecutive_by_date``,
#: sorted the empty date first and diffed an enrolled bill into its introduced text.
CONSECUTIVE_PAIR_RULE = "consecutive_by_date_then_stage"

#: What a ``financial_changes`` row claims, and what it does not.
WORD_ALIGNMENT_CLAIM = "word_alignment"

_DIFF_KEY = {
    "bill_id": "The bill both printings belong to.",
    "from_version_code": "The earlier printing's version code.",
    "from_source": "Which acquisition path supplied the earlier printing.",
    "to_version_code": "The later printing's version code.",
    "to_source": "Which acquisition path supplied the later printing.",
}

SECTION_DIFFS = table_contract(
    "section_diffs",
    grain="One row per compared pair of consecutive printings of one bill.",
    identity=("bill_id", "from_version_code", "from_source", "to_version_code", "to_source"),
    version_column="to_version_date",
    columns={
        **_DIFF_KEY,
        "from_version_date": "The earlier printing's publisher date.",
        "to_version_date": "The later printing's publisher date; the merge prefers the larger value.",
        "pair_type": "Which comparison strategy this pair called for: xml-xml, pdf-pdf or pdf-xml.",
        "pair_rule": "Why these two printings were compared: neighbours by date, then by stage, never every pair.",
        "added_count": "Sections present only in the later printing.",
        "removed_count": "Sections present only in the earlier printing.",
        "modified_count": "Sections present in both whose body text differs.",
        "unchanged_count": "Sections present in both whose body text is identical.",
        "moved_count": "Sections the move round paired at a different path.",
        "item_count": "How many section_diff_items rows this diff produced.",
        "engine_name": "Which diff engine produced this row; the stand-in for a rule name.",
        "engine_version": "The engine's declared version.",
        "engine_revision": "The exact pinned commit the engine was installed from.",
        "computed_at": "When the comparison ran, from the caller's injected clock.",
    },
)

SECTION_DIFF_ITEMS = table_contract(
    "section_diff_items",
    grain="One row per settled correspondence in one version-pair comparison.",
    identity=("bill_id", "from_version_code", "from_source", "to_version_code", "to_source", "seq"),
    version_column=None,
    columns={
        **_DIFF_KEY,
        "seq": "Position in the engine's own stable ordering of settled correspondences.",
        "op": "What changed: added, removed, modified, unchanged or moved.",
        "similarity": "The word-overlap signal the assignment round recorded, rounded to four places.",
        "moved": "True when the engine classified this correspondence as a move.",
        "pairing_rule": "Which assignment round selected this correspondence: path-round, move-round or unpaired.",
        "evidence_json": "Every named signal the round recorded, as the engine spelled them.",
        "match_path": "The normalized cross-version key, unit-separator joined.",
        "match_path_json": "The same path as a JSON array.",
        "display_path_old_json": "The earlier printing's display path, as a JSON array.",
        "display_path_new_json": "The later printing's display path, as a JSON array.",
        "section_number": "The section's displayed number.",
        "heading": "The section heading, preferring the later printing's.",
        "from_element_id": "The earlier printing's own element id, which resolves this side to a bill_sections row.",
        "to_element_id": "The later printing's own element id.",
        "from_text_sha256": "Digest of the earlier body text, so an unchanged side is recognisable without it.",
        "to_text_sha256": "Digest of the later body text.",
        "from_text_chars": "Character length of the earlier body text.",
        "to_text_chars": "Character length of the later body text.",
        "text_diff_json": "The engine's word-level diff as a JSON array, capped at the published byte limit.",
        "text_diff_truncated": "True when the word diff did not fit the cap and entries were dropped from the end.",
        "financial_from_amounts_json": "Every dollar figure the earlier body states, as a JSON array.",
        "financial_to_amounts_json": "Every dollar figure the later body states, as a JSON array.",
        "financial_amounts_changed": "True when the two multisets of figures differ; needs no account model to be true.",
        "financial_has_amendment_annotations": "True when the section carries amendment annotations around its figures.",
    },
)

FINANCIAL_CHANGES = table_contract(
    "financial_changes",
    grain="One row per aligned pair of dollar figures in a section whose amounts changed.",
    identity=("bill_id", "from_version_code", "from_source", "to_version_code", "to_source", "seq", "amount_index"),
    version_column=None,
    columns={
        **_DIFF_KEY,
        "seq": "The section_diff_items row this pairing came from.",
        "amount_index": "Position of this pairing within that section's word alignment.",
        "label": "The section heading, which BillTrax left empty in every row it wrote.",
        "from_amount": "The figure on the earlier side, or NULL where the alignment found none.",
        "to_amount": "The figure on the later side, or NULL where the alignment found none.",
        "delta": "to_amount minus from_amount, or NULL when either side is absent.",
        "pairing_claim": (
            "What this row claims: that the two figures sit at the same place in a word-level alignment. "
            "It does not claim they are the same account."
        ),
    },
)


def _diff_key(bill_id: str, from_ref: object, to_ref: object) -> Row:
    return {
        "bill_id": bill_id,
        "from_version_code": text(from_ref.version_code),
        "from_source": text(from_ref.source),
        "to_version_code": text(to_ref.version_code),
        "to_source": text(to_ref.source),
    }


def _capped_json(entries: tuple[str, ...] | None, cap: int) -> tuple[str | None, bool | None]:
    """Serialize a word diff, keeping the longest prefix that fits ``cap`` bytes.

    A rewritten appropriations title produces tens of thousands of diff tokens,
    so the prefix is found by bisection -- the encoding grows monotonically with
    the prefix length -- rather than by dropping one entry at a time, which
    would be O(n^2) in the number dropped.
    """
    if entries is None:
        return None, None
    encoded = json_column(list(entries))
    if len(encoded.encode("utf-8")) <= cap:
        return encoded, False
    low, high = 0, len(entries)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json_column(list(entries[:middle])).encode("utf-8")) <= cap:
            low = middle
        else:
            high = middle - 1
    return json_column(list(entries[:low])), True


def shape_section_diff(
    diff: object,
    *,
    bill_id: str,
    from_ref: object,
    to_ref: object,
    from_version_date: str | None,
    to_version_date: str | None,
    pair_type: str,
    engine: object,
    computed_at: str,
) -> Row:
    """One ``section_diffs`` row for one compared pair.

    ``from_ref`` and ``to_ref`` are read for ``version_code`` and ``source``
    only -- an ``interpretation.bill_family.BillVersionCapture`` carries both.
    The design named these ``VersionRef``; that record's ``version_id`` has to
    be unique for ``pair_type`` to index it, and a version code is not unique
    across sources, so the two fields are read separately here.
    """
    summary = diff.summary
    return {
        **_diff_key(bill_id, from_ref, to_ref),
        "from_version_date": text(from_version_date),
        "to_version_date": text(to_version_date),
        "pair_type": text(pair_type),
        "pair_rule": CONSECUTIVE_PAIR_RULE,
        "added_count": text(summary.get("added", 0)),
        "removed_count": text(summary.get("removed", 0)),
        "modified_count": text(summary.get("modified", 0)),
        "unchanged_count": text(summary.get("unchanged", 0)),
        "moved_count": text(summary.get("moved", 0)),
        "item_count": text(len(diff.items)),
        "engine_name": text(engine.name),
        "engine_version": text(engine.version),
        "engine_revision": text(engine.revision),
        "computed_at": text(computed_at),
    }


def shape_section_diff_item(
    item: object,
    *,
    bill_id: str,
    from_ref: object,
    to_ref: object,
    text_diff_cap: int = TEXT_DIFF_CAP_BYTES,
) -> Row:
    """One ``section_diff_items`` row, carrying the provenance upstream computed."""
    financial = item.financial
    diff_json, truncated = _capped_json(item.text_diff, text_diff_cap)
    return {
        **_diff_key(bill_id, from_ref, to_ref),
        "seq": text(item.seq),
        "op": text(item.op),
        "similarity": text(item.similarity),
        "moved": flag(item.moved),
        "pairing_rule": text(item.pairing_rule),
        "evidence_json": json_column(dict(item.evidence)),
        "match_path": joined(item.match_path),
        "match_path_json": json_column(list(item.match_path)),
        "display_path_old_json": (None if item.display_path_old is None else json_column(list(item.display_path_old))),
        "display_path_new_json": (None if item.display_path_new is None else json_column(list(item.display_path_new))),
        "section_number": text(item.section_number),
        "heading": text(item.heading),
        "from_element_id": text(item.from_element_id) or None,
        "to_element_id": text(item.to_element_id) or None,
        "from_text_sha256": digest(item.from_text),
        "to_text_sha256": digest(item.to_text),
        "from_text_chars": text(None if item.from_text is None else len(item.from_text)),
        "to_text_chars": text(None if item.to_text is None else len(item.to_text)),
        "text_diff_json": diff_json,
        "text_diff_truncated": flag(truncated),
        "financial_from_amounts_json": (None if financial is None else json_column(list(financial.from_amounts))),
        "financial_to_amounts_json": None if financial is None else json_column(list(financial.to_amounts)),
        "financial_amounts_changed": flag(None if financial is None else financial.amounts_changed),
        "financial_has_amendment_annotations": (
            flag(None if financial is None else financial.has_amendment_annotations)
        ),
    }


def shape_financial_change(pair: object, *, item_key: Row, amount_index: int) -> Row:
    """One ``financial_changes`` row.

    ``item_key`` is the shaped ``section_diff_items`` row this pairing came
    from; its identity columns are copied rather than rebuilt, so parent and
    child cannot disagree about which section they describe.
    """
    return {
        "bill_id": item_key["bill_id"],
        "from_version_code": item_key["from_version_code"],
        "from_source": item_key["from_source"],
        "to_version_code": item_key["to_version_code"],
        "to_source": item_key["to_source"],
        "seq": item_key["seq"],
        "amount_index": text(amount_index),
        "label": text(pair.label),
        "from_amount": text(pair.from_amount),
        "to_amount": text(pair.to_amount),
        "delta": text(pair.delta),
        "pairing_claim": WORD_ALIGNMENT_CLAIM,
    }


__all__ = [
    "CONSECUTIVE_PAIR_RULE",
    "FINANCIAL_CHANGES",
    "SECTION_DIFFS",
    "SECTION_DIFF_ITEMS",
    "TEXT_DIFF_CAP_BYTES",
    "WORD_ALIGNMENT_CLAIM",
    "shape_financial_change",
    "shape_section_diff",
    "shape_section_diff_item",
]
