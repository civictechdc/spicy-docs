"""Hermetic tests for the SAM.gov bulk-extract path (no network).

Covers download-URL discovery, the defensive file parse (envelope, bare
array, NDJSON, gzip, zip, garbage), key reinjection, the poll loop, and the
trigger-orchestrated population with its count and duplicate refusals. The
fixture is a trimmed but faithful copy of a real ``entityData[]`` record from
the v4 ``/entities`` response.
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile

import httpx
import pytest

from spicy_docs.sources.sam_extract import (
    SamBulkExtract,
    SamExtractError,
    extract_entities_url,
    find_extract_download_url,
    parse_extract_records,
    reinject_extract_key,
    validate_entity,
    year_window_literal,
)


def _entity(uei: str) -> dict:
    return {"entityRegistration": {"ueiSAM": uei}}


def _ueis(records) -> list[str]:
    return [r["entityRegistration"]["ueiSAM"] for r in records]


# -- URL and literal builders ------------------------------------------------


def test_year_window_literal_spans_the_calendar_year():
    assert year_window_literal(2022) == "[01/01/2022,12/31/2022]"
    with pytest.raises(SamExtractError):
        year_window_literal(0)


def test_extract_entities_url_carries_format_and_window():
    url = extract_entities_url(year=2022)
    assert "format=json" in url
    assert "registrationStatus=A" in url
    assert (
        "registrationDate=%5B01%2F01%2F2022%2C12%2F31%2F2022%5D" in url
        or "registrationDate=[01/01/2022,12/31/2022]" in url
    )
    assert (
        extract_entities_url() == "https://api.sam.gov/entity-information/v4/entities?registrationStatus=A&format=json"
    )


# -- download-URL discovery --------------------------------------------------


def test_find_download_url_prefers_placeholder_link():
    payload = {
        "totalRecords": 764850,
        "links": {"selfLink": "https://api.sam.gov/entity-information/v4/entities?api_key=X"},
        "download": "https://api.sam.gov/comp/extracts/ENTITY_123.json?api_key=REPLACE_WITH_API_KEY",
    }
    assert find_extract_download_url(payload) == payload["download"]


def test_find_download_url_falls_back_to_download_like_url():
    payload = {"result": {"fileUrl": "https://api.sam.gov/comp/extractfile/download/abc.zip"}}
    assert find_extract_download_url(payload) == "https://api.sam.gov/comp/extractfile/download/abc.zip"


def test_find_download_url_none_when_absent():
    assert find_extract_download_url({"totalRecords": 0, "entityData": []}) is None


# -- defensive file parsing --------------------------------------------------


def test_parse_extract_envelope_json():
    raw = json.dumps({"entityData": [_entity("A"), _entity("B")]}).encode()
    assert _ueis(parse_extract_records(raw)) == ["A", "B"]


def test_parse_extract_bare_array():
    raw = json.dumps([_entity("A"), _entity("C")]).encode()
    assert _ueis(parse_extract_records(raw)) == ["A", "C"]


def test_parse_extract_single_entity_object():
    raw = json.dumps(_entity("solo")).encode()
    assert _ueis(parse_extract_records(raw)) == ["solo"]


def test_parse_extract_ndjson():
    raw = ("\n".join(json.dumps(_entity(u)) for u in ("A", "B", "C")) + "\n").encode()
    assert _ueis(parse_extract_records(raw)) == ["A", "B", "C"]


def test_parse_extract_gzip_envelope():
    raw = gzip.compress(json.dumps({"entityData": [_entity("Z")]}).encode())
    assert _ueis(parse_extract_records(raw)) == ["Z"]


def test_parse_extract_zip_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ENTITY.json", json.dumps([_entity("Q"), _entity("R")]))
    assert _ueis(parse_extract_records(buf.getvalue())) == ["Q", "R"]


def test_parse_extract_envelope_count_mismatch_refuses():
    raw = json.dumps({"totalRecords": 3, "entityData": [_entity("A"), _entity("B")]}).encode()
    with pytest.raises(SamExtractError, match="differs from totalRecords"):
        parse_extract_records(raw)


@pytest.mark.parametrize("raw", [b"", b"not json at all"])
def test_parse_extract_empty_or_garbage(raw):
    with pytest.raises(SamExtractError):
        parse_extract_records(raw)


# -- key reinjection ---------------------------------------------------------


def test_reinject_key_swaps_placeholder_and_query_param():
    masked = (
        "https://api.sam.gov/entity-information/v4/entities"
        "?api_key=REPLACE_WITH_API_KEY&page=5&size=10&registrationStatus=A"
    )
    out = reinject_extract_key(masked, "real-secret")
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(out).query)
    assert query["api_key"] == ["real-secret"]
    assert query["page"] == ["5"]
    assert query["size"] == ["10"]


def test_reinject_key_swaps_placeholder_token_in_path():
    masked = "https://api.sam.gov/comp/extractfile/REPLACE_WITH_API_KEY/ENTITY.json"
    out = reinject_extract_key(masked, "real-secret")
    assert "REPLACE_WITH_API_KEY" not in out
    assert "api_key=real-secret" in out


def test_reinject_key_refuses_foreign_host():
    with pytest.raises(SamExtractError, match="authorized API host"):
        reinject_extract_key("https://evil.example/x?api_key=REPLACE_WITH_API_KEY", "k")


# -- orchestration with a fake client ----------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", payload: dict | None = None):
        self.status_code = status_code
        self.content = content
        self._payload = payload

    def json(self):
        assert self._payload is not None, "json() called on a response without a payload"
        return self._payload


class _FakeClient:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        assert self._responses, "fake client ran out of responses"
        return self._responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_records_triggers_then_downloads_and_checks_counts(monkeypatch):
    body = json.dumps({"entityData": [_entity("A"), _entity("B")]}).encode()
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 2, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(200, content=body),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    got = _ueis(reader.records())
    assert got == ["A", "B"]
    # The trigger asked for a JSON extract; the download URL had the key re-injected.
    trigger_url, trigger_params = client.calls[0]
    assert "format=json" in trigger_url
    assert trigger_params == {"api_key": "secret"}
    assert "REPLACE_WITH_API_KEY" not in client.calls[1][0]
    assert "api_key=secret" in client.calls[1][0]


def test_records_accepts_inline_population_without_download(monkeypatch):
    client = _FakeClient([_FakeResponse(200, payload={"totalRecords": 2, "entityData": [_entity("A"), _entity("B")]})])
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    assert _ueis(reader.records()) == ["A", "B"]
    assert len(client.calls) == 1  # no download request when the data came inline


def test_records_refuses_count_mismatch(monkeypatch):
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 3, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(200, content=json.dumps([_entity("A"), _entity("B")]).encode()),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    with pytest.raises(SamExtractError, match="count differs"):
        list(reader.records())


def test_records_refuses_repeated_identifier(monkeypatch):
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 2, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(200, content=json.dumps([_entity("A"), _entity("A")]).encode()),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    with pytest.raises(SamExtractError, match="repeats an entity"):
        list(reader.records())


def test_download_polls_until_ready(monkeypatch):
    body = json.dumps({"entityData": [_entity("A"), _entity("B")]}).encode()
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 2, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(202),
            _FakeResponse(202),
            _FakeResponse(200, content=body),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    assert _ueis(reader.records()) == ["A", "B"]


def test_download_gives_up_after_poll_budget(monkeypatch):
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 2, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(202),
            _FakeResponse(202),
            _FakeResponse(202),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None, poll_max=3)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    with pytest.raises(SamExtractError, match="poll budget"):
        list(reader.records())


def test_records_bounds_max_records_across_population(monkeypatch):
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                payload={"totalRecords": 3, "download": "https://api.sam.gov/x/f.json?api_key=REPLACE_WITH_API_KEY"},
            ),
            _FakeResponse(200, content=json.dumps([_entity("A"), _entity("B"), _entity("C")]).encode()),
        ]
    )
    reader = SamBulkExtract(api_key="secret", sleep=lambda _: None, max_records=2)
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    assert _ueis(reader.records()) == ["A", "B"]


def test_reader_refuses_missing_key():
    with pytest.raises(SamExtractError, match="SAM-authorized"):
        SamBulkExtract(api_key="")


def test_validate_entity_refuses_missing_uei():
    with pytest.raises(SamExtractError, match="ueiSAM"):
        validate_entity({"entityRegistration": {}})
