"""CRS report files on congress.gov: keyless PDF and HTML for one explicit report.

``listing.py`` names the reports and ``crs_summaries.py`` fetches their
metadata; both need the api.data.gov key and neither carries the file. The file
lives on the public web route
``https://www.congress.gov/crs_external_products/{family}/PDF/{id}/{id}.{version}.pdf``,
which is served without a key and without a browser user agent. ``HEAD`` on it
answers 403 while ``GET`` serves, so this module only ever issues ``GET``.

The PDF route carries no identity inside the bytes: a CRS PDF states no report
id a reader can check. Identity is therefore the request itself, proved three
ways — the publisher's ``application/pdf`` media type, the ``%PDF-`` magic, and
a final URL equal to the locator. A 200 that is not a PDF is a refusal with its
bytes retained, never data and never absence. ``validate_body_prefix`` is not
called here: it belongs to the streamed download path and only rejects HTML,
which the magic check already subsumes.

Two facts measured over 13,970 publisher-stated PDF URLs (the ``formats`` rows
of `receipts/crs-summaries-2026-09-07.jsonl`, 2026-09-07) shape the selection:

* The family segment is usually the id's alphabetic prefix, but 80 ``RL`` reports
  are filed under ``RA``, and the 224 legacy ``98-807``-style ids carry no prefix
  at all. Prefer the publisher's stated URL; ``family_from_report_id`` is an
  inference that fails loudly as a 404, never as data.
* Superseded versions stay available, so a version need not be the one the CRS
  list states; it selects one specific file. A version never issued is a 404.

Evidence: `corpora/supply-2026-09-02/receipts/port-P03-crs-files-2026-09-14/`.

**HTML.** The publisher's ``formats[]`` also states an HTML URL,
``.../{family}/HTML/{id}.html`` — no per-id directory and, unlike the PDF
route, no version segment: congress.gov serves exactly one HTML file per
report, whichever version is current. Measured 2026-09-19, bounded to eight
requests (two reports' ``crsreport/{id}`` metadata, then three header variants
each against the stated HTML URL — the file route's own client headers, the
same Accept/User-Agent built with default transport settings, and a
browser-like Accept): IF12853 answered 200 on all three variants; IF11830
answered 200 on one of three and 403 (a bot-wall page, kept as evidence) on
the other two, including the literal replica of this module's own client. So
the route is real but not reliably reachable keyless — HTML is preferred, but
every attempt falls back to the versioned PDF route rather than raising, and
`acquire_report_pdf` alone remains the only way to reach a specific
superseded version. The HTML carries no version of its own, so identity is
the report id, stated twice independently in the bytes (the cover line's
parenthesized id and the ``data-prod-type`` family marker) plus the final URL.
Evidence: `docs/sources/crs-files.md`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

CRS_EXTERNAL_PRODUCTS = "https://www.congress.gov/crs_external_products"
PDF_MEDIA_TYPE = "application/pdf"
HTML_MEDIA_TYPE = "text/html"
#: The largest retained CRS PDF is 2.1 MB; the largest fetched on 2026-09-14 was 1.5 MB.
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
MAX_CRS_FILE_BYTES = 64 * 1024 * 1024
#: Observed versions run 1..427 over 13,970 reports.
MAX_VERSION = 9999

#: Families observed: R, RL, RS, RA, IF, IN, LSB, TE, IG. A report's stated URL may name another.
_FAMILY = re.compile(r"[A-Z]{1,4}")
#: 13,753 ids are an uppercase prefix and exactly five digits; 224 are legacy ``NN-NNN``.
_REPORT_ID = re.compile(r"[A-Z]{1,4}[0-9]{1,6}|[0-9]{2}-[0-9]{2,4}")
_ID_PREFIX = re.compile(r"([A-Z]{1,4})[0-9]{1,6}")
_STATED_URL = re.compile(
    rf"{re.escape(CRS_EXTERNAL_PRODUCTS)}/(?P<family>[A-Z]{{1,4}})/PDF/"
    rf"(?P<directory>{_REPORT_ID.pattern})/(?P<stem>{_REPORT_ID.pattern})\.(?P<version>[0-9]{{1,4}})\.pdf"
)
#: No per-id directory and no version segment: congress.gov serves one current HTML file per report.
_HTML_STATED_URL = re.compile(
    rf"{re.escape(CRS_EXTERNAL_PRODUCTS)}/(?P<family>[A-Z]{{1,4}})/HTML/(?P<stem>{_REPORT_ID.pattern})\.html"
)
#: Each file is signed; ``/ByteRange [0 a b c]`` sits in the first 4 KiB and ``b + c`` is the file size.
_BYTE_RANGE = re.compile(rb"/ByteRange\s*\[\s*[0-9]+\s+[0-9]+\s+([0-9]+)\s+([0-9]+)\s*\]")
_HEADER_WINDOW = 4096


class CrsFileSourceError(ValueError):
    """The request or response cannot establish the selected CRS report file."""


class CrsFileUnavailableError(CrsFileSourceError):
    """Only the exact requested locator has answered 404/410.

    Congress.gov answers a missing id, a missing version, a wrong family and a
    lowercase family with the same 404 HTML page, so this never means the report
    is absent; it means this locator held no file when asked.
    """

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"CRS file source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def _limit(max_bytes: object) -> int:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_CRS_FILE_BYTES:
        raise CrsFileSourceError("max_bytes must be a positive integer no greater than 64 MiB")
    return max_bytes


@dataclass(frozen=True, slots=True)
class CrsFileSelection:
    """One file: the publisher's family path segment, report id and version.

    ``family`` is the publisher's spelling and is case-sensitive; ``if`` in place
    of ``IF`` answered 404. It is not always the id's prefix, so take it from the
    report's stated PDF URL when there is one.
    """

    family: str
    report_id: str
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or _FAMILY.fullmatch(self.family) is None:
            raise CrsFileSourceError("family must be the publisher's uppercase path segment, such as 'IF' or 'RA'")
        if not isinstance(self.report_id, str) or _REPORT_ID.fullmatch(self.report_id) is None:
            raise CrsFileSourceError("report_id must be a CRS id such as 'IF11830' or the legacy '98-807'")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or not 1 <= self.version <= MAX_VERSION:
            raise CrsFileSourceError(f"version must be an integer from 1 to {MAX_VERSION}")

    @property
    def file_name(self) -> str:
        return f"{self.report_id}.{self.version}.pdf"


def crs_file_locator(selection: CrsFileSelection) -> str:
    if not isinstance(selection, CrsFileSelection):
        raise CrsFileSourceError("selection must be a CrsFileSelection")
    return f"{CRS_EXTERNAL_PRODUCTS}/{selection.family}/PDF/{selection.report_id}/{selection.file_name}"


def crs_file_selection(stated_url: str) -> CrsFileSelection:
    """Read the publisher's own PDF URL, as the CRS detail row spells it in ``formats``.

    This is the exact route, not an inference. The directory and the file stem
    must both equal the report id, as they did in all 13,970 stated URLs.
    """
    if not isinstance(stated_url, str):
        raise CrsFileSourceError("stated_url must be a string")
    match = _STATED_URL.fullmatch(stated_url)
    if match is None:
        raise CrsFileSourceError("stated_url is not a congress.gov CRS report PDF URL")
    if match["directory"] != match["stem"]:
        raise CrsFileSourceError("stated_url names different report ids in its directory and file name")
    return CrsFileSelection(match["family"], match["stem"], int(match["version"]))


def family_from_report_id(report_id: str) -> str:
    """Infer the family from the id prefix. Right for 13,890 of 13,970 retained reports.

    Wrong for the 80 ``RL`` reports filed under ``RA`` (``RL/PDF/RL31312/…``
    answered 404 while ``RA/PDF/RL31312/…`` served), and impossible for the 224
    legacy ``NN-NNN`` ids, which this refuses. Use it only when the report's
    stated PDF URL is not at hand; a wrong inference answers 404.
    """
    if not isinstance(report_id, str) or _REPORT_ID.fullmatch(report_id) is None:
        raise CrsFileSourceError("report_id must be a CRS id such as 'IF11830' or the legacy '98-807'")
    prefix = _ID_PREFIX.fullmatch(report_id)
    if prefix is None:
        raise CrsFileSourceError("a legacy CRS id states no family; take it from the report's stated PDF URL")
    return prefix[1]


@dataclass(frozen=True, slots=True)
class CrsHtmlSelection:
    """The current HTML rendition of one report: no version, because the route carries none.

    Congress.gov serves exactly one HTML file per report, at
    ``{family}/HTML/{report_id}.html`` — always whichever version is current.
    A caller that needs one specific, possibly superseded version must use
    ``CrsFileSelection`` and the PDF route; this selection cannot express one.
    """

    family: str
    report_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or _FAMILY.fullmatch(self.family) is None:
            raise CrsFileSourceError("family must be the publisher's uppercase path segment, such as 'IF' or 'RA'")
        if not isinstance(self.report_id, str) or _REPORT_ID.fullmatch(self.report_id) is None:
            raise CrsFileSourceError("report_id must be a CRS id such as 'IF11830' or the legacy '98-807'")

    @property
    def file_name(self) -> str:
        return f"{self.report_id}.html"


def crs_html_locator(selection: CrsHtmlSelection) -> str:
    if not isinstance(selection, CrsHtmlSelection):
        raise CrsFileSourceError("selection must be a CrsHtmlSelection")
    return f"{CRS_EXTERNAL_PRODUCTS}/{selection.family}/HTML/{selection.file_name}"


def crs_html_selection(stated_url: str) -> CrsHtmlSelection:
    """Read the publisher's own HTML URL, as the CRS detail row spells it in ``formats``."""
    if not isinstance(stated_url, str):
        raise CrsFileSourceError("stated_url must be a string")
    match = _HTML_STATED_URL.fullmatch(stated_url)
    if match is None:
        raise CrsFileSourceError("stated_url is not a congress.gov CRS report HTML URL")
    return CrsHtmlSelection(match["family"], match["stem"])


@dataclass(frozen=True, slots=True)
class CrsReportPdf:
    """What the bytes themselves state: the PDF version and the signed length, if present."""

    selection: CrsFileSelection
    pdf_version: str
    byte_size: int
    signed_byte_range_total: int | None


def read_crs_pdf(
    body: bytes, selection: CrsFileSelection, *, final_url: str, max_bytes: int = DEFAULT_MAX_BYTES
) -> CrsReportPdf:
    """Prove the bytes are one complete PDF served by the locator; refuse anything else by name.

    The bytes name no report, so the final URL is the identity and must equal
    the locator. Completeness then has two independent statements. Every CRS PDF
    ends ``%%EOF``. Each is also signed, and the signature's ``/ByteRange``
    states the whole file's length in the first 4 KiB; where it appears it must
    agree with what was captured. That proves the capture is whole, not that it
    is authentic: the number comes from the file being checked.
    """
    _limit(max_bytes)
    if not isinstance(selection, CrsFileSelection):
        raise CrsFileSourceError("selection must be a CrsFileSelection")
    check_final_url(
        final_url,
        crs_file_locator(selection),
        error_type=CrsFileSourceError,
        message="CRS file final URL differs from the requested locator",
    )
    if not isinstance(body, (bytes, bytearray)):
        raise CrsFileSourceError("body must be bytes")
    body = bytes(body)
    if len(body) > max_bytes:
        raise CrsFileSourceError("CRS file exceeds its byte bound")
    version = check_pdf_bytes(body, error_type=CrsFileSourceError, label="CRS file response")
    signed = _BYTE_RANGE.search(body, 0, _HEADER_WINDOW)
    total = int(signed[1]) + int(signed[2]) if signed else None
    if total is not None and total != len(body):
        raise CrsFileSourceError("CRS file length differs from the length its signature states")
    return CrsReportPdf(selection, version, len(body), total)


@dataclass(frozen=True, slots=True)
class CrsReportHtml:
    """What the bytes themselves state: the report id, twice over, never a version."""

    selection: CrsHtmlSelection
    byte_size: int


def read_crs_html(
    body: bytes, selection: CrsHtmlSelection, *, final_url: str, max_bytes: int = DEFAULT_MAX_BYTES
) -> CrsReportHtml:
    """Prove the bytes are the one report's current HTML served by the locator.

    The route states no version, so completeness and identity rest on the
    report id alone -- stated twice independently in the markup, the way the
    PDF path's two statements (magic and signed length) are independent of
    each other. The cover line spells the id in parentheses
    (``(IF12853)``) and a ``data-prod-type`` attribute near the foot of the
    document states the family. Both must agree with the selection, and the
    final URL must equal the locator. There is no version to check: a stale
    or ahead-of-metadata capture cannot be told apart from a fresh one by the
    bytes alone, which is why this rendition only ever stands in for a
    report's *current* file (module docstring).
    """
    _limit(max_bytes)
    if not isinstance(selection, CrsHtmlSelection):
        raise CrsFileSourceError("selection must be a CrsHtmlSelection")
    check_final_url(
        final_url,
        crs_html_locator(selection),
        error_type=CrsFileSourceError,
        message="CRS HTML final URL differs from the requested locator",
    )
    if not isinstance(body, (bytes, bytearray)):
        raise CrsFileSourceError("body must be bytes")
    body = bytes(body)
    if len(body) > max_bytes:
        raise CrsFileSourceError("CRS HTML exceeds its byte bound")
    if f"({selection.report_id})".encode() not in body:
        raise CrsFileSourceError("CRS HTML does not state the requested report id")
    if f'data-prod-type="{selection.family}"'.encode() not in body:
        raise CrsFileSourceError("CRS HTML does not state the requested report family")
    return CrsReportHtml(selection, len(body))


@dataclass(frozen=True, slots=True)
class CrsFileBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_CRS_FILE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class CrsFileAcquisition:
    selection: CrsFileSelection
    file: CrsReportPdf
    capture: CapturedBodyResponse
    request_count: int
    budget: CrsFileBudget


@dataclass(frozen=True, slots=True)
class CrsHtmlAcquisition:
    selection: CrsHtmlSelection
    html: CrsReportHtml
    capture: CapturedBodyResponse
    request_count: int
    budget: CrsFileBudget


class CrsFileAcquirer(SourceAcquirer):
    """Keyless capture of one CRS report file. Summaries stay the separate, keyed fetch.

    ``acquire_report`` prefers the current HTML rendition and falls back to
    the versioned PDF on any refusal; ``acquire_report_pdf`` alone reaches a
    specific, possibly superseded version, which HTML cannot express.
    """

    def __init__(
        self,
        *,
        budget: CrsFileBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, CrsFileBudget):
            raise TypeError("budget must be a CrsFileBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-crs-files/1.0",
            label="CRS file",
            error_type=CrsFileSourceError,
            context_key="crs_file_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> CrsFileBudget:
        return self._budget

    def acquire_report_pdf(
        self, selection: CrsFileSelection, *, max_bytes: int | None = None, reset_budget: bool = True
    ) -> CrsFileAcquisition:
        """One GET for one version. The caller keeps ``capture.body``; nothing is written here.

        ``reset_budget=False`` chains this request onto a budget
        ``acquire_report`` already started for the same operation, rather
        than granting it a fresh ``max_requests``.
        """
        locator = crs_file_locator(selection)
        effective = replace(self.budget, max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes))

        file, capture = self.capture_validated(
            locator,
            media_types=(PDF_MEDIA_TYPE,),
            parse=lambda response, limit: read_crs_pdf(
                response.body, selection, final_url=response.resolved_url, max_bytes=limit
            ),
            max_bytes=effective.max_bytes,
            unavailable=CrsFileUnavailableError,
            context={
                "operation": "crs-report-pdf",
                "selection": asdict(selection),
                "url": locator,
                "budget": asdict(effective),
            },
            reset_budget=reset_budget,
        )
        return CrsFileAcquisition(selection, file, capture, self.request_count, effective)

    def acquire_report_html(
        self, selection: CrsHtmlSelection, *, max_bytes: int | None = None, reset_budget: bool = True
    ) -> CrsHtmlAcquisition:
        """One GET for the report's current HTML. Refused more often than the PDF route.

        Measured 2026-09-19 (module docstring): congress.gov's keyless bot
        wall answers this route 200 for some requests and 403 for others
        against the very same report, so a caller that must have a body
        should use ``acquire_report`` rather than treating a refusal here as
        the report having no HTML.
        """
        locator = crs_html_locator(selection)
        effective = replace(self.budget, max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes))

        html, capture = self.capture_validated(
            locator,
            media_types=(HTML_MEDIA_TYPE,),
            parse=lambda response, limit: read_crs_html(
                response.body, selection, final_url=response.resolved_url, max_bytes=limit
            ),
            max_bytes=effective.max_bytes,
            unavailable=CrsFileUnavailableError,
            context={
                "operation": "crs-report-html",
                "selection": asdict(selection),
                "url": locator,
                "budget": asdict(effective),
            },
            reset_budget=reset_budget,
        )
        return CrsHtmlAcquisition(selection, html, capture, self.request_count, effective)

    def acquire_report(
        self,
        pdf_selection: CrsFileSelection,
        *,
        html_selection: CrsHtmlSelection | None = None,
        max_bytes: int | None = None,
    ) -> CrsHtmlAcquisition | CrsFileAcquisition:
        """Prefer the current HTML rendition; fall back to the versioned PDF on any refusal.

        ``html_selection`` should come from the same ``formats[]`` response as
        ``pdf_selection`` -- the HTML route carries no version, so it can only
        stand in for the report's *current* file, never a caller-pinned
        historical one. Pass ``html_selection=None`` (or omit it) for a
        historical version; this then behaves exactly like
        ``acquire_report_pdf``.

        A refusal fetching HTML -- the bot wall, an unexpected shape, a
        missing identity marker -- is not a hard failure: it falls back to
        the PDF route under the same request budget rather than raising.
        Only a PDF-route failure (or an exhausted budget) propagates.
        """
        if html_selection is not None:
            try:
                return self.acquire_report_html(html_selection, max_bytes=max_bytes)
            except (CredentialRefusedError, CrsFileSourceError):
                return self.acquire_report_pdf(pdf_selection, max_bytes=max_bytes, reset_budget=False)
        return self.acquire_report_pdf(pdf_selection, max_bytes=max_bytes)
