"""Releases: reading behavior."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from rulespec_artifacts import (
    ArtifactVerificationError,
    LocalMemberSource,
)

from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import (
    IMPLEMENTATION_ID,
    PRODUCER,
    QUERY_SCOPE,
    _CountingBlobSource,
    _document,
    _publish,
    _reader,
    _stable_pages,
)


def test_source_build_refuses_a_historical_producer() -> None:
    with pytest.raises(SourceNativeReleaseError, match="producer product must be spicy-docs"):
        SourceNativeReleaseBuild(
            query_scope=QUERY_SCOPE,
            producer=replace(PRODUCER, product="spicy-regs"),
            started_at="2026-08-25T00:00:00Z",
        )


def test_reader_holds_at_most_the_fixed_bucket_count_of_streams(tmp_path: Path) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(1, 257)]
    published = _publish(tmp_path, _stable_pages(*documents))
    counting = _CountingBlobSource(LocalSourceNativeBlobStore(tmp_path / "blobs"))
    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=counting,
        profile=FEDERAL_REGISTER_PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )

    assert len(list(reader.iter_records())) == len(documents)
    assert 1 < counting.maximum <= 64
    assert counting.active == 0


def test_changed_member_fails_before_reader_yields(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    record_partition = next(value for value in receipt["payloadPartitions"] if value["partitionKind"] == "records")
    records_path = tmp_path / "blobs" / "sha256" / record_partition["blobRef"][7:]
    records_path.write_bytes(records_path.read_bytes().replace(b"source-native rule", b"changed source rule"))

    with pytest.raises(ArtifactVerificationError, match="invalid.member-digest"):
        _reader(published.root, published.artifact.pin)


def test_records_and_renditions_stream_across_fixed_identity_buckets(
    tmp_path: Path,
) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(3, 0, -1)]
    published = _publish(tmp_path, _stable_pages(*documents))
    reader = _reader(published.root, published.artifact.pin)

    assert [row["sourceRecordId"] for row in reader.iter_records()] == [
        "2026-00001@2026-08-25",
        "2026-00002@2026-08-25",
        "2026-00003@2026-08-25",
    ]
    assert len(list(reader.iter_renditions())) == 12
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["partitionPolicy"] == {
        "algorithm": "sha256-utf8-modulo",
        "bucketCount": 64,
        "identityEncoding": "utf-8",
    }
    assert sorted(path.name for path in (published.root / "records").iterdir()) == ["scopes.jsonl"]
    assert {value["partitionKind"] for value in receipt["payloadPartitions"]} >= {"records", "renditions"}


def test_reader_requires_explicit_verifier_allowlist(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))

    with pytest.raises(SourceNativeReleaseError, match="at least one verifier"):
        SourceNativeReleaseReader(
            LocalMemberSource(published.root),
            blob_source=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            profile=FEDERAL_REGISTER_PROFILE,
            expected_pin=published.artifact.pin,
            accepted_verifier_implementation_ids=frozenset(),
        )
    with pytest.raises(SourceNativeReleaseError, match="not accepted"):
        SourceNativeReleaseReader(
            LocalMemberSource(published.root),
            blob_source=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            profile=FEDERAL_REGISTER_PROFILE,
            expected_pin=published.artifact.pin,
            accepted_verifier_implementation_ids=frozenset({"git+https://example.test/other@" + "b" * 40}),
        )
