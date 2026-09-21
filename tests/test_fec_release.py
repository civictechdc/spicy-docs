"""A retained census releases only replayable, explicitly pinned observations.

Pins selected-census publication and replay, requested-empty observations,
refusal of changed counts, controls, ids, filters and captures, decimal
spelling, byte and scope bounds, and iterator behavior on short and null reads.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher, SourceNativeReleaseReader
from spicy_docs.sources.fec.catalog import MAX_METADATA_BYTES
from spicy_docs.sources.fec.profile import (
    FEC_COMMITTEE_CENSUS_PROFILE as PROFILE,
)
from spicy_docs.sources.fec.profile import (
    MAX_CAPTURES,
    committee_census_scope,
    iter_retained_committee_pages,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER

URL = "https://api.open.fec.gov/v1/committees/?cycle=2024&cycle=2026&sort=committee_id&per_page=1"


def _inputs(tmp_path, *, records=None, response_change=None):
    """Build the committee-census inputs over the retained captures."""
    if records is None:
        records = [
            {
                "committee_id": "C00000001",
                "name": "First",
                "future_field": {"null": None, "array": []},
                "text": "A full narrative",
                "pdf_url": "https://www.fec.gov/example.pdf",
            },
            {"committee_id": "C00000002", "name": "Second", "sponsor_candidate_list": [], "cycles": [2024, 2026]},
        ]
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    captures, originals = [], []
    for index in range(max(1, len(records))):
        value = {
            "api_version": "1.0",
            "future_top_field": {"retained": True},
            "pagination": {
                "count": len(records),
                "is_count_exact": True,
                "page": index + 1,
                "pages": len(records),
                "per_page": 1,
            },
            "results": records[index : index + 1],
        }
        if response_change is not None:
            response_change(value)
        raw = json.dumps(value, indent=2).encode()
        sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
        blobs.put_blob(sha256, len(raw), (raw,))
        url = URL + (f"&page={index + 1}" if index else "")
        captures.append(
            {
                "requestUrl": url,
                "resolvedUrl": url,
                "observedAt": "2026-09-12T10:00:00+00:00",
                "responseSha256": sha256,
                "byteSize": len(raw),
                "mediaType": "application/json",
                "via": "direct",
            }
        )
        originals.append(raw)
    return captures, originals, blobs


def _publish(tmp_path, captures, pages):
    """Publish the census and return its reader and release root."""
    return SourceNativeReleasePublisher(
        PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "release-blobs"),
        clock=lambda: datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    ).publish(
        pages,
        build=SourceNativeReleaseBuild(
            query_scope=committee_census_scope(captures), producer=PRODUCER, started_at="2026-09-12T11:00:00Z"
        ),
        destination=tmp_path / "release",
    )


def test_selected_census_publishes_and_replays_complete_metadata_and_exact_originals(tmp_path):
    """A selected census publishes and replays complete metadata and exact originals, with assets and bodies
    separate.
    """
    captures, originals, blobs = _inputs(tmp_path)
    pages = list(iter_retained_committee_pages(captures, blob_source=blobs))
    assert pages == list(iter_retained_committee_pages(captures, blob_source=blobs))
    published = _publish(tmp_path, captures, pages)
    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=LocalSourceNativeBlobStore(tmp_path / "release-blobs"),
        profile=PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
    records = sorted(reader.iter_records(), key=lambda row: row["sourceRecordId"])
    assert [row["sourceRecordId"] for row in records] == ["C00000001", "C00000002"]
    first, second = (row["record"] for row in records)
    assert first["capture"] == captures[0]
    assert first["metadata"] == {
        "committee_id": "C00000001",
        "name": "First",
        "future_field": {"null": None, "array": []},
        "pdf_url": "https://www.fec.gov/example.pdf",
    }
    assert first["embedded_bodies"] == [{"source_pointer": "/results/0/text", "characters": 16, "field": "text"}]
    assert first["source_pointer"] == "/results/0"
    assert first["assets"] == [
        {
            "url": "https://www.fec.gov/example.pdf",
            "media_type": "application/pdf",
            "source_pointer": "/results/0/pdf_url",
        }
    ]
    assert second["metadata"]["sponsor_candidate_list"] == []
    assert second["metadata"]["cycles"] == [2024, 2026]
    assert PROFILE.source_state_scope == "observed-crawl"
    for page, original in zip(pages, originals, strict=True):
        with ZipFile(BytesIO(page.response_bytes)) as archive:
            assert archive.read("response.json") == original
    evidence = reader.record_evidence("C00000001")
    with ZipFile(BytesIO(reader.read_evidence(evidence["evidenceBlobRef"]))) as archive:
        assert archive.read("response.json") == originals[0]


def test_empty_exact_observation_is_publishable_without_claiming_source_absence(tmp_path):
    """An exact empty observation is publishable without claiming source absence."""
    captures, _, blobs = _inputs(tmp_path, records=[])
    result = _publish(tmp_path, captures, iter_retained_committee_pages(captures, blob_source=blobs))
    assert result.root.is_dir()
    assert PROFILE.source_state_scope == "observed-crawl"


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["pagination"].update(count=99),
        lambda value: value["pagination"].update(is_count_exact=False),
        lambda value: value["pagination"].update(per_page=2),
        lambda value: value["pagination"].update(page=7),
        lambda value: value["results"][0].update(committee_id="bad"),
    ],
)
def test_publisher_rejects_changed_counts_controls_and_source_ids(tmp_path, change):
    """Changed counts, controls and source ids are rejected."""
    captures, _, blobs = _inputs(tmp_path, response_change=change)
    with pytest.raises(ValueError):
        _publish(tmp_path, captures, iter_retained_committee_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


def test_repeated_committee_id_is_rejected_instead_of_silently_collapsed(tmp_path):
    """A repeated committee id is rejected rather than silently collapsed."""
    captures, _, blobs = _inputs(tmp_path, records=[{"committee_id": "C00000001"}] * 2)
    with pytest.raises(ValueError, match="repeat or cease increasing"):
        _publish(tmp_path, captures, iter_retained_committee_pages(captures, blob_source=blobs))


def test_missing_terminal_capture_cannot_shrink_declared_selected_scope(tmp_path):
    """A missing terminal capture cannot shrink the declared selected scope."""
    captures, _, blobs = _inputs(tmp_path)
    pages = list(iter_retained_committee_pages(captures, blob_source=blobs))
    with pytest.raises(ValueError, match="terminal page"):
        _publish(tmp_path, captures, pages[:-1])
    with pytest.raises(ValueError, match="continuation differs"):
        _publish(tmp_path, captures[:-1], pages[:-1])


def test_capture_time_and_transport_pins_are_checked_before_record_emission(tmp_path):
    """Capture time and transport pins are checked before any record is emitted."""
    captures, _, blobs = _inputs(tmp_path)
    pages = list(iter_retained_committee_pages(captures, blob_source=blobs))
    altered = [{**capture, "observedAt": "2026-09-13T00:00:00Z"} for capture in captures]
    with pytest.raises(ValueError, match="capture differs"):
        _publish(tmp_path, altered, pages)


def test_iterator_hashes_consumed_bytes_and_evidence_parser_checks_inner_pin(tmp_path):
    """The iterator hashes consumed bytes and the evidence parser checks the inner pin."""
    captures, _, blobs = _inputs(tmp_path)
    altered = [{**capture, "byteSize": capture["byteSize"] - 1} for capture in captures]
    with pytest.raises(ValueError, match="response bytes differ"):
        next(iter_retained_committee_pages(altered, blob_source=blobs))
    page = next(iter_retained_committee_pages(captures, blob_source=blobs))
    with pytest.raises(ValueError, match="ZIP"):
        _publish(tmp_path, captures, [replace(page, response_bytes=b"not a captured response")])


def test_scope_keeps_repeated_filters_and_rejects_missing_initial_page_or_changed_filters(tmp_path):
    """Scope keeps repeated filters and rejects a missing initial page or changed filters."""
    captures, _, _ = _inputs(tmp_path)
    assert "cycle=2024&cycle=2026" in committee_census_scope(captures)["captures"][0]["requestUrl"]
    with pytest.raises(ValueError, match="omits pages"):
        committee_census_scope(captures[1:])
    captures[1] = {**captures[1], "requestUrl": captures[1]["requestUrl"].replace("2024", "2022")}
    captures[1]["resolvedUrl"] = captures[1]["requestUrl"]
    with pytest.raises(ValueError, match="changes source filters"):
        committee_census_scope(captures)


def test_capture_inventory_has_an_explicit_bound(tmp_path):
    """The capture inventory has an explicit bound."""
    captures, _, _ = _inputs(tmp_path)
    first = captures[0]
    bounded = []
    for index in range(MAX_CAPTURES):
        url = URL + (f"&page={index + 1}" if index else "")
        bounded.append({**first, "requestUrl": url, "resolvedUrl": url})
    assert len(committee_census_scope(bounded)["captures"]) == MAX_CAPTURES
    with pytest.raises(ValueError, match="bounded"):
        committee_census_scope(bounded + [first])


def test_profile_import_and_replay_do_not_require_live_http_libraries(tmp_path):
    """Profile import and replay do not require live HTTP libraries."""
    captures, _, blobs = _inputs(tmp_path)
    page = next(iter_retained_committee_pages(captures, blob_source=blobs))
    evidence = tmp_path / "evidence.zip"
    evidence.write_bytes(page.response_bytes)
    code = """
import sys
from pathlib import Path
sys.modules['httpx'] = None
from spicy_docs.source_native.profiles import FEC_COMMITTEE_CENSUS_PROFILE
parsed = FEC_COMMITTEE_CENSUS_PROFILE.parse_page_response(Path(sys.argv[1]).read_bytes())
assert parsed['results'][0]['metadata']['committee_id'] == 'C00000001'
assert 'spicy_docs.sources.fec.client' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code, str(evidence)], check=True, capture_output=True, text=True)


def test_decimal_values_keep_exact_spelling_and_the_original_json_type(tmp_path):
    """Decimal values keep exact spelling and the original JSON type."""
    captures, originals, blobs = _inputs(tmp_path, records=[{"committee_id": "C00000001", "precise": "NUMBER"}])
    raw = originals[0].replace(b'"NUMBER"', b"12345678901234567890.123400")
    sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    blobs.put_blob(sha256, len(raw), (raw,))
    captures[0] = {**captures[0], "responseSha256": sha256, "byteSize": len(raw)}
    page = next(iter_retained_committee_pages(captures, blob_source=blobs))
    result = PROFILE.parse_page_response(page.response_bytes)
    assert result["results"][0]["metadata"]["precise"] == "12345678901234567890.123400"
    with ZipFile(BytesIO(page.response_bytes)) as archive:
        assert archive.read("response.json") == raw


def test_maximum_response_is_read_once_and_oversized_capture_is_refused(tmp_path):
    """The maximum response is read once and an oversized capture is refused."""
    captures, originals, blobs = _inputs(tmp_path, records=[{"committee_id": "C00000001"}])
    raw = originals[0] + b" " * (MAX_METADATA_BYTES - len(originals[0]))
    sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
    blobs.put_blob(sha256, len(raw), (raw,))
    captures[0] = {**captures[0], "responseSha256": sha256, "byteSize": len(raw)}

    class CountedSource:
        opened = 0

        def open(self, blob_ref):
            self.opened += 1
            return blobs.open(blob_ref)

    counted = CountedSource()
    pages = list(iter_retained_committee_pages(captures, blob_source=counted))
    assert counted.opened == 1
    _publish(tmp_path, captures, pages)
    with pytest.raises(ValueError, match="byte size exceeds"):
        committee_census_scope([{**captures[0], "byteSize": MAX_METADATA_BYTES + 1}])


def test_aggregate_scope_bound_refuses_large_metadata_before_reading_blobs(tmp_path):
    """The aggregate scope bound refuses large metadata before any blob is read."""
    captures, _, _ = _inputs(tmp_path)
    first = captures[0]
    expanded = []
    for index in range(MAX_CAPTURES):
        url = URL + (f"&page={index + 1}" if index else "")
        expanded.append({**first, "requestUrl": url, "resolvedUrl": url, "via": "x" * 4000})
    with pytest.raises(ValueError, match="scope exceeds"):
        committee_census_scope(expanded)


@pytest.mark.parametrize("chunk_size", [1, 7, 65_536])
def test_retained_iterator_accepts_short_binary_reads_without_changing_evidence(tmp_path, chunk_size):
    """The retained iterator accepts short binary reads without changing evidence."""
    captures, originals, blobs = _inputs(tmp_path, records=[{"committee_id": "C00000001"}])

    class ShortStream(BytesIO):
        def read(self, requested=-1):
            assert 0 < requested <= 65_536
            return super().read(min(chunk_size, requested))

    class ShortSource:
        def open(self, blob_ref):
            assert blob_ref == captures[0]["responseSha256"]
            return ShortStream(originals[0])

    actual = list(iter_retained_committee_pages(captures, blob_source=ShortSource()))
    expected = list(iter_retained_committee_pages(captures, blob_source=blobs))
    assert actual == expected


@pytest.mark.parametrize("condition", ["null", "truncated", "extra-byte"])
def test_retained_iterator_refuses_null_reads_and_wrong_lengths(tmp_path, condition):
    """The retained iterator refuses null reads and wrong lengths."""
    captures, originals, _ = _inputs(tmp_path, records=[{"committee_id": "C00000001"}])

    class FaultStream(BytesIO):
        def read(self, requested=-1):
            return None if condition == "null" else super().read(min(7, requested))

    class FaultSource:
        def open(self, blob_ref):
            raw = originals[0][:-1] if condition == "truncated" else originals[0] + b"x"
            return FaultStream(raw)

    with pytest.raises(ValueError, match="bounded binary bytes|response bytes differ"):
        next(iter_retained_committee_pages(captures, blob_source=FaultSource()))
