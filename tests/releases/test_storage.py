"""Releases: storage behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from rulespec_artifacts import (
    ArtifactVerificationError,
    BlobIntegrityError,
    BlobLimitError,
    LocalMemberSource,
    MemberSourceError,
    admit_artifact,
)

from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from spicy_docs.storage.publication import ImmutablePublicationError
from tests.releases.fixtures import (
    _document,
    _publish,
    _reader,
    _stable_pages,
)


def test_blob_store_refuses_corrupt_existing_content(tmp_path: Path) -> None:
    payload = b"digest-addressed source bytes"
    blob_ref = "sha256:" + hashlib.sha256(payload).hexdigest()
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")

    write = store.put_blob(blob_ref, len(payload), (payload,))
    assert write.reused is False
    assert write.bytes_written == len(payload)
    path = tmp_path / "blobs" / "sha256" / blob_ref[7:]
    path.write_bytes(b"x" * len(payload))

    with pytest.raises(ImmutablePublicationError, match="content identity"):
        store.put_blob(blob_ref, len(payload), (payload,))


def test_blob_store_reuses_verified_bytes_without_consuming_input(tmp_path: Path) -> None:
    payload = b"shared physical writer, source receipt"
    blob_ref = "sha256:" + hashlib.sha256(payload).hexdigest()
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    store.put_blob(blob_ref, len(payload), (payload,))

    def unexpected_input():
        pytest.fail("known verified bytes should be reused before fetching input")
        yield b""

    write = store.put_blob(blob_ref, len(payload), unexpected_input())
    assert (write.blob_ref, write.byte_size, write.reused, write.bytes_written) == (blob_ref, len(payload), True, 0)
    assert (store.root / "sha256" / blob_ref[7:]).read_bytes() == payload
    with store.open(blob_ref) as stream:
        assert stream.read() == payload


@pytest.mark.parametrize("payload, error_type", [(b"longer", BlobLimitError), (b"x", BlobIntegrityError)])
def test_blob_store_maps_shared_bound_and_integrity_errors(
    tmp_path: Path, payload: bytes, error_type: type[ValueError]
) -> None:
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    blob_ref = "sha256:" + hashlib.sha256(b"ok").hexdigest()
    with pytest.raises(ImmutablePublicationError) as refused:
        store.put_blob(blob_ref, 2, [payload])
    assert isinstance(refused.value.__cause__, error_type)
    assert list((store.root / ".pending").iterdir()) == []
    assert list((store.root / "sha256").iterdir()) == []


def test_read_only_blob_store_open_does_not_create_missing_layout(
    tmp_path: Path,
) -> None:
    root = tmp_path / "blobs"
    root.mkdir()

    with pytest.raises(ValueError, match="layout is missing"):
        LocalSourceNativeBlobStore(root, create=False)

    assert list(root.iterdir()) == []


def test_blob_store_reader_refuses_a_replaced_root(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalSourceNativeBlobStore(root)
    payload = b"pinned source-native bytes"
    blob_ref = "sha256:" + hashlib.sha256(payload).hexdigest()
    store.put_blob(blob_ref, len(payload), (payload,))
    retained = tmp_path / "retained-blobs"
    root.rename(retained)
    LocalSourceNativeBlobStore(root)

    with pytest.raises(MemberSourceError, match="artifact root changed"), store.open(blob_ref):
        pytest.fail("a replaced root must fail before yielding bytes")

    assert (retained / "sha256" / blob_ref[7:]).read_bytes() == payload


@pytest.mark.parametrize("child_name", ["sha256", ".pending"])
def test_blob_store_refuses_internal_symlink_layout(
    tmp_path: Path,
    child_name: str,
) -> None:
    root = tmp_path / "blobs"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")
    (root / child_name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="non-symlink directory"):
        LocalSourceNativeBlobStore(root)

    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text() == "unchanged"


@pytest.mark.parametrize("child_name", ["sha256", ".pending"])
def test_blob_store_refuses_replaced_internal_directory(
    tmp_path: Path,
    child_name: str,
) -> None:
    root = tmp_path / "blobs"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LocalSourceNativeBlobStore(root)
    original = root / f"{child_name}.original"
    (root / child_name).rename(original)
    (root / child_name).symlink_to(outside, target_is_directory=True)
    payload = b"must remain inside the admitted store"
    blob_ref = "sha256:" + hashlib.sha256(payload).hexdigest()

    with pytest.raises(ValueError, match="non-symlink directory"):
        store.put_blob(blob_ref, len(payload), (payload,))

    assert list(outside.iterdir()) == []
    assert list(original.iterdir()) == []


def test_external_payloads_require_injected_blob_source(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))

    with pytest.raises(ArtifactVerificationError, match="injected BlobSource"):
        admit_artifact(LocalMemberSource(published.root))


@pytest.mark.parametrize("mutation", ["same-size", "changed-size"])
def test_blob_mutation_after_reader_admission_fails_before_a_row_is_returned(
    tmp_path: Path,
    mutation: str,
) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader = _reader(published.root, published.artifact.pin)
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    record_partition = next(value for value in receipt["payloadPartitions"] if value["partitionKind"] == "records")
    records_path = tmp_path / "blobs" / "sha256" / record_partition["blobRef"][7:]
    payload = records_path.read_bytes()
    records_path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:] if mutation == "same-size" else payload + b"\n")

    with pytest.raises(ArtifactVerificationError, match="invalid.member-digest"):
        next(reader.iter_records())
