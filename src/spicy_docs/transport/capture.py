"""Bounded exact HTTP captures shared by source-specific acquisition clients.

Source modules choose URLs, validate identities and decide fallback. This client
owns request counts, pacing and complete response bytes; it never persists them.
Install spicy-docs[acquisition] to use its optional HTTPX dependency.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, observed_instant, refused_capture
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.http import RetryableHTTPStatusError
from spicy_docs.transport.retry import retry_http


class _RetryableTransportError(ConnectionError):
    """Transport failed without copying arbitrary provider text into logs."""


def _evidence_media_type(response: httpx.Response) -> str:
    """The media type raw evidence bytes are: the stated one, unless the body is encoded."""
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        # Raw encoded bytes are evidence, not the decoded format named by the header.
        return "application/octet-stream"
    return (response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]


def _stated_length(response: httpx.Response) -> int | None:
    """The response's ``Content-Length`` as an integer, or ``None`` when it states none or an invalid one."""
    stated = response.headers.get("content-length")
    return int(stated) if stated is not None and stated.isascii() and stated.isdigit() else None


def _access_refusal(response: httpx.Response, url: str, max_bytes: int) -> RefusedResponse:
    """Retain complete bounded raw evidence for a 401/403; a failed read marks it unavailable, never absent."""
    media_type = _evidence_media_type(response)
    body = bytearray()
    try:
        for chunk in response.iter_raw(chunk_size=min(max_bytes + 1, 64 * 1024)):
            observed = len(body) + len(chunk)
            if observed > max_bytes:
                return RefusedResponse(
                    url, "transport", None, media_type, "response-byte-limit", observed, _stated_length(response)
                )
            body.extend(chunk)
    except httpx.RequestError:
        return RefusedResponse(url, "transport", None, media_type, "response-unavailable", len(body))
    return RefusedResponse(url, "transport", bytes(body), media_type, "access-refused", len(body))


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
        headers: Mapping[str, str] | None = None,
        retain_refusal_bodies: bool = False,
    ) -> None:
        """``headers`` adds fixed request headers, such as a credential header; they never enter URLs.

        ``retain_refusal_bodies`` is for keyless routes, where a 401/403 is a bot
        wall rather than a rejected key and its body is evidence; a keyed route
        must leave it off, since the body can echo the key.
        """
        self.max_requests = max_requests
        self.retain_refusal_bodies = retain_refusal_bodies
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
            headers={"User-Agent": user_agent, "Accept-Encoding": "identity", **dict(headers or {})},
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

    def start_request(self) -> None:
        """Charge one attempt to this operation's budget and pace it; any transport's attempt may call it."""
        if self._closed:
            raise ValueError("Source acquisition client is closed")
        if self._request_count >= self.max_requests:
            raise self.error_type("Source acquisition exhausted its total request budget")
        if self._last_request_start is not None:
            while (delay := self.min_request_interval_seconds - (time.monotonic() - self._last_request_start)) > 0:
                time.sleep(delay)
        self._last_request_start = time.monotonic()
        self._request_count += 1

    def capture(
        self,
        url: str,
        *,
        max_bytes: int,
        allow_unavailable: bool = False,
        allow_gzip: bool = False,
        method: str = "GET",
        content: bytes | None = None,
        request_headers: Mapping[str, str] | None = None,
        retain_dropped_body: bool = False,
        max_attempts: int | None = None,
    ) -> CapturedBodyResponse:
        """``POST`` sends ``content`` verbatim and records it on the capture; credentials never belong in it.

        ``max_attempts`` caps this call's retries below the remaining budget; a
        ladder rung passes ``1`` so its one attempt is recorded, not retried.

        ``retain_dropped_body`` keeps what a body delivered before any
        ``httpx.RequestError`` cut it short (a dropped connection, a reset, a read
        timeout) as the transport refusal's evidence, marked
        ``response-incomplete`` so it is never read as the whole answer. The
        failure is retried exactly as without it; the error that finally escapes
        carries the last attempt's bytes. It is for keyless routes only: those
        bytes never reach the credential-echo check a completed capture gets.
        """
        if self._closed:
            raise ValueError("Source acquisition client is closed")
        if method not in ("GET", "POST"):
            raise ValueError("method must be GET or POST")
        if (content is not None) != (method == "POST"):
            raise ValueError("POST requires a request body and GET forbids one")
        if max_attempts is not None and (
            isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts <= 0
        ):
            raise ValueError("max_attempts must be a positive integer")
        headers = {"Accept-Encoding": "gzip" if allow_gzip else "identity", **dict(request_headers or {})}

        def attempt() -> CapturedBodyResponse:
            self.start_request()
            # A cookie set by one response must not steer the next request:
            # a publisher that keys page selection on session state would
            # otherwise answer a different page than the URL names.
            self._client.cookies.clear()
            try:
                with self._client.stream(method, url, headers=headers, content=content) as response:
                    if response.status_code in (401, 403):
                        error = CredentialRefusedError(
                            f"Body source answered HTTP {response.status_code}; stopping acquisition"
                        )
                        if self.retain_refusal_bodies:
                            attach_refused_response(error, _access_refusal(response, url, max_bytes))
                        raise error
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
                            RefusedResponse(
                                url,
                                "transport",
                                None,
                                "application/octet-stream",
                                "response-byte-limit",
                                stated_byte_size=int(stated_length),
                            ),
                        )
                        raise error
                    body = bytearray()
                    # HTTPX's chunker yields at most this size, including over
                    # short transport reads. A complete capture needs EOF. The
                    # chunker loses what it holds when the stream fails, so a
                    # dropped body is kept only by reading chunks as they arrive.
                    chunk_size = None if retain_dropped_body else min(max_bytes + 1, 64 * 1024)
                    try:
                        for chunk in response.iter_raw(chunk_size=chunk_size):
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
                                        None if stated_length is None else int(stated_length),
                                    ),
                                )
                                raise error
                            body.extend(chunk)
                    except httpx.RequestError:
                        if not retain_dropped_body:
                            raise
                        dropped = _RetryableTransportError("Body source transport failed while acquiring a response")
                        attach_refused_response(
                            dropped,
                            RefusedResponse(
                                url,
                                "transport",
                                bytes(body),
                                _evidence_media_type(response),
                                "response-incomplete",
                                len(body),
                            ),
                        )
                        raise dropped from None
                    capture = CapturedBodyResponse(
                        requested_url=url,
                        resolved_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        observed_at=observed_instant(self._clock),
                        body=bytes(body),
                        content_encoding=encoding,
                        method=method,
                        request_body=content,
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
                        attach_capture(error, capture)
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
                max_attempts=remaining if max_attempts is None else min(remaining, max_attempts),
            )
        except Exception as error:
            attach_refused_response(
                error,
                RefusedResponse(url, "transport", None, "application/octet-stream", "response-unavailable"),
            )
            raise
