"""Releases: publication behavior."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from spicy_docs.source_native import (
    FAILURE_CLASS_DETERMINISTIC,
    PARTITION_LEDGER,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
)
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import (
    FederalRegisterPage,
    federal_register_source_record_id,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from spicy_docs.storage.publication import ImmutablePublicationError
from tests.releases.fixtures import (
    PRODUCER,
    QUERY_SCOPE,
    _build,
    _collapsing_profile,
    _completed_at,
    _document,
    _page,
    _partition_map,
    _publish,
    _reader,
    _stable_paged_pages,
    _stable_pages,
)
from tests.source_fixtures import federal_response, payload_rows


def test_stable_release_preserves_source_value_and_streams(tmp_path: Path) -> None:
    published = _publish(tmp_path, _stable_pages(_document()))
    reader = _reader(published.root, published.artifact.pin)

    records = list(reader.iter_records())
    assert reader.pin == published.artifact.pin
    assert reader.source_state_scope == "observed-crawl"
    assert reader.source_system_id == "https://www.federalregister.gov/api/v1"
    assert reader.source_system_version == "v1"
    assert reader.source_state_digest.startswith("sha256:")
    assert reader.source_native_schema_set_digest.startswith("sha256:")
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["startedAt"] == "2026-08-25T00:00:00Z"
    assert receipt["completedAt"] == "2026-08-25T00:00:01Z"
    assert "byteMeasurements" not in receipt
    measurements = published.byte_measurements
    assert measurements["publicationBytesWritten"] == sum(
        path.stat().st_size for path in published.root.rglob("*") if path.is_file()
    )
    payload_bytes = sum(path.stat().st_size for path in (tmp_path / "blobs" / "sha256").iterdir())
    assert measurements["payloadBytesRead"] == payload_bytes
    assert measurements["payloadBytesWritten"] == payload_bytes
    assert measurements["payloadBytesReused"] == 0
    assert records[0]["record"]["agencies"] == []
    assert records[0]["record"]["topics"] == []
    assert records[0]["record"]["regulation_id_numbers"] == ["not-a-rin"]
    assert records[0]["fieldDiagnostics"] == [
        {
            "code": "malformed-rin",
            "field": "regulation_id_numbers",
            "value": "not-a-rin",
        }
    ]

    renditions = list(reader.iter_renditions())
    assert [(row["sourceField"], row["locator"], row["mediaType"]) for row in renditions] == [
        ("body_html_url", None, "text/html"),
        ("full_text_xml_url", None, "application/xml"),
        ("html_url", "https://www.federalregister.gov/d/2026-00001", "text/html"),
        ("pdf_url", None, "application/pdf"),
    ]


def test_build_refuses_an_unrecognized_producer_product() -> None:
    with pytest.raises(SourceNativeReleaseError, match="producer product must be spicy-docs"):
        SourceNativeReleaseBuild(
            query_scope=QUERY_SCOPE,
            producer=replace(PRODUCER, product="spicy-widgets"),
            started_at="2026-08-25T00:00:00Z",
        )


def test_identical_evidence_pages_keep_distinct_page_inventories(
    tmp_path: Path,
) -> None:
    response = federal_response(_document())
    pages = [
        FederalRegisterPage(
            traversal_index=traversal,
            page_index=window,
            request_key=f"https://example.test/window/{window}",
            source_cursor=None,
            response_bytes=response,
            window_index=window,
            window_page_index=0,
        )
        for traversal in range(2)
        for window in range(2)
    ]
    profile = _collapsing_profile()
    published = _publish(tmp_path, pages, profile=profile)
    page_rows = sorted(
        payload_rows(published.root, "acquisition-pages"),
        key=lambda row: (row["traversalIndex"], row["pageIndex"]),
    )

    assert len({row["evidenceBlobRef"] for row in page_rows}) == 1
    assert [len(row["discoveredRecords"]) for row in page_rows] == [1, 1, 1, 1]
    reader = _reader(published.root, published.artifact.pin, profile=profile)
    assert len(list(reader.iter_records())) == 1


def test_source_native_record_preserves_predecessor_source_facts(tmp_path: Path) -> None:
    document = _document(
        agencies=[
            {
                "name": "Environmental Protection Agency",
                "raw_name": "ENVIRONMENTAL PROTECTION AGENCY",
                "slug": "environmental-protection-agency",
            }
        ],
        body_html_url="https://www.federalregister.gov/documents/full_text/html/2026-00001.html",
        full_text_xml_url="https://www.federalregister.gov/documents/full_text/xml/2026/08/25/2026-00001.xml",
        docket_ids=["EPA-HQ-OAR-2026-0001"],
        pdf_url="https://www.govinfo.gov/content/pkg/FR-2026-08-25/pdf/2026-00001.pdf",
        regulation_id_numbers=["2060-AV12"],
        title="Native Federal Register title",
        topics=["Air pollution control"],
        type="Notice",
    )

    published = _publish(tmp_path, _stable_pages(document))
    reader = _reader(published.root, published.artifact.pin)

    assert next(iter(reader.iter_records()))["record"] == document
    assert [(row["sourceField"], row["locator"]) for row in reader.iter_renditions()] == [
        ("body_html_url", document["body_html_url"]),
        ("full_text_xml_url", document["full_text_xml_url"]),
        ("html_url", document["html_url"]),
        ("pdf_url", document["pdf_url"]),
    ]


@pytest.mark.parametrize("xml_locator", ["", 17, [], {}])
def test_invalid_xml_locator_is_retained_as_a_record_failure(tmp_path: Path, xml_locator: object) -> None:
    published = _publish(tmp_path, _stable_pages(_document(full_text_xml_url=xml_locator)))
    reader = _reader(published.root, published.artifact.pin)
    assert list(reader.iter_records()) == []
    assert list(reader.iter_renditions()) == []
    failures = [row for row in payload_rows(published.root, PARTITION_LEDGER) if row["failure"] is not None]
    assert len(failures) == 1
    assert failures[0]["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC
    assert failures[0]["failure"]["evidenceDigest"].startswith("sha256:")


@pytest.mark.parametrize("publication_date", [None, "", "not-a-date", "2026-08-25T00:00:00Z"])
def test_malformed_publication_date_is_a_deterministic_failure_not_an_abort(
    tmp_path: Path, publication_date: object
) -> None:
    """SD-22 step 2: a record that fails classification is deterministic --
    the identical bytes reparse identically, so retrying changes nothing --
    and no longer aborts the whole publish. This is the defect step 2 fixes:
    one unparseable date once aborted a 205,696-document agency publish.
    Publication completes, the malformed record contributes no published
    record, and its failure is recorded in the ledger with both receipt
    count invariants intact.
    """
    good = _document("2026-00001")
    bad = _document("2026-00002", publication_date=publication_date)
    published = _publish(tmp_path, _stable_pages(good, bad))
    reader = _reader(published.root, published.artifact.pin)

    assert [record["record"]["document_number"] for record in reader.iter_records()] == ["2026-00001"]

    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 1
    assert receipt["failedRecordCount"] == 1
    assert receipt["deterministicFailureCount"] == 1
    assert receipt["transientFailureCount"] == 0
    assert receipt["unclassedFailureCount"] == 0
    # inputObservationCount == publishedRecordCount + discardedObservationCount:
    # a classification failure never becomes an input observation at all, so
    # it is neither published nor discarded -- it is absent from both sides
    # of this equation, which is why it needs no term of its own here.
    assert receipt["inputObservationCount"] == receipt["publishedRecordCount"] + receipt["discardedObservationCount"]
    # discoveredRecordCount == inputObservationCount + failedRecordCount:
    # everything discovered in evidence either became an input observation
    # or failed outright before it could.
    assert receipt["discoveredRecordCount"] == receipt["inputObservationCount"] + receipt["failedRecordCount"]

    failures = [row for row in payload_rows(published.root, PARTITION_LEDGER) if row["failure"] is not None]
    assert len(failures) == 1
    assert failures[0]["failure"]["class"] == FAILURE_CLASS_DETERMINISTIC
    assert failures[0]["failure"]["reasonCode"]
    assert failures[0]["failure"]["evidenceDigest"].startswith("sha256:")


def test_acquisition_exception_cannot_publish_partial_release(tmp_path: Path) -> None:
    destination = tmp_path / "interrupted"

    def interrupted_pages() -> Iterator[FederalRegisterPage]:
        yield _page(0, 0, federal_response(_document()))
        raise RuntimeError("source stopped")

    with pytest.raises(RuntimeError, match="source stopped"):
        SourceNativeReleasePublisher(
            FEDERAL_REGISTER_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            interrupted_pages(),
            build=_build(),
            destination=destination,
        )

    assert not destination.exists()
    orphan_refs = {path.name for path in (tmp_path / "blobs" / "sha256").iterdir()}
    assert len(orphan_refs) == 1

    recovered = _publish(tmp_path, _stable_pages(_document()))
    assert recovered.byte_measurements["payloadBytesReused"] > 0
    assert orphan_refs <= {path.name for path in (tmp_path / "blobs" / "sha256").iterdir()}


def test_successor_reuses_unchanged_buckets_and_writes_only_new_payloads(
    tmp_path: Path,
) -> None:
    documents = [_document(f"2026-{number:05d}") for number in range(1, 13)]
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")

    initial = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=store,
        clock=_completed_at,
    ).publish(
        _stable_paged_pages(*documents),
        build=_build(),
        destination=tmp_path / "initial",
    )
    initial_files = {path.name: path.stat().st_size for path in (tmp_path / "blobs" / "sha256").iterdir()}

    changed_index = 5
    changed_documents = [dict(value) for value in documents]
    changed_documents[changed_index]["title"] = "One changed source row"
    successor = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=store,
        clock=_completed_at,
    ).publish(
        _stable_paged_pages(*changed_documents),
        build=_build(),
        destination=tmp_path / "successor",
    )

    initial_partitions = _partition_map(initial.root)
    successor_partitions = _partition_map(successor.root)
    changed_record_id = federal_register_source_record_id(documents[changed_index])
    changed_bucket = int.from_bytes(hashlib.sha256(changed_record_id.encode()).digest(), "big") % 64
    expected_changed = {
        ("records", f"{changed_bucket:02d}"),
        ("acquisition-records", f"{changed_bucket:02d}"),
        *{
            (
                "acquisition-pages",
                f"{int.from_bytes(hashlib.sha256(f'{traversal}:{changed_index}'.encode()).digest(), 'big') % 64:02d}",
            )
            for traversal in range(2)
        },
    }
    observed_changed = {
        key for key in initial_partitions if initial_partitions[key]["blobRef"] != successor_partitions[key]["blobRef"]
    }
    assert observed_changed == expected_changed
    assert all(
        initial_partitions[key]["blobRef"] == successor_partitions[key]["blobRef"]
        for key in initial_partitions
        if key not in expected_changed
    )

    current_files = {path.name: path.stat().st_size for path in (tmp_path / "blobs" / "sha256").iterdir()}
    new_files = set(current_files) - set(initial_files)
    assert successor.byte_measurements["payloadBytesWritten"] == sum(current_files[name] for name in new_files)
    assert successor.byte_measurements["payloadBytesReused"] > 0

    rebuilt = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=store,
        clock=_completed_at,
    ).publish(
        _stable_paged_pages(*documents),
        build=_build(),
        destination=tmp_path / "rebuilt",
    )
    assert _partition_map(rebuilt.root) == initial_partitions
    # Store reuse changes operational reporting, not any sealed input.
    assert rebuilt.artifact.pin == initial.artifact.pin
    assert rebuilt.byte_measurements != initial.byte_measurements
    assert rebuilt.byte_measurements["payloadBytesWritten"] == 0
    assert rebuilt.byte_measurements["payloadBytesReused"] == rebuilt.byte_measurements["payloadBytesRead"]


def test_concurrent_publishers_never_replace_the_winner(tmp_path: Path) -> None:
    barrier = Barrier(2)
    destination = tmp_path / "release"

    def publish():
        def synchronized_pages() -> Iterator[FederalRegisterPage]:
            barrier.wait()
            yield from _stable_pages(_document())

        return SourceNativeReleasePublisher(
            FEDERAL_REGISTER_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            synchronized_pages(),
            build=_build(),
            destination=destination,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish) for _ in range(2)]
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], (FileExistsError, ImmutablePublicationError))
    assert _reader(destination, successes[0].artifact.pin).pin == successes[0].artifact.pin


def test_stale_publication_lock_file_does_not_poison_retry(tmp_path: Path) -> None:
    destination = tmp_path / "release"
    (tmp_path / ".release.publish.lock").write_bytes(b"abandoned")

    published = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        _stable_pages(_document()),
        build=_build(),
        destination=destination,
    )

    assert _reader(destination, published.artifact.pin).pin == published.artifact.pin
