"""The shared Zyte adapter bounds bytes and never surfaces its credential."""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources import zyte
from spicy_docs.transport.capture import BoundedHttpCapture
from spicy_docs.transport.zyte import ZyteBudget, ZyteTransport

PRODUCT_URL = "https://www.gao.gov/products/gao-26-107693"


class _Response:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        #: A real provider response always carries headers; a stub that omits
        #: them would hide the request-id read rather than exercise it.
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_fetch_returns_exact_target_bytes_from_a_bounded_provider_response(monkeypatch) -> None:
    body = b"<html>exact target bytes</html>"
    provider = json.dumps(
        {
            "httpResponseBody": base64.b64encode(body).decode(),
            "httpResponseHeaders": [{"name": "Content-Type", "value": "text/html"}],
            "statusCode": 200,
            "url": "https://www.gao.gov/products/gao-26-107693",
        }
    ).encode()
    requests = []

    def open_request(request, *, timeout: float):
        requests.append((request, timeout))
        return _Response(provider)

    monkeypatch.setattr(zyte.urllib.request, "urlopen", open_request)
    response = zyte.ZyteHttpFetcher(token="test-token").fetch(
        "https://www.gao.gov/products/gao-26-107693",
        timeout_seconds=9.0,
        max_bytes=1024,
    )

    assert response.body == body
    assert response.status_code == 200
    assert response.content_type == "text/html"
    assert requests[0][1] == 9.0
    assert b"test-token" not in requests[0][0].data


def test_token_validation_errors_never_repeat_the_secret() -> None:
    secret = " secret-value "

    with pytest.raises(zyte.ZyteTransportError) as raised:
        zyte.ZyteHttpFetcher(token=secret)

    assert "secret-value" not in str(raised.value)


def test_fetcher_representation_does_not_expose_the_credential() -> None:
    assert "secret-value" not in repr(zyte.ZyteHttpFetcher(token="secret-value"))


def test_fetch_refuses_target_bytes_over_the_caller_bound(monkeypatch) -> None:
    provider = json.dumps(
        {
            "httpResponseBody": base64.b64encode(b"12345").decode(),
            "httpResponseHeaders": [{"name": "Content-Type", "value": "text/html"}],
            "statusCode": 200,
            "url": "https://www.gao.gov/products/gao-26-107693",
        }
    ).encode()
    monkeypatch.setattr(zyte.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(provider))

    with pytest.raises(zyte.ZyteTransportError, match="max_bytes") as raised:
        zyte.ZyteHttpFetcher(token="test-token").fetch(
            "https://www.gao.gov/products/gao-26-107693",
            timeout_seconds=9.0,
            max_bytes=4,
        )
    context = getattr(raised.value, "refused_response", None)
    assert isinstance(context, RefusedResponse)
    assert context.unavailable_reason == "response-byte-limit"
    assert context.observed_byte_size == 5
    assert context.response_bytes is None


@pytest.mark.parametrize("location", ["body", "resolved-url", "content-type"])
@pytest.mark.parametrize("encoded", [False, True])
def test_reflected_credentials_are_unavailable_evidence(monkeypatch, location: str, encoded: bool) -> None:
    # Deliberately shorter than logging's replacement threshold: the transport
    # knows the credential and must not retain it even when it is short.
    token = "s3cr!t"
    reflected = base64.b64encode(f"{token}:".encode()).decode() if encoded else token
    body = f"<html>{reflected}</html>".encode() if location == "body" else b"<html>publisher page</html>"
    url = "https://www.gao.gov/products/gao-26-107693"
    provider = json.dumps(
        {
            "httpResponseBody": base64.b64encode(body).decode(),
            "httpResponseHeaders": [
                {"name": "Content-Type", "value": reflected if location == "content-type" else "text/html"}
            ],
            "statusCode": 200,
            "url": url + f"?echo={reflected}" if location == "resolved-url" else url,
        }
    ).encode()
    monkeypatch.setattr(zyte.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(provider))
    with pytest.raises(zyte.ZyteTransportError, match="reflected transport credential") as raised:
        zyte.ZyteHttpFetcher(token=token).fetch(url, timeout_seconds=9, max_bytes=1024)
    context = getattr(raised.value, "refused_response", None)
    assert isinstance(context, RefusedResponse)
    assert context.unavailable_reason == "credential-suppressed"
    assert context.response_bytes is None
    assert context.observed_byte_size == len(body)
    assert token not in str(raised.value) + repr(context)
    assert reflected not in str(raised.value) + repr(context)


def test_empty_received_target_body_is_distinct_from_missing_provider_field(monkeypatch) -> None:
    provider = json.dumps(
        {
            "httpResponseBody": "",
            "httpResponseHeaders": [{"name": "Content-Type", "value": "text/html"}],
            "statusCode": 200,
        }
    ).encode()
    monkeypatch.setattr(zyte.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(provider))
    response = zyte.ZyteHttpFetcher(token="test-token").fetch(
        "https://www.gao.gov/products/gao-26-107693", timeout_seconds=9, max_bytes=1024
    )
    assert response.body == b""


def test_browser_html_is_a_rendering_and_states_no_publisher_media_type(monkeypatch) -> None:
    """A rendered DOM is not bytes any publisher sent, so no Content-Type is invented for it."""
    provider = json.dumps({"browserHtml": "<html>rendered</html>", "statusCode": 200, "url": PRODUCT_URL}).encode()
    sent: list[bytes] = []

    def open_request(request, *, timeout: float):
        sent.append(request.data)
        return _Response(provider)

    monkeypatch.setattr(zyte.urllib.request, "urlopen", open_request)
    response = zyte.ZyteHttpFetcher(token="test-token").fetch(
        PRODUCT_URL, timeout_seconds=9, max_bytes=1024, mode=zyte.BROWSER_HTML
    )

    assert response.body == b"<html>rendered</html>"
    assert response.mode == zyte.BROWSER_HTML
    assert response.content_type is None
    assert b'"browserHtml":true' in sent[0]
    assert b"httpResponseBody" not in sent[0]


def test_an_unsupported_mode_is_refused_before_any_provider_request(monkeypatch) -> None:
    monkeypatch.setattr(
        zyte.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no provider request should be made")
    )
    with pytest.raises(zyte.ZyteTransportError, match="mode"):
        zyte.ZyteHttpFetcher(token="test-token").fetch(
            PRODUCT_URL, timeout_seconds=9, max_bytes=1024, mode="screenshot"
        )


def test_the_provider_request_id_is_read_from_its_response_headers(monkeypatch) -> None:
    monkeypatch.setattr(
        zyte.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(_ok_provider(b"body"), headers={"Request-Id": " abc123 ", "Server": "zyte"}),
    )
    response = zyte.ZyteHttpFetcher(token="test-token").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
    assert response.request_id == "abc123"


def test_a_provider_error_names_its_own_kind_and_never_its_prose_or_the_credential(monkeypatch) -> None:
    payload = json.dumps({"type": "/download/temporary-error", "title": "secret-value leaked prose"}).encode()

    def open_request(*_args, **_kwargs):
        raise zyte.urllib.error.HTTPError(zyte.ZYTE_API_URL, 520, "error", {}, io.BytesIO(payload))

    monkeypatch.setattr(zyte.urllib.request, "urlopen", open_request)
    with pytest.raises(zyte.ZyteTransportError) as raised:
        zyte.ZyteHttpFetcher(token="secret-value").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)

    assert "520" in str(raised.value)
    assert "/download/temporary-error" in str(raised.value)
    assert "secret-value" not in str(raised.value)
    assert "prose" not in str(raised.value)


def _ok_provider(body: bytes, url: str = PRODUCT_URL) -> bytes:
    return json.dumps(
        {
            "httpResponseBody": base64.b64encode(body).decode(),
            "httpResponseHeaders": [{"name": "Content-Type", "value": "text/html"}],
            "statusCode": 200,
            "url": url,
        }
    ).encode()


def _capture_client(transport: ZyteTransport) -> BoundedHttpCapture:
    return BoundedHttpCapture(
        max_requests=2,
        timeout_seconds=9,
        min_request_interval_seconds=0,
        user_agent="test",
        error_type=ValueError,
        transport=transport,
        clock=lambda: datetime.now(UTC),
        retain_refusal_bodies=True,
    )


def test_the_injectable_transport_captures_a_body_and_records_that_it_was_proxied(monkeypatch) -> None:
    """The whole point of the shape: a source acquirer's own client, over Zyte, with provenance."""
    monkeypatch.setattr(
        zyte.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(_ok_provider(b"<html>page</html>"), headers={"request-id": "rq-1"}),
    )
    transport = ZyteTransport(zyte.ZyteHttpFetcher(token="test-token"), max_bytes=1024, timeout_seconds=9)
    client = _capture_client(transport)
    client.reset_budget()

    capture = client.capture(PRODUCT_URL, max_bytes=1024)

    assert capture.status_code == 200
    assert capture.body == b"<html>page</html>"
    assert capture.content_type == "text/html"
    (record,) = transport.records
    assert (record.ordinal, record.mode, record.zyte_request_id) == (1, zyte.HTTP_RESPONSE_BODY, "rq-1")
    assert record.proxied_client == "zyte"
    assert record.body_is_publisher_bytes is True
    assert record.byte_size == len(capture.body)
    client.close()


def test_a_proxied_capture_carries_its_record_on_the_response_extensions(monkeypatch) -> None:
    monkeypatch.setattr(zyte.urllib.request, "urlopen", lambda *_a, **_k: _Response(_ok_provider(b"x")))
    transport = ZyteTransport(zyte.ZyteHttpFetcher(token="test-token"), max_bytes=1024, timeout_seconds=9)
    response = transport.handle_request(httpx.Request("GET", PRODUCT_URL))
    assert response.extensions["zyte_proxy_record"] is transport.records[0]


def test_the_transport_proxies_only_get(monkeypatch) -> None:
    """A target POST body has nowhere to go; sending a GET instead would answer another request."""
    monkeypatch.setattr(
        zyte.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no provider request should be made")
    )
    transport = ZyteTransport(zyte.ZyteHttpFetcher(token="test-token"), max_bytes=1024, timeout_seconds=9)
    with pytest.raises(zyte.ZyteTransportError, match="GET"):
        transport.handle_request(httpx.Request("POST", PRODUCT_URL, content=b"{}"))


def test_a_proxy_redirect_is_refused_rather_than_reported_as_the_requested_url(monkeypatch) -> None:
    monkeypatch.setattr(
        zyte.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(_ok_provider(b"x", url=PRODUCT_URL + "/moved")),
    )
    transport = ZyteTransport(zyte.ZyteHttpFetcher(token="test-token"), max_bytes=1024, timeout_seconds=9)
    with pytest.raises(zyte.ZyteTransportError, match="different URL"):
        transport.handle_request(httpx.Request("GET", PRODUCT_URL))


def test_the_shared_budget_stops_provider_calls_at_its_ceiling(monkeypatch) -> None:
    calls: list[object] = []

    def open_request(*_args, **_kwargs):
        calls.append(None)
        return _Response(_ok_provider(b"x"))

    monkeypatch.setattr(zyte.urllib.request, "urlopen", open_request)
    budget = ZyteBudget(1)
    fetcher = zyte.ZyteHttpFetcher(token="test-token")
    first = ZyteTransport(fetcher, max_bytes=1024, timeout_seconds=9, budget=budget)
    second = ZyteTransport(fetcher, max_bytes=1024, timeout_seconds=9, budget=budget)

    first.handle_request(httpx.Request("GET", PRODUCT_URL))
    with pytest.raises(zyte.ZyteTransportError, match="budget"):
        second.handle_request(httpx.Request("GET", PRODUCT_URL))

    assert len(calls) == 1
    assert budget.spent == 1
