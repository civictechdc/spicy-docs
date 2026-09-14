"""USAspending recipients: a keyless POST list whose page metadata names the next page.

``/api/v2/recipient/`` takes a JSON body and answers ``results`` with a
``page_metadata`` envelope carrying ``total``, ``hasNext`` and the next page
number. The reader records each request body beside its exact response. The
recipient universe is large (over eighteen million on 2026-09-14); callers
bound a walk with ``max_pages`` and narrow it with ``award_type`` or a keyword.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

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

API = "https://api.usaspending.gov/api/v2"
RECIPIENTS_URL = f"{API}/recipient/"
RESULTS_KEY = "results"
MAX_LIMIT = 100
AWARD_TYPES = ("all", "contracts", "grants", "loans", "direct_payments", "other")
type AwardType = Literal["all", "contracts", "grants", "loans", "direct_payments", "other"]
USASPENDING = JsonPageFamily(
    name="usaspending",
    label="USAspending",
    host="api.usaspending.gov",
    method="POST",
    next_kind="page-number",
    next_path=("page_metadata", "next"),
    count_path=("page_metadata", "total"),
    credential_header=None,
    requires_credential=False,
)


def recipients_request(
    *,
    limit: int = MAX_LIMIT,
    page: int = 1,
    sort: Literal["amount", "name", "duns"] = "amount",
    order: Literal["asc", "desc"] = "desc",
    award_type: AwardType = "all",
    keyword: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """The first request of a recipient list: its URL and JSON body."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise PagedJsonSourceError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise PagedJsonSourceError("page must be a positive integer")
    if sort not in ("amount", "name", "duns") or order not in ("asc", "desc"):
        raise PagedJsonSourceError("sort must be amount, name or duns and order asc or desc")
    if award_type not in AWARD_TYPES:
        raise PagedJsonSourceError(f"award_type must be one of {', '.join(AWARD_TYPES)}")
    body: dict[str, Any] = {"limit": limit, "page": page, "order": order, "sort": sort, "award_type": award_type}
    if keyword is not None:
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 256:
            raise PagedJsonSourceError("keyword must be a nonempty string of at most 256 characters")
        body["keyword"] = keyword
    return RECIPIENTS_URL, body


class UsaspendingRecipientsReader(PagedJsonReader):
    def __init__(
        self,
        *,
        budget: PagedJsonBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(family=USASPENDING, budget=budget, transport=transport, clock=clock)

    def recipients(self, body: Mapping[str, Any], *, max_pages: int = DEFAULT_MAX_PAGES) -> Iterator[JsonPage]:
        return self.pages(RECIPIENTS_URL, records_key=RESULTS_KEY, max_pages=max_pages, body=body)
