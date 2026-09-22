"""SAM.gov entity registrations, page by page with exact evidence.

The Entity Management API answers ``totalRecords``, ``entityData`` and
``links.nextLink``, and needs a SAM.gov-issued key, sent as ``X-Api-Key``; the
publisher's links carry an ``api_key=REPLACE_WITH_API_KEY`` placeholder that the
reader drops before requesting.

**A walk reaches the first 10,000 records of a query and no more, and the
publisher never says so.** A page is refused once ``(page + 1) * size`` passes
``MAX_REACHABLE_RECORDS``, in two spellings of ``400`` (``RTL`` "Results Too
Large" and ``PRM`` "Error In Creating Data"), while every reachable page still
states a ``links.nextLink`` pointing past the cap. Measured live on 2026-09-14
with ``registrationStatus=A`` (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-14/q4-sam-deep-cap``);
it contradicts an earlier note of a walk topping out near 5,000.
``SamEntitiesReader.entities`` therefore compares the first page's
``totalRecords`` against ``reachable_records`` and refuses a too-deep query
after one request, telling the caller to window by ``registrationDate``; a
declared total (790,545, then 790,559 twenty minutes later) is that instant's
statement, not what a walk can see.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date as Date
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode

from spicy_docs.reading.paged_json import (
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
)
from spicy_docs.transport.source_acquirer import utc_now

if TYPE_CHECKING:
    import httpx

API = "https://api.sam.gov/entity-information/v4"
MAX_SIZE = 10
SIZE_FIELD = "size"
# The publisher refuses a page once (page + 1) * size passes this; see the module docstring.
MAX_REACHABLE_RECORDS = 10_000
ENTITIES_KEY = "entityData"
type RegistrationStatus = Literal["A", "E"]
SAM = JsonPageFamily(
    name="sam",
    label="SAM.gov",
    host="api.sam.gov",
    next_path=("links", "nextLink"),
    count_path=("totalRecords",),
    drop_query_names=frozenset({"api_key"}),
    limit_field=SIZE_FIELD,
    max_reachable_records=MAX_REACHABLE_RECORDS,
    window_hint="registrationDate window",
)


def reachable_records(size: int) -> int:
    """How many records a walk at this page size can reach: whole pages within the publisher's cap."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PagedJsonSourceError("size must be a positive integer")
    return MAX_REACHABLE_RECORDS // size * size


def _us_date(value: Date, name: str) -> str:
    if not isinstance(value, Date) or isinstance(value, datetime):
        raise PagedJsonSourceError(f"{name} must be a date")
    return value.strftime("%m/%d/%Y")


def entities_url(
    *,
    registration_status: RegistrationStatus | None = "A",
    registered_from: Date | None = None,
    registered_to: Date | None = None,
    size: int = MAX_SIZE,
    page: int = 0,
) -> str:
    """Name one entity query; a registration window is the publisher's ``[MM/DD/YYYY,MM/DD/YYYY]`` literal."""
    if registration_status is not None and registration_status not in ("A", "E"):
        raise PagedJsonSourceError("registration_status must be 'A' (active), 'E' (expired) or None")
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_SIZE:
        raise PagedJsonSourceError(f"size must be an integer from 1 to {MAX_SIZE}")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise PagedJsonSourceError("page must be a non-negative integer")
    if (registered_from is None) != (registered_to is None):
        raise PagedJsonSourceError("a registration window needs both registered_from and registered_to")
    query: list[tuple[str, str]] = []
    if registration_status is not None:
        query.append(("registrationStatus", registration_status))
    if registered_from is not None and registered_to is not None:
        if registered_to < registered_from:
            raise PagedJsonSourceError("registered_to precedes registered_from")
        query.append(
            (
                "registrationDate",
                f"[{_us_date(registered_from, 'registered_from')},{_us_date(registered_to, 'registered_to')}]",
            )
        )
    query += [(SIZE_FIELD, str(size)), ("page", str(page))]
    return f"{API}/entities?{urlencode(query, safe='[],/')}"


class SamEntitiesReader(PagedJsonReader):
    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=SAM, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def entities(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk entity pages; the family's reach bound refuses a too-deep query after its first page."""
        return self.pages(url, records_key=ENTITIES_KEY, max_pages=max_pages)


def _next_day(value: Date) -> Date:
    return Date.fromordinal(value.toordinal() + 1)


def windowed_entities(
    reader: SamEntitiesReader,
    *,
    registered_from: Date,
    registered_to: Date,
    registration_status: RegistrationStatus | None = "A",
    max_records: int | None = None,
    max_pages: int = MAX_REACHABLE_RECORDS // MAX_SIZE + 2,
) -> Iterator[dict]:
    """Walk a registration range, subdividing windows the publisher cannot page through.

    The publisher refuses a walk once ``(page + 1) * size`` passes
    ``MAX_REACHABLE_RECORDS`` (module docstring), so a window whose declared
    total exceeds the reach bound at the walk size is halved recursively until
    pageable; a single day still over the bound refuses rather than publishing
    only the reachable records. Each leaf window is walked by the paged
    reader with its exact-count checks; ``max_records`` bounds emitted records
    across the whole range. Use :class:`spicy_docs.sources.sam_extract.SamBulkExtract`
    for full coverage instead of many windowed walks.
    """
    if max_records is not None and (type(max_records) is not int or max_records <= 0):
        raise PagedJsonSourceError("max_records must be a positive integer or None")
    if isinstance(registered_from, datetime) or isinstance(registered_to, datetime):
        raise PagedJsonSourceError("registration bounds must be dates")
    if registered_to < registered_from:
        raise PagedJsonSourceError("registered_to precedes registered_from")
    emitted = 0

    def budget_left() -> bool:
        return max_records is None or emitted < max_records

    def walk(gte: Date, lte: Date) -> Iterator[dict]:
        nonlocal emitted
        if not budget_left():
            return
        probe_url = entities_url(
            registration_status=registration_status, registered_from=gte, registered_to=lte, size=1, page=0
        )
        probe = next(reader.entities(probe_url, max_pages=1))
        total = probe.declared_count
        reachable = reachable_records(MAX_SIZE)
        if total is not None and total > reachable and gte < lte:
            mid = gte + (lte - gte) // 2
            yield from walk(gte, mid)
            yield from walk(_next_day(mid), lte)
            return
        if total is not None and total > reachable:
            raise PagedJsonSourceError(
                "SAM single-day selection exceeds the reachable page limit; use the bulk extract"
            )
        url = entities_url(
            registration_status=registration_status, registered_from=gte, registered_to=lte, size=MAX_SIZE, page=0
        )
        for page in reader.entities(url, max_pages=max_pages):
            for record in page.records:
                if not budget_left():
                    return
                emitted += 1
                yield dict(record)

    yield from walk(registered_from, registered_to)
