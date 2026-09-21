#!/usr/bin/env python3
"""Publish docket and document releases per agency with bounded resume checks.

One runner exclusively holds <root>/campaign.lock; resume skips a release only after
bounded admission rechecks its external pin, requested scope, and accepted producer-verifier
identity, and unreceipted destinations move aside before retry. One window per agency feeds
both collections; SIGINT/SIGTERM terminate children and exit non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any, Final, NamedTuple, TextIO

from rulespec_artifacts import canonical_json_bytes

from spicy_docs.cli.sources import source_registration

DEFAULT_PYTHON: Final = Path(sys.executable)
SOURCE_DOCKETS: Final = "regulations-dockets"
SOURCE_DOCUMENTS: Final = "regulations-documents"
_DESTINATION_PREFIX: Final = {SOURCE_DOCKETS: "regs-dockets", SOURCE_DOCUMENTS: "regs-documents"}
_RESULT_ID_FIELDS: Final = (
    "logicalId",
    "artifactDigest",
    "sourceNativeSchemaSetDigest",
    "sourceStateDigest",
    "sourceStateScope",
    "sourceSystemId",
    "sourceSystemVersion",
)
_FAILED_STATUSES: Final = frozenset({"failed", "admission-failed", "interrupted"})
_WINDOW_HELP: Final = "{} of the one window per agency; it feeds both collections and is meant to be full history"

RunSubprocess = Callable[[list[str], Path], int]
ReleaseOutcome = tuple[str, str, str, str]  # release, agency, source, status


class CampaignError(Exception):
    """Raised for a campaign configuration or ownership problem before any subprocess runs."""


class RunContext(NamedTuple):
    """Shared per-run paths, lock, live-child map, and stop flag."""

    run_subprocess: RunSubprocess
    clock: Callable[[], datetime]
    receipts_dir: Path
    logs_dir: Path
    campaign_path: Path
    lock: threading.Lock  # guards both `live` and the campaign.jsonl append
    live: dict[str, dict[str, str]]  # release -> row skeleton, for children running right now
    stopping: threading.Event


_CHILDREN: Final[set[subprocess.Popen[bytes]]] = set()  # every child alive right now, so a signal can kill them
_CHILDREN_LOCK: Final = threading.Lock()


def run_child(command: list[str], log_path: Path, *, stopping: threading.Event | None = None) -> int:
    """Default runner: stream one child's stdout and stderr into its log, and stay killable."""
    if stopping is not None and stopping.is_set():
        return -signal.SIGTERM
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    with _CHILDREN_LOCK:
        _CHILDREN.add(process)
    # A signal between Popen and registration cannot find the child in the set.
    # Check after registration too; later signals use the registered process.
    if stopping is not None and stopping.is_set():
        with suppress(OSError):
            process.terminate()
    try:
        return process.wait()
    finally:
        with _CHILDREN_LOCK:
            _CHILDREN.discard(process)


def _terminate_children() -> None:
    with _CHILDREN_LOCK:
        live = list(_CHILDREN)
    for process in live:
        with suppress(OSError):
            process.terminate()


def _instant(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _destination(root: Path, source: str, agency: str) -> Path:
    return root / f"{_DESTINATION_PREFIX[source]}-{agency}"


def _cli(python: Path, subcommand: str, **flags: object) -> list[str]:
    command = [str(python), "-m", "spicy_docs.cli.source_native", subcommand]
    for name, value in flags.items():
        command += [f"--{name.replace('_', '-')}", str(value)]
    return command


def _publish_command(args: argparse.Namespace, source: str, agency: str, destination: Path) -> list[str]:
    return _cli(
        args.python,
        "publish",
        source=source,
        since=args.window_since.isoformat(),
        until=args.window_until.isoformat(),
        agency=agency,
        destination=destination,
        blob_store=args.blob_store,
        implementation_id=args.implementation_id,
    )


def _log_receipt(log_path: Path) -> dict[str, Any]:
    """The CLI writes one JSON receipt line, so the log's last non-empty line is that receipt."""
    try:
        last_line = b""
        with log_path.open("rb") as log:
            for line in log:
                if line.strip():
                    last_line = line
        payload = json.loads(last_line.decode("utf-8")) if last_line else None
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _valid_receipt(receipt: object, destination: Path, source: str, command: str = "publish") -> bool:
    """Accept only current command results addressed to this release."""
    if not isinstance(receipt, dict):
        return False
    named = receipt.get("release")
    outcome = receipt.get("collectionOutcome")
    try:
        return (
            receipt.get("ok") is True
            and receipt.get("command") == command
            and receipt.get("source") == source
            and isinstance(named, str)
            and Path(named).is_absolute()
            and Path(named).resolve() == destination.resolve()
            and all(isinstance(receipt.get(key), str) and receipt[key] for key in _RESULT_ID_FIELDS)
            and isinstance(outcome, dict)
            and isinstance(outcome.get("requestedScope"), dict)
        )
    except (OSError, ValueError):
        return False


def _resume_receipt(path: Path, destination: Path, source: str) -> dict[str, Any] | None:
    """Return the stored receipt when this release can resume from it, else None."""

    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        return receipt if _valid_receipt(receipt, destination, source) else None
    except (OSError, ValueError):
        return None


def _admit_receipt(
    ctx: RunContext, receipt: dict[str, Any], destination: Path, source: str, agency: str, args: argparse.Namespace
) -> bool:
    """Re-inspect the release and require it to match the stored receipt; raises ValueError on any difference."""

    requested_scope = source_registration(source).query_scope(
        argparse.Namespace(
            source=source, since=args.window_since, until=args.window_until, agency=[agency], product_id=[]
        )
    )
    if receipt["collectionOutcome"]["requestedScope"] != requested_scope:
        raise ValueError("stored publish receipt does not match the requested agency and window")
    command = _cli(
        args.python,
        "inspect",
        source=source,
        release=destination,
        blob_store=args.blob_store,
        logical_id=receipt["logicalId"],
        artifact_digest=receipt["artifactDigest"],
        failure_limit=0,
    )
    for implementation_id in args.accepted_verifier_implementation_id:
        command.extend(["--accepted-verifier-implementation-id", implementation_id])
    inspected = _execute(ctx, command, destination=destination, release=destination.name, agency=agency, source=source)
    if not inspected:
        return False
    if inspected["collectionOutcome"]["requestedScope"] != requested_scope:
        raise ValueError("admitted release does not match the requested agency and window")
    for field in _RESULT_ID_FIELDS:
        if inspected[field] != receipt[field]:
            raise ValueError(f"stored publish receipt differs from admitted release at {field}")
    if canonical_json_bytes(inspected["collectionOutcome"]) != canonical_json_bytes(receipt["collectionOutcome"]):
        raise ValueError("stored publish receipt differs from admitted release at collectionOutcome")
    return True


def _append_log(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8") as log:  # append: a previous attempt's log is history, not waste
        log.write(text)


def _append_row(ctx: RunContext, row: dict[str, object]) -> None:
    with ctx.lock, ctx.campaign_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _log_interrupted(ctx: RunContext) -> None:
    """Record every child that was still running when the campaign was interrupted."""
    with ctx.lock:
        running = list(ctx.live.items())
    for release, skeleton in running:
        _append_row(
            ctx,
            {
                **skeleton,
                "release": release,
                "finishedAt": _instant(ctx.clock),
                "exitCode": None,
                "ok": False,
                "status": "interrupted",
            },
        )


def _execute(
    ctx: RunContext, command: list[str], *, destination: Path, release: str, agency: str, source: str
) -> dict[str, Any]:
    """Run a killable command; retain publication receipts separately from inspection output."""
    if ctx.stopping.is_set():
        return {}
    operation = command[3]
    log_path = ctx.logs_dir / f"{release}.log"
    started_at, start = _instant(ctx.clock), time.monotonic()
    _append_log(log_path, f"\n$ {started_at} {shlex.join(command)}\n")
    with ctx.lock:
        ctx.live[release] = {"agency": agency, "source": source, "startedAt": started_at, "command": operation}
    try:
        exit_code = ctx.run_subprocess(command, log_path)
    except OSError as error:
        exit_code = -1
        _append_log(log_path, f"{type(error).__name__}: {error}\n")
    finally:
        with ctx.lock:
            ctx.live.pop(release, None)
    payload = _log_receipt(log_path)
    valid = exit_code == 0 and _valid_receipt(payload, destination, source, operation)
    if valid and operation == "publish":
        (ctx.receipts_dir / f"{release}.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    ok = valid and not ctx.stopping.is_set()
    status = (
        "interrupted"
        if ctx.stopping.is_set()
        else "completed"
        if ok
        else "admission-failed"
        if operation == "inspect"
        else "failed"
    )
    error = payload.get("error")
    _append_row(
        ctx,
        {
            "release": release,
            "agency": agency,
            "source": source,
            "command": operation,
            "status": status,
            **({"error": error.get("message")} if isinstance(error, dict) else {}),
            "startedAt": started_at,
            "finishedAt": _instant(ctx.clock),
            "elapsedSeconds": round(time.monotonic() - start, 3),
            "exitCode": exit_code,
            "ok": ok,
            "logicalId": payload.get("logicalId"),
            "artifactDigest": payload.get("artifactDigest"),
        },
    )
    return payload if ok else {}


def _fail_admission(ctx: RunContext, *, release: str, agency: str, source: str, reason: str) -> None:
    """Record an admission failure as a campaign row and a log line."""

    now = _instant(ctx.clock)
    _append_log(ctx.logs_dir / f"{release}.log", f"\n{now} cannot admit {release}: {reason}\n")
    _append_row(
        ctx,
        {
            "release": release,
            "agency": agency,
            "source": source,
            "finishedAt": now,
            "ok": False,
            "status": "admission-failed",
            "error": reason,
        },
    )


def _rename_aside(path: Path, stamp: str) -> None:
    """Preserve every failed attempt, including retries within the same clock tick."""
    if not (path.exists() or path.is_symlink()):
        return
    stem = f"{path.name}.failed-{stamp}"
    aside = path.with_name(stem)
    suffix = 0
    while aside.exists() or aside.is_symlink():
        suffix += 1
        aside = path.with_name(f"{stem}-{suffix}")
    path.rename(aside)


def _run_one_release(ctx: RunContext, *, agency: str, source: str, args: argparse.Namespace) -> ReleaseOutcome:
    """Resume from a valid receipt or publish fresh, then require admission; returns the release outcome."""

    destination = _destination(args.destination_root, source, agency)
    release = destination.name
    receipt_path = ctx.receipts_dir / f"{release}.json"
    receipt = _resume_receipt(receipt_path, destination, source) if destination.exists() else None
    published = receipt is None
    if published:
        stamp = ctx.clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        for path in (destination, receipt_path):
            _rename_aside(path, stamp)
        command = _publish_command(args, source, agency, destination)
        receipt = _execute(ctx, command, destination=destination, release=release, agency=agency, source=source)
        if not receipt:
            return release, agency, source, "interrupted" if ctx.stopping.is_set() else "failed"
    try:
        admitted = _admit_receipt(ctx, receipt, destination, source, agency, args)
    except (OSError, ValueError) as error:
        _fail_admission(ctx, release=release, agency=agency, source=source, reason=str(error))
        return release, agency, source, "admission-failed"
    if ctx.stopping.is_set():
        return release, agency, source, "interrupted"
    if not admitted:
        return release, agency, source, "admission-failed"
    return release, agency, source, "done" if published else "skipped"


def _run_agency(ctx: RunContext, agency: str, args: argparse.Namespace) -> list[ReleaseOutcome]:
    outcomes = []
    for source in (SOURCE_DOCKETS, SOURCE_DOCUMENTS):
        if ctx.stopping.is_set():
            break
        outcomes.append(_run_one_release(ctx, agency=agency, source=source, args=args))
    return outcomes


def _agencies(args: argparse.Namespace) -> list[str]:
    """Collect unique agency codes from file and flags, largest-first when ``--sizes`` is given."""

    codes: list[str] = []
    if args.agencies_file:
        data = json.loads(args.agencies_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise CampaignError(f"{args.agencies_file} must hold a JSON list of agency codes")
        codes.extend(str(code) for code in data)
    codes.extend(args.agency)
    if not codes:
        raise CampaignError("no agencies given; pass --agencies-file or --agency")
    seen: set[str] = set()
    ordered = [code for code in codes if not (code in seen or seen.add(code))]
    if not args.sizes:
        return ordered
    sizes = json.loads(args.sizes.read_text(encoding="utf-8"))
    if not isinstance(sizes, dict):
        raise CampaignError(f"{args.sizes} must hold a JSON object of {{agency: count}}")
    return sorted(ordered, key=lambda agency: (-int(sizes.get(agency, 0)), agency))


def _summarize(outcomes: list[ReleaseOutcome], elapsed: float, *, interrupted: bool) -> str:
    per_source: dict[str, dict[str, int]] = {}
    for _release, _agency, source, status in outcomes:
        counts = per_source.setdefault(source, {"done": 0, "failed": 0, "skipped": 0})
        counts["failed" if status in _FAILED_STATUSES else status] += 1
    counted = "; ".join(
        f"{source}: {c['done']} done, {c['failed']} failed, {c['skipped']} skipped"
        for source, c in sorted(per_source.items())
    )
    agencies = {agency for _release, agency, _source, _status in outcomes}
    return f"{len(agencies)} agencies, {len(outcomes)} releases in {elapsed:.1f}s{' (interrupted)' * interrupted}. {counted}."


def _print_dry_run(args: argparse.Namespace, *, out: TextIO) -> None:
    for agency in _agencies(args):
        for source in (SOURCE_DOCKETS, SOURCE_DOCUMENTS):
            destination = _destination(args.destination_root, source, agency)
            print(shlex.join(_publish_command(args, source, agency, destination)), file=out)


def _claim_root(root: Path, clock: Callable[[], datetime]) -> Path:
    """Take the one-runner-per-root lock; rename-aside resume is only safe while it is held."""
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "campaign.lock"
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "startedAt": _instant(clock)}, sort_keys=True) + "\n")
    except FileExistsError:
        holder = lock_path.read_text(encoding="utf-8").strip() or "an unrecorded process"
        raise CampaignError(f"{lock_path} is held by {holder}; one runner at a time per destination root") from None
    return lock_path


def _install_signal_handlers(handler: Callable[..., None]) -> Callable[[], None]:
    """Route SIGINT and SIGTERM to handler and return a restore callable (no-op off the main thread)."""
    previous: list[tuple[int, Any]] = []
    for number in (signal.SIGINT, signal.SIGTERM):
        with suppress(ValueError):
            previous.append((number, signal.signal(number, handler)))

    def restore() -> None:
        for number, original in previous:
            signal.signal(number, original)

    return restore


def _run_campaign(
    args: argparse.Namespace, *, run_subprocess: RunSubprocess, clock: Callable[[], datetime]
) -> tuple[list[ReleaseOutcome], float, bool]:
    """Run every agency under the root lock; returns outcomes, elapsed seconds, and whether it stopped."""

    ordered = _agencies(args)
    lock_path = _claim_root(args.destination_root, clock)
    stopping = threading.Event()
    ctx = RunContext(
        run_subprocess=partial(run_child, stopping=stopping) if run_subprocess is run_child else run_subprocess,
        clock=clock,
        receipts_dir=args.destination_root / "receipts",
        logs_dir=args.destination_root / "logs",
        campaign_path=args.destination_root / "campaign.jsonl",
        lock=threading.Lock(),
        live={},
        stopping=stopping,
    )
    for directory in (ctx.receipts_dir, ctx.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    ctx.campaign_path.touch(exist_ok=True)
    executor = ThreadPoolExecutor(max_workers=max(1, args.concurrency))

    def stop(_number: object = None, _frame: object = None) -> None:
        ctx.stopping.set()
        _terminate_children()
        _log_interrupted(ctx)

    restore, started = _install_signal_handlers(stop), time.monotonic()
    outcomes: list[ReleaseOutcome] = []
    try:
        futures = [executor.submit(_run_agency, ctx, agency, args) for agency in ordered]
        for future in futures:
            # Cancel from this loop, not from the handler: shutdown() wants a lock submit() holds.
            if ctx.stopping.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
            with suppress(CancelledError):
                outcomes.extend(future.result())
    finally:
        restore()
        executor.shutdown(wait=True)
        lock_path.unlink(missing_ok=True)
    return outcomes, time.monotonic() - started, ctx.stopping.is_set()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agency", action="append", default=[], help="Agency code; repeat for multiple agencies")
    parser.add_argument("--agencies-file", type=Path, help="JSON file holding a list of agency codes")
    parser.add_argument("--window-since", type=date.fromisoformat, required=True, help=_WINDOW_HELP.format("Start"))
    parser.add_argument("--window-until", type=date.fromisoformat, required=True, help=_WINDOW_HELP.format("End"))
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--blob-store", type=Path, required=True, help="Persistent content-addressed payload store")
    parser.add_argument(
        "--implementation-id",
        required=True,
        help="Implementation identity passed to each new publish",
    )
    parser.add_argument(
        "--accepted-verifier-implementation-id",
        action="append",
        required=True,
        help="Trusted producer-verifier identity for new and resumed releases; repeat to accept several builds",
    )
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent agency slots")
    parser.add_argument(
        "--python", type=Path, default=DEFAULT_PYTHON, help="Interpreter to run the source-native CLI with"
    )
    parser.add_argument("--sizes", type=Path, help="JSON {agency: object count}; schedules largest-first when given")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands that would run, in order, and exit")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    run_subprocess: RunSubprocess = run_child,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out, err = stdout or sys.stdout, stderr or sys.stderr
    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            _print_dry_run(args, out=out)
            return 0
        outcomes, elapsed, interrupted = _run_campaign(args, run_subprocess=run_subprocess, clock=clock)
    except CampaignError as error:
        print(f"campaign error: {error}", file=err)
        return 1
    print(_summarize(outcomes, elapsed, interrupted=interrupted), file=out)
    if interrupted:
        print("campaign interrupted; live children were terminated", file=err)
        return 1
    return 1 if any(status in _FAILED_STATUSES for _release, _agency, _source, status in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
