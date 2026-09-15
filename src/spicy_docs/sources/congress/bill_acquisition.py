"""Capture one bill's status and explicitly selected XML text from GovInfo.

Callers own selection, retention and processing. Each call has its own request
budget; pacing persists across calls. Status links describe available formats,
while a successful text capture proves the selected bill/version's XML shape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.congress.bill_status import (
    BillIdentity,
    BillSourceError,
    BillStatus,
    bill_status_locator,
    parse_bill_status,
)
from spicy_docs.sources.congress.bill_text import (
    BillTextIdentity,
    bill_xml_locator,
    select_bill_xml,
    validate_bill_text,
)
from spicy_docs.transport.captured import CapturedBodyResponse, refused_capture
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    utc_now,
)

if TYPE_CHECKING:
    import httpx


@dataclass(frozen=True, slots=True)
class BillAcquisitionBudget:
    """Per-call request/response bounds and per-client request-start pacing."""

    max_requests: int
    max_status_bytes: int
    max_text_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_status_bytes, "max_status_bytes", MAX_EVIDENCE_BYTES)
        check_byte_bound(self.max_text_bytes, "max_text_bytes", MAX_EVIDENCE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class BillStatusAcquisition:
    status: BillStatus
    capture: CapturedBodyResponse
    request_count: int
    budget: BillAcquisitionBudget


@dataclass(frozen=True, slots=True)
class BillTextAcquisition:
    identity: BillTextIdentity
    capture: CapturedBodyResponse
    request_count: int
    budget: BillAcquisitionBudget


class BillSourceUnavailableError(BillSourceError):
    """The exact requested locator answered 404/410; other routes are unknown."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Bill source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def _require_xml_capture(capture: CapturedBodyResponse, *, expected_url: str) -> None:
    if capture.requested_url != expected_url or capture.resolved_url != expected_url:
        raise BillSourceError("Bill capture URL differs from the requested source locator")
    if capture.status_code in (404, 410):
        raise BillSourceUnavailableError(capture)
    if capture.status_code != 200:
        raise BillSourceError("Bill capture must contain an HTTP 200 response")
    media_type = (capture.content_type or "").split(";", 1)[0].strip().casefold()
    if media_type not in ("application/xml", "text/xml"):
        raise BillSourceError("Bill source Content-Type must be XML")


class BillAcquirer(SourceAcquirer):
    """A sequential, caller-owned client for status and selected XML text.

    No automatic latest-version choice or format fallback occurs. A text call
    rechecks retained status bytes and requires its source-stated XML link.
    Transport timeouts bound individual waits, not total elapsed time.
    """

    def __init__(
        self,
        *,
        budget: BillAcquisitionBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, BillAcquisitionBudget):
            raise TypeError("budget must be a BillAcquisitionBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-congress-bills/1.0",
            label="Bill",
            error_type=BillSourceError,
            context_key="bill_acquisition",
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> BillAcquisitionBudget:
        return self._budget

    def _failure(
        self,
        error: Exception,
        *,
        operation: str,
        identity: BillIdentity,
        package_id: str | None,
        capture: CapturedBodyResponse | None,
        stage: str = "source-validation",
        budget: BillAcquisitionBudget | None = None,
    ) -> None:
        if capture is not None:
            attach_refused_response(error, refused_capture(capture, stage=stage))
        error.__dict__["bill_acquisition"] = {
            "operation": operation,
            "identity": asdict(identity),
            "packageId": package_id,
            "requestCount": self._http.request_count,
            "budget": asdict(budget or self.budget),
        }

    def acquire_status(self, identity: BillIdentity) -> BillStatusAcquisition:
        """Fetch and validate exact BILLSTATUS XML for one explicit bill ID."""
        url = bill_status_locator(identity)
        self._http.reset_budget()
        capture = None
        try:
            capture = self._http.capture(url, max_bytes=self.budget.max_status_bytes, allow_unavailable=True)
            _require_xml_capture(capture, expected_url=url)
            status = parse_bill_status(capture.body, identity=identity, max_bytes=self.budget.max_status_bytes)
            return BillStatusAcquisition(status, capture, self._http.request_count, self.budget)
        except Exception as error:
            self._failure(error, operation="status", identity=identity, package_id=None, capture=capture)
            raise

    def acquire_text(
        self,
        status: BillStatusAcquisition,
        *,
        package_id: str,
        max_bytes: int | None = None,
    ) -> BillTextAcquisition:
        """Fetch the selected package's offered XML, within the caller's allowance.

        max_bytes can narrow max_text_bytes for an injected dataset fetcher.
        Unavailable XML is reported explicitly; HTML/PDF links remain metadata.
        """
        if not isinstance(status, BillStatusAcquisition):
            raise TypeError("status must be a BillStatusAcquisition")
        identity = status.status.identity
        url = bill_xml_locator(identity, package_id)
        limit = self.budget.max_text_bytes
        if max_bytes is not None:
            if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
                raise ValueError("max_bytes must be a positive integer")
            limit = min(limit, max_bytes)
        self._http.reset_budget()
        effective_budget = replace(self.budget, max_text_bytes=limit)
        active_capture = status.capture
        stage = "status-validation"
        try:
            _require_xml_capture(status.capture, expected_url=bill_status_locator(identity))
            parsed = parse_bill_status(status.capture.body, identity=identity, max_bytes=self.budget.max_status_bytes)
            if parsed != status.status:
                raise BillSourceError("Bill status fields differ from the retained XML")
            select_bill_xml(parsed, package_id)
            # A later HTTP failure must never be attributed to the status XML.
            active_capture = None
            stage = "source-validation"
            capture = self._http.capture(url, max_bytes=limit, allow_unavailable=True)
            active_capture = capture
            _require_xml_capture(capture, expected_url=url)
            text_identity = validate_bill_text(
                capture.body, identity=identity, package_id=package_id, final_url=capture.resolved_url, max_bytes=limit
            )
            return BillTextAcquisition(text_identity, capture, self._http.request_count, effective_budget)
        except Exception as error:
            self._failure(
                error,
                operation="text",
                identity=identity,
                package_id=package_id,
                capture=active_capture,
                stage=stage,
                budget=effective_budget,
            )
            raise


__all__ = [
    "BillAcquirer",
    "BillAcquisitionBudget",
    "BillSourceUnavailableError",
    "BillStatusAcquisition",
    "BillTextAcquisition",
]
