"""Evidence access contract: point and bulk reads stay tied to admitted membership and the selected
observation, open only the matching identity bucket, verify digest and size at read time, and close every
stream.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import (
    MAX_EVIDENCE_BYTES,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native.profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import (
    IMPLEMENTATION_ID,
    _build,
    _collapsing_profile,
    _completed_at,
    _document,
    _publish,
    _reader,
    _signing_date_version,
    _stable_paged_pages,
    _stable_pages,
)
from tests.source_fixtures import federal_response


class _ReadTrackingStream(BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.requests: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.requests.append(size)
        return super().read(size)


class _MemoryBlobs:
    """A custom blob source deliberately makes no integrity guarantees of its own."""

    def __init__(self, directory: Path) -> None:
        self.values = {f"sha256:{path.name}": path.read_bytes() for path in (directory / "sha256").iterdir()}
        self.opened: list[tuple[str, _ReadTrackingStream]] = []

    @contextmanager
    def open(self, blob_ref: str):
        with _ReadTrackingStream(self.values[blob_ref]) as stream:
            self.opened.append((blob_ref, stream))
            yield stream


def _memory_reader(published, directory: Path):
    blobs = _MemoryBlobs(directory / "blobs")
    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=blobs,
        profile=FEDERAL_REGISTER_PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
    blobs.opened.clear()  # The checks below measure access after admission.
    return reader, blobs


def test_record_evidence_reads_only_its_bucket_and_closes_before_returning(tmp_path: Path) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(256)]
    published = _publish(tmp_path, _stable_pages(*documents))
    reader, blobs = _memory_reader(published, tmp_path)
    identity = "2026-00000@2026-08-25"

    evidence = reader.record_evidence(identity)

    assert evidence is not None
    assert evidence == {
        "sourceRecordId": identity,
        "observationRef": {"sourceRecordId": identity},
        "evidenceBlobRef": "sha256:" + hashlib.sha256(federal_response(*documents)).hexdigest(),
        "failure": None,
    }
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    expected_bucket = f"{int.from_bytes(hashlib.sha256(identity.encode()).digest(), 'big') % 64:02d}"
    partition = next(
        value
        for value in receipt["payloadPartitions"]
        if value["partitionKind"] == "acquisition-records" and value["partitionId"] == expected_bucket
    )
    assert len(blobs.opened) == 1
    assert blobs.opened[0][0] == partition["blobRef"]
    assert blobs.opened[0][1].closed
    evidence["observationRef"]["sourceRecordId"] = "caller mutation"
    assert reader.record_evidence(identity)["observationRef"] == {"sourceRecordId": identity}


def test_bulk_record_evidence_reads_each_partition_once_and_matches_record_order(tmp_path: Path, monkeypatch) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(256)]
    published = _publish(tmp_path, _stable_pages(*documents, _document(title=False)))
    reader, blobs = _memory_reader(published, tmp_path)
    identities = [row["sourceRecordId"] for row in reader.iter_records()]
    blobs.opened.clear()

    def no_point_lookup(*args):
        pytest.fail("bulk evidence must not repeat point lookups")

    monkeypatch.setattr(reader, "record_evidence", no_point_lookup)
    evidence = list(reader.iter_record_evidence())

    assert [row["sourceRecordId"] for row in evidence] == identities
    expected_ref = "sha256:" + hashlib.sha256(federal_response(*documents, _document(title=False))).hexdigest()
    assert all(
        row
        == {
            "sourceRecordId": identity,
            "observationRef": {"sourceRecordId": identity},
            "evidenceBlobRef": expected_ref,
            "failure": None,
        }
        for identity, row in zip(identities, evidence, strict=True)
    )
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    expected = {
        item["blobRef"] for item in receipt["payloadPartitions"] if item["partitionKind"] == "acquisition-records"
    }
    assert {ref for ref, _ in blobs.opened} == expected
    assert len(blobs.opened) == len(expected)
    assert all(stream.closed for _, stream in blobs.opened)


def test_bulk_record_evidence_closes_when_consumer_stops_early(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(*(_document(f"2026-{n:05d}") for n in range(70))))
    reader, blobs = _memory_reader(published, tmp_path)
    rows = reader.iter_record_evidence()
    assert next(rows)["failure"] is None
    assert blobs.opened
    rows.close()
    assert all(stream.closed for _, stream in blobs.opened)


@pytest.mark.parametrize("documents", [(), (_document(title=False),)])
def test_bulk_record_evidence_empty_and_failure_only_controls(tmp_path: Path, documents) -> None:
    published = _publish(tmp_path, _stable_pages(*documents))
    reader, blobs = _memory_reader(published, tmp_path)
    assert list(reader.iter_record_evidence()) == []
    assert all(stream.closed for _, stream in blobs.opened)


@pytest.mark.parametrize("bulk", [False, True])
def test_record_evidence_returns_selected_observation_not_discarded_ones(tmp_path: Path, bulk: bool) -> None:
    profile = _collapsing_profile(observation_version=_signing_date_version)
    old, selected = _document(signing_date="2026-08-24"), _document(signing_date="2026-08-25")
    pages = _stable_paged_pages(old, selected)
    published = _publish(tmp_path, pages, profile=profile)
    reader = _reader(published.root, published.artifact.pin, profile=profile)

    if bulk:
        (evidence,) = reader.iter_record_evidence()
    else:
        evidence = reader.record_evidence("2026-00001@2026-08-25")

    assert evidence is not None
    assert evidence["evidenceBlobRef"] == "sha256:" + hashlib.sha256(pages[1].response_bytes).hexdigest()
    assert reader.read_evidence(evidence["evidenceBlobRef"]) == pages[1].response_bytes
    assert reader.collection_outcome["discardedObservationCount"] == 1


@pytest.mark.parametrize("change", ["wrong-bucket", "unordered"])
@pytest.mark.parametrize("bulk", [False, True])
def test_record_evidence_keeps_partition_row_checks(tmp_path: Path, change: str, bulk: bool) -> None:
    published = _publish(tmp_path, _stable_pages(*(_document(f"2026-{n:05d}") for n in range(256))))
    reader, blobs = _memory_reader(published, tmp_path)
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    partition = next(
        value
        for value in receipt["payloadPartitions"]
        if value["partitionKind"] == "acquisition-records" and value["recordCount"] >= 2
    )

    def bucket(identity):
        return f"{int.from_bytes(hashlib.sha256(identity.encode()).digest(), 'big') % 64:02d}"

    # A later, absent identity forces the scan past both changed rows.
    identity = next(f"zz-query-{n}" for n in range(10_000) if bucket(f"zz-query-{n}") == partition["partitionId"])
    lines = blobs.values[partition["blobRef"]].splitlines()
    if change == "wrong-bucket":
        row = json.loads(lines[0])
        row["sourceRecordId"] = next(
            f"wrong-{n}" for n in range(64) if bucket(f"wrong-{n}") != partition["partitionId"]
        )
        lines[0] = json.dumps(row).encode()
    else:
        lines[0], lines[1] = lines[1], lines[0]
    blobs.values[partition["blobRef"]] = b"\n".join(lines) + b"\n"

    with pytest.raises(SourceNativeReleaseError, match="wrong identity bucket|partition is unordered"):
        list(reader.iter_record_evidence()) if bulk else reader.record_evidence(identity)
    if not bulk:
        assert len(blobs.opened) == 1
    assert all(stream.closed for _, stream in blobs.opened)


def test_failure_only_and_unrequested_ids_have_no_published_success(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document(title=False)))
    reader, blobs = _memory_reader(published, tmp_path)
    failure = next(reader.iter_failures())

    assert reader.record_evidence(failure["sourceRecordId"]) is None
    assert reader.record_evidence("never-requested") is None
    assert reader.read_evidence(failure["evidenceBlobRef"]) == federal_response(_document(title=False))
    assert all(stream.closed for _, stream in blobs.opened)


def test_record_evidence_with_no_record_partitions_does_not_open_blobs(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages())
    reader, blobs = _memory_reader(published, tmp_path)

    assert reader.record_evidence("not-published") is None
    assert blobs.opened == []


@pytest.mark.parametrize("identity", ["", None, 1, True])
def test_record_evidence_requires_a_nonempty_text_identity(tmp_path: Path, identity) -> None:
    published = _publish(tmp_path, _stable_pages())
    reader, blobs = _memory_reader(published, tmp_path)
    with pytest.raises(SourceNativeReleaseError, match="identity must be nonempty text"):
        reader.record_evidence(identity)
    assert blobs.opened == []


def test_read_evidence_refuses_unknown_or_other_role_before_storage_access(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    record_ref = next(value["blobRef"] for value in receipt["payloadPartitions"] if value["partitionKind"] == "records")
    for ref in ("sha256:" + "0" * 64, record_ref, "../../arbitrary-file", None, []):
        with pytest.raises(SourceNativeReleaseError, match="not an admitted source evidence member"):
            reader.read_evidence(ref)
    assert blobs.opened == []


@pytest.mark.parametrize("limit", [-1, True, 1.5, "20", None, MAX_EVIDENCE_BYTES + 1])
def test_read_evidence_requires_a_bounded_integer_limit(tmp_path: Path, limit) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    evidence = reader.record_evidence("2026-00001@2026-08-25")
    blobs.opened.clear()
    with pytest.raises(ValueError, match="evidence byte limit must be an integer"):
        reader.read_evidence(evidence["evidenceBlobRef"], max_bytes=limit)
    assert blobs.opened == []


@pytest.mark.parametrize("limit", [0, 1])
def test_read_evidence_refuses_declared_oversize_before_opening(tmp_path: Path, limit: int) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    evidence = reader.record_evidence("2026-00001@2026-08-25")
    blobs.opened.clear()
    with pytest.raises(SourceNativeReleaseError, match="exceeds the requested byte limit"):
        reader.read_evidence(evidence["evidenceBlobRef"], max_bytes=limit)
    assert blobs.opened == []


@pytest.mark.parametrize("change", ["same-size", "shorter", "longer", "over-limit"])
def test_read_evidence_rechecks_changed_bytes_from_custom_store_and_closes(tmp_path: Path, change: str) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    evidence = reader.record_evidence("2026-00001@2026-08-25")
    ref = evidence["evidenceBlobRef"]
    original = blobs.values[ref]
    limit = len(original) + 1
    replacements = {
        "same-size": original[:-1] + b"!",
        "shorter": original[:-1],
        "longer": original + b"!",
        "over-limit": original + b"!!!",
    }
    blobs.values[ref] = replacements[change]
    blobs.opened.clear()

    with pytest.raises(SourceNativeReleaseError, match="digest differs|size differs|exceeds the requested byte limit"):
        reader.read_evidence(ref, max_bytes=limit)

    assert len(blobs.opened) == 1
    expected_reads = [limit + 1]
    if len(replacements[change]) <= limit:
        expected_reads.append(limit + 1 - len(replacements[change]))
    assert blobs.opened[0][1].requests == expected_reads
    assert blobs.opened[0][1].closed


def test_read_evidence_drains_valid_short_reads_within_the_bound(tmp_path: Path, monkeypatch) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    evidence = reader.record_evidence("2026-00001@2026-08-25")
    ref = evidence["evidenceBlobRef"]
    original = blobs.values[ref]
    blobs.opened.clear()

    def short_read(self, size=-1):
        self.requests.append(size)
        return BytesIO.read(self, min(size, 7))

    monkeypatch.setattr(_ReadTrackingStream, "read", short_read)

    assert reader.read_evidence(ref, max_bytes=len(original)) == original
    ((opened_ref, stream),) = blobs.opened
    assert opened_ref == ref
    assert len(stream.requests) > 1
    assert stream.requests[-1] == 1  # Read to EOF even when declared bytes arrived.
    assert all(0 < size <= len(original) + 1 for size in stream.requests)
    assert stream.closed


def test_read_evidence_closes_storage_when_read_raises(tmp_path: Path, monkeypatch) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader, blobs = _memory_reader(published, tmp_path)
    evidence = reader.record_evidence("2026-00001@2026-08-25")
    blobs.opened.clear()
    error = OSError("injected read failure")

    def refuse_read(self, size=-1):
        raise error

    monkeypatch.setattr(_ReadTrackingStream, "read", refuse_read)
    with pytest.raises(OSError) as caught:
        reader.read_evidence(evidence["evidenceBlobRef"])
    assert caught.value is error
    assert blobs.opened[0][1].closed


def test_zero_byte_limit_can_read_admitted_empty_evidence(tmp_path: Path) -> None:
    # This test profile defines empty bytes as an empty response. The real
    # Federal Register parser still refuses empty response bytes.
    profile = replace(FEDERAL_REGISTER_PROFILE, parse_page_response=lambda raw: json.loads(federal_response()))
    pages = [
        SimpleNamespace(**{**asdict(page), "response_bytes": b""}, evidence_media_type="application/json")
        for page in _stable_pages()
    ]
    published = SourceNativeReleasePublisher(
        profile, blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"), clock=_completed_at
    ).publish(pages, build=_build(), destination=tmp_path / "release")
    reader = _reader(published.root, published.artifact.pin, profile=profile)

    assert reader.read_evidence("sha256:" + hashlib.sha256(b"").hexdigest(), max_bytes=0) == b""
