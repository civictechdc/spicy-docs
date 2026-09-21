"""Shared keyless probe, request counter and publisher constants for the analysis tools.

``bill_html_xml_gap`` and ``legislative_data_map`` both probe keyless publisher
routes with the same bounded client and read the same constants, so the probe
and its vocabulary live here rather than in either tool.
"""

from __future__ import annotations

from collections import Counter

from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import SourceAcquirer

CONGRESS_API = "https://api.congress.gov/v3"
GOVINFO_BULK = "https://www.govinfo.gov/bulkdata/json"
JSON_TYPES = ("application/json",)

#: One counter per process; the probe and every reader family share it.
REQUESTS: Counter[str] = Counter()


class ProbeError(ValueError):
    """A keyless probe refused: wrong media type, too large, or unreadable."""


class ProbeUnavailableError(ProbeError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"HTTP {capture.status_code}")
        self.capture = capture


class KeylessProbe(SourceAcquirer):
    """One bounded keyless GET per call; refusal bodies are retained like any keyless family."""

    def __init__(self, *, timeout_seconds: float, min_request_interval_seconds: float) -> None:
        super().__init__(
            max_requests=2,
            timeout_seconds=timeout_seconds,
            min_request_interval_seconds=min_request_interval_seconds,
            user_agent="spicy-docs-legislative-data-map/1.0",
            label="probe",
            error_type=ProbeError,
            context_key="probe",
            keyless=True,
        )

    def get(
        self, url: str, *, media_types: tuple[str, ...], max_bytes: int, accept: str | None = None
    ) -> CapturedBodyResponse:
        REQUESTS["keyless"] += 1
        _, capture = self.capture_validated(
            url,
            media_types=media_types,
            parse=lambda capture, _limit: capture,
            max_bytes=max_bytes,
            unavailable=ProbeUnavailableError,
            context={"operation": "probe", "url": url},
            request_headers={"Accept": accept} if accept else None,
        )
        return capture


def local_name(tag: str) -> str:
    """An XML element or attribute name without its namespace; the same rule both tools apply."""
    return tag.rsplit("}", 1)[-1]
