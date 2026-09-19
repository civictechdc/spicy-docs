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
    # A5, A6, A7, A10
    "committee-meeting": {"congress": 119, "chamber": "house"},
    "committee-meeting-detail": {"congress": 119, "chamber": "house", "event_id": 119565},
    "treaty": {"congress": 119},
    "treaty-detail": {"congress": 119, "number": 2},
    "daily-congressional-record": {},
    "daily-congressional-record-detail": {"volume": 172, "issue": 148},
    "house-communication-detail": {"congress": 119, "communication_type": "ec", "number": 4752},
    "senate-communication": {"congress": 119},
    "senate-communication-detail": {"congress": 119, "communication_type": "ec", "number": 4712},
    "house-requirement": {},
    "house-requirement-detail": {"number": 8070},
    "house-requirement-communications": {"number": 8070},
    # A8, A9, A10: laws, committees, members, prints.
    "law": {"congress": 119},
    "law-detail": {"congress": 119, "law_type": "pub", "number": 21},
    "committee": {"congress": 119},
    "committee-detail": {"chamber": "house", "system_code": "hsju00"},
    "member": {},
    "member-congress": {"congress": 119},
    "member-detail": {"bioguide_id": "W000832"},
    "committee-print": {"congress": 119},
    "committee-print-detail": {"congress": 119, "chamber": "house", "number": 63747},
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
    "committee-meeting": (FIXTURES / "congress-committee-meeting-list.json").read_bytes(),
    "daily-congressional-record": (FIXTURES / "congress-daily-congressional-record-list.json").read_bytes(),
    "senate-communication": (FIXTURES / "congress-senate-communication-list.json").read_bytes(),
    "house-requirement": (FIXTURES / "congress-house-requirement-list.json").read_bytes(),
    "house-requirement-communications": (FIXTURES / "congress-house-requirement-communications.json").read_bytes(),
    # The five A8/A9/A10 list routes; the four detail routes answer one record, not three,
    # and get their own fixtures and tests below rather than this shared 3-record table.
    "law": (FIXTURES / "congress-law-list.json").read_bytes(),
    "committee": (FIXTURES / "congress-committee-list.json").read_bytes(),
    "member": (FIXTURES / "congress-member-list.json").read_bytes(),
    "member-congress": (FIXTURES / "congress-member-congress-list.json").read_bytes(),
    "committee-print": (FIXTURES / "congress-committee-print-list.json").read_bytes(),
}
# Every detail route's fixture: one JSON object identified by its full path, not a paginated
# list. law-detail, committee-detail, member-detail and this branch's six A5/A6/A7/A10 detail
# routes all nest a single, non-empty object under their records key and need
# CongressListRoute.single_record=True to read it (reading/paged_json.py's _read_page); treaty-
# detail and committee-print-detail nest a one-element array instead, which the reader's
# ordinary list path already reads, so both keep single_record's False default.
DETAIL_FIXTURE_BYTES: dict[str, bytes] = {
    "law-detail": (FIXTURES / "congress-law-detail.json").read_bytes(),
    "committee-detail": (FIXTURES / "congress-committee-detail.json").read_bytes(),
    "member-detail": (FIXTURES / "congress-member-detail.json").read_bytes(),
    "committee-print-detail": (FIXTURES / "congress-committee-print-detail.json").read_bytes(),
    "committee-meeting-detail": (FIXTURES / "congress-committee-meeting-detail.json").read_bytes(),
    "treaty-detail": (FIXTURES / "congress-treaty-detail.json").read_bytes(),
    "daily-congressional-record-detail": (FIXTURES / "congress-daily-congressional-record-detail.json").read_bytes(),
    "house-communication-detail": (FIXTURES / "congress-house-communication-detail.json").read_bytes(),
    "senate-communication-detail": (FIXTURES / "congress-senate-communication-detail.json").read_bytes(),
    "house-requirement-detail": (FIXTURES / "congress-house-requirement-detail.json").read_bytes(),
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
    "committee-meeting": (
        1611,
        "https://api.congress.gov/v3/committee-meeting/119/house?offset=3&limit=3&format=json",
        "eventId",
        "119569",
    ),
    "daily-congressional-record": (
        5869,
        "https://api.congress.gov/v3/daily-congressional-record?offset=3&limit=3&format=json",
        "issueNumber",
        "148",
    ),
    "senate-communication": (
        4842,
        "https://api.congress.gov/v3/senate-communication/119?offset=3&limit=3&format=json",
        "number",
        4712,
    ),
    "house-requirement": (
        3226,
        "https://api.congress.gov/v3/house-requirement?offset=3&limit=3&format=json",
        "number",
        12478,
    ),
    "house-requirement-communications": (
        92450,
        "https://api.congress.gov/v3/house-requirement/8070/matching-communications?offset=3&limit=3&format=json",
        "number",
        2,
    ),
    "law": (108, "https://api.congress.gov/v3/law/119?offset=3&limit=3&format=json", "number", "307"),
    "committee": (
        238,
        "https://api.congress.gov/v3/committee/119?offset=3&limit=3&format=json",
        "systemCode",
        "hsbu00",
    ),
    "member": (2696, "https://api.congress.gov/v3/member?offset=3&limit=3&format=json", "bioguideId", "W000832"),
    "member-congress": (
        555,
        "https://api.congress.gov/v3/member/congress/119?offset=3&limit=3&format=json",
        "bioguideId",
        "W000832",
    ),
    "committee-print": (
        79,
        "https://api.congress.gov/v3/committee-print/119?offset=3&limit=3&format=json",
        "jacketNumber",
        63747,
    ),
}
# treaty answers only 2 rows for the 119th Congress (declared count 2 < limit 3), so it cannot
# share the fixed "3 records" assumption in test_table_driven_pages_parse_with_publisher_spellings
# above; see test_treaty_list_page_parses_with_its_own_short_count below instead.
TREATY_FIXTURE_BYTES = (FIXTURES / "congress-treaty-list.json").read_bytes()
# (a field on the one record, its value) -- spot-checks the field survives the generic reader
# unchanged, for this branch's six A5/A6/A7/A10 detail routes specifically (a subset of
# DETAIL_FIXTURE_BYTES above; the other four detail routes get their own dedicated tests below).
DETAIL_ROUTE_EXPECTATIONS: dict[str, tuple[str, object]] = {
    "committee-meeting-detail": ("title", "Various Measures"),
    "treaty-detail": ("topic", "Taxation"),
    "daily-congressional-record-detail": ("issueNumber", "148"),
    "house-communication-detail": ("isRulemaking", "True"),
    "senate-communication-detail": ("congressionalRecordDate", "2026-09-17"),
    "house-requirement-detail": ("nature", "Congressional review of agency rulemaking."),
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
        # Measured live 2026-09-19 (see the fixtures README): each list route below was probed
        # directly (limit=3, sort=updateDate desc vs asc) and every one ignores sort; the six
        # detail routes answer one record, not a list, so sort does not apply and is False by
        # construction, not by probe.
        "committee-meeting": False,
        "committee-meeting-detail": False,
        "treaty": False,
        "treaty-detail": False,
        "daily-congressional-record": False,
        "daily-congressional-record-detail": False,
        "house-communication-detail": False,
        "senate-communication": False,
        "senate-communication-detail": False,
        "house-requirement": False,
        "house-requirement-detail": False,
        "house-requirement-communications": False,
        # A8/A9/A10: law, member, member-congress and committee-print carry Table A's "sort
        # ignored" finding (the exact route Table A measured); committee carries Table A's
        # "committee" entry, also named in the module docstring's reorder list. member-congress
        # is a different URL than Table A's bare member row, so it got its own direct probe
        # (member/congress/119?limit=1, sort=updateDate desc vs asc; see the fixtures README).
        # The four detail routes have no list to reorder.
        "law": False,
        "law-detail": False,
        "committee": True,
        "committee-detail": False,
        "member": False,
        "member-congress": False,
        "member-detail": False,
        "committee-print": False,
        "committee-print-detail": False,
    }
    # Measured live 2026-09-19 (see the fixtures README): a one-day fromDateTime window cut
    # committee-bills' declared count from 41,822 to 9 (honored) but left bill-actions' declared
    # count at 59 either way (ignored). Every other list route keeps the carried-forward default;
    # the four A8/A9/A10 detail routes answer one record, so there is no list to window and
    # window_honored=False there is structural, not a measurement (see the class docstring).
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
        # Measured live 2026-09-19 (see the fixtures README): a one-day fromDateTime window cut
        # committee-meeting's declared count from 1,611 to 8 and treaty's from 786 to 0 (both
        # honored), but left daily-congressional-record's declared count at 5,869 and
        # senate-communication's at 4,842 unchanged either way (both ignored).
        # house-requirement/house-requirement-communications keep the carried-forward default,
        # not measured this round. Every detail route is False by construction: one record has
        # no window to narrow.
        "committee-meeting": True,
        "committee-meeting-detail": False,
        "treaty": True,
        "treaty-detail": False,
        "daily-congressional-record": False,
        "daily-congressional-record-detail": False,
        "house-communication-detail": False,
        "senate-communication": False,
        "senate-communication-detail": False,
        "house-requirement": True,
        "house-requirement-detail": False,
        "house-requirement-communications": True,
        "law": True,
        "law-detail": False,
        "committee": True,
        "committee-detail": False,
        "member": True,
        "member-congress": True,
        "member-detail": False,
        "committee-print": True,
        "committee-print-detail": False,
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
    # A5, A6, A7, A10: records keys as Congress.gov spells them (fixtures README).
    assert LIST_ROUTES["committee-meeting"].records_key == "committeeMeetings"
    assert LIST_ROUTES["committee-meeting-detail"].records_key == "committeeMeeting"
    assert LIST_ROUTES["treaty"].records_key == "treaties"
    assert LIST_ROUTES["treaty-detail"].records_key == "treaty"
    assert LIST_ROUTES["daily-congressional-record"].records_key == "dailyCongressionalRecord"
    assert LIST_ROUTES["daily-congressional-record-detail"].records_key == "issue"
    assert LIST_ROUTES["house-communication-detail"].records_key == "houseCommunication"
    assert LIST_ROUTES["senate-communication"].records_key == "senateCommunications"
    assert LIST_ROUTES["senate-communication-detail"].records_key == "senateCommunication"
    assert LIST_ROUTES["house-requirement"].records_key == "houseRequirements"
    assert LIST_ROUTES["house-requirement-detail"].records_key == "houseRequirement"
    assert LIST_ROUTES["house-requirement-communications"].records_key == "matchingCommunications"
    # A8/A9/A10: the publisher's own spellings, confirmed live 2026-09-19 -- "law" reuses
    # BILLS_KEY, since the publisher spells law and bill rows the same "bills" key.
    assert LIST_ROUTES["law"].records_key == BILLS_KEY
    assert LIST_ROUTES["law-detail"].records_key == "bill"
    assert LIST_ROUTES["committee"].records_key == "committees"
    assert LIST_ROUTES["committee-detail"].records_key == "committee"
    assert LIST_ROUTES["member"].records_key == "members"
    assert LIST_ROUTES["member-congress"].records_key == "members"
    assert LIST_ROUTES["member-detail"].records_key == "member"
    assert LIST_ROUTES["committee-print"].records_key == "committeePrints"
    assert LIST_ROUTES["committee-print-detail"].records_key == "committeePrint"


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
        # A5, A6, A7, A10
        ("committee-meeting", "https://api.congress.gov/v3/committee-meeting/119/house?format=json&limit=3"),
        (
            "committee-meeting-detail",
            "https://api.congress.gov/v3/committee-meeting/119/house/119565?format=json&limit=3",
        ),
        ("treaty", "https://api.congress.gov/v3/treaty/119?format=json&limit=3"),
        ("treaty-detail", "https://api.congress.gov/v3/treaty/119/2?format=json&limit=3"),
        ("daily-congressional-record", "https://api.congress.gov/v3/daily-congressional-record?format=json&limit=3"),
        (
            "daily-congressional-record-detail",
            "https://api.congress.gov/v3/daily-congressional-record/172/148?format=json&limit=3",
        ),
        (
            "house-communication-detail",
            "https://api.congress.gov/v3/house-communication/119/ec/4752?format=json&limit=3",
        ),
        ("senate-communication", "https://api.congress.gov/v3/senate-communication/119?format=json&limit=3"),
        (
            "senate-communication-detail",
            "https://api.congress.gov/v3/senate-communication/119/ec/4712?format=json&limit=3",
        ),
        ("house-requirement", "https://api.congress.gov/v3/house-requirement?format=json&limit=3"),
        ("house-requirement-detail", "https://api.congress.gov/v3/house-requirement/8070?format=json&limit=3"),
        (
            "house-requirement-communications",
            "https://api.congress.gov/v3/house-requirement/8070/matching-communications?format=json&limit=3",
        ),
        # A8, A9, A10
        ("law", "https://api.congress.gov/v3/law/119?format=json&limit=3"),
        ("law-detail", "https://api.congress.gov/v3/law/119/pub/21?format=json&limit=3"),
        ("committee", "https://api.congress.gov/v3/committee/119?format=json&limit=3"),
        ("committee-detail", "https://api.congress.gov/v3/committee/house/hsju00?format=json&limit=3"),
        ("member", "https://api.congress.gov/v3/member?format=json&limit=3"),
        ("member-congress", "https://api.congress.gov/v3/member/congress/119?format=json&limit=3"),
        ("member-detail", "https://api.congress.gov/v3/member/W000832?format=json&limit=3"),
        ("committee-print", "https://api.congress.gov/v3/committee-print/119?format=json&limit=3"),
        (
            "committee-print-detail",
            "https://api.congress.gov/v3/committee-print/119/house/63747?format=json&limit=3",
        ),
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
    assert (
        list_route_url(LIST_ROUTES["committee"], limit=3) == "https://api.congress.gov/v3/committee?format=json&limit=3"
    )
    assert (
        list_route_url(LIST_ROUTES["law"], congress=119, limit=3)
        == "https://api.congress.gov/v3/law/119?format=json&limit=3"
    )
    # "member" has no path parameter at all, unlike the trailing-optional routes above.
    assert list_route_url(LIST_ROUTES["member"], limit=3) == "https://api.congress.gov/v3/member?format=json&limit=3"


def test_new_list_routes_omit_their_optional_trailing_segments():
    """A5, A6, A7, A10: committee-meeting, treaty and senate-communication all support a bare
    request the same way amendment/nomination do; committee-meeting also supports congress alone,
    omitting only its trailing chamber."""
    assert (
        list_route_url(LIST_ROUTES["committee-meeting"], limit=3)
        == "https://api.congress.gov/v3/committee-meeting?format=json&limit=3"
    )
    assert (
        list_route_url(LIST_ROUTES["committee-meeting"], congress=119, limit=3)
        == "https://api.congress.gov/v3/committee-meeting/119?format=json&limit=3"
    )
    assert list_route_url(LIST_ROUTES["treaty"], limit=3) == "https://api.congress.gov/v3/treaty?format=json&limit=3"
    assert (
        list_route_url(LIST_ROUTES["senate-communication"], limit=3)
        == "https://api.congress.gov/v3/senate-communication?format=json&limit=3"
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
        # A5, A6, A7, A10
        ("committee-meeting", {"chamber": "house"}),
        ("committee-meeting-detail", {"congress": 119, "chamber": "house"}),
        ("committee-meeting-detail", {"chamber": "house", "event_id": 119565}),
        ("committee-meeting-detail", {"congress": 119, "chamber": "upper", "event_id": 119565}),
        ("committee-meeting-detail", {"congress": 119, "chamber": "house", "event_id": 0}),
        ("committee-meeting-detail", {"congress": 119, "chamber": "house", "event_id": True}),
        ("treaty-detail", {"congress": 119}),
        ("treaty-detail", {"number": 2}),
        ("treaty-detail", {"congress": 0, "number": 2}),
        ("treaty-detail", {"congress": 119, "number": 0}),
        ("daily-congressional-record", {"issue": 148}),
        ("daily-congressional-record-detail", {"volume": 172}),
        ("daily-congressional-record-detail", {"issue": 148}),
        ("daily-congressional-record-detail", {"volume": 0, "issue": 148}),
        ("daily-congressional-record-detail", {"volume": 172, "issue": 0}),
        ("house-communication-detail", {"congress": 119, "number": 4752}),
        ("house-communication-detail", {"congress": 119, "communication_type": "ec"}),
        ("house-communication-detail", {"congress": 119, "communication_type": "EC", "number": 4752}),
        ("house-communication-detail", {"congress": 119, "communication_type": "e", "number": 4752}),
        ("house-communication-detail", {"congress": 119, "communication_type": "1c", "number": 4752}),
        ("senate-communication-detail", {"congress": 119, "communication_type": "ec"}),
        ("senate-communication-detail", {"congress": 119, "number": 4712}),
        ("senate-communication-detail", {"communication_type": "ec", "number": 4712}),
        ("house-requirement", {"number": 8070}),
        ("house-requirement-detail", {}),
        ("house-requirement-detail", {"number": 0}),
        ("house-requirement-detail", {"number": True}),
        ("house-requirement-communications", {}),
        ("house-requirement-communications", {"number": -1}),
        # A8, A9, A10
        ("law", {"congress": 0}),
        ("law", {"congress": 119, "law_type": "public"}),
        ("law", {"law_type": "pub"}),
        ("law-detail", {"congress": 119, "law_type": "pub"}),
        ("law-detail", {"congress": 119, "number": 21}),
        ("law-detail", {"law_type": "pub", "number": 21}),
        ("law-detail", {"congress": 119, "law_type": "public", "number": 21}),
        ("law-detail", {"congress": 119, "law_type": "pub", "number": 0}),
        ("committee", {"congress": 1000}),
        ("committee", {"chamber": "house"}),
        ("committee-detail", {"chamber": "house"}),
        ("committee-detail", {"system_code": "hsju00"}),
        ("committee-detail", {"chamber": "upper", "system_code": "hsju00"}),
        ("committee-detail", {"chamber": "house", "system_code": "HSJU00"}),
        ("committee-detail", {"chamber": "house", "system_code": "hsju0"}),
        ("member", {"congress": 119}),
        ("member-congress", {}),
        ("member-congress", {"congress": 0}),
        ("member-detail", {"bioguide_id": "w000832"}),
        ("member-detail", {"bioguide_id": "W00083"}),
        ("member-detail", {"bioguide_id": "W0008322"}),
        ("member-detail", {"bioguide_id": "0000832"}),
        ("committee-print", {"congress": 0}),
        ("committee-print-detail", {"congress": 119, "chamber": "house"}),
        ("committee-print-detail", {"congress": 119, "number": 63747}),
        ("committee-print-detail", {"chamber": "house", "number": 63747}),
        ("committee-print-detail", {"congress": 119, "chamber": "upper", "number": 63747}),
        ("committee-print-detail", {"congress": 119, "chamber": "house", "number": 0}),
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


@pytest.mark.parametrize("route_name", sorted(name for name, route in LIST_ROUTES.items() if not route.window_honored))
def test_list_route_url_refuses_a_date_window_the_publisher_ignores_table_driven(route_name):
    """Table-driven over every route, not only bill-actions: the window check fires before path
    assembly, so this exercises every ``window_honored=False`` route in ``LIST_ROUTES`` --
    including the ten A5/A6/A7/A8/A9/A10 detail routes, where a window is not applicable by
    construction, and daily-congressional-record/senate-communication, measured ignored."""
    with pytest.raises(PagedJsonSourceError, match="ignores the date window"):
        list_route_url(
            LIST_ROUTES[route_name], from_datetime="2026-09-18T00:00:00Z", **ROUTE_PARAMS.get(route_name, {})
        )


@pytest.mark.parametrize("route_name", sorted(name for name, route in LIST_ROUTES.items() if route.window_honored))
def test_list_route_url_accepts_a_date_window_the_publisher_honors_table_driven(route_name):
    url = list_route_url(
        LIST_ROUTES[route_name], from_datetime="2026-09-18T00:00:00Z", limit=3, **ROUTE_PARAMS.get(route_name, {})
    )
    assert "fromDateTime=2026-09-18T00%3A00%3A00Z" in url


@pytest.mark.parametrize("route_name", sorted(DETAIL_FIXTURE_BYTES))
def test_list_route_url_refuses_a_date_window_on_every_detail_route(route_name):
    """A detail route answers one record; there is no list to window, so a window refuses
    the same way bill-actions' does, on structural grounds rather than a live probe."""
    with pytest.raises(PagedJsonSourceError, match="ignores the date window"):
        list_route_url(LIST_ROUTES[route_name], from_datetime="2026-09-18T00:00:00Z", **ROUTE_PARAMS[route_name])


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


def test_treaty_list_page_parses_with_its_own_short_count():
    """A10: the 119th Congress answers only 2 treaties for a limit=3 request -- fewer rows than
    the limit, and no publisher ``next`` -- so it cannot share the fixed "3 records" assumption
    every other table-driven fixture above uses."""
    route = LIST_ROUTES["treaty"]
    transport = Transport(TREATY_FIXTURE_BYTES)
    url = list_route_url(route, limit=3, congress=119)
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key)
    assert page.records_key == "treaties"
    assert page.declared_count == 2
    assert page.next_url is None
    assert len(page.records) == 2
    assert page.records[0]["number"] == 2 and page.records[0]["topic"] == "Taxation"
    assert transport.calls[0].headers["x-api-key"] == KEY and "api_key" not in str(transport.calls[0].url)


@pytest.mark.parametrize("route_name", sorted(DETAIL_ROUTE_EXPECTATIONS))
def test_detail_routes_parse_one_record_with_no_pagination(route_name):
    """A5, A6, A7, A10: a detail route answers one record identified by its full path, not a
    list -- house-communication, daily-congressional-record, senate-communication and
    house-requirement nest a single object under their key; treaty nests a one-element array
    instead. Both shapes read as a single-record page with no declared count and no
    continuation (reading/paged_json.py's Mapping-wrapping in ``_read_page``, opted into via
    ``route.single_record``), and every field the fixture carries is reachable unchanged through
    the same ``records()``/``page()`` walk a list route uses."""
    route = LIST_ROUTES[route_name]
    field, value = DETAIL_ROUTE_EXPECTATIONS[route_name]
    transport = Transport(DETAIL_FIXTURE_BYTES[route_name])
    url = list_route_url(route, **ROUTE_PARAMS[route_name])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    assert page.records_key == route.records_key
    assert page.declared_count is None
    assert page.next_url is None
    assert len(page.records) == 1
    assert page.records[0][field] == value
    assert transport.calls[0].headers["x-api-key"] == KEY and "api_key" not in str(transport.calls[0].url)


def test_committee_meeting_detail_carries_related_bills_and_documents_unshaped():
    """A7: relatedItems.bills, meetingDocuments and the other nested arrays the map's
    meeting->bill and meeting->documents edges rely on all survive through the generic reader,
    not just the scalar fields spot-checked above."""
    route = LIST_ROUTES["committee-meeting-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["committee-meeting-detail"])
    url = list_route_url(route, **ROUTE_PARAMS["committee-meeting-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    (record,) = page.records
    bills = record["relatedItems"]["bills"]
    assert {"congress": 119, "number": "1653", "type": "HR"}.items() <= bills[0].items()
    assert record["meetingDocuments"] and record["committees"][0]["systemCode"] == "hsba00"


def test_house_communication_detail_carries_the_regulatory_bridge_fields_unshaped():
    """A5: isRulemaking, reportNature (which carries the RIN), the committee referral's
    systemCode and matchingRequirements[].number -- the fields the regulatory-bridge gap names --
    all reach the caller exactly as the publisher spelled them."""
    route = LIST_ROUTES["house-communication-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["house-communication-detail"])
    url = list_route_url(route, **ROUTE_PARAMS["house-communication-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    (record,) = page.records
    assert record["isRulemaking"] == "True"
    assert "RIN: 3133-AF97" in record["reportNature"]
    assert record["committees"][0]["systemCode"] == "hsba00"
    assert record["matchingRequirements"][0]["number"] == 8070


def test_daily_congressional_record_detail_carries_full_issue_sections_unshaped():
    """A10: fullIssue.sections, the legislative-day calendar the map's record->legislative-day
    edge reads, reaches the caller unshaped."""
    route = LIST_ROUTES["daily-congressional-record-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["daily-congressional-record-detail"])
    url = list_route_url(route, **ROUTE_PARAMS["daily-congressional-record-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    (record,) = page.records
    sections = record["fullIssue"]["sections"]
    assert {section["name"] for section in sections} == {"Daily Digest", "Senate Section"}


def test_house_requirement_detail_carries_the_matching_communications_pointer_unshaped():
    """A6: matchingCommunications.count and .url on the detail record, and the requirement number
    on each row the sibling matching-communications list answers."""
    detail_route = LIST_ROUTES["house-requirement-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["house-requirement-detail"])
    url = list_route_url(detail_route, **ROUTE_PARAMS["house-requirement-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=detail_route.records_key, single_record=detail_route.single_record)
    (record,) = page.records
    assert record["matchingCommunications"]["count"] == 92450
    assert record["matchingCommunications"]["url"].endswith(
        "/house-requirement/8070/matching-communications?format=json"
    )

    communications_route = LIST_ROUTES["house-requirement-communications"]
    transport = Transport(ROUTE_FIXTURE_BYTES["house-requirement-communications"])
    url = list_route_url(communications_route, limit=3, **ROUTE_PARAMS["house-requirement-communications"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=communications_route.records_key)
    assert page.records[0]["communicationType"]["code"] == "EC"


# --- A8/A9/A10 detail routes: one record, not a list ----------------------------
#
# law-detail, committee-detail and member-detail answer their records_key as a single
# JSON object ({"bill": {...}}, {"committee": {...}}, {"member": {...}}), not an array;
# reading/paged_json.py's generic PagedJsonReader wraps that object as the page's one
# record instead of shaping it down to a chosen field, so every field the fixture record
# carries -- including nested ones like subcommittees, terms and laws -- stays reachable.
# committee-print-detail keeps the publisher's own one-item array under "committeePrint".


def test_law_detail_reads_the_whole_bill_record_as_one_row():
    route = LIST_ROUTES["law-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["law-detail"])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS["law-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    assert page.records_key == "bill"
    assert page.declared_count is None
    assert page.next_url is None
    assert len(page.records) == 1
    bill = page.records[0]
    assert bill["congress"] == 119 and bill["number"] == "1" and bill["type"] == "HR"
    assert bill["laws"] == [{"number": "119-21", "type": "Public Law"}]
    # Fields the fixture record carries beyond the ones this test names -- amendments,
    # committees, sponsors, summaries -- are the same dict, so they are reachable unshaped.
    assert {"actions", "amendments", "committees", "sponsors", "summaries"} <= bill.keys()


def test_committee_detail_reads_the_whole_committee_record_as_one_row():
    route = LIST_ROUTES["committee-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["committee-detail"])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS["committee-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    assert page.records_key == "committee"
    assert page.declared_count is None
    assert len(page.records) == 1
    committee = page.records[0]
    assert committee["systemCode"] == "hsju00" and committee["type"] == "Standing"
    assert isinstance(committee["subcommittees"], list) and len(committee["subcommittees"]) > 0
    assert (
        isinstance(committee["history"], list)
        and committee["history"][0]["officialName"] == "Committee on the Judiciary"
    )


def test_member_detail_reads_the_whole_member_record_as_one_row():
    route = LIST_ROUTES["member-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["member-detail"])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS["member-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key, single_record=route.single_record)
    assert page.records_key == "member"
    assert page.declared_count is None
    assert len(page.records) == 1
    member = page.records[0]
    assert member["bioguideId"] == "W000832"
    assert isinstance(member["terms"], list) and member["terms"][0]["congress"] == 119
    assert isinstance(member["partyHistory"], list) and member["partyHistory"][0]["partyAbbreviation"] == "D"


def test_committee_print_detail_reads_the_publishers_one_item_array():
    route = LIST_ROUTES["committee-print-detail"]
    transport = Transport(DETAIL_FIXTURE_BYTES["committee-print-detail"])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS["committee-print-detail"])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(url, records_key=route.records_key)
    assert page.records_key == "committeePrint"
    assert page.declared_count == 1
    assert len(page.records) == 1
    assert page.records[0]["jacketNumber"] == 63747 and page.records[0]["chamber"] == "House"


@pytest.mark.parametrize("route_name", sorted(DETAIL_FIXTURE_BYTES))
def test_records_walks_every_detail_route_to_a_clean_one_page_end(route_name):
    """The full traversal (`records`/`pages`, not just one `page()` call) on every detail
    shape -- the bare-object routes with no pagination at all, and committee-print-detail's
    real one-item array with pagination.count=1 -- yields exactly one page and ends cleanly,
    the same as reaching a publisher's terminal page normally would."""
    route = LIST_ROUTES[route_name]
    transport = Transport(DETAIL_FIXTURE_BYTES[route_name])
    url = list_route_url(route, limit=3, **ROUTE_PARAMS[route_name])
    with CongressListingReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.records(route, url, max_pages=5))
    assert len(pages) == 1
    assert len(transport.calls) == 1
    assert pages[0].next_url is None
    assert len(pages[0].records) == 1


# --- live pagination contract (one request per route, not run by default) ------

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
LIVE_BUDGET = PagedJsonBudget(2, 4 * 1024 * 1024, 30, 0.5)
# These detail routes answer with no pagination wrapper at all (confirmed live 2026-09-19):
# law-detail, committee-detail and member-detail nest a single object ({"bill": {...}},
# {"committee": {...}}, {"member": {...}}); committee-meeting-detail, daily-congressional-record-
# detail, house-communication-detail, senate-communication-detail and house-requirement-detail
# do the same; treaty-detail nests a one-element array instead, but carries no "pagination" key
# either. committee-print-detail is the one detail route here that keeps a real pagination
# wrapper, since the publisher answers it with a one-item array and a real pagination.count of 1.
NO_PAGINATION_ROUTES = frozenset(
    {
        "law-detail",
        "committee-detail",
        "member-detail",
        "committee-meeting-detail",
        "treaty-detail",
        "daily-congressional-record-detail",
        "house-communication-detail",
        "senate-communication-detail",
        "house-requirement-detail",
    }
)


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
    if route_name not in NO_PAGINATION_ROUTES:
        assert page.declared_count is not None
    assert page.next_url is None or urlsplit(page.next_url).hostname == "api.congress.gov"
    assert len(page.records) >= 1
