"""Shared retry policy for the Federal Register and public-table HTTP fetchers.

Pins the attempt budget, capped doubling backoff, full jitter, and stderr logs: transport errors, 429/5xx, and empty
responses retry, while other 4xx fail immediately. MockTransport and recorded sleeps keep every test offline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs.transport import http, retry

FIXED_NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _response(status_code: int, content: bytes = b"") -> httpx.Response:
    return httpx.Response(status_code, content=content)


def _scripted_client(*actions: httpx.Response | Exception) -> tuple[httpx.Client, list[httpx.Request]]:
    """A real ``httpx.Client`` over a scripted, no-network ``MockTransport``.

    ``actions`` play back in call order; a call past the end of the script
    repeats the last action, which is enough to prove "keeps retrying until
    the budget is exhausted" without writing out thirteen identical entries.
    """

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        action = actions[min(len(calls) - 1, len(actions) - 1)]
        if isinstance(action, Exception):
            raise action
        return action

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _call_federal_register(client: httpx.Client, url: str) -> bytes | None:
    return http.fetch_federal_register(client, url)


def _call_public_table(client: httpx.Client, url: str) -> bytes | None:
    capture = http.fetch_public_table(client, url, clock=lambda: FIXED_NOW)
    return None if capture is None else capture.content


_FETCHERS = pytest.mark.parametrize(
    "fetch",
    [
        pytest.param(_call_federal_register, id="federal-register"),
        pytest.param(_call_public_table, id="spicy-regs-public-table"),
    ],
)


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace ``time.sleep`` with a recorder: no real sleeping, ever."""

    delays: list[float] = []
    monkeypatch.setattr(retry.time, "sleep", delays.append)
    return delays


@_FETCHERS
def test_transport_error_retries_the_full_budget_then_raises(
    fetch: Callable[[httpx.Client, str], bytes | None],
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(httpx.ConnectError("simulated handshake timeout"))

    with pytest.raises(httpx.ConnectError):
        fetch(client, "https://example.test/persistent-outage")

    assert len(calls) == retry.MAX_HTTP_ATTEMPTS
    assert len(recorded_sleeps) == retry.MAX_HTTP_ATTEMPTS - 1


@_FETCHERS
def test_429_retries_then_a_later_attempt_returns_the_bytes(
    fetch: Callable[[httpx.Client, str], bytes | None],
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(
        _response(429),
        _response(429),
        _response(200, b"payload"),
    )

    assert fetch(client, "https://example.test/throttled") == b"payload"
    assert len(calls) == 3
    assert len(recorded_sleeps) == 2


@_FETCHERS
def test_5xx_retries_then_a_later_attempt_returns_the_bytes(
    fetch: Callable[[httpx.Client, str], bytes | None],
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(_response(503), _response(200, b"payload"))

    assert fetch(client, "https://example.test/unavailable") == b"payload"
    assert len(calls) == 2
    assert len(recorded_sleeps) == 1


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_federal_register_other_4xx_fails_immediately_without_retrying(
    status_code: int,
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(_response(status_code))

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _call_federal_register(client, "https://example.test/refused")

    assert not isinstance(excinfo.value, http.RetryableHTTPStatusError)
    assert len(calls) == 1
    assert recorded_sleeps == []


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_public_table_other_4xx_fails_immediately_without_retrying(
    status_code: int,
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(_response(status_code))

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _call_public_table(client, "https://example.test/refused")

    assert not isinstance(excinfo.value, http.RetryableHTTPStatusError)
    assert len(calls) == 1
    assert recorded_sleeps == []


def test_public_table_404_still_returns_none_without_retrying(
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(_response(404))

    assert _call_public_table(client, "https://example.test/missing-partition") is None
    assert len(calls) == 1
    assert recorded_sleeps == []


def test_federal_register_empty_response_still_retries(recorded_sleeps: list[float]) -> None:
    client, calls = _scripted_client(_response(200, b""), _response(200, b"payload"))

    assert _call_federal_register(client, "https://example.test/flaky-empty") == b"payload"
    assert len(calls) == 2
    assert len(recorded_sleeps) == 1


def test_public_table_empty_response_still_retries(recorded_sleeps: list[float]) -> None:
    client, calls = _scripted_client(_response(200, b""), _response(200, b"payload"))

    assert _call_public_table(client, "https://example.test/flaky-empty") == b"payload"
    assert len(calls) == 2
    assert len(recorded_sleeps) == 1


def test_recorded_sleeps_grow_then_are_capped(
    monkeypatch: pytest.MonkeyPatch,
    recorded_sleeps: list[float],
) -> None:
    """Full jitter draws uniformly up to a deterministic ceiling. Pinning the
    draw to that ceiling (``lambda _lo, hi: hi``) turns the recorded sequence
    into the exact worst-case schedule -- doubling from 2s, capped at 60s --
    so growth-then-cap is a plain equality check instead of a fight with the
    RNG.
    """

    monkeypatch.setattr(retry.random, "uniform", lambda _lo, hi: hi)
    client, calls = _scripted_client(httpx.ConnectError("simulated handshake timeout"))

    with pytest.raises(httpx.ConnectError):
        _call_federal_register(client, "https://example.test/persistent-outage")

    expected = [min(2**attempt, retry.RETRY_BACKOFF_CEILING_SECONDS) for attempt in range(1, retry.MAX_HTTP_ATTEMPTS)]
    assert recorded_sleeps == expected
    assert recorded_sleeps == sorted(recorded_sleeps)
    assert max(recorded_sleeps) == retry.RETRY_BACKOFF_CEILING_SECONDS
    assert recorded_sleeps.count(retry.RETRY_BACKOFF_CEILING_SECONDS) > 1
    assert len(calls) == retry.MAX_HTTP_ATTEMPTS
    # The whole point: worst-case patience is on the order of ten minutes now,
    # not the old thirty seconds.
    assert sum(expected) > 480


def test_retry_logs_attempt_delay_and_reason_to_stderr(
    capsys: pytest.CaptureFixture[str],
    recorded_sleeps: list[float],
) -> None:
    client, _calls = _scripted_client(_response(503), _response(200, b"payload"))

    assert _call_federal_register(client, "https://example.test/flaky-503") == b"payload"

    err = capsys.readouterr().err
    assert f"retry 1/{retry.MAX_HTTP_ATTEMPTS - 1}" in err
    assert "RetryableHTTPStatusError" in err
    assert "retryable Federal Register response" in err


@pytest.mark.parametrize(
    "credential_form", ["exact-key", "api_key", "X-Amz-Credential", "X-Amz-Signature", "X-Amz-Security-Token"]
)
def test_shared_retry_scrubs_credentials_before_truncating_and_logging(
    credential_form: str,
    capsys: pytest.CaptureFixture[str],
    recorded_sleeps: list[float],
) -> None:
    secret = "SYNTHETIC-RETRY-" + "x" * 400
    # A query credential must be scrubbed even when no literal was supplied.
    api_key = secret if credential_form == "exact-key" else ""
    detail = (
        f"X-Api-Key: {secret}; endpoint=fixture"
        if api_key
        else f"https://example.test/?{credential_form}={secret}&format=json"
    )
    attempts = 0

    def operation() -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError(f"connection reset: {detail}")
        return b"payload"

    assert retry.retry_http(operation, retryable=(httpx.RequestError,), api_key=api_key) == b"payload"
    assert attempts == 2 and len(recorded_sleeps) == 1
    log = capsys.readouterr().err
    assert "SYNTHETIC-" not in log
    assert "ConnectError: connection reset:" in log
    assert f"retry 1/{retry.MAX_HTTP_ATTEMPTS - 1} in " in log
    assert "(cap 2s)" in log
    if api_key:
        assert "X-Api-Key: <redacted>; endpoint=fixture" in log
    else:
        assert f"{credential_form}=<redacted>&format=json" in log


@_FETCHERS
def test_keyless_fetchers_scrub_query_credentials_in_retry_errors(
    fetch: Callable[[httpx.Client, str], bytes | None],
    capsys: pytest.CaptureFixture[str],
    recorded_sleeps: list[float],
) -> None:
    client, calls = _scripted_client(
        httpx.ConnectError("connection reset: https://other.example.test/?api_key=SYNTHETIC-REDIRECT&format=json"),
        _response(200, b"payload"),
    )
    with client:
        assert fetch(client, "https://example.test/fixture") == b"payload"
    assert len(calls) == 2 and len(recorded_sleeps) == 1
    log = capsys.readouterr().err
    assert "SYNTHETIC-REDIRECT" not in log
    assert "api_key=<redacted>&format=json" in log
