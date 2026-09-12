"""Regulations.gov raw schemas and their canonical schema-set digests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import cache
from typing import Any, Final

from rulespec_artifacts import (
    schema_bundle_digest,
)

from spicy_docs.sources.regulations_gov.definitions import (
    _ATTACHMENT_ATTRIBUTE_FIELDS,
    _COMMENT_BOOLEAN_FIELDS,
    _COMMENT_INTEGER_FIELDS,
    _COMMENT_INTEGER_OR_TEXT_FIELDS,
    _DISPLAY_PROPERTY_FIELDS,
    _DOCUMENT_BOOLEAN_FIELDS,
    _DOCUMENT_INTEGER_FIELDS,
    _DOCUMENT_TEXT_ARRAY_FIELDS,
    _LINK_FIELDS,
    _TOPIC_FIELDS,
    COMMENT_ATTRIBUTE_FIELDS,
    COMMENT_COLLECTION,
    COMMENT_SCHEMA_NAME,
    COMMENT_SCHEMA_PATH,
    DOCKET_ATTRIBUTE_FIELDS,
    DOCKET_COLLECTION,
    DOCKET_SCHEMA_NAME,
    DOCKET_SCHEMA_PATH,
    DOCUMENT_ATTRIBUTE_FIELDS,
    DOCUMENT_COLLECTION,
    DOCUMENT_SCHEMA_NAME,
    DOCUMENT_SCHEMA_PATH,
    SCHEMA_VERSION,
)

_NULLABLE_TEXT_SCHEMA: Final = {"type": ["string", "null"]}
_NULLABLE_BOOLEAN_SCHEMA: Final = {"type": ["boolean", "null"]}
_NULLABLE_INTEGER_SCHEMA: Final = {"type": ["integer", "null"]}
_TEXT_ARRAY_SCHEMA: Final = {
    "items": {"type": "string"},
    "type": ["array", "null"],
}
_DISPLAY_PROPERTIES_SCHEMA: Final = {
    "items": {
        "additionalProperties": False,
        "properties": {name: _NULLABLE_TEXT_SCHEMA for name in sorted(_DISPLAY_PROPERTY_FIELDS)},
        "type": "object",
    },
    "type": ["array", "null"],
}
_FILE_FORMATS_SCHEMA: Final = {
    "items": {
        "additionalProperties": False,
        "properties": {
            "fileUrl": {"minLength": 1, "type": "string"},
            "format": _NULLABLE_TEXT_SCHEMA,
            "size": {"type": ["integer", "string", "null"]},
        },
        "required": ["fileUrl"],
        "type": "object",
    },
    "type": ["array", "null"],
}
_LINKS_SCHEMA: Final = {
    "additionalProperties": False,
    "properties": {name: _NULLABLE_TEXT_SCHEMA for name in sorted(_LINK_FIELDS)},
    "type": ["object", "null"],
}
_RELATIONSHIPS_SCHEMA: Final = {
    "additionalProperties": False,
    "properties": {
        "attachments": {
            "additionalProperties": False,
            "properties": {
                "data": {
                    "oneOf": [
                        {"type": "null"},
                        {
                            "additionalProperties": False,
                            "properties": {
                                "id": {"minLength": 1, "type": "string"},
                                "type": {"minLength": 1, "type": "string"},
                            },
                            "required": ["id", "type"],
                            "type": "object",
                        },
                        {
                            "items": {
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"minLength": 1, "type": "string"},
                                    "type": {"minLength": 1, "type": "string"},
                                },
                                "required": ["id", "type"],
                                "type": "object",
                            },
                            "type": "array",
                        },
                    ]
                },
                "links": _LINKS_SCHEMA,
            },
            "type": ["object", "null"],
        }
    },
    "type": ["object", "null"],
}
_ATTACHMENT_ATTRIBUTES_SCHEMA: dict[str, Any] = {
    name: _NULLABLE_TEXT_SCHEMA
    for name in sorted(_ATTACHMENT_ATTRIBUTE_FIELDS - {"authors", "docOrder", "fileFormats"})
}
_ATTACHMENT_ATTRIBUTES_SCHEMA.update(
    {
        "authors": _TEXT_ARRAY_SCHEMA,
        "docOrder": _NULLABLE_INTEGER_SCHEMA,
        "fileFormats": _FILE_FORMATS_SCHEMA,
    }
)
_INCLUDED_SCHEMA: Final = {
    "items": {
        "additionalProperties": False,
        "properties": {
            "attributes": {
                "additionalProperties": False,
                "properties": _ATTACHMENT_ATTRIBUTES_SCHEMA,
                "type": "object",
            },
            "id": {"minLength": 1, "type": "string"},
            "links": _LINKS_SCHEMA,
            "relationships": _RELATIONSHIPS_SCHEMA,
            "type": {"const": "attachments"},
        },
        "required": ["attributes", "id", "type"],
        "type": "object",
    },
    "type": ["array", "null"],
}
_META_SCHEMA: Final = {
    "additionalProperties": False,
    "properties": {
        "hasMore": {"type": ["boolean", "null"]},
        "hasNextPage": {"type": ["boolean", "null"]},
        "numberOfElements": _NULLABLE_INTEGER_SCHEMA,
        "pageNumber": _NULLABLE_INTEGER_SCHEMA,
        "pageSize": _NULLABLE_INTEGER_SCHEMA,
        "totalElements": _NULLABLE_INTEGER_SCHEMA,
        "totalPages": _NULLABLE_INTEGER_SCHEMA,
    },
    "type": ["object", "null"],
}


def _raw_schema(
    *,
    schema_id: str,
    collection: str,
    attributes: Mapping[str, Any],
    required_attributes: Sequence[str],
) -> dict[str, Any]:
    return {
        "$id": schema_id,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "data": {
                "additionalProperties": False,
                "properties": {
                    "attributes": {
                        "additionalProperties": False,
                        "properties": dict(attributes),
                        "required": list(required_attributes),
                        "type": "object",
                    },
                    "id": {"minLength": 1, "type": "string"},
                    "links": _LINKS_SCHEMA,
                    "relationships": _RELATIONSHIPS_SCHEMA,
                    "type": {"const": collection},
                },
                "required": ["attributes", "id", "type"],
                "type": "object",
            },
            "included": _INCLUDED_SCHEMA,
            "meta": _META_SCHEMA,
        },
        "required": ["data"],
        "type": "object",
        "x-spicy-record-order": [
            {
                "fieldPath": "/data/id",
                "nullOrder": "forbidden",
                "tupleComparison": "utf16-code-unit",
                "valueType": "string",
            }
        ],
    }


_DOCUMENT_ATTRIBUTES_SCHEMA: dict[str, Any] = {
    name: _NULLABLE_TEXT_SCHEMA for name in sorted(DOCUMENT_ATTRIBUTE_FIELDS)
}
_DOCUMENT_ATTRIBUTES_SCHEMA.update({name: _NULLABLE_BOOLEAN_SCHEMA for name in _DOCUMENT_BOOLEAN_FIELDS})
_DOCUMENT_ATTRIBUTES_SCHEMA.update({name: _NULLABLE_INTEGER_SCHEMA for name in _DOCUMENT_INTEGER_FIELDS})
_DOCUMENT_ATTRIBUTES_SCHEMA.update({name: _TEXT_ARRAY_SCHEMA for name in _DOCUMENT_TEXT_ARRAY_FIELDS})
_DOCUMENT_ATTRIBUTES_SCHEMA.update(
    {
        "displayProperties": _DISPLAY_PROPERTIES_SCHEMA,
        "fileFormats": _FILE_FORMATS_SCHEMA,
        "topics": {
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "additionalProperties": False,
                        "properties": {name: _NULLABLE_TEXT_SCHEMA for name in sorted(_TOPIC_FIELDS)},
                        "type": "object",
                    },
                ]
            },
            "type": ["array", "null"],
        },
    }
)
_DOCKET_ATTRIBUTES_SCHEMA: dict[str, Any] = {name: _NULLABLE_TEXT_SCHEMA for name in sorted(DOCKET_ATTRIBUTE_FIELDS)}
_DOCKET_ATTRIBUTES_SCHEMA.update(
    {
        "displayProperties": _DISPLAY_PROPERTIES_SCHEMA,
        "keywords": _TEXT_ARRAY_SCHEMA,
    }
)
_COMMENT_ATTRIBUTES_SCHEMA: dict[str, Any] = {name: _NULLABLE_TEXT_SCHEMA for name in sorted(COMMENT_ATTRIBUTE_FIELDS)}
_COMMENT_ATTRIBUTES_SCHEMA.update({name: _NULLABLE_BOOLEAN_SCHEMA for name in _COMMENT_BOOLEAN_FIELDS})
_COMMENT_ATTRIBUTES_SCHEMA.update({name: _NULLABLE_INTEGER_SCHEMA for name in _COMMENT_INTEGER_FIELDS})
_COMMENT_ATTRIBUTES_SCHEMA.update(
    {name: {"type": ["integer", "string", "null"]} for name in _COMMENT_INTEGER_OR_TEXT_FIELDS}
)
_COMMENT_ATTRIBUTES_SCHEMA.update(
    {
        "displayProperties": _DISPLAY_PROPERTIES_SCHEMA,
        "fileFormats": _FILE_FORMATS_SCHEMA,
    }
)

REGULATIONS_GOV_DOCUMENT_SCHEMA: Final = _raw_schema(
    schema_id="urn:spicy-regs:schema:regulations-gov-document-raw:1.0",
    collection=DOCUMENT_COLLECTION,
    attributes=_DOCUMENT_ATTRIBUTES_SCHEMA,
    required_attributes=("agencyId", "postedDate"),
)
REGULATIONS_GOV_DOCKET_SCHEMA: Final = _raw_schema(
    schema_id="urn:spicy-regs:schema:regulations-gov-docket-raw:1.0",
    collection=DOCKET_COLLECTION,
    attributes=_DOCKET_ATTRIBUTES_SCHEMA,
    required_attributes=("agencyId", "modifyDate"),
)
REGULATIONS_GOV_COMMENT_SCHEMA: Final = _raw_schema(
    schema_id="urn:spicy-regs:schema:regulations-gov-comment-raw:1.0",
    collection=COMMENT_COLLECTION,
    attributes=_COMMENT_ATTRIBUTES_SCHEMA,
    required_attributes=("agencyId", "postedDate"),
)


# Schemas are immutable constants. Cache their digests across publication and
# replay rather than recomputing per record; see docs/decisions.md.
@cache
def document_source_schema_digest() -> str:
    return schema_bundle_digest({DOCUMENT_SCHEMA_PATH: REGULATIONS_GOV_DOCUMENT_SCHEMA})


@cache
def docket_source_schema_digest() -> str:
    return schema_bundle_digest({DOCKET_SCHEMA_PATH: REGULATIONS_GOV_DOCKET_SCHEMA})


@cache
def comment_source_schema_digest() -> str:
    return schema_bundle_digest({COMMENT_SCHEMA_PATH: REGULATIONS_GOV_COMMENT_SCHEMA})


def document_source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": document_source_schema_digest(),
        "schemaName": DOCUMENT_SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    }


def docket_source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": docket_source_schema_digest(),
        "schemaName": DOCKET_SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    }


def comment_source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": comment_source_schema_digest(),
        "schemaName": COMMENT_SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    }
