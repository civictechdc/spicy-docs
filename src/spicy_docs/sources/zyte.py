"""Bounded, secret-safe raw HTTP capture through Zyte.

Why this lives here: some public publishers, including GAO, refuse ordinary
direct clients while allowing browser-backed acquisition.  The transport is
source acquisition, not vocabulary meaning, so SpicyDocs owns its copy instead
of importing a sibling product at runtime. The rigor shared with the other
provider clients lives in :mod:`spicy_docs.transport.provider_api`.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from spicy_docs.transport.provider_api import (
    PROVIDER_ERROR_BYTES,
    absolute_public_http_url,
    read_provider_payload,
    refuse_oversized_target,
    refuse_reflected_credential,
    require_provider_credential,
    strict_provider_json,
    validate_provider_api_url,
    validate_provider_credential,
)

ZYTE_API_URL: Final = "https://api.zyte.com/v1/extract"
ZYTE_TOKEN_ENV: Final = "ZYTE_TOKEN"
#: Zyte returns the publisher's own response bytes.
HTTP_RESPONSE_BODY: Final = "httpResponseBody"
#: Zyte returns its browser's serialized DOM, which is a rendering, not the
#: publisher's bytes. Kept distinct because the two are different evidence.
BROWSER_HTML: Final = "browserHtml"
MODES: Final = (HTTP_RESPONSE_BODY, BROWSER_HTML)
_PROVIDER: Final = "Zyte"


class ZyteTransportError(ValueError):
    """Zyte could not return one exact, bounded target response.

    ``target_status`` is the target's own status when the provider stated one
    before the failure, so a caller can let a 401/403 decide before any body check.
    """

    target_status: int | None = None


def validate_zyte_token(token: str) -> str:
    """Validate without ever including the credential in an error."""
    return validate_provider_credential(token, name=ZYTE_TOKEN_ENV, error_type=ZyteTransportError)


def require_zyte_token_from_environment() -> str:
    """Read only the named credential; never discover or parse dotenv files."""
    return require_provider_credential(ZYTE_TOKEN_ENV, error_type=ZyteTransportError)


@dataclass(frozen=True, slots=True)
class ZyteHttpResponse:
    """Target bytes and public target response metadata, with how they were obtained.

    ``mode`` is what the proxy was asked for and therefore what the body *is*:
    ``httpResponseBody`` is the publisher's own bytes as Zyte's client received
    them; ``browserHtml`` is Zyte's browser's serialized DOM, which no publisher
    ever sent. ``request_id`` is the provider's own handle on this fetch, for a
    receipt; it is never a credential.
    """

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes
    mode: str = HTTP_RESPONSE_BODY
    request_id: str | None = None


def _content_type_from_headers(value: object) -> str | None:
    if not isinstance(value, list):
        raise ZyteTransportError("Zyte response omitted httpResponseHeaders")
    content_types: list[str] = []
    for ordinal, header in enumerate(value):
        if not isinstance(header, dict):
            raise ZyteTransportError(f"Zyte response header {ordinal} must be an object")
        name = header.get("name")
        item_value = header.get("value")
        if not isinstance(name, str) or not isinstance(item_value, str):
            raise ZyteTransportError(f"Zyte response header {ordinal} must contain string name and value")
        if name.casefold() == "content-type":
            content_types.append(item_value.strip())
    if len(content_types) > 1:
        raise ZyteTransportError("Zyte target response repeats Content-Type")
    if content_types and not content_types[0]:
        raise ZyteTransportError("Zyte target Content-Type must not be empty")
    return content_types[0] if content_types else None


#: Zyte's own error slugs are a closed vocabulary (``/download/temporary-error``
#: and the like). Only this shape is ever copied out of a provider error body:
#: a slug says whether the target was banned, unreachable or refused, which a
#: bare status code cannot, while free provider prose is never recorded.
_PROVIDER_ERROR_TYPE = re.compile(r'"type"\s*:\s*"(/[a-z0-9/_-]{1,64})"')


def _provider_error_kind(error: urllib.error.HTTPError, secrets: tuple[str, ...]) -> str:
    """The provider's own error slug, for a receipt; never its prose and never a credential."""
    try:
        payload = error.read(PROVIDER_ERROR_BYTES)
    except (OSError, ValueError):
        return ""
    finally:
        error.close()
    match = _PROVIDER_ERROR_TYPE.search(payload.decode("utf-8", "replace"))
    if match is None or any(secret in match[1] for secret in secrets):
        return ""
    return f" ({match[1]})"


def _request_id_from_provider_headers(headers: Any) -> str | None:
    """The provider's own handle on this fetch, for a receipt.

    Zyte has spelled it more than one way, so the name is matched rather than
    guessed, and a response that states none reads as ``None`` -- an absent id
    is recorded as absent, never fabricated.
    """

    try:
        items = list(headers.items())
    except AttributeError:
        return None
    for name, value in items:
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        folded = name.casefold()
        if "request-id" in folded or folded == "x-amzn-requestid":
            stripped = value.strip()
            if stripped:
                return stripped
    return None


@dataclass(frozen=True, slots=True)
class ZyteHttpFetcher:
    """Fetch exact target bytes in O(P + B) time and O(P + B) space.

    ``P`` is the bounded provider JSON and ``B`` is the caller-bounded target
    body.  Base64 requires both forms briefly, so this is deliberately a
    single-document adapter rather than a corpus accumulator.
    """

    token: str = field(repr=False)
    api_url: str = ZYTE_API_URL

    def __post_init__(self) -> None:
        validate_zyte_token(self.token)
        validate_provider_api_url(self.api_url, provider=_PROVIDER, error_type=ZyteTransportError)

    @classmethod
    def from_environment(cls) -> ZyteHttpFetcher:
        return cls(token=require_zyte_token_from_environment())

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
        mode: str = HTTP_RESPONSE_BODY,
        target_headers: Sequence[tuple[str, str]] = (),
        extra_secrets: Sequence[str] = (),
    ) -> ZyteHttpResponse:
        """One provider call, no retry and no second URL; ``mode`` states what the body is.

        ``target_headers`` travel to the target (``httpResponseBody`` only).
        ``extra_secrets`` join this fetcher's own credential: none is ever
        repeated in an error, and a response reflecting one is not retained.
        """
        if timeout_seconds <= 0:
            raise ZyteTransportError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ZyteTransportError("max_bytes must be positive")
        if mode not in MODES:
            raise ZyteTransportError(f"Zyte mode must be one of {MODES}")
        if target_headers and mode != HTTP_RESPONSE_BODY:
            raise ZyteTransportError("Zyte target headers need httpResponseBody mode")
        if any(
            not isinstance(part, str) or not part or any(character in part for character in "\r\n\0")
            for header in target_headers
            for part in header
        ) or any(not isinstance(secret, str) or not secret for secret in extra_secrets):
            raise ZyteTransportError("Zyte target headers and secrets must be nonempty single-line strings")
        absolute_public_http_url(url, label="target URL", error_type=ZyteTransportError)
        request_fields: dict[str, Any] = {"url": url}
        if mode == HTTP_RESPONSE_BODY:
            request_fields["httpResponseBody"] = True
            request_fields["httpResponseHeaders"] = True
        else:
            request_fields["browserHtml"] = True
        if target_headers:
            request_fields["customHttpRequestHeaders"] = [
                {"name": name, "value": value} for name, value in target_headers
            ]
        request_payload = json.dumps(
            request_fields,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        basic = base64.b64encode(f"{self.token}:".encode("iso-8859-1")).decode("ascii")
        secrets = (self.token, basic, *extra_secrets)
        request = urllib.request.Request(
            self.api_url,
            data=request_payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                "User-Agent": "SpicyDocs bounded raw capture/1.0",
            },
            method="POST",
        )
        # Provider and socket errors can carry request text; none is chained or copied.
        try:
            response = urllib.request.urlopen(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as error:
            kind = _provider_error_kind(error, secrets)
            raise ZyteTransportError(f"Zyte acquisition failed with HTTP {error.code}{kind}") from None
        except (OSError, urllib.error.URLError):
            raise ZyteTransportError("Zyte acquisition failed before receiving a response") from None
        try:
            with response:
                provider_payload = read_provider_payload(
                    response, max_bytes=max_bytes, provider=_PROVIDER, error_type=ZyteTransportError
                )
                request_id = _request_id_from_provider_headers(response.headers)
        except OSError:
            raise ZyteTransportError("Zyte acquisition failed while reading the provider response") from None

        value = strict_provider_json(provider_payload, provider=_PROVIDER, error_type=ZyteTransportError)
        target_status = value.get("statusCode")
        if not isinstance(target_status, int) or isinstance(target_status, bool):
            raise ZyteTransportError("Zyte response omitted target statusCode")
        try:
            resolved_url, content_type, body = _target_answer(
                value, url=url, mode=mode, max_bytes=max_bytes, secrets=secrets, request_id=request_id
            )
        except ZyteTransportError as error:
            error.target_status = target_status
            raise
        return ZyteHttpResponse(
            requested_url=url,
            resolved_url=resolved_url,
            status_code=target_status,
            content_type=content_type,
            body=body,
            mode=mode,
            request_id=request_id,
        )


def _target_answer(
    value: dict[str, Any],
    *,
    url: str,
    mode: str,
    max_bytes: int,
    secrets: tuple[str, ...],
    request_id: str | None,
) -> tuple[str, str | None, bytes]:
    """The target's final URL, media type and exact bytes, refused when unproven, reflected or over bound."""
    # A final URL the provider did not state is unproven; defaulting it to the
    # requested URL would make every caller's final-URL check agree with itself.
    resolved_url = value.get("url")
    if not isinstance(resolved_url, str):
        raise ZyteTransportError("Zyte response omitted the target's final URL")
    absolute_public_http_url(resolved_url, label="resolved target URL", error_type=ZyteTransportError)
    if mode == HTTP_RESPONSE_BODY:
        encoded_body = value.get("httpResponseBody")
        if not isinstance(encoded_body, str):
            raise ZyteTransportError("Zyte response omitted httpResponseBody")
        content_type = _content_type_from_headers(value.get("httpResponseHeaders"))
        try:
            body = base64.b64decode(encoded_body, validate=True)
        except (ValueError, binascii.Error):
            raise ZyteTransportError("Zyte returned invalid base64 target bytes") from None
    else:
        rendered = value.get("browserHtml")
        if not isinstance(rendered, str):
            raise ZyteTransportError("Zyte response omitted browserHtml")
        # No Content-Type is stated, and inventing one would describe a
        # rendered DOM as a publisher's declared media type.
        content_type = None
        body = rendered.encode("utf-8")
    refuse_reflected_credential(
        body,
        secrets=secrets,
        metadata=(url, resolved_url, content_type or "", request_id or ""),
        error_type=ZyteTransportError,
        message="Zyte target response contains a reflected transport credential",
    )
    refuse_oversized_target(body, url=url, max_bytes=max_bytes, provider=_PROVIDER, error_type=ZyteTransportError)
    return resolved_url, content_type, body


__all__ = [
    "BROWSER_HTML",
    "HTTP_RESPONSE_BODY",
    "MODES",
    "ZYTE_API_URL",
    "ZYTE_TOKEN_ENV",
    "ZyteHttpFetcher",
    "ZyteHttpResponse",
    "ZyteTransportError",
    "require_zyte_token_from_environment",
    "validate_zyte_token",
]
