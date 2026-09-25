"""Acquire Federal Register XML first, with bounded GovInfo HTML fallback.

Exact XML 404/410 responses permit HTML fallback; other failures remain visible.
The sequential client owns request bounds and pacing. Pure source validators
check identity; callers retain or process the returned bytes without refetching.
Install ``spicy-docs[acquisition]`` for this HTTPX-based operation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Self

import httpx

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.federal_register.body_sources import (
    FederalRegisterBodySourceError,
    GovInfoGranuleIdentity,
    GovInfoModsResolution,
    govinfo_granule_locator,
    govinfo_mods_locator,
    resolve_govinfo_granule_from_mods,
    validate_govinfo_granule,
)
from spicy_docs.sources.federal_register.body_text import (
    PublisherTextIdentity,
    publisher_text_locator,
    validate_publisher_text,
)
from spicy_docs.sources.federal_register.body_xml import (
    PublisherXmlIdentity,
    publisher_xml_locator,
    validate_publisher_xml,
)
from spicy_docs.transport.capture import BoundedHttpCapture, CapturedBodyResponse, refused_capture
from spicy_docs.transport.source_acquirer import check_byte_bound, check_request_count, check_timing

GovInfoBodyRoute = Literal["granule", "mods-start-page"]
BodyFormatPreference = Literal["prefer-xml", "xml", "html", "txt"]
FederalRegisterBodyRoute = Literal["publisher-xml", "publisher-text", "granule", "mods-start-page"]
_USER_AGENT = "spicy-docs-federal-register-body/1.0"


@dataclass(frozen=True, slots=True)
class FederalRegisterBodyBudget:
    """Per-acquisition request/byte bounds and per-client request-start pacing.

    ``max_requests`` includes every XML/text/MODS/HTML request and retry. Redirects are
    always refused. The timeout bounds transport waits, not total elapsed time.
    A zero start interval explicitly disables pacing within this client.
    """

    max_requests: int
    max_body_bytes: int
    max_mods_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_body_bytes, "max_body_bytes", MAX_EVIDENCE_BYTES)
        check_byte_bound(self.max_mods_bytes, "max_mods_bytes", MAX_EVIDENCE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class FederalRegisterBodyAcquisition:
    """Validated source identity and captures, without a separate publication."""

    requested_format: BodyFormatPreference
    format: Literal["xml", "html", "txt"]
    route: FederalRegisterBodyRoute
    identity: PublisherXmlIdentity | PublisherTextIdentity | GovInfoGranuleIdentity
    body: CapturedBodyResponse
    mods: CapturedBodyResponse | None
    mods_resolution: GovInfoModsResolution | None
    unavailable_xml: CapturedBodyResponse | None
    request_count: int
    budget: FederalRegisterBodyBudget


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FederalRegisterBodyAcquirer:
    """Prefer publisher XML using one sequential, caller-owned client.

    Request counts reset per ``acquire``; pacing persists until ``close``.
    HTML fallback requires XML 404/410. Credentials and redirects are refused.
    Injected transports must honor HTTPX's streaming interface and may not add
    hidden requests or authentication. This class is not a concurrent scheduler.
    """

    def __init__(
        self,
        *,
        budget: FederalRegisterBodyBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(budget, FederalRegisterBodyBudget):
            raise TypeError("budget must be a FederalRegisterBodyBudget")
        self._budget = budget
        self._closed = False
        self._http = BoundedHttpCapture(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=_USER_AGENT,
            error_type=FederalRegisterBodySourceError,
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> FederalRegisterBodyBudget:
        return self._budget

    def __enter__(self) -> Self:
        if self._closed:
            raise ValueError("Federal Register body acquirer is closed")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._http.close()

    def acquire(
        self,
        *,
        document_number: str,
        publication_date: str,
        format: BodyFormatPreference = "prefer-xml",
        html_route: GovInfoBodyRoute = "granule",
        start_page: int | None = None,
    ) -> FederalRegisterBodyAcquisition:
        """Return exact XML when available, or the chosen HTML route after 404/410.

        Use ``format="xml"`` to require XML, ``format="txt"`` for publisher
        text or ``format="html"`` for GovInfo. A successful fallback retains the XML response
        that caused it. Source failures never become implicit format absence.
        """
        if self._closed:
            raise ValueError("Federal Register body acquirer is closed")
        xml_url = publisher_xml_locator(document_number, publication_date)
        granule_url = govinfo_granule_locator(document_number, publication_date)
        if format not in ("prefer-xml", "xml", "html", "txt"):
            raise ValueError("format must be prefer-xml, xml, html or txt")
        if format == "txt" and (html_route != "granule" or start_page is not None):
            raise ValueError("publisher text does not use an HTML route or start_page")
        if html_route not in ("granule", "mods-start-page"):
            raise ValueError("html_route must be granule or mods-start-page")
        if html_route == "mods-start-page":
            if isinstance(start_page, bool) or not isinstance(start_page, int) or start_page <= 0:
                raise ValueError("MODS route requires a positive integer start_page")
        elif start_page is not None:
            raise ValueError("start_page is only valid for the MODS route")
        self._http.reset_budget()
        mods = None
        resolution = None
        unavailable_xml = None
        active_capture = None
        route: FederalRegisterBodyRoute = "publisher-xml" if format != "html" else html_route
        try:
            if format == "txt":
                route = "publisher-text"
                body = self._http.capture(
                    publisher_text_locator(document_number, publication_date), max_bytes=self.budget.max_body_bytes
                )
                active_capture = body
                if bare_media_type(body.content_type) not in ("text/plain", "text/html"):
                    raise FederalRegisterBodySourceError("Publisher text Content-Type must be text/plain or text/html")
                text_identity = validate_publisher_text(
                    body.body,
                    source_document_number=document_number,
                    publication_date=publication_date,
                    final_url=body.resolved_url,
                    max_bytes=self.budget.max_body_bytes,
                )
                return FederalRegisterBodyAcquisition(
                    requested_format=format,
                    format="txt",
                    route=route,
                    identity=text_identity,
                    body=body,
                    mods=None,
                    mods_resolution=None,
                    unavailable_xml=None,
                    request_count=self._http.request_count,
                    budget=self.budget,
                )
            if format != "html":
                xml = self._http.capture(
                    xml_url, max_bytes=self.budget.max_body_bytes, allow_unavailable=format == "prefer-xml"
                )
                active_capture = xml
                if xml.status_code == 200:
                    if bare_media_type(xml.content_type) not in ("application/xml", "text/xml"):
                        raise FederalRegisterBodySourceError("Publisher body Content-Type must be XML")
                    xml_identity = validate_publisher_xml(
                        xml.body,
                        source_document_number=document_number,
                        publication_date=publication_date,
                        final_url=xml.resolved_url,
                        max_bytes=self.budget.max_body_bytes,
                    )
                    return FederalRegisterBodyAcquisition(
                        requested_format=format,
                        format="xml",
                        route="publisher-xml",
                        identity=xml_identity,
                        body=xml,
                        mods=None,
                        mods_resolution=None,
                        unavailable_xml=None,
                        request_count=self._http.request_count,
                        budget=self.budget,
                    )
                unavailable_xml = xml

            route = html_route
            active_capture = None
            access_id = document_number
            if html_route == "mods-start-page":
                assert start_page is not None
                mods = self._http.capture(govinfo_mods_locator(publication_date), max_bytes=self.budget.max_mods_bytes)
                active_capture = mods
                resolution = resolve_govinfo_granule_from_mods(
                    mods.body,
                    publication_date=publication_date,
                    start_page=start_page,
                    max_bytes=self.budget.max_mods_bytes,
                )
                access_id = resolution.access_id
                granule_url = resolution.granule_url
            # A failed later request must not inherit the successful MODS body.
            active_capture = None
            body = self._http.capture(granule_url, max_bytes=self.budget.max_body_bytes)
            active_capture = body
            identity = validate_govinfo_granule(
                body.body,
                source_document_number=document_number,
                publication_date=publication_date,
                access_id=access_id,
                final_url=body.resolved_url,
                max_bytes=self.budget.max_body_bytes,
            )
            return FederalRegisterBodyAcquisition(
                requested_format=format,
                format="html",
                route=html_route,
                identity=identity,
                body=body,
                mods=mods,
                mods_resolution=resolution,
                unavailable_xml=unavailable_xml,
                request_count=self._http.request_count,
                budget=self.budget,
            )
        except Exception as error:
            if active_capture is not None:
                attach_refused_response(error, refused_capture(active_capture, stage="source-validation"))
            error.__dict__["body_acquisition"] = {
                "format": format,
                "htmlRoute": html_route,
                "route": route,
                "documentNumber": document_number,
                "publicationDate": publication_date,
                "startPage": start_page,
                "requestCount": self._http.request_count,
                "budget": asdict(self.budget),
                "unavailableXml": unavailable_xml,
            }
            raise


__all__ = [
    "BodyFormatPreference",
    "CapturedBodyResponse",
    "FederalRegisterBodyAcquirer",
    "FederalRegisterBodyAcquisition",
    "FederalRegisterBodyBudget",
    "FederalRegisterBodyRoute",
    "GovInfoBodyRoute",
]
