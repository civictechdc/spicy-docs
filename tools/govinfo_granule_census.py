#!/usr/bin/env python3
"""Enumerate govinfo's granule ids per Federal Register issue and diff ours against them.

GPO's granule ids are derived from the printed FR Doc colophon, and that
colophon carries a composition defect: on some printed pages the space between
the number and "Filed" was lost, so ``95-8641`` was filed at GPO as granule
``95-8641-Filed``. Every route keyed on the bare number then 404s. RefSpec found
that specimen on 2026-08-31 by a four-route probe; the overseer re-found it on
2026-09-05 by listing the issue package. Two routes, one mechanism.

This measures the population rather than guessing at it. A package listing
returns EVERY granule for an issue in one call (138 for FR-1995-04-10), so one
request per issue enumerates the whole corpus of ids -- no need to know in
advance which documents are broken, which is the part nobody can know.

WHAT THIS CANNOT SEE, stated because a census that reports agreement with its
own assumptions is not a measurement:

* Matching is exact string equality, deliberately. Any normalisation (splitting
  a trailing "Filed") would decide the very question being asked, and RefSpec's
  pilot attestation recorded ``reverse_substitution: forbidden`` -- for
  ``E5-2394`` the fused spelling is the only live identifier, so a "repair"
  destroys that case while fixing ``95-8641``. Unmatched is reported, never
  resolved.
* Unmatched is reported in BOTH directions and neither direction alone is "the
  defect count". Granules include non-documents (the Reader Aids section is
  served under an internal placeholder id), and our corpus may legitimately
  hold a document for a date whose granule GPO files differently or not at all.
* An issue that 404s or errors is recorded as such and excluded from the rates,
  because a failed listing is missing evidence, not evidence of zero mismatches.

The key is read from an env file at run time and never printed, never placed in
a URL, and never written to the output: govinfo is fronted by api.data.gov,
which accepts ``X-Api-Key``, so it stays in a header where no logged request
line can carry it.

Resumable by design: results are appended per issue as JSONL and an existing
output file is read first, so a run interrupted at hour two resumes rather than
re-spending the quota.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spicy_docs.source_native import ROLE_RECORDS

# Reaching for a private helper deliberately: it already implements capped
# exponential backoff with full jitter and 429/5xx classification, and this
# tool hand-rolling a second one would be the copy the doctrine forbids.
# Promote it to a public name when a third consumer appears.
from spicy_docs.source_native_cli import _retry_http
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

MANIFEST_PATH: tuple[str, str] = ("manifests", "source-native.json")
GRANULES_URL = "https://api.govinfo.gov/packages/FR-{date}/granules"
USER_AGENT = "spicy-docs-govinfo-granule-census/1.0"


class _RetryableStatus(httpx.HTTPStatusError):
    """A 429 or 5xx worth retrying, as distinct from a 404 that is an answer."""


class CredentialRefusedError(RuntimeError):
    """A 401 or 403 aborts the run instead of being recorded and passed over.

    The enumeration route was verified keyless. If the publisher starts
    answering 401 or 403, the premise that this census spends no credential has
    failed, and the only safe response is to stop and say so. Recording it as a
    per-issue failure and continuing would walk all 1,502 issues collecting
    refusals, and -- worse -- would hide a change of terms behind a column of
    zeros that reads like coverage.

    Never retry these and never fall back to sending a key. A run authorized on
    "this spends nothing" must not quietly become a run that spends something.
    """


def _read_api_key(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {env_file}")


def _our_numbers_by_date(release_root: Path, blob_store: Path) -> dict[str, set[str]]:
    store = LocalSourceNativeBlobStore(blob_store, create=False)
    members = json.loads(release_root.joinpath(*MANIFEST_PATH).read_text())["members"]
    by_date: dict[str, set[str]] = collections.defaultdict(set)
    for member in (m for m in members if m["role"] == ROLE_RECORDS):
        with store.open(member["blobRef"]) as handle:
            for line in handle:
                record = json.loads(line)["record"]
                by_date[record["publication_date"]].add(record["document_number"])
    return dict(by_date)


def _fetch_page(client: httpx.Client, date: str, params: dict[str, str]) -> dict[str, Any]:
    def _attempt() -> dict[str, Any]:
        response = client.get(GRANULES_URL.format(date=date), params=params)
        if response.status_code in (401, 403):
            raise CredentialRefusedError(
                f"govinfo answered {response.status_code} for FR-{date}: the keyless "
                "enumeration premise has failed. Stopping rather than continuing or "
                "sending a key."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus(
                "retryable govinfo response", request=response.request, response=response
            )
        response.raise_for_status()
        return response.json()

    return _retry_http(_attempt, retryable=(httpx.RequestError, _RetryableStatus))


def _granule_ids(client: httpx.Client, date: str, page_size: int) -> tuple[list[str], int, int | None]:
    """Every granuleId for one issue, following the offsetMark pages.

    Returns the ids, the calls spent, and the issue's own declared granule
    count. The caller reconciles the two: a listing that stopped early is
    missing evidence, and silently reporting its short list as the issue's
    granules would manufacture unmatched numbers that are really our own
    truncation.
    """
    ids: list[str] = []
    declared: int | None = None
    offset_mark = "*"
    calls = 0
    while True:
        payload = _fetch_page(client, date, {"pageSize": str(page_size), "offsetMark": offset_mark})
        calls += 1
        if declared is None:
            count = payload.get("count")
            declared = int(count) if isinstance(count, int | str) else None
        granules = payload.get("granules") or []
        ids.extend(g["granuleId"] for g in granules if "granuleId" in g)
        next_mark = payload.get("offsetMark")
        if not granules or not payload.get("nextPage") or not next_mark or next_mark == offset_mark:
            break
        offset_mark = next_mark
    return ids, calls, declared


def census(
    release_root: Path,
    blob_store: Path,
    output: Path,
    *,
    api_key: str,
    through: str,
    page_size: int,
    min_interval_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> int:
    by_date = _our_numbers_by_date(release_root, blob_store)
    dates = sorted(d for d in by_date if d <= through)
    done: set[str] = set()
    if output.exists():
        for line in output.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["publicationDate"])
        print(f"resuming: {len(done):,} issues already recorded", file=sys.stderr)

    todo = [d for d in dates if d not in done]
    print(f"{len(dates):,} issues in scope, {len(todo):,} to fetch", file=sys.stderr)

    with httpx.Client(
        headers={"Accept": "application/json", "User-Agent": USER_AGENT, "X-Api-Key": api_key},
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
        transport=transport,
    ) as client, output.open("a") as sink:
        last = 0.0
        for index, date in enumerate(todo, start=1):
            wait = min_interval_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            ours = by_date[date]
            try:
                ids, calls, declared = _granule_ids(client, date, page_size)
            except httpx.HTTPStatusError as error:
                row = {
                    "publicationDate": date,
                    "status": "listing-failed",
                    "httpStatus": error.response.status_code,
                    "ourDocumentCount": len(ours),
                }
            else:
                granules = set(ids)
                complete = declared is None or len(ids) >= declared
                row = {
                    "publicationDate": date,
                    # A listing that returned fewer granules than the issue
                    # declares is evidence we truncated, not evidence of a
                    # mismatch; keep it out of the rates.
                    "status": "listed" if complete else "listing-incomplete",
                    "apiCalls": calls,
                    "ourDocumentCount": len(ours),
                    "granuleCount": len(granules),
                    "granuleCountDeclaredBySource": declared,
                    "matched": len(ours & granules),
                    "ourNumbersUnmatched": sorted(ours - granules),
                    "granulesUnmatched": sorted(granules - ours),
                }
            sink.write(json.dumps(row, sort_keys=True) + "\n")
            sink.flush()
            if index % 25 == 0 or index == len(todo):
                print(f"  {index:,}/{len(todo):,} issues", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--blob-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL, appended, resumable")
    parser.add_argument(
        "--env-file", type=Path, required=True, help="File holding the API key assignment"
    )
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument(
        "--through",
        default="1999-12-31",
        help="Last publication date to enumerate. Default stops at the bulkdata boundary: "
        "2000 onward is enumerable keylessly from bulk XML, so spending a keyed quota on it "
        "would be waste.",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=3.7,
        help="Floor between requests. Default keeps a single runner under api.data.gov's "
        "1,000/hour default. Measure the concurrency you intend to run before raising it.",
    )
    args = parser.parse_args(argv)
    return census(
        args.release_root,
        args.blob_store,
        args.output,
        api_key=_read_api_key(args.env_file, args.env_var),
        through=args.through,
        page_size=args.page_size,
        min_interval_seconds=args.min_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
