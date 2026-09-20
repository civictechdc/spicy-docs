"""Fixture coverage for ``src/spicy_docs/sources/congress/crs_summaries.py``.

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

from spicy_docs.sources.congress.crs_summaries import CredentialRefusedError, run
from spicy_docs.transport.credentials import read_api_key


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
        return httpx.Response(200, text="<html>Just a moment...</html>", headers={"content-type": "text/html"})

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

    with pytest.raises(CredentialRefusedError, match="access was refused"):
        run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert len(seen) == 1


def test_a_recorded_failure_is_retried_and_a_success_is_not(tmp_path: Path) -> None:
    """ "Asked and got nothing" must stay distinct from "never asked".

    Skipping any row already present converts an outage into a receipt that
    reads as coverage -- the defect that bit the GovInfo census.
    """
    parquet = _parquet(tmp_path, ["R1", "R2"])
    output = tmp_path / "out.jsonl"
    output.write_text(
        json.dumps({"reportId": "R1", "status": "ok"})
        + "\n"
        + json.dumps({"reportId": "R2", "status": "failed"})
        + "\n"
    )
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        rid = request.url.path.rsplit("/", 1)[-1]
        asked.append(rid)
        payload = _report(rid)
        payload["CRSReport"]["version"] = 15
        return httpx.Response(200, json=payload)

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    assert asked == ["R2"]
    rows = _rows(output)
    assert rows[0] == {"reportId": "R1", "status": "ok"}
    assert rows[-1]["version"] == 15


@pytest.mark.parametrize("version", [15, "15", 0, None])
def test_a_new_capture_preserves_the_native_version(tmp_path: Path, version: Any) -> None:
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"
    payload = _report("R1")
    payload["CRSReport"]["version"] = version

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    row = _rows(output)[0]
    assert row["status"] == "ok"
    assert row["version"] == version
    assert type(row["version"]) is type(version)


def test_a_missing_version_stays_absent(tmp_path: Path) -> None:
    parquet = _parquet(tmp_path, ["R1"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report("R1"))

    run(parquet, output, api_key="k", delay_seconds=0.0, transport=_transport(handler))

    row = _rows(output)[0]
    assert row["status"] == "ok"
    assert "version" not in row


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


def test_a_recorded_error_does_not_carry_the_credential(tmp_path: Path) -> None:
    """The credential never reaches the data file, and so never a receipt.

    Not a hand-built string: this drives the real 404 path so the error text
    is whatever ``httpx.HTTPStatusError`` actually renders, which is the
    shape that leaked. congress.gov takes its key as a query *parameter*, and
    that exception renders the full request URL, so the unmodified message
    carries the key into the row -- as it did for ``R43434`` on 2026-09-07,
    and from there into a receipt that printed 120 characters of it.
    """
    secret = "DEADBEEF" * 5  # 40 chars, the length congress.gov issues
    parquet = _parquet(tmp_path, ["R43434"])
    output = tmp_path / "out.jsonl"

    def handler(request: httpx.Request) -> httpx.Response:
        assert secret in str(request.url), "the key must really be on the wire"
        return httpx.Response(404, json={"error": "not found"})

    run(parquet, output, api_key=secret, delay_seconds=0.0, transport=_transport(handler))

    row = _rows(output)[0]
    assert row["status"] == "failed"
    assert secret not in row["error"]
    assert secret not in output.read_text()
    # Redacted, not merely truncated away: the error stays useful, and the
    # marker survives the 120-character window a receipt prints.
    assert "api_key=<redacted>" in row["error"]
    assert "404" in row["error"]
    assert "api_key=<redacted>" in row["error"][:120]


def test_the_scrub_removes_a_key_it_was_not_handed(tmp_path: Path) -> None:
    """The pattern half, which the literal half cannot cover.

    A redirect to another keyed host, or a nested URL quoted inside a
    message, carries a credential this function was never told about.
    """
    from spicy_docs.transport.credentials import scrub_credential

    text = "GET https://other.example/v3/x?api_key=SOME-OTHER-SECRET&format=json failed"
    assert "SOME-OTHER-SECRET" not in scrub_credential(text, "the-configured-key")
    assert "api_key=<redacted>" in scrub_credential(text, "the-configured-key")
    # And a short or empty configured key must not scrub unrelated text away.
    assert scrub_credential("no credential here", "") == "no credential here"


def test_the_scrub_removes_the_configured_key_in_a_form_the_pattern_misses() -> None:
    """The literal half, which the pattern half cannot cover.

    Written because mutation said it was needed: deleting the literal pass
    left every other test in this file green, so the docstring's claim that
    both passes earn their place was unbacked. A credential does not only
    appear as ``api_key=<value>``. An upstream error body that echoes the key
    back, a header rendered into a message, or a redirect that moves it into
    the path all present it bare, and the query-parameter pattern matches
    none of those.
    """
    from spicy_docs.transport.credentials import scrub_credential

    secret = "DEADBEEF" * 5
    for carrier in (
        f"invalid credential: {secret}",
        f"X-Api-Key: {secret}",
        f"https://api.congress.gov/v3/{secret}/crsreport",
    ):
        assert secret not in scrub_credential(carrier, secret), carrier
        assert "<redacted>" in scrub_credential(carrier, secret), carrier
