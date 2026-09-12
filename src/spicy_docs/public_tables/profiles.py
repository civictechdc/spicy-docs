"""Faithful public Parquet views over Regulations.gov source records.

The source-native release remains the complete source record.  These profiles
only preserve the stable flat columns already used by public Parquet readers;
they do not add catalog policy, document processing, or search behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from rulespec_artifacts import canonical_json_bytes

from spicy_docs.schemas.federal_register import (
    FEDERAL_REGISTER_COLUMNS,
    project_federal_register_document,
)
from spicy_docs.schemas.regulations import COMMENT, DOCKET, DOCUMENT
from spicy_docs.sources.federal_register.native import (
    SCHEMA_NAME as FEDERAL_REGISTER_SCHEMA_NAME,
)
from spicy_docs.sources.federal_register.native import (
    SOURCE_SYSTEM_ID as FEDERAL_REGISTER_SOURCE_SYSTEM_ID,
)
from spicy_docs.sources.federal_register.native import federal_register_source_record_id
from spicy_docs.sources.regulations_gov.definitions import (
    COMMENT_SCHEMA_NAME,
    COMMENT_SOURCE_SYSTEM_ID,
    DOCKET_SCHEMA_NAME,
    DOCKET_SOURCE_SYSTEM_ID,
    DOCUMENT_SCHEMA_NAME,
    DOCUMENT_SOURCE_SYSTEM_ID,
)


class PublicTableProjectionError(ValueError):
    """A source-native row cannot be represented by its public source view."""


@dataclass(frozen=True, slots=True)
class PublicTableProfile:
    """One explicitly injected source-to-public-table projection."""

    table_name: str
    schema_id: str
    projection_id: str
    projection_version: str
    source_system_id: str
    source_schema_name: str
    columns: tuple[str, ...]
    primary_key: str | tuple[str, ...]
    partition_columns: tuple[str, ...]
    sort_columns: tuple[str, ...]
    project_source_record: Callable[[dict[str, Any]], Mapping[str, Any]]
    source_record_id: Callable[[Mapping[str, Any]], str] | None = None

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return (self.primary_key,) if isinstance(self.primary_key, str) else self.primary_key

    @property
    def primary_key_spec(self) -> str | list[str]:
        """Scalar keys name one column; compound keys name every column."""
        return self.primary_key if isinstance(self.primary_key, str) else list(self.primary_key)

    def row_key(self, row: Mapping[str, Any]) -> str:
        """A collision-safe index key, distinct from the source's identity encoding."""
        values = [row[name] for name in self.primary_key_columns]
        if any(not isinstance(value, str) or not value for value in values):
            raise PublicTableProjectionError("public-table primary key is empty")
        return values[0] if isinstance(self.primary_key, str) else canonical_json_bytes(values).decode("utf-8")

    def project(self, source_row: Mapping[str, Any]) -> dict[str, str | None]:
        if source_row.get("schemaName") != self.source_schema_name:
            raise PublicTableProjectionError(f"{self.table_name} source schema differs from {self.source_schema_name}")
        record = source_row.get("record")
        if not isinstance(record, Mapping):
            raise PublicTableProjectionError(f"{self.table_name} source-native row has no record object")
        projected = self.project_source_record(dict(record))
        if set(projected) != set(self.columns):
            raise PublicTableProjectionError(f"{self.table_name} public columns differ from its stable schema")
        normalized = {name: _public_text(projected[name], field=name) for name in self.columns}
        key = self.row_key(normalized)
        identity = self.source_record_id(normalized) if self.source_record_id is not None else key
        if identity != source_row.get("sourceRecordId"):
            raise PublicTableProjectionError(f"{self.table_name} primary key differs from the source record identity")
        for name in self.partition_columns:
            value = normalized[name]
            if value is None or not value:
                raise PublicTableProjectionError(f"{self.table_name} partition column {name} is empty")
        return normalized


def _public_text(value: object, *, field: str) -> str | None:
    """Match the existing all-UTF-8 public schemas without silent objects."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    raise PublicTableProjectionError(f"public field {field} has unsupported value type {type(value).__name__}")


REGULATIONS_GOV_DOCUMENT_PUBLIC_TABLE: Final = PublicTableProfile(
    table_name="documents",
    schema_id="urn:spicy-regs:schema:public-documents:1.0",
    projection_id="urn:spicy-regs:projection:regulations-gov-public-documents",
    projection_version="1.0",
    source_system_id=DOCUMENT_SOURCE_SYSTEM_ID,
    source_schema_name=DOCUMENT_SCHEMA_NAME,
    columns=tuple(DOCUMENT.schema),
    primary_key=DOCUMENT.dedup_key,
    partition_columns=(),
    sort_columns=("agency_code", "posted_date", "document_id"),
    project_source_record=DOCUMENT.extract,
)

REGULATIONS_GOV_DOCKET_PUBLIC_TABLE: Final = PublicTableProfile(
    table_name="dockets",
    schema_id="urn:spicy-regs:schema:public-dockets:1.0",
    projection_id="urn:spicy-regs:projection:regulations-gov-public-dockets",
    projection_version="1.0",
    source_system_id=DOCKET_SOURCE_SYSTEM_ID,
    source_schema_name=DOCKET_SCHEMA_NAME,
    columns=tuple(DOCKET.schema),
    primary_key=DOCKET.dedup_key,
    partition_columns=(),
    sort_columns=("agency_code", "modify_date", "docket_id"),
    project_source_record=DOCKET.extract,
)

REGULATIONS_GOV_COMMENT_PUBLIC_TABLE: Final = PublicTableProfile(
    table_name="comments",
    schema_id="urn:spicy-regs:schema:public-comments:1.0",
    projection_id="urn:spicy-regs:projection:regulations-gov-public-comments",
    projection_version="1.0",
    source_system_id=COMMENT_SOURCE_SYSTEM_ID,
    source_schema_name=COMMENT_SCHEMA_NAME,
    columns=tuple(COMMENT.schema),
    primary_key=COMMENT.dedup_key,
    partition_columns=("agency_code",),
    sort_columns=("docket_id", "posted_date", "comment_id"),
    project_source_record=COMMENT.extract,
)

FEDERAL_REGISTER_PUBLIC_TABLE: Final = PublicTableProfile(
    table_name="federal_register",
    schema_id="urn:spicy-regs:schema:public-federal-register:1.0",
    projection_id="urn:spicy-regs:projection:federal-register-public-table",
    projection_version="1.1",
    source_system_id=FEDERAL_REGISTER_SOURCE_SYSTEM_ID,
    source_schema_name=FEDERAL_REGISTER_SCHEMA_NAME,
    columns=FEDERAL_REGISTER_COLUMNS,
    primary_key=("document_number", "publication_date"),
    partition_columns=(),
    sort_columns=("publication_date", "document_number"),
    project_source_record=project_federal_register_document,
    source_record_id=federal_register_source_record_id,
)


__all__ = [
    "FEDERAL_REGISTER_PUBLIC_TABLE",
    "REGULATIONS_GOV_COMMENT_PUBLIC_TABLE",
    "REGULATIONS_GOV_DOCKET_PUBLIC_TABLE",
    "REGULATIONS_GOV_DOCUMENT_PUBLIC_TABLE",
    "PublicTableProfile",
    "PublicTableProjectionError",
]
