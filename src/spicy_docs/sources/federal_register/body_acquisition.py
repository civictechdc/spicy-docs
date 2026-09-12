"""Bounded acquisition of a selected GovInfo Federal Register body.

The caller selects either the direct granule or issue-MODS start-page route.
This sequential client owns request bounds and pacing, while the pure
``body_sources`` module owns identity. Returned bytes can be stored or supplied
to a dataset fetcher without another download. No catalog or run state is made.
Install ``spicy-docs[acquisition]`` for this HTTPX-based operation.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal, Self

import httpx

from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.federal_register.body_sources import (
    FederalRegisterBodySourceError,
    GovInfoGranuleIdentity,
    GovInfoModsResolution,
    govinfo_granule_locator,
    govinfo_mods_locator,
    resolve_govinfo_granule_from_mods,
    validate_govinfo_granule,
)
from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError
from spicy_docs.transport.retry import retry_http

GovInfoBodyRoute = Literal["granule", "mods-start-page"]
_USER_AGENT = "spicy-docs-govinfo-body/1.0"


@dataclass(frozen=True, slots=True)
class GovInfoBodyBudget:
    """Per-acquisition request/byte bounds and per-client request-start pacing.

    ``max_requests`` includes every MODS/body request and retry. Redirects are
    always refused. The timeout bounds transport waits, not total elapsed time.
    A zero start interval explicitly disables pacing within this client.
    """

    max_requests: int
    max_body_bytes: int
    max_mods_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int) or self.max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        for name in ("max_body_bytes", "max_mods_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_EVIDENCE_BYTES:
                raise ValueError(f"{name} must be an integer from 1 to {MAX_EVIDENCE_BYTES}")
        for name, positive in (("timeout_seconds", True), ("min_request_interval_seconds", False)):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or positive
                and value == 0
            ):
                raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")


@dataclass(frozen=True, slots=True)
class CapturedGovInfoResponse:
    """One complete response body and the public facts observed with it."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    observed_at: str
    body: bytes = field(repr=False)

    @property
    def byte_size(self) -> int:
        return len(self.body)

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True, slots=True)
class GovInfoBodyAcquisition:
    """Validated source identity and captures, without a separate publication."""

    route: GovInfoBodyRoute
    identity: GovInfoGranuleIdentity
    body: CapturedGovInfoResponse
    mods: CapturedGovInfoResponse | None
    mods_resolution: GovInfoModsResolution | None
    request_count: int
    budget: GovInfoBodyBudget


class _RetryableTransportError(ConnectionError):
    """Transport failed without copying arbitrary provider text into logs."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _refused(capture: CapturedGovInfoResponse, *, stage: str) -> RefusedResponse:
    return RefusedResponse(
        request_key=capture.requested_url,
        stage=stage,
        response_bytes=capture.body,
        media_type=(capture.content_type or "application/octet-stream").split(";", 1)[0].strip(),
        observed_byte_size=capture.byte_size,
    )


class GovInfoBodyAcquirer:
    """Acquire explicit GovInfo routes using one sequential, caller-owned client.

    Request counts reset per ``acquire``; pacing persists until ``close``.
    The operation accepts no credentials, redirects or automatic route fallback.
    Injected transports must honor HTTPX's streaming interface and may not add
    hidden requests or authentication. This class is not a concurrent scheduler.
    """

    def __init__(
        self,
        *,
        budget: GovInfoBodyBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(budget, GovInfoBodyBudget):
            raise TypeError("budget must be a GovInfoBodyBudget")
        self.budget = budget
        self._clock = clock
        self._last_request_start: float | None = None
        self._closed = False
        self._request_count = 0
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(budget.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"},
        )

    def __enter__(self) -> Self:
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def _start_request(self) -> None:
        if self._request_count >= self.budget.max_requests:
            raise FederalRegisterBodySourceError("GovInfo acquisition exhausted its total request budget")
        if self._last_request_start is not None:
            while (
                delay := self.budget.min_request_interval_seconds - (time.monotonic() - self._last_request_start)
            ) > 0:
                time.sleep(delay)
        self._last_request_start = time.monotonic()
        self._request_count += 1

    def _capture(self, url: str, *, max_bytes: int) -> CapturedGovInfoResponse:
        def attempt() -> CapturedGovInfoResponse:
            self._start_request()
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code in (401, 403):
                        raise CredentialRefusedError(
                            f"GovInfo answered HTTP {response.status_code}; stopping acquisition"
                        )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise RetryableHTTPStatusError(
                            f"GovInfo answered retryable HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise FederalRegisterBodySourceError("GovInfo response uses unsupported content encoding")
                    stated_length = response.headers.get("content-length")
                    if stated_length is not None and (not stated_length.isascii() or not stated_length.isdigit()):
                        raise FederalRegisterBodySourceError("GovInfo response Content-Length is invalid")
                    if stated_length is not None and int(stated_length) > max_bytes:
                        error = FederalRegisterBodySourceError("GovInfo response exceeds its byte bound")
                        attach_refused_response(
                            error,
                            RefusedResponse(url, "transport", None, "application/octet-stream", "response-byte-limit"),
                        )
                        raise error
                    body = bytearray()
                    # HTTPX's chunker yields at most this size, including over
                    # short transport reads. A complete capture needs EOF.
                    for chunk in response.iter_raw(chunk_size=max_bytes + 1):
                        if len(body) + len(chunk) > max_bytes:
                            error = FederalRegisterBodySourceError("GovInfo response exceeds its byte bound")
                            attach_refused_response(
                                error,
                                RefusedResponse(
                                    url,
                                    "transport",
                                    None,
                                    "application/octet-stream",
                                    "response-byte-limit",
                                    len(body) + len(chunk),
                                ),
                            )
                            raise error
                        body.extend(chunk)
                    observed_at = self._clock()
                    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                        raise ValueError("GovInfo acquisition clock must return a timezone-aware instant")
                    capture = CapturedGovInfoResponse(
                        requested_url=url,
                        resolved_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        observed_at=observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                        body=bytes(body),
                    )
                    try:
                        if response.status_code != 200:
                            raise FederalRegisterBodySourceError(f"GovInfo answered HTTP {response.status_code}")
                        if stated_length is not None and int(stated_length) != capture.byte_size:
                            raise FederalRegisterBodySourceError("GovInfo response size differs from Content-Length")
                        if capture.resolved_url != url:
                            raise FederalRegisterBodySourceError("GovInfo response final URL differs from its request")
                    except FederalRegisterBodySourceError as error:
                        attach_refused_response(error, _refused(capture, stage="transport"))
                        raise
                    return capture
            except httpx.RequestError:
                raise _RetryableTransportError("GovInfo transport failed while acquiring a response") from None

        try:
            remaining = self.budget.max_requests - self._request_count
            if remaining <= 0:
                error = FederalRegisterBodySourceError("GovInfo acquisition exhausted its total request budget")
                attach_refused_response(
                    error,
                    RefusedResponse(
                        url, "before-request", None, "application/octet-stream", "request-budget-exhausted"
                    ),
                )
                raise error
            return retry_http(
                attempt,
                retryable=(_RetryableTransportError, RetryableHTTPStatusError),
                max_attempts=remaining,
            )
        except Exception as error:
            attach_refused_response(
                error,
                RefusedResponse(url, "transport", None, "application/octet-stream", "response-unavailable"),
            )
            raise

    def acquire(
        self,
        *,
        document_number: str,
        publication_date: str,
        route: GovInfoBodyRoute,
        start_page: int | None = None,
    ) -> GovInfoBodyAcquisition:
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        granule_url = govinfo_granule_locator(document_number, publication_date)
        if route not in ("granule", "mods-start-page"):
            raise ValueError("GovInfo body route must be granule or mods-start-page")
        if route == "mods-start-page":
            if isinstance(start_page, bool) or not isinstance(start_page, int) or start_page <= 0:
                raise ValueError("MODS route requires a positive integer start_page")
            if self.budget.max_requests < 2:
                raise ValueError("MODS route requires a total budget of at least two requests")
        elif start_page is not None:
            raise ValueError("start_page is only valid for the MODS route")
        self._request_count = 0
        mods = None
        resolution = None
        active_capture = None
        try:
            access_id = document_number
            if route == "mods-start-page":
                assert start_page is not None
                mods = self._capture(govinfo_mods_locator(publication_date), max_bytes=self.budget.max_mods_bytes)
                active_capture = mods
                resolution = resolve_govinfo_granule_from_mods(
                    mods.body,
                    publication_date=publication_date,
                    start_page=start_page,
                    max_bytes=self.budget.max_mods_bytes,
                )
                access_id = resolution.access_id
                granule_url = resolution.granule_url
            # A failed later request must not inherit the successful MODS body.
            active_capture = None
            body = self._capture(granule_url, max_bytes=self.budget.max_body_bytes)
            active_capture = body
            identity = validate_govinfo_granule(
                body.body,
                source_document_number=document_number,
                publication_date=publication_date,
                access_id=access_id,
                final_url=body.resolved_url,
                max_bytes=self.budget.max_body_bytes,
            )
            return GovInfoBodyAcquisition(route, identity, body, mods, resolution, self._request_count, self.budget)
        except Exception as error:
            if active_capture is not None:
                attach_refused_response(error, _refused(active_capture, stage="source-validation"))
            error.__dict__["body_acquisition"] = {
                "route": route,
                "documentNumber": document_number,
                "publicationDate": publication_date,
                "startPage": start_page,
                "requestCount": self._request_count,
                "budget": asdict(self.budget),
            }
            raise


__all__ = [
    "CapturedGovInfoResponse",
    "GovInfoBodyAcquirer",
    "GovInfoBodyAcquisition",
    "GovInfoBodyBudget",
    "GovInfoBodyRoute",
]
