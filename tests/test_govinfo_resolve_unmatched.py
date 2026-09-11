"""The keyed diagnostic records evidence without turning missing evidence into absence."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.transport import retry
from tools.analysis.govinfo_resolve_unmatched import CredentialRefusedError, granule_ids, run

DIGEST = "sha256:" + "a" * 64
DATE = "1995-04-10"


def _census(path: Path, *, digest: str | None = DIGEST) -> Path:
    path.write_text(
        json.dumps(
            {
                "publicationDate": DATE,
                "sourceReleaseDigest": digest,
                "status": "listed",
                "ourNumbersUnmatched": ["95-8641", "95-8642"],
            }
        )
        + "\n"
    )
    return path


def _rows(output: Path) -> list[dict]:
    return [json.loads(line) for line in output.read_text().splitlines()]


def _complete() -> dict:
    return {"granules": [{"granuleId": "95-8641-Filed"}], "count": 1, "nextPage": None}


def _run(census: Path, output: Path, handler) -> int:
    return run(
        census, output, api_key="test-api-secret", min_interval_seconds=0, transport=httpx.MockTransport(handler)
    )


def test_populated_complete_listing_names_matches_and_endpoint_nonmatches(tmp_path: Path) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_complete())

    assert _run(census, output, handler) == 0
    row = _rows(output)[0]
    assert row["status"] == "listed"
    assert row["sourceReleaseDigest"] == DIGEST
    assert row["numbers"] == [
        {"number": "95-8641", "verdict": "fused-match", "granuleIds": ["95-8641-Filed"]},
        {"number": "95-8642", "verdict": "not-listed", "granuleIds": None},
    ]
    assert requests[0].headers["X-Api-Key"] == "test-api-secret"
    assert "test-api-secret" not in str(requests[0].url)
    assert "test-api-secret" not in output.read_text()
    assert _run(census, output, handler) == 0
    assert len(requests) == 1  # a complete listing settles this exact input


@pytest.mark.parametrize("status", [401, 403])
def test_credential_refusal_aborts_without_recording_or_retrying(tmp_path: Path, status: int) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    with pytest.raises(CredentialRefusedError, match=f"HTTP {status}"):
        _run(census, output, handler)
    assert len(requests) == 1
    assert output.read_text() == ""


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"granules": [], "count": 0}, "listing-empty"),
        ({"granules": [{"granuleId": "unrelated"}], "count": 2}, "listing-incomplete"),
        ({"granules": [{"granuleId": "unrelated"}], "count": 1, "nextPage": "page-2"}, "listing-incomplete"),
        ({"granules": [{"granuleId": "same"}, {"granuleId": "same"}], "count": 2}, "listing-incomplete"),
        ({"granules": [{"granuleId": "unrelated"}]}, "listing-invalid"),
        ({"granules": [{"granuleId": "unrelated"}], "count": True}, "listing-invalid"),
        ({"granules": [{}], "count": 1}, "listing-invalid"),
        ({"granules": [], "count": -1}, "listing-invalid"),
    ],
)
def test_indeterminate_listings_never_mean_absence_and_retry_on_resume(tmp_path, payload, expected_status) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    assert _run(census, output, lambda request: httpx.Response(200, json=payload)) == 1
    row = _rows(output)[0]
    assert row["status"] == expected_status
    assert {item["verdict"] for item in row["numbers"]} == {expected_status}
    assert all(item["granuleIds"] is None for item in row["numbers"])
    assert _run(census, output, lambda request: httpx.Response(200, json=_complete())) == 0
    assert [row["status"] for row in _rows(output)] == [expected_status, "listed"]


def test_recorded_request_failure_is_retried(tmp_path: Path) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    assert _run(census, output, lambda request: httpx.Response(404)) == 1
    assert _rows(output)[0]["httpStatus"] == 404
    assert _run(census, output, lambda request: httpx.Response(200, json=_complete())) == 0
    assert [row["status"] for row in _rows(output)] == ["request-failed", "listed"]


@pytest.mark.parametrize("failure", [429, 503, "request-error"])
@pytest.mark.parametrize("recovers", [True, False], ids=["recovers", "exhausts"])
def test_retryable_requests_recover_or_record_exhaustion_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, failure: int | str, recovers: bool
) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    requests = []
    delays = []
    monkeypatch.setattr(retry.random, "uniform", lambda lower, upper: upper)
    monkeypatch.setattr(retry.time, "sleep", delays.append)
    monkeypatch.setattr(retry.time, "monotonic", lambda: 100.0)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if recovers and len(requests) == 2:
            return httpx.Response(200, json=_complete())
        if failure == "request-error":
            raise httpx.ConnectError("connection failed with X-Api-Key=test-api-secret", request=request)
        return httpx.Response(failure, text="upstream request included X-Api-Key=test-api-secret")

    assert _run(census, output, handler) == (0 if recovers else 1)
    expected_attempts = 2 if recovers else retry.MAX_HTTP_ATTEMPTS
    assert len(requests) == expected_attempts
    assert len(delays) == expected_attempts - 1
    assert all(0 < delay <= retry.RETRY_BACKOFF_CEILING_SECONDS for delay in delays)
    rows = _rows(output)
    assert len(rows) == 1  # retry attempts do not look like separate settled observations
    assert rows[0]["status"] == ("listed" if recovers else "request-failed")
    assert rows[0]["sourceReleaseDigest"] == DIGEST
    if not recovers:
        assert rows[0]["httpStatus"] == (None if failure == "request-error" else failure)
        assert {item["verdict"] for item in rows[0]["numbers"]} == {"request-failed"}
    captured = capsys.readouterr()
    assert "test-api-secret" not in output.read_text() + captured.out + captured.err
    if failure == "request-error":
        assert "ConnectError: connection failed" in captured.err
        assert "<redacted>" in captured.err


def test_direct_listing_caller_without_credential_header_retries_normally(monkeypatch, capsys) -> None:
    attempts = 0
    monkeypatch.setattr(retry.time, "sleep", lambda delay: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection temporarily unavailable", request=request)
        return httpx.Response(200, json=_complete())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        listing = granule_ids(client, DATE)
    assert listing.status == "listed"
    assert attempts == 2
    assert "ConnectError: connection temporarily unavailable" in capsys.readouterr().err


def test_full_page_remains_incomplete_even_when_count_matches(tmp_path: Path) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    payload = {"granules": [{"granuleId": f"number-{index}"} for index in range(1000)], "count": 1000}
    assert _run(census, output, lambda request: httpx.Response(200, json=payload)) == 1
    row = _rows(output)[0]
    assert row["status"] == "listing-incomplete"
    assert {item["verdict"] for item in row["numbers"]} == {"listing-incomplete"}


def test_census_requires_recorded_source_digest_before_network_or_output(tmp_path: Path) -> None:
    census, output = _census(tmp_path / "census.jsonl", digest=None), tmp_path / "output.jsonl"
    with pytest.raises(ValueError, match="every census row must carry sourceReleaseDigest"):
        _run(census, output, lambda request: pytest.fail("must not request"))
    assert not output.exists()


@pytest.mark.parametrize("digest", [None, "sha256:" + "b" * 64])
def test_resume_requires_same_recorded_source_digest(tmp_path: Path, digest: str | None) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    previous = json.dumps({"publicationDate": DATE, "sourceReleaseDigest": digest}) + "\n"
    output.write_text(previous)
    with pytest.raises(ValueError, match="same sourceReleaseDigest"):
        _run(census, output, lambda request: pytest.fail("must not request"))
    assert output.read_text() == previous


def test_changed_unmatched_numbers_are_queried_again_for_same_release(tmp_path: Path) -> None:
    census, output = _census(tmp_path / "census.jsonl"), tmp_path / "output.jsonl"
    assert _run(census, output, lambda request: httpx.Response(200, json=_complete())) == 0
    row = json.loads(census.read_text())
    row["ourNumbersUnmatched"].append("95-8643")
    census.write_text(json.dumps(row) + "\n")
    assert _run(census, output, lambda request: httpx.Response(200, json=_complete())) == 0
    assert len(_rows(output)) == 2
    assert len(_rows(output)[1]["numbers"]) == 3
