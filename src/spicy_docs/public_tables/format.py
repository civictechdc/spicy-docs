"""Public-table identities, physical format choices, and member naming."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pyarrow as pa
from rulespec_artifacts import (
    ArtifactPin,
    Producer,
    Supersedes,
    VerifiedArtifact,
)

from spicy_docs.public_table_profiles import PublicTableProfile
from spicy_docs.releases.format import SUPPORTED_PRODUCER_PRODUCTS

KIND = "spicyregs-public-table"
FORMAT_VERSION = "1.0"
VERIFIER_ID = "urn:spicy-regs:public-table-verifier"
VERIFIER_VERSION = "1.0"
INPUT_ROLE = "source-native-release"
MEMBER_ROLE = "public-table-data"
MANIFEST_KEY = "manifests/public-table.json"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
PARQUET_FORMAT_VERSION = "2.6"
PARQUET_COMPRESSION = "zstd"
DEFAULT_MAX_ROWS_PER_MEMBER = 100_000
DEFAULT_MAX_ROWS_PER_BATCH = 2_000
DEFAULT_MAX_BATCH_BYTES = 16 * 1024 * 1024

_SPEC_FIELDS = frozenset(
    {
        "columns",
        "maxRowsPerMember",
        "parquetCompression",
        "parquetFormatVersion",
        "partitionColumns",
        "primaryKey",
        "projectionId",
        "projectionVersion",
        "schemaId",
        "sortColumns",
        "sourceStateDigest",
        "sourceStateScope",
        "sourceSystemId",
        "tableName",
    }
)
_PARTITION_VALUE = re.compile(r"^[A-Za-z0-9._-]+$")
_PART_FILE = re.compile(r"^part-([0-9]{6})\.parquet$")


class PublicTableError(ValueError):
    """A public table cannot be built, admitted, or published safely."""


@runtime_checkable
class SourceNativeTableInput(Protocol):
    """The admitted source-native facts needed by the public projection."""

    @property
    def pin(self) -> ArtifactPin: ...

    source_state_scope: str
    source_system_id: str
    source_state_digest: str

    def iter_records(self) -> Iterator[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class PublicTableBuild:
    """Product identity and bounded physical choices for one generation."""

    producer: Producer
    max_rows_per_member: int = DEFAULT_MAX_ROWS_PER_MEMBER
    max_rows_per_batch: int = DEFAULT_MAX_ROWS_PER_BATCH
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES
    supersedes: Supersedes | None = None

    def __post_init__(self) -> None:
        if self.producer.product not in SUPPORTED_PRODUCER_PRODUCTS:
            raise PublicTableError(
                f"public-table producer product must be one of {sorted(SUPPORTED_PRODUCER_PRODUCTS)}"
            )
        if self.producer.verifier_id != VERIFIER_ID or self.producer.verifier_version != VERIFIER_VERSION:
            raise PublicTableError("public-table producer names an unsupported verifier")
        if (
            min(
                self.max_rows_per_member,
                self.max_rows_per_batch,
                self.max_batch_bytes,
            )
            < 1
        ):
            raise PublicTableError("public-table physical bounds must be positive")


@dataclass(frozen=True, slots=True)
class PublishedPublicTable:
    root: Path
    artifact: VerifiedArtifact


def _arrow_schema(profile: PublicTableProfile) -> pa.Schema:
    return pa.schema((name, pa.string()) for name in profile.columns)


def _spec(
    source: SourceNativeTableInput,
    *,
    profile: PublicTableProfile,
    max_rows_per_member: int,
) -> dict[str, Any]:
    return {
        "columns": list(profile.columns),
        "maxRowsPerMember": max_rows_per_member,
        "parquetCompression": PARQUET_COMPRESSION,
        "parquetFormatVersion": PARQUET_FORMAT_VERSION,
        "partitionColumns": list(profile.partition_columns),
        "primaryKey": profile.primary_key,
        "projectionId": profile.projection_id,
        "projectionVersion": profile.projection_version,
        "schemaId": profile.schema_id,
        "sortColumns": list(profile.sort_columns),
        "sourceStateDigest": source.source_state_digest,
        "sourceStateScope": source.source_state_scope,
        "sourceSystemId": source.source_system_id,
        "tableName": profile.table_name,
    }


def _validate_profile(profile: PublicTableProfile) -> None:
    columns = profile.columns
    if not columns or len(columns) != len(set(columns)):
        raise PublicTableError("public-table columns must be nonempty and distinct")
    if profile.primary_key not in columns:
        raise PublicTableError("public-table primary key is absent from its columns")
    if any(name not in columns for name in (*profile.partition_columns, *profile.sort_columns)):
        raise PublicTableError("public-table partition or sort column is absent")
    if len(profile.partition_columns) != len(set(profile.partition_columns)):
        raise PublicTableError("public-table partition columns repeat")
    if not profile.sort_columns or profile.primary_key not in profile.sort_columns:
        raise PublicTableError("public-table total order must include its primary key")


def _member_position(
    object_key: str,
    *,
    profile: PublicTableProfile,
) -> tuple[tuple[str, ...], int]:
    parts = object_key.split("/")
    expected_length = 2 + len(profile.partition_columns)
    empty_partition_member = bool(profile.partition_columns) and len(parts) == 2
    if parts[0] != "data" or (len(parts) != expected_length and not empty_partition_member):
        raise PublicTableError(f"invalid public-table member key: {object_key}")
    values: list[str] = []
    partition_components = () if empty_partition_member else parts[1:-1]
    for column, component in zip(
        profile.partition_columns if not empty_partition_member else (),
        partition_components,
        strict=True,
    ):
        prefix = f"{column}="
        value = component.removeprefix(prefix)
        if not component.startswith(prefix) or not value or _PARTITION_VALUE.fullmatch(value) is None:
            raise PublicTableError(f"invalid public-table partition key: {object_key}")
        values.append(value)
    match = _PART_FILE.fullmatch(parts[-1])
    if match is None:
        raise PublicTableError(f"invalid public-table member filename: {object_key}")
    return tuple(values), int(match.group(1))


def _member_key(
    partition: tuple[str, ...],
    part: int,
    *,
    profile: PublicTableProfile,
) -> str:
    if len(partition) not in {0, len(profile.partition_columns)}:
        raise PublicTableError("public-table partition arity differs")
    if not partition and profile.partition_columns:
        # A valid empty release still needs one self-describing Parquet member.
        # No row can contradict the absent Hive value.
        return f"data/part-{part:06d}.parquet"
    components = ["data"]
    for column, value in zip(profile.partition_columns, partition, strict=True):
        if _PARTITION_VALUE.fullmatch(value) is None:
            raise PublicTableError(f"public-table partition value for {column} is not portable: {value!r}")
        components.append(f"{column}={value}")
    components.append(f"part-{part:06d}.parquet")
    return "/".join(components)
