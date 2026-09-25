"""Rules shared by the credentialed acquisition-provider clients (Zyte, Firecrawl).

A provider client sends one POST carrying the target URL, reads the provider's
JSON envelope and returns the target's exact bytes. The rigor around that call
was written once in :mod:`spicy_docs.sources.zyte` and then copied into
:mod:`spicy_docs.sources.firecrawl`; it lives here so every client applies the
same checks. The provider-specific request fields, response fields and error
vocabularies stay with each client. Every helper raises the caller's own error
type, and every message names the provider or credential but never the value.

Standard library only: the clients use ``urllib`` so they need no optional extra.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from collections.abc import Iterable, Iterator
from typing import Any, Final, Protocol

from spicy_docs.reading.refusals import RefusedResponse, attach_refused_response

#: A provider envelope holds the target body Base64-encoded (4/3 of its size)
#: plus metadata, so its read bound is twice the target bound plus this
#: overhead, and never below one MiB.
MIN_PROVIDER_BYTES: Final = 1024 * 1024
PROVIDER_OVERHEAD_BYTES: Final = 64 * 1024
#: How much of a provider error body is read to find its closed-vocabulary slug.
PROVIDER_ERROR_BYTES: Final = 4096
#: Encodings a reflected credential is looked for in, besides the metadata strings.
_REFLECTION_ENCODINGS: Final = ("utf-8", "iso-8859-1")


class _Readable(Protocol):
    def read(self, amount: int, /) -> bytes: ...


def validate_provider_credential(value: str, *, name: str, error_type: type[Exception]) -> str:
    """Accept one provider credential as sent, naming ``name`` but never the value in a refusal."""
    stripped = value.strip()
    if not stripped:
        raise error_type(f"{name} must not be empty")
    if stripped != value:
        raise error_type(f"{name} must not contain surrounding whitespace")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        raise error_type(f"{name} must not include dotenv quote characters")
    # A code-point test, not an encode attempt: the codec's error would carry the credential itself.
    if any(ord(character) > 0xFF for character in value):
        raise error_type(f"{name} contains unsupported credential characters")
    return value


def require_provider_credential(name: str, *, error_type: type[Exception]) -> str:
    """Read only the named environment variable; never discover or parse dotenv files."""
    value = os.environ.get(name)
    if value is None:
        raise error_type(f"{name} is required for live acquisition")
    return validate_provider_credential(value, name=name, error_type=error_type)


def absolute_public_http_url(value: str, *, label: str, error_type: type[Exception]) -> str:
    """An absolute HTTP(S) URL with no userinfo, or a refusal naming ``label``."""
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise error_type(f"{label} must be an absolute credential-free HTTP(S) URL")
    return value


def validate_provider_api_url(value: str, *, provider: str, error_type: type[Exception]) -> str:
    """The provider endpoint: HTTPS, no userinfo, no query and no fragment, so no secret can ride in it."""
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise error_type(f"{provider} API URL must be an absolute credential-free HTTPS URL")
    return value


class _RepeatedField(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _RepeatedField(key)
        result[key] = value
    return result


def strict_provider_json(payload: bytes, *, provider: str, error_type: type[Exception]) -> dict[str, Any]:
    """The provider envelope as a JSON object; a repeated field is refused, never resolved last-wins.

    Every refusal is raised outside the parser's handler: its exception holds
    the whole payload, which can echo a credential, so no refusal chains to it.
    """
    try:
        value = json.loads(payload, object_pairs_hook=_closed_pairs)
    except _RepeatedField as repeated:
        failure = f"{provider} response repeats field {repeated.key!r}"
    except (UnicodeDecodeError, json.JSONDecodeError):
        failure = f"{provider} returned an invalid JSON response"
    else:
        if isinstance(value, dict):
            return value
        failure = f"{provider} response must be a JSON object"
    raise error_type(failure)


def provider_payload_limit(max_bytes: int) -> int:
    """The largest provider envelope accepted for a target bound of ``max_bytes``."""
    return max(MIN_PROVIDER_BYTES, max_bytes * 2 + PROVIDER_OVERHEAD_BYTES)


def read_provider_payload(response: _Readable, *, max_bytes: int, provider: str, error_type: type[Exception]) -> bytes:
    """Read the whole envelope within its bound; one byte past the bound refuses rather than truncates."""
    limit = provider_payload_limit(max_bytes)
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise error_type(f"{provider} response exceeded the bounded provider payload size")
    return payload


def _encoded(secrets: Iterable[str]) -> Iterator[bytes]:
    for secret in secrets:
        for encoding in _REFLECTION_ENCODINGS:
            try:
                yield secret.encode(encoding)
            except UnicodeEncodeError:
                continue


def refuse_reflected_credential(
    body: bytes,
    *,
    secrets: Iterable[str],
    metadata: Iterable[str],
    error_type: type[Exception],
    message: str,
) -> None:
    """Refuse a capture that echoes a transport credential, retaining no bytes.

    Retained evidence must be exact, so the transport that knows the
    credential suppresses the whole capture. It never redacts publisher bytes
    and then calls them exact. The refusal records only the observed size.
    """
    present = tuple(secret for secret in secrets if secret)
    reflected = any(secret in item for secret in present for item in metadata) or any(
        encoded in body for encoded in _encoded(present)
    )
    if not reflected:
        return
    error = error_type(message)
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


def refuse_oversized_target(
    body: bytes, *, url: str, max_bytes: int, provider: str, error_type: type[Exception]
) -> None:
    """Refuse target bytes over the caller's bound, recording the observed size but none of the bytes."""
    if len(body) <= max_bytes:
        return
    error = error_type(f"{provider} target response exceeds max_bytes={max_bytes}")
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


__all__ = [
    "MIN_PROVIDER_BYTES",
    "PROVIDER_ERROR_BYTES",
    "PROVIDER_OVERHEAD_BYTES",
    "absolute_public_http_url",
    "provider_payload_limit",
    "read_provider_payload",
    "refuse_oversized_target",
    "refuse_reflected_credential",
    "require_provider_credential",
    "strict_provider_json",
    "validate_provider_api_url",
    "validate_provider_credential",
]
