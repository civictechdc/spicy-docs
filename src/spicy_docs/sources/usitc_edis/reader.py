"""One investigation's docket as records: identity proven first, every document with its attachments.

``UsitcEdisReader`` reads exactly one investigation **phase** -- the
publisher's own unit, since ``731-1103`` Final and Review are different
dockets -- in three steps: prove the phase exists on the investigation
listing, walk its document listing to the publisher's empty terminal page,
then capture each document's attachment metadata. A record is yielded only
complete, so ``last_keys`` names the documents that produced one and
``failed_keys`` the documents whose attachment page did not answer, for the
next run to retry first. A failure of a listing itself yields nothing and
raises: no docket can be established from a refused listing, and a later
run re-asks from scratch. One instance is one pass; the HTTP client it
opened closes when the pass ends.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.sources.base import Reader
from spicy_docs.sources.usitc_edis.api import (
    DEFAULT_MAX_PAGES,
    EdisAcquirer,
    EdisBudget,
    EdisPage,
    document_list_url,
    investigation_url,
)
from spicy_docs.sources.usitc_edis.records import (
    AttachmentRecord,
    DocumentRecord,
    Investigation,
    UsitcEdisSourceError,
)
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, refused_capture
from spicy_docs.transport.http import RetryableHTTPStatusError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import httpx


def attachment_record_dict(attachment: AttachmentRecord) -> dict[str, Any]:
    """One attachment row in the publisher's own element spellings."""
    return {
        "id": attachment.id,
        "documentId": attachment.document_id,
        "title": attachment.title,
        "fileSize": attachment.file_size,
        "originalFileName": attachment.original_file_name,
        "pageCount": attachment.page_count,
        "createDate": attachment.create_date,
        "lastModifiedDate": attachment.last_modified_date,
        "downloadUri": attachment.download_url,
    }


def _scope_error(message: str, capture: CapturedBodyResponse) -> UsitcEdisSourceError:
    error = UsitcEdisSourceError(message)
    attach_capture(error, capture)
    attach_refused_response(error, refused_capture(capture, stage="source-validation"))
    return error


def document_record_dict(
    document: DocumentRecord, *, page_sha256: str, attachments: tuple[AttachmentRecord, ...], attachment_sha256: str
) -> dict[str, Any]:
    """One record in the publisher's own element spellings, with the captures that stated it."""
    return {
        "documentId": document.id,
        "documentType": document.document_type,
        "documentTitle": document.document_title,
        "securityLevel": document.security_level,
        "investigationNumber": document.investigation_number,
        "investigationPhase": document.investigation_phase,
        "investigationStatus": document.investigation_status,
        "investigationTitle": document.investigation_title,
        "investigationType": document.investigation_type,
        "firmOrganization": document.firm_organization,
        "filedBy": document.filed_by,
        "onBehalfOf": document.on_behalf_of,
        "documentDate": document.document_date,
        "officialReceivedDate": document.official_received_date,
        "actionJacketControlNumber": document.action_jacket_control_number,
        "memorandumControlNumber": document.memorandum_control_number,
        "attachmentListUri": document.attachment_list_url,
        "modifiedDate": document.modified_date,
        "documentListPageSha256": page_sha256,
        "attachments": [attachment_record_dict(attachment) for attachment in attachments],
        "attachmentListSha256": attachment_sha256,
    }


class UsitcEdisReader(Reader):
    """Reads one investigation phase's docket documents, each with attachment metadata.

    After a complete ``iter_records`` pass, ``last_keys`` holds the document
    ids that produced a record -- the caller may manifest exactly those --
    while ``failed_keys`` holds the ids whose attachment page did not
    answer, for the next run to retry first via ``retry_keys``. A retry key
    the listing no longer states is neither retried nor dropped: it stays on
    ``unlisted_retry_keys`` for the caller to resolve. ``fail_fast`` turns a
    failed attachment page into an immediate raise instead.

    The document listing matches ``investigationNumber`` as a partial number
    (measured 2026-09-25: ``337-145`` answered only 337-1451, 337-1453 and
    337-1454 rows, receipt ``edis-partial-number-probe-2026-09-25``), so a row
    whose number extends the requested one is kept on ``partial_match_rows``
    as evidence and never enters the docket. The investigation route's
    matching is unmeasured and gets the same rule. Any other number, or another
    phase under the exact number on the document listing, still refuses.
    """

    def __init__(
        self,
        *,
        budget: EdisBudget,
        investigation_number: str,
        investigation_phase: str,
        retry_keys: Iterable[str] | None = None,
        fail_fast: bool = False,
        max_pages: int = DEFAULT_MAX_PAGES,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.budget = budget
        self.investigation_number = investigation_number
        self.investigation_phase = investigation_phase
        self.fail_fast = fail_fast
        self.max_pages = max_pages
        # Deduplicated, first-stated order: a run that is capped or interrupted
        # cannot keep postponing the keys a previous run already failed on.
        self.retry_keys = list(dict.fromkeys(retry_keys or ()))
        acquirer: EdisAcquirer
        if clock is None:
            acquirer = EdisAcquirer(budget=budget, transport=transport)
        else:
            acquirer = EdisAcquirer(budget=budget, transport=transport, clock=clock)
        self.acquirer = acquirer
        super().__init__()
        self.unlisted_retry_keys: list[str] = []
        self.partial_match_rows: list[dict[str, Any]] = []

    def _partial_match(self, number: str, phase: str, page: EdisPage[Any], **identity: int) -> bool:
        """Whether the publisher's prefix match added this row; if so it is kept as evidence, never read."""
        if number == self.investigation_number or not number.startswith(self.investigation_number):
            return False
        self.partial_match_rows.append(
            {**identity, "investigationNumber": number, "investigationPhase": phase, "pageSha256": page.sha256}
        )
        return True

    def _investigation(self) -> Investigation:
        """The listing's own statement of the phase this reader reads.

        The number's listing is walked until it states the phase: this both
        proves the investigation exists and binds the reader to the
        publisher's spelling of it, before any document is requested. A
        complete walk that states no such phase is this query's answer today,
        not source absence.
        """
        url = investigation_url(number=self.investigation_number)
        for page in self.acquirer.investigations(url, max_pages=self.max_pages):
            for record in page.records:
                if self._partial_match(record.number, record.phase, page):
                    continue
                if record.number != self.investigation_number:
                    raise _scope_error(
                        f"USITC EDIS listing row {record.number!r} is outside the requested investigation "
                        f"{self.investigation_number!r}",
                        page.capture,
                    )
                if record.phase == self.investigation_phase:
                    return record
        raise UsitcEdisSourceError(
            f"USITC EDIS investigation listing states no phase {self.investigation_phase!r} "
            f"for {self.investigation_number!r}"
        )

    def iter_records(self) -> Iterator[dict[str, Any]]:
        """Yield one complete record per document; retry a previous run's failed keys first."""
        self.last_keys = []
        self.failed_keys = []
        self.unlisted_retry_keys = []
        self.partial_match_rows = []
        with self.acquirer:
            self._investigation()
            listing_url = document_list_url(
                investigation_number=self.investigation_number,
                investigation_phase=self.investigation_phase,
            )
            documents: list[DocumentRecord] = []
            page_digests: dict[int, str] = {}
            for page in self.acquirer.documents(listing_url, max_pages=self.max_pages):
                for record in page.records:
                    if self._partial_match(
                        record.investigation_number, record.investigation_phase, page, documentId=record.id
                    ):
                        continue
                    if (record.investigation_number, record.investigation_phase) != (
                        self.investigation_number,
                        self.investigation_phase,
                    ):
                        raise _scope_error(
                            f"USITC EDIS document {record.id} is outside the requested investigation "
                            f"{self.investigation_number!r} phase {self.investigation_phase!r}",
                            page.capture,
                        )
                    documents.append(record)
                    page_digests[record.id] = page.sha256
            listed = {str(document.id) for document in documents}
            self.unlisted_retry_keys = [key for key in self.retry_keys if key not in listed]
            retry = set(self.retry_keys)
            ordered = [d for d in documents if str(d.id) in retry] + [d for d in documents if str(d.id) not in retry]
            for document in ordered:
                try:
                    listing = self.acquirer.attachments(document.id)
                except (UsitcEdisSourceError, RetryableHTTPStatusError):
                    self.failed_keys.append(str(document.id))
                    if self.fail_fast:
                        raise
                    continue
                yield document_record_dict(
                    document,
                    page_sha256=page_digests[document.id],
                    attachments=listing.records,
                    attachment_sha256=listing.capture.sha256,
                )
                self.last_keys.append(str(document.id))
