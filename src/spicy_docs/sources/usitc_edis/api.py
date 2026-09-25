"""Bounded capture of the EDIS `/data` XML routes: explicit pages, exact bytes, a named transport seam.

The web service documents one pagination contract -- up to 100 rows per
request under a ``pageNumber`` query parameter that defaults to 1, and an
**empty** page beyond the last row -- so the walk advances the page number
it generated, stops at the first empty page, and refuses to end any other
way. A first page that answers empty is a requested-empty observation of
that query on that day, not source absence, and is surfaced as an empty
first page rather than a zero. No declared total travels with the rows,
so the walk sees a listing that shifts under it in one direction only: an
insertion into pages already read pushes a served row onto the next page,
repeating an identity, which refuses; a deletion from pages already read
pulls an unread row onto a page already read, skipping it silently, and
cannot be seen here at all. The pooled walks of ``reading/paged_json.py``
settle against a declared total, which this service never states, so they
cannot close that gap.

Earlier probes on 2026-09-24 found that the sampled paths answered Akamai's
``Access Denied`` to curl and httpx alike -- browser user agent, HTTP/1.1
or 2, ``robots.txt`` included -- while the same URLs served a real WebKit
browser, and the credentialed proxies answered them: Zyte ``httpResponseBody``
and Firecrawl v2 ``rawBase64`` both returned the real XML (receipts
``zyte-client-smoke-2026-09-24``, ``firecrawl-client-smoke-2026-09-24``).
The acquirer therefore takes any ``httpx.BaseTransport``. Later direct
download requests reached EDIS's authentication boundary (401 anonymously,
403 with a token issued for DataWeb), so earlier walls do not prove
permanent direct refusal. The anonymous attachment-PDF route runs the shared
walled ladder (``SourceAcquirer.capture_walled``: DIRECT on this client and
its transport, then the proxies), which escalates a wall instead of reading
it as the publisher's answer; with an EDIS API token read at call time it
makes one credentialed request instead, direct or explicitly through Zyte
(:mod:`spicy_docs.sources.usitc_edis.credentialed`). All request and
response checking is transport-agnostic and pinned by tests against a mock,
so the transport seam is exactly one constructor argument.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import urlencode

from spicy_docs.reading.paged_json import query_value, with_query
from spicy_docs.sources.usitc_edis.attachments import (
    MAX_DOWNLOAD_BYTES,
    PDF_MEDIA_TYPES,
    attachment_download_locator,
    read_attachment_pdf,
)
from spicy_docs.sources.usitc_edis.credentialed import check_route, credentialed_download, validate_edis_token
from spicy_docs.sources.usitc_edis.records import (
    MAX_PAGE_BYTES,
    USER_AGENT,
    AttachmentRecord,
    DocumentRecord,
    Investigation,
    UsitcEdisSourceError,
    UsitcEdisUnavailableError,
    check_edis_data_url,
    check_edis_id,
    parse_attachments,
    parse_documents,
    parse_investigations,
)
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

    from spicy_docs.sources.usitc_edis.attachments import AttachmentDownload

#: The publisher's documented page size; a page holding more rows than this refuses.
PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100
XML_MEDIA_TYPES = ("application/xml", "text/xml")
#: The guide spells the parameter ``pageNumber`` in its parameter table and
#: ``pagenumber`` in one example URL; both spellings are read where the
#: caller's URL carries them, and builders always write ``pageNumber``.
PAGE_PARAMETERS = ("pageNumber", "pagenumber")
Row = TypeVar("Row", Investigation, DocumentRecord)


def _token(value: object, *, label: str) -> str | None:
    """One nonblank publisher token with no surrounding whitespace, or ``None`` to omit it."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise UsitcEdisSourceError(f"EDIS {label} must be a trimmed nonempty string")
    return value


def _page_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise UsitcEdisSourceError("page must be a positive integer")
    return value


def _query(built: list[tuple[str, str]], page: int) -> str:
    built.append(("pageNumber", str(_page_number(page))))
    return urlencode(built)


def investigation_url(
    *,
    number: str | None = None,
    phase: str | None = None,
    investigation_type: str | None = None,
    status: str | None = None,
    page: int = 1,
) -> str:
    """One investigation-listing page URL. ``number`` and ``phase`` are path selectors when stated.

    ``investigation_type`` and ``status`` are the guide's documented query
    filters (full strings; ``Preinstitution``, ``Active``, ``Inactive``,
    ``Cancelled``). Measured live 2026-09-24 through a browser-backed
    transport: the type filter applies (every returned row stated the
    requested type), and the status filter applies under the guide's
    parameter-table spelling ``investigationStatus`` (camelCase), which this
    builder writes; the lowercase example spelling ``investigationstatus``
    answered the same unfiltered first page for Active, Inactive and a
    nonsense value alike, so it is ignored (receipt
    ``usitc-edis-filters-2026-09-24``). Callers that keep lowercase URLs
    should filter the rows instead.
    """
    number = _token(number, label="investigation number")
    phase = _token(phase, label="investigation phase")
    if phase is not None and number is None:
        raise UsitcEdisSourceError("EDIS investigation phase requires an investigation number")
    path = "/data/investigation"
    for selector in (number, phase):
        if selector is not None:
            path += f"/{selector}"
    pairs: list[tuple[str, str]] = []
    if (value := _token(investigation_type, label="investigation type")) is not None:
        pairs.append(("investigationType", value))
    if (value := _token(status, label="investigation status")) is not None:
        pairs.append(("investigationStatus", value))
    return f"https://edis.usitc.gov{path}?{_query(pairs, page)}"


def document_list_url(
    *,
    investigation_number: str | None = None,
    investigation_phase: str | None = None,
    document_type: str | None = None,
    firm_org: str | None = None,
    security_level: str | None = None,
    page: int = 1,
) -> str:
    """One document-listing page URL. ``investigation_number`` accepts the publisher's partial numbers."""
    pairs: list[tuple[str, str]] = []
    if (value := _token(investigation_number, label="investigation number")) is not None:
        pairs.append(("investigationNumber", value))
    if (value := _token(investigation_phase, label="investigation phase")) is not None:
        pairs.append(("investigationPhase", value))
    if (value := _token(document_type, label="document type")) is not None:
        pairs.append(("documentType", value))
    if (value := _token(firm_org, label="firm organization")) is not None:
        pairs.append(("firmOrg", value))
    if (value := _token(security_level, label="security level")) is not None:
        pairs.append(("securityLevel", value))
    return f"https://edis.usitc.gov/data/document?{_query(pairs, page)}"


def document_url(document_id: int) -> str:
    """The metadata locator for one known document, without a listing walk."""
    return f"https://edis.usitc.gov/data/document/{check_edis_id(document_id)}"


def attachment_url(document_id: int) -> str:
    """The attachment-metadata locator for one document; the id is digits, never a guess."""
    return f"https://edis.usitc.gov/data/attachment/{check_edis_id(document_id)}"


def _page_parameter(url: str) -> tuple[str, int]:
    """The one page parameter this URL carries, whichever spelling, with its value.

    Absent, present under both spellings, or non-digit values refuse: an
    explicit page is part of the walk's contract with this publisher.
    """
    stated = [(name, value) for name in PAGE_PARAMETERS if (value := query_value(url, name)) is not None]
    if len(stated) != 1:
        raise UsitcEdisSourceError("EDIS walk URL must carry exactly one pageNumber parameter")
    name, value = stated[0]
    if not value.isdigit() or int(value) < 1:
        raise UsitcEdisSourceError("EDIS walk URL page number must be positive digits")
    return name, int(value)


@dataclass(frozen=True, slots=True)
class EdisPage[Row]:
    """One exact listing response and its rows; an empty page is an observation, not a zero."""

    page_number: int
    capture: CapturedBodyResponse
    records: tuple[Row, ...]

    @property
    def sha256(self) -> str:
        return self.capture.sha256

    @property
    def is_empty(self) -> bool:
        return not self.records


@dataclass(frozen=True, slots=True)
class EdisAttachmentListing:
    """One document's attachment rows with the capture that stated them."""

    document_id: int
    capture: CapturedBodyResponse
    records: tuple[AttachmentRecord, ...]


@dataclass(frozen=True, slots=True)
class EdisBudget:
    """Bounds for each request; pacing persists across one client's requests."""

    max_requests: int
    max_page_bytes: int
    max_download_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_page_bytes, "max_page_bytes", MAX_PAGE_BYTES)
        check_byte_bound(self.max_download_bytes, "max_download_bytes", MAX_DOWNLOAD_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


class EdisAcquirer(SourceAcquirer):
    """Keyless, paced capture of EDIS listing pages and attachment PDFs.

    One client per acquirer. Listing walks chain each page onto the
    operation's shared request budget, so ``max_requests`` bounds a whole
    walk, not each page separately.
    """

    def __init__(
        self,
        *,
        budget: EdisBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, EdisBudget):
            raise TypeError("budget must be an EdisBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=USER_AGENT,
            label="USITC EDIS",
            error_type=UsitcEdisSourceError,
            context_key="usitc_edis_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> EdisBudget:
        return self._budget

    def investigations(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[EdisPage[Investigation]]:
        """Walk investigation pages for one URL to the publisher's empty terminal page."""
        return self._walk(url, parse_investigations, max_pages=max_pages)

    def documents(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[EdisPage[DocumentRecord]]:
        """Walk document pages for one URL to the publisher's empty terminal page."""
        return self._walk(url, parse_documents, max_pages=max_pages)

    def document(
        self, document_id: int, *, max_bytes: int | None = None
    ) -> tuple[DocumentRecord | None, CapturedBodyResponse]:
        """Capture one known document without walking its investigation's listing.

        ``None`` with a successful capture is requested-empty, never proof
        of absence. A 404/410 raises ``UsitcEdisUnavailableError``. Multiple
        rows or a different document id refuse with the capture retained.
        """
        url = document_url(document_id)
        limit = narrow_byte_limit(self.budget.max_page_bytes, max_bytes)

        def parse(response: CapturedBodyResponse, bound: int) -> DocumentRecord | None:
            rows = parse_documents(response.body, max_bytes=bound)
            if len(rows) > 1:
                raise UsitcEdisSourceError("EDIS document lookup returned more than one document")
            if rows and rows[0].id != document_id:
                raise UsitcEdisSourceError("EDIS document lookup names a document other than the one requested")
            return rows[0] if rows else None

        return self.capture_validated(
            url,
            media_types=XML_MEDIA_TYPES,
            parse=parse,
            max_bytes=limit,
            unavailable=UsitcEdisUnavailableError,
            context={"operation": "document", "url": url, "documentId": document_id},
        )

    def _walk(
        self,
        url: str,
        parse: Callable[..., tuple[Row, ...]],
        *,
        max_pages: int,
    ) -> Iterator[EdisPage[Row]]:
        """Advance the page number this package generated until the publisher answers empty.

        Each page is checked against the documented page size, and each row
        identity against every identity already served, so an insertion that
        repeats a row refuses; a deletion that skips one is the module's
        documented blind spot. Pages already yielded remain partial
        observations when a later page refuses.
        """
        check_request_count(max_pages, "max_pages")
        url = check_edis_data_url(url)
        parameter, page_number = _page_parameter(url)
        seen: set[object] = set()
        rows_served = 0
        for index in range(max_pages):
            requested = with_query(url, parameter, str(page_number))
            rows, capture = self.capture_validated(
                requested,
                media_types=XML_MEDIA_TYPES,
                parse=lambda response, bound: parse(response.body, max_bytes=bound),
                max_bytes=self.budget.max_page_bytes,
                unavailable=UsitcEdisUnavailableError,
                context={"operation": "listing-page", "url": requested, "pageNumber": page_number},
                reset_budget=index == 0,
            )
            if len(rows) > PAGE_SIZE:
                raise UsitcEdisSourceError(f"EDIS listing page {page_number} holds more than {PAGE_SIZE} rows")
            for record in rows:
                identity = record.identity if isinstance(record, Investigation) else record.id
                if identity in seen:
                    raise UsitcEdisSourceError(
                        f"EDIS listing served the same identity twice by page {page_number}; re-walk this query"
                    )
                seen.add(identity)
            rows_served += len(rows)
            yield EdisPage(page_number, capture, rows)
            if not rows:
                return
            page_number += 1
        raise UsitcEdisSourceError(
            f"EDIS listing walk reached its page bound ({max_pages} pages, {rows_served} rows) "
            "before the publisher's empty terminal page"
        )

    def attachments(self, document_id: int, *, max_bytes: int | None = None) -> EdisAttachmentListing:
        """One GET for one document's attachment metadata page; no pagination on this route."""
        url = check_edis_data_url(attachment_url(document_id))
        limit = narrow_byte_limit(self.budget.max_page_bytes, max_bytes)
        records, capture = self.capture_validated(
            url,
            media_types=XML_MEDIA_TYPES,
            parse=lambda response, bound: parse_attachments(response.body, document_id=document_id, max_bytes=bound),
            max_bytes=limit,
            unavailable=UsitcEdisUnavailableError,
            context={"operation": "attachment-listing", "url": url, "documentId": document_id},
        )
        return EdisAttachmentListing(document_id, capture, records)

    def acquire_attachment_pdf(
        self,
        url: str,
        *,
        declared_size: int | None = None,
        max_bytes: int | None = None,
        token: str | None = None,
        credentialed_transport: str | None = None,
    ) -> tuple[AttachmentDownload, CapturedBodyResponse]:
        """Capture one attachment PDF at the locator the metadata stated.

        With no ``token`` (the default), the route runs the shared walled
        ladder through :meth:`capture_walled`: DIRECT on this acquirer's own
        client, then ZYTE_HTTP and FIRECRAWL_RAW, so a wall or a refusal on one
        rung escalates instead of reading as the publisher's answer, and a
        clean 404/410 -- publisher absence -- raises
        ``UsitcEdisUnavailableError``. A ``WalledFetchError`` (every rung
        walled, refused or failed) passes through with its rung outcomes.

        With ``token``, the route makes one direct credentialed request
        carrying ``Authorization: Bearer <token>`` -- the transport the EDIS
        Data Web Service guide (2024-06-14) documents -- and the caller reads
        the value at call time (``read_api_key``), so no module state ever
        holds it. A credentialed 401/403 raises
        :class:`~spicy_docs.transport.credentials.CredentialRefusedError`
        with its body suppressed and never escalates. Other wall-marked
        answers raise ``UsitcEdisSourceError`` with the capture retained. A
        caller may explicitly select ``credentialed_transport="zyte"`` for a
        known direct wall, which discloses the token to that proxy. A
        transport named without a token refuses rather than silently taking
        the anonymous ladder.

        Every route ends in the same proof: the media type, the ``%PDF-``
        magic and trailer, the final URL, and -- when the caller holds the
        metadata route's ``fileSize`` -- that exact byte count. All routes
        share this client's pacing clock and reset the attempt count per
        operation. The ladder resolves provider credentials once per acquirer
        and skips a provider without one, uncharged; the explicit Zyte route
        charges its one attempt even when its credential is missing.
        """
        locator = attachment_download_locator(url)
        limit = narrow_byte_limit(self.budget.max_download_bytes, max_bytes)
        if declared_size is not None:
            if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size < 0:
                raise UsitcEdisSourceError("declared_size must be a non-negative integer")
            if declared_size > limit:
                raise UsitcEdisSourceError("publisher declares the file larger than the capture byte bound")
        if token is None:
            if credentialed_transport is not None:
                raise UsitcEdisSourceError("EDIS credentialed transport needs a download token")
        else:
            token = validate_edis_token(token)
            route = check_route(credentialed_transport or "direct")
        context = {
            "operation": "attachment-pdf",
            "url": locator.url,
            "documentId": locator.document_id,
            "attachmentId": locator.attachment_id,
            "declaredSize": declared_size,
            "maxBytes": limit,
        }

        def parse(capture: CapturedBodyResponse, _bound: int) -> AttachmentDownload:
            download = read_attachment_pdf(capture.body, url=locator.url, final_url=capture.resolved_url)
            if declared_size is not None and download.byte_size != declared_size:
                raise UsitcEdisSourceError("EDIS attachment byte count differs from the size the publisher declared")
            return download

        if token is None:
            download, capture, _answer = self.capture_walled(
                locator.url,
                media_types=PDF_MEDIA_TYPES,
                parse=parse,
                max_bytes=limit,
                unavailable=UsitcEdisUnavailableError,
                context=context,
            )
            return download, capture
        context = {**context, "route": f"credentialed-{route}"}
        capture = None
        try:
            capture = credentialed_download(
                locator.url,
                token=token,
                max_bytes=limit,
                timeout_seconds=self.budget.timeout_seconds,
                route=route,
                before_request=lambda: self.start_external_request(reset_budget=True),
                clock=self._clock,
            )
            download = self._checked(
                capture,
                media_types=PDF_MEDIA_TYPES,
                parse=parse,
                max_bytes=limit,
                unavailable=UsitcEdisUnavailableError,
            )
        except Exception as error:
            self._attach(error, capture, context)
            raise
        return download, capture
