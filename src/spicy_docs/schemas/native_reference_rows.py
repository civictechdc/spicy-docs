"""The native legal-reference tables: literal U.S. Code and eCFR XML observations, and each complete read of an input.

These shapers do not parse citations, resolve targets or assert legal effect: an observation row leaves them with its
three interpretation columns NULL, and ``interpretation.native_legal_references.interpret_native_references`` fills
them. The caller supplies the retained input pin and source metadata, and publishes callback rows only after the
existing source scanner completes successfully. Both tables spell ``scope_id`` with :func:`native_reference_scope_id`.
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

#: The rule both tables' ``rule_version`` names: the scanners' selected shapes and
#: ``interpretation.native_legal_references``' reading. A change to either that moves a published value moves it.
NATIVE_LEGAL_REFERENCE_RULE = "native-legal-reference/002"

#: The shapes each family's scanner selects, and the ones it knowingly leaves out, in the order a read row lists them.
_READ_SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ecfr": (("AUTH", "SOURCE"), ("PARAUTH", "SECAUTH")),
    "uscode": (("href", "sourceCredit"), ()),
}


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
        "rule_version": "The rule this read ran under, the same as its observation rows'; comparable for equality only.",
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
            "How the reading under rule_version read this observation: `native_section_href`, "
            "`native_statute_href`, `native_public_law_href` or `unsupported_href` for an href, "
            "`partial_text_findings` or `no_qualified_text_findings` for text; it does not claim exhaustive "
            "extraction."
        ),
        "target_candidates_json": (
            "The typed targets the reading found, as a JSON array in reading order, each with the outcome of the "
            "host's lookup in the target tables it selected; several targets in one note stay one row, and an "
            "unsupported href has none."
        ),
        "rule_version": (
            "`native-legal-reference/002`: the scanners' selected shapes and the reading this row was produced "
            "under, comparable for equality only."
        ),
    },
)


def _check_input(
    *, source_record_key: str, source_locator: str, input_sha256: str, edition: str | None, **counts: int
) -> None:
    """Refuse, as :class:`TableContractError`, what a row would publish wrongly: a blank record key or locator, an input
    digest not spelled ``sha256:`` plus 64 lowercase hex, an edition that is neither ``None`` nor a non-empty string,
    and a count or ordinal that is negative or not an int."""
    if not source_record_key or not source_locator:
        raise TableContractError("native reference projection requires a source record key and locator")
    if not isinstance(input_sha256, str) or _SHA256.fullmatch(input_sha256) is None:
        raise TableContractError(f"input_sha256 must be spelled sha256: plus 64 lowercase hex, not {input_sha256!r}")
    if edition is not None and (not isinstance(edition, str) or not edition):
        raise TableContractError("edition must be a non-empty string or None")
    for name, value in counts.items():
        if type(value) is not int or value < 0:
            raise TableContractError(f"{name} must be a nonnegative integer")


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
    """One ``native_legal_references`` row in contract order, checked and keyed, its interpretation columns NULL.

    Refuses every input :func:`_check_input` refuses.
    """
    _check_input(
        source_record_key=source_record_key,
        source_locator=source_locator,
        input_sha256=input_sha256,
        edition=edition,
        occurrence_index=occurrence_index,
    )
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


def shape_native_reference_read(
    *,
    source_family: str,
    source_record_key: str,
    edition: str | None,
    input_sha256: str,
    source_locator: str,
    source_bytes: int,
    occurrence_count: int,
    manifest_sha256: str,
) -> Row:
    """The ``native_legal_reference_reads`` row of one input whose scan completed, zero observations included.

    The family names the selected and unsupported shapes; ``source_bytes`` and ``occurrence_count`` are the input's
    length and the observation rows its scan produced. Refuses an unknown family, a manifest digest not spelled
    ``sha256:``, and every input :func:`_check_input` refuses.
    """
    if source_family not in _READ_SHAPES:
        raise TableContractError(f"no native reference scanner reads the {source_family!r} family")
    _check_input(
        source_record_key=source_record_key,
        source_locator=source_locator,
        input_sha256=input_sha256,
        edition=edition,
        source_bytes=source_bytes,
        occurrence_count=occurrence_count,
    )
    if not isinstance(manifest_sha256, str) or _SHA256.fullmatch(manifest_sha256) is None:
        raise TableContractError(
            f"manifest_sha256 must be spelled sha256: plus 64 lowercase hex, not {manifest_sha256!r}"
        )
    selected, unsupported = _READ_SHAPES[source_family]
    row: Row = {
        "scope_id": native_reference_scope_id(source_family, source_record_key, edition),
        "source_family": source_family,
        "source_record_key": source_record_key,
        "edition": edition,
        "input_sha256": input_sha256,
        "source_locator": source_locator,
        "source_bytes": text(source_bytes),
        "occurrence_count": text(occurrence_count),
        "read_status": "complete_selected_shapes",
        "selected_shapes_json": json_column(list(selected)),
        "unsupported_shapes_json": json_column(list(unsupported)),
        "manifest_sha256": manifest_sha256,
        "rule_version": NATIVE_LEGAL_REFERENCE_RULE,
    }
    NATIVE_LEGAL_REFERENCE_READS.spelled_key(row)
    return NATIVE_LEGAL_REFERENCE_READS.checked(row)


__all__ = [
    "NATIVE_LEGAL_REFERENCES",
    "NATIVE_LEGAL_REFERENCE_READS",
    "NATIVE_LEGAL_REFERENCE_RULE",
    "native_reference_scope_id",
    "shape_ecfr_note",
    "shape_native_reference_read",
    "shape_uscode_reference",
    "shape_uscode_source_credit",
]
