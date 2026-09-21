"""Route one bounded capture through Zyte as an injectable ``httpx`` transport.

A proxied body is evidence of what Zyte's client was served, not of a direct
capture, so every response carries a :class:`ZyteProxyRecord` naming the
provider's request id, the mode and that the publisher saw the proxy. Exactly
one provider call per request, no retry of its own, and no credential to the
publisher; ``browserHtml`` stays distinct from ``httpResponseBody`` because a
rendered DOM is not bytes any publisher sent. The shared transport lives here
because acquisition is this package's job and RefSpec depends on it, not the
reverse.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from spicy_docs.sources.zyte import (
    BROWSER_HTML,
    HTTP_RESPONSE_BODY,
    MODES,
    ZyteHttpFetcher,
    ZyteTransportError,
)

#: What the publisher observed. Stated on every record so a receipt cannot
#: report a proxied capture as a direct one by omission.
PROXIED_CLIENT = "zyte"


class ZyteBudget:
    """A hard ceiling on provider calls, shared across every transport that draws on it.

    A per-acquirer request budget cannot bound spend on a paid proxy, because a
    measurement opens one acquirer per family. This is the one counter that
    does, and it refuses rather than exceeding its ceiling.
    """

    def __init__(self, max_requests: int) -> None:
        if max_requests <= 0:
            raise ZyteTransportError("max_requests must be positive")
        self.max_requests = max_requests
        self._spent = 0

    @property
    def spent(self) -> int:
        return self._spent

    def take(self) -> None:
        if self._spent >= self.max_requests:
            raise ZyteTransportError(f"Zyte request budget of {self.max_requests} is exhausted")
        self._spent += 1


@dataclass(frozen=True, slots=True)
class ZyteProxyRecord:
    """One proxied capture's provenance, in the shape a receipt row needs."""

    ordinal: int
    requested_url: str
    resolved_url: str
    mode: str
    zyte_request_id: str | None
    status_code: int
    content_type: str | None
    byte_size: int
    sha256: str
    proxied_client: str = PROXIED_CLIENT

    @property
    def body_is_publisher_bytes(self) -> bool:
        """``browserHtml`` is Zyte's rendering; only ``httpResponseBody`` is the publisher's bytes."""
        return self.mode == HTTP_RESPONSE_BODY


class ZyteTransport(httpx.BaseTransport):
    """An ``httpx`` transport that makes exactly one Zyte call per request.

    O(1) provider calls and O(B) bytes per request, for a body the caller
    bounds; the record list grows by one entry per request and holds no bodies.
    """

    def __init__(
        self,
        fetcher: ZyteHttpFetcher,
        *,
        max_bytes: int,
        timeout_seconds: float,
        mode: str = HTTP_RESPONSE_BODY,
        budget: ZyteBudget | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ZyteTransportError("max_bytes must be positive")
        if timeout_seconds <= 0:
            raise ZyteTransportError("timeout_seconds must be positive")
        if mode not in MODES:
            raise ZyteTransportError(f"Zyte mode must be one of {MODES}")
        self._fetcher = fetcher
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._mode = mode
        self._budget = budget
        self._records: list[ZyteProxyRecord] = []

    @property
    def records(self) -> Sequence[ZyteProxyRecord]:
        """Every proxied capture this transport made, in request order."""
        return tuple(self._records)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Proxy this one GET through the fetcher, spending one budget call.

        A different method or a URL the proxy resolves elsewhere is refused.
        """
        if request.method != "GET":
            # The provider call is a POST to Zyte carrying the target URL; a
            # target-side POST body has nowhere to go, and silently sending a
            # GET instead would answer a different request than the caller made.
            raise ZyteTransportError("the Zyte transport proxies GET requests only")
        if self._budget is not None:
            self._budget.take()
        url = str(request.url)
        response = self._fetcher.fetch(
            url,
            timeout_seconds=self._timeout_seconds,
            max_bytes=self._max_bytes,
            mode=self._mode,
        )
        if response.resolved_url != url:
            # The caller's client follows no redirect; reporting the proxy's
            # final URL as an answer to the requested one would hide the hop.
            raise ZyteTransportError("Zyte resolved the target to a different URL than the one requested")
        record = ZyteProxyRecord(
            ordinal=len(self._records) + 1,
            requested_url=url,
            resolved_url=response.resolved_url,
            mode=response.mode,
            zyte_request_id=response.request_id,
            status_code=response.status_code,
            content_type=response.content_type,
            byte_size=len(response.body),
            sha256=hashlib.sha256(response.body).hexdigest(),
        )
        self._records.append(record)
        headers = [("content-type", response.content_type)] if response.content_type else []
        return httpx.Response(
            response.status_code,
            headers=headers,
            # An iterator, not the bytes: bytes mark the response as already
            # consumed, and the shared capture client reads every body through
            # ``iter_raw`` so it can stop at its own byte bound.
            content=iter((response.body,)),
            request=request,
            extensions={"zyte_proxy_record": record},
        )


__all__ = [
    "BROWSER_HTML",
    "HTTP_RESPONSE_BODY",
    "PROXIED_CLIENT",
    "ZyteBudget",
    "ZyteProxyRecord",
    "ZyteTransport",
]
