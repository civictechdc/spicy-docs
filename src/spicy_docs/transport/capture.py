"""Bounded exact HTTP captures shared by source-specific acquisition clients.

Source modules choose URLs, validate identities and decide fallback. This client
owns request counts, pacing and complete response bytes; it never persists them.
Install spicy-docs[acquisition] to use its optional HTTPX dependency.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError
from spicy_docs.transport.retry import retry_http


@dataclass(frozen=True, slots=True)
class CapturedBodyResponse:
    """Exact response payload bytes, before any content decoding, and observed facts."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    observed_at: str
    body: bytes = field(repr=False)
    content_encoding: str = "identity"

    @property
    def byte_size(self) -> int:
        return len(self.body)

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.body).hexdigest()


class _RetryableTransportError(ConnectionError):
    """Transport failed without copying arbitrary provider text into logs."""


def refused_capture(capture: CapturedBodyResponse, *, stage: str) -> RefusedResponse:
    return RefusedResponse(
        request_key=capture.requested_url,
        stage=stage,
        response_bytes=capture.body,
        media_type=(capture.content_type or "application/octet-stream").split(";", 1)[0].strip(),
        observed_byte_size=capture.byte_size,
    )


class BoundedHttpCapture:
    """One sequential client with per-operation counts and persistent pacing.

    The owning source validates configuration and calls reset_budget before each
    public operation. Every attempt consumes one request, including retries.
    Injected transports must not add hidden requests or authentication.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        timeout_seconds: float,
        min_request_interval_seconds: float,
        user_agent: str,
        error_type: type[Exception],
        transport: httpx.BaseTransport | None,
        clock: Callable[[], datetime],
    ) -> None:
        self.max_requests = max_requests
        self.min_request_interval_seconds = min_request_interval_seconds
        self.error_type = error_type
        self._clock = clock
        self._last_request_start: float | None = None
        self._request_count = 0
        self._closed = False
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
        )

    @property
    def request_count(self) -> int:
        return self._request_count

    def reset_budget(self) -> None:
        if self._closed:
            raise ValueError("Source acquisition client is closed")
        self._request_count = 0

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def _start_request(self) -> None:
        if self._request_count >= self.max_requests:
            raise self.error_type("Source acquisition exhausted its total request budget")
        if self._last_request_start is not None:
            while (delay := self.min_request_interval_seconds - (time.monotonic() - self._last_request_start)) > 0:
                time.sleep(delay)
        self._last_request_start = time.monotonic()
        self._request_count += 1

    def capture(
        self, url: str, *, max_bytes: int, allow_unavailable: bool = False, allow_gzip: bool = False
    ) -> CapturedBodyResponse:
        if self._closed:
            raise ValueError("Source acquisition client is closed")

        def attempt() -> CapturedBodyResponse:
            self._start_request()
            try:
                with self._client.stream(
                    "GET", url, headers={"Accept-Encoding": "gzip" if allow_gzip else "identity"}
                ) as response:
                    if response.status_code in (401, 403):
                        raise CredentialRefusedError(
                            f"Body source answered HTTP {response.status_code}; stopping acquisition"
                        )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise RetryableHTTPStatusError(
                            f"Body source answered retryable HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    encoding = response.headers.get("content-encoding", "identity").strip().lower()
                    if encoding not in ({"identity", "gzip"} if allow_gzip else {"identity"}):
                        raise self.error_type("Body source response uses unsupported content encoding")
                    stated_length = response.headers.get("content-length")
                    if stated_length is not None and (not stated_length.isascii() or not stated_length.isdigit()):
                        raise self.error_type("Body source response Content-Length is invalid")
                    if stated_length is not None and int(stated_length) > max_bytes:
                        error = self.error_type("Body source response exceeds its byte bound")
                        attach_refused_response(
                            error,
                            RefusedResponse(url, "transport", None, "application/octet-stream", "response-byte-limit"),
                        )
                        raise error
                    body = bytearray()
                    # HTTPX's chunker yields at most this size, including over
                    # short transport reads. A complete capture needs EOF.
                    for chunk in response.iter_raw(chunk_size=min(max_bytes + 1, 64 * 1024)):
                        if len(body) + len(chunk) > max_bytes:
                            error = self.error_type("Body source response exceeds its byte bound")
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
                        raise ValueError("Source acquisition clock must return a timezone-aware instant")
                    capture = CapturedBodyResponse(
                        requested_url=url,
                        resolved_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        observed_at=observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                        body=bytes(body),
                        content_encoding=encoding,
                    )
                    try:
                        if stated_length is not None and int(stated_length) != capture.byte_size:
                            raise self.error_type("Body source response size differs from Content-Length")
                        if capture.resolved_url != url:
                            raise self.error_type("Body source response final URL differs from its request")
                        if response.status_code != 200 and not (
                            allow_unavailable and response.status_code in (404, 410)
                        ):
                            raise self.error_type(f"Body source answered HTTP {response.status_code}")
                    except self.error_type as error:
                        error.__dict__["capture"] = capture
                        attach_refused_response(error, refused_capture(capture, stage="transport"))
                        raise
                    return capture
            except httpx.RequestError:
                raise _RetryableTransportError("Body source transport failed while acquiring a response") from None

        try:
            remaining = self.max_requests - self._request_count
            if remaining <= 0:
                error = self.error_type("Source acquisition exhausted its total request budget")
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
