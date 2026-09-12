"""Carry exact refused response bytes to the caller without changing the error.

Source adapters attach only bounded publisher response bodies and safe request
identifiers. Transport credentials, provider responses, and request headers do
not belong here. ``None`` means unavailable; ``b""`` is an exact empty response.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
