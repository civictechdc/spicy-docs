"""CFR identity scans bind the shared bounded scanner to CFR refusals and limits."""

from __future__ import annotations

from ..xml import IdentityXmlScan as _IdentityXmlScan
from .models import CfrSourceError, _limit


class IdentityXmlScan(_IdentityXmlScan):
    def __init__(self, fields: set[tuple[str, ...]]) -> None:
        super().__init__(fields, error_type=CfrSourceError, label="CFR XML")

    def read(self, body: bytes, max_bytes: int) -> None:
        _limit(max_bytes)
        super().read(body, max_bytes)
