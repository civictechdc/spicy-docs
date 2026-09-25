"""FERC eLibrary WebAPI routes and body-paged walks, each answer captured exactly.

FERC's eLibrary is an Angular application whose calls go to a keyless JSON API
at ``https://elibrary.ferc.gov/eLibraryWebAPI/api/``. The base URL and the
application id are the SPA's own statement in
``/eLibrary/assets/config/app-settings.json`` (captured 2026-09-24); the routes,
bodies and paging below are read from the SPA's bundles and from live requests
retained 2026-09-24/25 (``docs/sources/ferc.md`` names the receipts). Every
request carries the SPA interceptor's headers (``elibrary_transport``).

GET routes answer ``{"DataList": [...], "ErrorList": []}``; search answers
``{"searchHits", "totalHits", "numHits", "success", "errorMessage"}``. A
non-empty ``ErrorList`` or ``success:false`` refuses: the publisher naming its
own failure cannot establish a record.

Search and the docket sheet page by request body, not by a continuation the
response names, so ``FercElibraryReader._walk`` advances the body's page field
while pages come back full, ends at the first short page, and refuses a moved
declared total, more rows than declared, a repeated identity, a page bound or
a terminal count disagreement.

- **Search** (``Search/AdvancedSearch``): ``curPage`` starts at 1. The SPA's
  paginator sends ``pageIndex+1``, and a 2026-09-25 control (``totalHits:
  207``) served the same first page for 0 and 1, the second for 2 and the
  7-row terminal page for 3. The publisher's help pages mark the date range
  required, so the body always carries a ``dateSearches`` window. The retained
  browser requests send ``idolResultID:""``; this module sends ``null`` until a
  response returns a ``searchResultId`` token, a spelling measured answering
  identically.
- **Docket sheet** (``Docket/GetSingleDocketSheet``): ``pageNumber`` is
  zero-based and ``Page.numHits`` echoes the requested page size (100 asked,
  100 echoed, 3 rows served), so a page is full when its rows equal it. Paging
  past one page is qualified only by synthetic fixtures. Each page's records
  are its ``DocumentsItem`` entries flattened, identified by ``accession_no``.
- **New dockets** (``Docket/GetATMSdocs/{mode}/{MM-dd-yyyy}/{MM-dd-yyyy}/{sort}``):
  one GET per date window; ``mode`` is one of the SPA new-docket page's radio values.

**An empty answer is not absence.** Identical new-docket windows answered zero
rows and then hundreds within a minute (2026-09-25), and a 2026-09-24 search
zero did not reproduce, so every requested-empty answer is an observation to
re-ask, never "done with nothing" (see ``ferc.readers``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from spicy_docs.reading.json_input import load_decimal_json
from spicy_docs.reading.paged_json import (
    DeclaredCountChanged,
    DeclaredCountMismatch,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
    encode_body,
)
from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.sources.ferc.vocabulary import SERIAL_DOCKET_PREFIXES, require_documented_class_type
from spicy_docs.transport.captured import CapturedBodyResponse, attach_capture, refused_capture
from spicy_docs.transport.credentials import REASON_CHARACTERS, CredentialRefusedError, scrub_credential
from spicy_docs.transport.source_acquirer import check_request_count, named_challenge, utc_now

if TYPE_CHECKING:
    import httpx

API = "https://elibrary.ferc.gov/eLibraryWebAPI/api"
#: The SPA's public application id, from its own app-settings.json (captured 2026-09-24).
APPLICATION_ID = "52f6cc3e-3b73-4b1d-9668-05c32c17bf38"
#: Every live probe sent a browser User-Agent and was answered; a tool-branded agent was
#: never tried here, and regulations.gov's download host refused one with a clean 403.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
DATA_LIST_KEY = "DataList"
SEARCH_HITS_KEY = "searchHits"
#: eLibrary spells this field with the doubled s in its own bundle and bytes.
ACCESSION_FIELD = "acesssionNumber"
#: Rulemaking comments in the publisher's class vocabulary (``Search/GetClassTypes``, 2026-09-24),
#: checked against the pinned roster at import so a drift fails loudly, not as a zero-hit walk.
RULEMAKING_COMMENT = ("Comments/Protest", "Rulemaking Comment")
require_documented_class_type(*RULEMAKING_COMMENT)
#: The SPA new-docket page's two radio values; both answered live 2026-09-25.
NEW_DOCKET_MODES = ("rbCreateDate", "rbFilingDate")
#: The new-docket form caps a range at 10 days; wider windows answered live anyway (2026-09-25).
NEW_DOCKET_WINDOW_DAYS = 10
NEW_DOCKETS_SORT = "DocketFullNumber"
ADVANCED_SEARCH_URL = f"{API}/Search/AdvancedSearch"
CLASS_TYPES_URL = f"{API}/Search/GetClassTypes"
DOCKET_SHEET_URL = f"{API}/Docket/GetSingleDocketSheet"
#: This module's own bounds, not publisher limits: a walk refuses before it can loop unbounded.
MAX_RESULTS_PER_PAGE = 100
MAX_PAGES = 100
#: The SPA's own all-dates epoch, from the retained browser request (2026-09-24).
EARLIEST_DATE = "1904-01-01"

#: Two letters with a fiscal year (``RM24-5``), or a roster prefix spelled with a serial
#: number (``P-14683``, ``ID-10800``; see ``vocabulary.SERIAL_DOCKET_PREFIXES``), each with
#: an optional three-digit sub-docket. The discontinued ``E-``/``G-``/``R-`` forms are not admitted.
_DOCKET = re.compile(
    r"(?:[A-Z]{2}[0-9]{1,4}-[0-9]{1,4}|" + f"(?:{'|'.join(SERIAL_DOCKET_PREFIXES)})" + r"-[0-9]{1,6})(-[0-9]{3})?"
)
#: YYYYMMDD-NNN(NN): the observed spellings include three-, four- and five-digit tails.
_ACCESSION = re.compile(r"[0-9]{8}-[0-9]{3,5}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SORT = re.compile(r"[A-Za-z]+")

FERC_ELIBRARY = JsonPageFamily(
    name="ferc-elibrary",
    label="FERC eLibrary",
    host="elibrary.ferc.gov",
    requires_credential=False,
    # The family contract's only kind without a publisher continuation. Like an
    # offset walk, ``_walk`` ends at the first short page; it advances a page
    # number in the POST body rather than an offset in the URL.
    next_kind="offset",
)


class FercElibraryError(PagedJsonSourceError):
    """The eLibrary response cannot establish the requested listing, description or file list."""


class FercElibraryUnavailableError(FercElibraryError):
    """Only the exact requested route answered 404/410."""

    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"FERC eLibrary answered HTTP {capture.status_code} for the requested route")
        self.capture = capture


class FercElibraryAccessRefusedError(CredentialRefusedError):
    """A keyless route answered 401/403: no credential was refused, but the run still ends here."""

    def __init__(self, route: str) -> None:
        super().__init__(f"FERC eLibrary refused access for {route}")


def docket_id(value: object) -> str:
    """A FERC docket identity, uppercased: ``RM24-5``, ``AD24-2-000``, ``P-14683-000``, ``ID-10800-000``."""
    if not isinstance(value, str) or _DOCKET.fullmatch(value.strip().upper()) is None:
        raise FercElibraryError("docket must be a FERC docket number such as RM24-5 or AD24-2-000")
    return value.strip().upper()


def accession_number(value: object) -> str:
    """An eLibrary accession identity, as the publisher spells it: ``20240418-4000``."""
    if not isinstance(value, str) or _ACCESSION.fullmatch(value.strip()) is None:
        raise FercElibraryError("accession must be an eLibrary accession number such as 20240418-4000")
    return value.strip()


def search_hit_reference(row: Mapping[str, Any]) -> str:
    """A search row's identity: the publisher's own ``reference`` field, which its table tracks rows by."""
    identity = row.get("reference")
    if not isinstance(identity, str) or not identity.strip():
        raise FercElibraryError("FERC eLibrary search row has no usable reference identity")
    return identity


def new_docket_identity(row: Mapping[str, Any]) -> str:
    """A new-docket row's identity, ``DocketFullNumber`` as served; a row without one cannot be tracked."""
    identity = row.get("DocketFullNumber")
    if not isinstance(identity, str) or not identity.strip():
        raise FercElibraryError("FERC eLibrary new-docket row has no usable DocketFullNumber identity")
    return identity


def docket_sheet_document_accession(row: Mapping[str, Any]) -> str:
    """A sheet document's identity, ``accession_no`` as served, held to the file-list route's accession grammar.

    The publisher's ``document_id`` measured 0 on every row of the qualification docket (2026-09-25).
    """
    identity = row.get("accession_no")
    if not isinstance(identity, str) or _ACCESSION.fullmatch(identity) is None:
        raise FercElibraryError("FERC eLibrary docket-sheet document has no usable accession_no identity")
    return identity


def docket_description_url(docket: str) -> str:
    return f"{API}/Docket/getDocketDescription/{docket_id(docket)}"


def sub_dockets_url(docket: str) -> str:
    """Sub-docket codes for one docket; probed live 2026-09-24 (200, ``{"DataList":["000"]}``)."""
    return f"{API}/Docket/getSubDocketSearch/{docket_id(docket)}"


def file_list_url(accession: str) -> str:
    """The deployed SPA's file-list route; ``File/GetFileListByAccession`` answered IIS 404 live (2026-09-24)."""
    return f"{API}/File/GetFileListFromP8/{accession_number(accession)}"


def new_dockets_url(mode: str, date_from: str, date_to: str, sort: str = NEW_DOCKETS_SORT) -> str:
    """One new-docket window, its ``YYYY-MM-DD`` dates spelled ``MM-dd-yyyy`` as the SPA's form posts them."""
    if mode not in NEW_DOCKET_MODES:
        raise FercElibraryError(f"mode must be one of {', '.join(NEW_DOCKET_MODES)}")
    start, end = _window(date_from, date_to)
    if not isinstance(sort, str) or _SORT.fullmatch(sort) is None:
        raise FercElibraryError("sort must be a field name of ASCII letters")
    return f"{API}/Docket/GetATMSdocs/{mode}/{_short(start)}/{_short(end)}/{sort}"


def _window(date_from: object, date_to: object) -> tuple[str, str]:
    """A ``YYYY-MM-DD`` window, ``date_to`` defaulting to today (UTC); a reversed window refuses."""
    start = _iso_date(date_from)
    end = _iso_date(utc_now().date().isoformat() if date_to is None else date_to)
    if start is None or end is None:
        raise FercElibraryError("date_from and date_to must be YYYY-MM-DD dates")
    if start > end:
        raise FercElibraryError("date_from must not be after date_to")
    return start, end


def _iso_date(value: object) -> str | None:
    """``value`` when it is a real calendar date spelled ``YYYY-MM-DD``, else ``None``."""
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _short(value: str) -> str:
    return date.fromisoformat(value).strftime("%m-%d-%Y")


def _integer(value: object, name: str, low: int, high: int | None = None) -> int:
    """An integer from ``low`` (to ``high``); a bool is not one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        raise FercElibraryError(f"{name} must be an integer from {low}" + (f" to {high}" if high is not None else ""))
    return value


def search_body(
    *,
    docket: str | None = None,
    document_class: Iterable[tuple[str, str]] = (),
    results_per_page: int = MAX_RESULTS_PER_PAGE,
    cur_page: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    idol_result_id: str | None = None,
) -> dict[str, Any]:
    """One ``Search/AdvancedSearch`` body, field for field as the SPA sends it; ``docket=None`` searches every docket.

    The window defaults to ``EARLIEST_DATE`` through today (UTC) with ``allDates:true``;
    either date narrows it and sends ``allDates:false``. ``document_class`` pairs are
    serialized as ``classTypes`` and sent as supplied (``(class, "All")`` selects the
    whole class); empty selects every class.
    """
    _integer(results_per_page, "results_per_page", 1, MAX_RESULTS_PER_PAGE)
    _integer(cur_page, "cur_page", 1)
    if idol_result_id is not None and not isinstance(idol_result_id, str):
        raise FercElibraryError("idol_result_id must be a string or None")
    classes = []
    for entry in document_class:
        if not isinstance(entry, tuple) or len(entry) != 2 or not all(isinstance(p, str) and p.strip() for p in entry):
            raise FercElibraryError("document_class entries must be (class, type) string pairs")
        classes.append({"documentClass": entry[0], "documentType": entry[1]})
    start, end = _window(EARLIEST_DATE if date_from is None else date_from, date_to)
    return {
        "searchText": "*",
        "searchFullText": True,
        "searchDescription": True,
        "dateSearches": [{"dateType": "filed_date", "startDate": start, "endDate": end}],
        "availability": None,
        "affiliations": [],
        "categories": [],
        "libraries": [],
        "accessionNumber": None,
        "eFiling": False,
        "docketSearches": [{"docketNumber": "" if docket is None else docket_id(docket), "subDocketNumbers": []}],
        "resultsPerPage": results_per_page,
        "curPage": cur_page,
        "classTypes": classes,
        "sortBy": "",
        "groupBy": "NONE",
        "idolResultID": idol_result_id,
        "allDates": date_from is None and date_to is None,
    }


def docket_search_body(docket: str, **options: Any) -> dict[str, Any]:
    """The search body restricted to one required, validated docket; ``options`` are ``search_body``'s."""
    return search_body(docket=docket_id(docket), **options)


def docket_sheet_body(
    dockets: str,
    subdockets: str | None = "",
    *,
    date_from: str = "1960-01-01",
    date_to: str | None = None,
    complete_flag: int = 0,
    num_hits: int = MAX_RESULTS_PER_PAGE,
    page_number: int = 0,
) -> dict[str, Any]:
    """One ``Docket/GetSingleDocketSheet`` body as the SPA sends it: lowercase docket, ``MM-dd-yyyy`` window, zero-based page."""
    docket = docket_id(dockets).lower()
    if subdockets is not None and not isinstance(subdockets, str):
        raise FercElibraryError("subdockets must be a string")
    start, end = _window(date_from, date_to)
    return {
        "dockets": docket,
        "subdockets": (subdockets or "").strip(),
        "filed_date_beg": _short(start),
        "filed_date_end": _short(end),
        "complete_flag": _integer(complete_flag, "complete_flag", 0, 1),
        "numHits": _integer(num_hits, "num_hits", 1, MAX_RESULTS_PER_PAGE),
        "pageNumber": _integer(page_number, "page_number", 0),
    }


def _envelope(capture: CapturedBodyResponse, label: str, row_type: type = Mapping) -> tuple[Mapping[str, Any], tuple]:
    """A ``{"DataList", "ErrorList"}`` answer and its rows; a named failure or a malformed list refuses."""
    value = load_decimal_json(capture.body, source="FERC eLibrary", error_type=FercElibraryError)
    if not isinstance(value, Mapping):
        raise FercElibraryError(f"{label} response is not a JSON object")
    errors = value.get("ErrorList")
    if errors is not None and not isinstance(errors, list):
        raise FercElibraryError(f"{label} ErrorList is not a list")
    if errors:
        joined = scrub_credential("; ".join(str(item) for item in errors))[:REASON_CHARACTERS]
        raise FercElibraryError(f"{label} answered with ErrorList: {joined}")
    rows = value.get(DATA_LIST_KEY)
    if not isinstance(rows, list) or not all(isinstance(row, row_type) for row in rows):
        raise FercElibraryError(f"{label} did not answer a list of {row_type.__name__} rows under {DATA_LIST_KEY}")
    return value, tuple(rows)


class DocketDescription(NamedTuple):
    """One docket's own description and kind code, from its two-string answer."""

    docket: str
    description: str
    kind: str | None
    capture: CapturedBodyResponse


class Listing(NamedTuple):
    """One unpaged answer's rows, exactly as served, with the capture that holds them."""

    capture: CapturedBodyResponse
    records: tuple[Mapping[str, Any], ...]


class FileList(NamedTuple):
    """One accession's file rows, exactly as served; the route answers its whole list in one response."""

    accession: str
    capture: CapturedBodyResponse
    records: tuple[Mapping[str, Any], ...]


def read_docket_description(capture: CapturedBodyResponse, *, docket: str) -> DocketDescription:
    """The description and kind code; an empty answer refuses rather than reading as a blank description."""
    _value, rows = _envelope(capture, "FERC eLibrary docket description", str)
    if not rows:
        raise FercElibraryError("FERC eLibrary answered an empty DataList for the requested docket")
    return DocketDescription(docket, rows[0], rows[1] if len(rows) > 1 else None, capture)


def read_sub_dockets(capture: CapturedBodyResponse) -> tuple[str, ...]:
    """``Docket/getSubDocketSearch`` answers the docket's sub-docket codes as strings."""
    return _envelope(capture, "FERC eLibrary sub-dockets", str)[1]


def read_file_list(capture: CapturedBodyResponse, *, accession: str) -> FileList:
    """An accession's file rows; an empty list is a requested-empty observation, returned as zero rows."""
    return FileList(accession, capture, _envelope(capture, "FERC eLibrary file list")[1])


def read_new_dockets(capture: CapturedBodyResponse) -> Listing:
    """A new-docket window's rows; an empty list is a requested-empty observation, returned as zero rows."""
    return Listing(capture, _envelope(capture, "FERC eLibrary new-docket listing")[1])


def read_class_types(capture: CapturedBodyResponse) -> Listing:
    """``Search/GetClassTypes``' bare array, every row and field kept; an empty array is an observation."""
    rows = load_decimal_json(capture.body, source="FERC eLibrary class types", error_type=FercElibraryError)
    if not isinstance(rows, list):
        raise FercElibraryError("FERC eLibrary class types did not answer a JSON array")
    for row in rows:
        if not isinstance(row, Mapping) or any(
            not isinstance(row.get(field), str) or not row[field].strip()
            for field in ("Class", "Type", "Library", "Category")
        ):
            raise FercElibraryError("FERC eLibrary class type row lacks Class, Type, Library or Category")
    return Listing(capture, tuple(rows))


def docket_sheet_rows(row: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """One sheet row flattened to one row per ``DocumentsItem`` entry, ``AuthorsItem``/``FedCitesItem`` attached verbatim."""
    entries = row.get("DocumentsItem")
    if not isinstance(entries, list) or not entries or not all(isinstance(entry, Mapping) for entry in entries):
        raise FercElibraryError("FERC eLibrary docket-sheet row has no usable DocumentsItem list")
    shared = {key: row[key] for key in ("AuthorsItem", "FedCitesItem") if row.get(key) is not None}
    for entry in entries:
        yield {**entry, **shared}


def _read_search_page(capture: CapturedBodyResponse, body: Mapping[str, Any], page_index: int) -> JsonPage:
    """One search envelope: rows, declared total, and the next body when the page came back full."""
    value = load_decimal_json(capture.body, source="FERC eLibrary", error_type=FercElibraryError)
    if not isinstance(value, Mapping):
        raise FercElibraryError("FERC eLibrary search response is not a JSON object")
    if value.get("success") is not True:
        message = value.get("errorMessage")
        detail = f": {scrub_credential(str(message))[:REASON_CHARACTERS]}" if message else ""
        raise FercElibraryError(f"FERC eLibrary search answered success:false{detail}")
    rows = value.get(SEARCH_HITS_KEY)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise FercElibraryError(f"FERC eLibrary search response omitted its {SEARCH_HITS_KEY} list")
    total = _integer(value.get("totalHits"), "FERC eLibrary search totalHits", 0)
    if _integer(value.get("numHits"), "FERC eLibrary search numHits", 0) != len(rows):
        raise FercElibraryError("FERC eLibrary search numHits differs from the rows it sent")
    if len(rows) > body["resultsPerPage"]:
        raise FercElibraryError("FERC eLibrary search page served more rows than resultsPerPage")
    token = value.get("searchResultId")
    carry = token if isinstance(token, str) and token else body.get("idolResultID")
    full = rows and len(rows) == body["resultsPerPage"]
    next_body = {**body, "curPage": body["curPage"] + 1, "idolResultID": carry} if full else None
    return JsonPage(page_index, SEARCH_HITS_KEY, capture, tuple(rows), total, None, dict(body), next_body)


def _read_docket_sheet_page(capture: CapturedBodyResponse, body: Mapping[str, Any], page_index: int) -> JsonPage:
    """One sheet envelope: its flattened documents, ``Page.totalHits``, and the next body when the page came back full."""
    value, rows = _envelope(capture, "FERC eLibrary docket sheet")
    page = value.get("Page")
    if not isinstance(page, Mapping):
        raise FercElibraryError("FERC eLibrary docket-sheet response omitted its Page envelope")
    total = _integer(page.get("totalHits"), "FERC eLibrary docket-sheet Page.totalHits", 0)
    size = _integer(page.get("numHits"), "FERC eLibrary docket-sheet Page.numHits", 0)
    if len(rows) > size:
        raise FercElibraryError("FERC eLibrary docket sheet served more rows than its Page.numHits")
    documents = tuple(document for row in rows for document in docket_sheet_rows(row))
    next_body = {**body, "pageNumber": body["pageNumber"] + 1} if rows and len(rows) == size else None
    return JsonPage(
        page_index, (DATA_LIST_KEY, "DocumentsItem"), capture, documents, total, None, dict(body), next_body
    )


class _Route(NamedTuple):
    """A POST route paged by its request body: where it lives, how a page reads and what identifies a record."""

    url: str
    operation: str
    label: str
    noun: str
    identity: Callable[[Mapping[str, Any]], str]
    read: Callable[[CapturedBodyResponse, Mapping[str, Any], int], JsonPage]


_SEARCH = _Route(
    ADVANCED_SEARCH_URL, "search-page", "FERC eLibrary search", "reference", search_hit_reference, _read_search_page
)
_DOCKET_SHEET = _Route(
    DOCKET_SHEET_URL,
    "docket-sheet-page",
    "FERC eLibrary docket sheet",
    "accession",
    docket_sheet_document_accession,
    _read_docket_sheet_page,
)


def elibrary_transport(transport: httpx.BaseTransport | None = None) -> httpx.BaseTransport:
    """Send the SPA interceptor's headers on every request: application id, one session id, a fresh correlation id.

    The session id lives as long as the returned transport, as the SPA keeps one in
    ``sessionStorage``; the User-Agent is ``BROWSER_USER_AGENT``. Every eLibrary client
    in this package wraps its transport here.
    """
    from uuid import uuid4

    import httpx

    wrapped = transport if transport is not None else httpx.HTTPTransport()
    session_id = str(uuid4())

    class _SpaHeaders(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            request.headers["user-agent"] = BROWSER_USER_AGENT
            request.headers["x-applicationid"] = APPLICATION_ID
            request.headers["x-sessionid"] = session_id
            request.headers["x-correlationid"] = str(uuid4())
            return wrapped.handle_request(request)

        def close(self) -> None:
            wrapped.close()

    return _SpaHeaders()


class FercElibraryReader(PagedJsonReader):
    """Docket descriptions, sub-dockets, file lists, class types, new dockets and the two body-paged walks."""

    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(
            family=FERC_ELIBRARY, budget=budget, api_key=None, transport=elibrary_transport(transport), clock=clock
        )

    def _capture[Result](
        self,
        url: str,
        parse: Callable[[CapturedBodyResponse], Result],
        *,
        operation: str,
        body: Mapping[str, Any] | None = None,
        page_index: int | None = None,
    ) -> Result:
        """One keyless GET, or a POST of ``body``; a 401/403 is recast as this family's refusal."""
        url = self.family.check_url(url)
        context: dict[str, object] = {"operation": operation, "family": self.family.name, "url": url}
        if body is not None:
            context |= {"requestBody": dict(body), "pageIndex": page_index}
        with named_challenge(url, error_type=FercElibraryAccessRefusedError, context_key=self.context_key):
            result, _capture = self.capture_validated(
                url,
                media_types=self.family.media_types,
                parse=lambda capture, _limit: parse(capture),
                max_bytes=self.budget.max_page_bytes,
                unavailable=FercElibraryUnavailableError,
                context=context,
                method="GET" if body is None else "POST",
                content=None if body is None else encode_body(body),
                request_headers=None if body is None else {"Content-Type": "application/json"},
            )
        return result

    def docket_description(self, docket: str) -> DocketDescription:
        """One docket's description and kind code (live for RM24-5, 2026-09-24)."""
        identity = docket_id(docket)
        return self._capture(
            docket_description_url(identity),
            lambda capture: read_docket_description(capture, docket=identity),
            operation="docket-description",
        )

    def class_types(self) -> Listing:
        """The live search vocabulary, including legacy values absent from the pinned PDF."""
        return self._capture(CLASS_TYPES_URL, read_class_types, operation="class-types")

    def sub_dockets(self, docket: str) -> tuple[str, ...]:
        """The docket's sub-docket codes."""
        return self._capture(sub_dockets_url(docket), read_sub_dockets, operation="sub-dockets")

    def file_list(self, accession: str) -> FileList:
        """One accession's file rows; an empty list is a requested-empty observation, returned as zero rows."""
        identity = accession_number(accession)
        return self._capture(
            file_list_url(identity), lambda capture: read_file_list(capture, accession=identity), operation="file-list"
        )

    def new_dockets(self, mode: str, date_from: str, date_to: str, *, sort: str = NEW_DOCKETS_SORT) -> Listing:
        """One date window's new dockets; an empty answer is a requested-empty observation, not absence."""
        return self._capture(
            new_dockets_url(mode, date_from, date_to, sort=sort), read_new_dockets, operation="new-dockets"
        )

    def search_pages(self, body: Mapping[str, Any], *, max_pages: int = MAX_PAGES) -> Iterator[JsonPage]:
        """Walk one search from ``curPage: 1`` to its terminal page, carrying ``searchResultId`` forward as the SPA does."""
        _integer(body.get("resultsPerPage"), "resultsPerPage", 1, MAX_RESULTS_PER_PAGE)
        return self._walk(_SEARCH, {**body, "curPage": 1}, max_pages)

    def docket_sheet_pages(self, body: Mapping[str, Any], *, max_pages: int = MAX_PAGES) -> Iterator[JsonPage]:
        """Walk one docket sheet from its body's ``pageNumber``; records are the flattened documents."""
        _integer(body.get("numHits"), "numHits", 1, MAX_RESULTS_PER_PAGE)
        _integer(body.get("pageNumber"), "pageNumber", 0)
        return self._walk(_DOCKET_SHEET, body, max_pages)

    def _walk(self, route: _Route, body: Mapping[str, Any], max_pages: int) -> Iterator[JsonPage]:
        """Advance the body while pages come back full; refuse a moved total, overserving, a repeat, a bound or a mismatch.

        Pages already yielded stay partial observations when a later page refuses. Every
        refusal carries the page it was decided on and the traversal's counts.
        """
        check_request_count(max_pages, "max_pages")
        declared: int | None = None
        observed = 0
        seen: set[str] = set()
        for index in range(max_pages):
            page = self._capture(
                route.url,
                lambda capture, body=body, index=index: route.read(capture, body, index),
                operation=route.operation,
                body=body,
                page_index=index,
            )
            try:
                if declared is None:
                    declared = page.declared_count
                elif page.declared_count != declared:
                    raise DeclaredCountChanged(
                        f"{route.label} declared count changed during the traversal",
                        declared=declared,
                        changed_to=page.declared_count,
                    )
                observed += len(page.records)
                if observed > declared:
                    raise FercElibraryError(f"{route.label} returned more records than it declared")
                for record in page.records:
                    identity = route.identity(record)
                    if identity in seen:
                        raise FercElibraryError(f"{route.label} returned repeated {route.noun} {identity!r}")
                    seen.add(identity)
            except PagedJsonSourceError as error:
                raise self._refused(error, route, page, observed=observed, declared=declared) from None
            yield page
            if page.next_body is None:
                if observed != declared:
                    mismatch = DeclaredCountMismatch(
                        f"{route.label} declared and observed record counts differ",
                        declared=declared,
                        observed=observed,
                    )
                    raise self._refused(mismatch, route, page, observed=observed, declared=declared)
                return
            body = page.next_body
        raise FercElibraryError(f"{route.label} page bound reached before a terminal page")

    def _refused(
        self, error: PagedJsonSourceError, route: _Route, page: JsonPage, *, observed: int, declared: int | None
    ) -> PagedJsonSourceError:
        """Attach the page a walk refusal was decided on, and the traversal's position and counts."""
        attach_capture(error, page.capture)
        attach_refused_response(error, refused_capture(page.capture, stage="source-validation"))
        return self._trace_traversal(
            error,
            url=route.url,
            body=page.request_body,
            page_index=page.page_index,
            records_key=page.records_key,
            single_record=False,
            observed=observed,
            declared=declared,
        )


__all__ = [
    "ACCESSION_FIELD",
    "ADVANCED_SEARCH_URL",
    "API",
    "APPLICATION_ID",
    "BROWSER_USER_AGENT",
    "CLASS_TYPES_URL",
    "DATA_LIST_KEY",
    "DOCKET_SHEET_URL",
    "EARLIEST_DATE",
    "FERC_ELIBRARY",
    "MAX_PAGES",
    "MAX_RESULTS_PER_PAGE",
    "NEW_DOCKETS_SORT",
    "NEW_DOCKET_MODES",
    "NEW_DOCKET_WINDOW_DAYS",
    "RULEMAKING_COMMENT",
    "SEARCH_HITS_KEY",
    "DocketDescription",
    "FercElibraryAccessRefusedError",
    "FercElibraryError",
    "FercElibraryReader",
    "FercElibraryUnavailableError",
    "FileList",
    "Listing",
    "accession_number",
    "docket_description_url",
    "docket_id",
    "docket_search_body",
    "docket_sheet_body",
    "docket_sheet_document_accession",
    "docket_sheet_rows",
    "elibrary_transport",
    "file_list_url",
    "new_docket_identity",
    "new_dockets_url",
    "read_class_types",
    "read_docket_description",
    "read_file_list",
    "read_new_dockets",
    "read_sub_dockets",
    "search_body",
    "search_hit_reference",
    "sub_dockets_url",
]
