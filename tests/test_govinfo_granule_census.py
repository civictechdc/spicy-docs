"""Fixture coverage for ``tools/govinfo_granule_census.py``.

The census exists to size a publisher-side identifier defect, so its tests are
mostly about the ways a census can lie: truncating a listing and reporting the
short list as the issue's granules, normalising a mismatch away, or spending a
quota re-fetching what it already has. Each has a test.

No network. Every request is served by an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.source_native_release_fixtures import records_release
from tools.govinfo_granule_census import CredentialRefusedError, _read_api_key, census

KEY = "test-key-not-a-real-one"


def _line(number: str, date: str) -> dict[str, Any]:
    return {
        "sourceRecordId": f"{number}@{date}",
        "record": {"document_number": number, "publication_date": date},
    }


def _env(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body)
    return path


def _transport(pages: dict[str, dict[str, Any]], seen: list[httpx.Request]) -> httpx.MockTransport:
    """Serve ``pages[date][request_mark]``.

    Keyed by the mark the client SENDS, not the one a response carries: govinfo
    returns the mark for the next page, so keying on the response's own mark
    serves the same page forever. An earlier version of this fixture did
    exactly that and failed a passing tool -- the loop guard had correctly
    stopped on the repeat.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        date = request.url.path.rsplit("/", 2)[-2].removeprefix("FR-")
        if date not in pages:
            return httpx.Response(404, json={"message": "no such package"})
        mark = request.url.params.get("offsetMark", "*")
        page = pages[date].get(mark)
        if page is None:
            return httpx.Response(404, json={"message": f"no page at {mark}"})
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


def _run(tmp_path: Path, records, pages, *, out_name="out.jsonl", seen=None) -> list[dict[str, Any]]:
    root, blobs = records_release(tmp_path, "release", records)
    output = tmp_path / out_name
    census(
        root,
        blobs,
        output,
        api_key=KEY,
        through="1999-12-31",
        page_size=1000,
        min_interval_seconds=0.0,
        transport=_transport(pages, seen if seen is not None else []),
    )
    return [json.loads(line) for line in output.read_text().splitlines() if line.strip()]


def test_the_fused_granule_is_reported_unmatched_in_both_directions(tmp_path: Path) -> None:
    """The 95-8641 shape: our clean number, GPO's fused granule, no repair."""
    rows = _run(
        tmp_path,
        [_line("95-8641", "1995-04-10"), _line("95-8642", "1995-04-10")],
        {
            "1995-04-10": {
                "*": {
                    "count": 2,
                    "granules": [{"granuleId": "95-8641-Filed"}, {"granuleId": "95-8642"}],
                    "offsetMark": "end",
                }
            }
        },
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "listed"
    assert rows[0]["matched"] == 1
    assert rows[0]["ourNumbersUnmatched"] == ["95-8641"]
    assert rows[0]["granulesUnmatched"] == ["95-8641-Filed"]


def test_a_short_listing_is_flagged_rather_than_counted_as_mismatches(tmp_path: Path) -> None:
    """Truncation must not masquerade as a publisher defect.

    The issue declares three granules and the page returns one. Reporting the
    other two of our numbers as unmatched would invent a defect out of our own
    incomplete read.
    """
    rows = _run(
        tmp_path,
        [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-10"), _line("95-3", "1995-04-10")],
        {"1995-04-10": {"*": {"count": 3, "granules": [{"granuleId": "95-1"}], "offsetMark": "end"}}},
    )

    assert rows[0]["status"] == "listing-incomplete"
    assert rows[0]["granuleCountDeclaredBySource"] == 3
    assert rows[0]["granuleCount"] == 1


def test_pagination_follows_the_offset_mark_and_terminates(tmp_path: Path) -> None:
    rows = _run(
        tmp_path,
        [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-10")],
        {
            "1995-04-10": {
                "*": {"count": 2, "granules": [{"granuleId": "95-1"}], "offsetMark": "p2", "nextPage": "u"},
                "p2": {"count": 2, "granules": [{"granuleId": "95-2"}], "offsetMark": "end"},
            }
        },
    )

    assert rows[0]["apiCalls"] == 2
    assert rows[0]["status"] == "listed"
    assert rows[0]["matched"] == 2


def test_a_repeated_offset_mark_terminates_rather_than_looping(tmp_path: Path) -> None:
    """A source that keeps handing back the same mark must not spin the quota."""
    rows = _run(
        tmp_path,
        [_line("95-1", "1995-04-10")],
        {
            "1995-04-10": {
                "*": {"count": 99, "granules": [{"granuleId": "95-1"}], "offsetMark": "*", "nextPage": "u"}
            }
        },
    )

    assert rows[0]["apiCalls"] == 1
    assert rows[0]["status"] == "listing-incomplete"


def test_a_missing_package_is_recorded_not_raised(tmp_path: Path) -> None:
    rows = _run(tmp_path, [_line("95-1", "1995-04-10")], {})

    assert rows[0]["status"] == "listing-failed"
    assert rows[0]["httpStatus"] == 404


def test_the_api_key_travels_in_a_header_and_never_in_the_url(tmp_path: Path) -> None:
    """A key in a query string leaks into every log line that records a URL."""
    seen: list[httpx.Request] = []
    _run(
        tmp_path,
        [_line("95-1", "1995-04-10")],
        {"1995-04-10": {"*": {"count": 1, "granules": [{"granuleId": "95-1"}], "offsetMark": "end"}}},
        seen=seen,
    )

    assert seen
    for request in seen:
        assert request.headers["X-Api-Key"] == KEY
        assert KEY not in str(request.url)


def test_a_resumed_run_refetches_nothing_already_recorded(tmp_path: Path) -> None:
    records = [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-11")]
    pages = {
        "1995-04-10": {"*": {"count": 1, "granules": [{"granuleId": "95-1"}], "offsetMark": "end"}},
        "1995-04-11": {"*": {"count": 1, "granules": [{"granuleId": "95-2"}], "offsetMark": "end"}},
    }
    root, blobs = records_release(tmp_path, "release", records)
    output = tmp_path / "out.jsonl"
    output.write_text(json.dumps({"publicationDate": "1995-04-10", "status": "listed"}) + "\n")

    seen: list[httpx.Request] = []
    census(
        root, blobs, output,
        api_key=KEY, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
        transport=_transport(pages, seen),
    )

    assert [str(r.url).split("/FR-")[1][:10] for r in seen] == ["1995-04-11"]


def test_the_through_date_keeps_the_keyed_quota_off_the_keyless_years(tmp_path: Path) -> None:
    """2000 onward is enumerable from bulk XML without a key; do not spend one."""
    records = [_line("99-1", "1999-12-31"), _line("00-1", "2000-01-03")]
    pages = {
        "1999-12-31": {"*": {"count": 1, "granules": [{"granuleId": "99-1"}], "offsetMark": "end"}},
        "2000-01-03": {"*": {"count": 1, "granules": [{"granuleId": "00-1"}], "offsetMark": "end"}},
    }
    root, blobs = records_release(tmp_path, "release", records)
    seen: list[httpx.Request] = []
    census(
        root, blobs, tmp_path / "out.jsonl",
        api_key=KEY, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
        transport=_transport(pages, seen),
    )

    assert len(seen) == 1
    assert "FR-1999-12-31" in str(seen[0].url)


def test_the_key_is_read_from_the_env_file_by_name(tmp_path: Path) -> None:
    env = _env(tmp_path, "ZYTE_TOKEN=other\nAPI_GOV='quoted-value'\n")

    assert _read_api_key(env, "API_GOV") == "quoted-value"


def test_a_missing_key_name_refuses_rather_than_running_unauthenticated(tmp_path: Path) -> None:
    env = _env(tmp_path, "ZYTE_TOKEN=other\n")

    with pytest.raises(SystemExit, match="API_GOV not found"):
        _read_api_key(env, "API_GOV")


def test_a_401_aborts_the_run_rather_than_being_recorded_and_passed_over(
    tmp_path: Path,
) -> None:
    """The keyless premise failing must stop the census, not become a column.

    A per-issue "listing-failed" row would walk all 1,502 issues collecting
    refusals and hide a change of terms behind zeros that read like coverage.
    A run authorized on "this spends nothing" must not continue once that has
    stopped being true.
    """
    records = [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-11")]
    root, blobs = records_release(tmp_path, "release", records)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"message": "api key required"})

    with pytest.raises(CredentialRefusedError, match="keyless enumeration premise has failed"):
        census(
            root, blobs, tmp_path / "out.jsonl",
            api_key=KEY, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
            transport=httpx.MockTransport(handler),
        )

    # Stopped on the first refusal, not after walking every issue.
    assert len(seen) == 1


def test_a_403_aborts_the_run_too(tmp_path: Path) -> None:
    root, blobs = records_release(tmp_path, "release", [_line("95-1", "1995-04-10")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    with pytest.raises(CredentialRefusedError):
        census(
            root, blobs, tmp_path / "out.jsonl",
            api_key=KEY, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
            transport=httpx.MockTransport(handler),
        )


def test_a_401_is_never_retried(tmp_path: Path) -> None:
    """Retrying a refusal wastes the publisher's time and changes nothing."""
    root, blobs = records_release(tmp_path, "release", [_line("95-1", "1995-04-10")])
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401)

    with pytest.raises(CredentialRefusedError):
        census(
            root, blobs, tmp_path / "out.jsonl",
            api_key=KEY, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
            transport=httpx.MockTransport(handler),
        )

    assert len(attempts) == 1
