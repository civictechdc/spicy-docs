"""Attachment and document-body files from ``downloads.regulations.gov``, one bounded PDF at a time.

The API declares every file it knows about as a ``fileFormats[].fileUrl`` on the
document's own ``attributes`` or on an attachment row. Those URLs are the only
locators this module accepts: it parses the publisher's spelling and checks its
grammar, and never builds a URL from an id and a guessed extension. Two file
names occur, both under ``https://downloads.regulations.gov/{documentId}/``:
``content.{ext}`` for the document's own rendition and ``attachment_{n}.{ext}``
for an attachment's. Over 2,745 declared renditions on 2,676 documents in the
retained 2026-09-05 attachment sample, every declared URL had exactly that
shape, on that host, with no query and no fragment.

**The host is keyless and must not be sent the key.** Verified live 2026-09-14
on one document: keyless and keyed requests returned the identical 200, 2,620
bytes and digest. It is S3 behind CloudFront, not api.data.gov, so it is not
metered against the api.data.gov hourly budget.

**It refuses a non-browser User-Agent, and that is not cosmetic.** With
``spicy-docs-regulations-gov/1.0`` the same URL answered 403 with a 919-byte
HTML page; with the browser agent below it answered 200 and the file (live
2026-09-14, reproducing DocSpec's 2026-09-05 finding). Without the header the
whole route reads as "the unmetered host does not work", which is a clean and
completely wrong answer, so the agent is a named constant with its evidence
rather than an implicit default.

**The host's 403 is ambiguous and never establishes absence.** A rejected
client gets 403 with a 919-byte ``text/html`` body; a file that is genuinely not
there gets 403 with S3's 111-byte ``application/xml`` ``AccessDenied``. The
shared capture client maps every 403 to a credential refusal and deliberately
retains no bytes for one, so this route aborts on 403 and leaves the two apart
only in a caller's receipt. An aborted capture is not a zero.

**Bounds come from measured files, not from a guess.** Across the 2,736 files
downloaded in the 2026-09-05 sample the median was 289,436 bytes, the 95th
percentile 5,913,955 and the maximum 562,644,355. The 16 MiB default covers
2,700 of 2,736 (98.7%) and the 640 MiB cap clears the observed maximum, so the
tail is reachable by an explicit caller bound rather than silently truncated.

**Magic is checked because the extension lies.** Three of those 2,736 files were
named ``.xlsx`` and began with the OLE2 signature of a legacy ``.xls``. A
``format`` of ``pdf`` is a publisher claim; ``%PDF-`` in the bytes is evidence.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from spicy_docs.sources.pdf_bytes import check_pdf_bytes
from spicy_docs.sources.regulations_gov.definitions import _ASCII_ID
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_final_url,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

ATTACHMENT_HOST = "downloads.regulations.gov"
PDF_MEDIA_TYPE = "application/pdf"
PDF_MAGIC = b"%PDF-"
DEFAULT_MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 640 * 1024 * 1024
# downloads.regulations.gov answers 403 with a 919-byte HTML page to any agent
# it does not recognise, including files the API declared one second earlier.
# This exact string was verified against the host on 2026-09-05 and again on
# 2026-09-14; a modified one is unverified.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_CONTENT_NAME = re.compile(r"content\.(?P<extension>[A-Za-z0-9]{1,8})")
_ATTACHMENT_NAME = re.compile(r"attachment_(?P<index>[1-9][0-9]{0,3})\.(?P<extension>[A-Za-z0-9]{1,8})")
type AttachmentKind = Literal["content", "attachment"]


class RegulationsGovAttachmentError(ValueError):
    """The locator or the response cannot establish the requested attachment file."""


class RegulationsGovAttachmentUnavailableError(RegulationsGovAttachmentError):
    """Only the exact requested file answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Regulations.gov attachment host answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class AttachmentLocator:
    """One publisher-declared file URL, kept in the publisher's own spelling."""

    url: str
    document_id: str
    file_name: str
    kind: AttachmentKind
    extension: str
    attachment_index: int | None = None

    @property
    def is_pdf(self) -> bool:
        return self.extension == "pdf"


def attachment_locator(file_url: object) -> AttachmentLocator:
    """Read one ``fileFormats[].fileUrl`` as a locator; refuse anything that is not one."""
    parts = urlsplit(file_url) if isinstance(file_url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname != ATTACHMENT_HOST or parts.query or parts.fragment:
        raise RegulationsGovAttachmentError(f"attachment locator must be an HTTPS {ATTACHMENT_HOST} URL")
    segments = parts.path.lstrip("/").split("/")
    if len(segments) != 2 or not all(segments):
        raise RegulationsGovAttachmentError("attachment locator path must be /{documentId}/{fileName}")
    identity, name = segments
    # The same id grammar the rest of this package classifies documents with.
    if _ASCII_ID.fullmatch(identity) is None:
        raise RegulationsGovAttachmentError("attachment locator does not name a document")
    if (content := _CONTENT_NAME.fullmatch(name)) is not None:
        return AttachmentLocator(file_url, identity, name, "content", content["extension"].casefold())
    if (attachment := _ATTACHMENT_NAME.fullmatch(name)) is not None:
        return AttachmentLocator(
            file_url, identity, name, "attachment", attachment["extension"].casefold(), int(attachment["index"])
        )
    raise RegulationsGovAttachmentError("attachment file name is neither content.{ext} nor attachment_{n}.{ext}")


@dataclass(frozen=True, slots=True)
class DeclaredFile:
    """The publisher's claim about one file: where it is, what it calls it, how big it says it is."""

    locator: AttachmentLocator
    format: str | None
    declared_size: int | None


def declared_files(record: Mapping[str, Any]) -> tuple[DeclaredFile, ...]:
    """Read ``attributes.fileFormats`` from a document or attachment row.

    ``fileFormats`` is absent or ``null`` when there is no file -- a withheld
    attachment carries a ``restrictReasonType`` and no file, which is a
    different answer from having no attachment. One attachment is commonly
    published in several formats of the same pages (2,745 renditions across
    2,509 attachments in the 2026-09-05 sample), so each entry is its own
    declared file and counting entries is not counting attachments.
    """
    if not isinstance(record, Mapping):
        raise RegulationsGovAttachmentError("a file declaration must be read from a record object")
    attributes = record.get("attributes")
    if not isinstance(attributes, Mapping):
        raise RegulationsGovAttachmentError("record omitted its attributes")
    formats = attributes.get("fileFormats")
    if formats is None:
        return ()
    if not isinstance(formats, list):
        raise RegulationsGovAttachmentError("fileFormats must be an array or null")
    files = []
    for index, entry in enumerate(formats):
        if not isinstance(entry, Mapping):
            raise RegulationsGovAttachmentError(f"fileFormats[{index}] must be an object")
        size = entry.get("size")
        if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
            raise RegulationsGovAttachmentError(f"fileFormats[{index}].size must be a non-negative integer or null")
        file_format = entry.get("format")
        if file_format is not None and not isinstance(file_format, str):
            raise RegulationsGovAttachmentError(f"fileFormats[{index}].format must be text or null")
        files.append(DeclaredFile(attachment_locator(entry.get("fileUrl")), file_format, size))
    return tuple(files)


def pdf_files(records: Iterator[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> tuple[DeclaredFile, ...]:
    """Every declared PDF across a document's own attributes and its attachment rows, in publisher order."""
    return tuple(file for record in records for file in declared_files(record) if file.locator.is_pdf)


@dataclass(frozen=True, slots=True)
class AttachmentBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_ATTACHMENT_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class AttachmentAcquisition:
    """Exact file bytes with the three things that tie them to the locator."""

    locator: AttachmentLocator
    capture: CapturedBodyResponse
    declared_size: int | None
    request_count: int
    budget: AttachmentBudget

    @property
    def sha256(self) -> str:
        return self.capture.sha256


def check_pdf_body(capture: CapturedBodyResponse, *, locator: AttachmentLocator, declared_size: int | None) -> None:
    """Media type, ``%PDF-`` magic, the final URL and, when declared, the byte count."""
    check_pdf_bytes(capture.body, error_type=RegulationsGovAttachmentError, label="attachment body")
    check_final_url(
        capture.resolved_url,
        locator.url,
        error_type=RegulationsGovAttachmentError,
        message="attachment final URL differs from its locator",
    )
    if declared_size is not None and capture.byte_size != declared_size:
        raise RegulationsGovAttachmentError("attachment byte count differs from the size the publisher declared")


class RegulationsGovAttachmentAcquirer(SourceAcquirer):
    """Keyless, paced capture of one declared PDF per call; the API key belongs to the other host."""

    def __init__(
        self,
        *,
        budget: AttachmentBudget,
        user_agent: str = BROWSER_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, AttachmentBudget):
            raise TypeError("budget must be an AttachmentBudget")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a nonempty string")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent=user_agent,
            label="Regulations.gov attachment",
            error_type=RegulationsGovAttachmentError,
            context_key="regulations_gov_attachment_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> AttachmentBudget:
        return self._budget

    def acquire_pdf(
        self, file: DeclaredFile | AttachmentLocator, *, max_bytes: int | None = None
    ) -> AttachmentAcquisition:
        """Capture one declared PDF. A ``DeclaredFile`` also binds the publisher's declared size."""
        locator = file.locator if isinstance(file, DeclaredFile) else file
        declared_size = file.declared_size if isinstance(file, DeclaredFile) else None
        if not isinstance(locator, AttachmentLocator):
            raise TypeError("acquire_pdf takes a DeclaredFile or an AttachmentLocator")
        if not locator.is_pdf:
            raise RegulationsGovAttachmentError("this route captures PDF renditions; the locator names another format")
        limit = narrow_byte_limit(self.budget.max_bytes, max_bytes)
        if declared_size is not None and declared_size > limit:
            raise RegulationsGovAttachmentError("publisher declares the file larger than the capture byte bound")
        _checked, capture = self.capture_validated(
            locator.url,
            media_types=(PDF_MEDIA_TYPE,),
            parse=lambda response, _limit: check_pdf_body(response, locator=locator, declared_size=declared_size),
            max_bytes=limit,
            unavailable=RegulationsGovAttachmentUnavailableError,
            context={
                "operation": "attachment-pdf",
                "url": locator.url,
                "documentId": locator.document_id,
                "fileName": locator.file_name,
                "declaredSize": declared_size,
                "maxBytes": limit,
            },
        )
        return AttachmentAcquisition(locator, capture, declared_size, self.request_count, self.budget)


__all__ = [
    "ATTACHMENT_HOST",
    "BROWSER_USER_AGENT",
    "DEFAULT_MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENT_BYTES",
    "PDF_MAGIC",
    "PDF_MEDIA_TYPE",
    "AttachmentAcquisition",
    "AttachmentBudget",
    "AttachmentKind",
    "AttachmentLocator",
    "DeclaredFile",
    "RegulationsGovAttachmentAcquirer",
    "RegulationsGovAttachmentError",
    "RegulationsGovAttachmentUnavailableError",
    "attachment_locator",
    "check_pdf_body",
    "declared_files",
    "pdf_files",
]
