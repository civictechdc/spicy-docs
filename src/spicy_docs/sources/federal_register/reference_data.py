"""Literal Federal Register agency, OpenAPI enum and type-facet observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from spicy_docs.sources.json_input import load_bounded_json

FR_AGENCIES_URL = "https://www.federalregister.gov/api/v1/agencies"
FR_DOCUMENTATION_URL = "https://www.federalregister.gov/api/v1/documentation.json"
FR_TYPE_FACETS_URL = "https://www.federalregister.gov/api/v1/documents/facets/type"
DEFAULT_MAX_BYTES = 16 * 1024 * 1024


class FederalRegisterReferenceError(ValueError):
    """The input cannot be read as the requested publisher source shape."""


def _read(payload: bytes, max_bytes: int, max_nodes: int, max_depth: int) -> Any:
    return load_bounded_json(
        payload,
        source="Federal Register reference data",
        error_type=FederalRegisterReferenceError,
        number_policy="finite-float",
        max_bytes=max_bytes,
        max_nodes=max_nodes,
        max_depth=max_depth,
    )


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FederalRegisterReferenceError(f"{path} must be an object")
    return value


def _field(row: dict[str, Any], name: str, kind: type, path: str, *, nullable: bool = False) -> Any:
    if name not in row:
        raise FederalRegisterReferenceError(f"{path}.{name} is missing")
    value = row[name]
    if not ((nullable and value is None) or type(value) is kind):
        raise FederalRegisterReferenceError(f"{path}.{name} must be {kind.__name__}{' or null' if nullable else ''}")
    return value


@dataclass(frozen=True, slots=True)
class FrAgencyObservation:
    agency_id: int
    slug: str
    name: str
    short_name: str | None
    description: str | None
    url: str
    json_url: str
    agency_url: str | None
    parent_id: int | None
    child_ids: tuple[int, ...]
    child_slugs: tuple[str, ...]
    raw: dict[str, Any]
    source_path: str


@dataclass(frozen=True, slots=True)
class FrAgencies:
    records: tuple[FrAgencyObservation, ...]
    raw: list[Any]
    input_sha256: str
    input_bytes: int


def read_fr_agencies(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_nodes: int = 500_000,
    max_depth: int = 64,
) -> FrAgencies:
    """Preserve ordered agency facts, unknown fields and unresolved relationships.

    Typed fields require the publisher's scalar/container types. Empty strings,
    duplicate IDs/slugs, arbitrary URL strings and missing graph targets remain
    observations. The caller decides whether a roster is usable or complete.
    """
    raw = _read(payload, max_bytes, max_nodes, max_depth)
    if not isinstance(raw, list):
        raise FederalRegisterReferenceError("FR agencies root must be an array")
    records = []
    for index, value in enumerate(raw):
        path = f"$[{index}]"
        row = _object(value, path)
        child_ids = _field(row, "child_ids", list, path)
        child_slugs = _field(row, "child_slugs", list, path)
        if any(type(item) is not int for item in child_ids):
            raise FederalRegisterReferenceError(f"{path}.child_ids must contain integers")
        if any(not isinstance(item, str) for item in child_slugs):
            raise FederalRegisterReferenceError(f"{path}.child_slugs must contain text")
        records.append(
            FrAgencyObservation(
                agency_id=_field(row, "id", int, path),
                slug=_field(row, "slug", str, path),
                name=_field(row, "name", str, path),
                short_name=_field(row, "short_name", str, path, nullable=True),
                description=_field(row, "description", str, path, nullable=True),
                url=_field(row, "url", str, path),
                json_url=_field(row, "json_url", str, path),
                agency_url=_field(row, "agency_url", str, path, nullable=True),
                parent_id=_field(row, "parent_id", int, path, nullable=True),
                child_ids=tuple(child_ids),
                child_slugs=tuple(child_slugs),
                raw=row,
                source_path=path,
            )
        )
    return FrAgencies(tuple(records), raw, hashlib.sha256(payload).hexdigest(), len(payload))


@dataclass(frozen=True, slots=True)
class FrEnumObservation:
    schema_name: str
    schema_path: str
    source_path: str
    values: tuple[Any, ...]
    raw_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FrDocumentedEnums:
    enums: tuple[FrEnumObservation, ...]
    raw: dict[str, Any]
    input_sha256: str
    input_bytes: int


def read_fr_documented_enums(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_nodes: int = 500_000,
    max_depth: int = 64,
) -> FrDocumentedEnums:
    """Read direct and array-item enums under OpenAPI components.schemas.

    Schema names, values, duplicates and order are literal source observations.
    Tuple position is the zero-based enum ordinal. Raw schemas and the full root
    retain descriptions, constraints, version fields and unselected content.
    No equality with a roster or a separately captured topic list is inferred.
    """
    raw = _object(_read(payload, max_bytes, max_nodes, max_depth), "$")
    components = _object(raw.get("components"), "$.components")
    schemas = _object(components.get("schemas"), "$.components.schemas")
    enums = []
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        path = "$.components.schemas[" + json.dumps(name, ensure_ascii=False) + "]"
        candidates = [(schema, path)]
        if isinstance(schema.get("items"), dict):
            candidates.append((schema["items"], path + ".items"))
        for container, location in candidates:
            if "enum" not in container:
                continue
            values = _field(container, "enum", list, location)
            enums.append(FrEnumObservation(name, path, location + ".enum", tuple(values), schema))
    return FrDocumentedEnums(tuple(enums), raw, hashlib.sha256(payload).hexdigest(), len(payload))


@dataclass(frozen=True, slots=True)
class FrTypeFacetObservation:
    code: str
    name: str
    count: int
    raw: dict[str, Any]
    source_path: str


@dataclass(frozen=True, slots=True)
class FrTypeFacets:
    records: tuple[FrTypeFacetObservation, ...]
    raw: dict[str, Any]
    input_sha256: str
    input_bytes: int


def read_fr_type_facets(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_nodes: int = 500_000,
    max_depth: int = 64,
) -> FrTypeFacets:
    """Read literal facet names/counts without joining them to documented codes."""
    raw = _object(_read(payload, max_bytes, max_nodes, max_depth), "$")
    rows = []
    for code, value in raw.items():
        path = "$[" + json.dumps(code, ensure_ascii=False) + "]"
        row = _object(value, path)
        rows.append(
            FrTypeFacetObservation(
                code,
                _field(row, "name", str, path),
                _field(row, "count", int, path),
                row,
                path,
            )
        )
    return FrTypeFacets(tuple(rows), raw, hashlib.sha256(payload).hexdigest(), len(payload))
