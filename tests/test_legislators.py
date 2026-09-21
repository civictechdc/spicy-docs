"""Community legislators crosswalk: shape rules, indexes, bounds and mocked acquisition.

Pins the parsed record shape (optional id fields, both FEC candidate-id forms,
district kept as the publisher's string), refusals that name the offending
record and field, the byte and record bounds, the two excerpt indexes, and
mocked acquisition including keyless capture and 401/403 handling. Refusal
tests mutate ``base_row`` rather than the real excerpts.
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
    LegislatorsRefusedError,
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
    """Every field of a well-formed record round-trips, and a sen term carries no district."""
    result = parse_legislators(encoded([base_row()]), max_bytes=BOUND)
    (record,) = result.records
    assert record.bioguide == "T000001" and record.lis == "S001"
    assert record.fec == ("S8WA00194",)
    assert (record.icpsr, record.govtrack, record.opensecrets, record.wikidata) == (12345, 400001, "N00000001", "Q1")
    assert (record.name_first, record.name_last) == ("Test", "Legislator")
    (term,) = record.terms
    assert (term.type, term.start, term.end, term.state) == ("sen", "2001-01-03", "2007-01-03", "WA")
    assert term.party == "Democrat"
    assert term.district is None  # a "sen" term carries no district in the raw


def test_a_rep_terms_district_is_kept_as_the_publisher_spelled_string():
    """A rep term's district keeps the publisher's string, so at-large 0 stays ``"0"``; a missing party is ``None``."""
    row = base_row()
    row["terms"][0].update({"type": "rep", "state": "VT", "district": 0})  # at-large: 0, not falsy-absent
    del row["terms"][0]["party"]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    term = result.records[0].terms[0]
    assert term.district == "0" and term.party is None


@pytest.mark.parametrize("field", ["lis", "fec", "icpsr", "govtrack", "opensecrets", "wikidata"])
def test_absent_optional_id_fields_are_none_or_empty_not_refused(field):
    """An absent optional id field is ``None`` or empty rather than a refusal."""
    row = base_row()
    del row["id"][field]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    record = result.records[0]
    assert getattr(record, field) in (None, ())


def test_a_term_with_no_end_date_parses_as_in_progress_not_a_refusal():
    """A term with no end date parses as in progress, not as a refusal."""
    row = base_row()
    del row["terms"][0]["end"]
    result = parse_legislators(encoded([row]), max_bytes=BOUND)
    assert result.records[0].terms[0].end is None


@pytest.mark.parametrize("fec_id", ["S8WA00194", "H2CA06028", "P80003023", "P00003483"])
def test_both_real_fec_candidate_id_shapes_are_accepted(fec_id):
    """Both real FEC id shapes are accepted: congressional ids embed a state and presidential ids do not."""
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
        (lambda r: r["terms"][0].__setitem__("end", "2001-1-3"), "end must be an ISO date"),
        (lambda r: r["terms"][0].__setitem__("start", "2026-13-45"), "not a real calendar date"),
        (lambda r: r["terms"][0].__setitem__("end", "2026-02-30"), "not a real calendar date"),
        (lambda r: r["terms"][0].pop("state"), "non-empty state"),
        (lambda r: r["terms"][0].__setitem__("state", ""), "non-empty state"),
        (lambda r: r["terms"][0].__setitem__("party", 1), "non-string party"),
        (lambda r: r["terms"][0].__setitem__("district", "4"), "district must be an integer"),
        (lambda r: r["terms"][0].__setitem__("district", True), "district must be an integer"),
        (lambda r: r["terms"].__setitem__(0, "not-an-object"), "must be an object"),
    ],
)
def test_record_shape_refusals_name_the_offending_record(mutate, message):
    """Each shape violation refuses with its own message and names ``record 0``."""
    row = base_row()
    mutate(row)
    with pytest.raises(LegislatorsSourceError, match=message) as raised:
        parse_legislators(encoded([row]), max_bytes=BOUND)
    assert "record 0" in str(raised.value)


@pytest.mark.parametrize("row", [1, "x", None, []])
def test_a_record_that_is_not_a_json_object_refuses(row):
    """A non-object record refuses as ``record 0 must be a JSON object``."""
    with pytest.raises(LegislatorsSourceError, match="record 0 must be a JSON object"):
        parse_legislators(encoded([row]), max_bytes=BOUND)


def test_duplicate_bioguide_refuses_naming_the_repeating_record():
    """A repeated bioguide id refuses and names the repeating record."""
    rows = [base_row(), base_row()]
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats bioguide id 'T000001'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


def test_duplicate_lis_refuses_naming_the_repeating_record():
    """A repeated LIS id refuses and names the repeating record."""
    rows = [base_row(), base_row()]
    rows[1]["id"]["bioguide"] = "T000002"
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats LIS id 'S001'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


def test_duplicate_fec_id_refuses_naming_the_repeating_record():
    """A repeated FEC id refuses and names the repeating record."""
    rows = [base_row(), base_row()]
    rows[1]["id"].update(bioguide="T000002", lis="S002")
    with pytest.raises(LegislatorsSourceError, match="record 1 repeats FEC id 'S8WA00194'"):
        parse_legislators(encoded(rows), max_bytes=BOUND)


@pytest.mark.parametrize("payload", [b"{}", b"null", b'"x"', b"[", b""])
def test_a_body_that_is_not_a_json_list_refuses(payload):
    """A body that is not a JSON list refuses."""
    with pytest.raises(LegislatorsSourceError):
        parse_legislators(payload, max_bytes=BOUND)


def test_an_empty_list_is_a_requested_empty_observation_not_a_refusal():
    """An empty list is a requested-empty observation, not a refusal."""
    assert parse_legislators(b"[]", max_bytes=BOUND).records == ()


# --- bounds ------------------------------------------------------------------------


@pytest.mark.parametrize("max_bytes", [0, True, MAX_HISTORICAL_BYTES + 1])
def test_max_bytes_bound_is_explicit(max_bytes):
    """``max_bytes`` refuses zero, booleans and values above the historical ceiling."""
    with pytest.raises(LegislatorsSourceError, match="max_bytes"):
        parse_legislators(encoded([base_row()]), max_bytes=max_bytes)


def test_a_body_larger_than_max_bytes_refuses():
    """A body larger than ``max_bytes`` refuses."""
    payload = encoded([base_row()])
    with pytest.raises(LegislatorsSourceError):
        parse_legislators(payload, max_bytes=len(payload) - 1)


@pytest.mark.parametrize("max_records", [0, True, MAX_RECORDS_CAP + 1])
def test_max_records_bound_is_explicit(max_records):
    """``max_records`` refuses zero, booleans and values above the cap."""
    with pytest.raises(LegislatorsSourceError, match="max_records"):
        parse_legislators(encoded([base_row()]), max_bytes=BOUND, max_records=max_records)


def test_more_records_than_max_records_refuses():
    """More records than ``max_records`` refuses."""
    second = base_row()
    second["id"]["bioguide"] = "T000002"
    with pytest.raises(LegislatorsSourceError, match="max_records"):
        parse_legislators(encoded([base_row(), second]), max_bytes=BOUND, max_records=1)


# --- indexes and shape, against the real excerpts -----------------------------------


def test_current_excerpt_parses_and_indexes_every_kept_shape():
    """The current excerpt parses to five records indexed by bioguide, LIS and FEC, including a dual-FEC senator."""
    result = parse_legislators(CURRENT_EXCERPT, max_bytes=BOUND)
    assert len(result.records) == 5
    assert set(result.by_bioguide) == {"C000127", "S000033", "W000805", "A000055", "G000607"}
    warner = result.by_bioguide["W000805"]
    assert warner.lis == "S327" and warner.fec == ("S6VA00093", "P80003023")
    assert result.by_lis["S327"] is warner
    assert result.by_fec["P80003023"] is warner
    assert warner.terms[-1].party == "Democrat" and warner.terms[-1].district is None  # senator: no district
    aderholt = result.by_bioguide["A000055"]
    assert aderholt.lis is None and aderholt.fec == ("H6AL04098",)
    assert aderholt.terms[-1].party == "Republican" and aderholt.terms[-1].district == "4"
    gallagher = result.by_bioguide["G000607"]
    assert gallagher.wikidata is None and gallagher.lis is None
    assert len(result.by_lis) == 3  # Cantwell, Sanders, Warner


def test_historical_excerpt_parses_and_carries_the_former_senator_crosswalk():
    """The historical excerpt parses to twenty records with former-senator LIS/FEC crosswalks and a party-less term."""
    result = parse_legislators(HISTORICAL_EXCERPT, max_bytes=BOUND)
    assert len(result.records) == 20
    graham = result.by_bioguide["G000359"]
    assert graham.lis == "S293" and result.by_lis["S293"] is graham
    assert graham.terms[-1].end == "2026-07-11", "left office three months before this capture"
    bassett = result.by_bioguide["B000226"]
    assert bassett.lis is None and bassett.fec == ()
    bland = result.by_bioguide["B000546"]
    assert bland.terms[0].type == "rep" and bland.lis is None
    assert bland.terms[0].party is None  # 1st Congress; its term carries no party in the raw
    assert bland.terms[0].district == "9"
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
    """The keyless acquirer captures the current route's exact bytes with identity encoding and no credential header."""
    transport = Transport(response(CURRENT_EXCERPT))
    with LegislatorsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_current()
    assert result.capture.body == CURRENT_EXCERPT and result.capture.requested_url == LEGISLATORS_CURRENT_URL
    assert len(result.file.records) == 5 and result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert "x-api-key" not in transport.calls[0].headers and "authorization" not in transport.calls[0].headers


def test_acquire_current_refuses_a_file_with_no_lis_entries():
    """A current file whose records carry no ``id.lis`` refuses, since sitting senators always have one."""
    row = base_row()
    del row["id"]["lis"]
    transport = Transport(response(encoded([row])))
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(LegislatorsSourceError, match="no id.lis"),
    ):
        source.acquire_current()


def test_acquirer_captures_exact_historical_bytes_at_its_own_bound():
    """The historical route captures its exact bytes under its own byte bound."""
    transport = Transport(response(HISTORICAL_EXCERPT))
    with LegislatorsAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_historical()
    assert result.capture.body == HISTORICAL_EXCERPT and result.capture.requested_url == LEGISLATORS_HISTORICAL_URL
    assert len(result.file.records) == 20


def test_a_call_may_narrow_the_byte_allowance_but_never_raise_it():
    """A call may narrow the byte allowance but cannot raise it past the budget."""
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
    """A 404/410, wrong content type or non-list JSON raises the family's own error and records the operation."""
    transport = Transport(answer)
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(error, match=message) as raised,
    ):
        source.acquire_current()
    assert raised.value.legislators_acquisition["operation"] == "current"
    assert len(transport.calls) == 1


def test_a_malformed_200_retains_its_exact_bytes_as_refused_evidence():
    """A malformed 200 keeps its exact bytes as refused evidence."""
    body = b'[{"id": {"bioguide": "X000001"}, "name": {}, "terms": []}]'
    transport = Transport(response(body))
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(LegislatorsSourceError) as raised,
    ):
        source.acquire_current()
    assert raised.value.refused_response.response_bytes == body


@pytest.mark.parametrize("status", [401, 403])
def test_a_public_access_refusal_on_a_keyless_route_is_named_not_a_credential_refusal(status):
    """A keyless 401/403 is this family's own ``LegislatorsSourceError``, not ``CredentialRefusedError``,
    and keeps its bytes and URL.
    """
    body = b"rate limited"
    transport = Transport(response(body, status, content_type="text/plain"))
    with (
        LegislatorsAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(LegislatorsRefusedError) as raised,
    ):
        source.acquire_current()
    assert isinstance(raised.value, LegislatorsSourceError)
    assert not isinstance(raised.value, CredentialRefusedError)
    assert raised.value.url == LEGISLATORS_CURRENT_URL
    assert raised.value.legislators_acquisition["operation"] == "current"
    refusal = raised.value.refused_response
    assert refusal.response_bytes == body and refusal.request_key == LEGISLATORS_CURRENT_URL


def test_the_historical_route_is_bounded_separately_from_the_current_route():
    """The historical route is bounded separately from the current route."""
    oversized_budget = LegislatorsBudget(
        3, len(CURRENT_EXCERPT), 10, 0, max_historical_bytes=len(HISTORICAL_EXCERPT) - 1
    )
    with (
        LegislatorsAcquirer(budget=oversized_budget, transport=Transport(response(HISTORICAL_EXCERPT))) as source,
        pytest.raises(LegislatorsSourceError),
    ):
        source.acquire_historical()


def test_budget_and_client_configuration_are_explicit():
    """Budget fields reject zero, negative or over-ceiling values; the acquirer takes a budget object, not a tuple."""
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
    """Importing the parser succeeds with httpx blocked."""
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
