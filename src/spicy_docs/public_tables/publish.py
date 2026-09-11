"""Index, project, verify, and publish an immutable public Parquet table."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from rulespec_artifacts import (
    ROOT_OBJECT_KEY,
    ArtifactInput,
    LocalMemberSource,
    MemberManifestReference,
    admit_artifact,
    build_artifact_root,
    canonical_json_bytes,
    describe_member,
    parse_canonical_json,
)

from spicy_docs.public_table_profiles import PublicTableProfile
from spicy_docs.public_tables.format import (
    INPUT_ROLE,
    KIND,
    MANIFEST_KEY,
    MEMBER_ROLE,
    PARQUET_COMPRESSION,
    PARQUET_FORMAT_VERSION,
    PARQUET_MEDIA_TYPE,
    PublicTableBuild,
    PublicTableError,
    PublishedPublicTable,
    SourceNativeTableInput,
    _arrow_schema,
    _member_key,
    _spec,
    _validate_profile,
)
from spicy_docs.public_tables.verify import (
    verify_public_table_release,
)
from spicy_docs.publication import (
    ImmutablePublicationError,
    publish_directory_once,
    write_bytes_once,
)


def _create_row_index(path: Path, profile: PublicTableProfile) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    partition_fields = ", ".join(
        f"partition_{index} TEXT NOT NULL" for index, _ in enumerate(profile.partition_columns)
    )
    sort_fields = ", ".join(f"sort_{index} TEXT" for index, _ in enumerate(profile.sort_columns))
    fields = ["row_id TEXT PRIMARY KEY"]
    if partition_fields:
        fields.append(partition_fields)
    if sort_fields:
        fields.append(sort_fields)
    fields.append("payload BLOB NOT NULL")
    connection.execute(f"CREATE TABLE rows ({', '.join(fields)})")
    return connection


def _index_rows(
    connection: sqlite3.Connection,
    source: SourceNativeTableInput,
    *,
    profile: PublicTableProfile,
) -> int:
    columns = [
        "row_id",
        *(f"partition_{index}" for index, _ in enumerate(profile.partition_columns)),
        *(f"sort_{index}" for index, _ in enumerate(profile.sort_columns)),
        "payload",
    ]
    placeholders = ", ".join("?" for _ in columns)
    query = f"INSERT INTO rows ({', '.join(columns)}) VALUES ({placeholders})"
    count = 0
    for source_row in source.iter_records():
        row = profile.project(source_row)
        identity = profile.row_key(row)
        partition = tuple(row[name] for name in profile.partition_columns)
        if any(value is None for value in partition):
            raise PublicTableError("public-table partition value is null")
        sort = tuple(row[name] for name in profile.sort_columns)
        payload = canonical_json_bytes(row)
        try:
            connection.execute(
                query,
                (
                    identity,
                    *partition,
                    *sort,
                    payload,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise PublicTableError(f"public table repeats primary key {identity!r}") from error
        count += 1
        if count % 10_000 == 0:
            connection.commit()
    connection.commit()
    return count


def _partitions(
    connection: sqlite3.Connection,
    *,
    profile: PublicTableProfile,
) -> Iterator[tuple[str, ...]]:
    if not profile.partition_columns:
        yield ()
        return
    columns = ", ".join(f"partition_{index}" for index, _ in enumerate(profile.partition_columns))
    for row in connection.execute(f"SELECT DISTINCT {columns} FROM rows ORDER BY {columns}"):
        yield tuple(str(value) for value in row)


def _partition_rows(
    connection: sqlite3.Connection,
    partition: tuple[str, ...],
    *,
    profile: PublicTableProfile,
) -> sqlite3.Cursor:
    where = " AND ".join(f"partition_{index} = ?" for index, _ in enumerate(partition)) or "1 = 1"
    order_terms: list[str] = []
    for index, _ in enumerate(profile.sort_columns):
        order_terms.extend((f"sort_{index} IS NULL", f"sort_{index}"))
    return connection.execute(
        f"SELECT payload FROM rows WHERE {where} ORDER BY {', '.join(order_terms)}",
        partition,
    )


def _decode_row(payload: bytes) -> dict[str, str | None]:
    value = parse_canonical_json(payload, path="public-table-row")
    if not isinstance(value, Mapping):
        raise PublicTableError("indexed public-table row is not an object")
    return {str(name): item for name, item in value.items()}  # type: ignore[misc]


def _write_empty_member(staging: Path, *, profile: PublicTableProfile) -> tuple[str, int]:
    key = _member_key((), 0, profile=profile)
    path = staging / key
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        _arrow_schema(profile).empty_table(),
        path,
        compression=PARQUET_COMPRESSION,
        version=PARQUET_FORMAT_VERSION,
    )
    return key, 0


def _write_partition(
    staging: Path,
    connection: sqlite3.Connection,
    partition: tuple[str, ...],
    *,
    profile: PublicTableProfile,
    build: PublicTableBuild,
) -> list[tuple[str, int]]:
    cursor = _partition_rows(connection, partition, profile=profile)
    schema = _arrow_schema(profile)
    completed: list[tuple[str, int]] = []
    writer: pq.ParquetWriter | None = None
    key = ""
    part = 0
    member_rows = 0
    batch: list[dict[str, str | None]] = []
    batch_bytes = 0

    def open_writer() -> None:
        nonlocal writer, key
        key = _member_key(partition, part, profile=profile)
        path = staging / key
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(
            path,
            schema,
            compression=PARQUET_COMPRESSION,
            version=PARQUET_FORMAT_VERSION,
        )

    def flush_batch() -> None:
        nonlocal batch, batch_bytes
        if not batch:
            return
        assert writer is not None
        writer.write_table(pa.Table.from_pylist(batch, schema=schema))
        batch = []
        batch_bytes = 0

    def close_writer() -> None:
        nonlocal writer, member_rows
        if writer is None:
            return
        flush_batch()
        writer.close()
        completed.append((key, member_rows))
        writer = None
        member_rows = 0

    try:
        for (raw_payload,) in cursor:
            payload = bytes(raw_payload)
            if len(payload) > build.max_batch_bytes:
                raise PublicTableError("one public-table row exceeds the configured batch-byte bound")
            if writer is None:
                open_writer()
            if member_rows == build.max_rows_per_member:
                close_writer()
                part += 1
                open_writer()
            if batch and (len(batch) == build.max_rows_per_batch or batch_bytes + len(payload) > build.max_batch_bytes):
                flush_batch()
            batch.append(_decode_row(payload))
            batch_bytes += len(payload)
            member_rows += 1
        close_writer()
        return completed
    finally:
        if writer is not None:
            # Release the handle on failure without flushing an unfinished batch.
            writer.close()


def _write_members(
    staging: Path,
    connection: sqlite3.Connection,
    *,
    profile: PublicTableProfile,
    build: PublicTableBuild,
) -> list[tuple[str, int]]:
    members: list[tuple[str, int]] = []
    for partition in _partitions(connection, profile=profile):
        members.extend(
            _write_partition(
                staging,
                connection,
                partition,
                profile=profile,
                build=build,
            )
        )
    if not members:
        members.append(_write_empty_member(staging, profile=profile))
    return members


class PublicTablePublisher:
    """Project one admitted source release into one immutable public table."""

    def __init__(self, profile: PublicTableProfile) -> None:
        _validate_profile(profile)
        self._profile = profile

    def publish(
        self,
        source: SourceNativeTableInput,
        *,
        build: PublicTableBuild,
        destination: Path,
    ) -> PublishedPublicTable:
        destination = Path(destination).absolute()
        if destination.exists() or destination.is_symlink():
            raise ImmutablePublicationError(f"refusing to replace immutable directory: {destination}")
        if source.source_system_id != self._profile.source_system_id:
            raise PublicTableError("source-native release does not match the public-table profile")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}.build-",
            dir=destination.parent,
        ) as directory:
            workspace = Path(directory)
            staging = workspace / "generation"
            staging.mkdir()
            connection = _create_row_index(workspace / "rows.sqlite3", self._profile)
            try:
                indexed = _index_rows(connection, source, profile=self._profile)
                member_rows = _write_members(
                    staging,
                    connection,
                    profile=self._profile,
                    build=build,
                )
            finally:
                connection.close()
            if sum(count for _, count in member_rows) != indexed:
                raise PublicTableError("public-table member accounting differs")
            local = LocalMemberSource(staging)
            members = [
                describe_member(
                    local,
                    object_key=key,
                    role=MEMBER_ROLE,
                    media_type=PARQUET_MEDIA_TYPE,
                    record_count=count,
                    schema_id=self._profile.schema_id,
                )
                for key, count in member_rows
            ]
            manifest, manifest_bytes = MemberManifestReference.for_members(
                scope_kind="global",
                scope_id=self._profile.table_name,
                object_key=MANIFEST_KEY,
                members=members,
            )
            write_bytes_once(staging / MANIFEST_KEY, manifest_bytes)
            root = build_artifact_root(
                kind=KIND,
                spec=_spec(
                    source,
                    profile=self._profile,
                    max_rows_per_member=build.max_rows_per_member,
                ),
                producer=build.producer,
                inputs=(
                    ArtifactInput(
                        role=INPUT_ROLE,
                        logical_id=source.pin.logical_id,
                        artifact_digest=source.pin.artifact_digest,
                    ),
                ),
                manifests=(manifest,),
                supersedes=build.supersedes,
            )
            write_bytes_once(staging / ROOT_OBJECT_KEY, canonical_json_bytes(root))
            artifact = admit_artifact(
                LocalMemberSource(staging),
                semantic_verifier=lambda artifact, source: verify_public_table_release(
                    artifact,
                    source,
                    profile=self._profile,
                ),
                scratch_directory=workspace / "verify",
            )
            publish_directory_once(staging, destination)
        return PublishedPublicTable(destination, artifact)
