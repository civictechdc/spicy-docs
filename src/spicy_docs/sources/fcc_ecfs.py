"""FCC ECFS proceedings and filings: offset walks over explicit date windows with exact evidence.

The Electronic Comment Filing System API answers rows under ``proceeding`` or
``filing`` beside ``aggregations``, with no count and no continuation, so the
reader advances ``offset`` by the rows received and stops at the first short
page. The api.data.gov key travels as ``X-Api-Key``. Date filters use the
publisher's bracketed literal ``[gte]YYYY-MM-DD[lte]YYYY-MM-DD``; deep offsets
are capped by the publisher, so callers narrow windows rather than walk far.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date as Date
from datetime import datetime
from urllib.parse import urlencode

import httpx

from spicy_docs.sources.paged_json import (
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
)
from spicy_docs.transport.source_acquirer import utc_now

API = "https://publicapi.fcc.gov/ecfs"
MAX_LIMIT = 250
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


def _window_url(
    endpoint: str, date_field: str, *, start: str, end: str, limit: int, offset: int, descending: bool
) -> str:
    start, end = _date(start, "start"), _date(end, "end")
    if end < start:
        raise PagedJsonSourceError("end precedes start")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise PagedJsonSourceError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PagedJsonSourceError("offset must be a non-negative integer")
    query = [
        (date_field, f"[gte]{start}[lte]{end}"),
        ("sort", f"{date_field},{'DESC' if descending else 'ASC'}"),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    return f"{API}/{endpoint}?{urlencode(query)}"


def proceedings_url(
    *, created_from: str, created_to: str, limit: int = 100, offset: int = 0, descending: bool = True
) -> str:
    """Proceedings created in a window, by ``date_proceeding_created``."""
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
    """Filings received in a window, by ``date_received``."""
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
        return self.pages(url, records_key=PROCEEDINGS_KEY, max_pages=max_pages)

    def filings(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=FILINGS_KEY, max_pages=max_pages)
