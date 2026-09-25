"""Comment-letter PDFs from ``comments.cftc.gov/Handlers/PdfHandler.ashx``, one bounded capture at a time.

The only locators this module accepts are the ``PdfHandler.ashx?id={fileId}``
URLs a comment's own detail page declares; it never builds one from a guessed
id, and it checks the grammar (HTTPS portal host, root handler path, exactly
one ``id``) before a request is made. The handler answered
``application/pdf`` on every capture this module's grammar was measured
against (2011-2025 era fixture URLs, provenance in
``docs/sources/cftc-comments.md``, plus six live 2026-09-24 captures in
receipt ``cftc-pdf-bounds-2026-09-24``),
but a media type is a publisher claim: the bytes must begin with ``%PDF-``
and end with a PDF trailer, exactly the check the regulations.gov attachment
route applies, because there the extension lied about three files in 2,736.

The same Cloudflare edge fronts this route as fronts the pages (measured
2026-09-24; see ``acquisition.py``) -- but its answer to a direct client is
intermittent on this route, not a fixed block: of the six letters in receipt
``cftc-pdf-bounds-2026-09-24``, five answered DIRECT cleanly and one walled
both DIRECT and Zyte before Firecrawl answered, and on the same day the
listing page answered DIRECT in one run and Zyte in the next -- so the
download always walks the shared ladder through
:meth:`~spicy_docs.transport.source_acquirer.SourceAcquirer.capture_walled`:
this acquirer's own client, Zyte ``httpResponseBody``, then Firecrawl
``rawBase64``, one bounded attempt per rung on one budget and pacing clock. A
body that starts ``%PDF-`` is never read as a wall (``detect_wall``); a clean
404/410 raises ``CftcPdfUnavailableError`` (the exact locator has nothing);
and ladder exhaustion raises ``CftcPdfRefusedError`` naming the block-page
shape the retained wall bytes show. This module's own gate (the declared media
type, the ``%PDF-`` magic, the trailer proof, the final URL and the byte caps)
reads every clean answer, and neither a wall nor a refusal is an observation
that the file is absent.

Bounds are runaway guards, not measured percentiles, and now pinned to a
live sample: the six letters of receipt ``cftc-pdf-bounds-2026-09-24``
measured 25,170-239,920 bytes (PDF 1.3-1.5), two orders of magnitude under
the default, so the default stays regulations.gov's 16 MiB (which covered
98.7% of that publisher's files) and the cap stays its measured maximum
(640 MiB). The sample is six letters; re-pin both bounds if a larger
campaign measures bigger letters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.sources.cftc_comments.acquisition import BROWSER_USER_AGENT, CftcPortalRefusedError
from spicy_docs.sources.cftc_comments.pages import (
    CftcCommentsSourceError,
    pdf_file_id,
    pdf_url,
)
from spicy_docs.sources.walled_fetch import Transport
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

PDF_MEDIA_TYPE = "application/pdf"
DEFAULT_MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 640 * 1024 * 1024


class CftcPdfError(CftcCommentsSourceError):
    """The locator or the response cannot establish the requested letter file."""


class CftcPdfUnavailableError(CftcPdfError):
    """Only the exact requested file answered 404/410; it never means the letter is absent."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"CFTC PDF handler answered HTTP {capture.status_code} for the requested file")
        self.capture = capture


class CftcPdfRefusedError(CftcPortalRefusedError):
    """The edge refused this client for the file; never an observation that the file is absent."""

    subject = "PDF handler"


@dataclass(frozen=True, slots=True)
class PdfLocator:
    """One publisher-declared handler URL, kept in the publisher's own spelling."""

    url: str
    file_id: int


def pdf_locator(file_url: object) -> PdfLocator:
    """Read one detail-page ``PdfHandler.ashx?id={n}`` link as a locator; refuse anything else."""
    return PdfLocator(url=file_url if isinstance(file_url, str) else "", file_id=pdf_file_id(file_url))


@dataclass(frozen=True, slots=True)
class PdfBudget:
    """Bounds for each file request; pacing persists across the client's captures.

    ``max_requests`` keeps its meaning as the operation's request-count cap:
    the walled-fetch ladder makes exactly one attempt per rung and never
    retries, so one acquisition attempts at most ``max_requests`` rungs and
    ``request_count`` reports the attempts actually made.
    """

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_PDF_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class PdfAcquisition:
    """Exact file bytes with the facts that tie them to the locator.

    ``transport`` names the ladder rung that answered, so a receipt cannot
    misattribute the bytes; ``request_id`` is the provider's own handle when a
    proxy rung answered; ``pdf_version`` is the version the bytes state.
    """

    locator: PdfLocator
    capture: CapturedBodyResponse
    request_count: int
    budget: PdfBudget
    transport: Transport
    request_id: str | None
    pdf_version: str

    @property
    def sha256(self) -> str:
        return self.capture.sha256


class CftcPdfAcquirer(SourceAcquirer):
    """Keyless, paced capture of one declared letter PDF per call, through the shared walled-fetch ladder.

    The ladder (this client, Zyte ``httpResponseBody``, Firecrawl
    ``rawBase64``) makes one bounded attempt per rung and returns the first
    clean answer. The bytes always pass this module's own gate, so a clean
    answer that is not a complete PDF refuses instead of being stored. Byte
    caps narrow per call, never raise. An injected ``transport`` carries the
    direct attempt.
    """

    def __init__(
        self,
        *,
        budget: PdfBudget,
        user_agent: str = BROWSER_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, PdfBudget):
            raise TypeError("budget must be a PdfBudget")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a nonempty string")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=user_agent,
            label="CFTC comment letter",
            error_type=CftcPdfError,
            context_key="cftc_pdf_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> PdfBudget:
        return self._budget

    def acquire_pdf(self, locator: PdfLocator | int, *, max_bytes: int | None = None) -> PdfAcquisition:
        """Capture one declared PDF, by locator or by its publisher file id; only a clean 404/410 says it has nothing."""
        target = pdf_locator(pdf_url(locator)) if isinstance(locator, int) else locator
        if not isinstance(target, PdfLocator):
            raise TypeError("acquire_pdf takes a PdfLocator or a publisher file id")
        if pdf_locator(target.url) != target:
            raise CftcPdfError("CFTC comment letter locator identity differs from its URL")
        limit = narrow_byte_limit(self._budget.max_bytes, max_bytes)

        def read(response: CapturedBodyResponse, _bound: int) -> str:
            return check_pdf_bytes(response.body, error_type=CftcPdfError, label=self.label)

        version, capture, answer = self.capture_walled(
            target.url,
            media_types=(PDF_MEDIA_TYPE,),
            parse=read,
            max_bytes=limit,
            unavailable=CftcPdfUnavailableError,
            context={"operation": "comment-letter-pdf", "url": target.url, "fileId": target.file_id, "maxBytes": limit},
            refusal=CftcPdfRefusedError,
        )
        return PdfAcquisition(
            locator=target,
            capture=capture,
            request_count=self.request_count,
            budget=self._budget,
            transport=answer.transport,
            request_id=answer.request_id,
            pdf_version=version,
        )
