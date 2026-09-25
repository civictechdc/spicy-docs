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

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, observed_instant, refused_capture
from spicy_docs.transport.credentials import CredentialRefusedError

if TYPE_CHECKING:
    import httpx

    from spicy_docs.sources.walled_fetch import ProxyFetchers, WalledFetchResult


def check_request_count(value: object, name: str = "max_requests") -> None:
    """Refuse anything but a positive integer (bools excluded) under ``name``."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def check_byte_bound(value: object, name: str, cap: int) -> None:
    """Refuse anything but an integer from 1 to ``cap`` (bools excluded) under ``name``."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
        raise ValueError(f"{name} must be an integer from 1 to {cap}")


def limit_byte_bound(value: object, *, name: str, cap: int, error_type: type[ValueError]) -> int:
    """One rule every source family applies to its own byte budget.

    The bound must be a positive integer at or under the family's measured cap,
    refused with the family's own error rather than the shared ``ValueError`` a
    caller would not catch. Caps are whole MiB and the refusal says so in MiB.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
        raise error_type(f"{name} must be a positive integer no greater than {cap // (1024 * 1024)} MiB")
    return value


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

    The shared client maps 401/403 to ``CredentialRefusedError`` so a keyed family
    aborts rather than treating a refusal as a bad row; a keyless family holds no
    credential, so the same status is a bot wall or an access refusal. Substituting
    ``error_type(url)`` keeps the acquisition context and refusal record the shared
    client attached, so the refusal's bytes still reach the caller.
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
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._proxies: ProxyFetchers | None = None
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

    def start_external_request(self, *, reset_budget: bool = False) -> None:
        """Charge and pace an attempt made outside the shared client; ``reset_budget`` starts a new operation."""
        if reset_budget:
            self._http.reset_budget()
        self._http.start_request()

    def _checked[Result](
        self,
        capture: CapturedBodyResponse,
        *,
        media_types: tuple[str, ...],
        parse: Callable[[CapturedBodyResponse, int], Result],
        max_bytes: int,
        unavailable: Callable[[CapturedBodyResponse], Exception],
    ) -> Result:
        """The checks every capture passes, whichever route carried it; 404/410 raise ``unavailable``."""
        if capture.status_code in (404, 410):
            raise unavailable(capture)
        if self._credential and self._credential.encode() in capture.body:
            raise CredentialRefusedError("source response echoed the API credential; capture was not retained")
        if bare_media_type(capture.content_type) not in media_types:
            raise self.error_type(f"{self.label} source Content-Type differs from the requested format")
        return parse(capture, max_bytes)

    def _attach(self, error: Exception, capture: CapturedBodyResponse | None, context: Mapping[str, object]) -> None:
        """A failing call's error carries its capture, refusal record and operation context."""
        # Transport already attaches bounded public refusal evidence. Do not
        # attach a capture after a credential refusal: its body may have echoed the key.
        if capture is not None and not isinstance(error, CredentialRefusedError):
            attach_capture(error, capture)
            attach_refused_response(error, refused_capture(capture, stage="source-validation"))
        error.__dict__[self.context_key] = {**dict(context), "requestCount": self._http.request_count}

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
        reset_budget: bool = True,
        retain_dropped_body: bool = False,
    ) -> tuple[Result, CapturedBodyResponse]:
        """One request; 404/410 raise ``unavailable``; any failure carries its capture and context.

        ``reset_budget=False`` chains this capture onto the budget a capture
        already made earlier in the same logical operation consumed, rather
        than granting it a fresh ``max_requests``: a source whose one
        operation is more than one HTTP request (a listing read before a
        conditional download, say) passes it on every call after the first so
        ``max_requests`` bounds the whole operation once, not each request in
        it separately, and ``request_count`` after the last call reports the
        true total. ``retain_dropped_body`` is passed to
        :meth:`~spicy_docs.transport.capture.BoundedHttpCapture.capture`, and
        only a keyless acquirer may ask for it.
        """
        if retain_dropped_body and not self._http.retain_refusal_bodies:
            raise ValueError("retain_dropped_body is for keyless routes: the bytes skip the credential-echo check")
        if reset_budget:
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
                retain_dropped_body=retain_dropped_body,
            )
            result = self._checked(
                capture, media_types=media_types, parse=parse, max_bytes=max_bytes, unavailable=unavailable
            )
        except Exception as error:
            self._attach(error, capture, context)
            raise
        return result, capture

    def capture_walled[Result](
        self,
        url: str,
        *,
        media_types: tuple[str, ...],
        parse: Callable[[CapturedBodyResponse, int], Result],
        max_bytes: int,
        unavailable: Callable[[CapturedBodyResponse], Exception],
        context: Mapping[str, object],
        publisher_page: Callable[[bytes], bool] | None = None,
        refusal: Callable[[str], Exception] | None = None,
    ) -> tuple[Result, CapturedBodyResponse, WalledFetchResult]:
        """One operation through the shared ``walled_fetch`` ladder, then :meth:`capture_validated`'s checks.

        The DIRECT rung is this acquirer's own client (one attempt, its
        transport, headers and user agent); each proxy rung is charged and
        paced on the same budget, with provider credentials resolved once per
        acquirer. Every answer is held to the byte bound and the exact locator.
        ``publisher_page`` vouches for this family's own 2xx bodies (see
        :func:`~spicy_docs.sources.walled_fetch.walled_fetch`). Ladder
        exhaustion raises ``WalledFetchError``, or ``refusal(url)`` carrying its
        ``refused_response`` and ``rung_outcomes``. Returns the parsed result,
        the capture, and the ladder's answer (its ``transport`` and provider
        ``request_id``).
        """
        # The ladder imports this module, so it is imported where it is used.
        from spicy_docs.sources.walled_fetch import ProxyFetchers, WalledFetchError, walled_fetch

        if not self._http.retain_refusal_bodies:
            raise ValueError("capture_walled is for keyless routes: a keyed route aborts on 401/403, never escalates")
        if self._proxies is None:
            self._proxies = ProxyFetchers.from_environment()
        self._http.reset_budget()
        context = {**dict(context), "route": "walled-ladder"}
        capture = None
        try:
            try:
                answer = walled_fetch(
                    url,
                    max_bytes=max_bytes,
                    timeout_seconds=self._timeout_seconds,
                    max_requests=self._http.max_requests,
                    before_request=self._http.start_request,
                    publisher_page=publisher_page,
                    direct=self._direct_attempt,
                    proxies=self._proxies,
                )
            except WalledFetchError as error:
                if refusal is None:
                    raise
                named = refusal(url)
                if "refused_response" in error.__dict__:
                    named.__dict__["refused_response"] = error.__dict__["refused_response"]
                named.__dict__["rung_outcomes"] = error.rung_outcomes
                raise named from error
            capture = CapturedBodyResponse(
                requested_url=url,
                resolved_url=answer.final_url,
                status_code=answer.status_code,
                content_type=answer.content_type,
                observed_at=observed_instant(self._clock),
                body=answer.body,
            )
            if capture.byte_size > max_bytes:
                raise self.error_type(f"{self.label} exceeds its {max_bytes}-byte bound")
            check_final_url(
                capture.resolved_url,
                url,
                error_type=self.error_type,
                message=f"{self.label} final URL differs from its locator",
            )
            result = self._checked(
                capture, media_types=media_types, parse=parse, max_bytes=max_bytes, unavailable=unavailable
            )
        except Exception as error:
            self._attach(error, capture, context)
            raise
        return result, capture, answer

    def _direct_attempt(self, url: str, max_bytes: int) -> CapturedBodyResponse:
        """The ladder's DIRECT rung on this acquirer's own client: one attempt, charged and paced like any capture."""
        return self._http.capture(url, max_bytes=max_bytes, allow_unavailable=True, max_attempts=1)
