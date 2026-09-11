"""Public-table admission and the full bounded Parquet-row gate."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from rulespec_artifacts import (
    MemberDescriptor,
    MemberSource,
    VerifiedArtifact,
    iter_member_descriptors,
)

from spicy_docs.public_tables.format import (
    _SPEC_FIELDS,
    INPUT_ROLE,
    KIND,
    MANIFEST_KEY,
    MEMBER_ROLE,
    PARQUET_COMPRESSION,
    PARQUET_FORMAT_VERSION,
    PARQUET_MEDIA_TYPE,
    VERIFIER_ID,
    VERIFIER_VERSION,
    PublicTableError,
    _arrow_schema,
    _member_position,
    _validate_profile,
)
from spicy_docs.public_tables.profiles import PublicTableProfile, PublicTableProjectionError
from spicy_docs.releases.format import SUPPORTED_PRODUCER_PRODUCTS


def _validate_root(
    artifact: VerifiedArtifact,
    source: MemberSource,
    *,
    profile: PublicTableProfile,
) -> tuple[Mapping[str, Any], tuple[MemberDescriptor, ...]]:
    root = artifact.root
    if root.get("kind") != KIND:
        raise PublicTableError("artifact is not a SpicyRegs public table")
    producer = root.get("producer")
    if not isinstance(producer, Mapping) or (
        producer.get("product") not in SUPPORTED_PRODUCER_PRODUCTS
        or producer.get("verifierId") != VERIFIER_ID
        or producer.get("verifierVersion") != VERIFIER_VERSION
    ):
        raise PublicTableError("public-table producer identity differs")
    inputs = root.get("inputs")
    if (
        not isinstance(inputs, list)
        or len(inputs) != 1
        or not isinstance(inputs[0], Mapping)
        or inputs[0].get("role") != INPUT_ROLE
    ):
        raise PublicTableError("public table must pin exactly one source-native release")
    spec = root.get("spec")
    if not isinstance(spec, Mapping) or set(spec) != _SPEC_FIELDS:
        raise PublicTableError("public-table specification fields differ")
    expected_profile_values = {
        "columns": list(profile.columns),
        "parquetCompression": PARQUET_COMPRESSION,
        "parquetFormatVersion": PARQUET_FORMAT_VERSION,
        "partitionColumns": list(profile.partition_columns),
        "primaryKey": profile.primary_key_spec,
        "projectionId": profile.projection_id,
        "projectionVersion": profile.projection_version,
        "schemaId": profile.schema_id,
        "sortColumns": list(profile.sort_columns),
        "sourceSystemId": profile.source_system_id,
        "tableName": profile.table_name,
    }
    if any(spec.get(name) != value for name, value in expected_profile_values.items()):
        raise PublicTableError("public-table specification differs from its injected profile")
    row_limit = spec.get("maxRowsPerMember")
    if isinstance(row_limit, bool) or not isinstance(row_limit, int) or row_limit < 1:
        raise PublicTableError("public-table member row limit is invalid")
    if spec.get("sourceStateScope") not in {"complete-snapshot", "observed-crawl"}:
        raise PublicTableError("public-table source-state scope is invalid")
    state_digest = spec.get("sourceStateDigest")
    if not isinstance(state_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", state_digest) is None:
        raise PublicTableError("public-table source-state digest is invalid")
    manifests = root.get("memberManifests")
    if (
        not isinstance(manifests, list)
        or len(manifests) != 1
        or not isinstance(manifests[0], Mapping)
        or manifests[0].get("scopeKind") != "global"
        or manifests[0].get("scopeId") != profile.table_name
        or manifests[0].get("objectKey") != MANIFEST_KEY
    ):
        raise PublicTableError("public table must carry one global member manifest")
    members = tuple(iter_member_descriptors(artifact, source))
    if not members:
        raise PublicTableError("public table has no Parquet member")
    positions: list[tuple[tuple[str, ...], int]] = []
    total_rows = 0
    for member in members:
        if (
            member.object_key is None
            or member.role != MEMBER_ROLE
            or member.media_type != PARQUET_MEDIA_TYPE
            or member.schema_id != profile.schema_id
            or member.record_count is None
            or member.record_count > row_limit
        ):
            raise PublicTableError("public-table member descriptor differs")
        position = _member_position(member.object_key, profile=profile)
        if profile.partition_columns and not position[0] and member.record_count != 0:
            raise PublicTableError("partitioned public table has rows outside a Hive partition")
        positions.append(position)
        total_rows += member.record_count
    if positions != sorted(positions) or len(positions) != len(set(positions)):
        raise PublicTableError("public-table members are not sorted and distinct")
    by_partition: dict[tuple[str, ...], list[int]] = {}
    for partition, part in positions:
        by_partition.setdefault(partition, []).append(part)
    if any(parts != list(range(len(parts))) for parts in by_partition.values()):
        raise PublicTableError("public-table member sequence is incomplete")
    if total_rows == 0:
        if len(members) != 1 or members[0].record_count != 0:
            raise PublicTableError("empty public table must carry one empty member")
    elif any(member.record_count == 0 for member in members):
        raise PublicTableError("nonempty public table carries an empty member")
    return spec, members


def verify_public_table_admission(
    artifact: VerifiedArtifact,
    source: MemberSource,
    *,
    profile: PublicTableProfile,
) -> None:
    """Check the cheap product shape after Rulespec structural admission."""

    _validate_profile(profile)
    _validate_root(artifact, source, profile=profile)


def _sort_value(row: Mapping[str, Any], columns: Sequence[str]) -> tuple[tuple[int, str], ...]:
    return tuple((1, "") if row[name] is None else (0, str(row[name])) for name in columns)


def verify_public_table_release(
    artifact: VerifiedArtifact,
    source: MemberSource,
    *,
    profile: PublicTableProfile,
) -> None:
    """Run the bounded producer gate over every public Parquet row."""

    spec, members = _validate_root(artifact, source, profile=profile)
    expected_schema = _arrow_schema(profile)
    seen_by_partition: dict[tuple[str, ...], tuple[tuple[int, str], ...]] = {}
    with tempfile.TemporaryDirectory(prefix="public-table-verify-") as directory:
        identities = sqlite3.connect(Path(directory) / "identities.sqlite3")
        identities.execute("CREATE TABLE ids (value TEXT PRIMARY KEY)")
        try:
            for member in members:
                assert member.object_key is not None and member.record_count is not None
                partition, _ = _member_position(member.object_key, profile=profile)
                with source.open(member.object_key) as stream:
                    parquet = pq.ParquetFile(stream)
                    if parquet.schema_arrow != expected_schema:
                        raise PublicTableError("public-table Parquet schema differs")
                    if parquet.metadata.num_rows != member.record_count:
                        raise PublicTableError("public-table Parquet row count differs")
                    previous = seen_by_partition.get(partition)
                    for batch in parquet.iter_batches(batch_size=2_000):
                        for row in pa.Table.from_batches([batch]).to_pylist():
                            try:
                                identity = profile.row_key(row)
                            except PublicTableProjectionError as error:
                                raise PublicTableError(str(error)) from error
                            try:
                                identities.execute("INSERT INTO ids VALUES (?)", (identity,))
                            except sqlite3.IntegrityError as error:
                                raise PublicTableError(f"public table repeats primary key {identity!r}") from error
                            actual_partition = tuple(str(row[name]) for name in profile.partition_columns)
                            if actual_partition != partition:
                                raise PublicTableError("public-table row differs from its Hive partition")
                            order = _sort_value(row, profile.sort_columns)
                            if previous is not None and order <= previous:
                                raise PublicTableError("public-table rows are not in their declared total order")
                            previous = order
                    if previous is not None:
                        seen_by_partition[partition] = previous
            identities.commit()
            observed = int(identities.execute("SELECT count(*) FROM ids").fetchone()[0])
            if observed != artifact.root["counts"]["totalRecordCount"]:
                raise PublicTableError("public-table root row accounting differs")
            if any(
                member.record_count is not None and member.record_count > spec["maxRowsPerMember"] for member in members
            ):
                raise PublicTableError("public-table member exceeds its row bound")
        finally:
            identities.close()
