"""SAM.gov entity registrations, page by page with exact evidence.

The Entity Management API answers ``totalRecords``, ``entityData`` and
``links.nextLink``. It needs a SAM.gov-issued key, which travels as
``X-Api-Key``; the publisher's links carry an ``api_key=REPLACE_WITH_API_KEY``
placeholder that the reader drops before requesting. Deep walks are capped by
the publisher, so callers window by ``registrationDate``.
"""

from __future__ import annotations

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

API = "https://api.sam.gov/entity-information/v4"
MAX_SIZE = 10
ENTITIES_KEY = "entityData"
type RegistrationStatus = Literal["A", "E"]
SAM = JsonPageFamily(
    name="sam",
    label="SAM.gov",
    host="api.sam.gov",
    next_path=("links", "nextLink"),
    count_path=("totalRecords",),
    drop_query_names=frozenset({"api_key"}),
)


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
    query += [("size", str(size)), ("page", str(page))]
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
        return self.pages(url, records_key=ENTITIES_KEY, max_pages=max_pages)
