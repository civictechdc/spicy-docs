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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Final

from spicy_docs.sources.refusals import RefusedResponse, attach_refused_response

ZYTE_API_URL: Final = "https://api.zyte.com/v1/extract"
ZYTE_TOKEN_ENV: Final = "ZYTE_TOKEN"
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
    """Exact target bytes and public target response metadata."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes


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
    ) -> ZyteHttpResponse:
        if timeout_seconds <= 0:
            raise ZyteTransportError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ZyteTransportError("max_bytes must be positive")
        _absolute_public_http_url(url, label="target URL")
        request_payload = json.dumps(
            {
                "httpResponseBody": True,
                "httpResponseHeaders": True,
                "url": url,
            },
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
            raise ZyteTransportError(f"Zyte acquisition failed with HTTP {error.code}") from error
        except (OSError, urllib.error.URLError) as error:
            raise ZyteTransportError("Zyte acquisition failed before receiving a response") from error
        with response:
            provider_payload = response.read(provider_max_bytes + 1)
        if len(provider_payload) > provider_max_bytes:
            raise ZyteTransportError("Zyte response exceeded the bounded provider payload size")

        value = _provider_json(provider_payload)
        encoded_body = value.get("httpResponseBody")
        target_status = value.get("statusCode")
        resolved_url = value.get("url", url)
        if not isinstance(encoded_body, str):
            raise ZyteTransportError("Zyte response omitted httpResponseBody")
        if not isinstance(target_status, int) or isinstance(target_status, bool):
            raise ZyteTransportError("Zyte response omitted target statusCode")
        if not isinstance(resolved_url, str):
            raise ZyteTransportError("Zyte response returned an invalid target URL")
        _absolute_public_http_url(resolved_url, label="resolved target URL")
        content_type = _content_type_from_headers(value.get("httpResponseHeaders"))
        try:
            body = base64.b64decode(encoded_body, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ZyteTransportError("Zyte returned invalid base64 target bytes") from error
        # Retained evidence must be exact. Suppress a reflected credential at
        # the transport that knows it, rather than redacting publisher bytes
        # and later describing them as an exact capture.
        public_metadata = (url, resolved_url, content_type or "")
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
        )


__all__ = [
    "ZYTE_API_URL",
    "ZYTE_TOKEN_ENV",
    "ZyteHttpFetcher",
    "ZyteHttpResponse",
    "ZyteTransportError",
    "require_zyte_token_from_environment",
    "validate_zyte_token",
]
