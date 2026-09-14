"""SAM.gov entity registrations, page by page with exact evidence.

The Entity Management API answers ``totalRecords``, ``entityData`` and
``links.nextLink``. It needs a SAM.gov-issued key, which travels as
``X-Api-Key``; the publisher's links carry an ``api_key=REPLACE_WITH_API_KEY``
placeholder that the reader drops before requesting.

**A walk reaches the first 10,000 records of a query and no more, and the
publisher never says so.** Measured live on 2026-09-14 with
``registrationStatus=A`` (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-14/q4-sam-deep-cap``),
one request per page: at ``size=10`` pages 0, 498, 499, 500 and 999 each served
``200`` with ten rows, while page 1000 answered ``400`` in the publisher's own
words --

    {"httpStatus":"400","title":"Results Too Large","detail":"The Page and Size
    search has exceeded 10,000 records (Page multiplied by Size). Please change
    the Page and Size accordingly.","type":"Invalid input","errorCode":"RTL", …}

-- and at ``size=7`` page 1427 served while page 1428 answered ``400``
``{"title":"Error In Creating Data","detail":"Invalid input value", …
"errorCode":"PRM"}``. Two spellings of the refusal, one boundary: a page is
refused once ``(page + 1) * size`` passes ``MAX_REACHABLE_RECORDS``, so
``reachable_records(size)`` records are reachable and the rest of the query is
not. This contradicts spicy-regs' note of a walk topping out near 5,000; 10,000
is what the publisher answered here, on one query on one day.

Every reachable page still states a ``links.nextLink`` -- page 999 pointed at
the page that refuses -- so following continuations walks 1,000 requests into a
``400`` that looks like drift. ``SamEntitiesReader.entities`` therefore compares
the first page's ``totalRecords`` against what the walk can reach and refuses
there, in one request, telling the caller to window by ``registrationDate``.
``totalRecords`` for ``registrationStatus=A`` read 790,545 and then 790,559
twenty minutes later: a declared count is that instant's statement, and it is
not what a walk can see.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date as Date
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode

from spicy_docs.sources.paged_json import (
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
