"""Campaign scheduling and recovery using real offline publications.

The injected child runner calls the actual source-native CLI with retained fixture
bytes, so publication replay, external receipts, and bounded admission are real.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rulespec_artifacts import ROOT_OBJECT_KEY, canonical_json_bytes

from spicy_docs.cli import campaign, source_native
from spicy_docs.cli.campaign import main, run_child
from spicy_docs.releases import publish
from tests.regulations_gov.fixtures import _docket, _docket_object, _document, _document_object, _Reader

FIXED_INSTANT = "2026-09-02T12:00:00Z"
IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40


def _clock() -> datetime:
    return datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def _flag(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def _append(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(text)


def _regulations_factory(agency: str, collection: str) -> _Reader:
    docket = f"{agency}-2024-0001"
    if collection == "dockets":
        value = _docket(docket, agencyId=agency, modifyDate="2024-08-24T00:00:00Z")
        source_object = _docket_object(docket, agency=agency, value=value)
    else:
        assert collection == "documents"
        document = f"{docket}-0001"
        value = _document(
            document,
            agencyId=agency,
            docketId=docket,
            modifyDate="2024-08-24T00:00:00Z",
            postedDate="2024-08-24T00:00:00Z",
        )
        source_object = _document_object(document, agency=agency, docket_id=docket, value=value)
    return _Reader([source_object])


class FakeRunner:
    """Replace process launch, retaining the actual CLI, publisher, and receipt output."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.publish_failures: set[tuple[str, str]] = set()
        self.noise = ""

    @property
    def publications(self) -> list[list[str]]:
        return [call for call in self.calls if call[3] == "publish"]

    def __call__(self, command: list[str], log_path: Path) -> int:
        self.calls.append(list(command))
        assert command[3] in {"publish", "inspect"}  # full audit is a separate operator command
        source = _flag(command, "--source")
        if command[3] == "publish" and (source, _flag(command, "--agency")) in self.publish_failures:
            _append(log_path, f"{self.noise}acquisition failed\n")
            return 1
        with log_path.open("a", encoding="utf-8") as log:
            log.write(self.noise)
            return source_native.main(
                command[3:],
                read_regulations=_regulations_factory,
                clock=_clock,
                stdout=log,
                stderr=log,
            )


def _argv(
    tmp_path: Path,
    *,
    agencies: list[str],
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
        IMPLEMENTATION_ID,
        "--accepted-verifier-implementation-id",
        IMPLEMENTATION_ID,
        "--python",
        "python3",
        "--concurrency",
        str(concurrency),
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


def _receipt_path(tmp_path: Path, source: str = "dockets") -> Path:
    return tmp_path / "out" / "receipts" / f"regs-{source}-EPA.json"


def _receipt(tmp_path: Path, source: str = "dockets") -> dict:
    return json.loads(_receipt_path(tmp_path, source).read_text(encoding="utf-8"))


def _campaign_rows(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "out" / "campaign.jsonl").read_text().splitlines()]


def _admission_failure(tmp_path: Path) -> dict:
    return next(row for row in reversed(_campaign_rows(tmp_path)) if row["status"] == "admission-failed")


def test_dockets_before_documents_order_within_agency(tmp_path: Path) -> None:
    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    assert [_flag(call, "--source") for call in runner.publications] == ["regulations-dockets", "regulations-documents"]


def test_default_interpreter_runs_publish_children(tmp_path: Path) -> None:
    runner = FakeRunner()
    argv = _argv(tmp_path, agencies=["EPA"])
    python_option = argv.index("--python")
    del argv[python_option : python_option + 2]

    assert main(argv, run_subprocess=runner, clock=_clock) == 0
    assert len(runner.calls) == 4
    assert {call[3] for call in runner.calls} == {"publish", "inspect"}
    assert all(call[:3] == [sys.executable, "-m", "spicy_docs.cli.source_native"] for call in runner.calls)


def test_largest_first_scheduling(tmp_path: Path) -> None:
    runner = FakeRunner()
    argv = _argv(tmp_path, agencies=["EPA", "FDA", "SEC"], sizes={"EPA": 100, "FDA": 5000, "SEC": 900})
    exit_code = main(argv, run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    agencies_in_order: list[str] = []
    for call in runner.publications:
        agency = _flag(call, "--agency")
        if agency not in agencies_in_order:
            agencies_in_order.append(agency)
    assert agencies_in_order == ["FDA", "SEC", "EPA"]


def test_receipt_log_and_jsonl_written(tmp_path: Path) -> None:
    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    out_root = tmp_path / "out"

    docket_receipt = json.loads((out_root / "receipts" / "regs-dockets-EPA.json").read_text(encoding="utf-8"))
    assert docket_receipt["ok"] is True
    assert docket_receipt["logicalId"].startswith("urn:spicy:artifact:spicyregs-source-native-release:")
    document_receipt = json.loads((out_root / "receipts" / "regs-documents-EPA.json").read_text(encoding="utf-8"))
    assert document_receipt["source"] == "regulations-documents"

    docket_log = (out_root / "logs" / "regs-dockets-EPA.log").read_text(encoding="utf-8")
    assert docket_log.splitlines()[0] == ""  # each attempt starts with a blank separator line
    assert docket_log.splitlines()[1].startswith(f"$ {FIXED_INSTANT} python3 -m spicy_docs.cli.source_native publish")
    assert json.loads(docket_log.splitlines()[-1])["ok"] is True  # the child's own streamed receipt line

    rows = [json.loads(line) for line in (out_root / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
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
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 0
    receipt = json.loads((tmp_path / "out" / "receipts" / "regs-dockets-EPA.json").read_text(encoding="utf-8"))
    assert receipt["logicalId"].startswith("urn:spicy:artifact:spicyregs-source-native-release:")


@pytest.mark.parametrize("bad_output", [b"", b"not JSON\n", b"[]\n", b"\xff\n"])
def test_bad_child_output_cannot_reuse_an_older_log_receipt(tmp_path: Path, bad_output: bytes) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    _receipt_path(tmp_path).unlink()

    class MalformedRunner(FakeRunner):
        def __call__(self, command: list[str], log_path: Path) -> int:
            if command[3] == "publish":
                self.calls.append(command)
                with log_path.open("ab") as log:
                    log.write(bad_output)
                return 0
            return super().__call__(command, log_path)

    assert main(args, run_subprocess=MalformedRunner(), clock=_clock) == 1
    assert not _receipt_path(tmp_path).exists()
    failed = next(row for row in reversed(_campaign_rows(tmp_path)) if row["command"] == "publish")
    assert failed["ok"] is False
    assert failed["status"] == "failed"
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    assert _receipt(tmp_path)["ok"] is True


def test_publication_replays_once_and_resume_only_admits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replayed = []
    original_replay = publish.verify_source_native_release

    def replay(artifact, member_source, **kwargs):
        replayed.append(artifact.pin)
        return original_replay(artifact, member_source, **kwargs)

    monkeypatch.setattr(publish, "verify_source_native_release", replay)
    monkeypatch.setattr(source_native, "verify_source_native_release", replay)
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    assert len(replayed) == 2  # one mandatory replay for each of the two releases
    assert not list((tmp_path / "out" / "receipts").glob("*.verify.json"))
    assert not list((tmp_path / "out" / "logs").glob("*.verify.log"))

    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert runner.publications == []
    assert len(replayed) == 2

    receipt = _receipt(tmp_path)
    assert (
        source_native.main(
            [
                "verify",
                "--source",
                "regulations-dockets",
                "--release",
                receipt["release"],
                "--blob-store",
                str(tmp_path / "blobs"),
                "--logical-id",
                receipt["logicalId"],
                "--artifact-digest",
                receipt["artifactDigest"],
                "--accepted-verifier-implementation-id",
                IMPLEMENTATION_ID,
            ]
        )
        == 0
    )
    assert len(replayed) == 3  # the operator explicitly requested the extra replay


def test_new_publication_requires_independently_accepted_build(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    args[args.index("--accepted-verifier-implementation-id") + 1] = "unaccepted-build"
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert len(runner.publications) == 2
    assert _receipt(tmp_path)["ok"] is True  # successful publication remains available for inspection
    assert _admission_failure(tmp_path)["status"] == "admission-failed"
    before = _receipt_path(tmp_path).read_bytes()
    args.extend(["--accepted-verifier-implementation-id", IMPLEMENTATION_ID])
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert runner.publications == []
    assert _receipt_path(tmp_path).read_bytes() == before


def test_old_release_requires_independently_accepted_build(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    before = _receipt_path(tmp_path).read_bytes()
    new_build = "git+https://example.test/spicy-docs@" + "b" * 40
    args[args.index("--implementation-id") + 1] = new_build
    args[args.index("--accepted-verifier-implementation-id") + 1] = new_build
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert runner.publications == []
    assert _receipt_path(tmp_path).read_bytes() == before
    assert "implementation is not accepted" in _admission_failure(tmp_path)["error"]
    args.extend(["--accepted-verifier-implementation-id", IMPLEMENTATION_ID])
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert runner.publications == []


@pytest.mark.parametrize("tamper", ["pin", "root", "publication", "scope"])
def test_resume_fails_closed_on_tampering_and_preserves_evidence(tmp_path: Path, tamper: str) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    destination = tmp_path / "out" / "regs-dockets-EPA"
    if tamper == "pin":
        path = _receipt_path(tmp_path)
        value = _receipt(tmp_path)
        value["artifactDigest"] = "sha256:" + "0" * 64
    else:
        path = (
            destination
            / {"root": ROOT_OBJECT_KEY, "publication": "receipts/publication.json", "scope": "records/scopes.jsonl"}[
                tamper
            ]
        )
        value = json.loads(path.read_text())
        if tamper == "root":
            value["spec"]["sourceStateDigest"] = "sha256:" + "0" * 64
        elif tamper == "publication":
            value["semanticVerdict"] = "fail"
        else:
            value["fields"]["modifiedThrough"] = "2024-12-31"
    path.write_bytes(canonical_json_bytes(value) + b"\n")
    before = path.read_bytes()
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert runner.publications == []
    assert path.read_bytes() == before
    assert destination.is_dir()
    assert not list((tmp_path / "out").glob("*.failed-*"))
    assert _admission_failure(tmp_path)["status"] == "admission-failed"


@pytest.mark.parametrize("count", [11, True])
def test_resume_checks_the_whole_external_outcome_against_the_release(tmp_path: Path, count: object) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    receipt = _receipt(tmp_path)
    receipt["collectionOutcome"]["publishedRecordCount"] = count
    _receipt_path(tmp_path).write_text(json.dumps(receipt))
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert runner.publications == []
    assert "collectionOutcome" in _admission_failure(tmp_path)["error"]
    assert _receipt(tmp_path) == receipt


def test_resume_still_hashes_payloads_and_preserves_corruption(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    destination = tmp_path / "out" / "regs-dockets-EPA"
    manifest = json.loads((destination / "manifests/source-native.json").read_text())
    blob_ref = next(row["blobRef"] for row in manifest["members"] if row["role"] == "source-native-records")
    blob = tmp_path / "blobs" / "sha256" / blob_ref.removeprefix("sha256:")
    before = blob.read_bytes()
    corrupted = before.replace(b"Exact docket title", b"Altered docket fact")
    assert corrupted != before
    blob.write_bytes(corrupted)
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert runner.publications == []
    assert blob.read_bytes() == corrupted
    assert _admission_failure(tmp_path)["status"] == "admission-failed"


@pytest.mark.parametrize("option", ["--verify", "--no-verify"])
def test_campaign_drops_redundant_verify_switches(tmp_path: Path, option: str) -> None:
    with pytest.raises(SystemExit) as error:
        main([*_argv(tmp_path, agencies=["EPA"]), option], run_subprocess=FakeRunner(), clock=_clock)
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("change_receipt", [False, True])
def test_resume_matches_the_actual_requested_scope(tmp_path: Path, change_receipt: bool) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    args[args.index("--window-until") + 1] = "2024-12-31"
    if change_receipt:
        for source, selector in (("dockets", "modifiedThrough"), ("documents", "publishedThrough")):
            receipt = _receipt(tmp_path, source)
            receipt["collectionOutcome"]["requestedScope"][selector] = "2024-12-31"
            _receipt_path(tmp_path, source).write_text(json.dumps(receipt))
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 1
    assert runner.publications == []
    assert "requested agency and window" in _admission_failure(tmp_path)["error"]


def test_publish_failure_exits_one_without_a_success_receipt(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.publish_failures.add(("regulations-dockets", "EPA"))
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 1
    assert not any(call[3] == "verify" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    assert not (tmp_path / "out" / "receipts" / "regs-dockets-EPA.json").exists()
    rows = [json.loads(line) for line in (tmp_path / "out" / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = next(row for row in rows if row["release"] == "regs-dockets-EPA")
    assert failed["ok"] is False
    assert failed["exitCode"] == 1


def test_receipted_releases_are_counted_as_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    capsys.readouterr()
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert runner.publications == []
    summary = capsys.readouterr().out
    assert "regulations-dockets: 0 done, 0 failed, 1 skipped" in summary
    assert "regulations-documents: 0 done, 0 failed, 1 skipped" in summary


@pytest.mark.parametrize("invalid", ["missing", "json", "legacy", "release", "pin", "source", "command", "ok"])
def test_missing_malformed_or_misdirected_receipts_retry_with_evidence_aside(tmp_path: Path, invalid: str) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    receipt_path = _receipt_path(tmp_path)
    value = _receipt(tmp_path)
    if invalid == "missing":
        receipt_path.unlink()
    elif invalid == "json":
        receipt_path.write_text("{invalid")
    else:
        if invalid == "legacy":
            value.pop("collectionOutcome")
        elif invalid == "release":
            value["release"] = str(tmp_path / "somewhere-else")
        elif invalid == "pin":
            value["artifactDigest"] = None
        else:
            value[invalid] = {"source": "regulations-documents", "command": "verify", "ok": False}[invalid]
        receipt_path.write_text(json.dumps(value))
    before = receipt_path.read_bytes() if receipt_path.exists() else None
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert [_flag(call, "--source") for call in runner.publications] == ["regulations-dockets"]
    assert len(list((tmp_path / "out").glob("regs-dockets-EPA.failed-*"))) == 1
    if before is not None:
        retained = next(receipt_path.parent.glob("regs-dockets-EPA.json.failed-*"))
        assert retained.read_bytes() == before
    assert _receipt(tmp_path)["ok"] is True


def test_missing_destination_does_not_reuse_its_old_pin_after_failed_retry(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    destination = tmp_path / "out" / "regs-dockets-EPA"
    destination.rename(tmp_path / "retained-old-release")

    class PartialRunner(FakeRunner):
        def __call__(self, command: list[str], log_path: Path) -> int:
            if command[3] == "publish":
                self.calls.append(list(command))
                destination.mkdir()
                (destination / "partial.txt").write_text("interrupted replacement")
                return 1
            return super().__call__(command, log_path)

    assert main(args, run_subprocess=PartialRunner(), clock=_clock) == 1
    assert not _receipt_path(tmp_path).exists()
    runner = FakeRunner()
    assert main(args, run_subprocess=runner, clock=_clock) == 0
    assert [_flag(call, "--source") for call in runner.publications] == ["regulations-dockets"]
    assert (
        next((tmp_path / "out").glob("regs-dockets-EPA.failed-*")).joinpath("partial.txt").read_text()
        == "interrupted replacement"
    )


def test_partial_destination_renamed_aside_then_retried(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    destination = out_root / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    (destination / "partial.txt").write_text("aborted run", encoding="utf-8")

    runner = FakeRunner()
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 0

    renamed = [path for path in out_root.iterdir() if path.name.startswith("regs-dockets-EPA.failed-")]
    assert len(renamed) == 1
    assert (renamed[0] / "partial.txt").read_text(encoding="utf-8") == "aborted run"
    assert any(call[3] == "publish" and _flag(call, "--source") == "regulations-dockets" for call in runner.calls)
    assert (out_root / "receipts" / "regs-dockets-EPA.json").is_file()
    assert destination.is_dir()  # a fresh, complete release now lives at the original name


def test_same_instant_retries_keep_every_partial_destination_and_receipt(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    destination = tmp_path / "out" / "regs-dockets-EPA"
    destination.mkdir(parents=True)
    receipt_path = _receipt_path(tmp_path)
    receipt_path.parent.mkdir()

    class PartialRunner(FakeRunner):
        def __call__(self, command: list[str], log_path: Path) -> int:
            if command[3] == "publish" and _flag(command, "--source") == "regulations-dockets":
                self.calls.append(list(command))
                destination.mkdir()
                (destination / "partial.txt").write_text("replacement")
                receipt_path.write_text("replacement receipt")
                return 1
            return super().__call__(command, log_path)

    (destination / "partial.txt").write_text("original")
    receipt_path.write_text("original receipt")
    assert main(args, run_subprocess=PartialRunner(), clock=_clock) == 1
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    assert {
        path.joinpath("partial.txt").read_text() for path in destination.parent.glob("regs-dockets-EPA.failed-*")
    } == {"original", "replacement"}
    assert {path.read_text() for path in receipt_path.parent.glob("regs-dockets-EPA.json.failed-*")} == {
        "original receipt",
        "replacement receipt",
    }


def test_retry_appends_to_the_release_log_instead_of_truncating_it(tmp_path: Path) -> None:
    argv = _argv(tmp_path, agencies=["EPA"])
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
    exit_code = main(_argv(tmp_path, agencies=["EPA"]), run_subprocess=runner, clock=_clock)
    assert exit_code == 1
    assert runner.publications == []
    assert not (tmp_path / "out" / "logs").exists()
    message = capsys.readouterr().err
    assert "campaign.lock is held by" in message and "4242" in message
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == 4242  # the holder's lock is left alone


def test_dry_run_prints_commands_in_order_and_touches_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(tmp_path, agencies=["EPA", "FDA"], dry_run=True)
    exit_code = main(argv, run_subprocess=FakeRunner(), clock=_clock)
    assert exit_code == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 4
    assert "publish" in lines[0] and "--source regulations-dockets" in lines[0] and "--agency EPA" in lines[0]
    assert "--source regulations-documents" in lines[1] and "--agency EPA" in lines[1]
    assert "--agency FDA" in lines[2] and "--agency FDA" in lines[3]
    assert not any("verify" in line for line in lines)
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
    argv = _argv(tmp_path, agencies=["EPA", "FDA"], concurrency=1)
    exit_code = main(argv, run_subprocess=runner, clock=_clock)
    assert exit_code == 1  # interruption is a failure exit even though the one child succeeded

    rows = [json.loads(line) for line in campaign_path.read_text(encoding="utf-8").splitlines()]
    interrupted = [row for row in rows if row.get("status") == "interrupted"]
    assert {(row["release"], row["agency"], row["ok"]) for row in interrupted} == {("regs-dockets-EPA", "EPA", False)}
    assert [_flag(call, "--agency") for call in runner.calls] == ["EPA"]  # documents and FDA never started
    assert not (tmp_path / "out" / "campaign.lock").exists()


def test_signal_terminates_a_real_admission_child_without_completion(tmp_path: Path) -> None:
    args = _argv(tmp_path, agencies=["EPA"])
    assert main(args, run_subprocess=FakeRunner(), clock=_clock) == 0
    before = {path.name: path.read_bytes() for path in (tmp_path / "out" / "receipts").iterdir()}
    row_count = len(_campaign_rows(tmp_path))
    script = tmp_path / "inspect_with_pause.py"
    script.write_text(
        "import sys, time\n"
        "from spicy_docs.cli import source_native\n"
        "from spicy_docs.storage.blobs import LocalSourceNativeBlobStore\n"
        "original_open = LocalSourceNativeBlobStore.open\n"
        "def pause_at_payload(self, blob_ref):\n"
        "    print('reading-retained-payload', flush=True)\n"
        "    time.sleep(30)\n"
        "    return original_open(self, blob_ref)\n"
        "LocalSourceNativeBlobStore.open = pause_at_payload\n"
        "raise SystemExit(source_native.main(sys.argv[1:]))\n"
    )
    main_thread = threading.main_thread().ident
    assert main_thread is not None
    log = tmp_path / "out" / "logs" / "regs-dockets-EPA.log"
    reading_payload = threading.Event()

    def interrupt_admission() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if "reading-retained-payload" in log.read_text():
                reading_payload.set()
                break
            time.sleep(0.01)
        signal.pthread_kill(main_thread, signal.SIGINT)

    calls = []

    def child(command: list[str], log_path: Path) -> int:
        calls.append(command)
        assert command[3] == "inspect"
        return run_child([sys.executable, str(script), *command[3:]], log_path)

    interrupter = threading.Thread(target=interrupt_admission)
    interrupter.start()
    started = time.monotonic()
    try:
        assert main(args, run_subprocess=child, clock=_clock) == 1
    finally:
        interrupter.join(timeout=1)
    assert reading_payload.is_set()
    assert time.monotonic() - started < 15  # the 30-second payload read was terminated
    assert len(calls) == 1  # no documents admission starts after SIGINT
    rows = _campaign_rows(tmp_path)[row_count:]
    assert rows and all(
        row["command"] == "inspect" and row["status"] == "interrupted" and not row["ok"] for row in rows
    )
    assert {path.name: path.read_bytes() for path in (tmp_path / "out" / "receipts").iterdir()} == before
    assert not (tmp_path / "out" / "campaign.lock").exists()

    resumed = FakeRunner()
    assert main(args, run_subprocess=resumed, clock=_clock) == 0
    assert [call[3] for call in resumed.calls] == ["inspect", "inspect"]


def test_pre_stopped_child_is_never_launched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stopping = threading.Event()
    stopping.set()

    def unexpected_launch(*_args, **_kwargs):
        pytest.fail("started a child after the campaign stopped")

    monkeypatch.setattr(campaign.subprocess, "Popen", unexpected_launch)
    log = tmp_path / "child.log"
    assert run_child([sys.executable, "-c", "pass"], log, stopping=stopping) == -signal.SIGTERM
    assert not log.exists()


def test_stop_between_launch_and_registration_terminates_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stopping = threading.Event()
    original = campaign.subprocess.Popen
    children = []

    def launch_then_stop(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        stopping.set()
        campaign._terminate_children()  # the new process is not registered yet
        return process

    monkeypatch.setattr(campaign.subprocess, "Popen", launch_then_stop)
    started = time.monotonic()
    exit_code = run_child(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path / "child.log",
        stopping=stopping,
    )
    assert exit_code == -signal.SIGTERM
    assert time.monotonic() - started < 10
    assert children and all(child.poll() is not None for child in children)
    assert not campaign._CHILDREN
