"""FCC ECFS proceedings and filings: offset walks over explicit date windows with exact evidence.

The Electronic Comment Filing System API answers rows under ``proceeding`` or
``filing`` beside ``aggregations``, with no count and no continuation, so the
reader advances ``offset`` by the rows received and stops at the first short
page. The api.data.gov key travels as ``X-Api-Key``. Date filters use the
publisher's bracketed literal ``[gte]YYYY-MM-DD[lte]YYYY-MM-DD``; deep offsets
are capped by the publisher, so callers narrow windows rather than walk far.

**Both bracketed bounds are instants, not days, so a caller's inclusive end day
is sent as the following date.** ``[gte]D[lte]E`` selects
``D T00:00:00Z <= t <= E T00:00:00Z``: the end date contributes its midnight
instant and none of its own day. Measured live on 2026-09-14 (receipt
``supply-2026-09-02/receipts/publisher-questions-2026-09-14/q1-fcc-same-day``),
sorting ``date_received`` descending with ``limit=5``:

- ``[gte]2026-09-08[lte]2026-09-08`` — 0 rows;
- ``[gte]2026-09-08[lte]2026-09-09`` — 5 rows, newest ``2026-09-08T23:56:03Z``,
  and ascending the oldest was ``2026-09-08T04:47:28Z``: exactly the 8th;
- ``[gte]2026-09-01[lte]2026-09-02`` — newest ``2026-09-01T23:59:15Z``, 45
  seconds short of the bound.

So ``_window_url`` spells the caller's inclusive ``*_to`` date as ``end + 1
day``, and ``filings_url(received_from=D, received_to=D)`` means the whole of
day D. A time component does **not** widen the window: both
``[lte]2026-09-08T23:59:59`` and ``[lte]2026-09-08 23:59:59`` answered the same
zero-row page. That page is byte-identical (1,037 bytes, SHA-256
``088009f281836c186fdb6709ca39c8723e9f814890a57a1a3907431da348d7ae``) for every
empty filings query, so an ignored filter and a matched-nothing filter cannot be
told apart here, and no zero on this route establishes absence.

Two consequences of using the publisher's inclusive ``[lte]``: a row stamped
exactly ``E+1 T00:00:00.000Z`` falls in the window, so adjacent day windows
overlap by that one instant; and ``[lt]`` was observed once to be honoured as an
end bound (``[gte]2026-09-08[lt]2026-09-09`` returned the same 21,278 bytes and
digest as ``[lte]2026-09-09``), which would close that instant but is one
observation of an operator the publisher does not document.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date as Date
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
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
    """The date whose midnight closes an inclusive window ending on ``end`` -- the day after it.

    The publisher's ``[lte]`` names an instant at ``00:00:00Z``, so the caller's
    last wanted day is bounded by the following date's midnight. See the module
    docstring for the measurement.
    """
    try:
        return (Date.fromisoformat(end) + timedelta(days=1)).isoformat()
    except OverflowError as error:
        raise PagedJsonSourceError("end must leave a following date for the publisher's bound") from error


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
        return self.pages(url, records_key=PROCEEDINGS_KEY, max_pages=max_pages)

    def filings(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=FILINGS_KEY, max_pages=max_pages)
