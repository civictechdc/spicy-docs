"""Bounded member I/O and content-addressed release partitions."""

from __future__ import annotations

import hashlib
import heapq
import os
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from rulespec_artifacts import (
    BlobSource,
    MemberDescriptor,
    MemberSource,
    canonical_json_bytes,
    describe_member_from_receipt,
    parse_admitted_json,
    parse_canonical_json,
)

from spicy_docs.releases.format import (
    MAX_ROW_BYTES,
    PARTITION_ALGORITHM,
    PARTITION_BUCKET_COUNT,
    PARTITION_KINDS,
    PARTITION_PAGES,
    PARTITION_RENDITIONS,
    PARTITION_ROLES,
    ROLE_LEDGER,
    ROLE_RECORDS,
    ROLE_RENDITIONS,
    SourceNativeReleaseError,
)
from spicy_docs.storage.blobs import SourceNativeBlobStore


@dataclass(slots=True)
class _ByteAccounting:
    payload_bytes_read: int = 0
    payload_bytes_reused: int = 0
    payload_bytes_written: int = 0

    def add(self, *, byte_size: int, reused: bool, bytes_written: int) -> None:
        self.payload_bytes_read += byte_size
        if reused:
            self.payload_bytes_reused += byte_size
        self.payload_bytes_written += bytes_written


@dataclass(frozen=True, slots=True)
class _PayloadPartition:
    partition_kind: str
    partition_id: str
    member: MemberDescriptor

    def receipt(self) -> dict[str, object]:
        if self.member.blob_ref is None or self.member.record_count is None:
            raise RuntimeError("source-native payload partition is incomplete")
        return {
            "blobRef": self.member.blob_ref,
            "byteSize": self.member.byte_size,
            "partitionId": self.partition_id,
            "partitionKind": self.partition_kind,
            "recordCount": self.member.record_count,
        }


def _jsonl_rows(stream: BinaryIO, *, label: str) -> Iterator[Mapping[str, Any]]:
    """Stream one payload member's rows, parsed but not re-canonicalised.

    Every caller reaches this through a reader whose constructor has already
    run ``admit_artifact``, which streams each member, hashes it, and refuses
    the release unless the bytes match the digest its manifest declares. The
    canonical form of a row is therefore already pinned by the time it is read,
    so ``parse_admitted_json`` keeps the parse-time refusals and drops the
    re-encode that used to prove it a second time -- 7x the cost of the parse
    it followed, and 85 s of one profiled catalog build over 1.33M rows.
    """

    while raw := stream.readline(MAX_ROW_BYTES + 2):
        if len(raw) > MAX_ROW_BYTES + 1:
            raise SourceNativeReleaseError(f"{label} contains an oversized row")
        if not raw.endswith(b"\n"):
            raise SourceNativeReleaseError(f"{label} contains an unterminated row")
        value = parse_admitted_json(raw[:-1], path=label)
        if not isinstance(value, Mapping):
            raise SourceNativeReleaseError(f"{label} row is not an object")
        yield value


def _read_jsonl(source: MemberSource, object_key: str) -> Generator[Mapping[str, Any], None, None]:
    with source.open(object_key) as stream:
        yield from _jsonl_rows(stream, label=object_key)


@contextmanager
def _open_descriptor(
    source: MemberSource,
    blob_source: BlobSource | None,
    member: MemberDescriptor,
) -> Iterator[BinaryIO]:
    if member.object_key is not None:
        with source.open(member.object_key) as stream:
            yield stream
        return
    if member.blob_ref is None or blob_source is None:
        raise SourceNativeReleaseError("source-native external members require an injected blob source")
    with blob_source.open(member.blob_ref) as stream:
        yield stream


def _read_one_json(source: MemberSource, object_key: str, byte_limit: int = MAX_ROW_BYTES) -> Mapping[str, Any]:
    with source.open(object_key) as stream:
        raw = stream.read(byte_limit + 1)
    if len(raw) > byte_limit:
        raise SourceNativeReleaseError(f"{object_key} exceeds its product limit")
    value = parse_canonical_json(raw, path=object_key)
    if not isinstance(value, Mapping):
        raise SourceNativeReleaseError(f"{object_key} is not an object")
    return value


def _partition_id(identity: str) -> str:
    if not isinstance(identity, str) or not identity:
        raise SourceNativeReleaseError("source-native partition identity must be nonempty text")
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return f"{int.from_bytes(digest, 'big') % PARTITION_BUCKET_COUNT:02d}"


def _partition_policy() -> dict[str, object]:
    return {
        "algorithm": PARTITION_ALGORITHM,
        "bucketCount": PARTITION_BUCKET_COUNT,
        "identityEncoding": "utf-8",
    }


def _file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            yield block


def _stage_partition(
    scratch: Path,
    *,
    blob_store: SourceNativeBlobStore,
    accounting: _ByteAccounting,
    partition_kind: str,
    partition_id: str,
    rows: Iterable[Mapping[str, Any]],
) -> _PayloadPartition | None:
    path = scratch / f"{partition_kind}-{partition_id}.jsonl"
    digest = hashlib.sha256()
    byte_size = 0
    record_count = 0
    try:
        with path.open("xb") as stream:
            for value in rows:
                payload = canonical_json_bytes(value)
                if len(payload) > MAX_ROW_BYTES:
                    raise SourceNativeReleaseError(f"source-native row exceeds {MAX_ROW_BYTES} bytes")
                for chunk in (payload, b"\n"):
                    stream.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
                record_count += 1
            stream.flush()
            os.fsync(stream.fileno())
        if record_count == 0:
            return None
        blob_ref = "sha256:" + digest.hexdigest()
        write = blob_store.put_blob(blob_ref, byte_size, _file_chunks(path))
        accounting.add(
            byte_size=byte_size,
            reused=write.reused,
            bytes_written=write.bytes_written,
        )
        return _PayloadPartition(
            partition_kind,
            partition_id,
            describe_member_from_receipt(
                blob_ref=blob_ref,
                role=PARTITION_ROLES[partition_kind],
                media_type="application/x-ndjson",
                byte_size=byte_size,
                record_count=record_count,
            ),
        )
    finally:
        path.unlink(missing_ok=True)


def _partition_row_identity(
    partition_kind: str,
    row: Mapping[str, Any],
) -> tuple[int, int, int, str, str]:
    if partition_kind == PARTITION_PAGES:
        traversal = row.get("traversalIndex")
        page = row.get("pageIndex")
        if (
            isinstance(traversal, bool)
            or not isinstance(traversal, int)
            or traversal < 0
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 0
        ):
            raise SourceNativeReleaseError("acquisition-page partition key is invalid")
        return (0, traversal, page, "", "")
    source_record_id = row.get("sourceRecordId")
    if not isinstance(source_record_id, str) or not source_record_id:
        raise SourceNativeReleaseError(f"source-native {partition_kind} row lacks sourceRecordId")
    if partition_kind == PARTITION_RENDITIONS:
        rendition_id = row.get("renditionId")
        if not isinstance(rendition_id, str) or not rendition_id:
            raise SourceNativeReleaseError("rendition partition row lacks renditionId")
        return (1, 0, 0, source_record_id, rendition_id)
    return (1, 0, 0, source_record_id, "")


def _identity_bucket_for_row(partition_kind: str, row: Mapping[str, Any]) -> str:
    key = _partition_row_identity(partition_kind, row)
    if partition_kind == PARTITION_PAGES:
        return _partition_id(f"{key[1]}:{key[2]}")
    return _partition_id(key[3])


def _partition_rows(
    source: MemberSource,
    blob_source: BlobSource | None,
    partitions: Sequence[_PayloadPartition],
) -> Generator[Mapping[str, Any], None, None]:
    if not partitions:
        return
    selected = tuple(sorted(partitions, key=lambda value: value.partition_id))
    partition_kind = selected[0].partition_kind
    if any(value.partition_kind != partition_kind for value in selected):
        raise SourceNativeReleaseError("source-native partition stream mixes kinds")
    with ExitStack() as stack:
        iterators: list[Iterator[Mapping[str, Any]]] = []
        heap: list[tuple[tuple[int, int, int, str, str], int, Mapping[str, Any]]] = []
        previous_by_partition: list[tuple[int, int, int, str, str] | None] = []
        for index, partition in enumerate(selected):
            stream = stack.enter_context(_open_descriptor(source, blob_source, partition.member))
            iterator = _jsonl_rows(
                stream,
                label=partition.member.blob_ref or "external-member",
            )
            iterators.append(iterator)
            previous_by_partition.append(None)
            try:
                row = next(iterator)
            except StopIteration:
                if partition.member.record_count != 0:
                    raise SourceNativeReleaseError("source-native partition record count differs")
                continue
            key = _partition_row_identity(partition_kind, row)
            if _identity_bucket_for_row(partition_kind, row) != partition.partition_id:
                raise SourceNativeReleaseError("source-native row is assigned to the wrong identity bucket")
            previous_by_partition[index] = key
            heapq.heappush(heap, (key, index, row))
        observed_counts = [0 for _ in selected]
        previous_key: tuple[int, int, int, str, str] | None = None
        while heap:
            key, index, row = heapq.heappop(heap)
            if previous_key is not None and key <= previous_key:
                raise SourceNativeReleaseError(f"source-native {partition_kind} rows are repeated or unordered")
            previous_key = key
            observed_counts[index] += 1
            yield row
            try:
                next_row = next(iterators[index])
            except StopIteration:
                continue
            next_key = _partition_row_identity(partition_kind, next_row)
            previous_in_partition = previous_by_partition[index]
            if previous_in_partition is not None and next_key <= previous_in_partition:
                raise SourceNativeReleaseError(f"source-native {partition_kind} partition is unordered")
            if _identity_bucket_for_row(partition_kind, next_row) != selected[index].partition_id:
                raise SourceNativeReleaseError("source-native row is assigned to the wrong identity bucket")
            previous_by_partition[index] = next_key
            heapq.heappush(heap, (next_key, index, next_row))
        for partition, observed in zip(selected, observed_counts, strict=True):
            if partition.member.record_count != observed:
                raise SourceNativeReleaseError("source-native partition record count differs")


def _payload_partitions(
    receipt: Mapping[str, Any],
    by_ref: Mapping[str, MemberDescriptor],
) -> dict[str, tuple[_PayloadPartition, ...]]:
    if receipt.get("partitionPolicy") != _partition_policy():
        raise SourceNativeReleaseError("source-native partition policy differs")
    raw_partitions = receipt.get("payloadPartitions")
    if not isinstance(raw_partitions, list):
        raise SourceNativeReleaseError("source-native payload partitions are absent")
    result: dict[str, list[_PayloadPartition]] = {kind: [] for kind in PARTITION_KINDS}
    previous: tuple[str, str] | None = None
    seen_refs: set[str] = set()
    for raw in raw_partitions:
        if not isinstance(raw, Mapping):
            raise SourceNativeReleaseError("source-native payload partition is not an object")
        partition = dict(raw)
        kind = partition.get("partitionKind")
        partition_id = partition.get("partitionId")
        blob_ref = partition.get("blobRef")
        if (
            not isinstance(kind, str)
            or kind not in PARTITION_ROLES
            or not isinstance(partition_id, str)
            or len(partition_id) != 2
            or not partition_id.isascii()
            or not partition_id.isdigit()
            or int(partition_id) >= PARTITION_BUCKET_COUNT
            or not isinstance(blob_ref, str)
        ):
            raise SourceNativeReleaseError("source-native payload partition identity is invalid")
        order_key = (kind, partition_id)
        if previous is not None and order_key <= previous:
            raise SourceNativeReleaseError("source-native payload partitions are repeated or unordered")
        previous = order_key
        member = by_ref.get(blob_ref)
        if (
            member is None
            or member.role != PARTITION_ROLES[kind]
            or member.media_type != "application/x-ndjson"
            or member.byte_size != partition.get("byteSize")
            or member.record_count != partition.get("recordCount")
            or not isinstance(member.record_count, int)
            or member.record_count <= 0
            or blob_ref in seen_refs
        ):
            raise SourceNativeReleaseError("source-native payload partition differs from its manifest member")
        seen_refs.add(blob_ref)
        result[kind].append(_PayloadPartition(kind, partition_id, member))
    partition_roles = {ROLE_RECORDS, ROLE_RENDITIONS, ROLE_LEDGER}
    manifest_partition_refs = {blob_ref for blob_ref, member in by_ref.items() if member.role in partition_roles}
    if seen_refs != manifest_partition_refs:
        raise SourceNativeReleaseError("source-native receipt does not account for every payload partition")
    return {kind: tuple(values) for kind, values in result.items()}
