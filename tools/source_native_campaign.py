#!/usr/bin/env python3
"""Shard-by-agency campaign runner for Phase A of the source supply consolidation plan.

Publishes docket and document releases per agency through ``spicy_docs.source_native_cli``
subprocesses, N agencies at a time (Phase A of
``spicysearch/docs/source-supply-consolidation-plan-2026-09-01.md``). Each child streams its
stdout and stderr into ``logs/<release>.log``, appended per attempt, and the CLI's one JSON
receipt line is read back as that log's last non-empty line. SIGINT and SIGTERM terminate the
live children, cancel the agencies not yet started, and exit non-zero.

One runner owns a destination root: the campaign claims ``<root>/campaign.lock`` exclusively
and refuses to run while another process holds it. Resume is release-grained -- skip a release
whose stored receipt names that destination and carries both pins, rename an un-receipted
destination aside (never delete) before retrying, drop the verify receipt whenever a publish
reruns so a replacement release is re-verified -- and is only safe under that root lock.

``--window-since``/``--window-until`` are one window per agency that feeds both collections and
is meant to be the source's full history; a narrower document window would need dockets over a
wider one, which this runner deliberately does not support.
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
from pathlib import Path
from typing import Any, Final, NamedTuple, TextIO

ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON: Final = ROOT / ".venv" / "bin" / "python"
SOURCE_DOCKETS: Final = "regulations-dockets"
SOURCE_DOCUMENTS: Final = "regulations-documents"
_DESTINATION_PREFIX: Final = {SOURCE_DOCKETS: "regs-dockets", SOURCE_DOCUMENTS: "regs-documents"}
_FAILED_STATUSES: Final = frozenset({"failed", "verify-failed"})
_WINDOW_HELP: Final = "{} of the one window per agency; it feeds both collections and is meant to be full history"

RunSubprocess = Callable[[list[str], Path], int]
ReleaseOutcome = tuple[str, str, str, str]  # release, agency, source, status

class CampaignError(Exception):
    """Raised for a campaign configuration or ownership problem before any subprocess runs."""

class RunContext(NamedTuple):
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

def run_child(command: list[str], log_path: Path) -> int:
    """Default runner: stream one child's stdout and stderr into its log, and stay killable."""
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    with _CHILDREN_LOCK:
        _CHILDREN.add(process)
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
    command = [str(python), "-m", "spicy_docs.source_native_cli", subcommand]
    for name, value in flags.items():
        command += [f"--{name.replace('_', '-')}", str(value)]
    return command

def _publish_command(args: argparse.Namespace, source: str, agency: str, destination: Path) -> list[str]:
    return _cli(args.python, "publish", source=source, since=args.window_since.isoformat(),
                until=args.window_until.isoformat(), agency=agency, destination=destination,
                blob_store=args.blob_store, implementation_id=args.implementation_id)

def _log_receipt(log_path: Path) -> dict[str, Any]:
    """The CLI writes one JSON receipt line, so the log's last non-empty line is that receipt."""
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}

def _resume_receipt(path: Path, destination: Path) -> dict[str, Any] | None:
    """A stored receipt counts on resume only when it names this destination and pins it."""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    named = receipt.get("release") if isinstance(receipt, dict) else None
    if not (isinstance(named, str) and receipt.get("logicalId") and receipt.get("artifactDigest")):
        return None
    return receipt if Path(named).resolve() == destination.resolve() else None

def _publication_verifier_id(destination: Path) -> tuple[str | None, str | None]:
    """Read the id that actually published this release from its own publication receipt.

    A campaign can span several builds, so the accepted verifier id has to come from the
    release being verified, never from the runner's own current ``--implementation-id`` --
    that value is correct for publish (the runner is the publisher there) but would silently
    re-accept the wrong build if reused for verify. Returns ``(verifier id, None)`` on success,
    or ``(None, what was missing)`` so the caller can fail closed with a clear reason.
    """
    path = destination / "receipts" / "publication.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, f"{path} does not exist"
    except json.JSONDecodeError as error:
        return None, f"{path} is not valid JSON ({error})"
    verifier_id = payload.get("verifierImplementationId") if isinstance(payload, dict) else None
    if isinstance(verifier_id, str) and verifier_id:
        return verifier_id, None
    return None, f"{path} is missing verifierImplementationId"

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
        _append_row(ctx, {**skeleton, "release": release, "finishedAt": _instant(ctx.clock),
                          "exitCode": None, "ok": False, "status": "interrupted"})

def _execute(ctx: RunContext, command: list[str], *, release: str, agency: str, source: str) -> dict[str, Any]:
    """Run one CLI command into its log, receipt a success, and return the parsed receipt."""
    log_path = ctx.logs_dir / f"{release}.log"
    started_at, start = _instant(ctx.clock), time.monotonic()
    _append_log(log_path, f"\n$ {started_at} {shlex.join(command)}\n")
    with ctx.lock:
        ctx.live[release] = {"agency": agency, "source": source, "startedAt": started_at}
    try:
        exit_code = ctx.run_subprocess(command, log_path)
    except OSError as error:
        exit_code = -1
        _append_log(log_path, f"{type(error).__name__}: {error}\n")
    finally:
        with ctx.lock:
            ctx.live.pop(release, None)
    payload = _log_receipt(log_path) if exit_code == 0 else {}
    ok = exit_code == 0 and bool(payload.get("ok"))
    if ok:
        (ctx.receipts_dir / f"{release}.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    _append_row(ctx, {
        "release": release, "agency": agency, "source": source, "startedAt": started_at,
        "finishedAt": _instant(ctx.clock), "elapsedSeconds": round(time.monotonic() - start, 3),
        "exitCode": exit_code, "ok": ok,
        "logicalId": payload.get("logicalId"), "artifactDigest": payload.get("artifactDigest"),
    })
    return payload if ok else {}

def _fail_verify(ctx: RunContext, *, release: str, agency: str, source: str, reason: str) -> None:
    """Record a verify that never ran because the release's own publisher id could not be read."""
    now = _instant(ctx.clock)
    _append_log(ctx.logs_dir / f"{release}.verify.log", f"\n{now} cannot verify {release}: {reason}\n")
    _append_row(ctx, {
        "release": f"{release}.verify", "agency": agency, "source": source, "startedAt": now, "finishedAt": now,
        "elapsedSeconds": 0.0, "exitCode": None, "ok": False, "logicalId": None, "artifactDigest": None,
        "status": "verify-failed", "error": reason,
    })

def _run_one_release(ctx: RunContext, *, agency: str, source: str, args: argparse.Namespace) -> ReleaseOutcome:
    destination = _destination(args.destination_root, source, agency)
    release = destination.name
    verify_path = ctx.receipts_dir / f"{release}.verify.json"
    receipt = _resume_receipt(ctx.receipts_dir / f"{release}.json", destination) if destination.exists() else None
    published = receipt is None
    if published:
        if destination.exists():
            stamp = ctx.clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination.rename(destination.with_name(f"{release}.failed-{stamp}"))
        verify_path.unlink(missing_ok=True)  # that verdict was about the release being replaced
        command = _publish_command(args, source, agency, destination)
        receipt = _execute(ctx, command, release=release, agency=agency, source=source)
        if not (receipt.get("logicalId") and receipt.get("artifactDigest")):  # fail closed on a pin-less receipt
            return release, agency, source, "failed"
    if not args.verify or _resume_receipt(verify_path, destination) is not None:
        return release, agency, source, "done" if published else "skipped"
    verifier_id, missing = _publication_verifier_id(destination)
    if verifier_id is None:
        _fail_verify(ctx, release=release, agency=agency, source=source, reason=missing or "unknown reason")
        return release, agency, source, "verify-failed"
    verify_command = _cli(args.python, "verify", source=source, release=destination, blob_store=args.blob_store,
                          logical_id=receipt["logicalId"], artifact_digest=receipt["artifactDigest"],
                          accepted_verifier_implementation_id=verifier_id)
    verified = _execute(ctx, verify_command, release=f"{release}.verify", agency=agency, source=source)
    return release, agency, source, "done" if verified else "verify-failed"

def _run_agency(ctx: RunContext, agency: str, args: argparse.Namespace) -> list[ReleaseOutcome]:
    outcomes = []
    for source in (SOURCE_DOCKETS, SOURCE_DOCUMENTS):
        if ctx.stopping.is_set():
            break
        outcomes.append(_run_one_release(ctx, agency=agency, source=source, args=args))
    return outcomes

def _agencies(args: argparse.Namespace) -> list[str]:
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
        f"{source}: {c['done']} done, {c['failed']} failed, {c['skipped']} skipped" for source, c in sorted(per_source.items())
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
    ordered = _agencies(args)
    lock_path = _claim_root(args.destination_root, clock)
    ctx = RunContext(
        run_subprocess=run_subprocess, clock=clock, receipts_dir=args.destination_root / "receipts",
        logs_dir=args.destination_root / "logs", campaign_path=args.destination_root / "campaign.jsonl",
        lock=threading.Lock(), live={}, stopping=threading.Event(),
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
    parser.add_argument("--implementation-id", required=True,
                        help="Passed to each publish; verify instead reads its accepted id from "
                             "the release's own receipts/publication.json")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent agency slots")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON, help="Interpreter to run the source-native CLI with")
    parser.add_argument("--sizes", type=Path, help="JSON {agency: object count}; schedules largest-first when given")
    parser.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True, help="Run verify after each publish")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands that would run, in order, and exit")
    return parser

def main(
    argv: list[str] | None = None, *, run_subprocess: RunSubprocess = run_child,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    stdout: TextIO | None = None, stderr: TextIO | None = None,
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
