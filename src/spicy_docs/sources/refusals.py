"""Carry exact refused response bytes to the caller without changing the error.

Source adapters attach only bounded publisher response bodies and safe request
identifiers. Transport credentials, provider responses, and request headers do
not belong here. ``None`` means unavailable; ``b""`` is an exact empty response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RefusedResponse:
    request_key: str
    stage: str
    response_bytes: bytes | None = field(repr=False)
    media_type: str
    unavailable_reason: str | None = None
    observed_byte_size: int | None = None


def attach_refused_response(error: Exception, response: RefusedResponse) -> None:
    """Preserve the error and any more precise context attached by its origin."""
    if not isinstance(getattr(error, "refused_response", None), RefusedResponse):
        error.__dict__["refused_response"] = response


def retain_refused_response(error: Exception, *, store: Path, max_bytes: int, credential: str = "") -> dict | None:
    """Keep bounded source-validation evidence when parsing fails before storage."""
    from rulespec_artifacts import LocalBlobWriter

    from spicy_docs.transport.credentials import scrub_credential

    response = getattr(error, "refused_response", None)
    if not isinstance(response, RefusedResponse):
        return None
    result = {
        "request_key": scrub_credential(response.request_key, credential),
        "stage": response.stage,
        "media_type": response.media_type,
        "unavailable_reason": response.unavailable_reason,
        "observed_byte_size": response.observed_byte_size,
    }
    if response.response_bytes is not None:
        if credential and credential.encode() in response.response_bytes:
            result["unavailable_reason"] = "credential echoed in response; bytes not retained"
        else:
            written = LocalBlobWriter(store).put([response.response_bytes], max_bytes=max_bytes)
            result.update(sha256=written.digest, bytes=written.byte_size)
    return result
