"""Transport-retry patience for the two source-native HTTP fetchers.

2026-09-02: a full-history Federal Register crawl lost hours of work to one
``_ssl.c:993: The handshake operation timed out`` while competing with a
heavy S3 fan-out. The old policy -- five attempts inside about thirty seconds
of total sleep -- gave up long before a transient network disturbance could
resolve. These tests pin the replacement policy (``_MAX_HTTP_ATTEMPTS``
attempts, a doubling backoff capped at ``_RETRY_BACKOFF_CEILING_SECONDS``,
full jitter, and a stderr line per retry) against both ``_fetch_with_retries``
(Federal Register) and ``_fetch_public_table`` (the spicy-regs public
tables), which share the ``retry_http`` helper and therefore the same
classification: 429 and 5xx and transport errors retry; any other 4xx and an
empty response behave exactly as before (immediate failure and retry,
respectively).

Nothing here touches the network -- every client is a real ``httpx.Client``
backed by a scripted, in-memory ``httpx.MockTransport``, and ``time.sleep``
is monkeypatched to record instead of sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs import source_native_cli
from spicy_docs.transport import retry

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
    return source_native_cli._fetch_with_retries(client, url)


def _call_public_table(client: httpx.Client, url: str) -> bytes | None:
    capture = source_native_cli._fetch_public_table(client, url, clock=lambda: FIXED_NOW)
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

    assert not isinstance(excinfo.value, source_native_cli._RetryableHTTPStatusError)
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

    assert not isinstance(excinfo.value, source_native_cli._RetryableHTTPStatusError)
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
    assert "_RetryableHTTPStatusError" in err
    assert "retryable Federal Register response" in err
