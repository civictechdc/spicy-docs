"""Senate Lobbying Disclosure Act filings from lda.gov, page by page with exact evidence.

The LDA REST API lists filings under ``results`` with ``count``, ``next`` and
``previous``. Keyless requests are served at a lower rate limit; a registered
key travels as ``Authorization: Token <key>``. Filter by filing year and by the
date a filing was posted, ordered by ``dt_posted`` so a window can be resumed
from its last posted date.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date as Date
from datetime import datetime
from typing import Literal
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

API = "https://lda.gov/api/v1"
MAX_PAGE_SIZE = 25
FILINGS_KEY = "results"
type FilingOrdering = Literal["dt_posted", "-dt_posted"]
LDA = JsonPageFamily(
    name="lda",
    label="LDA",
    host="lda.gov",
    next_path=("next",),
    count_path=("count",),
    credential_header="Authorization",
    credential_format="Token {key}",
    requires_credential=False,
)


def _date(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DD")
    try:
        Date.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid calendar date") from error
    return value


def filings_url(
    *,
    filing_year: int | None = None,
    posted_after: str | None = None,
    posted_before: str | None = None,
    page_size: int = MAX_PAGE_SIZE,
    ordering: FilingOrdering = "dt_posted",
) -> str:
    """Name one filings query; the first page is page 1 and the publisher supplies the rest."""
    if filing_year is not None and (
        isinstance(filing_year, bool) or not isinstance(filing_year, int) or not 1999 <= filing_year <= 2100
    ):
        raise PagedJsonSourceError("filing_year must be an integer from 1999 to 2100")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise PagedJsonSourceError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
    if ordering not in ("dt_posted", "-dt_posted"):
        raise PagedJsonSourceError("ordering must be 'dt_posted' or '-dt_posted'")
    start, end = _date(posted_after, "posted_after"), _date(posted_before, "posted_before")
    if start is not None and end is not None and end < start:
        raise PagedJsonSourceError("posted_before precedes posted_after")
    query: list[tuple[str, str]] = []
    if filing_year is not None:
        query.append(("filing_year", str(filing_year)))
    if start is not None:
        query.append(("filing_dt_posted_after", start))
    if end is not None:
        query.append(("filing_dt_posted_before", end))
    query += [("ordering", ordering), ("page", "1"), ("page_size", str(page_size))]
    return f"{API}/filings/?{urlencode(query)}"


class LdaFilingsReader(PagedJsonReader):
    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=LDA, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def filings(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(url, records_key=FILINGS_KEY, max_pages=max_pages)
