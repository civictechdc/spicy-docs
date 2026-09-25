"""FERC eLibrary DownloadPDF: one bounded generated PDF per accession, POSTed exactly as the SPA posts it.

The route is bundle-derived (``main.js``, captured 2026-09-24): the download
service POSTs ``{API}/File/DownloadPDF?accesssionNumber={accession}`` -- the
publisher's own misspelled query parameter -- with one JSON body:

* ``{"serverLocation": ""}`` -- the accession entry point. Measured live
  2026-09-24 for the public accession ``20251125-3057`` (a letter order under
  ER25-3543): ``200 application/pdf``, a generated seven-page PDF, no wall, no
  redirect. This one POST is the common case.
* ``{"serverLocation": location}`` -- the follow-up the SPA sends after the
  first POST answered 400 with a JSON body naming ``ServerLocation`` (the SPA's
  ``blobToString`` error path). This acquirer follows the same two-step
  contract: exactly one follow-up carrying the location the publisher named,
  within the same operation's request budget. A 400 that names no usable
  location is a publisher refusal with its body retained as evidence.

House rules mirrored from the regulations.gov/FCC attachment routes: bounded
bytes (16 MiB default, 640 MiB cap -- the measured regulations.gov bounds,
carried until a FERC campaign restates them), PDF magic and trailer proved
through :mod:`spicy_docs.reading.pdf_bytes`, only 404/410 naming absence, a 200
with an empty body recorded as ``requested_empty`` and never skipped, refusal
evidence retained, error text scrubbed before truncation.

The shared ``walled_fetch`` ladder is not climbed because none of its rungs can
express a POST, and this route is POST-only per the bundle. Wall detection still
reuses :func:`~spicy_docs.sources.walled_fetch.detect_wall`, the one canonical
wall vocabulary, so a wall is named (``client-rejected``) instead of read as
bytes or absence. If this host ever walls this route, a POST-capable rung belongs
in the shared ladder, not here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.sources.ferc.elibrary import (
    API,
    BROWSER_USER_AGENT,
    FercElibraryError,
    accession_number,
    elibrary_transport,
)
from spicy_docs.sources.walled_fetch import detect_wall
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, attached_capture, refused_capture
from spicy_docs.transport.credentials import CredentialRefusedError, failure_reason
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

DEFAULT_MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 640 * 1024 * 1024
#: The route generates PDFs, so the answer is a PDF or an octet-stream; the
#: magic check, not the media type, is the gate (measured live: application/pdf).
DOWNLOAD_MEDIA_TYPES = ("application/pdf", "application/octet-stream")
#: Captured only so a wall page or a JSON answer is named before the PDF media-type refusal.
_ANSWER_MEDIA_TYPES = (*DOWNLOAD_MEDIA_TYPES, "application/json", "text/html", "text/plain")
#: The SPA's two-step contract is the whole operation's budget, retries included.
_MAX_REQUESTS = 2

type DownloadRefusalKind = Literal["client-rejected", "redirected", "publisher-refused"]


def pdf_download_url(accession: str) -> str:
    """The DownloadPDF locator for one accession, with the publisher's own misspelled parameter."""
    return f"{API}/File/DownloadPDF?accesssionNumber={accession_number(accession)}"


def pdf_download_body(server_location: str = "") -> bytes:
    """One DownloadPDF request body, spelled field for field as the SPA sends it."""
    if not isinstance(server_location, str):
        raise FercElibraryError("server_location must be a string")
    return json.dumps({"serverLocation": server_location}, separators=(",", ":")).encode("utf-8")


def usable_server_location(body: bytes) -> str | None:
    """The non-empty ``ServerLocation`` string a 400 answer names, else ``None`` (a publisher refusal)."""
    try:
        value = json.loads(body) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    location = value.get("ServerLocation") if isinstance(value, dict) else None
    return location if isinstance(location, str) and location.strip() else None


class FercElibraryDownloadError(FercElibraryError):
    """The DownloadPDF answer cannot establish the requested PDF."""


class FercElibraryDownloadUnavailableError(FercElibraryDownloadError):
    """Only the exact requested download answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"FERC eLibrary DownloadPDF answered HTTP {capture.status_code} for the requested accession")
        self.capture = capture


class FercElibraryDownloadRefusedError(CredentialRefusedError):
    """The download refused the request, and which refusal: never an observation that the file is absent.

    A ``CredentialRefusedError`` subclass on purpose: this host holds no credential,
    but a refusal still ends the operation, so callers that abort on one keep
    aborting. The refused body stays on ``refused_response``.
    """

    def __init__(self, accession: str, kind: DownloadRefusalKind) -> None:
        meaning = {
            "client-rejected": "the edge rejected this client, so the request never reached the file",
            "redirected": "the host redirected this URL, which states nothing about the file existing at it",
            "publisher-refused": "the publisher refused this accession without naming a server location",
        }[kind]
        super().__init__(
            f"FERC eLibrary DownloadPDF refused {accession}: {meaning}; this is not an observation that the file is absent"
        )
        self.accession = accession
        self.refusal_kind = kind


def _refusal(
    accession: str, kind: DownloadRefusalKind, capture: CapturedBodyResponse
) -> FercElibraryDownloadRefusedError:
    error = FercElibraryDownloadRefusedError(accession, kind)
    attach_capture(error, capture)
    attach_refused_response(error, refused_capture(capture, stage="source-validation"))
    return error


@dataclass(frozen=True, slots=True)
class FercElibraryDownloadBudget:
    """One download's limits: bytes, per-POST timeout, and the pace between POSTs."""

    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_byte_bound(self.max_bytes, "max_bytes", MAX_DOWNLOAD_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class DownloadAcquisition:
    """The generated PDF bytes and every POST that produced them.

    ``request_count`` counts the attempts made, retries included; ``captures``
    retains each answered POST in order and ``capture`` is the last. A failed
    acquisition carries its completed captures on the raised error's ``captures``.
    """

    accession: str
    capture: CapturedBodyResponse
    request_count: int
    budget: FercElibraryDownloadBudget
    requested_empty: bool
    captures: tuple[CapturedBodyResponse, ...]

    @property
    def sha256(self) -> str:
        return self.capture.sha256


class FercElibraryDownloadAcquirer(SourceAcquirer):
    """Keyless capture of one accession's generated PDF: one POST, or the SPA's two-step, per call."""

    def __init__(
        self,
        *,
        budget: FercElibraryDownloadBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, FercElibraryDownloadBudget):
            raise TypeError("budget must be a FercElibraryDownloadBudget")
        self.budget = budget
        super().__init__(
            max_requests=_MAX_REQUESTS,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=BROWSER_USER_AGENT,
            label="FERC eLibrary DownloadPDF",
            error_type=FercElibraryDownloadError,
            context_key="ferc_elibrary_download_acquisition",
            transport=elibrary_transport(transport),
            clock=clock,
            keyless=True,
        )

    def acquire(self, accession: str, *, max_bytes: int | None = None) -> DownloadAcquisition:
        """Capture one accession's generated PDF; a 400 naming a server location gets one follow-up POST.

        Only 404/410 is the host saying the exact accession has nothing. A wall, a
        401/403, a redirect, or a 400 naming no usable location raises the named
        refusal; a 200 with an empty body returns ``requested_empty``.
        """
        identity = accession_number(accession)
        url = pdf_download_url(identity)
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        context = {"operation": "download-pdf", "url": url, "accession": identity, "maxBytes": limit}
        captures: list[CapturedBodyResponse] = []
        try:
            answer = self._post(url, pdf_download_body(), identity, limit, context, captures, first=True)
            if isinstance(answer, str):
                answer = self._post(url, pdf_download_body(answer), identity, limit, context, captures, first=False)
        except Exception as error:
            error.__dict__[self.context_key] = {**context, "requestCount": self.request_count}
            error.__dict__["captures"] = tuple(captures)
            raise
        return DownloadAcquisition(identity, captures[-1], self.request_count, self.budget, answer, tuple(captures))

    def _post(
        self,
        url: str,
        body: bytes,
        accession: str,
        limit: int,
        context: dict[str, object],
        captures: list[CapturedBodyResponse],
        *,
        first: bool,
    ) -> bool | str:
        """One bounded POST: whether a 200 answered empty, or the server location a first 400 names."""
        from spicy_docs.transport.http import RetryableHTTPStatusError

        try:
            requested_empty, capture = self.capture_validated(
                url,
                media_types=_ANSWER_MEDIA_TYPES,
                parse=lambda capture, _limit: _check_body(capture, accession),
                max_bytes=limit,
                unavailable=FercElibraryDownloadUnavailableError,
                context=context,
                method="POST",
                content=body,
                request_headers={"Content-Type": "application/json"},
                reset_budget=first,
            )
        except (ConnectionError, RetryableHTTPStatusError) as error:
            raise FercElibraryDownloadError(
                f"FERC eLibrary DownloadPDF transport failed: {failure_reason(error)}"
            ) from error
        except CredentialRefusedError as error:
            refused = getattr(error, "refused_response", None)
            if (capture := attached_capture(error)) is not None:
                captures.append(capture)
            if isinstance(error, FercElibraryDownloadRefusedError):
                raise
            wall = detect_wall(getattr(refused, "response_bytes", None) or b"") is not None
            named = FercElibraryDownloadRefusedError(accession, "client-rejected" if wall else "publisher-refused")
            if refused is not None:
                named.__dict__["refused_response"] = refused
            raise named from error
        except FercElibraryDownloadError as error:
            capture = attached_capture(error)
            if capture is None:
                raise
            captures.append(capture)
            status = capture.status_code
            if status == 200:
                raise
            if first and status == 400 and (location := usable_server_location(capture.body)):
                return location
            kind: DownloadRefusalKind | None = (
                "client-rejected"
                if detect_wall(capture.body) is not None
                else "redirected"
                if 300 <= status < 400
                else "publisher-refused"
                if status == 400
                else None
            )
            if kind is None:
                raise
            raise _refusal(accession, kind, capture) from error
        captures.append(capture)
        return requested_empty


def _check_body(capture: CapturedBodyResponse, accession: str) -> bool:
    """A 200 answer: a wall is refused by name, then the media type and PDF magic gate; empty is ``requested_empty``."""
    if detect_wall(capture.body) is not None:
        raise _refusal(accession, "client-rejected", capture)
    if bare_media_type(capture.content_type) not in DOWNLOAD_MEDIA_TYPES:
        raise FercElibraryDownloadError(
            f"FERC eLibrary DownloadPDF answer Content-Type {capture.content_type!r} is not a PDF download type"
        )
    if not capture.body:
        return True
    check_pdf_bytes(capture.body, error_type=FercElibraryDownloadError, label="FERC eLibrary DownloadPDF body")
    return False


__all__ = [
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "DOWNLOAD_MEDIA_TYPES",
    "MAX_DOWNLOAD_BYTES",
    "DownloadAcquisition",
    "DownloadRefusalKind",
    "FercElibraryDownloadAcquirer",
    "FercElibraryDownloadBudget",
    "FercElibraryDownloadError",
    "FercElibraryDownloadRefusedError",
    "FercElibraryDownloadUnavailableError",
    "pdf_download_body",
    "pdf_download_url",
    "usable_server_location",
]
