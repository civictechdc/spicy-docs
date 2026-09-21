"""CRS report files on congress.gov: keyless PDF and HTML for one explicit report.

``listing.py`` names the reports and ``crs_summaries.py`` fetches their
metadata (both keyed); the file itself sits on the public web route
``.../crs_external_products/{family}/PDF/{id}/{id}.{version}.pdf``, which
serves without a key. ``HEAD`` answers 403 while ``GET`` serves, so this module
only ever issues ``GET``. The PDF route carries no identity inside the bytes,
so identity is the request itself, proved three ways -- the
``application/pdf`` media type, the ``%PDF-`` magic, and a final URL equal to
the locator; a 200 that is not a PDF is a refusal with its bytes retained,
never data and never absence. The family segment is usually the id's alphabetic
prefix but not always (80 ``RL`` reports are filed under ``RA``, and the
legacy ``98-807``-style ids carry none), so prefer the publisher's stated URL;
``family_from_report_id`` is an inference that fails loudly as a 404, never as
data. Superseded versions stay available, so a version selects one specific
file and a version never issued is a 404.

The publisher's ``formats[]`` also states an HTML URL -- one current file per
report, with no per-id directory and no version segment. Congress.gov's
keyless bot wall answers that route inconsistently request to request (three
of six repeated request pairs flipped status, measured 2026-09-19), so HTML is
preferred but never trusted: ``acquire_report`` tries it once and falls back
to the versioned PDF under the same request budget on any refusal, carrying
the refused capture as ``html_refusal`` so the fallback stays auditable. The
HTML carries no version of its own, so it can only ever stand in for the
version the same ``formats[]`` read called current -- ``CrsReportSelection``
freezes that pairing -- and its identity is the report id stated twice
independently, the ``class="CoverDate"`` element and the ``data-prod-type``
attribute, read through ``reading/markup.py``'s events rather than a raw
substring search, so a citation in another report's prose cannot satisfy it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from spicy_docs.reading.markup import HTML_VOID_TAGS, MarkupEvent, MarkupReadError, read_html_events
from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    limit_byte_bound,
    named_challenge,
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


class CrsHtmlRefusedError(CrsFileSourceError):
    """The keyless HTML route answered 401/403; there is no credential here to reject.

    The bot wall answers inconsistently -- the exact same request can answer
    200 once and 403 the next attempt -- so ``named_challenge`` recasts that
    refusal into this error so it is catchable as a ``CrsFileSourceError``,
    its body retained as evidence on ``refused_response``, rather than letting
    it escape as ``CredentialRefusedError`` (which only the PDF route's
    ``HEAD`` probe triggers today).
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"CRS HTML source refused access to {url}; no credential exists to reject")
        self.url = url


def _limit(max_bytes: object) -> int:
    return limit_byte_bound(max_bytes, name="max_bytes", cap=MAX_CRS_FILE_BYTES, error_type=CrsFileSourceError)


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
    """Infer the family from the id prefix. Right for most reports, wrong for the ``RL``-under-``RA`` case.

    Impossible for the 224 legacy ``NN-NNN`` ids, which this refuses. Use it
    only when the report's stated PDF URL is not at hand; a wrong inference
    answers 404, never data.
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
class CrsReportSelection:
    """One report, as one ``formats[]`` response named it.

    ``pdf`` carries the version that response called current. ``html``, when
    the publisher stated one, was read from the very same response, so it can
    only ever stand in for that same version -- never a caller-chosen
    historical one paired in after the fact. Build this with
    ``crs_report_selection(formats)`` from the publisher's own array;
    constructing it directly still checks that both name the same report, so
    the mismatch a caller assembling ``CrsFileSelection`` and
    ``CrsHtmlSelection`` by hand could otherwise make is structurally
    impossible here.
    """

    pdf: CrsFileSelection
    html: CrsHtmlSelection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pdf, CrsFileSelection):
            raise CrsFileSourceError("pdf must be a CrsFileSelection")
        if self.html is not None:
            if not isinstance(self.html, CrsHtmlSelection):
                raise CrsFileSourceError("html must be a CrsHtmlSelection or None")
            if (self.html.family, self.html.report_id) != (self.pdf.family, self.pdf.report_id):
                raise CrsFileSourceError("pdf and html select different reports")


def crs_report_selection(formats: Sequence[Mapping[str, object]]) -> CrsReportSelection:
    """Build one report's selection from its ``crsreport/{id}`` ``formats[]`` array.

    Reads exactly what the publisher stated in one response: the ``PDF`` entry
    names the current version and the ``HTML`` entry, when present, is paired
    with that same version because both came from the same read. A caller with
    only a stated URL in hand still has
    ``crs_file_selection``/``crs_html_selection`` directly, but assembling a
    ``CrsReportSelection`` from two separately-fetched URLs risks pairing a
    current HTML rendition with a different report's or a different moment's
    PDF version; reading both from one array cannot.
    """
    if isinstance(formats, (str, bytes)) or not isinstance(formats, Sequence):
        raise CrsFileSourceError("formats must be the report's formats[] sequence")
    by_format: dict[str, str] = {}
    for entry in formats:
        if not isinstance(entry, Mapping):
            raise CrsFileSourceError("formats must be a sequence of mappings")
        name, url = entry.get("format"), entry.get("url")
        if isinstance(name, str) and isinstance(url, str):
            by_format[name.upper()] = url
    if "PDF" not in by_format:
        raise CrsFileSourceError("formats states no PDF rendition")
    pdf = crs_file_selection(by_format["PDF"])
    html = crs_html_selection(by_format["HTML"]) if "HTML" in by_format else None
    return CrsReportSelection(pdf, html)


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


def _cover_date_text(events: tuple[MarkupEvent, ...]) -> str | None:
    """Text of the ``<div class="CoverDate">`` element alone -- the report's own cover line.

    Never a raw substring search over the whole body: a related report cited
    in this page's prose (``... see CRS Report (IF12853) ...``) states that
    other id in parentheses too, and must not be mistaken for this page's own
    cover line. Depth-tracked through the shared markup reader's events so
    the scope is exactly one element, regardless of what it nests.
    """
    depth: int | None = None
    parts: list[str] = []
    for event in events:
        if depth is None:
            if event.kind == "start" and event.name == "div" and dict(event.attributes).get("class") == "CoverDate":
                depth = 0
            continue
        if event.kind == "end":
            if depth == 0:
                return "".join(parts)
            depth -= 1
        elif event.kind == "start" and event.name not in HTML_VOID_TAGS:
            depth += 1
        elif event.kind == "text" and event.text:
            parts.append(event.text)
    return None


def _prod_type(events: tuple[MarkupEvent, ...]) -> str | None:
    """The ``data-prod-type`` attribute value, wherever the markup states it."""
    for event in events:
        if event.kind in ("start", "empty"):
            value = dict(event.attributes).get("data-prod-type")
            if value is not None:
                return value
    return None


def read_crs_html(
    body: bytes, selection: CrsHtmlSelection, *, final_url: str, max_bytes: int = DEFAULT_MAX_BYTES
) -> CrsReportHtml:
    """Prove the bytes are the one report's current HTML served by the locator.

    The route states no version, so identity rests on the report id alone --
    stated twice independently, the way the PDF path's two statements are
    independent of each other: the cover line's own ``class="CoverDate"``
    element spells the id in parentheses, and a ``data-prod-type`` attribute
    states the family. Both are read through ``reading/markup.py``'s parsed
    events, scoped to that one element, not a substring search over the whole
    page, which a citation to this id in another report's prose could
    otherwise satisfy. Both must agree with the selection, and the final URL
    must equal the locator. There is no version to check, which is why this
    rendition only ever stands in for a report's *current* file.
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
    try:
        events = read_html_events(body).events
    except MarkupReadError as error:
        raise CrsFileSourceError("CRS HTML does not parse as markup") from error
    cover_date = _cover_date_text(events)
    if cover_date is None or f"({selection.report_id})" not in cover_date:
        raise CrsFileSourceError("CRS HTML does not state the requested report id")
    if _prod_type(events) != selection.family:
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


@dataclass(frozen=True, slots=True)
class CrsReportAcquisition:
    """One report, in whichever rendition congress.gov actually served -- and why, when it was not HTML.

    Exactly one of ``html``/``pdf`` is set, matching ``rendition``.
    ``html_skipped_reason`` and ``html_refusal`` are mutually exclusive and
    both ``None`` when ``rendition == "html"``: the former is set when HTML
    was never attempted at all (a superseded version was requested, or the
    report states none), the latter when HTML *was* attempted and the
    publisher refused it -- so the fallback stays auditable from the result
    itself, not only from a caught and discarded exception.
    """

    rendition: Literal["html", "pdf"]
    html: CrsReportHtml | None
    pdf: CrsReportPdf | None
    capture: CapturedBodyResponse
    html_refusal: RefusedResponse | None
    html_skipped_reason: str | None
    request_count: int
    budget: CrsFileBudget


class CrsFileAcquirer(SourceAcquirer):
    """Keyless capture of one CRS report file. Summaries stay the separate, keyed fetch.

    ``acquire_report`` prefers the current HTML rendition for the version its
    ``CrsReportSelection`` calls current, and always uses the versioned PDF
    route for any other version or when the publisher states no HTML.
    ``acquire_report_pdf``/``acquire_report_html`` remain available directly
    for finer control over a single rendition.
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
        """One GET for the report's current HTML. Refused more often than the PDF route, and non-deterministically.

        Congress.gov's keyless bot wall is inconsistent request to request,
        not just report to report: repeated identical requests flipped status
        between passes (module docstring). A caller that must have a body
        should use ``acquire_report`` rather than treating a refusal here as
        the report having no HTML.

        A 401/403 is recast as ``CrsHtmlRefusedError`` by ``named_challenge``
        (this route is keyless, so it is a bot wall, not a credential being
        rejected) rather than escaping as ``CredentialRefusedError`` --
        consistent with this repo's other keyless families.
        """
        locator = crs_html_locator(selection)
        effective = replace(self.budget, max_bytes=narrow_byte_limit(self.budget.max_bytes, max_bytes))

        with named_challenge(locator, error_type=CrsHtmlRefusedError, context_key=self.context_key):
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

    def _report_from_pdf(
        self,
        pdf_selection: CrsFileSelection,
        *,
        max_bytes: int | None,
        reset_budget: bool = True,
        html_refusal: RefusedResponse | None = None,
        html_skipped_reason: str | None = None,
    ) -> CrsReportAcquisition:
        pdf = self.acquire_report_pdf(pdf_selection, max_bytes=max_bytes, reset_budget=reset_budget)
        return CrsReportAcquisition(
            rendition="pdf",
            html=None,
            pdf=pdf.file,
            capture=pdf.capture,
            html_refusal=html_refusal,
            html_skipped_reason=html_skipped_reason,
            request_count=pdf.request_count,
            budget=pdf.budget,
        )

    def acquire_report(
        self,
        selection: CrsReportSelection,
        *,
        version: int | None = None,
        max_bytes: int | None = None,
    ) -> CrsReportAcquisition:
        """Prefer the current HTML rendition; fall back to the versioned PDF on any refusal.

        ``version`` defaults to ``selection.pdf.version`` -- the version the
        same ``formats[]`` read called current, the only version HTML can
        stand in for, since the route states no version of its own. A request
        for any other version is routed straight to the PDF route, and
        ``html_skipped_reason`` on the result says why, making a caller-pinned
        historical version silently answered with today's HTML structurally
        impossible rather than a rule a caller has to remember.

        A refusal fetching HTML -- the bot wall, an unexpected shape, a
        missing identity marker -- is not a hard failure: it falls back to the
        PDF route under the same request budget, and the refused capture is
        kept on the result as ``html_refusal`` so the fallback stays
        auditable. Only a PDF-route failure (or an exhausted budget)
        propagates.
        """
        if not isinstance(selection, CrsReportSelection):
            raise CrsFileSourceError("selection must be a CrsReportSelection")
        current = selection.pdf.version
        requested = current if version is None else version
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise CrsFileSourceError("version must be an integer")
        pdf_selection = (
            selection.pdf
            if requested == current
            else CrsFileSelection(selection.pdf.family, selection.pdf.report_id, requested)
        )

        if selection.html is None:
            return self._report_from_pdf(
                pdf_selection, max_bytes=max_bytes, html_skipped_reason="the report states no HTML rendition"
            )
        if requested != current:
            reason = f"version {requested} was requested; HTML only stands in for the current version {current}"
            return self._report_from_pdf(pdf_selection, max_bytes=max_bytes, html_skipped_reason=reason)

        try:
            html = self.acquire_report_html(selection.html, max_bytes=max_bytes)
        except CrsFileSourceError as error:
            refusal = getattr(error, "refused_response", None)
            html_refusal = refusal if isinstance(refusal, RefusedResponse) else None
            return self._report_from_pdf(
                pdf_selection, max_bytes=max_bytes, reset_budget=False, html_refusal=html_refusal
            )
        return CrsReportAcquisition(
            rendition="html",
            html=html.html,
            pdf=None,
            capture=html.capture,
            html_refusal=None,
            html_skipped_reason=None,
            request_count=html.request_count,
            budget=html.budget,
        )
