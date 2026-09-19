"""Congress.gov list routes name explicit queries and walk exact pages to the publisher's end."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from spicy_docs.reading.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.congress.listing import (
    BILLS_KEY,
    CONGRESS_GOV,
    CRS_REPORTS_KEY,
    LIST_ROUTES,
    MAX_LIMIT,
    CongressListingReader,
    CongressListRoute,
    bill_list_url,
    crs_report_list_url,
    list_route_url,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import read_api_key

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
BILLS = (FIXTURES / "congress-bill-list.json").read_bytes()
CRS = (FIXTURES / "congress-crsreport-list.json").read_bytes()
BUDGET = PagedJsonBudget(3, 65536, 7, 0)
KEY = "k3y-abcdef0123456789"

# One set of path parameters per table-driven route, reused across the URL-builder,
# page-parse and sort-refusal tests below so each route is named once.
ROUTE_PARAMS: dict[str, dict[str, object]] = {
    "amendment": {"congress": 119},
    "committee-bills": {"chamber": "house", "committee_code": "hsju00"},
    "bill-actions": {"congress": 119, "bill_type": "hr", "number": 1},
    "nomination": {"congress": 119},
    "hearing": {"congress": 119},
    "committee-report": {"congress": 119},
    "house-communication": {"congress": 119},
    "house-vote": {"congress": 119, "session": 1},
}
ROUTE_FIXTURE_BYTES: dict[str, bytes] = {
    "amendment": (FIXTURES / "congress-amendment-list.json").read_bytes(),
    "committee-bills": (FIXTURES / "congress-committee-bills-list.json").read_bytes(),
    "bill-actions": (FIXTURES / "congress-bill-actions-list.json").read_bytes(),
    "nomination": (FIXTURES / "congress-nomination-list.json").read_bytes(),
    "hearing": (FIXTURES / "congress-hearing-list.json").read_bytes(),
    "committee-report": (FIXTURES / "congress-committee-report-list.json").read_bytes(),
    "house-communication": (FIXTURES / "congress-house-communication-list.json").read_bytes(),
    "house-vote": (FIXTURES / "congress-house-vote-list.json").read_bytes(),
}
# (declared count, next URL, one distinguishing field on the first record, its value)
ROUTE_PAGE_EXPECTATIONS: dict[str, tuple[int, str, str, object]] = {
    "amendment": (7066, "https://api.congress.gov/v3/amendment/119?offset=3&limit=3&format=json", "type", "SAMDT"),
    "committee-bills": (
        41822,
        "https://api.congress.gov/v3/committee/house/hsju00/bills?offset=3&limit=3&format=json",
        "relationshipType",
        "Referred To",
    ),
    "bill-actions": (
        59,
        "https://api.congress.gov/v3/bill/119/hr/1/actions?offset=3&limit=3&format=json",
        "type",
        "President",
    ),
    "nomination": (
        2208,
        "https://api.congress.gov/v3/nomination/119?offset=3&limit=3&format=json",
        "citation",
        "PN730-20",
    ),
    "hearing": (971, "https://api.congress.gov/v3/hearing/119?offset=3&limit=3&format=json", "jacketNumber", 64431),
    "committee-report": (
        950,
        "https://api.congress.gov/v3/committee-report/119?offset=3&limit=3&format=json",
        "citation",
        "H. Rept. 119-1",
    ),
    "house-communication": (
        4975,
        "https://api.congress.gov/v3/house-communication/119?offset=3&limit=3&format=json",
        "number",
        4752,
    ),
    "house-vote": (
        362,
        "https://api.congress.gov/v3/house-vote/119/1?offset=3&limit=3&format=json",
        "rollCallNumber",
        240,
    ),
}


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
        {"sort": None},
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


# --- table-driven routes (Phase 4) ---------------------------------------------


def test_route_table_states_records_keys_and_measured_sort_support():
    assert {name: route.sort_honored for name, route in LIST_ROUTES.items()} == {
        "bill": True,
        "crsreport": False,
        "amendment": True,
        "committee-bills": False,
        "bill-actions": False,
        "nomination": False,
        "hearing": False,
        "committee-report": True,
        "house-communication": False,
        "house-vote": False,
    }
    # Measured live 2026-09-19 (see the fixtures README): a one-day fromDateTime window cut
    # committee-bills' declared count from 41,822 to 9 (honored) but left bill-actions' declared
    # count at 59 either way (ignored). Every other route keeps the carried-forward default.
    assert {name: route.window_honored for name, route in LIST_ROUTES.items()} == {
        "bill": True,
        "crsreport": True,
        "amendment": True,
        "committee-bills": True,
        "bill-actions": False,
        "nomination": True,
        "hearing": True,
        "committee-report": True,
        "house-communication": True,
        "house-vote": True,
    }
    assert LIST_ROUTES["bill"].records_key == BILLS_KEY
    assert LIST_ROUTES["crsreport"].records_key == CRS_REPORTS_KEY
    assert LIST_ROUTES["amendment"].records_key == "amendments"
    assert LIST_ROUTES["nomination"].records_key == "nominations"
    assert LIST_ROUTES["hearing"].records_key == "hearings"
    assert LIST_ROUTES["committee-report"].records_key == "reports"
    assert LIST_ROUTES["house-communication"].records_key == "houseCommunications"
    assert LIST_ROUTES["bill-actions"].records_key == "actions"
    assert LIST_ROUTES["house-vote"].records_key == "houseRollCallVotes"
    # Confirmed live 2026-09-19: this route alone nests its rows under a wrapper
    # object instead of a top-level array; see tests/fixtures/listings/README.md.
    assert LIST_ROUTES["committee-bills"].records_key == ("committee-bills", "bills")


@pytest.mark.parametrize(
    ("route_name", "expected"),
    [
        ("amendment", "https://api.congress.gov/v3/amendment/119?format=json&limit=3"),
        ("committee-bills", "https://api.congress.gov/v3/committee/house/hsju00/bills?format=json&limit=3"),
        ("bill-actions", "https://api.congress.gov/v3/bill/119/hr/1/actions?format=json&limit=3"),
        ("nomination", "https://api.congress.gov/v3/nomination/119?format=json&limit=3"),
        ("hearing", "https://api.congress.gov/v3/hearing/119?format=json&limit=3"),
        ("committee-report", "https://api.congress.gov/v3/committee-report/119?format=json&limit=3"),
        ("house-communication", "https://api.congress.gov/v3/house-communication/119?format=json&limit=3"),
        ("house-vote", "https://api.congress.gov/v3/house-vote/119/1?format=json&limit=3"),
    ],
)
def test_list_route_url_builds_the_exact_publisher_request(route_name, expected):
    assert list_route_url(LIST_ROUTES[route_name], limit=3, **ROUTE_PARAMS[route_name]) == expected


def test_list_route_url_bare_route_omits_the_congress_segment():
    assert (
        list_route_url(LIST_ROUTES["amendment"], limit=3) == "https://api.congress.gov/v3/amendment?format=json&limit=3"
    )
    assert (
        list_route_url(LIST_ROUTES["nomination"], limit=3)
        == "https://api.congress.gov/v3/nomination?format=json&limit=3"
    )


@pytest.mark.parametrize(
    ("route_name", "kwargs"),
    [
        ("amendment", {"congress": 0}),
        ("amendment", {"congress": 1000}),
        ("amendment", {"chamber": "house"}),
        ("committee-bills", {"committee_code": "hsju00"}),
        ("committee-bills", {"chamber": "house"}),
        ("committee-bills", {"chamber": "upper", "committee_code": "hsju00"}),
        ("committee-bills", {"chamber": "house", "committee_code": "HSJU00"}),
        ("committee-bills", {"chamber": "house", "committee_code": "hsju0"}),
        ("committee-bills", {"chamber": "house", "committee_code": "hsju001"}),
        ("bill-actions", {"congress": 119, "number": 1}),
        ("bill-actions", {"congress": 119, "bill_type": "hr"}),
        ("bill-actions", {"bill_type": "hr", "number": 1}),
        ("bill-actions", {"congress": 119, "bill_type": "HR", "number": 1}),
        ("bill-actions", {"congress": 119, "bill_type": "hr", "number": 0}),
        ("bill-actions", {"congress": 119, "bill_type": "hr", "number": -1}),
        ("bill-actions", {"congress": 119, "bill_type": "hr", "number": True}),
        ("nomination", {"congress": 119, "chamber": "house"}),
        ("hearing", {"congress": 1000}),
        ("house-vote", {"session": 1}),
        ("house-vote", {"congress": 119}),
        ("house-vote", {"congress": 119, "session": 0}),
        ("house-vote", {"congress": 119, "session": 3}),
        ("house-vote", {"congress": 119, "session": "1"}),
        ("house-vote", {"congress": 119, "session": True}),
        ("bill", {"congress": 0}),
        ("bill", {"bill_type": "hr"}),
        ("bill", {"congress": 119, "bill_type": "HR"}),
        ("bill", {"chamber": "house"}),
        ("crsreport", {"congress": 119}),
    ],
)
def test_list_route_url_refuses_invalid_or_missing_path_params(route_name, kwargs):
    with pytest.raises(PagedJsonSourceError):
        list_route_url(LIST_ROUTES[route_name], limit=3, **kwargs)


@pytest.mark.parametrize("route_name", sorted(name for name, route in LIST_ROUTES.items() if not route.sort_honored))
def test_list_route_url_refuses_sort_the_publisher_ignores(route_name):
    with pytest.raises(PagedJsonSourceError, match="ignores sort"):
        list_route_url(LIST_ROUTES[route_name], sort="updateDate desc", **ROUTE_PARAMS.get(route_name, {}))


@pytest.mark.parametrize("route_name", sorted(name for name, route in LIST_ROUTES.items() if route.sort_honored))
def test_list_route_url_accepts_sort_the_publisher_honors(route_name):
    url = list_route_url(LIST_ROUTES[route_name], sort="updateDate asc", limit=3, **ROUTE_PARAMS.get(route_name, {}))
    assert "sort=updateDate+asc" in url


def test_bill_route_matches_its_named_builder():
    """`bill_list_url` is a thin, contract-preserving alias over the same table-driven path builder."""
    assert list_route_url(
        LIST_ROUTES["bill"], congress=119, bill_type="hr", limit=250, sort="updateDate desc"
    ) == bill_list_url(congress=119, bill_type="hr")
    assert bill_list_url(limit=2) == list_route_url(LIST_ROUTES["bill"], limit=2) + "&sort=updateDate+desc"


def test_crsreport_route_matches_its_named_builder_apart_from_the_legacy_sort():
    """`crs_report_list_url` predates the sort measurement and still sends `sort` unconditionally;
    `list_route_url` on the same table entry is the gated, measurement-honest equivalent."""
    assert (
        crs_report_list_url(limit=250) == list_route_url(LIST_ROUTES["crsreport"], limit=250) + "&sort=updateDate+desc"
    )


def test_list_route_url_refuses_sort_on_crsreport_but_the_legacy_builder_still_sends_it():
    with pytest.raises(PagedJsonSourceError, match="ignores sort"):
        list_route_url(LIST_ROUTES["crsreport"], sort="updateDate desc")
    assert "sort=updateDate+desc" in crs_report_list_url(sort="updateDate desc")


@pytest.mark.parametrize("builder", [bill_list_url, crs_report_list_url])
def test_legacy_builders_still_refuse_a_literal_sort_none(builder):
    """`_query` now accepts an optional sort for `list_route_url`, but the two legacy, named
    builders never accepted a missing one; a literal `sort=None` must still refuse."""
    with pytest.raises(PagedJsonSourceError, match="sort must be"):
        builder(sort=None)


def test_list_route_url_refuses_a_date_window_the_publisher_ignores():
    with pytest.raises(PagedJsonSourceError, match="ignores the date window"):
        list_route_url(
            LIST_ROUTES["bill-actions"], from_datetime="2026-09-18T00:00:00Z", **ROUTE_PARAMS["bill-actions"]
        )
    with pytest.raises(PagedJsonSourceError, match="ignores the date window"):
        list_route_url(LIST_ROUTES["bill-actions"], to_datetime="2026-09-18T00:00:00Z", **ROUTE_PARAMS["bill-actions"])


def test_list_route_url_accepts_a_date_window_the_publisher_honors():
    url = list_route_url(
        LIST_ROUTES["committee-bills"], from_datetime="2026-09-18T00:00:00Z", **ROUTE_PARAMS["committee-bills"]
    )
    assert "fromDateTime=2026-09-18T00%3A00%3A00Z" in url


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "x", "path": "x/{congress}/{type}", "records_key": "rows", "optional_params": frozenset({"congress"})},
        {"name": "x", "path": "", "records_key": "rows"},
        {"name": "", "path": "x", "records_key": "rows"},
        {"name": "x", "path": "x", "records_key": ""},
        {"name": "x", "path": "x", "records_key": ()},
        {"name": "x", "path": "x/{congress}", "records_key": "rows", "optional_params": frozenset({"chamber"})},
    ],
)
def test_congress_list_route_refuses_invalid_construction(kwargs):
    """A route whose ``optional_params`` makes an interior parameter optional while a later one stays
    required (``congress`` optional but ``type`` is not), an empty path, an empty name or an empty
    records key all refuse at construction, the same as an ``optional_params`` entry the path never
    declares as a parameter at all."""
    with pytest.raises(ValueError):
        CongressListRoute(**kwargs)


@pytest.mark.parametrize("route_name", sorted(ROUTE_PAGE_EXPECTATIONS))
def test_table_driven_pages_parse_with_publisher_spellings(route_name):
    route = LIST_ROUTES[route_name]
    count, next_url, field, value = ROUTE_PAGE_EXPECTATIONS[route_name]
    transport = Transport(ROUTE_FIXTURE_BYTES[route_name])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS[route_name])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key)
    assert page.records_key == route.records_key
    assert page.declared_count == count
    assert page.next_url == next_url
    assert len(page.records) == 3
    assert page.records[0][field] == value
    assert transport.calls[0].headers["x-api-key"] == KEY and "api_key" not in str(transport.calls[0].url)


def test_records_method_walks_a_table_driven_route():
    route = LIST_ROUTES["nomination"]
    transport = Transport(ROUTE_FIXTURE_BYTES["nomination"])
    url = list_route_url(route, congress=119, limit=3)
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = next(source.records(route, url, max_pages=1))
    assert page.records_key == "nominations" and page.declared_count == 2208 and len(page.records) == 3


# --- live pagination contract (one request per route, not run by default) ------

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
LIVE_BUDGET = PagedJsonBudget(2, 4 * 1024 * 1024, 30, 0.5)


@pytest.mark.integration
@pytest.mark.parametrize("route_name", sorted(ROUTE_PARAMS))
def test_table_driven_route_walks_one_live_page(route_name):
    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    key = read_api_key(ENV_FILE, "API_GOV")
    route = LIST_ROUTES[route_name]
    url = list_route_url(route, limit=3, **ROUTE_PARAMS[route_name])
    with CongressListingReader(budget=LIVE_BUDGET, api_key=key) as reader:
        page = next(reader.records(route, url, max_pages=1))
    assert page.declared_count is not None
    assert page.next_url is None or urlsplit(page.next_url).hostname == "api.congress.gov"
    assert len(page.records) >= 1
