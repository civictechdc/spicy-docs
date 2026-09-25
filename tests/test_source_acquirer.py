"""Shared request budgets and pacing include source-owned external transports."""

import httpx
import pytest

from spicy_docs.sources import walled_fetch as walled_fetch_module
from spicy_docs.sources.walled_fetch import Transport, WalledFetchResult
from spicy_docs.transport import capture as capture_module
from spicy_docs.transport.http import RetryableHTTPStatusError
from spicy_docs.transport.source_acquirer import SourceAcquirer, utc_now


def test_external_attempts_share_capture_pacing_and_reset_only_for_a_new_operation(monkeypatch):
    elapsed = [0.0]
    sleeps = []
    direct_times = []

    def sleep(delay):
        sleeps.append(delay)
        elapsed[0] += delay

    def handler(_request):
        direct_times.append(elapsed[0])
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, stream=httpx.ByteStream(b"facts"))

    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", sleep)
    source = SourceAcquirer(
        max_requests=2,
        timeout_seconds=1,
        min_request_interval_seconds=3,
        user_agent="test",
        label="test",
        error_type=ValueError,
        context_key="test_context",
        transport=httpx.MockTransport(handler),
    )

    def capture(*, reset_budget=True):
        return source.capture_validated(
            "https://publisher.example/source",
            media_types=("text/plain",),
            parse=lambda response, _limit: response.body,
            max_bytes=100,
            unavailable=lambda _response: ValueError("unavailable"),
            context={},
            reset_budget=reset_budget,
        )

    with source:
        capture()
        source.start_external_request()
        assert source.request_count == 2 and elapsed[0] == 3
        with pytest.raises(ValueError, match="request budget"):
            source.start_external_request()
        assert elapsed[0] == 3
        source.start_external_request(reset_budget=True)
        assert source.request_count == 1 and elapsed[0] == 6
        capture(reset_budget=False)
        assert source.request_count == 2 and elapsed[0] == 9
    assert sleeps == [3, 3, 3] and direct_times == [0, 9]
    with pytest.raises(ValueError, match="closed"):
        source.start_external_request()


def _paced(monkeypatch):
    elapsed = [0.0]

    def sleep(delay):
        elapsed[0] += delay

    monkeypatch.setattr(capture_module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(capture_module.time, "sleep", sleep)
    return elapsed


def _walled_source(handler, *, max_requests=3, keyless=True):
    return SourceAcquirer(
        max_requests=max_requests,
        timeout_seconds=1,
        min_request_interval_seconds=3,
        user_agent="test-agent",
        label="test",
        error_type=ValueError,
        context_key="test_context",
        transport=httpx.MockTransport(handler),
        keyless=keyless,
    )


def _walled_capture(source, **kwargs):
    return source.capture_walled(
        "https://publisher.example/source",
        media_types=("text/plain",),
        parse=lambda response, _limit: response.body,
        max_bytes=100,
        unavailable=lambda _response: ValueError("unavailable"),
        context={"operation": "test"},
        **kwargs,
    )


def test_capture_walled_runs_direct_on_its_own_client_and_resolves_providers_once(monkeypatch):
    """The DIRECT rung is this acquirer's client; proxy rungs share its budget and pacing; providers resolve once."""
    elapsed = _paced(monkeypatch)
    attempts, resolutions = [], []

    def handler(request):
        attempts.append(("direct", elapsed[0], request.headers["user-agent"]))
        return httpx.Response(403, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(b"Access Denied"))

    def zyte(url, **_kwargs):
        attempts.append(("zyte", elapsed[0]))
        return WalledFetchResult(b"facts", 200, "text/plain", url, Transport.ZYTE_HTTP, None, "req-1")

    def resolve(_cls):
        resolutions.append(1)
        return walled_fetch_module.ProxyFetchers(zyte=object(), firecrawl="FIRECRAWL_API_KEY is required")

    monkeypatch.setattr(walled_fetch_module.ProxyFetchers, "from_environment", classmethod(resolve))
    monkeypatch.setattr(walled_fetch_module, "_zyte_rung", zyte)
    with _walled_source(handler) as source:
        body, capture, answer = _walled_capture(source)
        assert (body, capture.body, answer.transport, source.request_count) == (
            b"facts",
            b"facts",
            Transport.ZYTE_HTTP,
            2,
        )
        _walled_capture(source)
    assert attempts == [("direct", 0, "test-agent"), ("zyte", 3), ("direct", 6, "test-agent"), ("zyte", 9)]
    assert resolutions == [1]


def test_capture_walled_is_for_keyless_routes_only():
    """A keyed route must abort on a credential refusal, so it may not escalate one to a proxy."""
    with (
        _walled_source(lambda _request: pytest.fail("no request"), keyless=False) as source,
        pytest.raises(ValueError, match="keyless"),
    ):
        _walled_capture(source)


def test_capture_walled_names_ladder_exhaustion_with_the_callers_refusal(monkeypatch):
    class Refused(RuntimeError):
        def __init__(self, url):
            super().__init__(f"refused {url}")

    blocked = b"<title>Attention Required! | Cloudflare</title>"
    monkeypatch.setattr(
        walled_fetch_module.ProxyFetchers,
        "from_environment",
        classmethod(lambda _cls: walled_fetch_module.ProxyFetchers(zyte="no key", firecrawl="no key")),
    )

    def handler(_request):
        return httpx.Response(403, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(blocked))

    with _walled_source(handler) as source, pytest.raises(Refused) as raised:
        _walled_capture(source, refusal=Refused)
    assert raised.value.refused_response.response_bytes == blocked
    assert [outcome.kind for outcome in raised.value.rung_outcomes] == ["wall", "credential-error", "credential-error"]
    assert raised.value.test_context == {"operation": "test", "route": "walled-ladder", "requestCount": 1}


def test_a_capture_can_hold_itself_to_fewer_attempts_than_its_budget():
    attempts = []

    def handler(_request):
        attempts.append(1)
        return httpx.Response(503, stream=httpx.ByteStream(b"busy"))

    client = capture_module.BoundedHttpCapture(
        max_requests=3,
        timeout_seconds=1,
        min_request_interval_seconds=0,
        user_agent="test",
        error_type=ValueError,
        transport=httpx.MockTransport(handler),
        clock=utc_now,
    )
    with pytest.raises(RetryableHTTPStatusError):
        client.capture("https://publisher.example/source", max_bytes=100, max_attempts=1)
    assert attempts == [1] and client.request_count == 1
