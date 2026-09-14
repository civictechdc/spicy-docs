"""GAO report files on ``files.gao.gov``: the keyless route to a product's own bytes.

``www.gao.gov`` refuses non-browser clients, so product pages are captured
through Zyte (``native.py``) and the reports feed is the keyless listing
(``rss.py``).  The report *files* live on a different host that answered a
plain client with no credential when probed on 2026-09-14.  Each host spells
the product its own way and the file host is case-sensitive both ways: the
report directory is uppercase, the asset filename lowercase.

Every GAO product has the PDF; only some have the online report.  Of the 47
product pages retained on 2026-08-22 in the salvaged GAO import, 47 link
``/assets/{product-id}.pdf`` and 26 link the ``files.gao.gov`` index, and a
product whose page omits the index answered ``403`` when it was requested
anyway.  So ``acquire_report_pdf`` is the route that always applies.

Two refusals to read correctly.  The host is an S3 origin that answers the
same ``403 AccessDenied`` for an object it does not have as for one it will
not serve, so a refusal here never establishes absence.  And it states
``application/octet-stream`` for PDF bytes, so the media type proves nothing;
the ``%PDF-`` magic and the trailing ``%%EOF`` marker do.

Locators, evidence and limits: ``docs/sources/gao-files.md`` and
``corpora/supply-2026-09-02/receipts/port-P04-gao-files-2026-09-14/``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Final
from urllib.parse import urljoin, urlsplit

from spicy_docs.sources.gao.native import GaoProductSourceError, gao_product_url
from spicy_docs.sources.pdf_bytes import check_pdf_bytes
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

REPORT_FILE_ROOT: Final = "https://files.gao.gov"
REPORT_RENDITIONS: Final = ("report", "highlights")
DEFAULT_MAX_INDEX_BYTES: Final = 8 * 1024 * 1024
DEFAULT_MAX_PDF_BYTES: Final = 32 * 1024 * 1024
MAX_REPORT_FILE_BYTES: Final = 256 * 1024 * 1024
INDEX_MEDIA_TYPES: Final = ("text/html",)
# files.gao.gov states application/octet-stream for PDF bytes (pinned
# 2026-09-14); www.gao.gov, which serves the same paths to browsers, is
# expected to state application/pdf. The magic bytes decide either way.
PDF_MEDIA_TYPES: Final = ("application/pdf", "application/octet-stream")
# ISO 32000-1 requires %%EOF as the file's last line; readers tolerate trailing
# bytes, so look in a bounded tail rather than at the exact end.


class GaoReportFileSourceError(ValueError):
    """The response cannot establish a GAO report file for the requested product."""


class GaoReportFileUnavailableError(GaoReportFileSourceError):
    """The file host answered 404 or 410. A 403 is not absence; see the module docstring."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"GAO file host answered HTTP {capture.status_code}")
        self.capture = capture


def _product_id(value: str) -> str:
    """Reuse the product-page id grammar; a report file is selected by product."""
    try:
        gao_product_url(value)
    except GaoProductSourceError as error:
        raise GaoReportFileSourceError("GAO report files are selected by a product ID") from error
    return value


def _rendition(value: str) -> str:
    if value not in REPORT_RENDITIONS:
        raise GaoReportFileSourceError(f"GAO report rendition must be one of {REPORT_RENDITIONS}")
    return value


def gao_report_pdf_locator(product_id: str, *, rendition: str = "report") -> str:
    """The publisher's own asset path, lowercase, on the file host."""
    suffix = "" if _rendition(rendition) == "report" else "-highlights"
    return f"{REPORT_FILE_ROOT}/assets/{_product_id(product_id)}{suffix}.pdf"


def gao_report_index_locator(product_id: str) -> str:
    """The online report's entry point; the file host spells the segment uppercase."""
    return f"{REPORT_FILE_ROOT}/reports/{_product_id(product_id).upper()}/index.html"


@dataclass(frozen=True, slots=True)
class GaoReportPdf:
    """What the bytes proved. Their size and digest stay on the capture, unduplicated."""

    product_id: str
    rendition: str
    locator: str
    pdf_version: str


@dataclass(frozen=True, slots=True)
class GaoReportIndex:
    """The online report as the publisher wrote it: its title, its PDF and its product."""

    product_id: str
    locator: str
    title: str | None
    pdf_url: str
    product_url: str


class _IndexScanner(HTMLParser):
    """One pass over the index: its title, its PDF anchors, and whether it links its product.

    Space is O(P) in the distinct PDF anchors, not O(A) in every anchor: the
    product link is a membership question, so it is answered while scanning.
    """

    def __init__(self, base: str, product_url: str) -> None:
        super().__init__()
        self._base = base
        self._product_url = product_url
        self._in_title = False
        self.title_parts: list[str] = []
        self.pdf_urls: set[str] = set()
        self.links_product = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag != "a":
            return
        for name, value in attrs:
            if name != "href" or not value:
                continue
            try:
                resolved = urljoin(self._base, value.strip())
                path = urlsplit(resolved).path
            except ValueError:  # a third-party href we cannot resolve is not our identity
                continue
            self.links_product = self.links_product or resolved == self._product_url
            if path.lower().endswith(".pdf"):
                self.pdf_urls.add(resolved)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def parse_gao_report_index(body: bytes, *, product_id: str, max_bytes: int = DEFAULT_MAX_INDEX_BYTES) -> GaoReportIndex:
    """Read the online report in O(B) time over B bounded bytes; identity comes from its own links.

    The index must name its report PDF at the locator this module builds and
    link its canonical product page. Both are the publisher's absolute or
    host-relative spellings resolved against the index URL.
    """
    check_byte_bound(max_bytes, "max_bytes", MAX_REPORT_FILE_BYTES)
    locator = gao_report_index_locator(product_id)
    if not body:
        raise GaoReportFileSourceError("GAO report index must be a nonempty document")
    if len(body) > max_bytes:
        raise GaoReportFileSourceError("GAO report index exceeds its byte bound")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GaoReportFileSourceError("GAO report index is not valid UTF-8") from error
    pdf_url = gao_report_pdf_locator(product_id)
    product_url = gao_product_url(product_id)
    scanner = _IndexScanner(locator, product_url)
    scanner.feed(text)
    scanner.close()
    if pdf_url not in scanner.pdf_urls:
        raise GaoReportFileSourceError("GAO report index does not link its report PDF")
    if not scanner.links_product:
        raise GaoReportFileSourceError("GAO report index does not link its canonical product page")
    title = "".join(scanner.title_parts).strip() or None
    return GaoReportIndex(product_id, locator, title, pdf_url, product_url)


def validate_gao_report_pdf(
    capture: CapturedBodyResponse, *, product_id: str, rendition: str = "report"
) -> GaoReportPdf:
    """Prove PDF identity in O(1) beyond the capture: magic, end marker and the final URL.

    The media type is checked by the acquirer against ``PDF_MEDIA_TYPES``; the
    file host states ``application/octet-stream``, so the bytes carry the proof.
    """
    locator = gao_report_pdf_locator(product_id, rendition=rendition)
    if capture.requested_url != locator:
        raise GaoReportFileSourceError("GAO report file final URL differs from its locator")
    check_final_url(
        capture.resolved_url,
        locator,
        error_type=GaoReportFileSourceError,
        message="GAO report file final URL differs from its locator",
    )
    version = check_pdf_bytes(capture.body, error_type=GaoReportFileSourceError, label="GAO report file")
    return GaoReportPdf(product_id, rendition, locator, version)


@dataclass(frozen=True, slots=True)
class GaoReportFileBudget:
    max_requests: int
    max_index_bytes: int
    max_pdf_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_index_bytes, "max_index_bytes", MAX_REPORT_FILE_BYTES)
        check_byte_bound(self.max_pdf_bytes, "max_pdf_bytes", MAX_REPORT_FILE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class GaoReportFileAcquisition:
    """What one operation observed. ``index`` is absent unless the online report was captured."""

    product_id: str
    pdf: GaoReportPdf
    pdf_capture: CapturedBodyResponse
    index: GaoReportIndex | None
    index_capture: CapturedBodyResponse | None
    request_count: int
    budget: GaoReportFileBudget


class GaoReportFileAcquirer(SourceAcquirer):
    """Keyless capture of one product's report file. Product pages stay a Zyte capture."""

    def __init__(
        self,
        *,
        budget: GaoReportFileBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, GaoReportFileBudget):
            raise TypeError("budget must be a GaoReportFileBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-gao-files/1.0",
            label="GAO report file",
            error_type=GaoReportFileSourceError,
            context_key="gao_report_file_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> GaoReportFileBudget:
        return self._budget

    def capture_report_index(self, product_id: str) -> tuple[GaoReportIndex, CapturedBodyResponse]:
        """One request for the online report. Absent online reports answer 403, not 404."""
        locator = gao_report_index_locator(product_id)
        return self.capture_validated(
            locator,
            media_types=INDEX_MEDIA_TYPES,
            parse=lambda response, limit: parse_gao_report_index(response.body, product_id=product_id, max_bytes=limit),
            max_bytes=self.budget.max_index_bytes,
            unavailable=GaoReportFileUnavailableError,
            context={"operation": "report-index", "productId": product_id, "url": locator},
        )

    def capture_report_pdf(
        self, product_id: str, *, rendition: str = "report"
    ) -> tuple[GaoReportPdf, CapturedBodyResponse]:
        """One request for the PDF at the locator this module builds."""
        expected = gao_report_pdf_locator(product_id, rendition=rendition)
        return self.capture_validated(
            expected,
            media_types=PDF_MEDIA_TYPES,
            parse=lambda response, _limit: validate_gao_report_pdf(
                response, product_id=product_id, rendition=rendition
            ),
            max_bytes=self.budget.max_pdf_bytes,
            unavailable=GaoReportFileUnavailableError,
            context={"operation": "report-pdf", "productId": product_id, "rendition": rendition, "url": expected},
        )

    def acquire_report_pdf(self, product_id: str, *, rendition: str = "report") -> GaoReportFileAcquisition:
        """The route every product has: one request, identity proved by the bytes."""
        pdf, capture = self.capture_report_pdf(product_id, rendition=rendition)
        return GaoReportFileAcquisition(product_id, pdf, capture, None, None, self.request_count, self.budget)

    def acquire_report_file(self, product_id: str, *, rendition: str = "report") -> GaoReportFileAcquisition:
        """Two requests: the online report, which states its own PDF URL, then that PDF.

        The index parse refuses unless the publisher names exactly the URL
        :func:`gao_report_pdf_locator` builds, so the capture that follows is
        the publisher's stated locator and not a guess.
        """
        index, index_capture = self.capture_report_index(product_id)
        requests = self.request_count
        pdf, pdf_capture = self.capture_report_pdf(product_id, rendition=rendition)
        return GaoReportFileAcquisition(
            product_id, pdf, pdf_capture, index, index_capture, requests + self.request_count, self.budget
        )
