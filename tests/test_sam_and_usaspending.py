"""SAM.gov and USAspending list routes: placeholder credentials dropped, POST pages recorded."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.sam import SAM, SamEntitiesReader, entities_url
from spicy_docs.sources.usaspending import RECIPIENTS_URL, USASPENDING, UsaspendingRecipientsReader, recipients_request
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
SAM_PAGE = (FIXTURES / "sam-entities-p1.json").read_bytes()
USA_PAGE = (FIXTURES / "usaspending-recipient-p1.json").read_bytes()
BUDGET = PagedJsonBudget(3, 256 * 1024, 7, 0)
KEY = "SAMkey0123456789abcdef"


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


def test_sam_family_and_url():
    assert SAM.requires_credential and SAM.credential_header == "X-Api-Key" and "api_key" in SAM.drop_query_names
    assert (
        entities_url(size=2) == "https://api.sam.gov/entity-information/v4/entities?registrationStatus=A&size=2&page=0"
    )
    assert entities_url(
        registration_status=None, registered_from=date(2025, 1, 1), registered_to=date(2025, 12, 31)
    ) == ("https://api.sam.gov/entity-information/v4/entities?registrationDate=[01/01/2025,12/31/2025]&size=10&page=0")
    for kwargs in (
        {"registration_status": "X"},
        {"size": 11},
        {"page": -1},
        {"registered_from": date(2025, 1, 1)},
        {"registered_from": date(2025, 2, 1), "registered_to": date(2025, 1, 1)},
    ):
        with pytest.raises(PagedJsonSourceError):
            entities_url(**kwargs)


def test_sam_pinned_page_drops_the_placeholder_and_keeps_the_key_in_the_header():
    transport = Transport(SAM_PAGE)
    with SamEntitiesReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        page = source.page(entities_url(size=2), records_key="entityData")
    assert page.declared_count == 790124 and len(page.records) == 2
    assert page.next_url == "https://api.sam.gov/entity-information/v4/entities?registrationStatus=A&size=2&page=1"
    assert b"REPLACE_WITH_API_KEY" in page.capture.body
    assert page.records[0]["entityRegistration"]["ueiSAM"]
    assert transport.calls[0].headers["x-api-key"] == KEY and "api_key" not in str(transport.calls[0].url)
    with pytest.raises(ValueError, match="requires an explicit API key"):
        SamEntitiesReader(budget=BUDGET, api_key=None, transport=transport)


def test_usaspending_family_and_request():
    assert (
        USASPENDING.method == "POST"
        and USASPENDING.next_kind == "page-number"
        and USASPENDING.credential_header is None
    )
    url, body = recipients_request(limit=2)
    assert url == RECIPIENTS_URL and body == {
        "limit": 2,
        "page": 1,
        "order": "desc",
        "sort": "amount",
        "award_type": "all",
    }
    assert recipients_request(keyword="acme", award_type="grants")[1]["keyword"] == "acme"
    for kwargs in (
        {"limit": 0},
        {"limit": 101},
        {"page": 0},
        {"sort": "id"},
        {"order": "up"},
        {"award_type": "idv"},
        {"keyword": " "},
    ):
        with pytest.raises(PagedJsonSourceError):
            recipients_request(**kwargs)


def test_usaspending_pinned_page_and_walk_record_each_request_body():
    first = USA_PAGE
    second = json.loads(USA_PAGE)
    second["page_metadata"].update(page=2, next=None, hasNext=False, total=4)
    first_dict = json.loads(first)
    first_dict["page_metadata"]["total"] = 4
    transport = Transport(json.dumps(first_dict).encode(), json.dumps(second).encode())
    with UsaspendingRecipientsReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.recipients(recipients_request(limit=2)[1]))
    assert [p.request_body["page"] for p in pages] == [1, 2]
    assert pages[0].capture.request_body == b'{"award_type":"all","limit":2,"order":"desc","page":1,"sort":"amount"}'
    assert pages[0].records[0]["uei"] and pages[0].records[0]["recipient_level"]
    assert transport.calls[1].method == "POST" and json.loads(transport.calls[1].read())["page"] == 2
    with UsaspendingRecipientsReader(budget=BUDGET, transport=Transport(USA_PAGE)) as source:
        page = source.page(RECIPIENTS_URL, records_key="results", body=recipients_request(limit=2)[1])
    assert page.declared_count == 18302930 and page.next_body["page"] == 2
