"""One public-site fallback shared by metadata capture and original downloads.

Pins the fallback trigger (a direct 403 on a public selection with no source
headers), exact response and blob recording, reuse of verified bytes, bounded
proxy chunks, and refusal to fall back for other failures, redirects, ETag
conditions or bound violations.
"""

from dataclasses import replace
from urllib.parse import urlsplit

import httpx
import pytest
from rulespec_artifacts import BlobIntegrityError

from spicy_docs.sources.zyte import ZyteHttpResponse
from spicy_docs.transport.download import AcquisitionError, BoundedAcquirer, HttpRefusal

URL = "https://www.foia.gov/report.xml"
BODY = b"<?xml version='1.0'?><report>Original</report>"


def source_url(url):
    """The selected public source URL for a route."""
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname not in {"www.foia.gov", "www.oversight.gov"}
        or p.query
        or p.fragment
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise ValueError("outside selected source")
    return url


class Proxy:
    """A proxy stub recording calls and returning queued bodies."""

    def __init__(self, **changes):
        self.calls = []
        self.response = replace(ZyteHttpResponse(URL, URL, 200, "application/xml", BODY), **changes)

    def fetch(self, url, **options):
        self.calls.append((url, options))
        return self.response


def client(proxy, *, handler=None, **options):
    """A public-fallback client over the proxy and a mock transport."""
    options.setdefault("public_fallback_url", lambda url: urlsplit(url).hostname == "www.foia.gov")
    return BoundedAcquirer(
        validate_url=source_url,
        zyte_on_denial=proxy,
        min_interval=0,
        transport=httpx.MockTransport(handler or (lambda _: httpx.Response(403))),
        **options,
    )


@pytest.mark.parametrize("operation", ["capture", "download"])
def test_public_source_reuses_one_fallback_and_records_exact_response(tmp_path, operation):
    """A 403 on a public source falls back once, records exact response metadata and blob, and verified bytes reuse
    storage without either route.
    """
    proxy = Proxy(resolved_url=URL + "/resolved")
    with client(proxy, timeout=7) as c:
        if operation == "capture":
            result = c.capture(URL, max_bytes=1024)
            assert result.body == BODY
            assert result.url == URL
            assert result.via == "zyte_after_http_403"
            assert result.resolved_url == URL + "/resolved"
        else:
            seen = []
            result = c.download(
                URL, store=tmp_path, max_bytes=1024, expected_size=len(BODY), validate_prefix=seen.append
            )
            assert (tmp_path / result["blob_path"]).read_bytes() == BODY
            assert result["url"] == URL and result["downloaded"]
            assert result["response"]["via"] == "zyte_after_http_403"
            assert result["response"]["resolved_url"] == URL + "/resolved"
            assert seen == [BODY]
            # Verified known bytes reuse storage without either network route.
            reused = c.download(
                URL, store=tmp_path, max_bytes=1024, expected_sha256=result["sha256"], expected_size=len(BODY)
            )
            assert reused["reused"] and not reused["downloaded"]
        assert c.request_count == 2
    assert proxy.calls == [(URL, {"timeout_seconds": 7, "max_bytes": 1024})]


def test_direct_success_keeps_streaming_and_never_calls_proxy(tmp_path):
    """A direct success streams and never calls the proxy."""
    proxy = Proxy()
    with client(
        proxy, handler=lambda _: httpx.Response(200, content=BODY, headers={"content-type": "application/xml"})
    ) as c:
        result = c.download(URL, store=tmp_path, max_bytes=1024)
        assert (tmp_path / result["blob_path"]).read_bytes() == BODY
        assert result["response"]["via"] == "direct"
        assert c.request_count == 1
    assert proxy.calls == []


@pytest.mark.parametrize(
    "options",
    [
        {"public_fallback_url": None},
        {"headers": lambda _: {"X-Api-Key": "private-test-credential"}},
    ],
)
def test_fallback_requires_explicit_public_selection_and_no_source_headers(options):
    """Fallback requires an explicit public selection and no source headers."""
    proxy = Proxy()
    with client(proxy, **options) as c, pytest.raises(HttpRefusal):
        c.capture(URL, max_bytes=1024)
    assert proxy.calls == []


@pytest.mark.parametrize("status", [401, 404])
def test_other_direct_failures_never_use_proxy(status):
    """Other direct failures never use the proxy."""
    proxy = Proxy()
    with client(proxy, handler=lambda _: httpx.Response(status)) as c, pytest.raises((HttpRefusal, AcquisitionError)):
        c.capture(URL, max_bytes=1024)
    assert proxy.calls == []


def test_direct_redirect_to_nonpublic_source_cannot_trigger_fallback():
    """A direct redirect to a non-public source cannot trigger fallback."""
    proxy = Proxy()

    def handler(request):
        return (
            httpx.Response(302, headers={"Location": "https://www.oversight.gov/private"})
            if str(request.url) == URL
            else httpx.Response(403)
        )

    with client(proxy, handler=handler) as c, pytest.raises(HttpRefusal):
        c.capture(URL, max_bytes=1024)
    assert proxy.calls == []


@pytest.mark.parametrize("private_headers", [False, True])
def test_every_direct_hop_must_be_public_and_header_free(private_headers):
    """Every direct hop must be public and header-free."""
    proxy = Proxy()
    private = "https://www.oversight.gov/private"
    final = URL + "/final"

    def handler(request):
        url = str(request.url)
        if url in (URL, private):
            return httpx.Response(302, headers={"Location": private if url == URL else final})
        return httpx.Response(403)

    options = {
        "headers": lambda url: {"X-Api-Key": "secret-test-key"} if private_headers and url == private else {},
    }
    if private_headers:
        options["public_fallback_url"] = lambda _: True
    with client(proxy, handler=handler, **options) as c, pytest.raises(HttpRefusal):
        c.capture(URL, max_bytes=1024)
    assert proxy.calls == []


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"resolved_url": "https://outside.example/report.xml"}, "outside selected source"),
        ({"resolved_url": "https://www.oversight.gov/private"}, "selected public source"),
        ({"requested_url": URL + "/other"}, "selected public source"),
        ({"body": b"x" * 1025}, "byte bound"),
        ({"status_code": 500}, "HTTP 500"),
    ],
)
def test_proxy_must_return_selected_bounded_success(changes, message):
    """The proxy must return a selected, bounded success."""
    proxy = Proxy(**changes)
    with client(proxy) as c, pytest.raises(ValueError, match=message):
        c.capture(URL, max_bytes=1024)
    assert len(proxy.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_proxy_auth_refusal_stops_without_retry(status):
    """A proxy auth refusal stops without retry."""
    proxy = Proxy(status_code=status)
    with client(proxy) as c, pytest.raises(HttpRefusal) as error:
        c.capture(URL, max_bytes=1024)
    assert error.value.status == status
    assert len(proxy.calls) == 1


@pytest.mark.parametrize("options, message", [({"max_requests": 1}, "budget"), ({}, "32 MiB")])
def test_proxy_counts_against_request_and_buffer_bounds(options, message):
    """Proxy calls count against request and buffer bounds."""
    proxy = Proxy()
    with client(proxy, **options) as c, pytest.raises(AcquisitionError, match=message):
        c.capture(URL, max_bytes=1024 if options else 32 * 1024**2 + 1)
    assert proxy.calls == []


def test_etag_condition_cannot_fall_back(tmp_path):
    """An ETag condition cannot fall back."""
    proxy = Proxy()
    with client(proxy) as c, pytest.raises(HttpRefusal):
        c.download(URL, store=tmp_path, max_bytes=1024, etag='"original-version"')
    assert proxy.calls == []


@pytest.mark.parametrize(
    "changes, options, message",
    [
        ({"body": b""}, {}, "empty"),
        ({"body": b"<html>challenge</html>", "content_type": "text/html"}, {}, "HTML"),
        ({}, {"expected_size": len(BODY) + 1}, None),
        ({}, {"expected_sha256": "sha256:" + "0" * 64}, None),
    ],
)
def test_proxy_download_shares_original_validation_and_storage_guards(tmp_path, changes, options, message):
    """A proxy download shares the original validation and storage guards, writing nothing on refusal."""
    with client(Proxy(**changes)) as c, pytest.raises((AcquisitionError, BlobIntegrityError), match=message):
        c.download(URL, store=tmp_path, max_bytes=1024, **options)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_public_redirect_can_still_use_fallback():
    """A public redirect can still use fallback."""
    proxy = Proxy()

    def handler(request):
        return (
            httpx.Response(302, headers={"Location": URL + "/redirect"})
            if str(request.url) == URL
            else httpx.Response(403)
        )

    with client(proxy, handler=handler) as c:
        assert c.capture(URL, max_bytes=1024).body == BODY
        assert c.request_count == 3
    assert len(proxy.calls) == 1 and proxy.calls[0][0] == URL


def test_proxy_large_body_uses_bounded_chunks_without_losing_bytes(tmp_path):
    """A large proxy body is read in bounded chunks without losing bytes."""
    payload = bytes(range(256)) * 600
    proxy = Proxy(body=payload, content_type="application/octet-stream")
    seen = []
    with client(proxy) as c:
        result = c.download(URL, store=tmp_path, max_bytes=len(payload), validate_prefix=seen.append)
    assert seen == [payload[: 64 * 1024]]
    assert result["bytes"] == len(payload)
    assert (tmp_path / result["blob_path"]).read_bytes() == payload
