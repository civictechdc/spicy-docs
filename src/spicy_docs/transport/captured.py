"""The exact captured response and its refusal adapter, importable without an HTTP client.

Validators and readers reference these; only the bounded client in
``capture.py`` needs the optional HTTPX dependency.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from spicy_docs.reading.refusals import RefusedResponse


@dataclass(frozen=True, slots=True)
class CapturedBodyResponse:
    """Exact response payload bytes, before any content decoding, and observed facts."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    observed_at: str
    body: bytes = field(repr=False)
    content_encoding: str = "identity"
    method: str = "GET"
    request_body: bytes | None = field(default=None, repr=False)

    @property
    def byte_size(self) -> int:
        return len(self.body)

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.body).hexdigest()


def refused_capture(capture: CapturedBodyResponse, *, stage: str) -> RefusedResponse:
    return RefusedResponse(
        request_key=capture.requested_url,
        stage=stage,
        response_bytes=capture.body,
        media_type=(capture.content_type or "application/octet-stream").split(";", 1)[0].strip(),
        observed_byte_size=capture.byte_size,
    )
