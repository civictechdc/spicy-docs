"""Explicit Congress.gov v3 list operations: bills and CRS reports, page by page with exact evidence.

The bill and CRS report lists answer JSON pages with the rows under ``bills``
or ``CRSReports``, a ``pagination.count`` for the whole query and a full
``pagination.next`` URL. The api.data.gov key travels as ``X-Api-Key``. Callers
choose the window with ``fromDateTime``/``toDateTime``; the walk runs to the
publisher's terminal page or refuses. A count is the publisher's statement for
that query on that day, not a frozen inventory.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Literal
from urllib.parse import urlencode

import httpx

from spicy_docs.sources.congress.bill_status import BILL_TYPES
from spicy_docs.sources.paged_json import (
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
)
from spicy_docs.transport.source_acquirer import utc_now

API = "https://api.congress.gov/v3"
MAX_LIMIT = 250
BILLS_KEY = "bills"
CRS_REPORTS_KEY = "CRSReports"
type ListSort = Literal["updateDate asc", "updateDate desc"]
CONGRESS_GOV = JsonPageFamily(
    name="congress-gov",
    label="Congress.gov",
    host="api.congress.gov",
    next_path=("pagination", "next"),
    count_path=("pagination", "count"),
)
_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _datetime(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATETIME.fullmatch(value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid UTC datetime") from error
    return value


def _query(*, from_datetime: str | None, to_datetime: str | None, limit: int, sort: ListSort) -> list[tuple[str, str]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise PagedJsonSourceError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if sort not in ("updateDate asc", "updateDate desc"):
        raise PagedJsonSourceError("sort must be 'updateDate asc' or 'updateDate desc'")
    start = _datetime(from_datetime, "from_datetime")
    end = _datetime(to_datetime, "to_datetime")
    if start is not None and end is not None and end < start:
        raise PagedJsonSourceError("to_datetime precedes from_datetime")
    query = [("format", "json"), ("limit", str(limit)), ("sort", sort)]
    if start is not None:
        query.append(("fromDateTime", start))
    if end is not None:
        query.append(("toDateTime", end))
    return query


def bill_list_url(
    *,
    congress: int | None = None,
    bill_type: str | None = None,
    from_datetime: str | None = None,
    to_datetime: str | None = None,
    limit: int = MAX_LIMIT,
    sort: ListSort = "updateDate desc",
) -> str:
    """Name one bill list query; a bill type requires its Congress."""
    path = "/bill"
    if congress is not None:
        if isinstance(congress, bool) or not isinstance(congress, int) or not 1 <= congress <= 999:
            raise PagedJsonSourceError("congress must be an integer from 1 to 999")
        path += f"/{congress}"
        if bill_type is not None:
            if bill_type not in BILL_TYPES:
                raise PagedJsonSourceError("bill_type must be a supported lowercase bill or resolution type")
            path += f"/{bill_type}"
    elif bill_type is not None:
        raise PagedJsonSourceError("bill_type requires an explicit congress")
    query = _query(from_datetime=from_datetime, to_datetime=to_datetime, limit=limit, sort=sort)
    return f"{API}{path}?{urlencode(query)}"


def crs_report_list_url(
    *,
    from_datetime: str | None = None,
    to_datetime: str | None = None,
    limit: int = MAX_LIMIT,
    sort: ListSort = "updateDate desc",
) -> str:
    query = _query(from_datetime=from_datetime, to_datetime=to_datetime, limit=limit, sort=sort)
    return f"{API}/crsreport?{urlencode(query)}"


class CongressListingReader(PagedJsonReader):
    """Bill and CRS report lists; every page is one bounded, evidenced request."""

    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=CONGRESS_GOV, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def bills(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=BILLS_KEY, max_pages=max_pages)

    def crs_reports(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=CRS_REPORTS_KEY, max_pages=max_pages)
