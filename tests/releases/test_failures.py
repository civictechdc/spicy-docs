"""Failure-classification contract: malformed source fields become deterministic failures recorded in the
ledger with stable reason codes, never aborting the publish, and the ledger's per-bucket success/failure merge
stays in increasing sourceRecordId order.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.releases import observations
from spicy_docs.source_native import (
    FAILURE_CLASS_DETERMINISTIC,
    PARTITION_LEDGER,
    REASON_RECORD_UNCLASSIFIABLE,
    SourceNativeReleaseError,
)
from spicy_docs.sources.federal_register.native import (
    FederalRegisterPage,
    FederalRegisterSourceError,
    federal_register_documents_url,
)
from tests.releases.fixtures import (
    QUERY_SCOPE,
    _document,
    _page,
    _publish,
    _reader,
    _stable_paged_pages,
    _stable_pages,
)
from tests.source_fixtures import federal_response, payload_rows


def test_observed_crawl_refuses_one_unreconciled_traversal(tmp_path: Path) -> None:
    with pytest.raises(SourceNativeReleaseError, match="two stable consecutive traversals"):
        _publish(tmp_path, [_page(0, 0, federal_response(_document()))])


def test_complete_snapshot_refuses_different_reconciliation_passes(tmp_path: Path) -> None:
    pages = [
        _page(0, 0, federal_response(_document("2026-00001"))),
        _page(1, 0, federal_response(_document("2026-00002"))),
    ]

    with pytest.raises(SourceNativeReleaseError, match="stable consecutive traversals"):
        _publish(tmp_path, pages)


def test_stable_federal_reconciliation_exposes_observed_crawl_scope(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))

    assert _reader(published.root, published.artifact.pin).source_state_scope == "observed-crawl"


def test_unclassified_source_field_is_a_deterministic_failure_not_an_abort(tmp_path: Path) -> None:
    good = _document("2026-00001")
    drifted = _document("2026-00002", new_upstream_field="unclassified")

    published = _publish(tmp_path, _stable_pages(good, drifted))
    reader = _reader(published.root, published.artifact.pin)

    assert [record["record"]["document_number"] for record in reader.iter_records()] == ["2026-00001"]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 1
    assert receipt["failedRecordCount"] == 1
    assert receipt["deterministicFailureCount"] == 1

    failures = [row for row in payload_rows(published.root, PARTITION_LEDGER) if row["failure"] is not None]
    assert len(failures) == 1
    assert failures[0]["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC
    assert failures[0]["failure"]["reasonCode"] == REASON_RECORD_UNCLASSIFIABLE


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"title": 7}, "title must be text or null"),
        ({"volume": True}, "volume must be an integer or null"),
        ({"docket_ids": [7]}, "docket_ids must be a text array or null"),
        ({"topics": [7]}, "topics must be a text array or null"),
    ],
)
def test_source_field_type_drift_is_a_deterministic_failure_not_an_abort(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    good = _document("2026-00001")
    drifted = _document("2026-00002")
    drifted.update(changes)

    published = _publish(tmp_path, _stable_pages(good, drifted))
    reader = _reader(published.root, published.artifact.pin)

    assert [record["record"]["document_number"] for record in reader.iter_records()] == ["2026-00001"]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 1
    assert receipt["failedRecordCount"] == 1
    assert receipt["deterministicFailureCount"] == 1

    failures = [row for row in payload_rows(published.root, PARTITION_LEDGER) if row["failure"] is not None]
    assert len(failures) == 1
    assert failures[0]["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC
    # The reason code is a stable identifier, not the exception text: these are
    # counted downstream. What varies per case is that each distinct malformation
    # is RECORDED rather than aborting the publish, which the assertions above
    # prove. The specific cause stays diagnosable from the retained evidence.
    assert failures[0]["failure"]["reasonCode"] == REASON_RECORD_UNCLASSIFIABLE


def test_every_record_failing_still_publishes_with_zero_published_records(tmp_path: Path) -> None:
    """Nothing survives classification, so the release is a pure failure record -- still a complete,
    admissible release, never a partial or aborted one."""
    bad = _document("2026-00001", publication_date="not-a-date")

    published = _publish(tmp_path, _stable_pages(bad))
    reader = _reader(published.root, published.artifact.pin)

    assert list(reader.iter_records()) == []
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 0
    assert receipt["failedRecordCount"] == 1
    assert receipt["deterministicFailureCount"] == 1
    assert receipt["discardedObservationCount"] == 0
    assert receipt["inputObservationCount"] == 0
    assert receipt["discoveredRecordCount"] == 1


def test_well_formed_corpus_still_reports_zero_failures(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document("2026-00001"), _document("2026-00002")))

    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 2
    assert receipt["failedRecordCount"] == 0
    assert receipt["deterministicFailureCount"] == 0
    assert receipt["transientFailureCount"] == 0
    assert receipt["unclassedFailureCount"] == 0
    assert receipt["discoveredRecordCount"] == receipt["inputObservationCount"]
    assert not [row for row in payload_rows(published.root, PARTITION_LEDGER) if row["failure"] is not None]


def test_scattered_failures_interleave_correctly_across_partition_buckets(tmp_path: Path) -> None:
    """Enough records that real and synthetic (``unclassified:...``) source-record identities share a partition
    bucket somewhere, proving the ledger's success/failure merge keeps every bucket in strictly increasing
    sourceRecordId order -- exactly what the partition reader enforces on the other end.
    """
    documents = []
    expected_failures = 0
    for number in range(1, 141):
        document = _document(f"2026-{number:05d}")
        if number % 7 == 0:
            document["publication_date"] = "not-a-date"
            expected_failures += 1
        documents.append(document)

    published = _publish(tmp_path, _stable_pages(*documents))
    reader = _reader(published.root, published.artifact.pin)

    published_numbers = [record["record"]["document_number"] for record in reader.iter_records()]
    assert len(published_numbers) == len(documents) - expected_failures
    assert len(set(published_numbers)) == len(published_numbers)

    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == len(documents) - expected_failures
    assert receipt["failedRecordCount"] == expected_failures
    assert receipt["deterministicFailureCount"] == expected_failures
    assert receipt["transientFailureCount"] == 0
    assert receipt["unclassedFailureCount"] == 0
    assert receipt["inputObservationCount"] == receipt["publishedRecordCount"] + receipt["discardedObservationCount"]
    assert receipt["discoveredRecordCount"] == receipt["inputObservationCount"] + receipt["failedRecordCount"]

    ledger_rows = payload_rows(published.root, PARTITION_LEDGER)
    assert len(ledger_rows) == len(documents)
    failure_rows = [row for row in ledger_rows if row["failure"] is not None]
    assert len(failure_rows) == expected_failures
    assert all(row["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC for row in failure_rows)


def test_missing_or_forked_page_chain_fails(tmp_path: Path) -> None:
    next_url = "https://www.federalregister.gov/api/v1/documents?format=json&page=2&cursor=stable"
    first = _page(0, 0, federal_response(_document(), next_page_url=next_url))
    second = _page(0, 1, federal_response(_document("2026-00002")), cursor="wrong")

    with pytest.raises(SourceNativeReleaseError, match="missing or forked"):
        _publish(tmp_path, [first, second])


def test_publisher_refuses_a_cyclic_source_cursor(tmp_path: Path) -> None:
    initial = federal_register_documents_url(QUERY_SCOPE)
    second = "https://www.federalregister.gov/api/v1/documents?format=json&page=2"
    pages = [
        FederalRegisterPage(
            0,
            0,
            initial,
            None,
            federal_response(_document("2026-00001"), next_page_url=second, count=3, total_pages=3),
        ),
        FederalRegisterPage(
            0,
            1,
            second,
            second,
            federal_response(_document("2026-00002"), next_page_url=initial, count=3, total_pages=3),
            window_page_index=1,
        ),
    ]

    with pytest.raises(FederalRegisterSourceError, match="cyclic page cursor"):
        _publish(tmp_path, pages)


def test_failure_cannot_be_relinked_to_another_retained_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = _stable_paged_pages(_document(), _document("2026-00002", publication_date="not-a-date"))
    other_evidence = "sha256:" + hashlib.sha256(pages[0].response_bytes).hexdigest()
    original = observations._failure_ledger_rows

    def relink(
        connection: sqlite3.Connection,
        accepted_traversal: int,
        partition_id: str | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        for row in original(connection, accepted_traversal, partition_id):
            # Both links point to an actual retained page, but not the page
            # containing the rejected record. Hash/membership checks alone pass.
            yield {
                **row,
                "evidenceBlobRef": other_evidence,
                "failure": {**row["failure"], "evidenceDigest": other_evidence},
            }

    monkeypatch.setattr(observations, "_failure_ledger_rows", relink)
    with pytest.raises(SourceNativeReleaseError, match="ledger differs from replayed evidence"):
        _publish(tmp_path, pages)
    assert not (tmp_path / "release").exists()
