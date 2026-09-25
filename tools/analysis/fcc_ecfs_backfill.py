#!/usr/bin/env python3
"""Plan and execute FCC ECFS filings date-window slices from a start date to today.

``fcc_filings`` holds a bounded first run; this driver plans the slice schedule
that reaches the archive's start and executes it one window at a time, with
pacing, an append-only resume file, and per-slice outcome rows. It is a dry run
by default: it prints the slice plan and makes no request and no write; only
``--execute`` fetches.

**Windows.** Each slice is an inclusive received-date window enumerated by
``FccEcfsReader.iter_filings``, which checks the publisher's exact count, pools
shifted walks and partitions a crowded window by submission time below the
offset ceiling (``docs/sources/listings.md``). A slice is the resume unit, not
a ceiling workaround; ``--slice-days`` sets its width. ``filings_url`` spells
an inclusive end day as the following midnight, so adjacent slices can share
filings at that instant; identity settles downstream on ``id_submission``.
Each completed slice writes one JSONL file of the publisher's exact filing JSON.

**Resume.** ``resume.jsonl`` beside the slice files holds one row per settled
or attempted window; the latest row per ``(start, end)`` wins. A ``done`` row
settles a window only while its output matches the retained byte size and
SHA-256; missing, changed or unpinned outputs are retried. Every unsuccessful
window is retried on the next run and remains incomplete until it succeeds. A
401/403 aborts the run: a refusal is not a bad slice. Messages are scrubbed
through ``scrub_credential`` before they are written.

**Documents.** ``--capture-documents`` pins each window's exact list pages and
acquires every declared document through ``FccCaptureJournal``. A completed
window also needs its pages to replay offline into the same records. The
journal verifies blobs before skipping successful files, retries unsuccessful
ones, preserves interrupted state and reports explicit file outcomes.
``--max-document-attempts`` bounds new file operations per invocation; reaching
it leaves the run incomplete. See ``docs/sources/fcc-ecfs-attachments.md``.

Run from the repository root:

```sh
uv run --frozen python -m tools.analysis.fcc_ecfs_backfill --since 1996-01-02 --output DIR --api-key-file ENV
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as Date
from pathlib import Path
from typing import IO, TYPE_CHECKING

from spicy_docs.reading.paged_json import DEFAULT_MAX_PAGE_BYTES, PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.fcc_ecfs import DEFAULT_FILINGS_LIMIT, FccEcfsReader
from spicy_docs.sources.fcc_ecfs_attachments import (
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_DOCUMENT_REQUESTS,
    FccEcfsDocumentAcquirer,
    FccEcfsDocumentBudget,
)
from spicy_docs.sources.fcc_ecfs_capture import FccCaptureJournal, json_line, read_capture_journal, verified_pages
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential

if TYPE_CHECKING:
    import httpx

#: Requests allowed per page, matching spicy-regs' ECFS budget: retries for a
#: flaky transport fit, and a page that cannot settle inside them fails loudly.
MAX_REQUESTS_PER_PAGE = 5
#: Default slice width in days: the first run saw 5,137 filings over 30 days
#: (spicy-regs, 2026-09-23), and a week keeps each resumable output modest.
DEFAULT_SLICE_DAYS = 7
API_KEY_NAME = "API_GOV"
RESUME_NAME = "resume.jsonl"


@dataclass(frozen=True, slots=True)
class Window:
    """One inclusive-day received-date window."""

    start: Date
    end: Date

    def as_row_key(self) -> tuple[str, str]:
        return (self.start.isoformat(), self.end.isoformat())


def plan_slices(since: Date, until: Date, slice_days: int) -> list[Window]:
    """Contiguous inclusive-day windows covering ``since`` through ``until``."""
    if isinstance(slice_days, bool) or not isinstance(slice_days, int) or slice_days < 1:
        raise ValueError("slice_days must be a positive integer")
    if since > until:
        raise ValueError("since must not follow until")
    planned: list[Window] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=slice_days - 1), until)
        planned.append(Window(start, end))
        start = end + timedelta(days=1)
    return planned


def load_resume(resume_file: Path, *, repair_tail: bool = False) -> dict[tuple[str, str], dict]:
    """The latest row per window; earlier rows stay in the append-only file as evidence."""
    state: dict[tuple[str, str], dict] = {}
    for row in read_capture_journal(resume_file, repair_tail=repair_tail):
        state[(row["start"], row["end"])] = row
    return state


def _records_path(output: Path, window: Window) -> Path:
    return output / f"filings-{window.start}-{window.end}.jsonl"


def _verified_done(output: Path, window: Window, row: dict, *, require_pages: bool) -> bool:
    """A done receipt settles only the exact output its size and digest pin, and, when asked, its replayable pages."""
    byte_size, digest = row.get("bytes"), row.get("sha256")
    if row.get("status") != "done" or type(byte_size) is not int or byte_size < 0 or not isinstance(digest, str):
        return False
    observed = 0
    hasher = hashlib.sha256()
    try:
        with _records_path(output, window).open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                observed += len(chunk)
                if observed > byte_size:
                    return False
                hasher.update(chunk)
    except OSError:
        return False
    return (
        observed == byte_size
        and "sha256:" + hasher.hexdigest() == digest
        and (not require_pages or verified_pages(output, row))
    )


def _settled(
    planned: list[Window], state: dict[tuple[str, str], dict], *, output: Path, require_pages: bool
) -> dict[Window, dict]:
    """Verify each planned window's done receipt once; the rest are pending."""
    return {
        window: row
        for window in planned
        if (row := state.get(window.as_row_key())) is not None
        and _verified_done(output, window, row, require_pages=require_pages)
    }


def _write_records(output: Path, window: Window, records: Iterable[dict]) -> tuple[str, int, int]:
    """Stream one window's JSONL to a staged file, hashing as it goes; replace the output only on success."""
    target = _records_path(output, window)
    staged = target.with_name(f".{target.name}.partial")
    hasher, size, count = hashlib.sha256(), 0, 0
    try:
        with staged.open("wb") as stream:
            for record in records:
                line = json_line(record)
                stream.write(line)
                hasher.update(line)
                size += len(line)
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(target)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return "sha256:" + hasher.hexdigest(), size, count


def _window_records(output: Path, window: Window, row: dict) -> Iterator[tuple[dict, dict]]:
    """Each verified filing with a pointer to its line in the pinned output."""
    with _records_path(output, window).open("rb") as stream:
        for line, body in enumerate(stream):
            yield json.loads(body), {"start": row["start"], "end": row["end"], "sha256": row["sha256"], "line": line}


def _append(sink: IO[str], row: dict) -> None:
    sink.write(json.dumps(row, sort_keys=True) + "\n")
    sink.flush()
    os.fsync(sink.fileno())


def backfill(
    *,
    since: Date,
    until: Date,
    output: Path,
    api_key: str,
    slice_days: int = DEFAULT_SLICE_DAYS,
    per_page: int = DEFAULT_FILINGS_LIMIT,
    min_interval_seconds: float = 3.7,
    pause_seconds: float = 5.0,
    transport: httpx.BaseTransport | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    capture_documents: bool = False,
    document_acquirer: FccEcfsDocumentAcquirer | None = None,
    max_document_attempts: int | None = None,
    max_document_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
    credential_values: tuple[str, ...] = (),
) -> int:
    """Execute discovery and optional files; return 0 complete, 1 incomplete, 2 refused."""
    planned = plan_slices(since, until, slice_days)
    output.mkdir(parents=True, exist_ok=True)
    resume_file = output / RESUME_NAME
    settled = _settled(
        planned, load_resume(resume_file, repair_tail=True), output=output, require_pages=capture_documents
    )
    queue = [window for window in planned if window not in settled]
    print(
        f"{len(planned)} planned windows {since}..{until} of {slice_days} day(s); "
        f"{len(queue)} to run at {per_page} filings per page",
        file=sys.stderr,
    )
    budget = PagedJsonBudget(
        max_requests=MAX_REQUESTS_PER_PAGE,
        max_page_bytes=DEFAULT_MAX_PAGE_BYTES,
        timeout_seconds=60,
        min_request_interval_seconds=min_interval_seconds,
    )
    unsettled = 0
    with ExitStack() as stack:
        journal = (
            stack.enter_context(
                FccCaptureJournal(
                    output,
                    secrets=(api_key, *credential_values),
                    max_document_attempts=max_document_attempts,
                    scope={
                        "since": since.isoformat(),
                        "until": until.isoformat(),
                        "sliceDays": slice_days,
                        "pageSize": per_page,
                        "maxDocumentBytes": max_document_bytes,
                        "minIntervalSeconds": min_interval_seconds,
                        "driverCodeSha256": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    },
                )
            )
            if capture_documents
            else None
        )
        reader = stack.enter_context(FccEcfsReader(budget=budget, api_key=api_key, transport=transport))
        sink = stack.enter_context(resume_file.open("a"))
        for index, window in enumerate(queue):
            if index and pause_seconds > 0:
                sleeper(pause_seconds)
            pages: list[dict] = []
            evidence = {"pages": pages} if journal else {}
            try:
                digest, byte_size, count = _write_records(
                    output,
                    window,
                    reader.iter_filings(
                        received_from=window.start.isoformat(),
                        received_to=window.end.isoformat(),
                        limit=per_page,
                        on_page=(lambda page, pages=pages: pages.append(journal.retain_page(page)))
                        if journal
                        else None,
                    ),
                )
            except CredentialRefusedError as error:
                _append(sink, _row(window, "refused", message=scrub_credential(str(error), api_key), **evidence))
                print(f"  {window.start}..{window.end} refused; aborting the run", file=sys.stderr)
                return 2
            except PagedJsonSourceError as error:
                unsettled += 1
                row = _row(window, "failed", message=scrub_credential(str(error), api_key), **evidence)
                _append(sink, row)
                print(f"  {window.start}..{window.end} failed: {row['message']}", file=sys.stderr)
                continue
            row = _row(window, "done", records=count, sha256=digest, bytes=byte_size, **evidence)
            _append(sink, row)
            settled[window] = row
            print(f"  {window.start}..{window.end} done: {count:,} filings", file=sys.stderr)
        if journal is not None:
            acquirer = document_acquirer or FccEcfsDocumentAcquirer(
                budget=FccEcfsDocumentBudget(
                    max_requests=DEFAULT_MAX_DOCUMENT_REQUESTS,
                    max_bytes=max_document_bytes,
                    timeout_seconds=60,
                    min_request_interval_seconds=min_interval_seconds,
                )
            )
            try:
                with acquirer:
                    for window in planned:
                        if row := settled.get(window):
                            for record, pointer in _window_records(output, window, row):
                                journal.acquire_filing(record, pointer, acquirer)
                            journal.commit()
            except CredentialRefusedError:
                journal.finish(discovery_complete=False)
                print("FCC document acquisition refused; aborting the run", file=sys.stderr)
                return 2
            summary = journal.finish(discovery_complete=len(settled) == len(planned))
            print(json.dumps(summary, sort_keys=True), file=sys.stderr)
            if not summary["complete"]:
                return 1
    if unsettled:
        print(f"{unsettled} window(s) unsettled; rerun to retry them", file=sys.stderr)
        return 1
    return 0


def _row(window: Window, status: str, **fields: object) -> dict:
    return {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "status": status,
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }


def _date(value: str) -> Date:
    """Parse a strict ``YYYY-MM-DD`` date, refusing a non-canonical spelling."""
    parsed = Date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Run the planner, and the fetch only when ``--execute`` says so."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=_date, required=True, help="First day of the backfill, YYYY-MM-DD")
    parser.add_argument("--until", type=_date, default=None, help="Last day; default today")
    parser.add_argument("--slice-days", type=int, default=DEFAULT_SLICE_DAYS, help="Slice width in days")
    parser.add_argument("--output", type=Path, required=True, help="Directory for resume.jsonl and per-slice JSONL")
    parser.add_argument("--api-key-file", type=Path, default=None, help="Env file holding API_GOV; required to execute")
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=3.7,
        help="Floor between page requests; measure before raising",
    )
    parser.add_argument("--pause-seconds", type=float, default=5.0, help="Pause between windows")
    parser.add_argument(
        "--capture-documents",
        action="store_true",
        help="Retain exact list pages and acquire every declared file with verified resume",
    )
    parser.add_argument("--max-document-attempts", type=int, help="Stop new file attempts at this bound; resume later")
    parser.add_argument("--max-document-bytes", type=int, default=DEFAULT_MAX_DOCUMENT_BYTES)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Fetch. Without this flag the command only prints the slice plan and writes nothing",
    )
    args = parser.parse_args(argv)
    until = args.until or datetime.now(UTC).date()
    try:
        planned = plan_slices(args.since, until, args.slice_days)
    except ValueError as error:
        parser.error(str(error))
    if not args.execute:
        state = load_resume(args.output / RESUME_NAME) if args.output.exists() else {}
        settled = _settled(planned, state, output=args.output, require_pages=args.capture_documents)
        print(
            f"{len(planned)} windows {args.since}..{until} of {args.slice_days} day(s); {len(settled)} already settled"
        )
        print("crowded windows partition by submission time below the publisher's result ceiling")
        for window in planned:
            print(f"{window.start}..{window.end} {(window.end - window.start).days + 1}d")
        return 0
    if args.api_key_file is None:
        parser.error("--api-key-file is required with --execute")
    return backfill(
        since=args.since,
        until=until,
        output=args.output,
        api_key=read_api_key(args.api_key_file, API_KEY_NAME),
        slice_days=args.slice_days,
        min_interval_seconds=args.min_interval_seconds,
        pause_seconds=args.pause_seconds,
        capture_documents=args.capture_documents,
        max_document_attempts=args.max_document_attempts,
        max_document_bytes=args.max_document_bytes,
        credential_values=tuple(os.environ.get(name, "") for name in ("ZYTE_TOKEN", "FIRECRAWL_API_KEY")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
