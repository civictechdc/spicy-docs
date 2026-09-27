"""Literal native XML observations for downstream relationship tables.

These shapers do not parse citations, resolve targets or assert legal effect.
The caller supplies the retained input pin and source metadata, and publishes
callback rows only after the existing source scanner completes successfully.
"""

from __future__ import annotations

from dataclasses import asdict

from spicy_docs.schemas.tables import Row, json_column, text


def _xml_observation(
    observation: object,
    *,
    source_record_key: str,
    input_sha256: str,
    occurrence_index: int,
    source_locator: str,
    edition: str | None,
) -> Row:
    if not source_record_key or not input_sha256 or not source_locator:
        raise ValueError("native reference projection requires source identity, input digest and locator")
    if type(occurrence_index) is not int or occurrence_index < 0:
        raise ValueError("occurrence_index must be a nonnegative integer")
    return {
        "source_record_key": source_record_key,
        "input_sha256": input_sha256,
        "occurrence_index": text(occurrence_index),
        "source_locator": source_locator,
        "edition": edition,
        "source_path": observation.element.source_xpath,
        "element_tag": observation.element.tag,
        "attributes_json": json_column(observation.element.attributes),
        "ancestors_json": json_column([asdict(item) for item in observation.ancestors]),
    }


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
    row = _xml_observation(
        observation,
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
    )
    row["href"] = observation.href
    row["observation_kind"] = "native_reference"
    return row


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
    row = _xml_observation(
        observation,
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
    )
    row["text"] = observation.text
    row["observation_kind"] = "source_credit"
    return row


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
        raise ValueError("only qualified AUTH and SOURCE note shapes can be projected")
    row = _xml_observation(
        observation,
        source_record_key=source_record_key,
        input_sha256=input_sha256,
        occurrence_index=occurrence_index,
        source_locator=source_locator,
        edition=edition,
    )
    part = observation.nearest_part
    row.update(
        observation_kind="authority" if kind == "AUTH" else "source_note",
        text=observation.text,
        text_runs_json=json_column(list(observation.text_runs)),
        cfr_title=title,
        cfr_part=None if part is None else part.attributes.get("N"),
    )
    return row
