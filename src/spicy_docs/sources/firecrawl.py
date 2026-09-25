"""Bounded, secret-safe raw HTTP capture through Firecrawl's v2 scrape endpoint.

Why this lives here: the same walled publishers that refuse ordinary direct
clients (see :mod:`spicy_docs.sources.zyte`) may answer Firecrawl's own
acquisition fleet, and ``rawBase64`` returns the publisher's original HTTP
response bytes for any content type when PDF parsing is disabled
(``parsers: []``). The transport is source acquisition, not vocabulary
meaning, so SpicyDocs owns its copy instead of importing a sibling product at
runtime. It applies the same rigor as :mod:`spicy_docs.sources.zyte`
through :mod:`spicy_docs.transport.provider_api`: credential validation that
never leaks the value, a bounded provider payload, reflected-credential
suppression and typed errors. The closed provider-error vocabulary and the
dataclass response stay here.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import urllib.error
import urllib.request
import uuid
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

FIRECRAWL_API_URL: Final = "https://api.firecrawl.dev/v2/scrape"
FIRECRAWL_API_KEY_ENV: Final = "FIRECRAWL_API_KEY"
#: Firecrawl returns the publisher's own response bytes, Base64-encoded, for
#: any content type; ``parsers: []`` disables PDF parsing so a PDF comes back
#: as raw bytes rather than extracted markdown.
RAW_BASE64: Final = "rawBase64"
#: Firecrawl returns the exact, unmodified HTML its client received.
RAW_HTML: Final = "rawHtml"
MODES: Final = (RAW_BASE64, RAW_HTML)
#: Firecrawl's own timeout floor and ceiling, in seconds (its ``timeout``
#: request field is milliseconds with minimum 1000 and maximum 300000).
MIN_TIMEOUT_SECONDS: Final = 1.0
MAX_TIMEOUT_SECONDS: Final = 300.0
_PROVIDER: Final = "Firecrawl"
#: Firecrawl's own error slugs are a closed vocabulary. The ``code`` field is
#: already one (``insufficient_credits``, ``UNKNOWN_ERROR`` and the like); the
#: one engine-failure wording the API states without a code is pinned beside
#: it, quoted from the live 2026-09-24 capture. Only these shapes are ever
#: copied out of a provider error body: free provider prose is never recorded.
_CODE_SLUG = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_KNOWN_ERROR_WORDINGS: Final = {"All scraping engines failed": "all_scraping_engines_failed"}


class FirecrawlTransportError(ValueError):
    """Firecrawl could not return one exact, bounded target response."""


def validate_firecrawl_api_key(key: str) -> str:
    """Validate without ever including the credential in an error."""
    return validate_provider_credential(key, name=FIRECRAWL_API_KEY_ENV, error_type=FirecrawlTransportError)


def require_firecrawl_api_key_from_environment() -> str:
    """Read only the named credential; never discover or parse dotenv files."""
    return require_provider_credential(FIRECRAWL_API_KEY_ENV, error_type=FirecrawlTransportError)


def _loose_provider_json(payload: bytes) -> dict[str, Any] | None:
    """A tolerant parse of the provider's error body; only slugs are ever copied out of it."""

    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _provider_error_slug(value: dict[str, Any] | None) -> str:
    """The provider's own error slug, for a receipt; never its prose and never a credential."""

    if value is None:
        return ""
    code = value.get("code")
    if isinstance(code, str) and _CODE_SLUG.match(code):
        return f" ({code})"
    error = value.get("error")
    if isinstance(error, str):
        for wording, slug in _KNOWN_ERROR_WORDINGS.items():
            if wording in error:
                return f" ({slug})"
    return ""


@dataclass(frozen=True, slots=True)
class FirecrawlResponse:
    """Target bytes and public target response metadata, with how they were obtained.

    ``mode`` is what the provider was asked for and therefore what the body
    *is*: ``rawBase64`` is the publisher's original HTTP response bytes (any
    content type, PDF parsing disabled); ``rawHtml`` is the unmodified HTML
    Firecrawl's client received, which the publisher did send. ``request_id``
    is the ``x-request-id`` this client generated for the call, so a receipt
    can correlate with the provider's logs; it is never a credential.
    """

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes
    mode: str = RAW_BASE64
    request_id: str | None = None


def _content_type_from_metadata(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("contentType")
    if value is None:
        return None
    if not isinstance(value, str):
        raise FirecrawlTransportError("Firecrawl response returned an invalid target Content-Type")
    stripped = value.strip()
    if not stripped:
        raise FirecrawlTransportError("Firecrawl target Content-Type must not be empty")
    return stripped


@dataclass(frozen=True, slots=True)
class FirecrawlFetcher:
    """Fetch exact target bytes in O(P + B) time and O(P + B) space.

    ``P`` is the bounded provider JSON and ``B`` is the caller-bounded target
    body.  Base64 requires both forms briefly, so this is deliberately a
    single-document adapter rather than a corpus accumulator.
    """

    key: str = field(repr=False)
    api_url: str = FIRECRAWL_API_URL

    def __post_init__(self) -> None:
        validate_firecrawl_api_key(self.key)
        validate_provider_api_url(self.api_url, provider=_PROVIDER, error_type=FirecrawlTransportError)

    @classmethod
    def from_environment(cls) -> FirecrawlFetcher:
        return cls(key=require_firecrawl_api_key_from_environment())

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
        mode: str = RAW_BASE64,
    ) -> FirecrawlResponse:
        """One provider call, no retry and no second URL; ``mode`` states what the body is.

        The provider's ``metadata.url`` is the only statement of where the
        target resolved. A response that omits it is refused rather than
        defaulted to the requested URL: every caller's redirect gate compares
        the two, and a default would make that comparison agree with itself.
        """
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise FirecrawlTransportError("timeout_seconds must be a number")
        if not math.isfinite(timeout_seconds):
            raise FirecrawlTransportError("timeout_seconds must be finite")
        if not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise FirecrawlTransportError(
                f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g} seconds "
                "(Firecrawl's own request-timeout bounds)"
            )
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise FirecrawlTransportError("max_bytes must be a positive integer")
        if mode not in MODES:
            raise FirecrawlTransportError(f"Firecrawl mode must be one of {MODES}")
        absolute_public_http_url(url, label="target URL", error_type=FirecrawlTransportError)
        # Generated by this client and recorded on the response so a receipt
        # can correlate a failed call with the provider's logs; it is a fresh
        # uuid, never a credential and never the target's.
        request_id = uuid.uuid4().hex
        request_fields: dict[str, Any] = {
            "url": url,
            "formats": [mode],
            # PDF parsing disabled: a PDF returns as its raw bytes, and an
            # HTML page returns unparsed.
            "parsers": [],
            # Never serve a cached page: evidence is for the URL as of the request.
            "maxAge": 0,
            "timeout": int(timeout_seconds * 1000),
            "storeInCache": False,
        }
        request_payload = json.dumps(request_fields, separators=(",", ":"), sort_keys=True).encode()
        request = urllib.request.Request(
            self.api_url,
            data=request_payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "User-Agent": "SpicyDocs bounded raw capture/1.0",
                "x-request-id": request_id,
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as error:
            try:
                payload = error.read(PROVIDER_ERROR_BYTES)
            except (OSError, ValueError):
                payload = b""
            raise FirecrawlTransportError(
                f"Firecrawl acquisition failed with HTTP {error.code}"
                f"{_provider_error_slug(_loose_provider_json(payload))}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise FirecrawlTransportError("Firecrawl acquisition failed before receiving a response") from error
        with response:
            provider_payload = read_provider_payload(
                response, max_bytes=max_bytes, provider=_PROVIDER, error_type=FirecrawlTransportError
            )

        value = strict_provider_json(provider_payload, provider=_PROVIDER, error_type=FirecrawlTransportError)
        success = value.get("success")
        if not isinstance(success, bool):
            raise FirecrawlTransportError("Firecrawl response omitted success")
        if success is False:
            # HTTP 200 with success:false is the engines-failed shape; the
            # known wording is folded to its canonical slug, nothing else is copied.
            raise FirecrawlTransportError(
                "Firecrawl acquisition failed: provider reported failure" + _provider_error_slug(value)
            )
        data = value.get("data")
        if not isinstance(data, dict):
            raise FirecrawlTransportError("Firecrawl response omitted data")
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            raise FirecrawlTransportError("Firecrawl response omitted metadata")
        target_status = metadata.get("statusCode")
        if not isinstance(target_status, int) or isinstance(target_status, bool):
            raise FirecrawlTransportError("Firecrawl response omitted target statusCode")
        if "url" not in metadata:
            raise FirecrawlTransportError("Firecrawl response omitted the resolved target URL (metadata.url)")
        resolved_url = metadata["url"]
        if not isinstance(resolved_url, str):
            raise FirecrawlTransportError("Firecrawl response returned an invalid target URL")
        absolute_public_http_url(resolved_url, label="resolved target URL", error_type=FirecrawlTransportError)
        content_type = _content_type_from_metadata(metadata)
        if mode == RAW_BASE64:
            encoded_body = data.get(RAW_BASE64)
            if not isinstance(encoded_body, str):
                raise FirecrawlTransportError("Firecrawl response omitted rawBase64")
            try:
                body = base64.b64decode(encoded_body, validate=True)
            except (ValueError, binascii.Error) as error:
                raise FirecrawlTransportError("Firecrawl returned invalid base64 target bytes") from error
        else:
            rendered = data.get(RAW_HTML)
            if not isinstance(rendered, str):
                raise FirecrawlTransportError("Firecrawl response omitted rawHtml")
            # rawHtml is the unmodified HTML the publisher sent, so its stated
            # Content-Type travels with it (unlike a rendered DOM, which no
            # publisher ever sent).
            body = rendered.encode("utf-8")
        refuse_reflected_credential(
            body,
            secrets=(self.key, f"Bearer {self.key}"),
            metadata=(url, resolved_url, content_type or "", request_id),
            error_type=FirecrawlTransportError,
            message="Firecrawl target response contains a reflected transport credential",
        )
        refuse_oversized_target(
            body, url=url, max_bytes=max_bytes, provider=_PROVIDER, error_type=FirecrawlTransportError
        )
        return FirecrawlResponse(
            requested_url=url,
            resolved_url=resolved_url,
            status_code=target_status,
            content_type=content_type,
            body=body,
            mode=mode,
            request_id=request_id,
        )


__all__ = [
    "FIRECRAWL_API_KEY_ENV",
    "FIRECRAWL_API_URL",
    "MAX_TIMEOUT_SECONDS",
    "MIN_TIMEOUT_SECONDS",
    "MODES",
    "RAW_BASE64",
    "RAW_HTML",
    "FirecrawlFetcher",
    "FirecrawlResponse",
    "FirecrawlTransportError",
    "require_firecrawl_api_key_from_environment",
    "validate_firecrawl_api_key",
]
