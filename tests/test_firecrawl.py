"""The shared Firecrawl adapter bounds bytes, captures provider provenance, and never surfaces its key.

Only the v2 scrape endpoint is called, the provider payload is bounded, provider errors name their
closed-vocabulary slug rather than prose, and reflected credentials are suppressed from evidence."""

from __future__ import annotations

import base64
import io
import json

import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources import firecrawl

PRODUCT_URL = "https://www.gao.gov/products/gao-26-107693"


class _Response:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def _ok_provider(
    body: bytes,
    url: str = PRODUCT_URL,
    status: int = 200,
    content_type: str = "text/html",
    mode: str = firecrawl.RAW_BASE64,
) -> bytes:
    data: dict = {
        "metadata": {"statusCode": status, "contentType": content_type, "url": url},
    }
    data[mode] = base64.b64encode(body).decode() if mode == firecrawl.RAW_BASE64 else body.decode()
    return json.dumps({"success": True, "data": data}).encode()


def test_fetch_returns_exact_target_bytes_from_a_bounded_provider_response(monkeypatch) -> None:
    body = b"<html>exact target bytes</html>"
    requests = []

    def open_request(request, *, timeout: float):
        requests.append((request, timeout))
        return _Response(_ok_provider(body))

    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", open_request)
    response = firecrawl.FirecrawlFetcher(key="test-key").fetch(
        PRODUCT_URL,
        timeout_seconds=9.0,
        max_bytes=1024,
    )

    assert response.body == body
    assert response.status_code == 200
    assert response.content_type == "text/html"
    assert response.mode == firecrawl.RAW_BASE64
    assert requests[0][1] == 9.0
    request, _timeout = requests[0]
    assert request.get_header("Authorization") == "Bearer test-key"
    assert b"test-key" not in request.data
    sent = json.loads(request.data)
    assert sent == {
        "url": PRODUCT_URL,
        "formats": [firecrawl.RAW_BASE64],
        "parsers": [],
        "maxAge": 0,
        "timeout": 9000,
        "storeInCache": False,
    }
    assert request.get_header("X-request-id") == response.request_id
    assert response.request_id


def test_key_validation_errors_never_repeat_the_secret() -> None:
    secret = " secret-value "

    with pytest.raises(firecrawl.FirecrawlTransportError) as raised:
        firecrawl.FirecrawlFetcher(key=secret)

    assert "secret-value" not in str(raised.value)


def test_fetcher_representation_does_not_expose_the_credential() -> None:
    assert "secret-value" not in repr(firecrawl.FirecrawlFetcher(key="secret-value"))


def test_a_missing_key_names_the_environment_variable_and_not_a_value(monkeypatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    with pytest.raises(firecrawl.FirecrawlTransportError, match="FIRECRAWL_API_KEY is required for live acquisition"):
        firecrawl.FirecrawlFetcher.from_environment()


def test_fetch_refuses_target_bytes_over_the_caller_bound(monkeypatch) -> None:
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(_ok_provider(b"12345")))

    with pytest.raises(firecrawl.FirecrawlTransportError, match="max_bytes") as raised:
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=4)
    context = getattr(raised.value, "refused_response", None)
    assert isinstance(context, RefusedResponse)
    assert context.unavailable_reason == "response-byte-limit"
    assert context.observed_byte_size == 5
    assert context.response_bytes is None


@pytest.mark.parametrize("location", ["body", "resolved-url", "content-type"])
@pytest.mark.parametrize("with_bearer", [False, True])
def test_reflected_credentials_are_unavailable_evidence(monkeypatch, location: str, with_bearer: bool) -> None:
    # Deliberately shorter than logging's replacement threshold: the transport
    # knows the credential and must not retain it even when it is short.
    key = "s3cr!t"
    reflected = f"Bearer {key}" if with_bearer else key
    body = f"<html>{reflected}</html>".encode() if location == "body" else b"<html>publisher page</html>"
    url = PRODUCT_URL
    provider = json.dumps(
        {
            "success": True,
            "data": {
                "rawBase64": base64.b64encode(body).decode(),
                "metadata": {
                    "statusCode": 200,
                    "contentType": reflected if location == "content-type" else "text/html",
                    "url": url + f"?echo={reflected}" if location == "resolved-url" else url,
                },
            },
        }
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="reflected transport credential") as raised:
        firecrawl.FirecrawlFetcher(key=key).fetch(url, timeout_seconds=9, max_bytes=1024)
    context = getattr(raised.value, "refused_response", None)
    assert isinstance(context, RefusedResponse)
    assert context.unavailable_reason == "credential-suppressed"
    assert context.response_bytes is None
    assert context.observed_byte_size == len(body)
    assert key not in str(raised.value) + repr(context)
    assert reflected not in str(raised.value) + repr(context)


def test_empty_received_target_body_is_distinct_from_missing_provider_field(monkeypatch) -> None:
    provider = json.dumps(
        {
            "success": True,
            "data": {"rawBase64": "", "metadata": {"statusCode": 200, "contentType": "text/html", "url": PRODUCT_URL}},
        }
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    response = firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
    assert response.body == b""


def test_raw_html_mode_returns_the_publisher_html_and_states_its_content_type(monkeypatch) -> None:
    provider = json.dumps(
        {
            "success": True,
            "data": {
                "rawHtml": "<html>exact html</html>",
                "metadata": {"statusCode": 200, "contentType": "text/html; charset=utf-8", "url": PRODUCT_URL},
            },
        }
    ).encode()
    sent: list[bytes] = []

    def open_request(request, *, timeout: float):
        sent.append(request.data)
        return _Response(provider)

    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", open_request)
    response = firecrawl.FirecrawlFetcher(key="test-key").fetch(
        PRODUCT_URL, timeout_seconds=9, max_bytes=1024, mode=firecrawl.RAW_HTML
    )

    assert response.body == b"<html>exact html</html>"
    assert response.mode == firecrawl.RAW_HTML
    # rawHtml is the publisher's own HTML, so its stated media type travels with it.
    assert response.content_type == "text/html; charset=utf-8"
    assert b'"rawHtml"' in sent[0]
    assert b"rawBase64" not in sent[0]


def test_an_unsupported_mode_is_refused_before_any_provider_request(monkeypatch) -> None:
    monkeypatch.setattr(
        firecrawl.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no provider request should be made")
    )
    with pytest.raises(firecrawl.FirecrawlTransportError, match="mode"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(
            PRODUCT_URL, timeout_seconds=9, max_bytes=1024, mode="screenshot"
        )


@pytest.mark.parametrize("timeout", [0.5, 0.0, 300.5])
def test_a_timeout_outside_the_provider_bounds_is_refused_before_any_request(monkeypatch, timeout: float) -> None:
    monkeypatch.setattr(
        firecrawl.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no provider request should be made")
    )
    with pytest.raises(firecrawl.FirecrawlTransportError, match="timeout_seconds"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=timeout, max_bytes=1024)


def test_a_provider_http_error_names_its_status_and_code_slug_never_prose(monkeypatch) -> None:
    payload = json.dumps(
        {"success": False, "error": "Payment required to access this resource.", "code": "insufficient_credits"}
    ).encode()

    def open_request(*_args, **_kwargs):
        raise firecrawl.urllib.error.HTTPError(firecrawl.FIRECRAWL_API_URL, 402, "error", {}, io.BytesIO(payload))

    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", open_request)
    with pytest.raises(firecrawl.FirecrawlTransportError) as raised:
        firecrawl.FirecrawlFetcher(key="secret-value").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)

    assert "402" in str(raised.value)
    assert "insufficient_credits" in str(raised.value)
    assert "Payment" not in str(raised.value)
    assert "secret-value" not in str(raised.value)


def test_a_200_success_false_reports_the_known_engine_failure_slug_never_prose(monkeypatch) -> None:
    provider = json.dumps({"success": False, "error": "All scraping engines failed"}).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="provider reported failure") as raised:
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
    assert "all_scraping_engines_failed" in str(raised.value)
    assert "All scraping engines failed" not in str(raised.value)


def test_a_success_false_without_a_known_wording_names_only_the_provider_failure(monkeypatch) -> None:
    provider = json.dumps({"success": False, "error": "some new prose"}).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="provider reported failure") as raised:
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
    assert "some new prose" not in str(raised.value)


def test_the_provider_payload_read_is_bounded(monkeypatch) -> None:
    class _FullResponse(_Response):
        def read(self, limit: int) -> bytes:
            return b"x" * limit

    # A response that answers the read bound in full exceeds the provider
    # payload ceiling, so the whole body is refused, never truncated.
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _FullResponse(b""))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="bounded provider payload size"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_a_provider_response_that_omits_success_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(json.dumps({"data": {}}).encode())
    )
    with pytest.raises(firecrawl.FirecrawlTransportError, match="omitted success"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_a_provider_response_that_omits_data_or_metadata_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(json.dumps({"success": True}).encode())
    )
    with pytest.raises(firecrawl.FirecrawlTransportError, match="omitted data"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)

    provider = json.dumps({"success": True, "data": {"rawBase64": "aGk="}}).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="omitted metadata"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_a_provider_response_that_omits_the_target_status_is_refused(monkeypatch) -> None:
    provider = json.dumps(
        {
            "success": True,
            "data": {"rawBase64": "aGk=", "metadata": {"contentType": "text/html", "url": PRODUCT_URL}},
        }
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="statusCode"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


@pytest.mark.parametrize(
    ("metadata_url", "message"),
    [({}, "omitted the resolved target URL"), ({"url": None}, "invalid target URL")],
)
def test_a_provider_response_without_a_resolved_url_is_refused_never_defaulted(
    monkeypatch, metadata_url: dict, message: str
) -> None:
    # Defaulting to the requested URL would make every caller's
    # final-URL-equals-locator gate agree with a value this client supplied.
    provider = json.dumps(
        {
            "success": True,
            "data": {"rawBase64": "aGk=", "metadata": {"statusCode": 200, "contentType": "text/html", **metadata_url}},
        }
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match=message):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_a_redirect_the_provider_states_is_reported_for_the_callers_gate(monkeypatch) -> None:
    redirected = "https://www.gao.gov/products/gao-26-107693/landing"
    monkeypatch.setattr(
        firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(_ok_provider(b"page", url=redirected))
    )
    response = firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
    assert response.requested_url == PRODUCT_URL
    assert response.resolved_url == redirected


def test_a_provider_response_that_repeats_a_field_is_refused(monkeypatch) -> None:
    provider = b'{"success": true, "success": false, "data": {}}'
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="repeats field 'success'"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_a_provider_response_that_omits_the_mode_field_is_refused(monkeypatch) -> None:
    provider = json.dumps(
        {"success": True, "data": {"metadata": {"statusCode": 200, "contentType": "text/html", "url": PRODUCT_URL}}}
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="rawBase64"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)


def test_invalid_base64_target_bytes_are_refused(monkeypatch) -> None:
    provider = json.dumps(
        {
            "success": True,
            "data": {
                "rawBase64": "!!! not base64 !!!",
                "metadata": {"statusCode": 200, "contentType": "text/html", "url": PRODUCT_URL},
            },
        }
    ).encode()
    monkeypatch.setattr(firecrawl.urllib.request, "urlopen", lambda *_a, **_k: _Response(provider))
    with pytest.raises(firecrawl.FirecrawlTransportError, match="invalid base64"):
        firecrawl.FirecrawlFetcher(key="test-key").fetch(PRODUCT_URL, timeout_seconds=9, max_bytes=1024)
