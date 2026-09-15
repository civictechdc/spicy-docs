"""CourtListener v4 search: RECAP dockets and opinion clusters, page by page with exact evidence.

The public ``/search/`` endpoint answers ``count``, ``next`` and ``results``;
``next`` carries an opaque cursor, and cursor pagination requires ``dateFiled``
ordering. Keyless requests are served at a lower rate limit; a token travels
as ``Authorization: Token <token>``. ``type=r`` lists RECAP dockets (with a
``document_count`` beside ``count``); ``type=o`` lists opinion clusters. The
bulk exports remain the route for whole-collection work.
"""

from __future__ import annotations

import re
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

API = "https://www.courtlistener.com/api/rest/v4"
RESULTS_KEY = "results"
type SearchKind = Literal["r", "o"]
type SearchOrder = Literal["dateFiled asc", "dateFiled desc"]
COURTLISTENER = JsonPageFamily(
    name="courtlistener",
    label="CourtListener",
    host="www.courtlistener.com",
    next_path=("next",),
    count_path=("count",),
    credential_header="Authorization",
    credential_format="Token {key}",
    requires_credential=False,
)
_COURT = re.compile(r"[a-z0-9]{1,32}")


def _filed(value: str | None, name: str) -> str | None:
    """The search endpoint takes MM/DD/YYYY; callers pass ISO dates."""
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DD")
    try:
        parsed = Date.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid calendar date") from error
    return parsed.strftime("%m/%d/%Y")


def search_url(
    *,
    kind: SearchKind,
    filed_after: str | None = None,
    filed_before: str | None = None,
    order_by: SearchOrder = "dateFiled asc",
    court: str | None = None,
    nature_of_suit: str | None = None,
    q: str | None = None,
) -> str:
    if kind not in ("r", "o"):
        raise PagedJsonSourceError("kind must be 'r' (RECAP dockets) or 'o' (opinion clusters)")
    if order_by not in ("dateFiled asc", "dateFiled desc"):
        raise PagedJsonSourceError("cursor pagination requires dateFiled ordering")
    if court is not None and (not isinstance(court, str) or _COURT.fullmatch(court) is None):
        raise PagedJsonSourceError("court must be a lowercase CourtListener court identifier")
    query: list[tuple[str, str]] = [("type", kind), ("order_by", order_by)]
    for name, value in (
        ("filed_after", _filed(filed_after, "filed_after")),
        ("filed_before", _filed(filed_before, "filed_before")),
    ):
        if value is not None:
            query.append((name, value))
    for name, value in (("court", court), ("nature_of_suit", nature_of_suit), ("q", q)):
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise PagedJsonSourceError(f"{name} must be a nonempty string of at most 512 characters")
            query.append((name, value))
    return f"{API}/search/?{urlencode(query)}"


class CourtListenerSearchReader(PagedJsonReader):
    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=COURTLISTENER, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def search(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=RESULTS_KEY, max_pages=max_pages)
