"""Collection outcomes preserve the difference between empty and rejected input."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseError, SourceNativeReleaseReader
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import (
    IMPLEMENTATION_ID,
    QUERY_SCOPE,
    _collapsing_profile,
    _CountingBlobSource,
    _document,
    _publish,
    _reader,
    _signing_date_version,
    _stable_pages,
)


@pytest.mark.parametrize(
    ("valid", "rejected", "outcome"),
    [(0, 0, "empty"), (2, 0, "no-record-rejections"), (1, 1, "partial-rejection"), (0, 2, "total-rejection")],
)
def test_outcome_reports_empty_success_partial_and_total_rejection(
    tmp_path: Path, valid: int, rejected: int, outcome: str
) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(valid)]
    documents.extend(_document(f"2026-{number + valid:05d}", title=False) for number in range(rejected))
    published = _publish(tmp_path, _stable_pages(*documents))
    reader = _reader(published.root, published.artifact.pin)

    summary = reader.collection_outcome

    assert summary["recordOutcome"] == outcome
    assert summary["requestedScope"] == QUERY_SCOPE
    assert summary["sourceStateScope"] == "observed-crawl"
    assert summary["traversalAcceptance"] == "stable-consecutive-traversals"
    assert summary["acquisitionPolicy"] == FEDERAL_REGISTER_PROFILE.acquisition_policy(QUERY_SCOPE)
    assert summary["acquisitionPolicy"]["strategy"] == "date-window-cap-split-stable-reconciliation"
    assert summary["acquisitionPolicy"]["initialQueryScope"] == QUERY_SCOPE
    assert summary["acquisitionPolicyVersion"] == "1.2"
    for field in ("acquisitionPolicyId", "acquisitionPolicyVersion", "acquisitionPolicyDigest"):
        assert summary[field] == published.artifact.root["spec"][field]
    assert summary["discoveredRecordCount"] == valid + rejected
    assert summary["inputObservationCount"] == summary["publishedRecordCount"] == valid
    assert summary["discardedObservationCount"] == 0
    assert summary["failedRecordCount"] == summary["deterministicFailureCount"] == rejected
    assert summary["transientFailureCount"] == summary["unclassedFailureCount"] == 0
    assert summary["reconciliationPassCount"] == 2
    assert summary["warnings"] == []
    failures = list(reader.iter_failures())
    assert len(failures) == rejected
    assert all(row["failure"]["class"] == "deterministic" for row in failures)
    assert all(set(row) == {"sourceRecordId", "failure", "observationRef", "evidenceBlobRef"} for row in failures)


def test_outcome_counts_discarded_observations_separately_from_record_rejections(tmp_path: Path) -> None:
    profile = _collapsing_profile(observation_version=_signing_date_version)
    pages = _stable_pages(
        _document(signing_date="2026-08-23"),
        _document(signing_date="2026-08-24"),
        _document(signing_date="2026-08-25"),
        _document("2026-00002", title=False),
    )
    published = _publish(tmp_path, pages, profile=profile)

    summary = _reader(published.root, published.artifact.pin, profile=profile).collection_outcome

    assert summary["recordOutcome"] == "partial-rejection"
    assert summary["discoveredRecordCount"] == 4
    assert summary["inputObservationCount"] == 3
    assert summary["publishedRecordCount"] == 1
    assert summary["discardedObservationCount"] == 2
    assert summary["failedRecordCount"] == 1


def test_outcome_is_a_fresh_mapping_and_does_not_reopen_payloads(tmp_path: Path, monkeypatch) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader = _reader(published.root, published.artifact.pin)

    def no_open(_blob_ref):
        pytest.fail("reading the summary must not reopen payloads")

    monkeypatch.setattr(reader._blob_source, "open", no_open)
    changed = reader.collection_outcome
    changed["requestedScope"]["publishedFrom"] = "1990-01-01"
    changed["warnings"].append({"code": "injected", "message": "caller mutation"})
    changed["publishedRecordCount"] = 9
    changed["acquisitionPolicy"]["initialQueryScope"]["publishedFrom"] = "1990-01-01"
    changed["acquisitionPolicy"]["coverageLimits"].clear()

    assert reader.collection_outcome["requestedScope"] == QUERY_SCOPE
    assert reader.collection_outcome["warnings"] == []
    assert reader.collection_outcome["publishedRecordCount"] == 1
    assert reader.collection_outcome["acquisitionPolicy"] == FEDERAL_REGISTER_PROFILE.acquisition_policy(QUERY_SCOPE)


def test_reader_refuses_to_describe_admitted_release_with_changed_policy_values(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages())
    changed_profile = replace(
        FEDERAL_REGISTER_PROFILE,
        acquisition_policy=lambda scope: {
            **FEDERAL_REGISTER_PROFILE.acquisition_policy(scope),
            "coverageLimits": ["An incorrect frozen snapshot claim."],
        },
    )

    # Identity/version still match. The reader must bind displayed policy values
    # to the release's digest even though reader admission does no source replay.
    with pytest.raises(SourceNativeReleaseError, match="acquisition-policy digest differs"):
        _reader(published.root, published.artifact.pin, profile=changed_profile)


@pytest.mark.parametrize("reject", [False, True])
def test_zero_limit_and_zero_sealed_failures_do_not_open_ledger(tmp_path: Path, monkeypatch, reject: bool) -> None:
    published = _publish(tmp_path, _stable_pages(_document(title=False) if reject else _document()))
    reader = _reader(published.root, published.artifact.pin)

    def no_open(_blob_ref):
        pytest.fail("no failure rows requested or sealed; ledger must remain closed")

    monkeypatch.setattr(reader._blob_source, "open", no_open)
    assert list(reader.iter_failures(limit=0)) == []
    if not reject:
        assert list(reader.iter_failures()) == []


@pytest.mark.parametrize("limit", [-1, True, 1.5, "1", None])
def test_failure_limit_requires_a_nonnegative_integer(tmp_path: Path, limit: object) -> None:
    published = _publish(tmp_path, _stable_pages())
    reader = _reader(published.root, published.artifact.pin)

    with pytest.raises(ValueError, match="failure limit must be a non-negative integer"):
        list(reader.iter_failures(limit=limit))


def test_failure_iterator_stops_at_limit_and_closes_its_stream(tmp_path: Path, monkeypatch) -> None:
    published = _publish(tmp_path, _stable_pages(_document(title=False)))
    reader = _reader(published.root, published.artifact.pin)
    closed = []
    failure = {"sourceRecordId": "rejected", "failure": {"class": "deterministic"}}

    def rows(*_args):
        try:
            yield {"sourceRecordId": "accepted", "failure": None}
            yield failure
            pytest.fail("failure iteration read beyond its requested limit")
        finally:
            closed.append(True)

    monkeypatch.setattr("spicy_docs.releases.reader._partition_rows", rows)

    assert list(reader.iter_failures(limit=1)) == [failure]
    assert closed == [True]


def test_failure_iteration_is_sorted_bounded_and_closes_partition_streams(tmp_path: Path) -> None:
    documents = [_document(f"2026-{number:05d}", title=False) for number in range(1, 141)]
    published = _publish(tmp_path, _stable_pages(*documents))
    counting = _CountingBlobSource(LocalSourceNativeBlobStore(tmp_path / "blobs"))
    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=counting,
        profile=FEDERAL_REGISTER_PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )

    sample = list(reader.iter_failures())
    complete = list(reader.iter_failures(limit=200))
    assert len(sample) == 100
    assert len(complete) == 140
    assert sample == complete[:100]
    assert [row["sourceRecordId"] for row in complete] == sorted(row["sourceRecordId"] for row in complete)
    assert 1 < counting.maximum <= 64
    assert counting.active == 0

    partial = reader.iter_failures(limit=10)
    assert next(partial) == complete[0]
    assert counting.active > 0
    partial.close()
    assert counting.active == 0
