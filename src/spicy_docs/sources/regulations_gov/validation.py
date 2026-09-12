"""Validate exact Regulations.gov object fields and nested source structures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rulespec_artifacts import (
    canonical_json_bytes,
)

from spicy_docs.sources.regulations_gov.definitions import (
    _ASCII_ID,
    _ATTACHMENT_ATTRIBUTE_FIELDS,
    _COMMENT_BOOLEAN_FIELDS,
    _COMMENT_INTEGER_FIELDS,
    _COMMENT_INTEGER_OR_TEXT_FIELDS,
    _DISPLAY_PROPERTY_FIELDS,
    _DOCUMENT_BOOLEAN_FIELDS,
    _DOCUMENT_INTEGER_FIELDS,
    _DOCUMENT_TEXT_ARRAY_FIELDS,
    _FILE_FORMAT_FIELDS,
    _INCLUDED_FIELDS,
    _LINK_FIELDS,
    _LINKAGE_FIELDS,
    _META_FIELDS,
    _RELATIONSHIP_FIELDS,
    _RELATIONSHIP_VALUE_FIELDS,
    _TOPIC_FIELDS,
    COMMENT_ATTRIBUTE_FIELDS,
    DOCKET_ATTRIBUTE_FIELDS,
    DOCUMENT_ATTRIBUTE_FIELDS,
    RegulationsGovSourceError,
)


def _closed_mapping(
    value: object,
    *,
    allowed: frozenset[str],
    label: str,
    required: frozenset[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RegulationsGovSourceError(f"{label} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise RegulationsGovSourceError(f"unclassified {label} fields: {sorted(unknown)}")
    if missing:
        raise RegulationsGovSourceError(f"{label} lacks fields: {sorted(missing)}")
    return cast(Mapping[str, Any], value)


def _text_or_null(value: object, label: str) -> None:
    if value is not None and not isinstance(value, str):
        raise RegulationsGovSourceError(f"{label} must be text or null")


def _validate_links(value: object, label: str) -> None:
    if value is None:
        return
    links = _closed_mapping(value, allowed=_LINK_FIELDS, label=label)
    for name, locator in links.items():
        _text_or_null(locator, f"{label}.{name}")


def _validate_file_formats(value: object, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise RegulationsGovSourceError(f"{label} must be an array or null")
    for index, item in enumerate(value):
        row = _closed_mapping(
            item,
            allowed=_FILE_FORMAT_FIELDS,
            label=f"{label}[{index}]",
            required=frozenset({"fileUrl"}),
        )
        locator = row.get("fileUrl")
        if not isinstance(locator, str) or not locator:
            raise RegulationsGovSourceError(f"{label}[{index}].fileUrl is invalid")
        _text_or_null(row.get("format"), f"{label}[{index}].format")
        size = row.get("size")
        if size is not None and (
            isinstance(size, bool)
            or not isinstance(size, (int, str))
            or isinstance(size, int)
            and size < 0
            or isinstance(size, str)
            and not size.isdigit()
        ):
            raise RegulationsGovSourceError(f"{label}[{index}].size is invalid")


def _validate_display_properties(value: object, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise RegulationsGovSourceError(f"{label} must be an array or null")
    for index, item in enumerate(value):
        row = _closed_mapping(
            item,
            allowed=_DISPLAY_PROPERTY_FIELDS,
            label=f"{label}[{index}]",
        )
        for name, field_value in row.items():
            _text_or_null(field_value, f"{label}[{index}].{name}")


def _validate_relationships(value: object, label: str) -> None:
    if value is None:
        return
    relationships = _closed_mapping(
        value,
        allowed=_RELATIONSHIP_FIELDS,
        label=label,
    )
    for name, relationship in relationships.items():
        row = _closed_mapping(
            relationship,
            allowed=_RELATIONSHIP_VALUE_FIELDS,
            label=f"{label}.{name}",
        )
        _validate_links(row.get("links"), f"{label}.{name}.links")
        if "data" in row:
            data = row["data"]
            values = data if isinstance(data, list) else [data]
            for index, linkage in enumerate(values):
                if linkage is None:
                    continue
                item = _closed_mapping(
                    linkage,
                    allowed=_LINKAGE_FIELDS,
                    label=f"{label}.{name}.data[{index}]",
                    required=_LINKAGE_FIELDS,
                )
                for field_name, field_value in item.items():
                    if not isinstance(field_value, str) or not field_value:
                        raise RegulationsGovSourceError(f"{label}.{name}.data[{index}].{field_name} is invalid")


def _validate_included(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise RegulationsGovSourceError("Regulations.gov included must be an array")
    for index, item in enumerate(value):
        row = _closed_mapping(
            item,
            allowed=_INCLUDED_FIELDS,
            label=f"Regulations.gov included[{index}]",
            required=frozenset({"attributes", "id", "type"}),
        )
        identity = row.get("id")
        if not isinstance(identity, str) or _ASCII_ID.fullmatch(identity) is None:
            raise RegulationsGovSourceError("Regulations.gov attachment id is not strict ASCII")
        if row.get("type") != "attachments":
            raise RegulationsGovSourceError("Regulations.gov included type is unsupported")
        attributes = _closed_mapping(
            row.get("attributes"),
            allowed=_ATTACHMENT_ATTRIBUTE_FIELDS,
            label="Regulations.gov attachment attributes",
        )
        for name in _ATTACHMENT_ATTRIBUTE_FIELDS - {
            "authors",
            "docOrder",
            "fileFormats",
        }:
            _text_or_null(attributes.get(name), f"attachment.{name}")
        authors = attributes.get("authors")
        if authors is not None and (
            not isinstance(authors, list) or any(not isinstance(author, str) for author in authors)
        ):
            raise RegulationsGovSourceError("Regulations.gov attachment authors must be a text array or null")
        doc_order = attributes.get("docOrder")
        if doc_order is not None and (isinstance(doc_order, bool) or not isinstance(doc_order, int)):
            raise RegulationsGovSourceError("Regulations.gov attachment docOrder must be an integer or null")
        _validate_file_formats(attributes.get("fileFormats"), "attachment.fileFormats")
        _validate_links(row.get("links"), "attachment.links")
        _validate_relationships(row.get("relationships"), "attachment.relationships")


def _source_data(value: object, *, collection: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    top = _closed_mapping(
        value,
        allowed=frozenset({"data", "included", "meta"}),
        label=f"Regulations.gov {collection} record",
        required=frozenset({"data"}),
    )
    data = _closed_mapping(
        top["data"],
        allowed=frozenset({"attributes", "id", "links", "relationships", "type"}),
        label=f"Regulations.gov {collection} data",
        required=frozenset({"attributes", "id", "type"}),
    )
    identity = data.get("id")
    if not isinstance(identity, str) or _ASCII_ID.fullmatch(identity) is None:
        raise RegulationsGovSourceError(f"Regulations.gov {collection} id must use strict ASCII")
    if data.get("type") != collection:
        raise RegulationsGovSourceError(f"Regulations.gov {collection} type differs")
    _validate_links(data.get("links"), f"Regulations.gov {collection} links")
    _validate_relationships(
        data.get("relationships"),
        f"Regulations.gov {collection} relationships",
    )
    _validate_included(top.get("included"))
    if "meta" in top:
        meta = _closed_mapping(
            top["meta"],
            allowed=_META_FIELDS,
            label="Regulations.gov meta",
        )
        canonical_json_bytes(meta)
    return top, data


def _validate_document_attributes(attributes: Mapping[str, Any]) -> None:
    unknown = set(attributes) - DOCUMENT_ATTRIBUTE_FIELDS
    if unknown:
        raise RegulationsGovSourceError(f"unclassified Regulations.gov document attribute fields: {sorted(unknown)}")
    for name in _DOCUMENT_BOOLEAN_FIELDS:
        value = attributes.get(name)
        if value is not None and not isinstance(value, bool):
            raise RegulationsGovSourceError(f"document attribute {name} must be boolean or null")
    for name in _DOCUMENT_INTEGER_FIELDS:
        value = attributes.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise RegulationsGovSourceError(f"document attribute {name} must be integer or null")
    for name in _DOCUMENT_TEXT_ARRAY_FIELDS:
        value = attributes.get(name)
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise RegulationsGovSourceError(f"document attribute {name} must be a text array or null")
    for name in DOCUMENT_ATTRIBUTE_FIELDS - (
        _DOCUMENT_BOOLEAN_FIELDS
        | _DOCUMENT_INTEGER_FIELDS
        | _DOCUMENT_TEXT_ARRAY_FIELDS
        | {"displayProperties", "fileFormats", "topics"}
    ):
        _text_or_null(attributes.get(name), f"document attribute {name}")
    _validate_display_properties(attributes.get("displayProperties"), "document.displayProperties")
    _validate_file_formats(attributes.get("fileFormats"), "document.fileFormats")
    topics = attributes.get("topics")
    if topics is not None:
        if not isinstance(topics, list):
            raise RegulationsGovSourceError("document topics must be an array or null")
        for index, topic in enumerate(topics):
            if isinstance(topic, str):
                continue
            row = _closed_mapping(
                topic,
                allowed=_TOPIC_FIELDS,
                label=f"document topics[{index}]",
            )
            for name, item in row.items():
                _text_or_null(item, f"document topics[{index}].{name}")


def _validate_docket_attributes(attributes: Mapping[str, Any]) -> None:
    unknown = set(attributes) - DOCKET_ATTRIBUTE_FIELDS
    if unknown:
        raise RegulationsGovSourceError(f"unclassified Regulations.gov docket attribute fields: {sorted(unknown)}")
    for name in DOCKET_ATTRIBUTE_FIELDS - {"displayProperties", "keywords"}:
        _text_or_null(attributes.get(name), f"docket attribute {name}")
    _validate_display_properties(attributes.get("displayProperties"), "docket.displayProperties")
    keywords = attributes.get("keywords")
    if keywords is not None and (not isinstance(keywords, list) or any(not isinstance(item, str) for item in keywords)):
        raise RegulationsGovSourceError("docket keywords must be a text array or null")


def _validate_comment_attributes(attributes: Mapping[str, Any]) -> None:
    unknown = set(attributes) - COMMENT_ATTRIBUTE_FIELDS
    if unknown:
        raise RegulationsGovSourceError(f"unclassified Regulations.gov comment attribute fields: {sorted(unknown)}")
    for name in _COMMENT_BOOLEAN_FIELDS:
        value = attributes.get(name)
        if value is not None and not isinstance(value, bool):
            raise RegulationsGovSourceError(f"comment attribute {name} must be boolean or null")
    for name in _COMMENT_INTEGER_FIELDS:
        value = attributes.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise RegulationsGovSourceError(f"comment attribute {name} must be integer or null")
    for name in _COMMENT_INTEGER_OR_TEXT_FIELDS:
        value = attributes.get(name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, str))
            or isinstance(value, int)
            and value < 0
            or isinstance(value, str)
            and not value.isdigit()
        ):
            raise RegulationsGovSourceError(f"comment attribute {name} must be a non-negative integer, digits, or null")
    for name in COMMENT_ATTRIBUTE_FIELDS - (
        _COMMENT_BOOLEAN_FIELDS
        | _COMMENT_INTEGER_FIELDS
        | _COMMENT_INTEGER_OR_TEXT_FIELDS
        | {"displayProperties", "fileFormats"}
    ):
        _text_or_null(attributes.get(name), f"comment attribute {name}")
    _validate_display_properties(
        attributes.get("displayProperties"),
        "comment.displayProperties",
    )
    _validate_file_formats(attributes.get("fileFormats"), "comment.fileFormats")
