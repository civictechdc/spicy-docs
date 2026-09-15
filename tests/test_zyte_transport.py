"""The shared Zyte adapter bounds bytes and never surfaces its credential."""

from __future__ import annotations

import base64
import json

import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources import zyte


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

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
