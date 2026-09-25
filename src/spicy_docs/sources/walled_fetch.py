"""One fetch ladder for walled publishers, with one canonical wall vocabulary.

Some public publishers refuse ordinary direct clients with an Akamai or
Cloudflare block page while answering credentialed proxies, and which rung
answers cleanly differs per route (measured live 2026-09-24: CFTC and USITC
answered Zyte and Firecrawl but 403'd a direct client; FERC answered Zyte a
Drupal 404 and Firecrawl's engines all failed). :func:`walled_fetch` walks one
bounded ladder -- DIRECT, ZYTE_HTTP, FIRECRAWL_RAW, then ZYTE_BROWSER when the
caller allows a rendered DOM -- and returns the first clean answer. Every rung
is one bounded attempt; a rung that fails or finds a wall is recorded as a
:class:`RungOutcome` and the ladder escalates, so a wall on one route is never
reported as a publisher's answer.

Reading the publisher's answer correctly:

* A wall is read from the answer's own bytes by :func:`detect_wall`. Block-page
  chrome marks a wall on any answer; the generic words a block page shares
  with ordinary prose ("Access Denied", "captcha", "Just a moment") mark one
  only on a refusal (401/403/429), because publishers' own pages quote them.
  A caller that recognises its publisher's page passes ``publisher_page``,
  and a 2xx body it vouches for returns before any wall check.
* A 404/410 whose bytes carry no wall markers is publisher absence and
  returns immediately. Requested-empty is a different thing: a clean 2xx
  returns whatever bytes it carries, including none.
* A 401/403 without wall markers is a publisher refusal, not a wall: the rung
  is recorded as refused and the ladder escalates, because a proxy may see the
  real answer. When every rung answers 401/403, the exhausted error says
  "publisher refused" distinctly.
* A wall -- 401/403 with wall markers, 429, or a 2xx whose bytes are a block
  page -- always escalates; the first wall body is retained as refusal
  evidence on the exhausted error.
* A 429 is a wall and still gets exactly one bounded attempt: the ladder
  never retries it. The direct rung does honor a ``Retry-After`` header its
  429 carries by waiting that long -- capped at
  ``_MAX_RETRY_AFTER_SECONDS`` -- before its outcome is recorded, so the
  escalation to the next rung leaves the publisher's stated backoff window
  alone. Only integer delay-seconds are honored (an HTTP-date or fractional
  value is not), and the proxy rungs cannot observe the header, so a proxy
  429 escalates at once.

The direct rung follows no redirects (the shared bounded client refuses a
final URL that differs from the locator) and runs on the caller's own client
when one is given (``direct``), otherwise on a one-attempt client built for the
call. The proxy rungs record the URL the provider resolved, and an acquirer
resolves their credentials once (``proxies``). Rung outcome details are
scrubbed when an outcome is built, and the credential holders refuse reflected
credentials themselves. The exhausted error's retained evidence names the
ladder stage, never the transport: ``wall-exhausted`` when wall bytes are
retained, ``publisher-refused`` when every rung answered 401/403 without
markers, and ``rungs-exhausted`` otherwise, so a receipt tells ladder
exhaustion apart from a per-rung transport refusal (which keeps stage
``transport``).

``detect_wall`` is the one canonical wall-marker vocabulary in this package,
and it names the family of the block page it matched; ``detect_spa_shell`` is
the one canonical SPA-shell check beside it: a body carrying
``<div id="root">`` and/or the JavaScript notice, and no wall marker. The
ladder itself never consults it -- a clean 2xx shell is still a clean 2xx --
callers such as the FCC ECFS route use it to name the shell as their own
refusal.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Final, Literal, Self

from spicy_docs.reading.pdf_bytes import PDF_MAGIC
from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.sources.firecrawl import (
    MAX_TIMEOUT_SECONDS,
    RAW_BASE64,
    FirecrawlFetcher,
    FirecrawlTransportError,
)
from spicy_docs.sources.zyte import BROWSER_HTML, HTTP_RESPONSE_BODY, ZyteHttpFetcher, ZyteTransportError
from spicy_docs.transport.credentials import scrub_credential
from spicy_docs.transport.provider_api import absolute_public_http_url
from spicy_docs.transport.source_acquirer import utc_now

if TYPE_CHECKING:
    from spicy_docs.transport.captured import CapturedBodyResponse

#: The direct rung's client when the caller names none; the walled hosts have
#: refused every agent spelling tested, so this states who asked, nothing more.
DEFAULT_USER_AGENT: Final = "SpicyDocs walled-fetch/1.0"

#: The longest Retry-After wait the direct rung honors. A 429 still gets one
#: bounded attempt and still escalates; honoring the header only paces the
#: escalation, and this cap keeps a hostile or misconfigured header from
#: stalling the ladder.
_MAX_RETRY_AFTER_SECONDS: Final = 10.0

#: Only a body's head is read for walls: the measured block pages are under 6 KiB.
_WALL_SCAN_BYTES: Final = 64 * 1024

type WallFamily = Literal["akamai", "cloudflare", "generic"]

#: Block-page chrome: strings a block page carries and a publisher's own text
#: does not, so they mark a wall on any answer. Each family names the longer,
#: more specific wording first. Seeded from the per-host captures of the proxy
#: client smoke harness (``tools/analysis/proxy_client_smoke.py``, 2026-09-24).
#: ``bazadebezolkohpepadr`` (Akamai Bot Manager's script tag) is deliberately
#: NOT a marker: measured 2026-09-24, the real 1,374-byte FCC ECFS React shell
#: carries it while being the publisher's page, not a wall (receipt
#: firecrawl-client-smoke-2026-09-24); on Akamai hosts the script is injected
#: into legitimate HTML too.
_BLOCK_PAGE_MARKERS: Final[tuple[tuple[WallFamily, tuple[bytes, ...]], ...]] = (
    ("akamai", (b"You don't have permission to access", b"errors.edgesuite.net", b"AkamaiGHost")),
    ("cloudflare", (b"Attention Required! | Cloudflare", b"Sorry, you have been blocked", b"Cloudflare Ray ID")),
)
#: Generic words a block page also carries but a publisher's own text can
#: quote, so they mark a wall only on a refusal (401/403/429). Measured
#: 2026-09-25 over the pinned 23,889,661-row regulations.gov comments Parquet
#: and 1,000 real PDFs (receipt supply-2026-09-02/receipts/
#: wall-marker-prevalence-2026-09-25/result.json): 53 comment bodies (63 rows
#: counting extracted attachment text) contain one, while no row contains a
#: block-page marker and no PDF contains either vocabulary; Arrow re-derived
#: the comment counts (crosscheck.json).
_REFUSAL_MARKERS: Final[tuple[tuple[WallFamily, tuple[bytes, ...]], ...]] = (
    ("akamai", (b"Access Denied",)),
    ("cloudflare", (b"You are unable to access", b"Attention Required", b"Just a moment", b"cf-ray")),
    ("generic", (b"captcha",)),
)

#: The one canonical SPA-viewer-shell vocabulary, moved here from the FCC
#: ECFS route (boyscout: one vocabulary beside the wall markers).
#: ``<div id="root">`` and the JavaScript notice are the telltales the
#: measured 2026-09-24 ECFS viewer shell carries; a wall-marked body is a
#: wall, never a shell, so the shell check consults the wall vocabulary first.
_SPA_SHELL_MARKERS: Final = (b'<div id="root">', b"You need to enable JavaScript")


class WallMarker(str):
    """The wall marker a body matched -- its text, the only evidence ever quoted -- and its ``family``."""

    family: WallFamily

    def __new__(cls, marker: str, family: WallFamily) -> Self:
        wall = super().__new__(cls, marker)
        wall.family = family
        return wall


def detect_wall(body: bytes, *, refusal: bool | None = None) -> WallMarker | None:
    """The wall marker this body matches, or ``None`` when it matches none.

    Substring checks on the first 64 KiB of the exact bytes, no regex; a body
    that starts ``%PDF-`` is never a wall. Block-page chrome counts on any
    answer. The generic words count only when ``refusal`` is true (the answer
    was a 401/403/429) or unstated (``None``, the whole vocabulary a caller
    that does not pass the status has always had); ``refusal=False`` is any
    other answer, such as a 2xx.
    """
    if body.startswith(PDF_MAGIC):
        return None
    head = body[:_WALL_SCAN_BYTES]
    vocabulary = _BLOCK_PAGE_MARKERS if refusal is False else _BLOCK_PAGE_MARKERS + _REFUSAL_MARKERS
    for family, markers in vocabulary:
        for marker in markers:
            if marker in head:
                return WallMarker(marker.decode("utf-8", "backslashreplace"), family)
    return None


def detect_spa_shell(body: bytes) -> bool:
    """Whether this body is a SPA viewer shell: a client-rendered app page, never a wall.

    The one canonical shell vocabulary beside :func:`detect_wall`: the body
    carries the React mount point ``<div id="root">`` and/or the JavaScript
    notice, and no wall marker. The ladder itself never consults this helper
    -- a clean 2xx shell is still a clean 2xx answer -- it exists for callers
    that must name the shell as their own refusal, and a wall page is a wall,
    never a shell.
    """
    if detect_wall(body) is not None:
        return False
    return any(marker in body for marker in _SPA_SHELL_MARKERS)


def _retry_after_seconds(value: str | None) -> float | None:
    """The integer delay-seconds a Retry-After header names, capped; ``None`` when it names none.

    RFC 9110's HTTP-date form and fractional seconds are not honored: the
    ladder is not a retry loop, and the direct rung keeps no clock arithmetic
    for a wait it caps anyway.
    """
    if value is None:
        return None
    seconds = value.strip()
    if not seconds.isascii() or not seconds.isdigit() or int(seconds) <= 0:
        return None
    return min(float(seconds), _MAX_RETRY_AFTER_SECONDS)


class Transport(str, Enum):
    """Which rung a result came from; stated on every result so a receipt cannot misattribute it."""

    DIRECT = "direct"
    ZYTE_HTTP = "zyte_http"
    ZYTE_BROWSER = "zyte_browser"
    FIRECRAWL_RAW = "firecrawl_raw"


type RungOutcomeKind = Literal["credential-error", "transport-error", "wall", "publisher-refused"]
#: The caller's own bounded client for the DIRECT rung: ``(url, max_bytes)`` to one capture attempt.
type DirectCapture = Callable[[str, int], CapturedBodyResponse]


@dataclass(frozen=True, slots=True)
class RungOutcome:
    """Why one rung did not return a clean answer; recorded, then the ladder escalates.

    ``kind`` is a closed vocabulary. ``detail`` is scrubbed here, when the
    outcome is built, so no outcome ever carries an unscrubbed detail. ``body``
    is the first wall body a rung saw, retained (bounded by the caller's
    ``max_bytes``) as refusal evidence on the exhausted error.
    """

    transport: Transport
    kind: RungOutcomeKind
    detail: str | None = None
    body: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.detail is not None:
            object.__setattr__(self, "detail", scrub_credential(self.detail))


@dataclass(frozen=True, slots=True)
class WalledFetchResult:
    """One clean answer: the exact bytes and the facts that tie them to the locator.

    ``wall`` is always ``None`` here: a wall-marked answer escalates instead
    of returning, and the exhausted error carries the wall evidence.
    """

    body: bytes
    status_code: int
    content_type: str | None
    final_url: str
    transport: Transport
    wall: str | None
    request_id: str | None


class WalledFetchError(ValueError):
    """No rung returned a clean answer; ``rung_outcomes`` names each rung's outcome."""

    def __init__(self, message: str, *, rung_outcomes: tuple[RungOutcome, ...] = ()) -> None:
        super().__init__(message)
        self.rung_outcomes = rung_outcomes


def _provider[Fetcher](from_environment: Callable[[], Fetcher], error_type: type[Exception]) -> Fetcher | str:
    """The provider's client from its environment credential, or the reason it has none."""
    try:
        return from_environment()
    except error_type as error:
        return str(error)


@dataclass(frozen=True, slots=True)
class ProxyFetchers:
    """The proxy rungs' clients, resolved once by an acquirer; a string is why that provider cannot be used."""

    zyte: ZyteHttpFetcher | str
    firecrawl: FirecrawlFetcher | str

    @classmethod
    def from_environment(cls) -> ProxyFetchers:
        return cls(
            _provider(ZyteHttpFetcher.from_environment, ZyteTransportError),
            _provider(FirecrawlFetcher.from_environment, FirecrawlTransportError),
        )


def _classify_answer(
    transport: Transport,
    resolved_url: str,
    status_code: int,
    content_type: str | None,
    body: bytes,
    request_id: str | None,
    publisher_page: Callable[[bytes], bool] | None = None,
) -> WalledFetchResult | RungOutcome:
    """Whether one rung's answer is a clean return, a wall, a refusal or an absence."""
    clean = WalledFetchResult(
        body=body,
        status_code=status_code,
        content_type=content_type,
        final_url=resolved_url,
        transport=transport,
        wall=None,
        request_id=request_id,
    )
    successful = 200 <= status_code < 300
    if successful and publisher_page is not None and publisher_page(body):
        return clean
    marker = detect_wall(body, refusal=status_code in (401, 403, 429))
    if marker is not None:
        return RungOutcome(transport, "wall", detail=f"the answer is a wall page ({marker!r})", body=body)
    if successful or status_code in (404, 410):
        return clean
    if status_code in (401, 403):
        return RungOutcome(
            transport,
            "publisher-refused",
            detail=f"the publisher answered HTTP {status_code} without wall markers",
        )
    if status_code == 429:
        return RungOutcome(transport, "wall", detail="the publisher answered HTTP 429")
    return RungOutcome(transport, "transport-error", detail=f"the target answered HTTP {status_code}")


def _direct_rung(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    user_agent: str | None,
    publisher_page: Callable[[bytes], bool] | None = None,
    direct: DirectCapture | None = None,
) -> WalledFetchResult | RungOutcome:
    """One bounded, no-redirect GET; the locator's final URL is itself.

    ``direct`` is the caller's own bounded client, which charges and paces its
    one attempt. Without it a ``BoundedHttpCapture`` (the client every
    ``SourceAcquirer`` builds on) is built for this call with
    ``max_requests=1``, so its retry loop is a single attempt; it accepts any
    content type and ``retain_refusal_bodies`` keeps a 401/403 body as
    evidence for the wall check.
    """
    from spicy_docs.transport.capture import BoundedHttpCapture
    from spicy_docs.transport.credentials import CredentialRefusedError
    from spicy_docs.transport.http import RetryableHTTPStatusError

    client = None
    if direct is None:
        client = BoundedHttpCapture(
            max_requests=1,
            timeout_seconds=timeout_seconds,
            min_request_interval_seconds=0,
            user_agent=user_agent or DEFAULT_USER_AGENT,
            error_type=WalledFetchError,
            transport=None,
            clock=utc_now,
            retain_refusal_bodies=True,
        )
    try:
        if client is not None:
            capture = client.capture(url, max_bytes=max_bytes, allow_unavailable=True)
        else:
            capture = direct(url, max_bytes)
    except CredentialRefusedError as error:
        refused = getattr(error, "refused_response", None)
        body = getattr(refused, "response_bytes", None) or b""
        marker = detect_wall(body, refusal=True)
        if marker is not None:
            return RungOutcome(
                Transport.DIRECT, "wall", detail=f"the direct answer is a wall page ({marker!r})", body=body
            )
        return RungOutcome(Transport.DIRECT, "publisher-refused")
    except RetryableHTTPStatusError as error:
        if error.response.status_code == 429:
            wait = _retry_after_seconds(error.response.headers.get("retry-after"))
            if wait is not None:
                # Still one bounded attempt: the wait paces the escalation,
                # it never retries. Honored before the outcome is recorded so
                # the next rung leaves the publisher's stated backoff alone.
                time.sleep(wait)
                return RungOutcome(
                    Transport.DIRECT,
                    "wall",
                    detail=f"the publisher answered HTTP 429; honored Retry-After ({wait:.0f}s)",
                )
            return RungOutcome(Transport.DIRECT, "wall", detail="the publisher answered HTTP 429")
        return RungOutcome(Transport.DIRECT, "transport-error", detail=str(error))
    except (ConnectionError, ValueError) as error:
        # The shared client's own refusals (byte bounds, redirects, odd
        # encodings, retryable transport failures) all land here as one
        # recorded rung outcome; a CredentialRefusedError never does.
        return RungOutcome(Transport.DIRECT, "transport-error", detail=str(error))
    finally:
        if client is not None:
            client.close()
    return _classify_answer(
        Transport.DIRECT,
        capture.resolved_url,
        capture.status_code,
        capture.content_type,
        capture.body,
        None,
        publisher_page,
    )


def _zyte_rung(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    mode: str,
    fetcher: ZyteHttpFetcher,
    publisher_page: Callable[[bytes], bool] | None = None,
) -> WalledFetchResult | RungOutcome:
    """One Zyte call with the client the ladder resolved; a provider failure is a recorded rung outcome."""
    transport = Transport.ZYTE_HTTP if mode == HTTP_RESPONSE_BODY else Transport.ZYTE_BROWSER
    try:
        response = fetcher.fetch(url, timeout_seconds=timeout_seconds, max_bytes=max_bytes, mode=mode)
    except ZyteTransportError as error:
        return RungOutcome(transport, "transport-error", detail=str(error))
    return _classify_answer(
        transport,
        response.resolved_url,
        response.status_code,
        response.content_type,
        response.body,
        response.request_id,
        publisher_page,
    )


def _firecrawl_rung(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    fetcher: FirecrawlFetcher,
    publisher_page: Callable[[bytes], bool] | None = None,
) -> WalledFetchResult | RungOutcome:
    """One Firecrawl call in rawBase64; the provider's timeout ceiling is its own, so the wait is clamped to it."""
    try:
        response = fetcher.fetch(
            url,
            timeout_seconds=min(timeout_seconds, MAX_TIMEOUT_SECONDS),
            max_bytes=max_bytes,
            mode=RAW_BASE64,
        )
    except FirecrawlTransportError as error:
        return RungOutcome(Transport.FIRECRAWL_RAW, "transport-error", detail=str(error))
    return _classify_answer(
        Transport.FIRECRAWL_RAW,
        response.resolved_url,
        response.status_code,
        response.content_type,
        response.body,
        response.request_id,
        publisher_page,
    )


def _exhausted(
    url: str, outcomes: tuple[RungOutcome, ...], wall_body: bytes | None, *, request_limit: int | None = None
) -> WalledFetchError:
    """The error that names every rung's outcome; wall evidence and refusals are attached, everything scrubbed.

    The retained evidence's stage names the ladder exhaustion -- never
    ``transport``, which per-rung refusals carry -- so a receipt tells the
    ladder's own dead end apart from any one rung's transport refusal.
    """
    parts: list[str] = []
    for outcome in outcomes:
        part = f"{outcome.transport.value}: {outcome.kind}"
        if outcome.detail:
            part += f" ({outcome.detail})"
        parts.append(part)
    exhausted = "every rung" if request_limit is None else f"request budget of {request_limit}"
    message = f"walled_fetch exhausted {exhausted} for {scrub_credential(url)}: " + "; ".join(parts)
    refused_only = bool(outcomes) and all(outcome.kind == "publisher-refused" for outcome in outcomes)
    if refused_only:
        scope = "every rung" if request_limit is None else "every attempted rung"
        message += f"; publisher refused: {scope} answered 401/403 without wall markers"
    error = WalledFetchError(message, rung_outcomes=outcomes)
    if wall_body is not None:
        attach_refused_response(
            error,
            RefusedResponse(
                url,
                "wall-exhausted",
                wall_body,
                "application/octet-stream",
                "wall-exhausted",
                len(wall_body),
            ),
        )
    elif refused_only:
        attach_refused_response(
            error, RefusedResponse(url, "publisher-refused", None, "application/octet-stream", "publisher-refused")
        )
    else:
        attach_refused_response(
            error, RefusedResponse(url, "rungs-exhausted", None, "application/octet-stream", "rungs-exhausted")
        )
    return error


def walled_fetch(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    user_agent: str | None = None,
    allow_browser: bool = False,
    max_requests: int | None = None,
    before_request: Callable[[], None] | None = None,
    publisher_page: Callable[[bytes], bool] | None = None,
    direct: DirectCapture | None = None,
    proxies: ProxyFetchers | None = None,
) -> WalledFetchResult:
    """One bounded ladder over DIRECT, ZYTE_HTTP, FIRECRAWL_RAW and (optionally) ZYTE_BROWSER.

    Returns the first clean answer; a clean 404/410 is publisher absence and
    returns just the same. Escalates on walls, refusals, missing credentials
    and transport failures; when every rung fails, raises
    :class:`WalledFetchError` naming each rung's outcome. ``max_requests``
    optionally caps the attempted rungs; exhaustion stops before the next
    rung and retains the outcomes and wall evidence already received.

    ``before_request`` runs before each attempted rung and can charge a shared
    budget and pace requests; its exceptions propagate immediately without
    trying another rung. ``publisher_page`` vouches for the caller's own 2xx
    bodies, which then return before any wall check. ``direct`` is the
    caller's own client for the DIRECT rung; it charges and paces its attempt
    itself, so ``before_request`` does not run before it. ``proxies`` are the
    provider clients an acquirer resolved once (read from the environment for
    this call when omitted); a provider without a credential takes its rung's
    place as a ``credential-error`` without a request, a charge or a pacing wait.
    """
    absolute_public_http_url(url, label="target URL", error_type=WalledFetchError)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise WalledFetchError("max_bytes must be a positive integer")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise WalledFetchError("timeout_seconds must be a number")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise WalledFetchError("timeout_seconds must be finite and positive")
    if user_agent is not None and (not isinstance(user_agent, str) or not user_agent.strip()):
        raise WalledFetchError("user_agent must be a nonempty string when given")
    if not isinstance(allow_browser, bool):
        raise WalledFetchError("allow_browser must be a bool")
    if max_requests is not None and (
        isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests <= 0
    ):
        raise WalledFetchError("max_requests must be a positive integer")
    if publisher_page is not None and not callable(publisher_page):
        raise WalledFetchError("publisher_page must be callable when given")
    proxies = ProxyFetchers.from_environment() if proxies is None else proxies
    zyte, firecrawl = proxies.zyte, proxies.firecrawl
    shared = {"max_bytes": max_bytes, "timeout_seconds": timeout_seconds, "publisher_page": publisher_page}
    rungs: list[tuple[Transport, object, Callable[[], WalledFetchResult | RungOutcome]]] = [
        (Transport.DIRECT, None, partial(_direct_rung, url, user_agent=user_agent, direct=direct, **shared)),
        (Transport.ZYTE_HTTP, zyte, partial(_zyte_rung, url, mode=HTTP_RESPONSE_BODY, fetcher=zyte, **shared)),
        (Transport.FIRECRAWL_RAW, firecrawl, partial(_firecrawl_rung, url, fetcher=firecrawl, **shared)),
    ]
    if allow_browser:
        rungs.append(
            (Transport.ZYTE_BROWSER, zyte, partial(_zyte_rung, url, mode=BROWSER_HTML, fetcher=zyte, **shared))
        )
    outcomes: list[RungOutcome] = []
    wall_body: bytes | None = None
    for transport, provider, rung in rungs[:max_requests]:
        if isinstance(provider, str):
            # Resolved without a credential: this rung makes no request, so it is neither charged nor paced.
            answer: WalledFetchResult | RungOutcome = RungOutcome(transport, "credential-error", detail=provider)
        else:
            if before_request is not None and not (transport is Transport.DIRECT and direct is not None):
                before_request()
            answer = rung()
        if isinstance(answer, WalledFetchResult):
            return answer
        outcomes.append(answer)
        if wall_body is None and answer.kind == "wall" and answer.body is not None:
            wall_body = answer.body
    request_limit = max_requests if max_requests is not None and max_requests < len(rungs) else None
    raise _exhausted(url, tuple(outcomes), wall_body, request_limit=request_limit)


__all__ = [
    "DEFAULT_USER_AGENT",
    "DirectCapture",
    "ProxyFetchers",
    "RungOutcome",
    "RungOutcomeKind",
    "Transport",
    "WallFamily",
    "WallMarker",
    "WalledFetchError",
    "WalledFetchResult",
    "detect_spa_shell",
    "detect_wall",
    "walled_fetch",
]
