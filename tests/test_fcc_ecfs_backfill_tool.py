"""The FCC ECFS backfill driver plans date slices, resumes verified outputs, and only fetches when told to.

Dry-run is the default and makes no request and no write; execution enumerates
each inclusive-day window through ``FccEcfsReader.iter_filings``, retries failed
windows on resume, and aborts on a credential refusal. ``Publisher`` serves the
counted, filter-honoring ECFS shape the traversal checks.
"""

import hashlib
import json
from datetime import date as Date
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.paged_json import PagedJsonSourceError
from spicy_docs.sources import fcc_ecfs_filings
from spicy_docs.sources.fcc_ecfs import FccEcfsReader
from spicy_docs.transport.credentials import CredentialRefusedError
from tests.test_fcc_ecfs_filings import Publisher
from tools.analysis.fcc_ecfs_backfill import Window, backfill, load_resume, main, plan_slices

KEY = "k3y-abcdef0123456789"
BASE = {"min_interval_seconds": 0, "pause_seconds": 0}


def filing(n: int, day: str = "2026-01-02") -> dict:
    return {
        "id_submission": f"{n:011d}",
        "date_received": f"{day}T03:04:05Z",
        "date_submission": f"{day}T03:{n // 60:02d}:{n % 60:02d}Z",
        "express_comment": 1,
        "documents": [],
    }


def rows(count: int, first: int = 1, day: str = "2026-01-02") -> list[dict]:
    return [filing(first + i, day) for i in range(count)]


def walked(publisher: Publisher, window: str) -> int:
    return sum(1 for call in publisher.calls if call.url.params["date_received"] == window)


def resume_rows(output: Path) -> list[dict]:
    return [json.loads(line) for line in (output / "resume.jsonl").read_text().splitlines() if line.strip()]


def damage_completed_window(output: Path, start: str, end: str, damage: str) -> None:
    target = output / f"filings-{start}-{end}.jsonl"
    if damage == "deleted":
        target.unlink()
    elif damage == "corrupt":
        body = target.read_bytes()
        target.write_bytes(b"!" + body[1:])  # Same size: the digest must be checked.
    else:
        legacy = dict(load_resume(output / "resume.jsonl")[(start, end)])
        legacy.pop("sha256")
        with (output / "resume.jsonl").open("a") as sink:
            sink.write(json.dumps(legacy) + "\n")


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    from spicy_docs.transport import retry

    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_the_plan_covers_the_span_in_contiguous_inclusive_windows():
    assert plan_slices(Date(2026, 1, 1), Date(2026, 1, 17), 7) == [
        Window(Date(2026, 1, 1), Date(2026, 1, 7)),
        Window(Date(2026, 1, 8), Date(2026, 1, 14)),
        Window(Date(2026, 1, 15), Date(2026, 1, 17)),
    ]
    assert plan_slices(Date(2024, 2, 27), Date(2024, 3, 1), 3) == [
        Window(Date(2024, 2, 27), Date(2024, 2, 29)),
        Window(Date(2024, 3, 1), Date(2024, 3, 1)),
    ]
    assert plan_slices(Date(2026, 1, 1), Date(2026, 1, 2), 1) == [
        Window(Date(2026, 1, 1), Date(2026, 1, 1)),
        Window(Date(2026, 1, 2), Date(2026, 1, 2)),
    ]
    with pytest.raises(ValueError):
        plan_slices(Date(2026, 1, 2), Date(2026, 1, 1), 7)
    with pytest.raises(ValueError):
        plan_slices(Date(2026, 1, 1), Date(2026, 1, 2), 0)


def test_the_default_run_is_a_dry_run_that_prints_the_plan_and_writes_nothing(tmp_path, capsys):
    code = main(["--since", "2026-01-01", "--until", "2026-01-10", "--output", str(tmp_path / "run")])
    out = capsys.readouterr().out
    assert code == 0 and "2026-01-01..2026-01-07" in out and "2026-01-08..2026-01-10" in out
    assert "partition by submission time" in out
    assert not (tmp_path / "run").exists()


def test_execution_walks_each_window_and_writes_its_records_with_evidence(tmp_path):
    publisher = Publisher(rows(3) + rows(1, 4, day="2026-01-09"))
    assert (
        backfill(
            since=Date(2026, 1, 1),
            until=Date(2026, 1, 11),
            output=tmp_path,
            api_key=KEY,
            per_page=2,
            transport=publisher,
            **BASE,
        )
        == 0
    )
    first = tmp_path / "filings-2026-01-01-2026-01-07.jsonl"
    second = tmp_path / "filings-2026-01-08-2026-01-11.jsonl"
    assert [json.loads(line)["id_submission"] for line in first.read_text().splitlines()] == [
        "00000000001",
        "00000000002",
        "00000000003",
    ]
    assert len(second.read_text().splitlines()) == 1
    statuses = {row["start"] + ".." + row["end"]: row for row in resume_rows(tmp_path)}
    assert [row["status"] for row in statuses.values()] == ["done", "done"]
    assert statuses["2026-01-01..2026-01-07"]["records"] == 3
    assert statuses["2026-01-08..2026-01-11"]["sha256"] == "sha256:" + hashlib.sha256(second.read_bytes()).hexdigest()


def test_an_empty_window_settles_done_with_no_records(tmp_path):
    assert (
        backfill(
            since=Date(2026, 1, 1),
            until=Date(2026, 1, 1),
            output=tmp_path,
            api_key=KEY,
            transport=Publisher([]),
            **BASE,
        )
        == 0
    )
    assert resume_rows(tmp_path)[0]["status"] == "done" and resume_rows(tmp_path)[0]["records"] == 0


def test_default_pause_is_passed_to_the_sleeper_between_windows(tmp_path):
    pauses = []
    code = backfill(
        since=Date(2026, 1, 1),
        until=Date(2026, 1, 2),
        output=tmp_path,
        api_key=KEY,
        slice_days=1,
        min_interval_seconds=0,
        transport=Publisher([]),
        sleeper=pauses.append,
    )
    assert code == 0 and pauses == [5.0]
    assert [row["status"] for row in resume_rows(tmp_path)] == ["done", "done"]


def test_a_credential_refusal_is_retried_after_the_key_is_repaired(tmp_path):
    arguments = {"since": Date(2026, 1, 1), "until": Date(2026, 1, 1), "output": tmp_path, **BASE}
    refused = httpx.MockTransport(lambda request: httpx.Response(401, stream=httpx.ByteStream(b"refused")))
    assert backfill(**arguments, api_key=KEY, transport=refused) == 2
    assert resume_rows(tmp_path)[-1]["status"] == "refused"
    repaired = Publisher(rows(1, day="2026-01-01"))
    assert backfill(**arguments, api_key="repaired-credential", transport=repaired) == 0
    assert len(repaired.calls) == 1
    assert [row["status"] for row in resume_rows(tmp_path)] == ["refused", "done"]
    assert (tmp_path / "filings-2026-01-01-2026-01-01.jsonl").read_text().strip() == json.dumps(
        filing(1, "2026-01-01"), sort_keys=True
    )


def test_a_crowded_day_completes_by_submission_time_partitions(tmp_path, monkeypatch):
    # Formerly a ceiling-refused day: the counted traversal now proves the partition.
    monkeypatch.setattr(fcc_ecfs_filings, "MAX_RESULT_WINDOW", 8)
    publisher = Publisher(rows(17))
    arguments = {"since": Date(2026, 1, 2), "until": Date(2026, 1, 2), "output": tmp_path, "api_key": KEY, **BASE}
    assert backfill(**arguments, per_page=3, transport=publisher) == 0
    assert resume_rows(tmp_path)[-1]["records"] == 17
    assert any("date_submission" in call.url.params for call in publisher.calls)


def test_resume_settles_done_windows_and_retries_failed_ones(tmp_path):
    publisher = Publisher(rows(3, day="2026-01-01") + rows(1, 4, day="2026-01-03"))
    retained = (json.dumps(filing(4, "2026-01-03"), sort_keys=True) + "\n").encode()
    (tmp_path / "filings-2026-01-03-2026-01-04.jsonl").write_bytes(retained)
    done = {
        "start": "2026-01-03",
        "end": "2026-01-04",
        "status": "done",
        "records": 1,
        "finishedAt": "x",
        "sha256": "sha256:" + hashlib.sha256(retained).hexdigest(),
        "bytes": len(retained),
    }
    (tmp_path / "resume.jsonl").write_text(
        json.dumps({"start": "2026-01-01", "end": "2026-01-02", "status": "failed", "finishedAt": "x"})
        + "\n"
        + json.dumps(done)
        + "\n"
    )
    arguments = {"since": Date(2026, 1, 1), "until": Date(2026, 1, 4), "output": tmp_path, "api_key": KEY, **BASE}
    assert backfill(**arguments, slice_days=2, per_page=2, transport=publisher) == 0
    # The failed window was retried (two pages for three rows); the done one was not re-requested.
    assert walked(publisher, "[gte]2026-01-01[lte]2026-01-03") == 2
    assert walked(publisher, "[gte]2026-01-03[lte]2026-01-05") == 0
    assert load_resume(tmp_path / "resume.jsonl")[("2026-01-01", "2026-01-02")]["status"] == "done"


@pytest.mark.parametrize("damage", ["deleted", "corrupt", "unpinned"])
def test_resume_reacquires_a_done_window_without_its_verified_output(tmp_path, capsys, damage):
    arguments = {"since": Date(2026, 1, 1), "until": Date(2026, 1, 1), "output": tmp_path, "api_key": KEY, **BASE}
    window = "[gte]2026-01-01[lte]2026-01-02"
    assert backfill(**arguments, transport=Publisher(rows(1, day="2026-01-01"))) == 0
    target = tmp_path / "filings-2026-01-01-2026-01-01.jsonl"
    expected = target.read_bytes()
    intact = Publisher([])
    assert backfill(**arguments, transport=intact) == 0
    assert intact.calls == [] and len(resume_rows(tmp_path)) == 1

    damage_completed_window(tmp_path, "2026-01-01", "2026-01-01", damage)
    assert main(["--since", "2026-01-01", "--until", "2026-01-01", "--output", str(tmp_path)]) == 0
    assert "0 already settled" in capsys.readouterr().out
    retried = Publisher(rows(1, day="2026-01-01"))
    assert backfill(**arguments, transport=retried) == 0
    assert walked(retried, window) == 1
    assert target.read_bytes() == expected
    assert resume_rows(tmp_path)[-1]["sha256"] == "sha256:" + hashlib.sha256(expected).hexdigest()


def test_a_credential_refusal_aborts_the_run_and_records_a_scrubbed_row(tmp_path, monkeypatch):
    def refuse(reader, *, received_from, **_):
        raise CredentialRefusedError(f"key {KEY} refused for {received_from}")

    monkeypatch.setattr(FccEcfsReader, "iter_filings", refuse)
    arguments = {"since": Date(2026, 1, 1), "until": Date(2026, 1, 2), "output": tmp_path, "api_key": KEY, **BASE}
    assert backfill(**arguments, slice_days=2, transport=Publisher([])) == 2
    row = resume_rows(tmp_path)[0]
    assert row["status"] == "refused" and KEY not in row["message"] and "<redacted>" in row["message"]


def test_a_failed_window_is_recorded_leaves_no_output_and_the_run_continues(tmp_path, monkeypatch):
    calls = []

    def fail(reader, *, received_from, **_):
        calls.append(received_from)
        yield filing(1)
        raise PagedJsonSourceError(f"window {received_from} would not settle")

    monkeypatch.setattr(FccEcfsReader, "iter_filings", fail)
    arguments = {"since": Date(2026, 1, 1), "until": Date(2026, 1, 4), "output": tmp_path, "api_key": KEY, **BASE}
    assert backfill(**arguments, slice_days=2, transport=Publisher([])) == 1
    assert [row["status"] for row in resume_rows(tmp_path)] == ["failed", "failed"]
    assert calls == ["2026-01-01", "2026-01-03"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["resume.jsonl"], "a refused walk publishes nothing"
