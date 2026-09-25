"""The EDIS attachment PDF route: ``/data/download/{documentId}/{attachmentId}``.

The web service guides state this route answers ``a stream of
application/pdf bytes`` and that download requests carry an EDIS
authentication token: the 2010 guide's Basic ``username:secretKey`` form,
superseded by the EDIS Data Web Service guide (v1.1, 2024-06-14), whose
token is generated in the EDIS web application and sent as
``Authorization: Bearer <token>``. Measured 2026-09-24: the direct rung
answered the host's Akamai wall, the Zyte rung reached the origin and an
anonymous request got **HTTP 401 without wall markers** -- the token
requirement holds, so an anonymous request gets a refusal, never the bytes
(receipt ``usitc-edis-download-ladder-2026-09-24``). The same day, a
credentialed request carrying ``Authorization: Bearer`` failed at the Zyte
provider itself twice (its own 520 ``/download/temporary-error``) while an
anonymous control through the same rung answered 401 in the same minute, so
the credentialed answer remained unmeasured (receipt
``usitc-edis-credentialed-2026-09-24``). The later
``scraper-completion-2026-09-24T235248Z/edis`` campaign reached the direct
route: anonymous access answered 401 and the available DataWeb token was
refused with 403. Direct credentialed capture is now the default; the Zyte
route remains an explicit option for a known direct wall. On 2026-09-25,
the supplied EDIS token returned both offered PDFs of public document 894762
through Zyte, with exact declared sizes (receipt
``edis-token-qualification-2026-09-25``). Bytes are acquired
through the shared walled ladder
(:func:`spicy_docs.sources.walled_fetch.walled_fetch`, run by the acquirer
through ``SourceAcquirer.capture_walled``) or through one credentialed request
(:mod:`spicy_docs.sources.usitc_edis.credentialed`), and the checks here
prove only what any answer must be to count as one publisher-served PDF:
the publisher's ``application/pdf`` or ``application/octet-stream`` media
type, the ``%PDF-`` magic and a trailer, a final URL equal to the locator,
and -- when the metadata route declared a ``fileSize`` -- that exact byte
count. A login page, an error XML document or a truncated stream is refused
with its bytes retained, never read as the file being absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from spicy_docs.reading.pdf_bytes import check_pdf_bytes
from spicy_docs.sources.usitc_edis.records import (
    EDIS_HOST,
    UsitcEdisSourceError,
    check_edis_data_url,
    check_edis_id,
)
from spicy_docs.transport.source_acquirer import check_final_url

#: The publisher's stated media type for the route, and the type publishers
#: commonly state for the same bytes; the magic check is the real witness.
PDF_MEDIA_TYPES = ("application/pdf", "application/octet-stream")
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_DOWNLOAD_PATH = re.compile(r"/data/download/([0-9]{1,12})/([0-9]{1,12})")


@dataclass(frozen=True, slots=True)
class AttachmentDownloadLocator:
    """One stated ``downloadUri``, split into the identity pair it names."""

    url: str
    document_id: int
    attachment_id: int


@dataclass(frozen=True, slots=True)
class AttachmentDownload:
    """What the captured bytes state about one attachment PDF."""

    url: str
    document_id: int
    attachment_id: int
    pdf_version: str
    byte_size: int


def attachment_download_locator(url: object) -> AttachmentDownloadLocator:
    """Accept one stated ``downloadUri`` in its own spelling, or refuse it by name."""
    url = check_edis_data_url(url)
    parts = urlsplit(url)
    if parts.query:
        raise UsitcEdisSourceError("EDIS download locator carries an unexpected query")
    stated = _DOWNLOAD_PATH.fullmatch(parts.path)
    if stated is None:
        raise UsitcEdisSourceError("EDIS download locator must be /data/download/{documentId}/{attachmentId}")
    return AttachmentDownloadLocator(url, check_edis_id(int(stated[1])), check_edis_id(int(stated[2])))


def attachment_download_url(document_id: int, attachment_id: int) -> str:
    """The documented download locator for one attachment; ids are digits, never a guess.

    The metadata route states the same URL in ``downloadUri``; this builder
    exists so a caller can re-derive a locator it already holds ids for
    without re-reading the listing, and its output passes the same grammar
    check as a stated one.
    """
    return attachment_download_locator(
        f"https://{EDIS_HOST}/data/download/{check_edis_id(document_id)}/{check_edis_id(attachment_id)}"
    ).url


def read_attachment_pdf(body: object, *, url: str, final_url: str) -> AttachmentDownload:
    """Prove the bytes are one complete PDF served for the locator the metadata stated.

    The magic and trailer checks catch a challenge page and a truncated
    stream; ``declared_size`` agreement, where the caller holds the metadata
    route's ``fileSize``, is checked by the acquirer that knows both.
    """
    locator = attachment_download_locator(url)
    check_final_url(
        final_url,
        url,
        error_type=UsitcEdisSourceError,
        message="EDIS attachment final URL differs from the locator the metadata stated",
    )
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise UsitcEdisSourceError("EDIS attachment response is empty; a nonempty PDF was requested")
    version = check_pdf_bytes(bytes(body), error_type=UsitcEdisSourceError, label="EDIS attachment PDF")
    return AttachmentDownload(locator.url, locator.document_id, locator.attachment_id, version, len(body))
