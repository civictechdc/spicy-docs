"""FCC ECFS proceedings and filings: explicit date selections with exact page evidence.

The low-level page iterators stop at the first short page. ``iter_filings``
also checks the native aggregation, pools shifted walks by submission ID and
partitions crowded selections before reaching the publisher's offset ceiling.
The api.data.gov key travels as ``X-Api-Key``.

Date builders retain the established following-day end bound. Closed timestamp
ranges can overlap at their boundary; ``[lt]`` did not exclude that boundary in
the September 25, 2026 probes. The earlier empty same-day response did not
establish timestamp precision or timezone semantics. See ``docs/sources/listings.md``
and campaign receipts ``fcc-pagination-research-2026-09-25T100156Z``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from datetime import date as Date
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
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

API = "https://publicapi.fcc.gov/ecfs"
MAX_LIMIT = 250
MAX_FILINGS_LIMIT = 5_000
DEFAULT_FILINGS_LIMIT = 1_000
PROCEEDINGS_KEY = "proceeding"
FILINGS_KEY = "filing"
FCC_ECFS = JsonPageFamily(
    name="fcc-ecfs",
    label="FCC ECFS",
    host="publicapi.fcc.gov",
    next_kind="offset",
    limit_field="limit",
    offset_field="offset",
)


def _date(value: str, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DD")
    try:
        Date.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid calendar date") from error
    return value


def _end_bound(end: str) -> str:
    """Keep the established following-day bound for a caller's inclusive end date."""
    try:
        return (Date.fromisoformat(end) + timedelta(days=1)).isoformat()
    except OverflowError as error:
        raise PagedJsonSourceError("end must leave a following date for the publisher's bound") from error


def _window_url(
    endpoint: str, date_field: str, *, start: str, end: str, limit: int, offset: int, descending: bool
) -> str:
    """Build one offset-walk URL; the inclusive end is spelled as the following midnight."""
    start, end = _date(start, "start"), _date(end, "end")
    if end < start:
        raise PagedJsonSourceError("end precedes start")
    maximum = MAX_FILINGS_LIMIT if endpoint == "filings" else MAX_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise PagedJsonSourceError(f"limit must be an integer from 1 to {maximum}")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PagedJsonSourceError("offset must be a non-negative integer")
    query = [
        (date_field, f"[gte]{start}[lte]{_end_bound(end)}"),
        ("sort", f"{date_field},{'DESC' if descending else 'ASC'}"),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    return f"{API}/{endpoint}?{urlencode(query)}"


def proceedings_url(
    *, created_from: str, created_to: str, limit: int = 100, offset: int = 0, descending: bool = True
) -> str:
    """Proceedings created in a window, by ``date_proceeding_created``; both dates are included."""
    return _window_url(
        "proceedings",
        "date_proceeding_created",
        start=created_from,
        end=created_to,
        limit=limit,
        offset=offset,
        descending=descending,
    )


def filings_url(
    *, received_from: str, received_to: str, limit: int = 100, offset: int = 0, descending: bool = True
) -> str:
    """Filings received in a window, by ``date_received``; both dates are included."""
    return _window_url(
        "filings",
        "date_received",
        start=received_from,
        end=received_to,
        limit=limit,
        offset=offset,
        descending=descending,
    )


class FccEcfsReader(PagedJsonReader):
    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=FCC_ECFS, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def proceedings(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk proceeding pages for one window URL under the family's shared budget."""
        return self.pages(url, records_key=PROCEEDINGS_KEY, max_pages=max_pages)

    def filings(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk filing pages for one window URL under the family's shared budget."""
        return self.pages(url, records_key=FILINGS_KEY, max_pages=max_pages)

    def iter_filings(
        self,
        *,
        received_from: str,
        received_to: str,
        proceeding: str | None = None,
        limit: int = DEFAULT_FILINGS_LIMIT,
        on_page: Callable[[JsonPage], None] | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        """Enumerate a received-date selection, splitting crowded submission timestamp ranges.

        Yield native filings with bounded memory. ``on_page`` receives every
        exact page, including probes and repeated walks, for caller-owned
        evidence retention. Stage outputs until normal iterator exhaustion:
        later pages or partition reconciliation can still refuse the selection.
        A row outside the received dates or proceeding actually sent refuses:
        an ignored filter and one that matched nothing look the same.
        Refresh, checkpoints, attachment acquisition and publication remain
        caller-owned. This is an observed selection, not an atomic API snapshot.
        """
        from spicy_docs.sources.fcc_ecfs_filings import iter_filings

        return iter_filings(
            self,
            received_from=received_from,
            received_to=received_to,
            proceeding=proceeding,
            limit=limit,
            on_page=on_page,
        )
