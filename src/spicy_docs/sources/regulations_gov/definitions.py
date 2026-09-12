"""Regulations.gov collection identities, accepted fields, and evidence data shapes."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final, Literal, Protocol

DOCUMENT_COLLECTION: Final = "documents"
DOCKET_COLLECTION: Final = "dockets"
COMMENT_COLLECTION: Final = "comments"
SOURCE_SYSTEM_VERSION: Final = "regulations.gov-v4-mirrulations-raw-data"
DOCUMENT_SOURCE_SYSTEM_ID: Final = "urn:spicy-regs:source:regulations-gov-mirrulations:documents"
DOCKET_SOURCE_SYSTEM_ID: Final = "urn:spicy-regs:source:regulations-gov-mirrulations:dockets"
COMMENT_SOURCE_SYSTEM_ID: Final = "urn:spicy-regs:source:regulations-gov-mirrulations:comments"
DOCUMENT_SCOPE_ID: Final = "regulations-gov-documents"
DOCKET_SCOPE_ID: Final = "regulations-gov-dockets"
COMMENT_SCOPE_ID: Final = "regulations-gov-comments"
DOCUMENT_SCHEMA_NAME: Final = "regulations-gov-document-raw"
DOCKET_SCHEMA_NAME: Final = "regulations-gov-docket-raw"
COMMENT_SCHEMA_NAME: Final = "regulations-gov-comment-raw"
SCHEMA_VERSION: Final = "1.0"
DOCUMENT_SCHEMA_PATH: Final = "sources/regulations-gov-document-raw-1.0.schema.json"
DOCKET_SCHEMA_PATH: Final = "sources/regulations-gov-docket-raw-1.0.schema.json"
COMMENT_SCHEMA_PATH: Final = "sources/regulations-gov-comment-raw-1.0.schema.json"
DOCUMENT_SOURCE_SCHEMA_KEY: Final = "schemas/regulations-gov-document-raw-1.0.schema.json"
DOCKET_SOURCE_SCHEMA_KEY: Final = "schemas/regulations-gov-docket-raw-1.0.schema.json"
COMMENT_SOURCE_SCHEMA_KEY: Final = "schemas/regulations-gov-comment-raw-1.0.schema.json"
DOCUMENT_RECORD_STEM: Final = "regulations-gov-document"
DOCKET_RECORD_STEM: Final = "regulations-gov-docket"
COMMENT_RECORD_STEM: Final = "regulations-gov-comment"
DOCUMENT_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:mirrulations-document-source-enumeration"
DOCKET_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:mirrulations-docket-source-enumeration"
COMMENT_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:mirrulations-comment-source-enumeration"
ACQUISITION_POLICY_VERSION: Final = "1.2"
MAX_TRAVERSALS: Final = 1
MAX_EVIDENCE_PACK_OBJECTS: Final = 1_000
MAX_EVIDENCE_PACK_RAW_BYTES: Final = 16 * 1024 * 1024
MAX_OBJECT_BYTES: Final = 16 * 1024 * 1024
# Every query re-acquires the whole agency prefix, so one window covering a
# source's whole history is the cheap shape (2026-08-25 spec, 2026-09-02 amendment).
MAX_QUERY_DAYS: Final = 40 * 366  # ~40 years, counting every year as a leap year
EVIDENCE_PACK_TYPE: Final = "mirrulations-evidence-pack-v1"
EVIDENCE_PACK_MEDIA_TYPE: Final = "application/zip"

_ASCII_ID: Final = re.compile(r"^[A-Za-z0-9._-]+$")
_ASCII_KEY: Final = re.compile(r"^[\x21-\x7e]+$")
# Mirrulations refetches an object under the same identity without deleting
# the earlier copy, appending one ``(N)`` group per refetch to the filename:
# ``NAME.json``, ``NAME(1).json``, and (a BIS document, sampled 2026-09-02)
# ``NAME(1)(2)(3)(4)(5)(6)(7)(8)(9)(10)(11)(12).json`` with twelve stacked
# groups. The groups are key-only bookkeeping and never change the record's
# own identity, so strip every trailing group -- not just one -- before
# comparing the key's claimed identity to the body's.
_KEY_REFETCH_SUFFIX: Final = re.compile(r"(?:\(\d+\))+$")
_DISPLAY_PROPERTY_FIELDS: Final = frozenset({"label", "name", "tooltip"})
_FILE_FORMAT_FIELDS: Final = frozenset({"fileUrl", "format", "size"})
_LINK_FIELDS: Final = frozenset({"related", "self"})
_RELATIONSHIP_FIELDS: Final = frozenset({"attachments"})
_RELATIONSHIP_VALUE_FIELDS: Final = frozenset({"data", "links"})
_LINKAGE_FIELDS: Final = frozenset({"id", "type"})
_ATTACHMENT_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "agencyNote",
        "authors",
        "description",
        "docAbstract",
        "docOrder",
        "fileFormats",
        "modifyDate",
        "publication",
        "restrictReason",
        "restrictReasonType",
        "title",
    }
)
_INCLUDED_FIELDS: Final = frozenset({"attributes", "id", "links", "relationships", "type"})
_META_FIELDS: Final = frozenset(
    {
        "hasMore",
        "hasNextPage",
        "numberOfElements",
        "pageNumber",
        "pageSize",
        "totalElements",
        "totalPages",
    }
)
DOCUMENT_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "additionalRins",
        "address1",
        "address2",
        "agencyId",
        "allowLateComments",
        "authorDate",
        "authors",
        "category",
        "cfrPart",
        "city",
        "comment",
        "commentEndDate",
        "commentStartDate",
        "country",
        "displayProperties",
        "docAbstract",
        "docketId",
        "documentType",
        "effectiveDate",
        "email",
        "exhibitLocation",
        "exhibitType",
        "fax",
        "field1",
        "field2",
        "fileFormats",
        "firstName",
        "frDocNum",
        "frVolNum",
        "govAgency",
        "govAgencyType",
        "implementationDate",
        "lastName",
        "legacyId",
        "media",
        "modifyDate",
        "objectId",
        "ombApproval",
        "openForComment",
        "organization",
        "originalDocumentId",
        "pageCount",
        "paperLength",
        "paperWidth",
        "phone",
        "postedDate",
        "postmarkDate",
        "reasonWithdrawn",
        "receiveDate",
        "regWriterInstruction",
        "restrictReason",
        "restrictReasonType",
        "sourceCitation",
        "startEndPage",
        "stateProvinceRegion",
        "subject",
        "submitterRep",
        "submitterRepAddress",
        "submitterRepCityState",
        "subtype",
        "title",
        "topics",
        "trackingNbr",
        "withdrawn",
        "withinCommentPeriod",
        "zip",
    }
)
DOCKET_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "agencyId",
        "category",
        "displayProperties",
        "dkAbstract",
        "docketType",
        "effectiveDate",
        "field1",
        "field2",
        "generic",
        "keywords",
        "legacyId",
        "modifyDate",
        "objectId",
        "organization",
        "petitionNbr",
        "program",
        "rin",
        "shortTitle",
        "subType",
        "subType2",
        "title",
    }
)
COMMENT_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "address1",
        "address2",
        "agencyId",
        "category",
        "city",
        "comment",
        "commentOn",
        "commentOnDocumentId",
        "country",
        "displayProperties",
        "docAbstract",
        "docketId",
        "documentType",
        "duplicateComments",
        "email",
        "fax",
        "field1",
        "field2",
        "fileFormats",
        "firstName",
        "govAgency",
        "govAgencyType",
        "lastName",
        "legacyId",
        "modifyDate",
        "objectId",
        "openForComment",
        "organization",
        "originalDocumentId",
        "pageCount",
        "phone",
        "postedDate",
        "postmarkDate",
        "reasonWithdrawn",
        "receiveDate",
        "restrictReason",
        "restrictReasonType",
        "stateProvinceRegion",
        "submitterRep",
        "submitterRepAddress",
        "submitterRepCityState",
        "subtype",
        "title",
        "trackingNbr",
        "withdrawn",
        "zip",
    }
)
_DOCUMENT_BOOLEAN_FIELDS: Final = frozenset({"allowLateComments", "openForComment", "withdrawn", "withinCommentPeriod"})
# These fields depend on the fetch time relative to commentStartDate/commentEndDate;
# openForComment also uses allowLateComments. Refetches can therefore disagree
# without a modifyDate change (for example, BIS-2023-0021-0001).
# allowLateComments and withdrawn are stored lifecycle facts: differences in
# either still refuse a tied version.
DOCUMENT_TIE_VOLATILE_FIELDS: Final = frozenset({"openForComment", "withinCommentPeriod"})
_DOCUMENT_INTEGER_FIELDS: Final = frozenset({"pageCount", "paperLength", "paperWidth"})
# cfrPart is text or null, never an array, in the v4 API and the mirror alike
# (sampled 2026-09-02, 120 ACF/FMCSA/SEC documents: 106 null, 14 str, 0 arrays).
_DOCUMENT_TEXT_ARRAY_FIELDS: Final = frozenset({"additionalRins", "authors"})
_TOPIC_FIELDS: Final = frozenset({"id", "label", "name", "slug"})
_COMMENT_BOOLEAN_FIELDS: Final = frozenset({"openForComment", "withdrawn"})
_COMMENT_INTEGER_FIELDS: Final = frozenset({"duplicateComments"})
_COMMENT_INTEGER_OR_TEXT_FIELDS: Final = frozenset({"pageCount"})


class RegulationsGovSourceError(ValueError):
    """Mirrulations evidence cannot prove the requested source release."""


class MirrulationsObject(Protocol):
    @property
    def key(self) -> str: ...

    @property
    def etag(self) -> str: ...

    @property
    def version_id(self) -> str | None: ...

    @property
    def content(self) -> bytes: ...


class MirrulationsObjectReader(Protocol):
    def iter_source_objects(
        self,
        *,
        max_bytes: int,
    ) -> Iterator[MirrulationsObject]: ...


RegulationsGovRead = Callable[[str], MirrulationsObjectReader]


@dataclass(frozen=True, slots=True)
class RegulationsGovPage:
    """One bounded ZIP pack of exact Mirrulations object bytes."""

    traversal_index: int
    page_index: int
    window_index: int
    window_page_index: int
    request_key: str
    source_cursor: str | None
    response_bytes: bytes

    @property
    def evidence_media_type(self) -> str:
        return EVIDENCE_PACK_MEDIA_TYPE

    def __post_init__(self) -> None:
        if (
            min(
                self.traversal_index,
                self.page_index,
                self.window_index,
                self.window_page_index,
            )
            < 0
        ):
            raise RegulationsGovSourceError("Mirrulations page indexes must be non-negative")
        if self.traversal_index != 0:
            raise RegulationsGovSourceError("Mirrulations enumeration has one traversal")
        if self.window_index != self.page_index or self.window_page_index != 0:
            raise RegulationsGovSourceError("Mirrulations evidence pages are explicit windows")
        if self.source_cursor is not None:
            raise RegulationsGovSourceError("Mirrulations source enumeration does not use caller-authored cursors")
        if not self.request_key or not self.response_bytes:
            raise RegulationsGovSourceError("Mirrulations evidence must be nonempty")


@dataclass(frozen=True, slots=True)
class MirrulationsWindow:
    kind: Literal["pack"]
    collection: str
    agency: str
    pack_index: int
    terminal: bool
