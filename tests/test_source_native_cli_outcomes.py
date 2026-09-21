"""Publish, verify, and inspect expose the same collection facts.

Inspect defaults to 20 failures, enforces the profile pin and verifier allowlist, and refuses a negative failure
limit before reading the release."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from spicy_docs.cli.source_native import main
from tests.releases.fixtures import _document
from tests.source_fixtures import federal_response
from tests.test_source_native_cli import FIXED_NOW, _publish_args, _verify_args


def _publish_documents(destination: Path, *documents: dict[str, object]) -> dict[str, object]:
    output = StringIO()
    errors = StringIO()
    assert (
        main(
            _publish_args(destination, "federal-register"),
            fetch=lambda _url: federal_response(*documents),
            clock=lambda: FIXED_NOW,
            stdout=output,
            stderr=errors,
        )
        == 0
    ), errors.getvalue()
    return json.loads(output.getvalue())


@pytest.mark.parametrize(
    ("valid", "rejected", "outcome"),
    [(0, 0, "empty"), (2, 0, "no-record-rejections"), (1, 2, "partial-rejection"), (0, 2, "total-rejection")],
)
def test_cli_shares_outcomes_across_publish_verify_and_inspect(
    tmp_path: Path, valid: int, rejected: int, outcome: str
) -> None:
    destination = tmp_path / "release"
    documents = [_document(f"2026-{number:05d}") for number in range(valid)]
    documents.extend(_document(f"2026-{number + valid:05d}", title=False) for number in range(rejected))
    published = _publish_documents(destination, *documents)
    expected = published["collectionOutcome"]
    measurements = published["byteMeasurements"]
    assert isinstance(expected, dict)
    assert isinstance(measurements, dict)
    assert measurements["publicationBytesWritten"] == sum(
        path.stat().st_size for path in destination.rglob("*") if path.is_file()
    )
    assert measurements["payloadBytesRead"] == measurements["payloadBytesWritten"] > 0
    assert measurements["payloadBytesReused"] == 0
    assert "byteMeasurements" not in json.loads((destination / "receipts/publication.json").read_bytes())
    assert expected["recordOutcome"] == outcome
    assert expected["publishedRecordCount"] == valid
    assert expected["failedRecordCount"] == rejected

    for command in ("verify", "inspect"):
        args = _verify_args(destination, "federal-register", published)
        args[0] = command
        if command == "inspect":
            args.extend(["--failure-limit", "1"])
        output, errors = StringIO(), StringIO()
        assert main(args, stdout=output, stderr=errors) == 0, errors.getvalue()
        result = json.loads(output.getvalue())
        assert result["collectionOutcome"] == expected
        assert "byteMeasurements" not in result  # admission cannot reconstruct the producer's storage work
        assert result["command"] == command
        assert result["artifactDigest"] == published["artifactDigest"]
        # Command success describes verification/admission, not record acceptance.
        assert result["ok"] is True
        if command == "inspect":
            assert result["failureLimit"] == 1
            assert len(result["failures"]) == min(1, rejected)
            assert result["failuresTruncated"] is (rejected > 1)
            assert all(row["failure"]["class"] == "deterministic" for row in result["failures"])


def test_inspect_defaults_to_twenty_failures_and_allows_outcome_only(tmp_path: Path) -> None:
    destination = tmp_path / "release"
    published = _publish_documents(destination, *(_document(f"2026-{n:05d}", title=False) for n in range(25)))
    args = _verify_args(destination, "federal-register", published)
    args[0] = "inspect"

    for options, limit in (([], 20), (["--failure-limit", "0"], 0)):
        output = StringIO()
        assert main([*args, *options], stdout=output, stderr=StringIO()) == 0
        result = json.loads(output.getvalue())
        assert result["failureLimit"] == limit
        assert len(result["failures"]) == limit
        assert result["failuresTruncated"] is True
        assert result["collectionOutcome"]["failedRecordCount"] == 25


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--source", "regulations-documents"),
        ("--artifact-digest", "sha256:" + "0" * 64),
        ("--accepted-verifier-implementation-id", "git+https://example.test/unaccepted@" + "b" * 40),
    ],
)
def test_inspect_enforces_profile_pin_and_verifier_allowlist(tmp_path: Path, option: str, value: str) -> None:
    destination = tmp_path / "release"
    published = _publish_documents(destination, _document())
    args = _verify_args(destination, "federal-register", published)
    args[0] = "inspect"
    args[args.index(option) + 1] = value
    output, errors = StringIO(), StringIO()

    assert main(args, stdout=output, stderr=errors) == 1
    assert output.getvalue() == ""
    assert json.loads(errors.getvalue())["ok"] is False


def test_inspect_refuses_negative_failure_limit_before_reading(tmp_path: Path, capsys) -> None:
    args = _verify_args(tmp_path / "absent", "federal-register", {"logicalId": "unused", "artifactDigest": "unused"})
    args[0] = "inspect"

    with pytest.raises(SystemExit) as error:
        main([*args, "--failure-limit", "-1"])
    assert error.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err
