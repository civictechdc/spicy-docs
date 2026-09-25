"""The walled fetch ladder: rung order, wall escalation, absence short-circuit, and scrubbed exhaustion.

All tests are offline: rung functions and the shared capture client are scripted, and credentials
are removed from the environment wherever a real rung would otherwise reach for one."""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.sources import walled_fetch
from spicy_docs.sources.walled_fetch import (
    DEFAULT_USER_AGENT,
    RungOutcome,
    Transport,
    WalledFetchError,
    WalledFetchResult,
    detect_spa_shell,
    detect_wall,
)
from spicy_docs.sources.walled_fetch import (
    walled_fetch as ladder,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError

URL = "https://www.fcc.gov/ecfs/document/26110074740/1"


def _result(transport: Transport, *, status: int = 200, body: bytes = b"<html>clean</html>") -> WalledFetchResult:
    return WalledFetchResult(
        body=body,
        status_code=status,
        content_type="text/html",
        final_url=URL,
        transport=transport,
        wall=None,
        request_id=None,
    )


class _ScriptedCaptureClient:
    """One scripted capture client per construction; records how the rung built it."""

    instances: ClassVar[list] = []
    scripted: ClassVar = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        _ScriptedCaptureClient.instances.append(self)

    def capture(self, url, *, max_bytes, allow_unavailable):
        assert _ScriptedCaptureClient.scripted is not None
        return _ScriptedCaptureClient.scripted(url, max_bytes)

    def close(self) -> None:
        pass


#: The real resolution, kept before the autouse fixture replaces it.
REAL_PROVIDERS = walled_fetch.ProxyFetchers.from_environment


@pytest.fixture(autouse=True)
def _no_live_credentials(monkeypatch) -> None:
    """No real credential is read, and a call without resolved providers gets stand-ins for the scripted rungs."""
    monkeypatch.delenv("ZYTE_TOKEN", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    resolved = walled_fetch.ProxyFetchers(zyte=object(), firecrawl=object())
    monkeypatch.setattr(walled_fetch.ProxyFetchers, "from_environment", classmethod(lambda _cls: resolved))


@pytest.fixture()
def scripted_capture(monkeypatch):
    _ScriptedCaptureClient.instances = []
    monkeypatch.setattr("spicy_docs.transport.capture.BoundedHttpCapture", _ScriptedCaptureClient)
    yield _ScriptedCaptureClient
    _ScriptedCaptureClient.scripted = None


def test_a_clean_direct_answer_returns_without_touching_the_proxies(monkeypatch, scripted_capture) -> None:
    capture = CapturedBodyResponse(
        requested_url=URL,
        resolved_url=URL,
        status_code=200,
        content_type="text/html",
        observed_at="2026-09-24T00:00:00Z",
        body=b"<html>real page</html>",
    )
    _ScriptedCaptureClient.scripted = lambda _url, _max_bytes: capture
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("zyte rung must not run"))
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("firecrawl rung must not run"))

    result = ladder(URL, max_bytes=1024, timeout_seconds=9)

    assert result.transport is Transport.DIRECT
    assert result.body == b"<html>real page</html>"
    assert result.status_code == 200
    assert result.final_url == URL
    assert result.wall is None


def test_a_direct_wall_escalates_to_zyte_and_then_firecrawl(monkeypatch) -> None:
    calls: list[str] = []

    def fake_direct(url, *, max_bytes, timeout_seconds, user_agent, publisher_page=None, direct=None):
        calls.append("direct")
        return RungOutcome(Transport.DIRECT, "wall", detail="the direct answer is a wall page ('Access Denied')")

    def fake_zyte(url, *, max_bytes, timeout_seconds, mode, publisher_page=None, fetcher=None):
        calls.append("zyte")
        return RungOutcome(Transport.ZYTE_HTTP, "transport-error", detail="Zyte acquisition failed")

    def fake_firecrawl(url, *, max_bytes, timeout_seconds, publisher_page=None, fetcher=None):
        calls.append("firecrawl")
        return _result(Transport.FIRECRAWL_RAW)

    monkeypatch.setattr(walled_fetch, "_direct_rung", fake_direct)
    monkeypatch.setattr(walled_fetch, "_zyte_rung", fake_zyte)
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", fake_firecrawl)

    result = ladder(URL, max_bytes=1024, timeout_seconds=9)

    assert calls == ["direct", "zyte", "firecrawl"]
    assert result.transport is Transport.FIRECRAWL_RAW


def test_a_publisher_404_short_circuits_the_ladder(monkeypatch) -> None:
    def fake_direct(url, *, max_bytes, timeout_seconds, user_agent, publisher_page=None, direct=None):
        return RungOutcome(Transport.DIRECT, "wall", detail="wall")

    def fake_zyte(url, *, max_bytes, timeout_seconds, mode, publisher_page=None, fetcher=None):
        return _result(Transport.ZYTE_HTTP, status=404, body=b"<html>not found</html>")

    monkeypatch.setattr(walled_fetch, "_direct_rung", fake_direct)
    monkeypatch.setattr(walled_fetch, "_zyte_rung", fake_zyte)
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("must not run"))

    result = ladder(URL, max_bytes=1024, timeout_seconds=9)

    assert result.transport is Transport.ZYTE_HTTP
    assert result.status_code == 404
    assert result.body == b"<html>not found</html>"


def test_a_clean_answer_at_the_request_limit_succeeds(monkeypatch):
    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: _result(Transport.DIRECT))
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("request cap exceeded"))
    assert ladder(URL, max_bytes=1024, timeout_seconds=9, max_requests=1).transport is Transport.DIRECT


@pytest.mark.parametrize("cap", [0, -1, True, 1.5])
def test_invalid_request_caps_spend_no_requests(monkeypatch, cap):
    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: pytest.fail("invalid budget requested"))
    with pytest.raises(WalledFetchError, match="max_requests"):
        ladder(URL, max_bytes=1024, timeout_seconds=9, max_requests=cap)


def test_all_rungs_exhausted_raises_an_error_naming_each_rung_outcome(monkeypatch) -> None:
    monkeypatch.setattr(
        walled_fetch,
        "_direct_rung",
        lambda *_a, **_k: RungOutcome(Transport.DIRECT, "transport-error", detail="connection reset"),
    )
    monkeypatch.setattr(
        walled_fetch,
        "_zyte_rung",
        lambda *_a, **_k: RungOutcome(Transport.ZYTE_HTTP, "credential-error", detail="ZYTE_TOKEN is required"),
    )
    monkeypatch.setattr(
        walled_fetch,
        "_firecrawl_rung",
        lambda *_a, **_k: RungOutcome(Transport.FIRECRAWL_RAW, "wall", detail="the answer is a wall page"),
    )

    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9)

    message = str(raised.value)
    assert "walled_fetch exhausted every rung" in message
    for part in ("direct: transport-error", "zyte_http: credential-error", "firecrawl_raw: wall"):
        assert part in message
    assert [outcome.transport for outcome in raised.value.rung_outcomes] == [
        Transport.DIRECT,
        Transport.ZYTE_HTTP,
        Transport.FIRECRAWL_RAW,
    ]
    context = getattr(raised.value, "refused_response", None)
    assert isinstance(context, RefusedResponse)
    assert context.unavailable_reason == "rungs-exhausted"
    # The ladder's own dead end is staged as such, not as a per-rung transport
    # refusal (which is what stage "transport" names elsewhere).
    assert context.stage == "rungs-exhausted"


def test_all_401_403_rungs_name_the_publisher_refusal_distinctly(monkeypatch) -> None:
    monkeypatch.setattr(
        walled_fetch, "_direct_rung", lambda *_a, **_k: RungOutcome(Transport.DIRECT, "publisher-refused")
    )
    monkeypatch.setattr(
        walled_fetch,
        "_zyte_rung",
        lambda *_a, **_k: RungOutcome(Transport.ZYTE_HTTP, "publisher-refused"),
    )
    monkeypatch.setattr(
        walled_fetch,
        "_firecrawl_rung",
        lambda *_a, **_k: RungOutcome(Transport.FIRECRAWL_RAW, "publisher-refused"),
    )

    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9)

    assert "publisher refused" in str(raised.value)
    assert all(outcome.kind == "publisher-refused" for outcome in raised.value.rung_outcomes)
    context = getattr(raised.value, "refused_response", None)
    assert context.unavailable_reason == "publisher-refused"
    assert context.stage == "publisher-refused"


def test_a_missing_key_is_a_credential_error_that_is_neither_charged_nor_paced(monkeypatch) -> None:
    """Keys resolve once; a provider without one takes its rung's place with no request, charge or wait."""
    events = []
    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: RungOutcome(Transport.DIRECT, "wall"))
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("Zyte has no key"))
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("Firecrawl has no key"))

    with pytest.raises(WalledFetchError) as raised:
        ladder(
            URL, max_bytes=1024, timeout_seconds=9, proxies=REAL_PROVIDERS(), before_request=lambda: events.append(1)
        )

    outcomes = raised.value.rung_outcomes
    assert [(outcome.transport, outcome.kind) for outcome in outcomes] == [
        (Transport.DIRECT, "wall"),
        (Transport.ZYTE_HTTP, "credential-error"),
        (Transport.FIRECRAWL_RAW, "credential-error"),
    ]
    assert "ZYTE_TOKEN is required for live acquisition" in outcomes[1].detail
    assert events == [1], "only the direct rung made a request"


def test_the_browser_rung_is_only_attempted_when_allow_browser_is_set(monkeypatch) -> None:
    attempts: list[tuple[str, str]] = []

    def fake_direct(url, *, max_bytes, timeout_seconds, user_agent, publisher_page=None, direct=None):
        return RungOutcome(Transport.DIRECT, "wall", detail="wall")

    def fake_zyte(url, *, max_bytes, timeout_seconds, mode, publisher_page=None, fetcher=None):
        attempts.append(("zyte", mode))
        return RungOutcome(Transport.ZYTE_HTTP if mode == "httpResponseBody" else Transport.ZYTE_BROWSER, "wall")

    def fake_firecrawl(url, *, max_bytes, timeout_seconds, publisher_page=None, fetcher=None):
        return RungOutcome(Transport.FIRECRAWL_RAW, "wall")

    monkeypatch.setattr(walled_fetch, "_direct_rung", fake_direct)
    monkeypatch.setattr(walled_fetch, "_zyte_rung", fake_zyte)
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", fake_firecrawl)

    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9, allow_browser=False)
    assert attempts == [("zyte", "httpResponseBody")]
    assert [o.transport for o in raised.value.rung_outcomes] == [
        Transport.DIRECT,
        Transport.ZYTE_HTTP,
        Transport.FIRECRAWL_RAW,
    ]

    attempts.clear()
    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9, allow_browser=True)
    assert attempts == [("zyte", "httpResponseBody"), ("zyte", "browserHtml")]
    assert [o.transport for o in raised.value.rung_outcomes] == [
        Transport.DIRECT,
        Transport.ZYTE_HTTP,
        Transport.FIRECRAWL_RAW,
        Transport.ZYTE_BROWSER,
    ]


@pytest.mark.parametrize(
    ("body", "marker"),
    [
        (b"<title>Access Denied</title>", "Access Denied"),
        (b"errors.edgesuite.net said no", "errors.edgesuite.net"),
        (b"Server: AkamaiGHost", "AkamaiGHost"),
        (b"<title>Attention Required! | Cloudflare</title>", "Attention Required! | Cloudflare"),
        (b"Just a moment...", "Just a moment"),
        (b"Cloudflare Ray ID: 1234", "Cloudflare Ray ID"),
        (b"cf-ray: 1234", "cf-ray"),
        (b"You are unable to access", "You are unable to access"),
        (b"please solve the captcha", "captcha"),
        (b"<results><investigations>", None),
        (b"%PDF-1.4", None),
        # Measured 2026-09-24: the real FCC ECFS React shell carries Akamai Bot
        # Manager's script tag while being the publisher's page, so that
        # string alone is never a wall.
        (b"<!doctype html><div id=root><script>bazadebezolkohpepadr.js</script>", None),
    ],
)
def test_detect_wall_names_each_vocabulary_marker(body: bytes, marker: str | None) -> None:
    assert detect_wall(body) == marker


def test_detect_wall_prefers_the_seed_marker_when_two_match() -> None:
    body = b"<HTML><TITLE>Access Denied</TITLE>You don't have permission to access"
    assert detect_wall(body) == "You don't have permission to access"


@pytest.mark.parametrize(
    ("body", "refusal", "marker", "family"),
    [
        (b"<title>Attention Required! | Cloudflare</title>", False, "Attention Required! | Cloudflare", "cloudflare"),
        (b"errors.edgesuite.net said no", False, "errors.edgesuite.net", "akamai"),
        (b"<title>Access Denied</title>", False, None, None),
        (b"<title>Access Denied</title>", True, "Access Denied", "akamai"),
        (b"Just a moment...", True, "Just a moment", "cloudflare"),
        (b"please solve the captcha", True, "captcha", "generic"),
        (b"%PDF-1.4 Access Denied Cloudflare Ray ID", True, None, None),
        (b" " * (64 * 1024) + b"Cloudflare Ray ID", True, None, None),
    ],
)
def test_detect_wall_reads_generic_words_only_on_a_refusal_and_names_the_family(body, refusal, marker, family):
    """Block-page chrome walls any answer; generic words, a PDF and bytes past the scanned head never wall a 2xx."""
    wall = detect_wall(body, refusal=refusal)
    assert wall == marker
    assert (wall.family if wall is not None else None) == family
    if wall is not None:
        assert repr(wall) == repr(marker), "a quoted marker reads exactly as its text"


def test_a_page_the_caller_vouches_for_returns_before_the_wall_check(monkeypatch, scripted_capture) -> None:
    """The publisher's own page quoting block-page chrome is its answer, not a wall, when the caller recognises it."""
    body = b"<div id=portal>A comment quoting 'Attention Required! | Cloudflare' and 'Cloudflare Ray ID'</div>"
    _ScriptedCaptureClient.scripted = lambda _url, _max_bytes: CapturedBodyResponse(
        requested_url=URL,
        resolved_url=URL,
        status_code=200,
        content_type="text/html",
        observed_at="2026-09-25T00:00:00Z",
        body=body,
    )
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("vouched page escalated"))
    vouched = ladder(URL, max_bytes=1024, timeout_seconds=9, publisher_page=lambda page: b"<div id=portal>" in page)
    assert vouched.transport is Transport.DIRECT and vouched.body == body
    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9, max_requests=1)
    assert raised.value.rung_outcomes[0].kind == "wall"


def test_resolved_proxies_skip_a_provider_without_a_credential_uncharged(monkeypatch) -> None:
    """An acquirer's resolved providers: a missing key takes its rung's place without a request, charge or wait."""
    events = []
    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: RungOutcome(Transport.DIRECT, "wall"))
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("Zyte has no credential"))

    def firecrawl(*_args, fetcher, **_kwargs):
        events.append(("firecrawl", fetcher))
        return _result(Transport.FIRECRAWL_RAW)

    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", firecrawl)
    client = object()  # stands in for a resolved FirecrawlFetcher
    proxies = walled_fetch.ProxyFetchers(zyte="ZYTE_TOKEN is required for live acquisition", firecrawl=client)
    result = ladder(
        URL, max_bytes=1024, timeout_seconds=9, proxies=proxies, before_request=lambda: events.append("charge")
    )
    assert result.transport is Transport.FIRECRAWL_RAW
    assert events == ["charge", "charge", ("firecrawl", client)]
    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9, proxies=proxies, max_requests=2)
    assert [(o.transport, o.kind) for o in raised.value.rung_outcomes] == [
        (Transport.DIRECT, "wall"),
        (Transport.ZYTE_HTTP, "credential-error"),
    ]


def test_the_callers_direct_client_charges_its_own_attempt(monkeypatch) -> None:
    """``direct`` runs the DIRECT rung on the caller's client, so ``before_request`` charges only the proxy rungs."""
    events = []

    def direct(url, max_bytes):
        events.append(("direct", url, max_bytes))
        raise ConnectionError("dropped")

    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: _result(Transport.ZYTE_HTTP))
    result = ladder(URL, max_bytes=77, timeout_seconds=9, direct=direct, before_request=lambda: events.append("charge"))
    assert result.transport is Transport.ZYTE_HTTP
    assert events == [("direct", URL, 77), "charge"]


def test_rung_outcome_details_are_scrubbed_when_built() -> None:
    outcome = RungOutcome(
        Transport.ZYTE_HTTP, "transport-error", detail="GET https://x.example/?api_key=SECRETVALUE123"
    )
    assert "SECRETVALUE123" not in outcome.detail and "api_key=<redacted>" in outcome.detail


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'<div id="root"></div>', True),
        (b'<!doctype html><html><body><div id="root"></div></body></html>', True),
        (b"You need to enable JavaScript to run this app.", True),
        (b'<div id="root"></div>You don\'t have permission to access', False),
        (b'<div id="root"></div>Just a moment...', False),
        (b"%PDF-1.4", False),
        (b"<html>plain page</html>", False),
        (b"", False),
    ],
)
def test_detect_spa_shell_names_the_viewer_shell_and_never_a_wall(body: bytes, expected: bool) -> None:
    assert detect_spa_shell(body) is expected


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b"<html>clean</html>", "result"),
        # A publisher's own 2xx page can quote the generic words; only block-page chrome walls it.
        (200, b"Access Denied", "result"),
        (200, b"<p>Comment: the captcha on the form failed. Just a moment ago I tried again.</p>", "result"),
        (200, b"<title>Attention Required! | Cloudflare</title>", "wall"),
        (200, b"Cloudflare Ray ID: 1234", "wall"),
        (403, b"Access Denied", "wall"),
        (429, b"please solve the captcha", "wall"),
        (404, b"<html>not found</html>", "result"),
        (404, b"errors.edgesuite.net", "wall"),
        (410, b"gone", "result"),
        (403, b"plain refusal page", "publisher-refused"),
        (403, b"Attention Required! | Cloudflare", "wall"),
        (301, b"moved", "transport-error"),
        (500, b"boom", "transport-error"),
    ],
)
def test_classify_answer_semantics(status: int, body: bytes, expected: str) -> None:
    answer = walled_fetch._classify_answer(Transport.ZYTE_HTTP, URL, status, "text/html", body, "req-1")
    if expected == "result":
        assert isinstance(answer, WalledFetchResult)
        assert answer.status_code == status
    elif expected == "wall":
        assert isinstance(answer, RungOutcome)
        assert answer.kind == "wall"
        assert answer.body == body
    elif expected == "publisher-refused":
        assert isinstance(answer, RungOutcome)
        assert answer.kind == "publisher-refused"
    else:
        assert isinstance(answer, RungOutcome)
        assert answer.kind == "transport-error"


def test_a_429_is_treated_as_a_wall_but_its_body_is_not_wall_evidence() -> None:
    answer = walled_fetch._classify_answer(Transport.ZYTE_HTTP, URL, 429, "text/html", b"slow down", "req-1")
    assert isinstance(answer, RungOutcome)
    assert answer.kind == "wall"
    assert "429" in answer.detail
    # A rate-limit page is not a block page, so it is not retained as the
    # wall evidence the exhausted error attaches.
    assert answer.body is None


def _rate_limited(headers: dict[str, str] | None = None):
    """A scripted capture that raises the direct client's 429, with the headers the publisher sent."""
    request = httpx.Request("GET", URL)

    def raise_429(_url, _max_bytes):
        raise RetryableHTTPStatusError(
            "Body source answered retryable HTTP 429",
            request=request,
            response=httpx.Response(429, headers=headers, request=request),
        )

    return raise_429


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        (None, None),
        ("", None),
        ("0", None),
        ("-3", None),
        (" 5 ", 5.0),
        ("120", 10.0),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("3.5", None),
    ],
)
def test_retry_after_reads_only_integer_delay_seconds_capped_at_ten(retry_after: str | None, expected: float | None):
    assert walled_fetch._retry_after_seconds(retry_after) == expected


def test_the_direct_rung_honors_a_429_retry_after_before_its_outcome_counts(monkeypatch, scripted_capture) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(walled_fetch.time, "sleep", sleeps.append)
    attempts: list[object] = []

    def counted(_url, _max_bytes):
        attempts.append(None)
        raise RetryableHTTPStatusError(
            "Body source answered retryable HTTP 429",
            request=httpx.Request("GET", URL),
            response=httpx.Response(429, headers={"Retry-After": "7"}, request=httpx.Request("GET", URL)),
        )

    _ScriptedCaptureClient.scripted = counted
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert isinstance(outcome, RungOutcome)
    assert outcome.kind == "wall"
    assert sleeps == [7.0]
    assert "honored Retry-After (7s)" in outcome.detail
    assert len(attempts) == 1, "honoring the header must never become a retry"


def test_a_429_retry_after_above_the_cap_waits_the_cap_not_the_header(monkeypatch, scripted_capture) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(walled_fetch.time, "sleep", sleeps.append)
    _ScriptedCaptureClient.scripted = _rate_limited({"Retry-After": "120"})
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert outcome.kind == "wall"
    assert sleeps == [10.0]


def test_a_429_without_an_honorable_retry_after_escalates_without_waiting(monkeypatch, scripted_capture) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(walled_fetch.time, "sleep", sleeps.append)
    _ScriptedCaptureClient.scripted = _rate_limited({})
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert outcome.kind == "wall"
    assert outcome.detail == "the publisher answered HTTP 429"
    assert sleeps == []


def test_the_ladder_escalates_a_429_paced_by_its_retry_after_without_a_retry(monkeypatch, scripted_capture) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(walled_fetch.time, "sleep", sleeps.append)
    _ScriptedCaptureClient.scripted = _rate_limited({"Retry-After": "2"})

    def fake_zyte(url, *, max_bytes, timeout_seconds, mode, publisher_page=None, fetcher=None):
        return _result(Transport.ZYTE_HTTP)

    monkeypatch.setattr(walled_fetch, "_zyte_rung", fake_zyte)
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("must not run"))

    result = ladder(URL, max_bytes=1024, timeout_seconds=9)

    assert result.transport is Transport.ZYTE_HTTP
    assert sleeps == [2.0], "the escalation leaves the publisher's stated backoff window alone"


def test_the_direct_rung_refuses_a_redirect_as_a_transport_error(scripted_capture) -> None:
    def redirected(_url, _max_bytes):
        raise WalledFetchError("Body source response final URL differs from its request")

    _ScriptedCaptureClient.scripted = redirected
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert isinstance(outcome, RungOutcome)
    assert outcome.kind == "transport-error"
    assert "final URL differs" in outcome.detail


def test_the_direct_rung_reads_a_wall_from_a_refused_body(scripted_capture) -> None:
    def refused(_url, _max_bytes):
        error = CredentialRefusedError("Body source answered HTTP 403; stopping acquisition")
        attach_refused_response(
            error,
            RefusedResponse(URL, "transport", b"<title>Access Denied</title>", "text/html", "access-refused"),
        )
        raise error

    _ScriptedCaptureClient.scripted = refused
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert isinstance(outcome, RungOutcome)
    assert outcome.kind == "wall"
    assert outcome.body == b"<title>Access Denied</title>"


def test_the_direct_rung_records_a_plain_refusal_as_publisher_refused(scripted_capture) -> None:
    def refused(_url, _max_bytes):
        error = CredentialRefusedError("Body source answered HTTP 401; stopping acquisition")
        attach_refused_response(
            error, RefusedResponse(URL, "transport", b"<html>forbidden</html>", "text/html", "access-refused")
        )
        raise error

    _ScriptedCaptureClient.scripted = refused
    outcome = walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert isinstance(outcome, RungOutcome)
    assert outcome.kind == "publisher-refused"


def test_the_direct_rung_uses_the_caller_user_agent_and_a_default_otherwise(scripted_capture) -> None:
    def refused(_url, _max_bytes):
        raise WalledFetchError("Body source answered HTTP 500")

    _ScriptedCaptureClient.scripted = refused
    walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent="UA-X")
    walled_fetch._direct_rung(URL, max_bytes=1024, timeout_seconds=9, user_agent=None)
    assert [instance.kwargs["user_agent"] for instance in _ScriptedCaptureClient.instances] == [
        "UA-X",
        DEFAULT_USER_AGENT,
    ]


def test_the_exhausted_error_scrubs_credential_shaped_details_and_retains_the_wall_body(monkeypatch) -> None:
    wall_body = b"<html>Access Denied</html>"
    monkeypatch.setattr(
        walled_fetch,
        "_direct_rung",
        lambda *_a, **_k: RungOutcome(Transport.DIRECT, "wall", detail="wall page", body=wall_body),
    )
    monkeypatch.setattr(
        walled_fetch,
        "_zyte_rung",
        lambda *_a, **_k: RungOutcome(
            Transport.ZYTE_HTTP, "transport-error", detail="request to api_key=SECRETVALUE123 failed"
        ),
    )
    monkeypatch.setattr(
        walled_fetch,
        "_firecrawl_rung",
        lambda *_a, **_k: RungOutcome(Transport.FIRECRAWL_RAW, "transport-error", detail="broken"),
    )

    with pytest.raises(WalledFetchError) as raised:
        ladder(URL, max_bytes=1024, timeout_seconds=9)

    message = str(raised.value)
    assert "SECRETVALUE123" not in message
    assert "api_key=<redacted>" in message
    context = getattr(raised.value, "refused_response", None)
    assert context.unavailable_reason == "wall-exhausted"
    assert context.stage == "wall-exhausted"
    assert context.response_bytes == wall_body
    assert context.observed_byte_size == len(wall_body)


@pytest.mark.parametrize(
    ("url", "max_bytes", "timeout", "user_agent", "allow_browser"),
    [
        ("ftp://example.com/file", 1024, 9, None, False),
        ("https://user:pass@example.com/", 1024, 9, None, False),
        (URL, 0, 9, None, False),
        (URL, True, 9, None, False),
        (URL, 1024, 0, None, False),
        (URL, 1024, 9, "   ", False),
        (URL, 1024, 9, None, "yes"),
    ],
)
def test_invalid_inputs_are_refused_before_any_rung(
    monkeypatch, url: str, max_bytes, timeout: float, user_agent: str | None, allow_browser
) -> None:
    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: pytest.fail("no rung must run"))
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("no rung must run"))
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("no rung must run"))
    with pytest.raises(WalledFetchError):
        ladder(url, max_bytes=max_bytes, timeout_seconds=timeout, user_agent=user_agent, allow_browser=allow_browser)


def test_before_request_budget_refusal_stops_before_the_next_rung(monkeypatch):
    attempts = []

    def before_request():
        if attempts:
            raise ValueError("shared request budget exhausted")
        attempts.append("charged")

    monkeypatch.setattr(walled_fetch, "_direct_rung", lambda *_a, **_k: RungOutcome(Transport.DIRECT, "wall"))
    monkeypatch.setattr(walled_fetch, "_zyte_rung", lambda *_a, **_k: pytest.fail("refused attempt reached Zyte"))
    monkeypatch.setattr(walled_fetch, "_firecrawl_rung", lambda *_a, **_k: pytest.fail("budget refusal was swallowed"))
    with pytest.raises(ValueError, match="shared request budget exhausted"):
        ladder(URL, max_bytes=1024, timeout_seconds=9, before_request=before_request)
    assert attempts == ["charged"]
