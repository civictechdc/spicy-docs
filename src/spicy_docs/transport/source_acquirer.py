"""Shared shape for explicit source acquirers: budget checks, client lifecycle, capture then validate.

Source families keep their own selections, locators, validators, error types
and result dataclasses. This module owns what was copied between them: how a
budget is checked, how the bounded HTTP client is created and closed, and how
one capture becomes a validated result with refusal evidence attached.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, refused_capture
from spicy_docs.transport.credentials import CredentialRefusedError

if TYPE_CHECKING:
    import httpx


def check_request_count(value: object, name: str = "max_requests") -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def check_byte_bound(value: object, name: str, cap: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
        raise ValueError(f"{name} must be an integer from 1 to {cap}")


def check_timing(timeout_seconds: object, min_request_interval_seconds: object) -> None:
    """Timeouts must be positive; a zero start interval explicitly disables pacing."""
    for name, value, positive in (
        ("timeout_seconds", timeout_seconds, True),
        ("min_request_interval_seconds", min_request_interval_seconds, False),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or (positive and value == 0)
        ):
            raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")


def check_payload(
    payload: object,
    max_bytes: object,
    *,
    label: str,
    error_type: type[ValueError],
    allow_empty: bool = True,
) -> bytes:
    """Return exact captured bytes within a positive caller bound, or refuse.

    One rule for every source validator: evidence is complete ``bytes``, its
    bound is a positive integer the caller chose, and nothing past that bound
    becomes evidence. ``allow_empty=False`` refuses an empty response where the
    source cannot mean one, keeping "the publisher sent nothing" separate from
    "the publisher sent something this module could not read".
    """
    if not isinstance(payload, bytes):
        raise error_type(f"{label} must be exact bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise error_type(f"{label} byte bound must be a positive integer")
    if not payload and not allow_empty:
        raise error_type(f"{label} is empty")
    if len(payload) > max_bytes:
        raise error_type(f"{label} exceeds its {max_bytes}-byte bound")
    return payload


def narrow_byte_limit(limit: int, max_bytes: int | None) -> int:
    """A call may narrow the client's byte allowance, never raise it."""
    if max_bytes is None:
        return limit
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return min(limit, max_bytes)


def utc_now() -> datetime:
    return datetime.now(UTC)


def check_final_url(final_url: str, locator: str, *, error_type: type[ValueError], message: str) -> None:
    """The response must have come from exactly the locator the request named."""
    if final_url != locator:
        raise error_type(message)


@contextmanager
def named_challenge(url: str, *, error_type: Callable[[str], Exception], context_key: str) -> Iterator[None]:
    """Recast a keyless route's 401/403 as the family's own error, not a credential refusal.

    The shared client maps 401/403 to ``CredentialRefusedError`` so a keyed
    family aborts rather than treating a refusal as a bad row. A keyless
    family holds no credential, so the same status is a bot wall or an
    access refusal, not a key being rejected -- and a caller catching the
    family's own ``error_type`` (typically a subclass of its shared source
    error) would otherwise miss it, since ``CredentialRefusedError`` is not
    one. This substitutes ``error_type(url)`` while keeping the acquisition
    context and refusal record the shared client already attached, so the
    refusal's bytes still reach the caller on ``refused_response``.
    """
    try:
        yield
    except CredentialRefusedError as error:
        challenge = error_type(url)
        carried = (context_key, "refused_response")
        challenge.__dict__.update({key: error.__dict__[key] for key in carried if key in error.__dict__})
        raise challenge from error


class SourceAcquirer:
    """A sequential, caller-owned client. Subclasses select, locate and validate.

    Request counts reset per operation; pacing persists until ``close``.
    ``context_key`` names the attribute a failing call attaches to its error
    (for example ``cfr_acquisition``) so receipts record the operation,
    selection, request count and effective budget.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        timeout_seconds: float,
        min_request_interval_seconds: float,
        user_agent: str,
        label: str,
        error_type: type[ValueError],
        context_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        headers: Mapping[str, str] | None = None,
        keyless: bool = False,
        credential: str | None = None,
    ) -> None:
        """``keyless`` routes keep 401/403 bodies as evidence; ``credential`` is refused if a body echoes it."""
        if keyless and credential:
            raise ValueError("a keyless acquirer cannot carry a credential")
        self.label = label
        self.error_type = error_type
        self.context_key = context_key
        self._credential = credential
        # The client needs the optional HTTPX dependency; locators and validators do not.
        from spicy_docs.transport.capture import BoundedHttpCapture

        self._http = BoundedHttpCapture(
            max_requests=max_requests,
            timeout_seconds=timeout_seconds,
            min_request_interval_seconds=min_request_interval_seconds,
            user_agent=user_agent,
            error_type=error_type,
            transport=transport,
            clock=clock,
            headers=headers,
            retain_refusal_bodies=keyless,
        )

    @property
    def request_count(self) -> int:
        return self._http.request_count

    def __enter__(self) -> Self:
        self._http.reset_budget()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def capture_validated[Result](
        self,
        url: str,
        *,
        media_types: tuple[str, ...],
        parse: Callable[[CapturedBodyResponse, int], Result],
        max_bytes: int,
        unavailable: Callable[[CapturedBodyResponse], Exception],
        context: Mapping[str, object],
        allow_gzip: bool = False,
        method: str = "GET",
        content: bytes | None = None,
        request_headers: Mapping[str, str] | None = None,
    ) -> tuple[Result, CapturedBodyResponse]:
        """One request; 404/410 raise ``unavailable``; any failure carries its capture and context."""
        self._http.reset_budget()
        capture = None
        try:
            capture = self._http.capture(
                url,
                max_bytes=max_bytes,
                allow_unavailable=True,
                allow_gzip=allow_gzip,
                method=method,
                content=content,
                request_headers=request_headers,
            )
            if capture.status_code in (404, 410):
                raise unavailable(capture)
            if self._credential and self._credential.encode() in capture.body:
                raise CredentialRefusedError("source response echoed the API credential; capture was not retained")
            media_type = (capture.content_type or "").split(";", 1)[0].strip().casefold()
            if media_type not in media_types:
                raise self.error_type(f"{self.label} source Content-Type differs from the requested format")
            return parse(capture, max_bytes), capture
        except Exception as error:
            # Transport already attaches bounded public refusal evidence.
            # Do not attach a capture here after a credential refusal: its body
            # may have echoed the key.
            if capture is not None and not isinstance(error, CredentialRefusedError):
                attach_capture(error, capture)
                attach_refused_response(error, refused_capture(capture, stage="source-validation"))
            error.__dict__[self.context_key] = {**dict(context), "requestCount": self._http.request_count}
            raise
