"""Acquire explicit CFR/eCFR sources with exact bytes and bounded HTTP evidence."""

from __future__ import annotations

import math
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Self

import httpx

from spicy_docs.sources.cfr.annual import annual_cfr_xml_locator, validate_annual_cfr_xml
from spicy_docs.sources.cfr.ecfr import (
    ecfr_bulk_xml_locator,
    ecfr_titles_locator,
    ecfr_xml_locator,
    parse_ecfr_titles,
    validate_ecfr_bulk_xml,
    validate_ecfr_xml,
)
from spicy_docs.sources.cfr.edition import AnnualCfrEdition, _parse_annual_cfr_metadata, annual_cfr_edition_locator
from spicy_docs.sources.cfr.models import (
    MAX_CFR_BYTES,
    AnnualCfrSelection,
    CfrSourceError,
    CfrXmlMetadata,
    EcfrSelection,
    EcfrTitles,
)
from spicy_docs.sources.govinfo.mods import GovInfoModsPackage
from spicy_docs.sources.refusals import attach_refused_response
from spicy_docs.transport.capture import BoundedHttpCapture, CapturedBodyResponse, refused_capture

type CfrSelection = EcfrSelection | AnnualCfrSelection | int


@dataclass(frozen=True, slots=True)
class CfrAcquisitionBudget:
    """Bounds for each operation; pacing persists across the client's operations.

    Whole titles need a larger explicit allowance than individual sections. This
    standalone capture bound does not change source-release admission limits.
    """

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        if isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int) or self.max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= MAX_CFR_BYTES
        ):
            raise ValueError(f"max_bytes must be an integer from 1 to {MAX_CFR_BYTES}")
        for name, positive in (("timeout_seconds", True), ("min_request_interval_seconds", False)):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or positive
                and value == 0
            ):
                raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")


@dataclass(frozen=True, slots=True)
class CfrXmlAcquisition:
    selection: CfrSelection
    identity: CfrXmlMetadata
    capture: CapturedBodyResponse
    request_count: int
    budget: CfrAcquisitionBudget
    xml: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class CfrTitlesAcquisition:
    titles: EcfrTitles
    capture: CapturedBodyResponse
    request_count: int
    budget: CfrAcquisitionBudget


@dataclass(frozen=True, slots=True)
class CfrEditionAcquisition:
    selection: AnnualCfrSelection
    edition: AnnualCfrEdition
    metadata: GovInfoModsPackage
    capture: CapturedBodyResponse
    request_count: int
    budget: CfrAcquisitionBudget


class CfrSourceUnavailableError(CfrSourceError):
    """Only the exact requested locator has answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"CFR source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CfrAcquirer:
    """A sequential source client. Callers select, retain and process captures.

    Dates, editions and source routes are explicit; no implicit latest choice,
    format fallback or disk cache occurs. Timeouts bound transport waits rather
    than total duration. XML validation establishes the documented native facts,
    retaining URL-only identity separately when the body cannot prove it.
    """

    def __init__(
        self,
        *,
        budget: CfrAcquisitionBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(budget, CfrAcquisitionBudget):
            raise TypeError("budget must be a CfrAcquisitionBudget")
        self._budget = budget
        self._http = BoundedHttpCapture(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-cfr/1.0",
            error_type=CfrSourceError,
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> CfrAcquisitionBudget:
        return self._budget

    def __enter__(self) -> Self:
        self._http.reset_budget()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _acquire[Result](
        self,
        url: str,
        *,
        operation: str,
        selection: CfrSelection | None,
        media_types: tuple[str, ...],
        parse: Callable[[CapturedBodyResponse, int], Result],
        max_bytes: int | None,
        allow_gzip: bool = False,
    ) -> tuple[Result, CapturedBodyResponse, CfrAcquisitionBudget]:
        limit = self.budget.max_bytes
        if max_bytes is not None:
            if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
                raise ValueError("max_bytes must be a positive integer")
            limit = min(limit, max_bytes)
        effective_budget = replace(self.budget, max_bytes=limit)
        self._http.reset_budget()
        capture = None
        try:
            capture = self._http.capture(url, max_bytes=limit, allow_unavailable=True, allow_gzip=allow_gzip)
            if capture.status_code in (404, 410):
                raise CfrSourceUnavailableError(capture)
            media_type = (capture.content_type or "").split(";", 1)[0].strip().casefold()
            if media_type not in media_types:
                raise CfrSourceError("CFR source Content-Type differs from the requested format")
            return parse(capture, limit), capture, effective_budget
        except Exception as error:
            if capture is not None:
                error.__dict__["capture"] = capture
                attach_refused_response(error, refused_capture(capture, stage="source-validation"))
            error.__dict__["cfr_acquisition"] = {
                "operation": operation,
                "selection": asdict(selection)
                if isinstance(selection, (EcfrSelection, AnnualCfrSelection))
                else selection,
                "requestCount": self._http.request_count,
                "budget": asdict(effective_budget),
            }
            raise

    def acquire_ecfr_titles(self, *, max_bytes: int | None = None) -> CfrTitlesAcquisition:
        """Capture the live title roster; its dates are available for caller selection."""
        titles, capture, budget = self._acquire(
            ecfr_titles_locator(),
            operation="ecfr-titles",
            selection=None,
            media_types=("application/json",),
            parse=lambda response, limit: parse_ecfr_titles(response.body, max_bytes=limit),
            max_bytes=max_bytes,
        )
        return CfrTitlesAcquisition(titles, capture, self._http.request_count, budget)

    def _xml(
        self,
        url: str,
        selection: CfrSelection,
        operation: str,
        parse: Callable[[bytes, str, int], CfrXmlMetadata],
        max_bytes: int | None,
    ) -> CfrXmlAcquisition:
        def validate(response: CapturedBodyResponse, limit: int) -> tuple[CfrXmlMetadata, bytes]:
            xml = response.body
            if response.content_encoding == "gzip":
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                try:
                    xml = decoder.decompress(response.body, limit + 1)
                except zlib.error as error:
                    raise CfrSourceError("CFR source gzip body is malformed") from error
                if len(xml) > limit or decoder.unconsumed_tail:
                    raise CfrSourceError("CFR decoded XML exceeds its byte bound")
                if not decoder.eof or decoder.unused_data:
                    raise CfrSourceError("CFR source requires one complete gzip body without trailing data")
            return parse(xml, response.resolved_url, limit), xml

        (identity, xml), capture, budget = self._acquire(
            url,
            operation=operation,
            selection=selection,
            media_types=("application/xml", "text/xml"),
            parse=validate,
            max_bytes=max_bytes,
            # The dated eCFR API explicitly requires response compression.
            allow_gzip=operation == "ecfr-api",
        )
        return CfrXmlAcquisition(selection, identity, capture, self._http.request_count, budget, xml)

    def acquire_ecfr(self, selection: EcfrSelection, *, max_bytes: int | None = None) -> CfrXmlAcquisition:
        """Capture one explicitly dated eCFR title, part or section from the API."""
        return self._xml(
            ecfr_xml_locator(selection),
            selection,
            "ecfr-api",
            lambda xml, url, limit: validate_ecfr_xml(xml, selection=selection, final_url=url, max_bytes=limit),
            max_bytes,
        )

    def acquire_annual(self, selection: AnnualCfrSelection, *, max_bytes: int | None = None) -> CfrXmlAcquisition:
        """Capture an annual volume or section, preserving its stated revision separately."""
        return self._xml(
            annual_cfr_xml_locator(selection),
            selection,
            "annual-cfr",
            lambda xml, url, limit: validate_annual_cfr_xml(xml, identity=selection, final_url=url, max_bytes=limit),
            max_bytes,
        )

    def acquire_ecfr_bulk(self, title: int, *, max_bytes: int | None = None) -> CfrXmlAcquisition:
        """Capture GovInfo's current bulk title; this route accepts no historical date."""
        return self._xml(
            ecfr_bulk_xml_locator(title),
            title,
            "ecfr-bulk",
            lambda xml, url, limit: validate_ecfr_bulk_xml(xml, title=title, final_url=url, max_bytes=limit),
            max_bytes,
        )

    def acquire_annual_edition(
        self,
        selection: AnnualCfrSelection,
        *,
        max_bytes: int | None = None,
    ) -> CfrEditionAcquisition:
        """Map package/constituent metadata and edition facts in one MODS request."""
        (edition, metadata), capture, budget = self._acquire(
            annual_cfr_edition_locator(selection),
            operation="annual-edition",
            selection=selection,
            media_types=("application/xml", "text/xml"),
            parse=lambda response, limit: _parse_annual_cfr_metadata(
                response.body,
                selection=selection,
                final_url=response.resolved_url,
                max_bytes=limit,
            ),
            max_bytes=max_bytes,
        )
        return CfrEditionAcquisition(selection, edition, metadata, capture, self._http.request_count, budget)
