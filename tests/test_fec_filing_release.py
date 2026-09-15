"""Selected filing-query publication preserves observations and source evidence."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher, SourceNativeReleaseReader
from spicy_docs.sources.fec.filing_profile import FEC_FILING_QUERY_PROFILE as PROFILE
from spicy_docs.sources.fec.filing_profile import filing_query_scope, iter_retained_filing_pages
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER
from tests.test_fec_release import _inputs as captured_inputs

URL = "https://api.open.fec.gov/v1/filings/?file_number=20&file_number=10&per_page=1"


def _inputs(tmp_path, *, records=None, response_change=None):
    rows = (
        records
        if records is not None
        else [
            {
                "file_number": 20,
                "sub_id": "200",
                "amendment_chain": [10, 20],
                "is_amended": False,
                "unknown": {"none": None, "empty": [], "empty_name": ""},
                "text": "Exact body\n",
                "fec_url": "https://docquery.fec.gov/dcdev/posted/20.fec",
                "amount": "DECIMAL",
            },
            {"file_number": 10, "sub_id": "100", "amendment_chain": [10, 20], "is_amended": True},
        ]
    )
    captures, originals, blobs = captured_inputs(tmp_path, records=rows, response_change=response_change)
    for index, capture in enumerate(captures):
        raw = originals[index].replace(b'"DECIMAL"', b"12345678901234567890.1200")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        blobs.put_blob(digest, len(raw), (raw,))
        url = URL + (f"&page={index + 1}" if index else "")
        captures[index] = {
            **capture,
            "requestUrl": url,
            "resolvedUrl": url,
            "responseSha256": digest,
            "byteSize": len(raw),
        }
        originals[index] = raw
    return captures, originals, blobs


def _publish(tmp_path, captures, pages):
    result = SourceNativeReleasePublisher(
        PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "output-blobs"),
        clock=lambda: datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    ).publish(
        pages,
        build=SourceNativeReleaseBuild(
            query_scope=filing_query_scope(captures), producer=PRODUCER, started_at="2026-09-13T11:00:00Z"
        ),
        destination=tmp_path / "release",
    )
    reader = SourceNativeReleaseReader(
        LocalMemberSource(result.root),
        blob_source=LocalSourceNativeBlobStore(tmp_path / "output-blobs"),
        profile=PROFILE,
        expected_pin=result.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
    return result, reader


def test_filing_query_preserves_native_ids_unknowns_amendments_and_body_coordinates(tmp_path):
    captures, originals, blobs = _inputs(tmp_path)
    _, reader = _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))
    records = {row["sourceRecordId"]: row["record"] for row in reader.iter_records()}
    # Source order is newest-first here; no current/amended observation is removed.
    assert set(records) == {"100", "200"}
    latest = records["200"]
    assert latest["metadata"] == {
        "file_number": 20,
        "sub_id": "200",
        "amendment_chain": [10, 20],
        "is_amended": False,
        "unknown": {"none": None, "empty": [], "empty_name": ""},
        "fec_url": "https://docquery.fec.gov/dcdev/posted/20.fec",
        "amount": "12345678901234567890.1200",
    }
    assert latest["capture"] == captures[0]
    assert records["100"]["metadata"]["is_amended"] is True
    assert latest["embedded_bodies"] == [{"source_pointer": "/results/0/text", "characters": 11, "field": "text"}]
    assert latest["assets"] == [
        {
            "url": "https://docquery.fec.gov/dcdev/posted/20.fec",
            "source_pointer": "/results/0/fec_url",
            "media_type": "text/plain",
        }
    ]
    assert list(reader.iter_renditions()) == []
    for observation in reader.iter_record_evidence():
        identity = observation["sourceRecordId"]
        with ZipFile(BytesIO(reader.read_evidence(observation["evidenceBlobRef"]))) as evidence:
            assert evidence.read("response.json") == originals[0 if identity == "200" else 1]


def test_requested_empty_query_keeps_its_capture_without_inventing_filing_records(tmp_path):
    captures, originals, blobs = _inputs(tmp_path, records=[])
    _, reader = _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))
    assert list(reader.iter_records()) == []
    outcome = reader.collection_outcome
    assert outcome["recordOutcome"] == "empty"
    assert outcome["acquisitionEvidenceCount"] == 1
    assert outcome["requestedScope"] == filing_query_scope(captures)
    assert outcome["sourceStateScope"] == "observed-crawl"
    page = next(iter_retained_filing_pages(captures, blob_source=blobs))
    with ZipFile(BytesIO(page.response_bytes)) as evidence:
        assert evidence.read("response.json") == originals[0]


@pytest.mark.parametrize("number", [{"file_number": None}, {}])
@pytest.mark.parametrize("filtered", [False, True])
def test_nullable_or_absent_file_number_is_metadata_not_identity(tmp_path, number, filtered):
    row = {"sub_id": "100", "unknown": {"retained": None}, **number}
    captures, _, blobs = _inputs(tmp_path, records=[row])
    if not filtered:
        captures[0]["requestUrl"] = captures[0]["resolvedUrl"] = "https://api.open.fec.gov/v1/filings/?per_page=1"
    pages = iter_retained_filing_pages(captures, blob_source=blobs)
    if filtered:
        with pytest.raises(ValueError, match="explicit file-number selection"):
            _publish(tmp_path, captures, pages)
    else:
        _, reader = _publish(tmp_path, captures, pages)
        observed = list(reader.iter_records())
        assert len(observed) == 1 and observed[0]["sourceRecordId"] == "100"
        assert observed[0]["record"]["metadata"] == row
        assert observed[0]["schemaVersion"] == "1.2"


@pytest.mark.parametrize("selected", [None, -9668190, 9668190])
def test_source_negative_file_number_round_trips_without_changing_identity(tmp_path, selected):
    # Literal values from the retained F13 response. File number is not identity.
    row = {"sub_id": "1072820200239473774", "file_number": -9668190, "form_type": "F13"}
    captures, originals, blobs = _inputs(tmp_path, records=[row])
    url = "https://api.open.fec.gov/v1/filings/?form_type=F13&per_page=1"
    if selected is not None:
        url += f"&file_number={selected}"
    captures[0]["requestUrl"] = captures[0]["resolvedUrl"] = url
    pages = iter_retained_filing_pages(captures, blob_source=blobs)
    if selected == 9668190:
        with pytest.raises(ValueError, match="explicit file-number selection"):
            _publish(tmp_path, captures, pages)
        assert not (tmp_path / "release").exists()
        return
    _, reader = _publish(tmp_path, captures, pages)
    (observed,) = reader.iter_records()
    assert observed["record"]["metadata"] == row
    assert observed["sourceRecordId"] == row["sub_id"]
    assert observed["schemaVersion"] == "1.2"
    (evidence,) = reader.iter_record_evidence()
    with ZipFile(BytesIO(reader.read_evidence(evidence["evidenceBlobRef"]))) as archive:
        assert archive.read("response.json") == originals[0]


@pytest.mark.parametrize("number", [True, False, "-9668190", -1.5, [], {}])
def test_file_number_still_requires_an_integer_or_null(tmp_path, number):
    captures, _, blobs = _inputs(tmp_path, records=[{"sub_id": "100", "file_number": number}])
    captures[0]["requestUrl"] = captures[0]["resolvedUrl"] = "https://api.open.fec.gov/v1/filings/?per_page=1"
    with pytest.raises(ValueError, match="invalid file number"):
        _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["pagination"].update(count=99),
        lambda value: value["pagination"].update(is_count_exact=False),
        lambda value: value["pagination"].update(per_page=2),
        lambda value: value["results"][0].update(sub_id=None),
        lambda value: value["results"][0].update(file_number=999),
        lambda value: value.update(error="source refused the query"),
    ],
)
def test_changed_counts_ids_filters_and_refusals_cannot_publish(tmp_path, change):
    captures, _, blobs = _inputs(tmp_path, response_change=change)
    with pytest.raises(ValueError):
        _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


def test_missing_page_and_shrunk_inventory_both_refuse(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    pages = list(iter_retained_filing_pages(captures, blob_source=blobs))
    with pytest.raises(ValueError, match="terminal"):
        _publish(tmp_path, captures, pages[:-1])
    with pytest.raises(ValueError, match="continuation"):
        _publish(tmp_path, captures[:-1], pages[:-1])


def test_repeated_source_sub_id_is_not_silently_deduplicated(tmp_path):
    captures, _, blobs = _inputs(tmp_path, records=[{"file_number": 10, "sub_id": "100"}] * 2)
    with pytest.raises(ValueError, match="repeats"):
        _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))


def test_capture_scope_and_raw_bytes_are_both_checked(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    pages = list(iter_retained_filing_pages(captures, blob_source=blobs))
    changed = [{**capture, "observedAt": "2026-09-13T00:00:00Z"} for capture in captures]
    with pytest.raises(ValueError, match="capture differs"):
        _publish(tmp_path, changed, pages)
    with pytest.raises(ValueError, match="ZIP"):
        _publish(tmp_path, captures, [replace(pages[0], response_bytes=b"<html>Access denied</html>")])


def test_new_profile_and_replay_import_without_http_dependency(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    path = tmp_path / "capture.zip"
    path.write_bytes(next(iter_retained_filing_pages(captures, blob_source=blobs)).response_bytes)
    code = """
import sys
from pathlib import Path
sys.modules['httpx'] = None
from spicy_docs.source_native.profiles import FEC_FILING_QUERY_PROFILE
assert FEC_FILING_QUERY_PROFILE.parse_page_response(Path(sys.argv[1]).read_bytes())['results'][0]['metadata']['sub_id'] == '200'
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True, capture_output=True, text=True)


def test_existing_committee_release_pin_is_unchanged_by_shared_helpers(tmp_path):
    from tests.test_fec_release import _inputs, _publish, iter_retained_committee_pages

    captures, _, blobs = _inputs(tmp_path)
    published = _publish(tmp_path, captures, iter_retained_committee_pages(captures, blob_source=blobs))
    # Frozen from the parent commit before the shared-helper extraction.
    assert (
        published.artifact.pin.artifact_digest
        == "sha256:df6053d86ad5f8147c930feeb47e8e0b84bd48a6de7ae2efd0d1ba678c75dc73"
    )


def test_existing_filing_release_pin_is_unchanged_by_shared_profile_wiring(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    published, _ = _publish(tmp_path, captures, iter_retained_filing_pages(captures, blob_source=blobs))
    # Frozen from c5082cc before candidate-query support and shared wiring.
    assert (
        published.artifact.pin.artifact_digest
        == "sha256:41e614766d25420a943cb6c612f4ad907bf1bba4793b18f76a18921090de2413"
    )
