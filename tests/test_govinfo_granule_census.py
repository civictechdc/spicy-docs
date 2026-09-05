"""Fixture coverage for ``tools/govinfo_granule_census.py``.

The census exists to size a publisher-side identifier defect, so its tests are
mostly about the ways a census can lie: reporting missing metadata as a
mismatch, normalising a difference away, spending a credential it was
authorized not to spend, or finishing clean because every request was refused.

No network. Every request is served by an ``httpx.MockTransport`` returning
MODS XML shaped like the saved sample at
``receipts/govinfo-mods-sample-FR-1994-01-03.xml``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.source_native_release_fixtures import records_release
from tools.govinfo_granule_census import (
    CredentialRefusedError,
    _granules_from_mods,
    _read_api_key,
    census,
)

MODS_NS = 'xmlns="http://www.loc.gov/mods/v3"'


def _line(number: str, date: str) -> dict[str, Any]:
    return {
        "sourceRecordId": f"{number}@{date}",
        "record": {"document_number": number, "publication_date": date},
    }


def _mods(granules: list[str] | list[tuple[str, str]]) -> bytes:
    """One issue's MODS record, in the shape the real sample uses."""
    parts = []
    for entry in granules:
        access, frdoc = entry if isinstance(entry, tuple) else (entry, entry)
        parts.append(
            f'<relatedItem type="constituent" ID="id-{access}">'
            f'<identifier type="FR Doc No.">{frdoc}</identifier>'
            f"<extension><accessId>{access}</accessId></extension>"
            f"</relatedItem>"
        )
    return f'<mods {MODS_NS}>{"".join(parts)}</mods>'.encode()


def _transport(pages: dict[str, bytes], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        date = request.url.path.rsplit("/", 2)[-2].removeprefix("FR-")
        if date not in pages:
            return httpx.Response(404, text="no such package")
        return httpx.Response(200, content=pages[date])

    return httpx.MockTransport(handler)


def _run(tmp_path: Path, records, pages, *, seen=None) -> list[dict[str, Any]]:
    root, blobs = records_release(tmp_path, "release", records)
    output = tmp_path / "out.jsonl"
    census(
        root, blobs, output,
        api_key=None, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
        transport=_transport(pages, seen if seen is not None else []),
    )
    return [json.loads(line) for line in output.read_text().splitlines() if line.strip()]


def test_the_fused_granule_is_reported_unmatched_in_both_directions(tmp_path: Path) -> None:
    """The 95-8641 shape: our clean number, GPO's fused granule id, no repair."""
    rows = _run(
        tmp_path,
        [_line("95-8641", "1995-04-10"), _line("95-8642", "1995-04-10")],
        {"1995-04-10": _mods(["95-8641-Filed", "95-8642"])},
    )

    assert rows[0]["status"] == "listed"
    assert rows[0]["matched"] == 1
    assert rows[0]["ourNumbersUnmatched"] == ["95-8641"]
    assert rows[0]["granulesUnmatched"] == ["95-8641-Filed"]


def test_the_census_keys_on_the_granule_id_not_the_parsed_document_number(
    tmp_path: Path,
) -> None:
    """Keying on FR Doc No. would compare our numbers against numbers.

    The MODS record carries both GPO's accessId and a parsed "FR Doc No.".
    Only the accessId carries the printed-colophon fusion, and only the
    accessId is what a content URL 404s against. A census keyed on the parsed
    number would agree with itself and report nothing.
    """
    rows = _run(
        tmp_path,
        [_line("95-8641", "1995-04-10")],
        {"1995-04-10": _mods([("95-8641-Filed", "95-8641")])},
    )

    assert rows[0]["matched"] == 0
    assert rows[0]["granulesUnmatched"] == ["95-8641-Filed"]


def test_a_missing_package_is_recorded_as_a_failure_not_an_empty_success(
    tmp_path: Path,
) -> None:
    """The keyed route this replaced returned 200 with zero granules for 57% of
    sampled 1994 issues, which recorded as a clean listing. A MODS 404 is a
    failure and stays one."""
    rows = _run(tmp_path, [_line("95-1", "1995-04-10")], {})

    assert rows[0]["status"] == "listing-failed"
    assert rows[0]["httpStatus"] == 404


def test_one_request_per_issue(tmp_path: Path) -> None:
    """A MODS record lists every constituent, so there is no paging to get wrong."""
    seen: list[httpx.Request] = []
    rows = _run(
        tmp_path,
        [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-10")],
        {"1995-04-10": _mods(["95-1", "95-2"])},
        seen=seen,
    )

    assert len(seen) == 1
    assert rows[0]["apiCalls"] == 1
    assert rows[0]["matched"] == 2


def test_no_credential_is_ever_sent(tmp_path: Path) -> None:
    """The run is authorized on spending nothing; nothing may leak a key."""
    seen: list[httpx.Request] = []
    _run(
        tmp_path,
        [_line("95-1", "1995-04-10")],
        {"1995-04-10": _mods(["95-1"])},
        seen=seen,
    )

    assert seen
    for request in seen:
        assert "X-Api-Key" not in request.headers
        assert "api_key" not in str(request.url).lower()


def test_a_401_aborts_the_run_rather_than_being_recorded_and_passed_over(
    tmp_path: Path,
) -> None:
    """A keyless route answering 401 means the premise failed. Stop."""
    root, blobs = records_release(
        tmp_path, "release", [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-11")]
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(CredentialRefusedError, match="supposed to need no credential"):
        census(
            root, blobs, tmp_path / "out.jsonl",
            api_key=None, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
            transport=httpx.MockTransport(handler),
        )

    assert len(seen) == 1


def test_a_403_aborts_and_is_never_retried(tmp_path: Path) -> None:
    root, blobs = records_release(tmp_path, "release", [_line("95-1", "1995-04-10")])
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(403)

    with pytest.raises(CredentialRefusedError):
        census(
            root, blobs, tmp_path / "out.jsonl",
            api_key=None, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
            transport=httpx.MockTransport(handler),
        )

    assert len(attempts) == 1


def test_a_resumed_run_refetches_nothing_already_recorded(tmp_path: Path) -> None:
    records = [_line("95-1", "1995-04-10"), _line("95-2", "1995-04-11")]
    pages = {"1995-04-10": _mods(["95-1"]), "1995-04-11": _mods(["95-2"])}
    root, blobs = records_release(tmp_path, "release", records)
    output = tmp_path / "out.jsonl"
    output.write_text(json.dumps({"publicationDate": "1995-04-10", "status": "listed"}) + "\n")

    seen: list[httpx.Request] = []
    census(
        root, blobs, output,
        api_key=None, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
        transport=_transport(pages, seen),
    )

    assert [str(r.url).split("/FR-")[1][:10] for r in seen] == ["1995-04-11"]


def test_the_through_date_bounds_the_run(tmp_path: Path) -> None:
    records = [_line("99-1", "1999-12-31"), _line("00-1", "2000-01-03")]
    pages = {"1999-12-31": _mods(["99-1"]), "2000-01-03": _mods(["00-1"])}
    root, blobs = records_release(tmp_path, "release", records)
    seen: list[httpx.Request] = []
    census(
        root, blobs, tmp_path / "out.jsonl",
        api_key=None, through="1999-12-31", page_size=1000, min_interval_seconds=0.0,
        transport=_transport(pages, seen),
    )

    assert len(seen) == 1
    assert "FR-1999-12-31" in str(seen[0].url)


def test_the_parser_reads_the_saved_sample(tmp_path: Path) -> None:
    """Guards the parser against the format, not against my reading of it.

    An XPath built from a prose description of this format found 105
    constituents and zero ids: accessId is an element under extension, not an
    identifier[@type='accessId'].
    """
    sample = (
        Path.home()
        / "Work/corpora/supply-2026-09-02/receipts/govinfo-mods-sample-FR-1994-01-03.xml"
    )
    if not sample.exists():
        pytest.skip("saved MODS sample not present")

    granules = _granules_from_mods(sample.read_bytes())

    assert len(granules) == 105
    assert ("93-31907", "93-31907") in granules


def test_the_key_reader_still_refuses_a_missing_name(tmp_path: Path) -> None:
    """Kept though the route is keyless: an old keyed invocation must fail loudly."""
    env = tmp_path / ".env"
    env.write_text("ZYTE_TOKEN=other\n")

    with pytest.raises(SystemExit, match="API_GOV not found"):
        _read_api_key(env, "API_GOV")


def test_resume_retries_a_failed_listing_instead_of_settling_it(tmp_path) -> None:
    """An outage must not become a permanent census answer.

    govinfo's backend went down mid-run on 2026-09-05 and nine issues were
    written as `listing-failed` with HTTP 502. Resume used to treat every
    recorded date as done, which would have left those nine unvisited forever
    and shipped a transient outage as a finding.
    """
    from tools.govinfo_granule_census import _resume_state

    output = tmp_path / "census.jsonl"
    output.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"publicationDate": "1994-01-03", "status": "listed"},
                {"publicationDate": "1995-07-13", "status": "listing-failed", "httpStatus": 502},
                {"publicationDate": "1995-07-14", "status": "listing-incomplete"},
            )
        )
        + "\n"
    )
    listed, retry = _resume_state(output)
    assert listed == {"1994-01-03"}
    # A short read is untrustworthy for the same reason a failure is.
    assert retry == {"1995-07-13", "1995-07-14"}


def test_a_later_listing_supersedes_an_earlier_failure(tmp_path) -> None:
    """The file is append-only, so the last row for a date is the current one."""
    from tools.govinfo_granule_census import _resume_state

    output = tmp_path / "census.jsonl"
    output.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"publicationDate": "1995-07-13", "status": "listing-failed", "httpStatus": 502},
                {"publicationDate": "1995-07-13", "status": "listed"},
                {"publicationDate": "1995-07-14", "status": "listed"},
                {"publicationDate": "1995-07-14", "status": "listing-failed", "httpStatus": 502},
            )
        )
        + "\n"
    )
    listed, retry = _resume_state(output)
    assert listed == {"1995-07-13"}
    assert retry == {"1995-07-14"}
