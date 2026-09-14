"""Congress.gov list routes name explicit queries and walk exact pages to the publisher's end."""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.listing import (
    BILLS_KEY,
    CONGRESS_GOV,
    CRS_REPORTS_KEY,
    MAX_LIMIT,
    CongressListingReader,
    bill_list_url,
    crs_report_list_url,
)
from spicy_docs.sources.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
BILLS = (FIXTURES / "congress-bill-list.json").read_bytes()
CRS = (FIXTURES / "congress-crsreport-list.json").read_bytes()
BUDGET = PagedJsonBudget(3, 65536, 7, 0)
KEY = "k3y-abcdef0123456789"


class Transport(httpx.MockTransport):
    def __init__(self, *bodies):
        self.bodies = iter(bodies)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return httpx.Response(
            200, stream=httpx.ByteStream(next(self.bodies)), headers={"content-type": "application/json"}
        )


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_family_states_the_publisher_contract():
    assert CONGRESS_GOV.host == "api.congress.gov"
    assert CONGRESS_GOV.next_path == ("pagination", "next") and CONGRESS_GOV.count_path == ("pagination", "count")
    assert CONGRESS_GOV.credential_header == "X-Api-Key" and CONGRESS_GOV.requires_credential


def test_list_urls_are_explicit_and_bounded():
    assert bill_list_url(limit=2) == "https://api.congress.gov/v3/bill?format=json&limit=2&sort=updateDate+desc"
    assert bill_list_url(
        congress=119, bill_type="hr", from_datetime="2026-09-01T00:00:00Z", to_datetime="2026-09-14T00:00:00Z"
    ) == (
        "https://api.congress.gov/v3/bill/119/hr?format=json&limit=250&sort=updateDate+desc"
        "&fromDateTime=2026-09-01T00%3A00%3A00Z&toDateTime=2026-09-14T00%3A00%3A00Z"
    )
    assert crs_report_list_url(sort="updateDate asc") == (
        "https://api.congress.gov/v3/crsreport?format=json&limit=250&sort=updateDate+asc"
    )
    assert MAX_LIMIT == 250


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 251},
        {"limit": True},
        {"sort": "title"},
        {"from_datetime": "2026-09-01"},
        {"from_datetime": "2026-13-01T00:00:00Z"},
        {"from_datetime": "2026-09-02T00:00:00Z", "to_datetime": "2026-09-01T00:00:00Z"},
        {"congress": 0},
        {"congress": 1000},
        {"congress": 119, "bill_type": "HR"},
        {"bill_type": "hr"},
    ],
)
def test_invalid_list_selections_refuse(kwargs):
    with pytest.raises(PagedJsonSourceError):
        bill_list_url(**kwargs)


def test_pinned_pages_parse_with_publisher_spellings():
    transport = Transport(BILLS, CRS)
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        bills = source.page(bill_list_url(limit=2), records_key=BILLS_KEY)
        reports = source.page(crs_report_list_url(limit=2), records_key=CRS_REPORTS_KEY)
    assert bills.capture.body == BILLS and len(bills.records) == 2
    assert bills.declared_count == 429950
    # The publisher spells the continuation with a raw space; the reader requests its encoded form.
    assert bills.next_url == "https://api.congress.gov/v3/bill?sort=updateDate+desc&offset=2&limit=2&format=json"
    assert b"sort=updateDate desc" in bills.capture.body
    assert bills.records[0]["congress"] == 119 and bills.records[0]["url"].startswith(
        "https://api.congress.gov/v3/bill/"
    )
    assert reports.declared_count == 14111 and reports.records[0]["id"] == "LSB11481"
    assert all(call.headers["x-api-key"] == KEY and "api_key" not in str(call.url) for call in transport.calls)


def test_walk_follows_publisher_continuations_to_a_consistent_end():
    first = json.loads(BILLS)
    first["pagination"]["count"] = 4
    second = json.loads(BILLS)
    second["pagination"] = {"count": 4}
    transport = Transport(json.dumps(first).encode(), json.dumps(second).encode())
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.bills(bill_list_url(limit=2)))
    assert [len(p.records) for p in pages] == [2, 2] and pages[1].next_url is None
    assert (
        str(transport.calls[1].url)
        == "https://api.congress.gov/v3/bill?sort=updateDate+desc&offset=2&limit=2&format=json"
    )


def test_walk_refuses_when_the_publisher_stops_short_of_its_count():
    only = json.loads(BILLS)
    only["pagination"] = {"count": 3}
    transport = Transport(json.dumps(only).encode())
    with (
        CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source,
        pytest.raises(PagedJsonSourceError, match="declared and observed"),
    ):
        list(source.bills(bill_list_url(limit=2)))
