"""Check a keyed GovInfo listing for identifiers left unmatched by the MODS census.

The census supplies issue dates, unmatched numbers and the source release digest; this asks the keyed
endpoint once per issue and does not infer absence from empty, malformed or incomplete listings, so
``not-listed`` describes that endpoint's answer, not GovInfo's holdings. Results append to JSONL; only
a complete populated listing settles an issue on resume, everything else (empty, request-failed,
incomplete) is recorded as indeterminate and retried, and a credential refusal aborts immediately.
Every input and output row must name the same source release digest.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from spicy_docs.transport.credentials import read_api_key, scrub_credential
from spicy_docs.transport.retry import retry_http

PAGE_SIZE = 1000
GRANULES = f"https://api.govinfo.gov/packages/FR-{{date}}/granules?offset=0&pageSize={PAGE_SIZE}"
USER_AGENT = "spicy-docs-govinfo-resolve-unmatched/1.0"


class CredentialRefusedError(RuntimeError):
    """A 401 or 403 stops the run before any per-issue result is recorded."""


class _RetryableStatus(httpx.HTTPStatusError):
    """A 429 or 5xx response that can be retried within the shared bound."""


@dataclass(frozen=True)
class Listing:
    """One issue's keyed granule answer: its status, ids, declared count and HTTP status."""

    status: str
    ids: tuple[str, ...] = ()
    declared: int | None = None
    http_status: int | None = None


def _rows(path: Path) -> list[dict[str, Any]]:
    """The non-blank JSONL lines of ``path``, parsed in order."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _source_digest(rows: list[dict[str, Any]]) -> str:
    """The one source-release digest every census row must name; raises when any row is missing it."""
    digests = {row.get("sourceReleaseDigest") for row in rows}
    if not digests or None in digests or any(not isinstance(d, str) or not d.startswith("sha256:") for d in digests):
        raise ValueError("every census row must carry sourceReleaseDigest; regenerate the census if it is missing")
    if len(digests) != 1:
        raise ValueError("census rows name different source releases")
    return next(iter(digests))


def unmatched_from_census(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The last row for a date wins, and only a complete listing contributes."""
    last = {row["publicationDate"]: row for row in rows}
    return {
        date: row["ourNumbersUnmatched"]
        for date, row in sorted(last.items())
        if row.get("status") == "listed" and row.get("ourNumbersUnmatched")
    }


def _settled(output: Path, digest: str, pending: dict[str, list[str]]) -> set[str]:
    if not output.exists():
        return set()
    last = {}
    for row in _rows(output):
        if row.get("sourceReleaseDigest") != digest:
            raise ValueError(
                "output rows must carry the same sourceReleaseDigest as the census; start a fresh output file"
            )
        last[row["publicationDate"]] = row
    return {
        date
        for date, row in last.items()
        if row.get("status") == "listed"
        and date in pending
        and sorted(item["number"] for item in row["numbers"]) == sorted(pending[date])
    }


def _is_fusion_of(granule_id: str, number: str) -> bool:
    """Match a whole identifier, optionally followed by a non-digit suffix.

    ``94-2050`` is not a fusion of ``94-20508``. Conversely,
    ``94-8046-Filed``, ``94-10956Filed``, and ``94-2050F`` retain a whole number.
    """
    return granule_id == number or (
        granule_id.startswith(number) and not granule_id[len(number) : len(number) + 1].isdigit()
    )


def granule_ids(client: httpx.Client, date: str) -> Listing:
    """One keyed granule listing for ``date``, classified as listed/empty/incomplete/invalid/failed."""

    def fetch() -> httpx.Response:
        try:
            response = client.get(GRANULES.format(date=date))
        except httpx.RequestError as error:
            detail = scrub_credential(str(error), client.headers.get("X-Api-Key", ""))
            raise httpx.RequestError(f"{type(error).__name__}: {detail}", request=error.request) from error
        if response.status_code in (401, 403):
            raise CredentialRefusedError(f"GovInfo refused the credential with HTTP {response.status_code}; stopping")
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus("retryable GovInfo response", request=response.request, response=response)
        response.raise_for_status()
        return response

    try:
        response = retry_http(fetch, retryable=(httpx.RequestError, _RetryableStatus))
    except httpx.HTTPStatusError as error:
        return Listing("request-failed", http_status=error.response.status_code)
    except httpx.RequestError:
        return Listing("request-failed")
    try:
        payload = response.json()
        granules = payload["granules"]
        declared = payload["count"]
        if not isinstance(granules, list) or type(declared) is not int or declared < 0:
            raise ValueError("invalid granule list or count")
        ids = tuple(row["granuleId"] for row in granules)
        if any(not isinstance(value, str) or not value for value in ids):
            raise ValueError("invalid granule identifier")
    except (KeyError, TypeError, ValueError):
        return Listing("listing-invalid", http_status=response.status_code)
    if payload.get("nextPage") or len(ids) >= PAGE_SIZE or len(ids) != declared or len(set(ids)) != len(ids):
        return Listing("listing-incomplete", ids, declared, response.status_code)
    return Listing("listed" if ids else "listing-empty", ids, declared, response.status_code)


def run(
    census: Path,
    output: Path,
    *,
    api_key: str,
    min_interval_seconds: float = 3.7,
    timeout: float = 90.0,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Resolve every pending issue, append results to ``output``, and return 1 if any stayed indeterminate."""
    census_rows = _rows(census)
    digest = _source_digest(census_rows)
    pending = unmatched_from_census(census_rows)
    done = _settled(output, digest, pending)
    todo = {date: numbers for date, numbers in pending.items() if date not in done}
    print(
        f"{sum(map(len, pending.values()))} unmatched numbers across {len(pending)} issues; {len(todo)} issues to resolve"
    )
    verdicts: Counter[str] = Counter()
    incomplete = False
    with (
        httpx.Client(
            headers={"X-Api-Key": api_key, "Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=timeout,
            transport=transport,
        ) as client,
        output.open("a") as sink,
    ):
        last = 0.0
        for date, numbers in sorted(todo.items()):
            wait = min_interval_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            listing = granule_ids(client, date)
            incomplete |= listing.status != "listed"
            rows = []
            for number in numbers:
                hits = (
                    [value for value in listing.ids if _is_fusion_of(value, number)]
                    if listing.status == "listed"
                    else []
                )
                verdict = ("fused-match" if hits else "not-listed") if listing.status == "listed" else listing.status
                verdicts[verdict] += 1
                rows.append({"number": number, "verdict": verdict, "granuleIds": hits or None})
            sink.write(
                json.dumps(
                    {
                        "publicationDate": date,
                        "sourceReleaseDigest": digest,
                        "status": listing.status,
                        "httpStatus": listing.http_status,
                        "keyedGranuleCount": len(listing.ids),
                        "keyedDeclaredCount": listing.declared,
                        "numbers": rows,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            sink.flush()
    print("verdicts:", dict(verdicts))
    if incomplete:
        print("Some listings remain indeterminate; rerun to retry them. No absence was inferred.", file=sys.stderr)
    return int(incomplete)


def main(argv: list[str] | None = None) -> int:
    """Resolve the census's unmatched numbers, reporting credential/IO failures on stderr."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--min-interval-seconds", type=float, default=3.7)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)
    try:
        return run(
            args.census,
            args.output,
            api_key=read_api_key(args.env_file, args.env_var),
            min_interval_seconds=args.min_interval_seconds,
            timeout=args.timeout,
        )
    except (CredentialRefusedError, OSError, ValueError) as error:
        print(f"GovInfo resolver error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
