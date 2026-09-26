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
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from loguru import logger

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


# -- the trigger-poll-download loop, through httpx's own request building ------------------

# The trigger's real answer (2026-09-23): a sentence, not JSON, and no count.
SENTENCE = (
    "Extract File will be available for download with url: "
    "https://api.sam.gov/entity-information/v4/download-entities?api_key=REPLACE_WITH_API_KEY&token=Tok123 "
    "in some time. If you have requested for an email notification, you will receive it once the file is ready."
)
# The download's real answer while the file generates.
IN_PROGRESS = {
    "httpStatus": "400",
    "title": "Extract File Generation is Still in Progress",
    "detail": "File Processing in Progress. Please check again later ",
    "type": "Still in Progress",
    "errorCode": "FSP",
}
# The download's real answer to an Accept that rules out its gzip, here for a ready file (2026-09-23;
# receipt in corpora/fork-execution-2026-09-21/sam-406-2026-09-23/).
NOT_ACCEPTABLE = {
    "httpStatus": "406 NOT_ACCEPTABLE",
    "title": "Invalid Accept Header",
    "detail": "No acceptable representation",
    "errorCode": "406",
}
# Long enough for scrub_credential's literal pass, which skips keys under 8 characters.
KEY = "sam-test-key-0123"
# The real renewals SAM held twice in the 2007 and 2008 registration-year extracts, 2026-09-26.
SUPERSEDED = json.loads((Path(__file__).parent / "fixtures" / "sam-extract-superseded-2026-09-26.json").read_text())
TRIGGER_DAY = date.fromisoformat(SUPERSEDED["trigger_day"])


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC)


def _admits_gzip(accept: str) -> bool:
    ranges = {part.split(";")[0].strip().lower() for part in accept.split(",")}
    return bool(ranges & {"*/*", "application/*", "application/x-gzip"})


def _extract(*ueis: str, total: int | None = None) -> bytes:
    body = {"totalRecords": len(ueis) if total is None else total, "entityData": [_entity(u) for u in ueis]}
    return gzip.compress(json.dumps(body).encode())


class _Publisher:
    """A MockTransport answering the trigger with SENTENCE and the download from ``downloads`` in turn.

    Like SAM, it refuses a download whose ``Accept`` rules out gzip with 406 before looking at the file.
    Time is its own: sleeps advance ``now``, and so does each request by ``latency`` seconds.
    """

    def __init__(self, *downloads: httpx.Response, trigger: httpx.Response | None = None, latency: float = 0.0):
        self.downloads = list(downloads)
        self.trigger = trigger or httpx.Response(200, text=SENTENCE)
        self.requests: list[httpx.Request] = []
        self.now = 0.0
        self.latency = latency

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.now += self.latency
        if request.url.path.endswith("/entities"):
            return self.trigger
        if not _admits_gzip(request.headers.get("Accept", "")):
            return httpx.Response(406, json=NOT_ACCEPTABLE)
        return self.downloads.pop(0)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def reader(self, **kwargs) -> SamBulkExtract:
        kwargs.setdefault("now", lambda: _at(TRIGGER_DAY))
        return SamBulkExtract(
            api_key=KEY, transport=httpx.MockTransport(self), sleep=self.sleep, clock=lambda: self.now, **kwargs
        )


def test_the_trigger_keeps_its_selection_and_adds_the_key():
    """httpx ``params`` would replace the query; the selection and the key must both arrive."""
    publisher = _Publisher(httpx.Response(200, content=_extract("A")))
    assert _ueis(publisher.reader(year=2026).records()) == ["A"]
    trigger = publisher.requests[0].url.params
    assert (trigger["registrationStatus"], trigger["format"], trigger["api_key"]) == ("A", "json", KEY)
    assert trigger["registrationDate"] == "[01/01/2026,12/31/2026]"
    download = publisher.requests[1].url.params
    assert (download["token"], download["api_key"]) == ("Tok123", KEY)


def test_the_download_polls_through_the_in_progress_answer():
    publisher = _Publisher(
        httpx.Response(400, json=IN_PROGRESS),
        httpx.Response(400, json=IN_PROGRESS),
        httpx.Response(200, content=_extract("A", "B")),
    )
    assert _ueis(publisher.reader().records()) == ["A", "B"]
    assert [request.headers["Accept"] for request in publisher.requests] == ["application/json", "*/*", "*/*", "*/*"]


def test_each_distinct_in_progress_detail_is_logged_once_and_scrubbed():
    """Both scrub passes: the reader's key bare (literal pass) and another key in a URL (pattern pass)."""
    other_key = "other-key-4567890"
    leaky = {**IN_PROGRESS, "detail": f"Still writing for {KEY} at https://api.sam.gov/x?api_key={other_key}"}
    publisher = _Publisher(
        *[httpx.Response(400, json=body) for body in (IN_PROGRESS, IN_PROGRESS, leaky, leaky)],
        httpx.Response(200, content=_extract("A")),
    )
    logged: list[str] = []
    sink = logger.add(logged.append, level="DEBUG", format="{level} {message}")
    try:
        assert _ueis(publisher.reader().records()) == ["A"]
    finally:
        logger.remove(sink)
    assert [line.strip() for line in logged if "still generating" in line] == [
        "DEBUG SAM extract still generating: File Processing in Progress. Please check again later",
        "DEBUG SAM extract still generating: Still writing for <redacted> at https://api.sam.gov/x?api_key=<redacted>",
    ]
    assert not any(KEY in line or other_key in line for line in logged)


def test_any_other_400_refuses():
    publisher = _Publisher(httpx.Response(400, json={"errorCode": "BAD", "title": "Invalid token"}))
    with pytest.raises(SamExtractError, match="HTTP 400"):
        list(publisher.reader().records())


def test_the_wait_is_wall_clock_from_the_trigger_so_hanging_polls_still_end_it():
    """Requests taking 100 s each: the deadline is set before the trigger, so polls start at 100 and 230 s only."""
    publisher = _Publisher(*[httpx.Response(400, json=IN_PROGRESS)] * 10, latency=100.0)
    with pytest.raises(SamExtractError, match="within its 300 s wait; last poll: HTTP 400"):
        list(publisher.reader(max_wait=300.0, poll_interval=30.0).records())
    trigger, *polls = publisher.requests
    assert len(polls) == 2 and publisher.now == 330.0
    assert trigger.extensions["timeout"]["read"] == 120.0
    assert {poll.extensions["timeout"]["read"] for poll in polls} == {30.0}


class _Stalling:
    """SAM answering each trigger with a fresh token, whose file is ready ``ready_after[token]`` seconds later.

    A token absent from ``ready_after`` never finishes. ``late`` maps a token to a file it would
    serve once abandoned, which the reader must never ask for.
    """

    def __init__(self, ready_after: dict[str, float], files: dict[str, bytes], late: dict[str, bytes] | None = None):
        self.tokens = iter(["Tok1", "Tok2", "Tok3", "Tok4"])
        self.ready_after, self.files, self.late = ready_after, files, late or {}
        self.triggered: dict[str, float] = {}
        self.now = 0.0
        self.downloads: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entities"):
            token = next(self.tokens)
            self.triggered[token] = self.now
            return httpx.Response(200, text=SENTENCE.replace("Tok123", token))
        token = request.url.params["token"]
        self.downloads.append(token)
        if token in self.late and max(self.triggered.values()) > self.triggered[token]:
            return httpx.Response(200, content=self.late[token])
        if token in self.ready_after and self.now - self.triggered[token] >= self.ready_after[token]:
            return httpx.Response(200, content=self.files[token])
        return httpx.Response(400, json=IN_PROGRESS)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def reader(self, **kwargs) -> SamBulkExtract:
        return SamBulkExtract(
            api_key=KEY,
            transport=httpx.MockTransport(self),
            sleep=self.sleep,
            clock=lambda: self.now,
            now=lambda: _at(TRIGGER_DAY),
            poll_interval=30.0,
            **kwargs,
        )


def test_a_stalled_trigger_is_abandoned_and_the_selection_triggered_afresh():
    """1968 on 2026-09-26: still generating after an hour, ready 0.5 minutes after a fresh trigger."""
    sam = _Stalling({"Tok2": 30.0}, {"Tok2": _extract("A", "B")})
    reader = sam.reader(attempt_wait=300.0, max_wait=900.0)
    assert _ueis(reader.records()) == ["A", "B"]
    [abandoned] = reader.abandoned
    assert (abandoned["attempt"], abandoned["token"], abandoned["waited_seconds"]) == (1, "Tok1", 300.0)
    assert abandoned["last_poll"] == "HTTP 400" and abandoned["triggered_at"] == _at(TRIGGER_DAY).isoformat()


def test_an_abandoned_token_is_never_read_even_once_its_file_is_ready():
    sam = _Stalling({"Tok2": 60.0}, {"Tok2": _extract("B")}, late={"Tok1": _extract("STALE")})
    reader = sam.reader(attempt_wait=300.0, max_wait=900.0)
    assert _ueis(reader.records()) == ["B"]
    second = sam.downloads.index("Tok2")
    assert "Tok1" not in sam.downloads[second:]


def test_triggers_are_capped_and_each_abandoned_one_is_kept_for_the_refusal():
    sam = _Stalling({}, {})
    reader = sam.reader(attempt_wait=300.0, max_wait=10_000.0, attempts=3)
    with pytest.raises(SamExtractError, match=r"last poll: HTTP 400 \(3 trigger\(s\), each abandoned\)"):
        list(reader.records())
    assert [entry["token"] for entry in reader.abandoned] == ["Tok1", "Tok2", "Tok3"]
    assert set(sam.triggered) == {"Tok1", "Tok2", "Tok3"}


def test_the_default_wait_clears_the_slowest_measured_file_on_every_attempt():
    """2026 was ready 21-46 minutes after one trigger on 2026-09-23; every other year within 3.5."""
    from spicy_docs.sources.sam_extract import EXTRACT_ATTEMPT_WAIT, EXTRACT_ATTEMPTS, EXTRACT_MAX_WAIT

    assert EXTRACT_ATTEMPT_WAIT > 46 * 60
    assert EXTRACT_MAX_WAIT == EXTRACT_ATTEMPTS * EXTRACT_ATTEMPT_WAIT


def _registration(uei: str, eft: str | None = None, updated: str = "2026-09-01", name: str = "X") -> dict:
    return {
        "entityRegistration": {
            "ueiSAM": uei,
            "entityEFTIndicator": eft,
            "lastUpdateDate": updated,
            "legalBusinessName": name,
        }
    }


def _file(records: list[dict], total: int) -> bytes:
    return gzip.compress(json.dumps({"totalRecords": total, "entityData": records}).encode())


def _read(download: bytes) -> list[dict]:
    return list(_Publisher(httpx.Response(200, content=download)).reader().records())


def test_a_file_with_fewer_registrations_than_it_declares_refuses():
    with pytest.raises(SamExtractError, match="fewer than its totalRecords"):
        _read(_file([_registration("A"), _registration("B")], total=3))
    with pytest.raises(SamExtractError, match="states no totalRecords"):
        _read(gzip.compress(json.dumps([_entity("A")]).encode()))


def test_registrations_are_keyed_by_uei_and_eft_indicator():
    """One entity registers once per EFT indicator; both registrations are kept."""
    got = _read(_file([_registration("A", "0001"), _registration("A", "0002"), _registration("B")], total=3))
    assert sorted((r["entityRegistration"]["ueiSAM"], r["entityRegistration"]["entityEFTIndicator"]) for r in got) == [
        ("A", "0001"),
        ("A", "0002"),
        ("B", None),
    ]


def test_a_file_written_while_registrations_change_keeps_the_newest_version_and_may_exceed_its_count():
    """Measured 2026-09-23: 147,250 declared, 147,256 rows, 147,254 registrations, two held twice."""
    older, newer = _registration("A", updated="2026-08-29"), _registration("A", updated="2026-09-16")
    got = _read(_file([older, newer, _registration("B"), _registration("C")], total=2))
    assert sorted(r["entityRegistration"]["ueiSAM"] for r in got) == ["A", "B", "C"]
    assert [r for r in got if r["entityRegistration"]["ueiSAM"] == "A"] == [newer]


def test_identical_repeats_collapse_and_differing_ones_at_one_date_refuse():
    assert len(_read(_file([_registration("A"), _registration("A")], total=1))) == 1
    with pytest.raises(SamExtractError, match="two differing versions"):
        _read(_file([_registration("A", name="X"), _registration("A", name="Y")], total=1))
    with pytest.raises(SamExtractError, match="two differing versions"):
        newer = _registration("A", updated="2026-09-16")
        _read(_file([_registration("A", name="X"), newer, _registration("A", name="Y")], total=1))


def _read_on(download: bytes, day: date) -> tuple[list[dict], SamBulkExtract]:
    reader = _Publisher(httpx.Response(200, content=download)).reader(now=lambda: _at(day))
    return list(reader.records()), reader


@pytest.mark.parametrize("year", ["2007", "2008"])
def test_a_renewal_the_source_still_holds_active_is_credited_toward_the_declared_count(year):
    """Each file declared exactly its rows and held one UEI twice; the entity API held both records Active."""
    older, newer = SUPERSEDED["years"][year]
    others = [_registration(f"OTHER{i}") for i in range(3)]
    got, reader = _read_on(_file([older, *others, newer], total=5), TRIGGER_DAY)
    assert len(got) == 4 and newer in got and older not in got
    prior, kept = older["entityRegistration"], newer["entityRegistration"]
    assert reader.superseded == [
        {
            "uei": kept["ueiSAM"],
            "eft_indicator": None,
            "superseded_last_update": prior["lastUpdateDate"],
            "superseded_expiration": prior["registrationExpirationDate"],
            "kept_last_update": kept["lastUpdateDate"],
            "kept_expiration": kept["registrationExpirationDate"],
            "trigger_day": "2026-09-26",
        }
    ]


@pytest.mark.parametrize("day", [date(2026, 9, 23), date(2026, 9, 24)])
def test_a_version_updated_as_the_file_generates_earns_no_credit(day):
    """A skipped registration plus a mid-write repeat looks like a renewal inside the count; it still refuses."""
    older, newer = SUPERSEDED["years"]["2008"]  # the newer version was updated 2026-09-23
    with pytest.raises(SamExtractError, match="0 concurrent superseded records, fewer than its totalRecords 2"):
        _read_on(_file([older, newer], total=2), day)


def test_a_trigger_naming_no_download_refuses():
    publisher = _Publisher(trigger=httpx.Response(200, text="Please try again later."))
    with pytest.raises(SamExtractError, match="no download URL"):
        list(publisher.reader().records())


def test_an_inline_population_needs_no_download():
    inline = {"totalRecords": 2, "entityData": [_entity("A"), _entity("B")]}
    publisher = _Publisher(trigger=httpx.Response(200, json=inline))
    assert _ueis(publisher.reader().records()) == ["A", "B"]
    assert len(publisher.requests) == 1


def test_max_records_bounds_what_is_emitted():
    publisher = _Publisher(httpx.Response(200, content=_extract("A", "B", "C")))
    assert _ueis(publisher.reader(max_records=2).records()) == ["A", "B"]


def test_reader_refuses_missing_key():
    with pytest.raises(SamExtractError, match="SAM-authorized"):
        SamBulkExtract(api_key="")


def test_validate_entity_refuses_missing_uei():
    with pytest.raises(SamExtractError, match="ueiSAM"):
        validate_entity({"entityRegistration": {}})
