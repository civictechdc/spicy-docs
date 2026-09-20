"""Bounded, secret-safe raw HTTP capture through Zyte.

Why this lives here: some public publishers, including GAO, refuse ordinary
direct clients while allowing browser-backed acquisition.  The transport is
source acquisition, not vocabulary meaning, so SpicyDocs owns its copy instead
of importing a sibling product at runtime.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Final

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response

ZYTE_API_URL: Final = "https://api.zyte.com/v1/extract"
ZYTE_TOKEN_ENV: Final = "ZYTE_TOKEN"
#: Zyte returns the publisher's own response bytes.
HTTP_RESPONSE_BODY: Final = "httpResponseBody"
#: Zyte returns its browser's serialized DOM, which is a rendering, not the
#: publisher's bytes. Kept distinct because the two are different evidence.
BROWSER_HTML: Final = "browserHtml"
MODES: Final = (HTTP_RESPONSE_BODY, BROWSER_HTML)
_MIN_PROVIDER_BYTES: Final = 1024 * 1024
_PROVIDER_OVERHEAD_BYTES: Final = 64 * 1024


class ZyteTransportError(ValueError):
    """Zyte could not return one exact, bounded target response."""


def validate_zyte_token(token: str) -> str:
    """Validate without ever including the credential in an error."""

    stripped = token.strip()
    if not stripped:
        raise ZyteTransportError("ZYTE_TOKEN must not be empty")
    if stripped != token:
        raise ZyteTransportError("ZYTE_TOKEN must not contain surrounding whitespace")
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        raise ZyteTransportError("ZYTE_TOKEN must not include dotenv quote characters")
    try:
        token.encode("iso-8859-1")
    except UnicodeEncodeError as error:
        raise ZyteTransportError("ZYTE_TOKEN contains unsupported credential characters") from error
    return token


def require_zyte_token_from_environment() -> str:
    """Read only the named credential; never discover or parse dotenv files."""

    token = os.environ.get(ZYTE_TOKEN_ENV)
    if token is None:
        raise ZyteTransportError(f"{ZYTE_TOKEN_ENV} is required for live acquisition")
    return validate_zyte_token(token)


def _absolute_public_http_url(value: str, *, label: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ZyteTransportError(f"{label} must be an absolute credential-free HTTP(S) URL")
    return value


def _validate_api_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ZyteTransportError("Zyte API URL must be an absolute credential-free HTTPS URL")
    return value


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
_PROVIDER_ERROR_BYTES: Final = 4096


def _provider_error_kind(error: urllib.error.HTTPError) -> str:
    """The provider's own error slug, for a receipt; never its prose and never a credential."""

    try:
        payload = error.read(_PROVIDER_ERROR_BYTES)
    except (OSError, ValueError):
        return ""
    match = _PROVIDER_ERROR_TYPE.search(payload.decode("utf-8", "replace"))
    return f" ({match.group(1)})" if match else ""


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


def _provider_json(payload: bytes) -> dict[str, Any]:
    def closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ZyteTransportError(f"Zyte response repeats field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=closed_pairs)
    except ZyteTransportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ZyteTransportError("Zyte returned an invalid JSON response") from error
    if not isinstance(value, dict):
        raise ZyteTransportError("Zyte response must be a JSON object")
    return value


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
        _validate_api_url(self.api_url)

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
    ) -> ZyteHttpResponse:
        """One provider call, no retry and no second URL; ``mode`` states what the body is."""
        if timeout_seconds <= 0:
            raise ZyteTransportError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ZyteTransportError("max_bytes must be positive")
        if mode not in MODES:
            raise ZyteTransportError(f"Zyte mode must be one of {MODES}")
        _absolute_public_http_url(url, label="target URL")
        request_fields: dict[str, Any] = {"url": url}
        if mode == HTTP_RESPONSE_BODY:
            request_fields["httpResponseBody"] = True
            request_fields["httpResponseHeaders"] = True
        else:
            request_fields["browserHtml"] = True
        request_payload = json.dumps(
            request_fields,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        basic = base64.b64encode(f"{self.token}:".encode("iso-8859-1")).decode("ascii")
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
        provider_max_bytes = max(
            _MIN_PROVIDER_BYTES,
            max_bytes * 2 + _PROVIDER_OVERHEAD_BYTES,
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as error:
            raise ZyteTransportError(
                f"Zyte acquisition failed with HTTP {error.code}{_provider_error_kind(error)}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise ZyteTransportError("Zyte acquisition failed before receiving a response") from error
        with response:
            provider_payload = response.read(provider_max_bytes + 1)
            request_id = _request_id_from_provider_headers(response.headers)
        if len(provider_payload) > provider_max_bytes:
            raise ZyteTransportError("Zyte response exceeded the bounded provider payload size")

        value = _provider_json(provider_payload)
        target_status = value.get("statusCode")
        resolved_url = value.get("url", url)
        if not isinstance(target_status, int) or isinstance(target_status, bool):
            raise ZyteTransportError("Zyte response omitted target statusCode")
        if not isinstance(resolved_url, str):
            raise ZyteTransportError("Zyte response returned an invalid target URL")
        _absolute_public_http_url(resolved_url, label="resolved target URL")
        if mode == HTTP_RESPONSE_BODY:
            encoded_body = value.get("httpResponseBody")
            if not isinstance(encoded_body, str):
                raise ZyteTransportError("Zyte response omitted httpResponseBody")
            content_type = _content_type_from_headers(value.get("httpResponseHeaders"))
            try:
                body = base64.b64decode(encoded_body, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ZyteTransportError("Zyte returned invalid base64 target bytes") from error
        else:
            rendered = value.get("browserHtml")
            if not isinstance(rendered, str):
                raise ZyteTransportError("Zyte response omitted browserHtml")
            # No Content-Type is stated, and inventing one would describe a
            # rendered DOM as a publisher's declared media type.
            content_type = None
            body = rendered.encode("utf-8")
        # Retained evidence must be exact. Suppress a reflected credential at
        # the transport that knows it, rather than redacting publisher bytes
        # and later describing them as an exact capture.
        public_metadata = (url, resolved_url, content_type or "", request_id or "")
        if any(secret in value for secret in (self.token, basic) for value in public_metadata) or any(
            secret.encode(encoding) in body for secret in (self.token, basic) for encoding in ("utf-8", "iso-8859-1")
        ):
            error = ZyteTransportError("Zyte target response contains a reflected transport credential")
            attach_refused_response(
                error,
                RefusedResponse(
                    request_key="[credential-suppressed]",
                    stage="transport",
                    response_bytes=None,
                    media_type="application/octet-stream",
                    unavailable_reason="credential-suppressed",
                    observed_byte_size=len(body),
                ),
            )
            raise error
        if len(body) > max_bytes:
            error = ZyteTransportError(f"Zyte target response exceeds max_bytes={max_bytes}")
            attach_refused_response(
                error,
                RefusedResponse(
                    request_key=url,
                    stage="transport",
                    response_bytes=None,
                    media_type="application/octet-stream",
                    unavailable_reason="response-byte-limit",
                    observed_byte_size=len(body),
                ),
            )
            raise error
        return ZyteHttpResponse(
            requested_url=url,
            resolved_url=resolved_url,
            status_code=target_status,
            content_type=content_type,
            body=body,
            mode=mode,
            request_id=request_id,
        )


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
