"""Exact companion records, explicit dataset shape, and existing bounded acquisition."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.legislators import (
    MAX_CURRENT_BYTES,
    LegislatorsAcquirer,
    LegislatorsBudget,
    LegislatorsRefusedError,
    LegislatorsSourceError,
    parse_legislator_companion,
)


@pytest.mark.parametrize(
    ("dataset", "field", "value"),
    [
        ("social-media", "social", {"twitter": "Example", "unknown": None}),
        ("district-offices", "offices", [{"latitude": 0.0, "longitude": -71.054, "phone": "001-555", "unknown": None}]),
    ],
)
def test_exact_record_bytes_and_unknown_fields_survive(dataset, field, value):
    row = {"id": {"bioguide": "W000805"}, field: value, "extra": "é"}
    record = json.dumps(row, ensure_ascii=False, indent=2).encode()
    body = b"[\n " + record + b"\n]"
    result = parse_legislator_companion(body, dataset=dataset, max_bytes=MAX_CURRENT_BYTES)
    assert result.records[0].raw_json.encode() == record
    assert result.records[0].source_record_index == 0
    assert result.by_bioguide["W000805"] == result.records[0]
    assert result.input_sha256 == "sha256:" + hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize(
    "body",
    [
        b'{"id": {"bioguide": "W000805"}, "social": {}}',
        b'[{"id": {"bioguide": "wrong"}, "social": {}}]',
        b'[{"id": {"bioguide": "W000805"}, "social": []}]',
        b'[{"id": {"bioguide": "W000805"}, "social": {}, "social": {}}]',
        b'[{"id": {"bioguide": "W000805"}, "social": {}}, {"id": {"bioguide": "W000805"}, "social": {}}]',
    ],
)
def test_bad_shapes_and_ambiguous_identity_refuse_whole_file(body):
    with pytest.raises(LegislatorsSourceError):
        parse_legislator_companion(body, dataset="social-media", max_bytes=MAX_CURRENT_BYTES)


def test_byte_record_and_dataset_bounds_apply_before_return():
    body = b'[{"id": {"bioguide": "W000805"}, "social": {}}]'
    for kwargs in ({"max_bytes": 1}, {"max_records": 0}, {"dataset": "executive"}):
        with pytest.raises(LegislatorsSourceError):
            parse_legislator_companion(body, **{"dataset": "social-media", "max_bytes": MAX_CURRENT_BYTES, **kwargs})


def test_unmatched_ids_and_empty_office_lists_are_retained():
    body = b'[{"id": {"bioguide": "Z999999"}, "offices": []}]'
    result = parse_legislator_companion(body, dataset="district-offices", max_bytes=MAX_CURRENT_BYTES)
    assert "Z999999" in result.by_bioguide
    assert json.loads(result.records[0].raw_json)["offices"] == []


def test_acquisition_uses_existing_capture_and_budget():
    body = b'[{"id": {"bioguide": "W000805"}, "social": {"twitter": "MarkWarner"}}]'

    def handle(request):
        assert request.url.path == "/congress-legislators/legislators-social-media.json"
        return httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": "application/json"})

    with LegislatorsAcquirer(
        budget=LegislatorsBudget(1, MAX_CURRENT_BYTES, 30, 0),
        transport=httpx.MockTransport(handle),
    ) as source:
        result = source.acquire_companion("social-media")
    assert result.capture.body == body
    assert result.file.input_sha256.endswith(hashlib.sha256(body).hexdigest())
    assert result.request_count == 1


@pytest.mark.parametrize("dataset", ["social-media", "district-offices"])
def test_native_companion_excerpt(dataset):
    body = (Path(__file__).parent / "fixtures" / "legislators" / f"legislators-{dataset}-excerpt.json").read_bytes()
    result = parse_legislator_companion(body, dataset=dataset, max_bytes=MAX_CURRENT_BYTES)
    record = result.by_bioguide["W000805"]
    expected = json.loads(body)[0]
    assert json.loads(record.raw_json) == expected
    assert record.source_record_index == 0


@pytest.mark.parametrize("status", [401, 403])
def test_companion_refusal_is_the_familys_own_error_with_its_bytes(status):
    body = b"rate limited"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "text/plain"})
    )
    with (
        LegislatorsAcquirer(budget=LegislatorsBudget(1, MAX_CURRENT_BYTES, 30, 0), transport=transport) as source,
        pytest.raises(LegislatorsRefusedError) as raised,
    ):
        source.acquire_companion("district-offices")
    assert raised.value.refused_response.response_bytes == body
    assert raised.value.legislators_acquisition["operation"] == "district-offices"
