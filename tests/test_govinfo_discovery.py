"""GovInfo discovery routes name explicit windows and read empty pages as observations."""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.govinfo.discovery import (
    GOVINFO,
    GRANULES_KEY,
    PACKAGES_KEY,
    GovInfoDiscoveryReader,
    collection_url,
    package_granules_url,
    published_url,
)
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
PUBLISHED = (FIXTURES / "govinfo-published-cfr.json").read_bytes()
GRANULES = (FIXTURES / "govinfo-package-granules.json").read_bytes()
BUDGET = PagedJsonBudget(3, 65536, 7, 0)
KEY = "k3y-abcdef0123456789"


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

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
    """Remove retry backoff waits."""
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_family_and_locators_follow_the_publisher_readme():
    """The family and locators follow the publisher README's paths and query spellings."""
    assert GOVINFO.host == "api.govinfo.gov" and GOVINFO.next_path == ("nextPage",) and GOVINFO.count_path == ("count",)
    assert published_url("2025-01-01", "2025-01-31", collections=["CFR"], page_size=2) == (
        "https://api.govinfo.gov/published/2025-01-01/2025-01-31?offsetMark=*&pageSize=2&collection=CFR"
    )
    assert published_url("2019-01-01", collections=["CFR", "FR"], modified_since="2020-01-01T00:00:00Z") == (
        "https://api.govinfo.gov/published/2019-01-01?offsetMark=*&pageSize=100&collection=CFR%2CFR"
        "&modifiedSince=2020-01-01T00%3A00%3A00Z"
    )
    assert collection_url("BILLS", "2025-07-03T00:00:00Z", "2025-12-10T23:59:59Z", page_size=150) == (
        "https://api.govinfo.gov/collections/BILLS/2025-07-03T00:00:00Z/2025-12-10T23:59:59Z?offsetMark=*&pageSize=150"
    )
    assert package_granules_url("CFR-2025-title1-vol1", page_size=2) == (
        "https://api.govinfo.gov/packages/CFR-2025-title1-vol1/granules?offsetMark=*&pageSize=2"
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: published_url("2025-1-1", collections=["CFR"]),
        lambda: published_url("2025-02-30", collections=["CFR"]),
        lambda: published_url("2025-02-01", "2025-01-01", collections=["CFR"]),
        lambda: published_url("2025-01-01", collections=[]),
        lambda: published_url("2025-01-01", collections="CFR"),
        lambda: published_url("2025-01-01", collections=["cfr"]),
        lambda: published_url("2025-01-01", collections=["CFR", "CFR"]),
        lambda: published_url("2025-01-01", collections=["CFR"], page_size=1001),
        lambda: published_url("2025-01-01", collections=["CFR"], modified_since="2020-01-01"),
        lambda: collection_url("BILLS", "2025-01-01"),
        lambda: collection_url("BILLS", "2025-02-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        lambda: package_granules_url("CFR 2025"),
        lambda: package_granules_url(""),
    ],
)
def test_invalid_selections_refuse(call):
    """Invalid selections are refused."""
    with pytest.raises(PagedJsonSourceError):
        call()


def test_pinned_pages_parse_and_continue_by_offset_mark():
    """Pinned pages parse and continue by offset mark, with the key in headers only."""
    transport = Transport(PUBLISHED, GRANULES)
    with GovInfoDiscoveryReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        packages = source.page(
            published_url("2025-01-01", "2025-01-31", collections=["CFR"], page_size=2), records_key=PACKAGES_KEY
        )
        granules = source.page(package_granules_url("CFR-2025-title1-vol1", page_size=2), records_key=GRANULES_KEY)
    assert packages.declared_count == 54 and len(packages.records) == 2
    assert "offsetMark=AoJwot" in packages.next_url
    assert packages.records[0]["packageId"].startswith("CFR-2025-title")
    assert packages.records[0]["congress"] is None
    assert granules.declared_count == 400 and granules.records[0]["granuleId"].startswith("CFR-2025-title1-vol1")
    assert all(call.headers["x-api-key"] == KEY for call in transport.calls)


def test_walk_ends_only_when_counts_agree_and_zero_count_is_an_observation():
    """The walk ends only when counts agree, and a zero count is an observation."""
    first = json.loads(PUBLISHED)
    first["count"] = 4
    second = json.loads(PUBLISHED)
    second["count"] = 4
    second["nextPage"] = None
    transport = Transport(json.dumps(first).encode(), json.dumps(second).encode())
    with GovInfoDiscoveryReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.packages(published_url("2025-01-01", "2025-01-31", collections=["CFR"], page_size=2)))
    assert [len(p.records) for p in pages] == [2, 2]
    empty = {"count": 0, "message": None, "nextPage": None, "previousPage": None, "packages": []}
    with GovInfoDiscoveryReader(budget=BUDGET, api_key=KEY, transport=Transport(json.dumps(empty).encode())) as source:
        pages = list(source.packages(published_url("1900-01-01", collections=["CFR"])))
    assert pages[0].declared_count == 0 and pages[0].records == ()
