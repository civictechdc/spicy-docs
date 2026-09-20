#!/usr/bin/env python3
"""Fetch CRS metadata and summaries from Congress.gov v3 using Parquet report ids.

Append one success or failure row per attempt to JSONL; PDFs are fetched separately.

Fetcher rules:
1. Validate JSON, a CRSReport object, and the requested id. Error-string checks
   alone can accept a challenge page as success.
2. Abort on 401/403; a credential refusal must stop the run.
3. Resume only skips status=ok. Retrying failures keeps outages from becoming
   apparent coverage.
4. Preserve sourceParquet on every row so the input remains traceable.
5. Scrub errors before truncating or writing them. The api_key query parameter
   appears in httpx exception URLs and can otherwise leak into rows or receipts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from spicy_docs.transport.credentials import (
    ACCESS_REFUSED_STATUSES,
    CredentialRefusedError,
    read_api_key,
    refusal_message,
    scrub_credential,
)
from spicy_docs.transport.retry import retry_http

API = "https://api.congress.gov/v3/crsreport/{report_id}"
USER_AGENT = "spicy-docs-crs-summaries/1.0"
#: 1,000 requests/hour is the published api.data.gov budget: 3.6 s exactly.
DEFAULT_DELAY_SECONDS = 3.7


class _RetryableStatus(httpx.HTTPStatusError):
    """429 or 5xx, worth retrying, as distinct from a 404 that is an answer."""


def report_ids(parquet: Path) -> list[str]:
    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=["report_id"])
    return [r for r in table.column("report_id").to_pylist() if r]


def fetch_one(client: httpx.Client, report_id: str, api_key: str) -> dict[str, Any]:
    """Return the CRSReport object, or raise. Success is asserted positively."""

    def _attempt() -> dict[str, Any]:
        response = client.get(
            API.format(report_id=report_id),
            params={"api_key": api_key, "format": "json"},
        )
        if response.status_code in ACCESS_REFUSED_STATUSES:
            raise CredentialRefusedError(refusal_message("congress.gov", response.status_code, report_id))
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus("retryable congress.gov response", request=response.request, response=response)
        response.raise_for_status()
        if "json" not in (response.headers.get("content-type") or ""):
            raise ValueError(f"{report_id}: not JSON ({response.headers.get('content-type')})")
        payload = response.json()
        report = payload.get("CRSReport")
        if not isinstance(report, dict):
            raise TypeError(f"{report_id}: no CRSReport object in the response")
        if report.get("id") != report_id:
            raise ValueError(f"{report_id}: response carries id {report.get('id')!r}")
        return report

    return retry_http(_attempt, retryable=(httpx.RequestError, _RetryableStatus), api_key=api_key)


def run(
    parquet: Path,
    output: Path,
    *,
    api_key: str,
    delay_seconds: float,
    limit: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    ids = report_ids(parquet)
    done: dict[str, str] = {}
    if output.exists():
        for line in output.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["reportId"]] = row.get("status", "")
    # A recorded failure is retried; only a recorded success is skipped.
    todo = [r for r in ids if done.get(r) != "ok"]
    retrying = sum(1 for r in todo if r in done)
    already_ok = len(ids) - len(todo)
    if limit is not None:
        todo = todo[:limit]
    # Count successes before applying the run limit; an unfetched row is not done.
    print(
        f"{len(ids):,} reports; {already_ok:,} already ok; {len(todo):,} to fetch this run "
        f"({retrying:,} of them retries of recorded failures)",
        file=sys.stderr,
    )

    ok = failed = 0
    with (
        httpx.Client(
            timeout=httpx.Timeout(60.0, connect=30.0),
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            transport=transport,
        ) as client,
        output.open("a") as sink,
    ):
        last = 0.0
        for index, report_id in enumerate(todo, start=1):
            wait = delay_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            try:
                report = fetch_one(client, report_id, api_key)
            except CredentialRefusedError:
                raise
            except Exception as error:  # noqa: BLE001 - recorded, then retried on resume
                row = {
                    "reportId": report_id,
                    "status": "failed",
                    "error": scrub_credential(f"{type(error).__name__}: {error}", api_key)[:300],
                    "sourceParquet": str(parquet),
                }
                failed += 1
            else:
                summary = report.get("summary") or ""
                row = {
                    "reportId": report_id,
                    "status": "ok",
                    "summaryChars": len(summary),
                    "summary": summary,
                    "title": report.get("title"),
                    "publishDate": report.get("publishDate"),
                    "updateDate": report.get("updateDate"),
                    "status_": report.get("status"),
                    "contentType": report.get("contentType"),
                    "formats": report.get("formats") or [],
                    "topics": report.get("topics") or [],
                    "authors": report.get("authors") or [],
                    "sourceParquet": str(parquet),
                }
                if "version" in report:
                    row["version"] = report["version"]
                ok += 1
            sink.write(json.dumps(row, sort_keys=True) + "\n")
            sink.flush()
            if index % 100 == 0 or index == len(todo):
                print(f"  {index:,}/{len(todo):,}  ok={ok:,} failed={failed:,}", file=sys.stderr)
    print(f"done: ok={ok:,} failed={failed:,}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL, appended, resumable")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    return run(
        args.report_parquet,
        args.output,
        api_key=read_api_key(args.env_file, args.env_var),
        delay_seconds=args.delay_seconds,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
