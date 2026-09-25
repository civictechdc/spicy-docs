"""EDIS `/data` XML rows: one pass, publisher spellings, and the URL grammar each row states.

The web service answers ``<results>`` holding one ``investigations``,
``documents`` or ``attachments`` wrapper around zero or more rows. Every
field is kept verbatim -- dates arrive in at least three spellings across
the retained captures (``2020/07/09 00:00:00``, ``2023/04/03 00:00:00`` and
the 2010 guide's ``2005-01-25 00:00:00.0``), so none is read here. An empty
element (``<pageCount/>``, ``<docketNumber/>``) is absent, not ``""``: the
publisher states the field exists and carries no value. Attachment metadata
can also state an empty ``<downloadUri/>``; no download locator is invented.
A row is refused, not repaired, when an identity field or required URL
element is missing, or a nonempty URL is outside this publisher's grammar.

Parsing is O(B) in the response bytes through ``reading/xml.py``, which
refuses DTDs and entity declarations before they can change source text.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit
from xml.etree.ElementTree import Element

from spicy_docs.reading.rss import child_text
from spicy_docs.reading.xml import parse_xml
from spicy_docs.transport.captured import CapturedBodyResponse

EDIS_HOST = "edis.usitc.gov"
#: Who every EDIS request names; the walled hosts refuse every agent spelling, so this states who asked.
USER_AGENT = "spicy-docs-usitc-edis/1.0"
DATA_PATH_PREFIX = "/data/"
#: Page bytes observed live: an investigation row is ~0.5 KB and a document
#: row ~1 KB, so a full 100-row page runs ~100 KB before XML overhead.
DEFAULT_MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGE_BYTES = 16 * 1024 * 1024
_MAX_ROWS_PER_PAGE = 1000  # runaway guard; the documented page size is 100
INVESTIGATIONS = "investigations"
DOCUMENTS = "documents"
ATTACHMENTS = "attachments"
#: Query names no retained URL may carry; a credential never travels in a
#: locator (the shared list-reader rule this package mirrors for XML).
_CREDENTIAL_QUERY_NAMES = frozenset({"api_key", "apikey", "api-key", "key", "token", "access_token"})


class UsitcEdisSourceError(ValueError):
    """The locator or the response cannot establish the requested EDIS listing or document."""


class UsitcEdisUnavailableError(UsitcEdisSourceError):
    """Only the exact requested locator answered 404/410; never an observation of absence."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"USITC EDIS source answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


def check_edis_id(value: object) -> int:
    """One publisher document or attachment id: a positive integer of at most 12 digits, never a bool."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10**12:
        raise UsitcEdisSourceError("EDIS document and attachment ids must be positive integers")
    return value


def check_edis_data_url(url: object) -> str:
    """Accept one publisher `/data` URL in its own spelling, or refuse it by name.

    Every URL a row states (``documentListUri``, ``attachmentListUri``,
    ``downloadUri``) and every URL this package builds must be HTTPS on the
    publisher's own host under ``/data/``, with no fragment and no
    credential in the query. The spelling is returned unchanged: it is
    evidence of what the publisher stated, not a template to rebuild.
    """
    parts = urlsplit(url) if isinstance(url, str) else None
    if (
        parts is None
        or parts.scheme != "https"
        or parts.hostname != EDIS_HOST
        or not parts.path.startswith(DATA_PATH_PREFIX)
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise UsitcEdisSourceError(f"EDIS locator must be an HTTPS {EDIS_HOST}/data URL")
    names = {name.casefold() for name, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if names & _CREDENTIAL_QUERY_NAMES:
        raise UsitcEdisSourceError("EDIS locator must not carry a credential in its query")
    return url


def _rows(body: bytes, *, wrapper: str, row_tag: str, max_bytes: int) -> tuple[Element, ...]:
    """Parse one listing page; exactly the expected wrapper around zero or more rows.

    An empty wrapper is a real answer (an out-of-range page is documented to
    return empty), so it is returned as zero rows for the caller -- which
    knows whether this was a first page -- to read as requested-empty.
    """
    root = parse_xml(body, max_bytes=max_bytes, error_type=UsitcEdisSourceError, label="EDIS listing")
    if root.tag != "results":
        raise UsitcEdisSourceError("EDIS listing root is not <results>")
    if len(root) != 1 or root[0].tag != wrapper:
        raise UsitcEdisSourceError(f"EDIS listing does not state exactly one <{wrapper}> wrapper")
    holder = root[0]
    rows = [child for child in holder if child.tag == row_tag]
    if len(rows) != len(holder) or len(rows) > _MAX_ROWS_PER_PAGE:
        raise UsitcEdisSourceError(f"EDIS listing wrapper holds something other than <{row_tag}> rows")
    return tuple(rows)


def _digits(value: str | None, *, label: str) -> int | None:
    """A publisher integer stated as digits, absent when the element is empty."""
    if value is None:
        return None
    if not value.isdigit():
        raise UsitcEdisSourceError(f"EDIS {label} is not the digits the publisher states")
    return int(value)


def _required(element: Element, tag: str, *, row: str) -> str:
    value = child_text(element, tag, error_type=UsitcEdisSourceError, label="EDIS listing")
    if value is None:
        raise UsitcEdisSourceError(f"EDIS {row} omitted its {tag}")
    if len(value) > 4096:
        raise UsitcEdisSourceError(f"EDIS {row} {tag} exceeds its length bound")
    return value


def _optional(element: Element, tag: str) -> str | None:
    return child_text(element, tag, error_type=UsitcEdisSourceError, label="EDIS listing")


@dataclass(frozen=True, slots=True)
class Investigation:
    """One investigation phase as the listing stated it.

    An EDIS investigation *is* its phase here: ``731-1103`` Final, Prelim,
    Review and Review2 are four rows with four document dockets, so the
    identity pair is ``(number, phase)`` and ``docket_number`` is the
    publisher's own internal key for the same phase (absent in older rows).
    """

    number: str
    phase: str
    status: str
    title: str
    type: str
    docket_number: int | None
    document_list_url: str

    @property
    def identity(self) -> tuple[str, str]:
        return (self.number, self.phase)


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """One docket document: identity is the publisher's numeric ``id``.

    ``document_date`` and ``official_received_date`` are verbatim publisher
    strings. ``firm_organization``, ``filed_by`` and ``on_behalf_of`` are
    the party fields where the publisher states them, absent when empty.
    """

    id: int
    document_type: str
    document_title: str | None
    security_level: str
    investigation_number: str
    investigation_phase: str
    investigation_status: str
    investigation_title: str
    investigation_type: str
    firm_organization: str | None
    filed_by: str | None
    on_behalf_of: str | None
    document_date: str
    official_received_date: str
    action_jacket_control_number: str | None
    memorandum_control_number: str | None
    attachment_list_url: str
    modified_date: str | None


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    """One attachment's metadata; an empty download URI offers no PDF locator.

    ``original_file_name`` is publisher metadata, never a local output path.
    """

    id: int
    document_id: int
    title: str | None
    file_size: int | None
    page_count: int | None
    create_date: str | None
    last_modified_date: str | None
    download_url: str | None
    original_file_name: str | None = None


def parse_investigations(body: bytes, *, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> tuple[Investigation, ...]:
    """Read one investigation page's rows. O(B); one pass, no per-row rescan."""
    investigations = []
    for row in _rows(body, wrapper=INVESTIGATIONS, row_tag="investigation", max_bytes=max_bytes):
        investigations.append(
            Investigation(
                number=_required(row, "investigationNumber", row="investigation"),
                phase=_required(row, "investigationPhase", row="investigation"),
                status=_required(row, "investigationStatus", row="investigation"),
                title=_required(row, "investigationTitle", row="investigation"),
                type=_required(row, "investigationType", row="investigation"),
                docket_number=_digits(_optional(row, "docketNumber"), label="docketNumber"),
                document_list_url=check_edis_data_url(_required(row, "documentListUri", row="investigation")),
            )
        )
    return tuple(investigations)


def parse_documents(body: bytes, *, max_bytes: int = DEFAULT_MAX_PAGE_BYTES) -> tuple[DocumentRecord, ...]:
    """Read one document page's rows, keeping each field's publisher spelling."""
    documents = []
    for row in _rows(body, wrapper=DOCUMENTS, row_tag="document", max_bytes=max_bytes):
        document_id = _digits(_required(row, "id", row="document"), label="document id")
        documents.append(
            DocumentRecord(
                id=document_id,
                document_type=_required(row, "documentType", row="document"),
                document_title=_optional(row, "documentTitle"),
                security_level=_required(row, "securityLevel", row="document"),
                investigation_number=_required(row, "investigationNumber", row="document"),
                investigation_phase=_required(row, "investigationPhase", row="document"),
                investigation_status=_required(row, "investigationStatus", row="document"),
                investigation_title=_required(row, "investigationTitle", row="document"),
                investigation_type=_required(row, "investigationType", row="document"),
                firm_organization=_optional(row, "firmOrganization"),
                filed_by=_optional(row, "filedBy"),
                on_behalf_of=_optional(row, "onBehalfOf"),
                document_date=_required(row, "documentDate", row="document"),
                official_received_date=_required(row, "officialReceivedDate", row="document"),
                action_jacket_control_number=_optional(row, "actionJacketControlNumber"),
                memorandum_control_number=_optional(row, "memorandumControlNumber"),
                attachment_list_url=check_edis_data_url(_required(row, "attachmentListUri", row="document")),
                modified_date=_optional(row, "modifiedDate"),
            )
        )
    return tuple(documents)


def parse_attachments(
    body: bytes, *, document_id: int | None = None, max_bytes: int = DEFAULT_MAX_PAGE_BYTES
) -> tuple[AttachmentRecord, ...]:
    """Read one attachment page's rows; a stated ``document_id`` must match every row."""
    attachments = []
    for row in _rows(body, wrapper=ATTACHMENTS, row_tag="attachment", max_bytes=max_bytes):
        # Live metadata can name attachments without offering a download,
        # including confidential documents. Retain the explicit empty field.
        if row.find("downloadUri") is None:
            raise UsitcEdisSourceError("EDIS attachment omitted its downloadUri")
        download_url = _optional(row, "downloadUri")
        if download_url is not None and len(download_url) > 4096:
            raise UsitcEdisSourceError("EDIS attachment downloadUri exceeds its length bound")
        attachment = AttachmentRecord(
            id=_digits(_required(row, "id", row="attachment"), label="attachment id"),
            document_id=_digits(_required(row, "documentId", row="attachment"), label="documentId"),
            title=_optional(row, "title"),
            file_size=_digits(_optional(row, "fileSize"), label="fileSize"),
            page_count=_digits(_optional(row, "pageCount"), label="pageCount"),
            create_date=_optional(row, "createDate"),
            last_modified_date=_optional(row, "lastModifiedDate"),
            download_url=check_edis_data_url(download_url) if download_url is not None else None,
            original_file_name=_optional(row, "originalFileName"),
        )
        if document_id is not None and attachment.document_id != document_id:
            raise UsitcEdisSourceError("EDIS attachment row names a document other than the one requested")
        attachments.append(attachment)
    return tuple(attachments)
