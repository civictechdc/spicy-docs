"""FCC ECFS filing documents: one bounded file per publisher-declared download URL.

Each filings row carries ``documents[]`` entries of ``{src, filename}`` (an
express comment carries none), where ``src`` is one of two publisher grammars,
each validated in the publisher's own spelling:

* ``https://docs.fcc.gov/public/attachments/{filename}`` -- the FCC-generated
  documents. Measured live 2026-09-24, a direct GET of ``DA-26-1030A1.pdf``
  answered ``200 application/pdf`` with no wall, and the exact bytes -- all
  125,605 of them, beginning ``%PDF-1.7`` -- are pinned in the firecrawl client
  smoke receipts (``supply-2026-09-02/receipts/
  firecrawl-client-smoke-2026-09-24``). The filename is the document's
  identity: it is the dedupe key, and an entry whose declared filename
  disagrees with the URL's own refuses.
* ``https://www.fcc.gov/ecfs/document/{id_submission}/{document index}`` -- the
  filer uploads. This locator serves the ECFS viewer application, not the
  file: measured live 2026-09-24, the URL answered a ~1,374-byte ``text/html``
  React shell carrying ``<div id="root">`` to both proxy providers (receipts
  ``supply-2026-09-02/receipts/zyte-client-smoke-2026-09-24`` and
  ``firecrawl-client-smoke-2026-09-24``), and no proxy returns the file from
  that URL. The shell's own JavaScript requests the file bytes from
  ``/ecfs/documents/{id_submission}/{index}`` (plural ``documents``, same
  host) as an ``arraybuffer`` and renders them through a ``blob:`` object
  URL. Measured live 2026-09-24 by reading the current bundle
  (``main.63eee072.js``) and its document-view chunk
  (``22.15764132.chunk.js``) and then asking the route once through the
  ladder's raw-body rung: ``https://www.fcc.gov/ecfs/documents/26110074740/1``
  answered ``200 application/pdf`` with the file's exact 335,544 bytes
  beginning ``%PDF-1.7`` (receipt
  ``supply-2026-09-02/receipts/fcc-ecfs-spa-route-2026-09-24``). The acquirer
  therefore requests the byte route, never the locator; the locator stays the
  publisher-declared identity -- ``(id_submission, document index)`` is still
  the dedupe key, and a clean ``text/html`` shell on the byte route is still
  the named ``spa-shell`` refusal, not an unrecognized one and not absence.
  The SPA's download links rewrite to ``/ecfs/file/download/{id}?file_name=
  {name}`` and its uploads use the files.fcc.gov file service
  (``files.fcc.gov/ecfs/download/{uuid}?orig=true&pk=...``): both are
  viewer-side plumbing recorded from the same bundle read, not routes this
  module requests.

**Acquisition climbs the shared walled-fetch ladder** through
:meth:`~spicy_docs.transport.source_acquirer.SourceAcquirer.capture_walled`:
DIRECT on this acquirer's own client, then ZYTE_HTTP and FIRECRAWL_RAW, no
browser rung, every attempt charged and paced on one budget, on the byte URL each locator
names (itself for docs.fcc.gov, ``/ecfs/documents/{id}/{index}`` for the SPA
host). The direct rung answers the Akamai wall on www.fcc.gov (measured on the
byte route too, 2026-09-24: 403 Access Denied to a browser agent), the
ZYTE_HTTP raw-body rung answered the byte route cleanly with the file's exact
bytes (measured, same receipt), and the shell check still names a clean viewer
shell. The ladder owns the wall vocabulary and the rung bookkeeping; this
module owns the grammar, the refusal kinds, the magic checks and the evidence.

**The SPA host is keyless and Akamai-gated, and that is not cosmetic.**
Measured live 2026-09-24 on one declared SPA URL, three GETs (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-24/q1-fcc-ecfs-document-host``):
``spicy-docs-fcc-ecfs/1.0`` answered 403, the browser agent below answered
403, and the browser agent plus ``Accept`` and ``Accept-Language`` headers
still answered 403. Every answer was the same 404-byte ``text/html``
``Access Denied`` page from ``Server: AkamaiGHost`` naming the requested URL
and a per-request reference (``x-reference-error``), so its digest changes
every time and :func:`document_refusal_kind` reads the page's own words
instead. The same wall answers a direct GET of the byte route (a 405-byte
``Access Denied`` measured the same day, receipt
``fcc-ecfs-spa-route-2026-09-24``), so the wall is host-wide and the ladder is
the route's clean path from this vantage. A wall that exhausts the ladder
therefore raises the ``client-rejected`` refusal with the retained wall bytes
as evidence.

**A redirect is a named refusal, not something this route follows.** The
ladder's direct rung never follows redirects, and the proxy rungs record the
URL the provider resolved; a clean answer whose final URL differs from the
byte URL it requested therefore raises ``FccEcfsDocumentRefusedError`` with
``refusal_kind="redirected"`` rather than a generic transport error, so a
future redirect reads as a publisher answer to revisit, not a broken capture.

**Neither refusal establishes absence.** Only 404/410 --
``FccEcfsDocumentUnavailableError`` -- is the host saying the exact byte URL
has nothing. An Akamai block speaks about the client, not the file, and a
redirect speaks about where a file moved, not whether it exists at the
locator.

**Requested-empty is recorded, not skipped.** A 200 with an empty body is a
complete answer about a URL the filings row declared, so it returns as an
acquisition with ``requested_empty`` set and no magic check -- separate from a
refusal, from a missing file, and from never having asked.

**Bounds and magic now rest on this route's own measurement.** Measured live
2026-09-24 (receipt
``supply-2026-09-02/receipts/fcc-ecfs-bounds-2026-09-24``), 8 docs.fcc.gov
attachments collected from one bounded walk of 600 filings rows across
2026-09-21..23 (12 docs.fcc.gov candidates) ranged 111,076-141,716 bytes, all
direct-rung ``200 application/pdf``. Together with the 125,605-byte
``DA-26-1030A1.pdf`` pin, the observed range sits two orders of magnitude
under 16 MiB, so ``DEFAULT_MAX_DOCUMENT_BYTES`` stays 16 MiB and
``MAX_DOCUMENT_BYTES`` stays the 640 MiB inherited construction cap -- the
ceiling a budget may name -- until a larger point is measured. Magic is
checked because extensions lie there too (three files named ``.xlsx`` began
with the OLE2 signature of a legacy ``.xls``); ``pdf`` additionally proves its
trailer through :mod:`spicy_docs.reading.pdf_bytes`. The publisher declares no
size for a document, so there is no declared byte count to check.

**The media type is advisory and the magic is the gate.** Publishers state
``application/pdf`` or ``application/octet-stream`` for the same file, so each
extension accepts the generic download types beside its canonical one, and
``text/html`` is never accepted as a document's media type: the viewer shell
is named by its own check before the media gate sees it, and the wall's answer
never reaches a clean result. The bytes decide.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import unquote, urlsplit

from spicy_docs.reading.media_types import bare_media_type
from spicy_docs.reading.pdf_bytes import PDF_MAGIC, check_pdf_bytes
from spicy_docs.sources.regulations_gov.attachments import BROWSER_USER_AGENT
from spicy_docs.sources.walled_fetch import Transport, WalledFetchError, detect_spa_shell, detect_wall
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture
from spicy_docs.transport.credentials import CredentialRefusedError
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

DOCUMENT_HOST = "www.fcc.gov"
DOCS_HOST = "docs.fcc.gov"
DEFAULT_MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_BYTES = 640 * 1024 * 1024
_CONTEXT_KEY = "fcc_ecfs_document_acquisition"
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
_DOCUMENT_PATH = re.compile(r"/ecfs/document/(?P<id>[0-9]{1,32})/(?P<index>[1-9][0-9]{0,3})$")
_DOCS_PATH = re.compile(r"/public/attachments/(?P<filename>[^?#]{1,255})$")
_FILENAME_EXTENSION = re.compile(r"\.(?P<extension>[A-Za-z0-9]{1,8})$")
type DocumentRefusalKind = Literal["client-rejected", "redirected", "unrecognized", "spa-shell"]
#: Refusals about one file. Every other refusal speaks for this client or the
#: host, so a capture run records these and continues but aborts on the rest.
PER_DOCUMENT_REFUSALS: frozenset[DocumentRefusalKind] = frozenset({"redirected", "spa-shell"})
_REFUSAL_MEANINGS: dict[DocumentRefusalKind, str] = {
    "client-rejected": "the edge rejected this client, so the request never reached the file",
    "redirected": "the host redirected this URL, which states nothing about the file existing at it",
    "unrecognized": "the refusal is in no shape this host is known to serve",
    "spa-shell": "the byte route answered the viewer shell instead of the file; bytes unacquirable on this route",
}
#: Magic prefixes by filename extension. Extensions absent from this table carry
#: no magic rule: their bytes are checked only for the requested-empty bound.
_EXTENSION_MAGIC: dict[str, tuple[bytes, ...]] = {
    "pdf": (PDF_MAGIC,),
    "doc": (OLE2_MAGIC,),
    "xls": (OLE2_MAGIC,),
    "ppt": (OLE2_MAGIC,),
    "docx": (ZIP_MAGIC,),
    "xlsx": (ZIP_MAGIC,),
    "pptx": (ZIP_MAGIC,),
    "zip": (ZIP_MAGIC,),
}
#: Canonical media types by extension, beside the generic download types every
#: extension accepts; ``text/html`` is refused for every extension on purpose.
#: The types are the registered ones for each format; the magic check stays the
#: gate because a download host may answer any of them as octet-stream.
_EXTENSION_MEDIA_TYPES: dict[str, tuple[str, ...]] = {
    "pdf": ("application/pdf",),
    "txt": ("text/plain",),
    "doc": ("application/msword",),
    "xls": ("application/vnd.ms-excel",),
    "ppt": ("application/vnd.ms-powerpoint",),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    "zip": ("application/zip",),
}
_GENERIC_DOWNLOAD_MEDIA_TYPES = ("application/octet-stream", "application/force-download")


class FccEcfsDocumentError(ValueError):
    """The locator or the response cannot establish the requested document file."""


class FccEcfsDocumentUnavailableError(FccEcfsDocumentError):
    """Only the exact requested file answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"FCC ECFS document host answered HTTP {capture.status_code}")
        self.capture = capture


class FccEcfsDocumentRefusedError(CredentialRefusedError):
    """The host refused the request, and which of its refusals this was.

    A ``CredentialRefusedError`` subclass on purpose: this host holds no
    credential, but a refusal still ends the operation, so callers that abort
    on one keep aborting. ``refusal_kind`` separates "my client was rejected"
    from "the host redirected" from "the byte route serves the viewer shell",
    without reading any of them as the file being absent;
    ``PER_DOCUMENT_REFUSALS`` names the kinds that speak about one file only.
    The refused body stays on ``refused_response``, which the keyless capture
    retains.
    """

    def __init__(self, locator: FccDocumentLocator, kind: DocumentRefusalKind) -> None:
        super().__init__(
            f"FCC ECFS document host refused {locator.subject}: "
            f"{_REFUSAL_MEANINGS[kind]}; this is not an observation that the file is absent"
        )
        self.locator = locator
        self.refusal_kind = kind


def document_refusal_kind(body: bytes | None) -> DocumentRefusalKind:
    """Whether the retained body is a wall page, read with the ladder's own vocabulary. Never an absence.

    Read from the bytes, not from the media type or a digest, because the
    Akamai page carries a per-request reference that changes its digest every
    time. A body in no known shape is ``unrecognized`` rather than guessed at;
    a redirect is named from the resolved URL by the acquirer, and the viewer
    shell by :func:`is_spa_shell_body`, not from a body here.
    """
    return "client-rejected" if body and detect_wall(body) is not None else "unrecognized"


def is_spa_shell_body(body: bytes, content_type: str | None) -> bool:
    """Whether a clean answer is the SPA host's viewer shell, not a document file.

    The locator ``/ecfs/document/{id}/{index}`` serves the ECFS viewer
    application: a ``text/html`` shell that renders the document through its
    own JavaScript call, so the file's bytes never travel on that URL. The
    acquirer requests the byte route the shell's JavaScript calls
    (``/ecfs/documents/{id}/{index}``, measured live 2026-09-24); this check
    still names a shell wherever one answers -- the locator serves it
    directly, and a byte route that cannot serve the file answers it instead
    of the bytes. The shell telltales come from the one canonical vocabulary
    in :func:`~spicy_docs.sources.walled_fetch.detect_spa_shell`, which also
    answers that a wall page is a wall, never a shell; this route's own gate
    is the media type.
    """
    return bare_media_type(content_type) == "text/html" and detect_spa_shell(body)


def media_types_for(extension: str | None) -> tuple[str, ...]:
    """The media types one extension's answer may carry; the magic check stays the gate."""
    return _EXTENSION_MEDIA_TYPES.get(extension or "", ()) + _GENERIC_DOWNLOAD_MEDIA_TYPES


@dataclass(frozen=True, slots=True)
class FccDocumentLocator:
    """One publisher-declared document URL, kept in the publisher's own spelling.

    ``id_submission`` and ``document_index`` name the SPA host's document; a
    docs.fcc.gov locator carries the row's ``id_submission`` (or none, when
    built without a row) and no index.
    """

    url: str
    id_submission: str | None
    document_index: int | None
    filename: str
    extension: str | None

    @property
    def dedupe_key(self) -> tuple[str, int] | str:
        """The component that names this document: the SPA URL's pair, or the docs filename."""
        if self.document_index is None:
            return self.filename
        assert self.id_submission is not None, "the SPA grammar carries the id in the URL"
        return (self.id_submission, self.document_index)

    @property
    def byte_url(self) -> str:
        """The URL whose GET answers this document's exact bytes, measured from the viewer shell's own JavaScript.

        The SPA locator ``/ecfs/document/{id}/{index}`` serves the viewer
        shell, whose JavaScript calls ``/ecfs/documents/{id}/{index}``
        (plural ``documents``, same host) for the file bytes -- measured live
        2026-09-24, receipt
        ``supply-2026-09-02/receipts/fcc-ecfs-spa-route-2026-09-24``. A
        docs.fcc.gov locator serves its file directly, so its byte URL is
        itself. The locator stays the publisher-declared identity; this is the
        request URL, never a second locator.
        """
        if self.document_index is None:
            return self.url
        return self.url.replace("/ecfs/document/", "/ecfs/documents/", 1)

    @property
    def subject(self) -> str:
        """One line naming this document for messages: ``{id}/{index}`` or the filename."""
        if self.document_index is None:
            return self.filename
        return f"{self.id_submission}/{self.document_index}"


def _declared_filename(filename: object) -> str:
    """The entry's declared filename must be a plain name; refuse a path or an empty one."""
    if not isinstance(filename, str) or not filename.strip():
        raise FccEcfsDocumentError("documents[] entry names no filename")
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise FccEcfsDocumentError("document filename must be a name, not a path")
    return filename


def document_locator(src: object, filename: object, *, id_submission: str | None = None) -> FccDocumentLocator:
    """Read one ``documents[]`` entry's ``src`` and ``filename``; refuse anything that is not one.

    Each host is validated in its own spelling: the SPA host must carry the
    ``/ecfs/document/{id}/{index}`` path, and the docs host the
    ``/public/attachments/{filename}`` path whose filename agrees with the
    entry's declared one. ``id_submission``, when the caller passes the filing
    row's own id, must agree with the SPA URL's id: a mismatch means the row
    declares another filing's document.
    """
    parts = urlsplit(src) if isinstance(src, str) else None
    if (
        parts is None
        or parts.scheme != "https"
        or parts.hostname not in (DOCUMENT_HOST, DOCS_HOST)
        or parts.query
        or parts.fragment
    ):
        raise FccEcfsDocumentError(
            f"document locator must be an HTTPS {DOCUMENT_HOST} or {DOCS_HOST} URL without query or fragment"
        )
    declared = _declared_filename(filename)
    if parts.hostname == DOCUMENT_HOST:
        path = _DOCUMENT_PATH.fullmatch(parts.path)
        if path is None:
            raise FccEcfsDocumentError("document locator path must be /ecfs/document/{id_submission}/{documentIndex}")
        identity = path["id"]
        if id_submission is not None and identity != id_submission:
            raise FccEcfsDocumentError("document locator names a different id_submission than its filing")
        index: int | None = int(path["index"])
    else:
        path = _DOCS_PATH.fullmatch(parts.path)
        if path is None:
            raise FccEcfsDocumentError("document locator path must be /public/attachments/{filename}")
        url_filename = unquote(path["filename"])
        if not url_filename.strip() or "/" in url_filename or "\\" in url_filename or url_filename in (".", ".."):
            raise FccEcfsDocumentError("document locator path filename must be a name, not a path")
        if url_filename != declared:
            raise FccEcfsDocumentError("document locator filename differs from its documents[] entry")
        identity = id_submission
        index = None
    suffix = _FILENAME_EXTENSION.search(declared)
    return FccDocumentLocator(src, identity, index, declared, suffix["extension"].casefold() if suffix else None)


@dataclass(frozen=True, slots=True)
class DeclaredDocument:
    """The publisher's claim about one file: where it is and what it calls it.

    ECFS declares no size for a document, so unlike the regulations.gov
    attachment route there is no declared byte count to check against a
    capture.
    """

    locator: FccDocumentLocator
    description: str | None


def declared_documents(record: Mapping[str, Any]) -> tuple[DeclaredDocument, ...]:
    """Read ``documents`` from a filings row, in publisher order.

    ``documents`` absent or ``null`` means the filing declared no files (an
    express comment), which is a different answer from a failed read. A row
    repeating one document identity -- the SPA pair or a docs filename --
    contradicts its own identity and refuses.
    """
    if not isinstance(record, Mapping):
        raise FccEcfsDocumentError("a document declaration must be read from a filings row object")
    identity = record.get("id_submission")
    if isinstance(identity, bool) or not isinstance(identity, (str, int)) or not str(identity).strip():
        raise FccEcfsDocumentError("filings row carries no id_submission to key its documents by")
    identity = str(identity)
    documents = record.get("documents")
    if documents is None:
        return ()
    if not isinstance(documents, list):
        raise FccEcfsDocumentError("documents must be an array or null")
    declared = []
    seen: set[tuple[str, int] | str] = set()
    for index, entry in enumerate(documents):
        if not isinstance(entry, Mapping):
            raise FccEcfsDocumentError(f"documents[{index}] must be an object")
        description = entry.get("description")
        if description is not None and not isinstance(description, str):
            raise FccEcfsDocumentError(f"documents[{index}].description must be text or null")
        locator = document_locator(entry.get("src"), entry.get("filename"), id_submission=identity)
        if locator.dedupe_key in seen:
            raise FccEcfsDocumentError(f"documents repeats {locator.subject}")
        seen.add(locator.dedupe_key)
        declared.append(DeclaredDocument(locator, description))
    return tuple(declared)


#: One attempt per rung of the default ladder: DIRECT, ZYTE_HTTP and FIRECRAWL_RAW.
DEFAULT_MAX_DOCUMENT_REQUESTS = 3


@dataclass(frozen=True, slots=True)
class FccEcfsDocumentBudget:
    """One document's limits: rung attempts, bytes per answer, per-attempt timeout, and the pace between attempts.

    The ladder makes one bounded attempt per rung and never retries, so one
    acquisition attempts at most ``max_requests`` rungs. Every attempt, proxy
    rungs included, is charged and paced on the acquirer's own client.
    """

    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_DOCUMENT_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class DocumentAcquisition:
    """Exact file bytes with the things that tie them to the locator.

    ``transport`` states which ladder rung answered, ``request_id`` the
    provider's own handle on a proxy rung's fetch (``None`` on the direct
    rung), and ``request_count`` every rung attempt the operation charged.
    """

    locator: FccDocumentLocator
    capture: CapturedBodyResponse
    request_count: int
    budget: FccEcfsDocumentBudget
    requested_empty: bool
    transport: Transport
    request_id: str | None

    @property
    def sha256(self) -> str:
        return self.capture.sha256


def check_document_body(capture: CapturedBodyResponse, *, locator: FccDocumentLocator) -> bool:
    """The filename's magic and the requested-empty answer; ``capture_walled`` already held the URL to the byte URL.

    Returns whether the host answered an exactly empty body to the request --
    a recorded answer, not a skip, and separate from every refusal.
    """
    if not capture.body:
        return True
    if locator.extension == "pdf":
        check_pdf_bytes(capture.body, error_type=FccEcfsDocumentError, label="document body")
    else:
        magic = _EXTENSION_MAGIC.get(locator.extension or "")
        if magic and not any(capture.body.startswith(prefix) for prefix in magic):
            raise FccEcfsDocumentError(
                f"document body does not begin with the magic its {locator.extension} filename declares"
            )
    return False


def _carried(named: Exception, error: Exception) -> Exception:
    """A named refusal keeps the refused bytes, rung outcomes and operation context; it is never a capture."""
    named.__dict__.update(
        {
            key: error.__dict__[key]
            for key in ("refused_response", "rung_outcomes", _CONTEXT_KEY)
            if key in error.__dict__
        }
    )
    return named


@contextmanager
def _named_refusal(locator: FccDocumentLocator) -> Iterator[None]:
    """Name which of the host's answers a failed acquisition was.

    Ladder exhaustion takes its kind from the retained wall bytes; rung
    outcomes that never reached a publisher keep the plain document error. A
    clean answer from another URL is a redirect, and a clean viewer shell
    fails the media gate; each is named from the capture the shared client
    attached, and neither is a capture of the file.
    """
    try:
        yield
    except WalledFetchError as error:
        refused = error.__dict__.get("refused_response")
        if getattr(refused, "unavailable_reason", None) == "rungs-exhausted":
            wrapped = FccEcfsDocumentError(
                f"FCC ECFS document fetch failed on every rung before any publisher answer: {error}"
            )
            raise _carried(wrapped, error) from error
        kind = document_refusal_kind(getattr(refused, "response_bytes", None))
        raise _carried(FccEcfsDocumentRefusedError(locator, kind), error) from error
    except FccEcfsDocumentUnavailableError:
        raise
    except FccEcfsDocumentError as error:
        capture = attached_capture(error)
        if capture is not None and capture.resolved_url != capture.requested_url:
            raise _carried(FccEcfsDocumentRefusedError(locator, "redirected"), error) from error
        if capture is not None and is_spa_shell_body(capture.body, capture.content_type):
            raise _carried(FccEcfsDocumentRefusedError(locator, "spa-shell"), error) from error
        raise


class FccEcfsDocumentAcquirer(SourceAcquirer):
    """Keyless capture of one declared document per call, through the shared walled-fetch ladder.

    ``capture_walled`` climbs DIRECT (this client), ZYTE_HTTP and
    FIRECRAWL_RAW, with no browser rung, on the locator's byte URL, charging
    and pacing every attempt on this acquirer's budget. docs.fcc.gov serves its
    file directly; the SPA host's byte route answers the proxy rung that
    escalates past the Akamai wall. Both hosts are keyless, so no route stays
    on ``capture_validated``. This class keeps the grammar, the refusal names
    and the format gate. The default agent is the regulations.gov route's
    measured one: docs.fcc.gov answered a plain curl 200 live 2026-09-24 and
    www.fcc.gov walled every agent tested, this one included (receipt
    ``firecrawl-client-smoke-2026-09-24``), so it is the best-known posture,
    not an observed unblock of the SPA host.
    """

    def __init__(
        self,
        *,
        budget: FccEcfsDocumentBudget,
        user_agent: str = BROWSER_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, FccEcfsDocumentBudget):
            raise TypeError("budget must be an FccEcfsDocumentBudget")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a nonempty string")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=user_agent,
            label="FCC ECFS document",
            error_type=FccEcfsDocumentError,
            context_key=_CONTEXT_KEY,
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> FccEcfsDocumentBudget:
        return self._budget

    def acquire(
        self, file: DeclaredDocument | FccDocumentLocator, *, max_bytes: int | None = None
    ) -> DocumentAcquisition:
        """Capture one declared document file through the ladder, whatever format its filename names.

        The request goes to the locator's byte URL, never to the SPA locator
        itself (measured live 2026-09-24, receipt
        ``fcc-ecfs-spa-route-2026-09-24``). A clean 404/410 on the byte URL is
        the publisher's absence at the exact URL. A clean viewer shell or an
        answer from another URL raises ``FccEcfsDocumentRefusedError`` naming
        it; neither names an absent file. A wall or refusal that exhausts
        every rung raises the named refusal read from the retained evidence.
        A 200 with an empty body returns ``requested_empty``.
        """
        locator = file.locator if isinstance(file, DeclaredDocument) else file
        if not isinstance(locator, FccDocumentLocator):
            raise TypeError("acquire takes a DeclaredDocument or an FccDocumentLocator")
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        magic = _EXTENSION_MAGIC.get(locator.extension or "", ())
        with _named_refusal(locator):
            requested_empty, capture, answer = self.capture_walled(
                locator.byte_url,
                media_types=media_types_for(locator.extension),
                parse=lambda capture, _limit: check_document_body(capture, locator=locator),
                max_bytes=limit,
                unavailable=FccEcfsDocumentUnavailableError,
                context={
                    "operation": "filing-document",
                    "url": locator.url,
                    "requestUrl": locator.byte_url,
                    "idSubmission": locator.id_submission,
                    "documentIndex": locator.document_index,
                    "filename": locator.filename,
                    "maxBytes": limit,
                },
                # A body with its format's magic is the file, whatever words it quotes.
                publisher_page=(lambda body: body.startswith(magic)) if magic else None,
            )
        return DocumentAcquisition(
            locator, capture, self.request_count, self.budget, requested_empty, answer.transport, answer.request_id
        )


__all__ = [
    "BROWSER_USER_AGENT",
    "DEFAULT_MAX_DOCUMENT_BYTES",
    "DEFAULT_MAX_DOCUMENT_REQUESTS",
    "DOCS_HOST",
    "DOCUMENT_HOST",
    "MAX_DOCUMENT_BYTES",
    "OLE2_MAGIC",
    "PER_DOCUMENT_REFUSALS",
    "ZIP_MAGIC",
    "DeclaredDocument",
    "DocumentAcquisition",
    "DocumentRefusalKind",
    "FccDocumentLocator",
    "FccEcfsDocumentAcquirer",
    "FccEcfsDocumentBudget",
    "FccEcfsDocumentError",
    "FccEcfsDocumentRefusedError",
    "FccEcfsDocumentUnavailableError",
    "check_document_body",
    "declared_documents",
    "document_locator",
    "document_refusal_kind",
    "is_spa_shell_body",
    "media_types_for",
]
