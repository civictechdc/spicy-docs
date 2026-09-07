#!/usr/bin/env python3
"""Fetch CRS report summaries from the Congress.gov v3 API, one row per report.

Tier 1 of the CRS item: the API returns metadata plus a ``summary`` that is
substantive text -- measured at a 3,500-character median with 100% coverage over
24 reports stratified by type and decade, about 21x the regulations.gov comment
field's 164. Tier 2, the full report, is PDF-only at 1.5-1.9 MB each and is a
separate item.

Four disciplines are built in rather than added after, each from a defect this
project hit:

1. **Assert on what success looks like, not on what one failure looks like.**
   A check for the absence of a known error string passed a Cloudflare
   challenge page that contained no such string -- it passed the exact failure
   it existed to catch. So a row counts only when the response parses as JSON,
   carries a ``CRSReport`` object, and that object's ``id`` equals the id
   requested. A negative check only ever catches the failure already seen.
2. **A credential refusal aborts.** 401/403 stops the run rather than being
   recorded per row and passed over; a run authorized as keyed-and-budgeted
   must not quietly continue against a wall.
3. **A recorded failure is retried, never skipped.** Resume re-attempts any row
   whose status is not ``ok``, so "asked and got nothing" stays distinct from
   "never asked". Skipping recorded failures is how an outage becomes a receipt
   that reads as coverage.
4. **Every row carries its provenance** -- the run id and the source parquet it
   was drawn from -- because a file whose rows came from two different inputs
   cannot be reconciled after the fact.
5. **A recorded error is scrubbed before it is written.** This API takes its
   credential as an ``api_key`` *query parameter*, and httpx's
   ``HTTPStatusError`` renders the full request URL, so the unmodified
   exception text carries the key into the data file and from there into a
   receipt -- one 404 on ``R43434`` did exactly that on 2026-09-07, and the
   receipt printed 120 characters of the error, which is long enough to reach
   past ``api_key=``. The credential is never printed, never in a URL, never in
   a receipt, and an error string is a URL in disguise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spicy_docs.source_native_cli import _retry_http

API = "https://api.congress.gov/v3/crsreport/{report_id}"
USER_AGENT = "spicy-docs-crs-summaries/1.0"
#: 1,000 requests/hour is the published api.data.gov budget: 3.6 s exactly.
DEFAULT_DELAY_SECONDS = 3.7


class CredentialRefusedError(RuntimeError):
    """401 or 403 ends the run. There is no fallback and no per-row recording."""


class _RetryableStatus(httpx.HTTPStatusError):
    """429 or 5xx, worth retrying, as distinct from a 404 that is an answer."""


def read_api_key(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {env_file}")


def report_ids(parquet: Path) -> list[str]:
    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=["report_id"])
    return [r for r in table.column("report_id").to_pylist() if r]


def scrub_credential(text: str, api_key: str) -> str:
    """Remove the credential from anything this tool records or prints.

    Two passes, because either alone leaves a hole. The pattern catches a
    credential this function was not handed -- a redirect to a different
    keyed host, a nested URL inside a message -- while the literal catches
    the key wherever it appears in a form the pattern does not match, such
    as a header echoed back in a response body. Scrubbing happens before
    truncation, never after: truncating first can cut a key in half and
    leave the front of it standing.
    """
    scrubbed = re.sub(r"(api_key=)[^&\s'\"]+", r"\1<redacted>", text)
    if len(api_key) >= 8:
        scrubbed = scrubbed.replace(api_key, "<redacted>")
    return scrubbed


def fetch_one(client: httpx.Client, report_id: str, api_key: str) -> dict[str, Any]:
    """Return the CRSReport object, or raise. Success is asserted positively."""

    def _attempt() -> dict[str, Any]:
        response = client.get(
            API.format(report_id=report_id),
            params={"api_key": api_key, "format": "json"},
        )
        if response.status_code in (401, 403):
            raise CredentialRefusedError(
                f"congress.gov answered {response.status_code} for {report_id}: the key was "
                "refused. Stopping rather than continuing or falling back."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus(
                "retryable congress.gov response", request=response.request, response=response
            )
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

    return _retry_http(_attempt, retryable=(httpx.RequestError, _RetryableStatus))


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
    # Counted BEFORE the limit is applied. Deriving "already ok" from the
    # post-limit list reported 13,975 done against an empty output file, which
    # is a progress line that lies in the direction of looking finished.
    print(
        f"{len(ids):,} reports; {already_ok:,} already ok; {len(todo):,} to fetch this run "
        f"({retrying:,} of them retries of recorded failures)",
        file=sys.stderr,
    )

    ok = failed = 0
    with httpx.Client(
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        transport=transport,
    ) as client, output.open("a") as sink:
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
                    "error": scrub_credential(
                        f"{type(error).__name__}: {error}", api_key
                    )[:300],
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
