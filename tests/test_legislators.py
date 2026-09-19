"""Community legislators crosswalk: shape rules, indexes, bounds and mocked acquisition.

``tests/fixtures/legislators/README.md`` documents where the two excerpt files
came from and why each kept record is in them. The refusal tests below mutate
a small synthetic-but-realistic record (``base_row``) rather than the real
excerpts, so a shape violation is isolated to exactly the field under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.legislators import (
    DEFAULT_MAX_CURRENT_BYTES,
    LEGISLATORS_CURRENT_URL,
    LEGISLATORS_HISTORICAL_URL,
    MAX_HISTORICAL_BYTES,
    MAX_RECORDS_CAP,
    LegislatorsAcquirer,
    LegislatorsBudget,
    LegislatorsSourceError,
    LegislatorsUnavailableError,
    parse_legislators,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "legislators"
CURRENT_EXCERPT = (FIXTURES / "legislators-current-excerpt.json").read_bytes()
HISTORICAL_EXCERPT = (FIXTURES / "legislators-historical-excerpt.json").read_bytes()

BOUND = MAX_HISTORICAL_BYTES  # generous; individual tests narrow it where the bound itself is under test


def base_row() -> dict:
    return {
        "id": {
            "bioguide": "T000001",
            "lis": "S001",
            "fec": ["S8WA00194"],
            "govtrack": 400001,
            "icpsr": 12345,
            "opensecrets": "N00000001",
            "wikidata": "Q1",
        },
        "name": {"first": "Test", "last": "Legislator"},
        "terms": [{"type": "sen", "start": "2001-01-03", "end": "2007-01-03", "state": "WA", "party": "Democrat"}],
    }


def encoded(rows: list) -> bytes:
    return json.dumps(rows, ensure_ascii=False).encode()


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


# --- shape: a valid record, every optional field, both FEC id shapes -------------


def test_a_well_formed_record_round_trips_every_field():
    result = parse_legislators(encoded([base_row()]), max_bytes=BOUND)
    (record,) = result.records
    assert record.bioguide == "T000001" and record.lis == "S001"
    assert record.fec == ("S8WA00194",)
    assert (record.icpsr, record.govtrack, record.opensecrets, record.wikidata) == (12345, 400001, "N00000001", "Q1")
    assert (record.name_first, record.name_last) == ("Test", "Legislator")
    (term,) = record.terms
    assert (term.type, term.start, term.end, term.state, term.party) == (
        "sen",
        "2001-01-03",
        "2007-01-03",
        "WA",
        "Democrat",
    )


@pytest.mark.parametrize("field", ["lis", "fec", "icpsr", "govtrack", "opensecrets", "wikidata"])
def test_absent_optional_id_fields_are_none_or_empty_not_refused(field):
    row = base_row()
    del row["id"][field]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    record = result.records[0]
    assert getattr(record, field) in (None, ())


def test_a_term_with_no_party_parses_as_none_not_a_refusal():
    """The 1st Congress predates political parties; a missing party is a fact. See B000546 in the fixture."""
    row = base_row()
    del row["terms"][0]["party"]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    assert result.records[0].terms[0].party is None


@pytest.mark.parametrize("fec_id", ["S8WA00194", "H2CA06028", "P80003023", "P00003483"])
def test_both_real_fec_candidate_id_shapes_are_accepted(fec_id):
    """Congressional ids embed a state; presidential ids do not. Both are real FEC ids; see the module docstring."""
    row = base_row()
    row["id"]["fec"] = [fec_id]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    assert result.records[0].fec == (fec_id,)


# --- shape: refusals name the offending record and field -------------------------


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda r: r["id"].pop("bioguide"), "non-empty id.bioguide"),
        (lambda r: r["id"].__setitem__("bioguide", ""), "non-empty id.bioguide"),
        (lambda r: r["id"].__setitem__("bioguide", 5), "non-empty id.bioguide"),
        (lambda r: r["id"].__setitem__("lis", "S12"), "not shaped like S###"),
        (lambda r: r["id"].__setitem__("lis", "A123"), "not shaped like S###"),
        (lambda r: r["id"].__setitem__("lis", 123), "not shaped like S###"),
        (lambda r: r["id"].__setitem__("fec", ["bogus"]), "unrecognized FEC candidate id shape"),
        (lambda r: r["id"].__setitem__("fec", ["S8WA0019"]), "unrecognized FEC candidate id shape"),
        (lambda r: r["id"].__setitem__("fec", ["P8000302"]), "unrecognized FEC candidate id shape"),
        (lambda r: r["id"].__setitem__("fec", "S8WA00194"), "not a list of strings"),
        (lambda r: r["id"].__setitem__("fec", [1]), "not a list of strings"),
        (lambda r: r["id"].__setitem__("icpsr", "12345"), "non-integer id.icpsr"),
        (lambda r: r["id"].__setitem__("opensecrets", 1), "non-string id.opensecrets"),
        (lambda r: r["id"].__setitem__("wikidata", 1), "non-string id.wikidata"),
        (lambda r: r.pop("id"), "is missing id"),
        (lambda r: r.__setitem__("id", []), "is missing id"),
        (lambda r: r.pop("name"), "missing name"),
        (lambda r: r["name"].__setitem__("first", ""), "non-empty name.first"),
        (lambda r: r["name"].__setitem__("last", 1), "non-empty name.last"),
        (lambda r: r.__setitem__("terms", []), "non-empty terms list"),
        (lambda r: r.pop("terms"), "non-empty terms list"),
        (lambda r: r["terms"][0].__setitem__("type", "del"), "must be 'rep' or 'sen'"),
        (lambda r: r["terms"][0].pop("type"), "must be 'rep' or 'sen'"),
        (lambda r: r["terms"][0].__setitem__("start", "2001-1-3"), "start must be an ISO date"),
        (lambda r: r["terms"][0].pop("end"), "end must be an ISO date"),
        (lambda r: r["terms"][0].pop("state"), "non-empty state"),
        (lambda r: r["terms"][0].__setitem__("state", ""), "non-empty state"),
        (lambda r: r["terms"][0].__setitem__("party", 1), "non-string party"),
        (lambda r: r["terms"].__setitem__(0, "not-an-object"), "must be an object"),
    ],
)
def test_record_shape_refusals_name_the_offending_record(mutate, message):
    row = base_row()
    mutate(row)
    with pytest.raises(LegislatorsSourceError, match=message) as raised:
        parse_legislators(encoded([row]), max_bytes=BOUND)
    assert "record 0" in str(raised.value)


@pytest.mark.parametrize("row", [1, "x", None, []])
def test_a_record_that_is_not_a_json_object_refuses(row):
    with pytest.raises(LegislatorsSourceError, match="record 0 must be a JSON object"):
        parse_legislators(encoded([row]), max_bytes=BOUND)


def test_duplicate_bioguide_refuses_naming_the_repeating_record():
    rows = [base_row(), base_row()]
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats bioguide id 'T000001'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


def test_duplicate_lis_refuses_naming_the_repeating_record():
    rows = [base_row(), base_row()]
    rows[1]["id"]["bioguide"] = "T000002"
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats LIS id 'S001'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


def test_duplicate_fec_id_refuses_naming_the_repeating_record():
    rows = [base_row(), base_row()]
    rows[1]["id"].update(bioguide="T000002", lis="S002")
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats FEC id 'S8WA00194'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


@pytest.mark.parametrize("payload", [b"{}", b"null", b'"x"', b"[", b""])
def test_a_body_that_is_not_a_json_list_refuses(payload):
    with pytest.raises(LegislatorsSourceError):
        parse_legislators(payload, max_bytes=BOUND)


def test_an_empty_list_is_a_requested_empty_observation_not_a_refusal():
    assert parse_legislators(b"[]", max_bytes=BOUND).records == ()


# --- bounds ------------------------------------------------------------------------


@pytest.mark.parametrize("max_bytes", [0, True, MAX_HISTORICAL_BYTES + 1])
def test_max_bytes_bound_is_explicit(max_bytes):
    with pytest.raises(LegislatorsSourceError, match="max_bytes"):
        parse_legislators(encoded([base_row()]), max_bytes=max_bytes)


def test_a_body_larger_than_max_bytes_refuses():
    payload = encoded([base_row()])
    with pytest.raises(LegislatorsSourceError):
        parse_legislators(payload, max_bytes=len(payload) - 1)


@pytest.mark.parametrize("max_records", [0, True, MAX_RECORDS_CAP + 1])
def test_max_records_bound_is_explicit(max_records):
    with pytest.raises(LegislatorsSourceError, match="max_records"):
        parse_legislators(encoded([base_row()]), max_bytes=BOUND, max_records=max_records)


def test_more_records_than_max_records_refuses():
    second = base_row()
    second["id"]["bioguide"] = "T000002"
    with pytest.raises(LegislatorsSourceError, match="max_records"):
        parse_legislators(encoded([base_row(), second]), max_bytes=BOUND, max_records=1)


# --- indexes and shape, against the real excerpts -----------------------------------


def test_current_excerpt_parses_and_indexes_every_kept_shape():
    result = parse_legislators(CURRENT_EXCERPT, max_bytes=BOUND)
    assert len(result.records) == 5
    assert set(result.by_bioguide) == {"C000127", "S000033", "W000805", "A000055", "G000607"}
    warner = result.by_bioguide["W000805"]
    assert warner.lis == "S327" and warner.fec == ("S6VA00093", "P80003023")
    assert result.by_lis["S327"] is warner
    assert result.by_fec["P80003023"] is warner
    aderholt = result.by_bioguide["A000055"]
    assert aderholt.lis is None and aderholt.fec == ("H6AL04098",)
    gallagher = result.by_bioguide["G000607"]
    assert gallagher.wikidata is None and gallagher.lis is None
    assert len(result.by_lis) == 3  # Cantwell, Sanders, Warner


def test_historical_excerpt_parses_and_carries_the_former_senator_crosswalk():
    result = parse_legislators(HISTORICAL_EXCERPT, max_bytes=BOUND)
    assert len(result.records) == 20
    graham = result.by_bioguide["G000359"]
    assert graham.lis == "S293" and result.by_lis["S293"] is graham
    assert graham.terms[-1].end == "2026-07-11", "left office three months before this capture"
    bassett = result.by_bioguide["B000226"]
    assert bassett.lis is None and bassett.fec == ()
    bland = result.by_bioguide["B000546"]
    assert bland.terms[0].party is None
    mccain = result.by_bioguide["M000303"]
    assert "P80002801" in mccain.fec and result.by_fec["P80002801"] is mccain
    assert len(result.by_lis) == 13


# --- acquisition, mocked ------------------------------------------------------------


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def response(body, status=200, *, content_type="application/json; charset=utf-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


BUDGET = LegislatorsBudget(3, DEFAULT_MAX_CURRENT_BYTES, 10, 0)


def test_acquirer_captures_exact_current_bytes_keyless():
    transport = Transport(response(CURRENT_EXCERPT))
    with LegislatorsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_current()
    assert result.capture.body == CURRENT_EXCERPT and result.capture.requested_url == LEGISLATORS_CURRENT_URL
    assert len(result.file.records) == 5 and result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert "x-api-key" not in transport.calls[0].headers and "authorization" not in transport.calls[0].headers


def test_acquirer_captures_exact_historical_bytes_at_its_own_bound():
    transport = Transport(response(HISTORICAL_EXCERPT))
    with LegislatorsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_historical()
    assert result.capture.body == HISTORICAL_EXCERPT and result.capture.requested_url == LEGISLATORS_HISTORICAL_URL
    assert len(result.file.records) == 20


def test_a_call_may_narrow_the_byte_allowance_but_never_raise_it():
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=Transport(response(CURRENT_EXCERPT))) as source,
        pytest.raises(LegislatorsSourceError),
    ):
        source.acquire_current(max_bytes=len(CURRENT_EXCERPT) - 1)


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(b"not found", 404, content_type="text/html"), LegislatorsUnavailableError, "HTTP 404"),
        (response(b"", 410), LegislatorsUnavailableError, "HTTP 410"),
        (response(b"<html>bad</html>", content_type="text/html"), LegislatorsSourceError, "Content-Type differs"),
        (response(b"{}", content_type="application/json"), LegislatorsSourceError, "must be a JSON list"),
    ],
)
def test_wrong_shape_or_unavailable_never_returns_a_file(answer, error, message):
    transport = Transport(answer)
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(error, match=message) as raised,
    ):
        source.acquire_current()
    assert raised.value.legislators_acquisition["operation"] == "current"
    assert len(transport.calls) == 1


def test_a_malformed_200_retains_its_exact_bytes_as_refused_evidence():
    body = b'[{"id": {"bioguide": "X000001"}, "name": {}, "terms": []}]'
    transport = Transport(response(body))
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(LegislatorsSourceError) as raised,
    ):
        source.acquire_current()
    assert raised.value.refused_response.response_bytes == body


@pytest.mark.parametrize("status", [401, 403])
def test_a_public_access_refusal_on_a_keyless_route_retains_its_body(status):
    body = b"rate limited"
    transport = Transport(response(body, status, content_type="text/plain"))
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(CredentialRefusedError) as raised,
    ):
        source.acquire_current()
    refusal = raised.value.refused_response
    assert refusal.response_bytes == body and refusal.request_key == LEGISLATORS_CURRENT_URL


def test_the_historical_route_is_bounded_separately_from_the_current_route():
    oversized_budget = LegislatorsBudget(
        3, len(CURRENT_EXCERPT), 10, 0, max_historical_bytes=len(HISTORICAL_EXCERPT) - 1
    )
    with (
        LegislatorsAcquirer(budget=oversized_budget, transport=Transport(response(HISTORICAL_EXCERPT))) as source,
        pytest.raises(LegislatorsSourceError),
    ):
        source.acquire_historical()


def test_budget_and_client_configuration_are_explicit():
    for fields in (
        {"max_requests": 0},
        {"max_bytes": 0},
        {"max_historical_bytes": MAX_HISTORICAL_BYTES + 1},
        {"timeout_seconds": 0},
        {"min_request_interval_seconds": -1},
    ):
        with pytest.raises(ValueError):
            LegislatorsBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        LegislatorsAcquirer(budget=(3, 4096, 7, 0), transport=Transport())


def test_parser_import_does_not_require_httpx():
    code = """
import importlib.abc
import sys
class NoHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "httpx" or fullname.startswith("httpx."):
            raise AssertionError("core parser imported HTTPX")
sys.meta_path.insert(0, NoHttpx())
from spicy_docs.sources.legislators import parse_legislators
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


# --- live: the real routes, bounded by the acquirer's own budget -------------------


@pytest.mark.integration
def test_live_acquisition_meets_the_2026_09_18_measured_floor():
    """Live counts only ever grow between captures; a regression below the pin is a real signal."""
    budget = LegislatorsBudget(
        max_requests=2, max_bytes=DEFAULT_MAX_CURRENT_BYTES, timeout_seconds=60, min_request_interval_seconds=1.0
    )
    with LegislatorsAcquirer(budget=budget) as source:
        current = source.acquire_current()
        historical = source.acquire_historical()
    assert len(current.file.records) >= 539
    assert len(current.file.by_lis) >= 100
    assert len(current.file.by_fec) >= 537
    assert len(historical.file.records) >= 12231
    assert len(historical.file.by_lis) >= 228
    assert len(historical.file.by_fec) >= 995
    assert current.capture.sha256.startswith("sha256:")
    assert historical.capture.sha256.startswith("sha256:")
