"""Resolve the numbers MODS does not list against the keyed granules endpoint.

The keyless MODS route is the complete one and the census is built on it, but it
omits at least one thing the keyed route has: GPO files some documents under a
granule id fused from the printed colophon, and `95-8641` is filed as
`95-8641-Filed`. This asks the keyed route about exactly the numbers MODS left
unmatched, and about nothing else.

**Three outcomes, and the third is why this tool exists.** A number is
`fused-match` when the listing holds a granule id that contains it, `not-listed`
when the listing is populated and does not, and **`listing-empty` when the keyed
endpoint answers HTTP 200 with a count of zero** -- which it does for whole
issues, including FR-1995-04-10, the issue holding the canonical `95-8641`
specimen. `listing-empty` is *indeterminate*, not absence. Recording it as
absence is precisely the defect that made an earlier keyed census read as though
govinfo held no granules at all: 200 with a declared count of 0 looks exactly
like a clean answer.

The unmatched set is re-derived from the census output rather than hardcoded, so
this stays correct as the census extends its date range.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

GRANULES = "https://api.govinfo.gov/packages/FR-{date}/granules?offset=0&pageSize=1000"
USER_AGENT = "spicy-docs-govinfo-resolve-unmatched/1.0"


def read_key(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {env_file}")


def unmatched_from_census(census: Path) -> dict[str, list[str]]:
    """The last row for a date wins, and only a complete listing contributes."""
    last: dict[str, dict[str, Any]] = {}
    for line in census.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            last[row["publicationDate"]] = row
    return {
        date: row["ourNumbersUnmatched"]
        for date, row in sorted(last.items())
        if row.get("status") == "listed" and row.get("ourNumbersUnmatched")
    }


def granule_ids(date: str, key: str, timeout: float) -> tuple[list[str], int | None, int | None]:
    request = urllib.request.Request(
        GRANULES.format(date=date),
        headers={"X-Api-Key": key, "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
            granules = payload.get("granules") or []
            return [g.get("granuleId", "") for g in granules], payload.get("count"), response.status
    except urllib.error.HTTPError as error:
        return [], None, error.code
    except (OSError, TimeoutError) as error:
        print(f"  {date}: {type(error).__name__}", file=sys.stderr)
        return [], None, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "Work" / "RefSpec" / ".env")
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--min-interval-seconds", type=float, default=3.7)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)

    pending = unmatched_from_census(args.census)
    done: set[str] = set()
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["publicationDate"])
    todo = {d: ns for d, ns in pending.items() if d not in done}
    total = sum(len(v) for v in pending.values())
    print(f"{total} unmatched numbers across {len(pending)} issues; {len(todo)} issues to resolve")

    key = read_key(args.env_file, args.env_var)
    verdicts: Counter[str] = Counter()
    with args.output.open("a") as sink:
        for index, (date, numbers) in enumerate(sorted(todo.items()), start=1):
            ids, declared, status = granule_ids(date, key, args.timeout)
            rows = []
            for number in numbers:
                if status != 200:
                    verdict, matched = "request-failed", None
                elif not ids:
                    # 200 with an empty listing. Indeterminate, never absence.
                    verdict, matched = "listing-empty", None
                else:
                    hits = [g for g in ids if number in g]
                    verdict = "fused-match" if hits else "not-listed"
                    matched = hits or None
                verdicts[verdict] += 1
                rows.append({"number": number, "verdict": verdict, "granuleIds": matched})
            sink.write(
                json.dumps(
                    {
                        "publicationDate": date,
                        "httpStatus": status,
                        "keyedGranuleCount": len(ids),
                        "keyedDeclaredCount": declared,
                        "numbers": rows,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            sink.flush()
            for row in rows:
                if row["verdict"] == "fused-match":
                    print(f"  {date}  {row['number']} -> {row['granuleIds']}")
            if index % 10 == 0:
                print(f"  {index}/{len(todo)} issues", file=sys.stderr)
            time.sleep(args.min_interval_seconds)

    print("\nverdicts:", dict(verdicts))
    print(
        "listing-empty is INDETERMINATE: the endpoint answered 200 with no granules, "
        "which is not evidence that govinfo lacks the document."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
