"""Fake-subprocess tests for the Phase A shard-by-agency campaign runner.

No network and no real ``spicy_docs.cli.source_native`` subprocess: every test injects a fake
runner in place of the Popen one and a fixed clock, then inspects the campaign runner's own
filesystem output (the root lock, receipts, logs, campaign.jsonl) and its exit code. The fake
runner has the real runner's contract -- it streams its output into the log the campaign
opened and returns an exit code -- so the receipt always comes back out of the log file.
"""

from __future__ import annotations

import json
import signal
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spicy_docs.cli.campaign import main

FIXED_INSTANT = "2026-09-02T12:00:00Z"


def _clock() -> datetime:
    return datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def _flag(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def _append(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(text)


class FakeRunner:
    """Records every invocation and streams a canned CLI receipt into the campaign's log file."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.publish_failures: set[tuple[str, str]] = set()
        self.noise = ""  # extra child output printed ahead of the receipt line

    def __call__(self, command: list[str], log_path: Path) -> int:
        self.calls.append(list(command))
        subcommand, source = command[3], _flag(command, "--source")
        if subcommand == "publish":
            agency = _flag(command, "--agency")
            if (source, agency) in self.publish_failures:
                _append(log_path, f"{self.noise}acquisition failed\n")
                return 1
            destination = Path(_flag(command, "--destination"))
            destination.mkdir(parents=True)  # the real CLI publishes its release files here
            (destination / "release.json").write_text("{}", encoding="utf-8")
            # The release's own publication receipt -- distinct from the one-line success JSON
            # streamed below, which carries no implementation id.
            receipts_dir = destination / "receipts"
            receipts_dir.mkdir()
            (receipts_dir / "publication.json").write_text(
                json.dumps({"verifierImplementationId": _flag(command, "--implementation-id")}),
                encoding="utf-8",
            )
            payload = {
                "ok": True,
                "command": "publish",
                "source": source,
                "release": str(destination.resolve()),
                "logicalId": f"urn:spicy-docs:test:{source}:{agency}",
                "artifactDigest": f"sha256:{source}-{agency}",
            }
        else:
            payload = {
                "ok": True,
                "command": "verify",
                "source": source,
                "release": str(Path(_flag(command, "--release")).resolve()),
                "logicalId": _flag(command, "--logical-id"),
                "artifactDigest": _flag(command, "--artifact-digest"),
            }
        _append(log_path, self.noise + json.dumps(payload) + "\n")
        return 0


def _argv(
    tmp_path: Path,
    *,
    agencies: list[str],
    verify: bool = True,
    sizes: dict[str, int] | None = None,
    dry_run: bool = False,
    concurrency: int = 1,
) -> list[str]:
    argv = [
        "--window-since",
        "2021-01-01",
        "--window-until",
        "2025-12-31",
        "--destination-root",
        str(tmp_path / "out"),
        "--blob-store",
        str(tmp_path / "blobs"),
        "--implementation-id",
        "git+file://spicy-docs@testsha",
        "--python",
        "python3",
        "--concurrency",
        str(concurrency),
        "--verify" if verify else "--no-verify",
    ]
    for agency in agencies:
        argv += ["--agency", agency]
    if sizes is not None:
        sizes_path = tmp_path / "sizes.json"
        sizes_path.write_text(json.dumps(sizes), encoding="utf-8")
        argv += ["--sizes", str(sizes_path)]
    if dry_run:
        argv.append("--dry-run")
    return argv


def _seed_receipt(tmp_path: Path, name: str, *, release: Path, logical_id: str = "urn:pre-existing") -> Path:
    receipts_dir = tmp_path / "out" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "release": str(release.resolve()),
                "logicalId": logical_id,
                "artifactDigest": "sha256:pre-existing",
            }
        ),
        encoding="utf-8",
    )
    return path


def _seed_publication_receipt(destination: Path, *, verifier_implementation_id: str) -> None:
    """Fabricate a release's own receipts/publication.json, as a prior publish would leave it."""
    receipts_dir = destination / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / "publication.json").write_text(
        json.dumps({"verifierImplementationId": verifier_implementation_id}),
        encoding="utf-8",
    )


def test_dockets_before_documents_order_within_agency(tmp_path: Path) -> None:
    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=False), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    assert [_flag(call, "--source") for call in runner.calls] == ["regulations-dockets", "regulations-documents"]


def test_largest_first_scheduling(tmp_path: Path) -> None:
    runner = FakeRunner()
    argv = _argv(tmp_path, agencies=["EPA", "FDA", "SEC"], verify=False, sizes={"EPA": 100, "FDA": 5000, "SEC": 900})
    exit_code = main(argv, run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    agencies_in_order: list[str] = []
    for call in runner.calls:
        agency = _flag(call, "--agency")
        if agency not in agencies_in_order:
            agencies_in_order.append(agency)
    assert agencies_in_order == ["FDA", "SEC", "EPA"]


def test_receipt_log_and_jsonl_written(tmp_path: Path) -> None:
    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=False), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    out_root = tmp_path / "out"

    docket_receipt = json.loads((out_root / "receipts" / "regs-dockets-EPA.json").read_text(encoding="utf-8"))
    assert docket_receipt["ok"] is True
    assert docket_receipt["logicalId"] == "urn:spicy-docs:test:regulations-dockets:EPA"
    document_receipt = json.loads((out_root / "receipts" / "regs-documents-EPA.json").read_text(encoding="utf-8"))
    assert document_receipt["source"] == "regulations-documents"

    docket_log = (out_root / "logs" / "regs-dockets-EPA.log").read_text(encoding="utf-8")
    assert docket_log.splitlines()[0] == ""  # each attempt starts with a blank separator line
    assert docket_log.splitlines()[1].startswith(f"$ {FIXED_INSTANT} python3 -m spicy_docs.cli.source_native publish")
    assert json.loads(docket_log.splitlines()[-1])["ok"] is True  # the child's own streamed receipt line

    rows = [json.loads(line) for line in (out_root / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"regulations-dockets", "regulations-documents"}
    for row in rows:
        assert row["release"] == f"regs-{row['source'].removeprefix('regulations-')}-EPA"
        assert row["agency"] == "EPA"
        assert row["ok"] is True
        assert row["exitCode"] == 0
        assert row["startedAt"] == row["finishedAt"] == FIXED_INSTANT
    assert not (out_root / "campaign.lock").exists()  # the root lock is released on the way out


def test_receipt_is_the_last_line_of_a_noisy_log(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.noise = "downloading page 1\ndownloading page 2\n\n"
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    receipt = json.loads((tmp_path / "out" / "receipts" / "regs-dockets-EPA.json").read_text(encoding="utf-8"))
    assert receipt["logicalId"] == "urn:spicy-docs:test:regulations-dockets:EPA"


def test_verify_command_arguments_from_publish_receipt(tmp_path: Path) -> None:
    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    verify_calls = [call for call in runner.calls if call[3] == "verify"]
    assert len(verify_calls) == 2
    docket_verify = next(call for call in verify_calls if _flag(call, "--source") == "regulations-dockets")
    assert _flag(docket_verify, "--logical-id") == "urn:spicy-docs:test:regulations-dockets:EPA"
    assert _flag(docket_verify, "--artifact-digest") == "sha256:regulations-dockets-EPA"
    assert _flag(docket_verify, "--release") == str(tmp_path / "out" / "regs-dockets-EPA")
    assert _flag(docket_verify, "--accepted-verifier-implementation-id") == "git+file://spicy-docs@testsha"
    assert (tmp_path / "out" / "receipts" / "regs-dockets-EPA.verify.json").is_file()


def test_verify_uses_the_id_that_actually_published_an_older_release(tmp_path: Path) -> None:
    """A campaign can span several builds; verify must accept the id that published THIS release,
    not the runner's own current --implementation-id (a later build, here)."""
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination, logical_id="urn:published-by-old-build")
    _seed_publication_receipt(destination, verifier_implementation_id="git+file://spicy-docs@oldsha")

    runner = FakeRunner()  # this run's own --implementation-id is testsha, a newer build
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0

    docket_verify = next(
        call for call in runner.calls if call[3] == "verify" and _flag(call, "--source") == "regulations-dockets"
    )
    assert _flag(docket_verify, "--accepted-verifier-implementation-id") == "git+file://spicy-docs@oldsha"


def test_verify_fails_clearly_when_publication_receipt_is_missing_the_id(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination, logical_id="urn:published-somehow")
    # No receipts/publication.json at all -- the release was never given one, or it was lost.

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 1

    assert not any(call[3] == "verify" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    assert not (out_root / "receipts" / "regs-dockets-EPA.verify.json").exists()

    rows = [json.loads(line) for line in (out_root / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = next(row for row in rows if row["release"] == "regs-dockets-EPA.verify")
    assert failed["ok"] is False
    assert "regs-dockets-EPA" in failed["error"]
    assert "publication.json" in failed["error"]

    log_text = (out_root / "logs" / "regs-dockets-EPA.verify.log").read_text(encoding="utf-8")
    assert "regs-dockets-EPA" in log_text
    assert "publication.json" in log_text


def test_verify_fails_clearly_when_publication_receipt_lacks_the_field(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination, logical_id="urn:published-somehow")
    receipts_dir = destination / "receipts"
    receipts_dir.mkdir()
    (receipts_dir / "publication.json").write_text(json.dumps({"logicalId": "urn:published-somehow"}), encoding="utf-8")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 1

    assert not any(call[3] == "verify" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    rows = [json.loads(line) for line in (out_root / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = next(row for row in rows if row["release"] == "regs-dockets-EPA.verify")
    assert failed["ok"] is False
    assert "verifierImplementationId" in failed["error"]


def test_publish_failure_skips_verify_and_exits_one(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.publish_failures.add(("regulations-dockets", "EPA"))
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 1
    assert not any(call[3] == "verify" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    assert not (tmp_path / "out" / "receipts" / "regs-dockets-EPA.json").exists()
    rows = [json.loads(line) for line in (tmp_path / "out" / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = next(row for row in rows if row["release"] == "regs-dockets-EPA")
    assert failed["ok"] is False
    assert failed["exitCode"] == 1


def test_skip_when_already_receipted_but_still_verifies(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    (destination / "marker.txt").write_text("already published", encoding="utf-8")
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination, logical_id="urn:pre-existing:dockets")
    _seed_publication_receipt(destination, verifier_implementation_id="git+file://spicy-docs@testsha")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0

    published = [(_flag(call, "--source"), _flag(call, "--agency")) for call in runner.calls if call[3] == "publish"]
    assert ("regulations-dockets", "EPA") not in published
    assert ("regulations-documents", "EPA") in published

    docket_verify = next(
        call for call in runner.calls if call[3] == "verify" and _flag(call, "--source") == "regulations-dockets"
    )
    assert _flag(docket_verify, "--logical-id") == "urn:pre-existing:dockets"
    assert _flag(docket_verify, "--artifact-digest") == "sha256:pre-existing"
    assert _flag(docket_verify, "--accepted-verifier-implementation-id") == "git+file://spicy-docs@testsha"
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "already published"


def test_fully_receipted_release_is_skipped_and_counted_as_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination)
    _seed_receipt(tmp_path, "regs-dockets-EPA.verify", release=destination)

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    assert [_flag(call, "--source") for call in runner.calls] == ["regulations-documents"] * 2  # publish then verify
    summary = capsys.readouterr().out
    assert "regulations-dockets: 0 done, 0 failed, 1 skipped" in summary
    assert "regulations-documents: 1 done, 0 failed, 0 skipped" in summary


@pytest.mark.parametrize(
    ("publish_receipt", "destination_present"),
    [(True, False), (False, True), (False, False)],
)
def test_stale_verify_receipt_never_stands_in_for_a_republish(
    tmp_path: Path, publish_receipt: bool, destination_present: bool
) -> None:
    """Any state that forces a republish must also force a re-verify of the replacement."""
    destination = tmp_path / "out" / "regs-dockets-EPA"
    if destination_present:
        destination.mkdir(parents=True)
        (destination / "partial.txt").write_text("aborted run", encoding="utf-8")
    if publish_receipt:
        _seed_receipt(tmp_path, "regs-dockets-EPA", release=destination)
    verify_path = _seed_receipt(tmp_path, "regs-dockets-EPA.verify", release=destination, logical_id="urn:stale")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=True), run_subprocess=runner, clock=_clock)
    assert exit_code == 0

    docket_calls = [call[3] for call in runner.calls if _flag(call, "--source") == "regulations-dockets"]
    assert docket_calls == ["publish", "verify"]
    assert (
        json.loads(verify_path.read_text(encoding="utf-8"))["logicalId"]
        == "urn:spicy-docs:test:regulations-dockets:EPA"
    )


def test_receipt_naming_another_release_is_ignored(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    _seed_receipt(tmp_path, "regs-dockets-EPA", release=tmp_path / "out" / "regs-dockets-FDA")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=False), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    assert _flag(runner.calls[0], "--source") == "regulations-dockets"
    assert any(path.name.startswith("regs-dockets-EPA.failed-") for path in (tmp_path / "out").iterdir())


def test_partial_destination_renamed_aside_then_retried(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    (destination / "partial.txt").write_text("aborted run", encoding="utf-8")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=False), run_subprocess=runner, clock=_clock)
    assert exit_code == 0

    renamed = [path for path in out_root.iterdir() if path.name.startswith("regs-dockets-EPA.failed-")]
    assert len(renamed) == 1
    assert (renamed[0] / "partial.txt").read_text(encoding="utf-8") == "aborted run"
    assert any(call[3] == "publish" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    assert (out_root / "receipts" / "regs-dockets-EPA.json").is_file()
    assert destination.is_dir()  # a fresh, complete release now lives at the original name


def test_retry_appends_to_the_release_log_instead_of_truncating_it(tmp_path: Path) -> None:
    argv = _argv(tmp_path, agencies=["EPA"], verify=False)
    assert main(argv, run_subprocess=FakeRunner(), clock=_clock) == 0
    (tmp_path / "out" / "receipts" / "regs-dockets-EPA.json").unlink()  # force a retry of that one release
    assert main(argv, run_subprocess=FakeRunner(), clock=_clock) == 0

    log_text = (tmp_path / "out" / "logs" / "regs-dockets-EPA.log").read_text(encoding="utf-8")
    assert log_text.count(f"$ {FIXED_INSTANT} python3 -m spicy_docs.cli.source_native publish") == 2


def test_second_runner_refuses_a_locked_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lock_path = tmp_path / "out" / "campaign.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"pid": 4242, "startedAt": FIXED_INSTANT}), encoding="utf-8")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"], verify=False), run_subprocess=runner, clock=_clock)
    assert exit_code == 1
    assert runner.calls == []
    assert not (tmp_path / "out" / "logs").exists()
    message = capsys.readouterr().err
    assert "campaign.lock is held by" in message and "4242" in message
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == 4242  # the holder's lock is left alone


def test_dry_run_prints_commands_in_order_and_touches_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(tmp_path, agencies=["EPA", "FDA"], verify=True, dry_run=True)
    exit_code = main(argv, run_subprocess=FakeRunner(), clock=_clock)
    assert exit_code == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 4
    assert "publish" in lines[0] and "--source regulations-dockets" in lines[0] and "--agency EPA" in lines[0]
    assert "--source regulations-documents" in lines[1] and "--agency EPA" in lines[1]
    assert "--agency FDA" in lines[2] and "--agency FDA" in lines[3]
    assert not any("verify" in line for line in lines)  # verify args depend on a publish result dry-run never produces
    assert not (tmp_path / "out").exists()


def test_signal_stops_the_campaign_and_records_the_running_child(tmp_path: Path) -> None:
    campaign_path = tmp_path / "out" / "campaign.jsonl"
    main_thread = threading.main_thread().ident
    assert main_thread is not None

    class InterruptingRunner(FakeRunner):
        """Signals the campaign's own process from inside the first child, then lets it finish."""

        def __call__(self, command: list[str], log_path: Path) -> int:
            if not self.calls:
                signal.pthread_kill(main_thread, signal.SIGINT)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and "interrupted" not in campaign_path.read_text(encoding="utf-8"):
                    time.sleep(0.01)
            return super().__call__(command, log_path)

    runner = InterruptingRunner()
    argv = _argv(tmp_path, agencies=["EPA", "FDA"], verify=False, concurrency=1)
    exit_code = main(argv, run_subprocess=runner, clock=_clock)
    assert exit_code == 1  # interruption is a failure exit even though the one child succeeded

    rows = [json.loads(line) for line in campaign_path.read_text(encoding="utf-8").splitlines()]
    interrupted = [row for row in rows if row.get("status") == "interrupted"]
    assert [(row["release"], row["agency"], row["ok"]) for row in interrupted] == [("regs-dockets-EPA", "EPA", False)]
    assert [_flag(call, "--agency") for call in runner.calls] == ["EPA"]  # documents and FDA never started
    assert not (tmp_path / "out" / "campaign.lock").exists()
