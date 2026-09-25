"""One bounded credentialed EDIS attachment download, direct or through Zyte.

The EDIS Data Web Service guide (v1.1, 2024-06-14) states that download
requests carry the API token the EDIS web application's "API Token
Generator" issues, appended to an ``Authorization: Bearer`` request header
(the 2010 ``EDIS3WebServiceGuide``'s Basic ``username:secretKey`` form
predates it). Direct HTTP through the shared bounded client is the default; a
caller may explicitly select the shared Zyte adapter for a known wall, which
forwards the header to the target and so discloses the token to that proxy.
A credential refusal never triggers a fallback. The token travels only as a
call argument and is never stored in module state.

A 401/403 is a credential refusal on either route, whatever its body holds,
and no such body is retained. Other answers use the shared wall vocabulary;
only a clean 200/404/410 comes back for the acquirer's PDF proof, and a
response that reflects the token is never retained.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response
from spicy_docs.sources.usitc_edis.attachments import attachment_download_locator
from spicy_docs.sources.usitc_edis.records import USER_AGENT, UsitcEdisSourceError
from spicy_docs.sources.walled_fetch import detect_wall
from spicy_docs.sources.zyte import ZyteHttpFetcher, ZyteTransportError
from spicy_docs.transport.captured import (
    CapturedBodyResponse,
    attach_capture,
    attached_capture,
    observed_instant,
    refused_capture,
)
from spicy_docs.transport.credentials import (
    ACCESS_REFUSED_STATUSES,
    CredentialRefusedError,
    refusal_message,
    scrub_credential,
)
from spicy_docs.transport.http import RetryableHTTPStatusError
from spicy_docs.transport.provider_api import refuse_reflected_credential, validate_provider_credential
from spicy_docs.transport.source_acquirer import utc_now

#: ``scrub_credential`` skips literal secrets shorter than this, so no shorter token is accepted.
MIN_TOKEN_LENGTH: Final = 8
#: A bearer token's practical header bound; JWT-sized tokens fit comfortably.
MAX_TOKEN_LENGTH: Final = 4096
#: The routes a credentialed download may take; neither falls back to the other.
CREDENTIALED_ROUTES: Final = ("direct", "zyte")


def validate_edis_token(token: object) -> str:
    """Accept one EDIS API token without ever repeating its value in an error."""
    if not isinstance(token, str):
        raise UsitcEdisSourceError("EDIS download token must be a nonempty string")
    validate_provider_credential(token, name="EDIS download token", error_type=UsitcEdisSourceError)
    # A bearer value travels in a header line, so no whitespace or control character may split it.
    if any(ord(character) <= 32 or ord(character) == 127 for character in token):
        raise UsitcEdisSourceError("EDIS download token must not contain whitespace or control characters")
    if not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH:
        raise UsitcEdisSourceError(
            f"EDIS download token length must be from {MIN_TOKEN_LENGTH} to {MAX_TOKEN_LENGTH} characters"
        )
    return token


def check_route(route: object) -> str:
    """One named credentialed route, refused before any request."""
    if route not in CREDENTIALED_ROUTES:
        raise UsitcEdisSourceError("EDIS credentialed transport must be direct or zyte")
    return route


def _credential_refusal(url: str, status: int) -> CredentialRefusedError:
    """The typed 401/403 stop; the body is never read into evidence."""
    error = CredentialRefusedError(refusal_message("USITC EDIS", status, "the credentialed attachment download"))
    attach_refused_response(
        error,
        RefusedResponse(
            url, "source-validation", None, "application/octet-stream", "credential-refusal-body-suppressed"
        ),
    )
    return error


def _checked_capture(capture: CapturedBodyResponse, *, token: str) -> CapturedBodyResponse:
    """Refuse denied credentials, reflected tokens and walls before retaining any body."""
    if capture.status_code in ACCESS_REFUSED_STATUSES:
        raise _credential_refusal(capture.requested_url, capture.status_code)
    refuse_reflected_credential(
        capture.body,
        secrets=(token,),
        metadata=(capture.requested_url, capture.resolved_url, capture.content_type or ""),
        error_type=UsitcEdisSourceError,
        message="USITC EDIS credentialed download answered with a reflected credential; capture was not retained",
    )
    marker = detect_wall(capture.body)
    if marker is not None:
        error = UsitcEdisSourceError(f"USITC EDIS credentialed download answered a wall page ({marker!r})")
    elif capture.status_code not in (200, 404, 410):
        error = UsitcEdisSourceError(f"USITC EDIS credentialed download answered HTTP {capture.status_code}")
    else:
        return capture
    attach_capture(error, capture)
    attach_refused_response(error, refused_capture(capture, stage="source-validation"))
    raise error


def _direct_download(
    url: str,
    *,
    token: str,
    max_bytes: int,
    timeout_seconds: float,
    before_request: Callable[[], None],
    clock: Callable[[], datetime],
) -> CapturedBodyResponse:
    """One shared-client GET; credential refusals never read or retain a body."""
    from spicy_docs.transport.capture import BoundedHttpCapture

    client = BoundedHttpCapture(
        max_requests=1,
        timeout_seconds=timeout_seconds,
        min_request_interval_seconds=0,
        user_agent=USER_AGENT,
        error_type=UsitcEdisSourceError,
        transport=None,
        clock=clock,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/pdf"},
        retain_refusal_bodies=False,
    )
    try:
        before_request()
        try:
            capture = client.capture(url, max_bytes=max_bytes, allow_unavailable=True)
        except (ValueError, ConnectionError, RetryableHTTPStatusError) as error:
            failure = error
        else:
            return _checked_capture(capture, token=token)
    finally:
        client.close()
    # Outside the handler, so no refusal below chains to the failure, whose
    # capture may reflect the token. The shared client's messages are a fixed
    # vocabulary that never copies transport text; scrubbing stays a backstop.
    found = attached_capture(failure)
    if found is not None:
        _checked_capture(found, token=token)
    wrapped = UsitcEdisSourceError(
        "USITC EDIS credentialed download could not be captured: " + scrub_credential(str(failure), token)
    )
    if found is not None:
        attach_capture(wrapped, found)
    refused = getattr(failure, "refused_response", None)
    # Retained bytes can only be the vetted capture's; bytes without one are never carried.
    if refused is not None and (refused.response_bytes is None or found is not None):
        attach_refused_response(wrapped, refused)
    raise wrapped


def _zyte_download(
    url: str,
    *,
    token: str,
    max_bytes: int,
    timeout_seconds: float,
    before_request: Callable[[], None],
    clock: Callable[[], datetime],
) -> CapturedBodyResponse:
    """One shared Zyte call carrying the bearer header; the target's 401/403 decides before any body check."""
    before_request()
    bearer = f"Bearer {token}"
    try:
        response = ZyteHttpFetcher.from_environment().fetch(
            url,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            target_headers=(("Authorization", bearer),),
            extra_secrets=(token, bearer),
        )
    except ZyteTransportError as error:
        failure = error
    else:
        capture = CapturedBodyResponse(
            requested_url=url,
            resolved_url=response.resolved_url,
            status_code=response.status_code,
            content_type=response.content_type,
            observed_at=observed_instant(clock),
            body=response.body,
        )
        return _checked_capture(capture, token=token)
    if failure.target_status in ACCESS_REFUSED_STATUSES:
        raise _credential_refusal(url, failure.target_status)
    # The shared adapter's messages never repeat a credential and never chain provider text.
    wrapped = UsitcEdisSourceError(f"USITC EDIS credentialed download could not be captured: {failure}")
    refused = getattr(failure, "refused_response", None)
    if refused is not None:
        attach_refused_response(wrapped, refused)
    raise wrapped


def credentialed_download(
    url: str,
    *,
    token: str,
    max_bytes: int,
    timeout_seconds: float,
    route: str = "direct",
    before_request: Callable[[], None] = lambda: None,
    clock: Callable[[], datetime] = utc_now,
) -> CapturedBodyResponse:
    """One request carrying ``Authorization: Bearer <token>`` over the selected route.

    Returns the exact target answer, stamped by ``clock``, for the acquirer's
    PDF proof. A non-credential wall raises :class:`UsitcEdisSourceError`
    with its capture; a 401/403 raises :class:`CredentialRefusedError` with
    body retention suppressed. Neither route follows redirects or retries.
    """
    token = validate_edis_token(token)
    download = _direct_download if check_route(route) == "direct" else _zyte_download
    # The bearer header travels to this target, so the locator must be the
    # publisher's own download route before the credential goes anywhere.
    attachment_download_locator(url)
    return download(
        url,
        token=token,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        before_request=before_request,
        clock=clock,
    )


__all__ = [
    "CREDENTIALED_ROUTES",
    "MAX_TOKEN_LENGTH",
    "MIN_TOKEN_LENGTH",
    "check_route",
    "credentialed_download",
    "validate_edis_token",
]
