"""Regulations.gov classification, versions, record identity, and renditions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Final, cast

from rulespec_artifacts import (
    FramedSection,
    canonical_json_bytes,
    framed_section_digest,
)

from spicy_docs.reading.media_types import media_type
from spicy_docs.sources.regulations_gov.definitions import (
    _KEY_REFETCH_SUFFIX,
    COMMENT_ATTRIBUTE_FIELDS,
    COMMENT_COLLECTION,
    COMMENT_SCHEMA_NAME,
    COMMENT_SCOPE_ID,
    DOCKET_ATTRIBUTE_FIELDS,
    DOCKET_COLLECTION,
    DOCKET_SCHEMA_NAME,
    DOCKET_SCOPE_ID,
    DOCUMENT_ATTRIBUTE_FIELDS,
    DOCUMENT_COLLECTION,
    DOCUMENT_SCHEMA_NAME,
    DOCUMENT_SCOPE_ID,
    DOCUMENT_TIE_VOLATILE_FIELDS,
    SCHEMA_VERSION,
    RegulationsGovSourceError,
)
from spicy_docs.sources.regulations_gov.validation import (
    _closed_mapping,
    _source_data,
    _validate_comment_attributes,
    _validate_docket_attributes,
    _validate_document_attributes,
)


def classify_document(value: object) -> dict[str, Any]:
    top, data = _source_data(value, collection=DOCUMENT_COLLECTION)
    attributes = _closed_mapping(
        data["attributes"],
        allowed=DOCUMENT_ATTRIBUTE_FIELDS,
        label="Regulations.gov document attributes",
        required=frozenset({"agencyId", "postedDate"}),
    )
    _validate_document_attributes(attributes)
    _optional_record_date(attributes.get("postedDate"), "document postedDate")
    observation_version(top, collection=DOCUMENT_COLLECTION)
    canonical_json_bytes(top)
    return dict(top)


def classify_docket(value: object) -> dict[str, Any]:
    top, data = _source_data(value, collection=DOCKET_COLLECTION)
    attributes = _closed_mapping(
        data["attributes"],
        allowed=DOCKET_ATTRIBUTE_FIELDS,
        label="Regulations.gov docket attributes",
        required=frozenset({"agencyId", "modifyDate"}),
    )
    _validate_docket_attributes(attributes)
    _record_date(attributes.get("modifyDate"), "docket modifyDate")
    observation_version(top, collection=DOCKET_COLLECTION)
    canonical_json_bytes(top)
    return dict(top)


def classify_comment(value: object) -> dict[str, Any]:
    top, data = _source_data(value, collection=COMMENT_COLLECTION)
    attributes = _closed_mapping(
        data["attributes"],
        allowed=COMMENT_ATTRIBUTE_FIELDS,
        label="Regulations.gov comment attributes",
        required=frozenset({"agencyId", "postedDate"}),
    )
    _validate_comment_attributes(attributes)
    _record_date(attributes.get("postedDate"), "comment postedDate")
    comment_observation_version(dict(top))
    canonical_json_bytes(top)
    return dict(top)


def _data_attributes(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], cast(Mapping[str, Any], record["data"])["attributes"])


def source_record_id(record: Mapping[str, Any]) -> str:
    return str(cast(Mapping[str, Any], record["data"])["id"])


def _key_claimed_identity(key: str) -> str:
    """Return the record identity a Mirrulations object key's filename claims.

    The key decides which agency and collection an object is admitted into;
    the body decides what it is. Nothing else compares the two, so this is
    the one place that does: strip the filename's ``.json`` extension and
    any trailing refetch suffix (see :data:`_KEY_REFETCH_SUFFIX`), and the
    caller requires what remains to equal :func:`source_record_id`.
    """
    name = key.rsplit("/", 1)[-1].removesuffix(".json")
    return _KEY_REFETCH_SUFFIX.sub("", name)


def _record_date(value: object, label: str) -> date:
    if not isinstance(value, str) or len(value) < 10:
        raise RegulationsGovSourceError(f"Regulations.gov {label} is invalid")
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError as error:
        raise RegulationsGovSourceError(f"Regulations.gov {label} is invalid") from error
    if parsed.isoformat() != value[:10]:
        raise RegulationsGovSourceError(f"Regulations.gov {label} is not canonical")
    return parsed


def _optional_record_date(value: object, label: str) -> date | None:
    """Return the document's date, or None when postedDate cannot define date scope.

    FMCSA records supply null postedDate; FAA records also supply malformed values.
    Treat both as undatable while preserving the source value. Docket modifyDate
    and comment postedDate still use strict parsing and refuse malformed values.
    """

    if value is None:
        return None
    try:
        return _record_date(value, label)
    except RegulationsGovSourceError:
        return None


# Documents can fall back to postedDate. Null instants remain valid observations.
_OBSERVATION_INSTANTS: Final = {
    COMMENT_COLLECTION: ("comment", ("modifyDate",)),
    DOCKET_COLLECTION: ("docket", ("modifyDate",)),
    DOCUMENT_COLLECTION: ("document", ("modifyDate", "postedDate")),
}


def source_issued_version(record: Mapping[str, Any], *, collection: str) -> str | None:
    """Return the exact source instant used to order observations, or None.

    Comments and dockets use modifyDate. Documents fall back to postedDate when
    modifyDate is null; an unusable postedDate supplies no instant and places the
    document outside date scope. Malformed modifyDate refuses for every collection.
    """

    if collection not in _OBSERVATION_INSTANTS:
        raise RegulationsGovSourceError(f"Regulations.gov {collection!r} is not a source-native collection")
    label, fields = _OBSERVATION_INSTANTS[collection]
    attributes = _data_attributes(record)
    for name in fields:
        value = attributes.get(name)
        if value is None:
            continue
        tolerate_unusable = collection == DOCUMENT_COLLECTION and name == "postedDate"
        if not isinstance(value, str) or not value:
            if tolerate_unusable:
                continue
            raise RegulationsGovSourceError(f"Regulations.gov {label} {name} must be nonempty text or null")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            if tolerate_unusable:
                continue
            raise RegulationsGovSourceError(f"Regulations.gov {label} {name} is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            if tolerate_unusable:
                continue
            raise RegulationsGovSourceError(f"Regulations.gov {label} {name} lacks a UTC offset")
        return value
    return None


def observation_version(record: Mapping[str, Any], *, collection: str) -> str | None:
    """Normalize the exact source instant only for deterministic comparison."""

    value = source_issued_version(record, collection=collection)
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return (
        parsed.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def comment_source_issued_version(record: Mapping[str, Any]) -> str | None:
    """Return the exact source value; null is a valid public observation."""

    return source_issued_version(record, collection=COMMENT_COLLECTION)


def comment_observation_version(record: Mapping[str, Any]) -> str | None:
    """Normalize the exact source instant only for deterministic comparison."""

    return observation_version(record, collection=COMMENT_COLLECTION)


def _source_record(
    record: Mapping[str, Any],
    *,
    schema_digest: str,
    schema_name: str,
    scope_id: str,
) -> dict[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": schema_name,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": scope_id,
        "sourceRecordId": source_record_id(record),
    }


def document_source_record(
    record: Mapping[str, Any],
    *,
    schema_digest: str,
) -> dict[str, Any]:
    return _source_record(
        record,
        schema_digest=schema_digest,
        schema_name=DOCUMENT_SCHEMA_NAME,
        scope_id=DOCUMENT_SCOPE_ID,
    )


def docket_source_record(
    record: Mapping[str, Any],
    *,
    schema_digest: str,
) -> dict[str, Any]:
    return _source_record(
        record,
        schema_digest=schema_digest,
        schema_name=DOCKET_SCHEMA_NAME,
        scope_id=DOCKET_SCOPE_ID,
    )


def comment_source_record(
    record: Mapping[str, Any],
    *,
    schema_digest: str,
) -> dict[str, Any]:
    return _source_record(
        record,
        schema_digest=schema_digest,
        schema_name=COMMENT_SCHEMA_NAME,
        scope_id=COMMENT_SCOPE_ID,
    )


def _rendition(
    *,
    source_record_id_value: str,
    source_field: str,
    rendition_id: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    locator = value.get("fileUrl")
    if not isinstance(locator, str) or not locator:
        raise RegulationsGovSourceError(f"Regulations.gov {source_field} lacks fileUrl")
    size = value.get("size")
    expected_size = int(size) if isinstance(size, str) and size.isdigit() else size
    if expected_size is not None and (
        isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0
    ):
        raise RegulationsGovSourceError(f"Regulations.gov {source_field} size is invalid")
    return {
        "expectedByteSize": expected_size,
        "expectedSha256": None,
        "locator": locator,
        "mediaType": media_type(value.get("format"), locator),
        "renditionId": rendition_id,
        "sourceField": source_field,
        "sourceRecordId": source_record_id_value,
    }


def _rendition_rows(
    record: Mapping[str, Any],
    *,
    direct_prefix: str,
) -> tuple[dict[str, Any], ...]:
    identity = source_record_id(record)
    rows: list[dict[str, Any]] = []
    formats = _data_attributes(record).get("fileFormats") or []
    for index, value in enumerate(cast(Sequence[Mapping[str, Any]], formats)):
        rows.append(
            _rendition(
                source_record_id_value=identity,
                source_field=f"data.attributes.fileFormats[{index}]",
                rendition_id=f"{direct_prefix}-{index:04d}",
                value=value,
            )
        )
    for included_index, included in enumerate(cast(Sequence[Mapping[str, Any]], record.get("included") or [])):
        attributes = cast(Mapping[str, Any], included["attributes"])
        for format_index, value in enumerate(cast(Sequence[Mapping[str, Any]], attributes.get("fileFormats") or [])):
            rows.append(
                _rendition(
                    source_record_id_value=identity,
                    source_field=(f"included[{included_index}].attributes.fileFormats[{format_index}]"),
                    rendition_id=f"attachment-{included_index:04d}-{format_index:04d}",
                    value=value,
                )
            )
    return tuple(rows)


def document_rendition_rows(record: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return _rendition_rows(record, direct_prefix="document")


def comment_rendition_rows(record: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return _rendition_rows(record, direct_prefix="comment")


def docket_rendition_rows(record: Mapping[str, Any]) -> tuple[()]:
    del record
    return ()


def document_source_record_digest(record: Mapping[str, Any]) -> str:
    return framed_section_digest(
        "spicyregs-regulations-gov-document-record/1",
        (FramedSection("record", 1, (dict(record),)),),
    )


def document_tie_comparison_digest(record: Mapping[str, Any]) -> str:
    """Second, narrower digest used only to judge same-instant ties.

    Equal to :func:`document_source_record_digest` except
    ``DOCUMENT_TIE_VOLATILE_FIELDS`` are dropped from ``data.attributes``
    first, so two mirror objects for one document version that differ only
    in those read-time-derived fields compare equal. Never published and
    never stored: this does not change what ``document_source_record_digest``
    covers, which stays a sealed identity over the exact record.
    """
    data = dict(record["data"])
    data["attributes"] = {
        key: value for key, value in dict(data["attributes"]).items() if key not in DOCUMENT_TIE_VOLATILE_FIELDS
    }
    stripped = dict(record)
    stripped["data"] = data
    return document_source_record_digest(stripped)


def docket_source_record_digest(record: Mapping[str, Any]) -> str:
    return framed_section_digest(
        "spicyregs-regulations-gov-docket-record/1",
        (FramedSection("record", 1, (dict(record),)),),
    )


def comment_source_record_digest(record: Mapping[str, Any]) -> str:
    return framed_section_digest(
        "spicyregs-regulations-gov-comment-record/1",
        (FramedSection("record", 1, (dict(record),)),),
    )
