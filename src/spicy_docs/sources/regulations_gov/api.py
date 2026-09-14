"""Regulations.gov API v4 document lists and details, page by page with exact evidence.

The official API answers JSON:API pages whose rows are under ``data`` and whose
paging statement is under ``meta``: ``totalElements``, ``pageNumber``,
``pageSize``, ``numberOfElements``, ``totalPages`` and ``hasNextPage``. The
api.data.gov key travels as ``X-Api-Key``. This is the keyed, live route; the
Mirrulations S3 mirror in the rest of this package remains the bulk route, and
the two are different observations of the same publisher.

Three facts about the paging were established from live bytes on 2026-09-14 and
they shape everything here (receipt
``supply-2026-09-02/receipts/port-P05-regulations-gov-2026-09-14``):

- **There is no ``links`` object.** Both a windowed and a docket-filtered list
  page answered with exactly two top-level keys, ``data`` and ``meta``. The
  continuation is ``meta.hasNextPage`` plus the current ``meta.pageNumber``, so
  the caller advances ``page[number]`` itself. The family still declares
  ``links.next`` as its continuation path, which is the JSON:API spelling: the
  publisher does not send it today, so the shared reader sees every page as
  terminal and this module's walk supplies the page numbers.
- **``totalElements`` is not the reachable count.** ``page[number]`` is capped
  at 40 whatever the page size -- ``totalPages`` reads 40 at ``page[size]=250``
  and 40 at ``page[size]=100`` alike, and page 41 answers HTTP 400 "Page number
  parameter is greater than allowed. Maximum value is 40." A query matching
  57,383 documents therefore exposes at most ``40 x page[size]``. Walk a window
  narrow enough to fit, and read a declared count as the query's size, never as
  what the walk can reach.
- **The declared count moves while you walk.** ``totalElements`` for one fixed
  ``filter[postedDate][ge]=2026-01-01`` query read 57,380 and then 57,383
  eighty-five seconds later. A count is the publisher's statement for that
  query at that instant.

A page's ``meta`` is read from the same retained bytes in a second pass, so the
publisher's own paging statement is checked rather than inferred from the
request. That costs one more JSON parse per page: 0.38 ms on the 9,029-byte
five-row fixture and 9.8 ms on a 211,509-byte 250-row page, against 1.1-2.6 s
of wall time for the request itself (timed 2026-09-14, 200 iterations each).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from spicy_docs.sources.json_input import load_decimal_json
from spicy_docs.sources.paged_json import (
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
    PagedJsonUnavailableError,
    query_value,
)
from spicy_docs.sources.regulations_gov.definitions import _ASCII_ID
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import utc_now

if TYPE_CHECKING:
    import httpx

API = "https://api.regulations.gov/v4"
DOCUMENTS_KEY = "data"
ATTACHMENTS_KEY = "data"
# All three bounds are the publisher's own, quoted from its HTTP 400 bodies on
# 2026-09-14: "Page size parameter must be a positive number of 5 or greater.",
# "Page size parameter is greater than allowed. Maximum value is 250." and
# "Page number parameter is greater than allowed. Maximum value is 40."
MIN_PAGE_SIZE = 5
MAX_PAGE_SIZE = 250
MAX_PAGE_NUMBER = 40
PAGE_NUMBER_FIELD = "page[number]"
PAGE_SIZE_FIELD = "page[size]"
REGULATIONS_GOV_API = JsonPageFamily(
    name="regulations-gov-api",
    label="Regulations.gov API",
    host="api.regulations.gov",
    next_kind="page-number",
    next_path=("meta", "hasNextPage"),
    page_field=PAGE_NUMBER_FIELD,
    count_path=("meta", "totalElements"),
    count_kind="advisory",
    media_types=("application/json", "application/vnd.api+json"),
)
# Live-verified 2026-09-14, one request each: postedDate, lastModifiedDate,
# commentEndDate and title answer 200; agencyId and documentType answer 400
# "Invalid 'Sort By' fieldName", as does a nonsense field. The set is the
# publisher's, not the documentation's.
SORT_FIELDS = ("commentEndDate", "lastModifiedDate", "postedDate", "title")
type DocumentSort = Literal[
    "commentEndDate",
    "-commentEndDate",
    "lastModifiedDate",
    "-lastModifiedDate",
    "postedDate",
    "-postedDate",
    "title",
    "-title",
]
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2}:[0-9]{2})")


class RegulationsGovApiError(PagedJsonSourceError):
    """The API response cannot establish the requested document listing or detail."""


class RegulationsGovApiUnavailableError(RegulationsGovApiError):
    """Only the exact requested document answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"Regulations.gov API answered HTTP {capture.status_code} for the requested document")
        self.capture = capture


def document_id(value: object) -> str:
    """The publisher's own document identity, checked against this package's id grammar."""
    if not isinstance(value, str) or _ASCII_ID.fullmatch(value) is None:
        raise RegulationsGovApiError("Regulations.gov document id must use strict ASCII")
    return value


def _date(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise RegulationsGovApiError(f"{name} must use YYYY-MM-DD")
    try:
        Date.fromisoformat(value)
    except ValueError as error:
        raise RegulationsGovApiError(f"{name} must be a valid calendar date") from error
    return value


def _timestamp(value: str | None, name: str) -> str | None:
    """``filter[lastModifiedDate]`` takes ``YYYY-MM-DD HH:MM:SS``; the space travels as ``+``."""
    if value is None:
        return None
    match = _TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RegulationsGovApiError(f"{name} must use YYYY-MM-DD HH:MM:SS")
    try:
        datetime.fromisoformat(f"{match[1]}T{match[2]}")
    except ValueError as error:
        raise RegulationsGovApiError(f"{name} must be a valid calendar timestamp") from error
    return value


def _ordered(start: str | None, end: str | None, name: str) -> None:
    if start is not None and end is not None and end < start:
        raise RegulationsGovApiError(f"{name} window ends before it begins")


def document_list_url(
    *,
    posted_from: str | None = None,
    posted_to: str | None = None,
    last_modified_from: str | None = None,
    last_modified_to: str | None = None,
    docket_id: str | None = None,
    agency_id: str | None = None,
    search_term: str | None = None,
    page_size: int = MAX_PAGE_SIZE,
    page_number: int = 1,
    sort: DocumentSort = "postedDate",
) -> str:
    """Name one document list query. A walk reaches at most ``40 x page_size`` rows."""
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not MIN_PAGE_SIZE <= page_size <= MAX_PAGE_SIZE:
        raise RegulationsGovApiError(f"page_size must be an integer from {MIN_PAGE_SIZE} to {MAX_PAGE_SIZE}")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or not 1 <= page_number <= MAX_PAGE_NUMBER:
        raise RegulationsGovApiError(f"page_number must be an integer from 1 to {MAX_PAGE_NUMBER}")
    if not isinstance(sort, str) or sort.removeprefix("-") not in SORT_FIELDS:
        raise RegulationsGovApiError(f"sort must be one of {SORT_FIELDS}, optionally prefixed with '-'")
    posted = (_date(posted_from, "posted_from"), _date(posted_to, "posted_to"))
    modified = (_timestamp(last_modified_from, "last_modified_from"), _timestamp(last_modified_to, "last_modified_to"))
    _ordered(*posted, "posted")
    _ordered(*modified, "last_modified")
    query: list[tuple[str, str]] = []
    for name, (start, end) in (("postedDate", posted), ("lastModifiedDate", modified)):
        if start is not None:
            query.append((f"filter[{name}][ge]", start))
        if end is not None:
            query.append((f"filter[{name}][le]", end))
    for name, value in (("docketId", docket_id), ("agencyId", agency_id), ("searchTerm", search_term)):
        if value is not None:
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise RegulationsGovApiError(f"{name} must be nonempty without surrounding whitespace")
            query.append((f"filter[{name}]", value))
    query += [(PAGE_SIZE_FIELD, str(page_size)), (PAGE_NUMBER_FIELD, str(page_number)), ("sort", sort)]
    return f"{API}/documents?{urlencode(query, safe='*')}"


def document_detail_url(identity: str) -> str:
    return f"{API}/documents/{document_id(identity)}"


def document_attachments_url(identity: str) -> str:
    """The ``related`` link of a document's ``attachments`` relationship."""
    return f"{API}/documents/{document_id(identity)}/attachments"


def _query_int(url: str, name: str) -> int | None:
    values = [value for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True) if key == name]
    if len(values) > 1:
        raise RegulationsGovApiError(f"Regulations.gov list URL repeats its {name} parameter")
    return int(values[0]) if values and values[0].isdigit() else None


def _with_page_number(url: str, number: int) -> str:
    parts = urlsplit(url)
    pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != PAGE_NUMBER_FIELD]
    pairs.append((PAGE_NUMBER_FIELD, str(number)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs, safe="*"), ""))


@dataclass(frozen=True, slots=True)
class DocumentListPage:
    """One list page: the shared reader's exact page, plus the publisher's own paging statement."""

    page: JsonPage
    page_number: int
    page_size: int
    number_of_elements: int
    total_elements: int
    total_pages: int
    has_next_page: bool
    document_ids: tuple[str, ...]

    @property
    def capture(self) -> CapturedBodyResponse:
        return self.page.capture

    @property
    def reachable_elements(self) -> int:
        """What a ``page[number]`` walk of this query can reach, which ``total_elements`` may exceed."""
        return min(self.total_elements, MAX_PAGE_NUMBER * self.page_size)


def _meta(page: JsonPage) -> Mapping[str, Any]:
    value = load_decimal_json(page.capture.body, source="Regulations.gov API", error_type=RegulationsGovApiError)
    meta = value.get("meta") if isinstance(value, Mapping) else None
    if not isinstance(meta, Mapping):
        raise RegulationsGovApiError("Regulations.gov list page omitted its meta paging statement")
    return meta


def _meta_int(meta: Mapping[str, Any], name: str) -> int:
    value = meta.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RegulationsGovApiError(f"Regulations.gov meta.{name} is not a non-negative integer")
    return value


def read_document_list_page(page: JsonPage, *, requested_page_number: int) -> DocumentListPage:
    """Check the publisher's paging statement against the page it actually served.

    The publisher states the same page three ways -- ``pageNumber``/``pageSize``
    against the request, ``numberOfElements`` against the rows, and
    ``hasNextPage`` against ``lastPage`` -- so a page served for a different
    request, or a truncated one, refuses instead of reading as a short last page.
    """
    meta = _meta(page)
    number, size = _meta_int(meta, "pageNumber"), _meta_int(meta, "pageSize")
    elements, total_pages = _meta_int(meta, "numberOfElements"), _meta_int(meta, "totalPages")
    total = page.declared_count
    if total is None:
        raise RegulationsGovApiError("Regulations.gov list page omitted its meta.totalElements count")
    if number != requested_page_number:
        raise RegulationsGovApiError("Regulations.gov served a page[number] other than the one requested")
    requested_size = _query_int(page.capture.requested_url, PAGE_SIZE_FIELD)
    if requested_size is not None and size != requested_size:
        raise RegulationsGovApiError("Regulations.gov served a page[size] other than the one requested")
    if elements != len(page.records):
        raise RegulationsGovApiError("Regulations.gov meta.numberOfElements differs from the rows it sent")
    if elements > size:
        raise RegulationsGovApiError("Regulations.gov sent more rows than its page[size]")
    has_next = meta.get("hasNextPage")
    if not isinstance(has_next, bool):
        raise RegulationsGovApiError("Regulations.gov meta.hasNextPage is not a boolean")
    last_page = meta.get("lastPage")
    if isinstance(last_page, bool) and last_page == has_next:
        raise RegulationsGovApiError("Regulations.gov meta.hasNextPage and meta.lastPage disagree")
    identities = tuple(_row_identity(row, index) for index, row in enumerate(page.records))
    if len(set(identities)) != len(identities):
        raise RegulationsGovApiError("Regulations.gov list page repeats a document id")
    return DocumentListPage(page, number, size, elements, total, total_pages, has_next, identities)


def _row_identity(row: Mapping[str, Any], index: int) -> str:
    if row.get("type") != "documents":
        raise RegulationsGovApiError(f"Regulations.gov list row {index} is not a document")
    try:
        return document_id(row.get("id"))
    except RegulationsGovApiError as error:
        raise RegulationsGovApiError(f"Regulations.gov list row {index} does not name a document") from error


@dataclass(frozen=True, slots=True)
class DocumentDetail:
    """One document as the publisher spelled it, with its attachments relationship link."""

    document_id: str
    capture: CapturedBodyResponse
    data: Mapping[str, Any]
    attributes: Mapping[str, Any]
    attachments_url: str | None


def read_document_detail(capture: CapturedBodyResponse, *, identity: str) -> DocumentDetail:
    """A detail response names one document object, not a list; its id must be the one requested."""
    value = load_decimal_json(capture.body, source="Regulations.gov API", error_type=RegulationsGovApiError)
    if not isinstance(value, Mapping):
        raise RegulationsGovApiError("Regulations.gov document response is not a JSON object")
    data = value.get("data")
    if not isinstance(data, Mapping):
        raise RegulationsGovApiError("Regulations.gov document response omitted its data object")
    if data.get("type") != "documents":
        raise RegulationsGovApiError("Regulations.gov document response is not a document")
    if document_id(data.get("id")) != identity:
        raise RegulationsGovApiError("Regulations.gov document response names a different document")
    attributes = data.get("attributes")
    if not isinstance(attributes, Mapping):
        raise RegulationsGovApiError("Regulations.gov document omitted its attributes")
    related = None
    relationships = data.get("relationships")
    if isinstance(relationships, Mapping):
        attachments = relationships.get("attachments")
        links = attachments.get("links") if isinstance(attachments, Mapping) else None
        related = links.get("related") if isinstance(links, Mapping) else None
        if related is not None and related != document_attachments_url(identity):
            raise RegulationsGovApiError("Regulations.gov attachments link is not this document's route")
    return DocumentDetail(identity, capture, data, attributes, related)


@dataclass(frozen=True, slots=True)
class AttachmentRelationship:
    """A document's attachments: one unpaged ``data`` list, with no ``meta`` and no continuation."""

    document_id: str
    capture: CapturedBodyResponse
    records: tuple[Mapping[str, Any], ...]


def read_attachment_relationship(capture: CapturedBodyResponse, *, identity: str) -> AttachmentRelationship:
    """Every row must be an attachment with an id; the publisher states no count and no next page."""
    value = load_decimal_json(capture.body, source="Regulations.gov API", error_type=RegulationsGovApiError)
    if not isinstance(value, Mapping):
        raise RegulationsGovApiError("Regulations.gov attachments response is not a JSON object")
    rows = value.get(ATTACHMENTS_KEY)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise RegulationsGovApiError("Regulations.gov attachments response omitted its data list")
    identities = []
    for index, row in enumerate(rows):
        if row.get("type") != "attachments":
            raise RegulationsGovApiError(f"Regulations.gov attachments row {index} is not an attachment")
        row_id = row.get("id")
        if not isinstance(row_id, str) or _ASCII_ID.fullmatch(row_id) is None:
            raise RegulationsGovApiError(f"Regulations.gov attachments row {index} id is not strict ASCII")
        identities.append(row_id)
    if len(set(identities)) != len(identities):
        raise RegulationsGovApiError("Regulations.gov attachments response repeats an attachment id")
    return AttachmentRelationship(identity, capture, tuple(rows))


class RegulationsGovApiReader(PagedJsonReader):
    """Document lists, details and attachment relationships; every response is one bounded request."""

    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=REGULATIONS_GOV_API, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def documents(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[DocumentListPage]:
        """Walk ``page[number]`` while the publisher says there is a next page.

        The publisher supplies no continuation URL, so the page number is the
        caller's to advance and every requested URL is caller-authored. Ending
        because the walk hit ``page[number]`` 40 with a next page outstanding is
        a refusal, not an end: narrow the window and walk it again.
        """
        for page in self.pages(url, records_key=DOCUMENTS_KEY, max_pages=max_pages):
            number = int(query_value(page.capture.requested_url, PAGE_NUMBER_FIELD) or 1)
            listing = read_document_list_page(page, requested_page_number=number)
            yield listing
            if listing.has_next_page and number >= MAX_PAGE_NUMBER:
                raise RegulationsGovApiError(
                    f"Regulations.gov page[number] bound {MAX_PAGE_NUMBER} reached with a next page outstanding"
                )

    def _item[Result](
        self, url: str, *, operation: str, identity: str, parse: Callable[[CapturedBodyResponse], Result]
    ) -> Result:
        """One non-list route. The shared page reader cannot serve these two.

        ``PagedJsonReader.page`` requires ``application/json`` and a ``data``
        list, and neither holds here: the detail and attachment routes answer
        ``application/vnd.api+json;charset=utf-8`` while the list route answers
        ``application/json`` (both live 2026-09-14), and a detail's ``data`` is
        an object. Both spellings are accepted because the publisher
        demonstrably uses both across its own routes. The credential-echo
        refusal the page reader performs is repeated here so no route can
        retain a body that echoed the key.
        """

        result, _capture = self.capture_validated(
            url,
            media_types=self.family.media_types,
            parse=lambda capture, _limit: parse(capture),
            max_bytes=self.budget.max_page_bytes,
            unavailable=RegulationsGovApiUnavailableError,
            context={"operation": operation, "family": self.family.name, "url": url, "documentId": identity},
        )
        return result

    def document(self, identity: str) -> DocumentDetail:
        """One document detail; 404 and 410 raise ``RegulationsGovApiUnavailableError`` with the capture."""
        return self._item(
            document_detail_url(identity),
            operation="document",
            identity=identity,
            parse=lambda capture: read_document_detail(capture, identity=identity),
        )

    def attachments(self, identity: str) -> AttachmentRelationship:
        """The attachments relationship: one unpaged list of this document's attachment rows."""
        return self._item(
            document_attachments_url(identity),
            operation="attachments",
            identity=identity,
            parse=lambda capture: read_attachment_relationship(capture, identity=identity),
        )


__all__ = [
    "API",
    "ATTACHMENTS_KEY",
    "DOCUMENTS_KEY",
    "MAX_PAGE_NUMBER",
    "MAX_PAGE_SIZE",
    "MIN_PAGE_SIZE",
    "REGULATIONS_GOV_API",
    "SORT_FIELDS",
    "AttachmentRelationship",
    "DocumentDetail",
    "DocumentListPage",
    "DocumentSort",
    "PagedJsonUnavailableError",
    "RegulationsGovApiError",
    "RegulationsGovApiReader",
    "RegulationsGovApiUnavailableError",
    "document_attachments_url",
    "document_detail_url",
    "document_id",
    "document_list_url",
    "read_attachment_relationship",
    "read_document_detail",
    "read_document_list_page",
]
