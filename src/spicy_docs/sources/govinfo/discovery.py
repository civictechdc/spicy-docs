"""Bounded GovInfo JSON discovery: what packages a collection published or changed, and a package's granules.

The keyed GovInfo API serves list pages whose rows sit under ``packages`` or
``granules`` with a ``count`` and a full ``nextPage`` URL carrying an opaque
``offsetMark``; the api.data.gov key travels as ``X-Api-Key``, and
``lastModified`` is the publisher's added-or-updated time, distinct from the
MODS issued or ingested dates. A nonexistent selection answers with a
well-formed empty page, so a ``count`` of zero is an observation of that query
on that day and never establishes absence.

Every page of these routes states its ``count``, and a walk names each
``packageId`` or ``granuleId`` once, so ``packages`` and ``granules`` refuse a
page without a count and an id that is missing, padded or already served in the
walk (the checks spicy-regs' CFR sections reader made on its own).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import date as Date
from datetime import datetime
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

API = "https://api.govinfo.gov"
MAX_PAGE_SIZE = 1000
PACKAGES_KEY = "packages"
GRANULES_KEY = "granules"
GOVINFO = JsonPageFamily(
    name="govinfo",
    label="GovInfo",
    host="api.govinfo.gov",
    next_path=("nextPage",),
    count_path=("count",),
)
_COLLECTION = re.compile(r"[A-Z][A-Z0-9]{1,15}")
_PACKAGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _date(value: str, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DD")
    try:
        Date.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid calendar date") from error
    return value


def _datetime(value: str, name: str) -> str:
    if not isinstance(value, str) or _DATETIME.fullmatch(value) is None:
        raise PagedJsonSourceError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise PagedJsonSourceError(f"{name} must be a valid UTC datetime") from error
    return value


def _page_size(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise PagedJsonSourceError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
    return str(value)


def _collections(values: Sequence[str]) -> str:
    if isinstance(values, str) or not values or len(set(values)) != len(values):
        raise PagedJsonSourceError("collections must be a nonempty sequence of distinct collection codes")
    for code in values:
        if not isinstance(code, str) or _COLLECTION.fullmatch(code) is None:
            raise PagedJsonSourceError("collection codes are uppercase letters and digits")
    return ",".join(values)


def published_url(
    start_date: str,
    end_date: str | None = None,
    *,
    collections: Sequence[str],
    page_size: int = 100,
    modified_since: str | None = None,
) -> str:
    """Packages issued in a date window for named collections; ``modified_since`` narrows by lastModified."""
    path = f"/published/{_date(start_date, 'start_date')}"
    if end_date is not None:
        end = _date(end_date, "end_date")
        if end < start_date:
            raise PagedJsonSourceError("end_date precedes start_date")
        path += f"/{end}"
    query = [("offsetMark", "*"), ("pageSize", _page_size(page_size)), ("collection", _collections(collections))]
    if modified_since is not None:
        query.append(("modifiedSince", _datetime(modified_since, "modified_since")))
    return f"{API}{path}?{urlencode(query, safe='*')}"


def collection_url(
    collection: str,
    last_modified_start: str,
    last_modified_end: str | None = None,
    *,
    page_size: int = 100,
) -> str:
    """Packages added or updated in one collection since a datetime: the publisher's resume primitive."""
    path = f"/collections/{_collections([collection])}/{_datetime(last_modified_start, 'last_modified_start')}"
    if last_modified_end is not None:
        end = _datetime(last_modified_end, "last_modified_end")
        if end < last_modified_start:
            raise PagedJsonSourceError("last_modified_end precedes last_modified_start")
        path += f"/{end}"
    query = [("offsetMark", "*"), ("pageSize", _page_size(page_size))]
    return f"{API}{path}?{urlencode(query, safe='*')}"


def package_granules_url(package_id: str, *, page_size: int = 100) -> str:
    if not isinstance(package_id, str) or _PACKAGE_ID.fullmatch(package_id) is None:
        raise PagedJsonSourceError("package_id spelling is unsupported")
    query = [("offsetMark", "*"), ("pageSize", _page_size(page_size))]
    return f"{API}/packages/{package_id}/granules?{urlencode(query, safe='*')}"


class GovInfoDiscoveryReader(PagedJsonReader):
    """Published, collection and granule lists; every page is one bounded, evidenced request."""

    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=GOVINFO, budget=budget, api_key=api_key, transport=transport, clock=clock)

    def packages(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk a ``published`` or ``collections`` query; each ``packageId`` once, every page counted."""
        return _identified(self.pages(url, records_key=PACKAGES_KEY, max_pages=max_pages), "packageId")

    def granules(self, url: str, *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        """Walk a package's granules; each ``granuleId`` once, every page counted."""
        return _identified(self.pages(url, records_key=GRANULES_KEY, max_pages=max_pages), "granuleId")


def _identified(pages: Iterable[JsonPage], field: str) -> Iterator[JsonPage]:
    """Refuse, before yielding it, a page without a count or with a missing, padded or repeated ``field``."""
    seen: set[str] = set()
    for page in pages:
        if page.declared_count is None:
            raise PagedJsonSourceError(f"GovInfo {page.records_key} page omitted its count")
        for record in page.records:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise PagedJsonSourceError(f"GovInfo list row requires a nonempty, unpadded {field}")
            if value in seen:
                raise PagedJsonSourceError(f"GovInfo walk repeats {field} {value}")
            seen.add(value)
        yield page
