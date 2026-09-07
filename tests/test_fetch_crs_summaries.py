"""Fixture coverage for ``tools/fetch_crs_summaries.py``.

Each test pins one discipline the tool exists to carry, and each discipline
comes from a defect this project hit rather than from a checklist. No network:
every response is served by an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tools.fetch_crs_summaries import CredentialRefusedError, read_api_key, run


def _parquet(tmp_path: Path, ids: list[str]) -> Path:
    path = tmp_path / "crs_reports.parquet"
    pq.write_table(pa.table({"report_id": ids}), path)
    return path


def _report(report_id: str, summary: str = "A summary.") -> dict[str, Any]:
    return {"CRSReport": {"id": report_id, "summary": summary, "title": "T", "formats": []}}


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _rows(output: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.read_text().splitlines() if line.strip()]


def test_a_response_carrying_a_different_id_is_not_a_success(tmp_path: Path) -> None:
    """Success is asserted positively, so a well-formed wrong answer fails.

    The failure this guards is the family's sharpest: a 200 with a valid body
    that is not the document asked for. Checking status, or checking for a
    known error string, passes it.
    """
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report("SOMETHING-ELSE"))

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    row = _rows(output)[0]
    assert row["status"] == "failed"
    assert "carries id" in row["error"]


def test_a_non_json_200_is_not_a_success(tmp_path: Path) -> None:
    """A challenge page or an HTML error served with status 200."""
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Just a moment...</html>",
                              headers={"content-type": "text/html"})

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert _rows(output)[0]["status"] == "failed"


def test_a_403_aborts_the_run_rather_than_being_recorded(tmp_path: Path) -> None:
    """A refused key ends the run; it is never recorded per row and passed over."""
    parquet = _parquet(tmp_path, ["R1", "R2", "R3"])
    output = tmp_path / "out.jsonl"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(403, json={"error": "denied"})

    with pytest.raises(CredentialRefusedError, match="the key was refused"):
        run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert len(seen) == 1


def test_a_recorded_failure_is_retried_and_a_success_is_not(tmp_path: Path) -> None:
    """"Asked and got nothing" must stay distinct from "never asked".

    Skipping any row already present converts an outage into a receipt that
    reads as coverage -- the defect that bit the GovInfo census.
    """
    parquet = _parquet(tmp_path, ["R1", "R2"])
    output = tmp_path / "out.jsonl"
    output.write_text(
        json.dumps({"reportId": "R1", "status": "ok"}) + "\n"
        + json.dumps({"reportId": "R2", "status": "failed"}) + "\n"
    )
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        rid = request.url.path.rsplit("/", 1)[-1]
        asked.append(rid)
        return httpx.Response(200, json=_report(rid))

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert asked == ["R2"]


def test_every_row_carries_the_source_it_was_drawn_from(tmp_path: Path) -> None:
    """A file whose rows came from two inputs cannot be reconciled afterwards."""
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        rid = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_report(rid))

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert _rows(output)[0]["sourceParquet"] == str(parquet)


def test_the_summary_is_recorded_with_its_length(tmp_path: Path) -> None:
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report("R1", summary="x" * 3500))

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    row = _rows(output)[0]
    assert row["status"] == "ok"
    assert row["summaryChars"] == 3500


def test_a_missing_key_name_refuses_rather_than_running_unauthenticated(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n")

    with pytest.raises(SystemExit, match="API_GOV not found"):
        read_api_key(env, "API_GOV")
