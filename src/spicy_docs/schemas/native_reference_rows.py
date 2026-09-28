"""The native legal-reference tables: literal U.S. Code and eCFR XML observations, and each complete read of an input.

These shapers do not parse citations, resolve targets or assert legal effect. The caller supplies the retained input
pin and source metadata, fills the host's three interpretation columns, and publishes callback rows only after the
existing source scanner completes successfully. ``native_legal_reference_reads`` is shaped by the host; its
``scope_id`` is :func:`native_reference_scope_id`, the one spelling both tables share.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from spicy_docs.schemas.tables import (
    AT_JOINED_KEY,
    VALUE_KEY,
    Reference,
    Row,
    TableContractError,
    digest,
    json_column,
    table_contract,
    text,
)

#: The one digest spelling a published digest column takes (``tables.digest``'s).
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def native_reference_scope_id(source_family: str, source_record_key: str, edition: str | None) -> str:
    """The replacement scope of one input: ``sha256:`` over the compact JSON array ``[family, record key, edition]``.

    The array is encoded with non-ASCII characters kept literal, not :func:`~spicy_docs.schemas.tables.json_column`'s
    escapes: it is a digest's preimage, never a published value, and this is the spelling the host minted every
    published ``scope_id`` with, so a record key or edition outside ASCII keeps the scope it already has.
    """
    return digest(json.dumps([source_family, source_record_key, edition], ensure_ascii=False, separators=(",", ":")))


NATIVE_LEGAL_REFERENCE_READS = table_contract(
    "native_legal_reference_reads",
    grain="One row per input scope: its latest complete read of the selected shapes, including a read that found none.",
    identity=("scope_id",),
    key_spelling=VALUE_KEY,
    version_column=None,
    columns={
        "scope_id": (
            "The scope this read replaced, spelled as `native_reference_scope_id` spells it; a complete read "
            "supersedes the scope's earlier read and every observation row it produced."
        ),
        "source_family": "The scanner family that read the input: `uscode` or `ecfr`.",
        "source_record_key": "The caller's record identity for the input, retained literally.",
        "edition": (
            "The edition or request date the caller's checked capture metadata states, literally; NULL when it "
            "states none, never read from a filename."
        ),
        "input_sha256": "`sha256:` digest of the exact XML bytes this read took.",
        "source_locator": "Where the caller retained the input from, literally; not proof of acquisition time or edition.",
        "source_bytes": "The input's length in bytes, as decimal text.",
        "occurrence_count": "How many observation rows this read produced, as decimal text, zero included.",
        "read_status": (
            "`complete_selected_shapes`: the scanner finished the whole input for the selected shapes, which does "
            "not mean every legal-reference form in it was read."
        ),
        "selected_shapes_json": (
            "The source shapes this read selected, as a JSON array: `AUTH` and `SOURCE` for eCFR, `href` and "
            "`sourceCredit` for the U.S. Code."
        ),
        "unsupported_shapes_json": (
            "The shapes this read knowingly left out, as a JSON array (`PARAUTH` and `SECAUTH` for eCFR); not a "
            "list of every form the scanner cannot read."
        ),
        "manifest_sha256": "`sha256:` digest of the selection manifest that named this input and any target pins.",
        "rule_version": "The host's scanner-and-interpretation rule version, comparable for equality only.",
    },
)

NATIVE_LEGAL_REFERENCES = table_contract(
    "native_legal_references",
    grain=(
        "One scanner observation in one pinned U.S. Code or eCFR XML input: a native href or source credit, or an "
        "AUTH or SOURCE note, with every target read from it nested rather than multiplied."
    ),
    identity=("scope_id", "input_sha256", "occurrence_index"),
    # No component can hold "@": the first two are sha256: digests and the third a decimal ordinal (none of the 881
    # live rows has an empty or "@"-holding one; 2026-09-28).
    key_spelling=AT_JOINED_KEY,
    version_column=None,
    references=(Reference(("scope_id",), "native_legal_reference_reads", ("scope_id",)),),
    columns={
        "scope_id": (
            "The input's replacement scope, `native_reference_scope_id` over source_family, source_record_key and "
            "edition; a complete read replaces every row of its scope, and a successful empty read clears it."
        ),
        "source_family": "The scanner family that read the input: `uscode` or `ecfr`, fixed by the shaper.",
        "source_record_key": "The caller's record identity for the input, retained literally.",
        "edition": (
            "The edition or request date the caller's checked capture metadata states, literally; NULL when it "
            "states none, never read from a filename."
        ),
        "input_sha256": "`sha256:` digest of the exact retained XML bytes the scanner read.",
        "source_locator": "Where the caller retained the input from, literally; not proof of acquisition time or edition.",
        "occurrence_index": (
            "The observation's zero-based position among the input's observations, both kinds counted together in "
            "the order the scanner reported them, as decimal text."
        ),
        "source_path": "The observed element's positional XPath in the input (`/*[1]/*[2]`), never a byte offset.",
        "element_tag": (
            "The observed element's tag, its namespace expanded (`{http://xml.house.gov/schemas/uslm/1.0}ref`) where "
            "the input declares one."
        ),
        "attributes_json": "Every attribute of the observed element, as a JSON object keyed by expanded name.",
        "ancestors_json": (
            "The observed element's ancestors from the root to its parent, each a JSON object of its attributes, "
            "positional XPath and tag."
        ),
        "observation_kind": (
            "`native_reference` or `source_credit` for a U.S. Code observation, `authority` (AUTH) or `source_note` "
            "(SOURCE) for an eCFR note."
        ),
        "href": (
            "The element's href exactly as stated, an empty string when stated empty; NULL when absent, and on "
            "every source credit and note."
        ),
        "text": "The complete decoded text of a source credit or note, whitespace kept; NULL on a native reference.",
        "text_runs_json": (
            "An eCFR note's text split at element boundaries, as a JSON array whose strings join to text; NULL on "
            "U.S. Code rows."
        ),
        "cfr_title": (
            "The CFR title the caller's checked capture metadata states, on an eCFR note; NULL when it states none, "
            "never inferred from a fragment."
        ),
        "cfr_part": (
            "The `N` of the nearest enclosing DIV5 part on an eCFR note; NULL when no part encloses it, and on U.S. "
            "Code rows."
        ),
        "interpretation_status": (
            "The host's reading of this observation under rule_version, such as `native_section_href` or "
            "`unsupported_href` for an href and `partial_text_findings` for text; it does not claim exhaustive "
            "extraction, and is NULL until a host interprets the row."
        ),
        "target_candidates_json": (
            "The host's typed target candidates for this observation and their lookup outcomes, as a JSON array, so "
            "several targets in one note stay one row; NULL until a host interprets the row."
        ),
        "rule_version": (
            "The host's scanner-and-interpretation rule version, comparable for equality only; NULL until a host "
            "interprets the row."
        ),
    },
)


def _observation_row(
    observation: object,
    *,
    source_family: str,
    observation_kind: str,
    source_record_key: str,
    input_sha256: str,
    occurrence_index: int,
    source_locator: str,
    edition: str | None,
    href: str | None = None,
    note_text: str | None = None,
    text_runs: tuple[str, ...] | None = None,
    cfr_title: str | None = None,
    cfr_part: str | None = None,
) -> Row:
    """One ``native_legal_references`` row in contract order, the host's three columns NULL, checked and keyed.

    Refuses, as :class:`TableContractError`, a blank record key or locator, an input digest not spelled ``sha256:``
    plus 64 lowercase hex, a negative or non-int ordinal, and an edition that is neither ``None`` nor a non-empty
    string: each is an input the scope or the member key would publish wrongly.
    """
    if not source_record_key or not source_locator:
        raise TableContractError("native reference projection requires a source record key and locator")
    if not isinstance(input_sha256, str) or _SHA256.fullmatch(input_sha256) is None:
        raise TableContractError(f"input_sha256 must be spelled sha256: plus 64 lowercase hex, not {input_sha256!r}")
    if type(occurrence_index) is not int or occurrence_index < 0:
        raise TableContractError("occurrence_index must be a nonnegative integer")
    if edition is not None and (not isinstance(edition, str) or not edition):
        raise TableContractError("edition must be a non-empty string or None")
    element = observation.element
    row: Row = {
        "scope_id": native_reference_scope_id(source_family, source_record_key, edition),
        "source_family": source_family,
        "source_record_key": source_record_key,
        "edition": edition,
        "input_sha256": input_sha256,
        "source_locator": source_locator,
        "occurrence_index": text(occurrence_index),
        "source_path": element.source_xpath,
        "element_tag": element.tag,
        "attributes_json": json_column(element.attributes),
        "ancestors_json": json_column([asdict(item) for item in observation.ancestors]),
        "observation_kind": observation_kind,
        "href": href,
        "text": note_text,
        "text_runs_json": None if text_runs is None else json_column(list(text_runs)),
        "cfr_title": cfr_title,
        "cfr_part": cfr_part,
        "interpretation_status": None,
        "target_candidates_json": None,
        "rule_version": None,
    }
    NATIVE_LEGAL_REFERENCES.spelled_key(row)
    return NATIVE_LEGAL_REFERENCES.checked(row)


def shape_uscode_reference(
    observation: object,
    *,
    source_record_key: str,
    input_sha256: str,
    occurrence_index: int,
    source_locator: str,
    edition: str | None = None,
) -> Row:
    """Keep every href shape, including empty/absent and unknown namespaces."""
    return _observation_row(
        observation,
        source_family="uscode",
        observation_kind="native_reference",
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
        href=observation.href,
    )


def shape_uscode_source_credit(
    observation: object,
    *,
    source_record_key: str,
    input_sha256: str,
    occurrence_index: int,
    source_locator: str,
    edition: str | None = None,
) -> Row:
    """Keep historical source-credit text separately from native href occurrences."""
    return _observation_row(
        observation,
        source_family="uscode",
        observation_kind="source_credit",
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
        note_text=observation.text,
    )


def shape_ecfr_note(
    observation: object,
    *,
    source_record_key: str,
    input_sha256: str,
    occurrence_index: int,
    source_locator: str,
    edition: str | None = None,
    title: str | None = None,
) -> Row:
    """Keep AUTH and SOURCE roles, literal text and ancestry; infer no title from a fragment.

    title and edition must come from separately checked capture metadata.
    PARAUTH/SECAUTH remain unsupported; a citation parser's partial findings
    belong beside this complete note rather than replacing its source text.
    """
    kind = observation.element.tag.rsplit("}", 1)[-1]
    if kind not in ("AUTH", "SOURCE"):
        raise TableContractError("only qualified AUTH and SOURCE note shapes can be projected")
    part = observation.nearest_part
    return _observation_row(
        observation,
        source_family="ecfr",
        observation_kind="authority" if kind == "AUTH" else "source_note",
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
        note_text=observation.text,
        text_runs=observation.text_runs,
        cfr_title=title,
        cfr_part=None if part is None else part.attributes.get("N"),
    )


__all__ = [
    "NATIVE_LEGAL_REFERENCES",
    "NATIVE_LEGAL_REFERENCE_READS",
    "native_reference_scope_id",
    "shape_ecfr_note",
    "shape_uscode_reference",
    "shape_uscode_source_credit",
]
