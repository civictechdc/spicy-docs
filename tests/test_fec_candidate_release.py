"""Candidate-query publication preserves exact scope and source observations."""

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher, SourceNativeReleaseReader
from spicy_docs.source_native_profiles import FEC_CANDIDATE_QUERY_PROFILE as PROFILE
from spicy_docs.sources.fec.candidate_profile import candidate_query_scope, iter_retained_candidate_pages
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER
from tests.test_fec_release import _inputs as synthetic_inputs

FIXTURES = Path(__file__).parent / "fixtures/fec/candidates"
URL = "https://api.open.fec.gov/v1/candidates/?cycle=2024&cycle=2026&per_page=1"


def _inputs(tmp_path, *, records=None, response_change=None):
    captures, originals, blobs = synthetic_inputs(
        tmp_path,
        records=records
        if records is not None
        else [
            {"candidate_id": "S6MI00103", "text": "Candidate body", "unknown": {"empty": [], "null": None}},
            {"candidate_id": "H2AK01158", "election_districts": ["00", "00"], "candidate_inactive": False},
        ],
        response_change=response_change,
    )
    for index, capture in enumerate(captures):
        capture["requestUrl"] = capture["resolvedUrl"] = URL + (f"&page={index + 1}" if index else "")
    return captures, originals, blobs


def _publish(tmp_path, captures, pages):
    output = LocalSourceNativeBlobStore(tmp_path / "output-blobs")
    published = SourceNativeReleasePublisher(
        PROFILE,
        blob_store=output,
        clock=lambda: datetime(2026, 9, 15, 2, 0, tzinfo=UTC),
    ).publish(
        pages,
        build=SourceNativeReleaseBuild(
            query_scope=candidate_query_scope(captures), producer=PRODUCER, started_at="2026-09-15T01:00:00Z"
        ),
        destination=tmp_path / "release",
    )
    return SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=output,
        profile=PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )


@pytest.mark.parametrize("file", ["selected.json", "empty.json"])
def test_retained_query_preserves_every_source_field_and_requested_scope(tmp_path, file):
    selected = next(item for item in json.loads((FIXTURES / "sources.json").read_bytes()) if item["file"] == file)
    capture = selected["capture"]
    raw = (FIXTURES / file).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == capture["responseSha256"]
    assert len(raw) == capture["byteSize"]
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
    reader = _publish(tmp_path, [capture], iter_retained_candidate_pages([capture], blob_source=blobs))
    expected = {row["candidate_id"]: row for row in json.loads(raw)["results"]}
    rows = {row["sourceRecordId"]: row["record"] for row in reader.iter_records()}
    assert {key: row["metadata"] for key, row in rows.items()} == expected
    assert reader.collection_outcome["requestedScope"] == {"captures": [capture]}
    assert reader.collection_outcome["sourceStateScope"] == "observed-crawl"
    assert reader.collection_outcome["acquisitionEvidenceCount"] == 1
    assert list(reader.iter_renditions()) == []
    if expected:
        assert set(rows) == {"H2AK01158"}  # The other requested ID is not an invented record.
        assert rows["H2AK01158"]["capture"] == capture
        assert rows["H2AK01158"]["source_pointer"] == "/results/0"
        (evidence,) = reader.iter_record_evidence()
        with ZipFile(BytesIO(reader.read_evidence(evidence["evidenceBlobRef"]))) as archive:
            assert archive.read("response.json") == raw
    else:
        assert reader.collection_outcome["recordOutcome"] == "empty"


def test_unsorted_pages_preserve_distinct_ids_unknowns_and_separated_bodies(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    reader = _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))
    rows = {row["sourceRecordId"]: row["record"] for row in reader.iter_records()}
    assert set(rows) == {"S6MI00103", "H2AK01158"}
    assert rows["S6MI00103"]["metadata"] == {"candidate_id": "S6MI00103", "unknown": {"empty": [], "null": None}}
    assert rows["S6MI00103"]["embedded_bodies"] == [
        {"source_pointer": "/results/0/text", "characters": 14, "field": "text"},
    ]
    assert rows["H2AK01158"]["metadata"]["election_districts"] == ["00", "00"]
    assert rows["H2AK01158"]["metadata"]["candidate_inactive"] is False
    assert "cycle=2024&cycle=2026" in reader.collection_outcome["requestedScope"]["captures"][0]["requestUrl"]


def test_pinned_publisher_refusal_stays_a_failure_instead_of_empty_success(tmp_path):
    capture = json.loads((FIXTURES / "sources.json").read_bytes())[0]["capture"]
    source = json.loads((FIXTURES / "sources.json").read_bytes())[2]
    raw = (FIXTURES / source["file"]).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == source["sha256"]
    capture = {**capture, "responseSha256": source["sha256"], "byteSize": source["bytes"]}
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    blobs.put_blob(source["sha256"], len(raw), (raw,))
    with pytest.raises(ValueError):
        _publish(tmp_path, [capture], iter_retained_candidate_pages([capture], blob_source=blobs))
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("identity", ["C00000001", "", "H2AK011580", "H2AK0115\n", None, 123, True])
def test_invalid_source_identity_refuses_publication(tmp_path, identity):
    captures, _, blobs = _inputs(tmp_path, records=[{"candidate_id": identity}])
    with pytest.raises(ValueError, match="candidate_id"):
        _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize("selected", ["H2AK01158", "P00000034"])
def test_direct_candidate_filter_requires_a_returned_match(tmp_path, selected):
    captures, _, blobs = _inputs(tmp_path, records=[{"candidate_id": "H2AK01158"}])
    capture = captures[0]
    capture["requestUrl"] = capture["resolvedUrl"] = URL + "&candidate_id=" + selected
    pages = iter_retained_candidate_pages(captures, blob_source=blobs)
    if selected == "H2AK01158":
        reader = _publish(tmp_path, captures, pages)
        assert [row["sourceRecordId"] for row in reader.iter_records()] == [selected]
    else:
        with pytest.raises(ValueError, match="candidate-ID selection"):
            _publish(tmp_path, captures, pages)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["pagination"].update(count=99),
        lambda value: value["pagination"].update(is_count_exact=False),
        lambda value: value["pagination"].update(page=7),
        lambda value: value["pagination"].update(per_page=2),
        lambda value: value.update(error="denied"),
    ],
)
def test_counts_page_controls_and_source_refusals_cannot_publish(tmp_path, change):
    captures, _, blobs = _inputs(tmp_path, response_change=change)
    with pytest.raises(ValueError):
        _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


def test_estimated_empty_count_cannot_publish(tmp_path):
    # Unlike nonempty estimates, this has no continuation to make it fail elsewhere.
    captures, _, blobs = _inputs(
        tmp_path,
        records=[],
        response_change=lambda value: value["pagination"].update(is_count_exact=False),
    )
    with pytest.raises(ValueError, match="exact nonnegative publisher count"):
        _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))
    assert not (tmp_path / "release").exists()


def test_duplicate_candidate_ids_refuse_instead_of_collapsing(tmp_path):
    captures, _, blobs = _inputs(tmp_path, records=[{"candidate_id": "P00000034"}] * 2)
    with pytest.raises(ValueError, match="repeats"):
        _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))


def test_candidate_ids_are_not_case_normalized(tmp_path):
    # Synthetic shape control, not evidence that the live API publishes lowercase IDs.
    ids = ["H2AK01158", "H2ak01158"]
    captures, _, blobs = _inputs(tmp_path, records=[{"candidate_id": identity} for identity in ids])
    reader = _publish(tmp_path, captures, iter_retained_candidate_pages(captures, blob_source=blobs))
    assert {row["sourceRecordId"]: row["record"]["metadata"]["candidate_id"] for row in reader.iter_records()} == {
        identity: identity for identity in ids
    }


def test_missing_page_shrunk_inventory_and_changed_capture_refuse(tmp_path):
    captures, _, blobs = _inputs(tmp_path)
    pages = list(iter_retained_candidate_pages(captures, blob_source=blobs))
    with pytest.raises(ValueError, match="terminal"):
        _publish(tmp_path, captures, pages[:-1])
    with pytest.raises(ValueError, match="continuation"):
        _publish(tmp_path, captures[:-1], pages[:-1])
    captures[1] = {**captures[1], "observedAt": "2026-09-13T00:00:00Z"}
    with pytest.raises(ValueError, match="capture differs"):
        _publish(tmp_path, captures, pages)


@pytest.mark.parametrize("path", ["candidates/search", "candidate/H2AK01158", "candidates/totals", "committees"])
def test_other_endpoint_shapes_need_their_own_identity_rules(tmp_path, path):
    captures, _, _ = _inputs(tmp_path)
    capture = captures[0]
    capture["requestUrl"] = capture["resolvedUrl"] = URL.replace("/candidates/", f"/{path}/")
    with pytest.raises(ValueError, match="selected endpoint"):
        candidate_query_scope([capture])
