"""FCC ECFS routes walk explicit date windows by offset and end at the first short page."""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.fcc_ecfs import FCC_ECFS, FccEcfsReader, filings_url, proceedings_url
from spicy_docs.sources.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
PROCEEDINGS = (FIXTURES / "fcc-ecfs-proceedings.json").read_bytes()
FILINGS = (FIXTURES / "fcc-ecfs-filings.json").read_bytes()
BUDGET = PagedJsonBudget(3, 256 * 1024, 7, 0)
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


def test_family_and_window_urls():
    assert FCC_ECFS.next_kind == "offset" and FCC_ECFS.count_path is None and FCC_ECFS.requires_credential
    assert proceedings_url(created_from="2026-01-01", created_to="2026-01-31", limit=2) == (
        "https://publicapi.fcc.gov/ecfs/proceedings?date_proceeding_created=%5Bgte%5D2026-01-01%5Blte%5D2026-01-31"
        "&sort=date_proceeding_created%2CDESC&limit=2&offset=0"
    )
    assert filings_url(received_from="2026-09-01", received_to="2026-09-02", limit=2, descending=False).endswith(
        "&sort=date_received%2CASC&limit=2&offset=0"
    )
    for kwargs in (
        {"created_from": "2026-1-1", "created_to": "2026-01-31"},
        {"created_from": "2026-02-01", "created_to": "2026-01-01"},
        {"created_from": "2026-01-01", "created_to": "2026-01-31", "limit": 251},
        {"created_from": "2026-01-01", "created_to": "2026-01-31", "offset": -1},
    ):
        with pytest.raises(PagedJsonSourceError):
            proceedings_url(**kwargs)


def test_pinned_pages_parse_and_the_walk_advances_by_offset():
    transport = Transport(PROCEEDINGS, FILINGS)
    with FccEcfsReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        proceedings = source.page(
            proceedings_url(created_from="2026-01-01", created_to="2026-01-31", limit=2), records_key="proceeding"
        )
        filings = source.page(
            filings_url(received_from="2026-09-01", received_to="2026-09-02", limit=2), records_key="filing"
        )
    assert proceedings.declared_count is None and len(proceedings.records) == 2
    assert proceedings.next_url.endswith("&limit=2&offset=2")
    assert proceedings.records[0]["id_proceeding"] and proceedings.records[0]["date_proceeding_created"]
    assert filings.records[0]["id_submission"] and filings.records[0]["date_received"]
    assert transport.calls[0].headers["x-api-key"] == KEY
    short = json.loads(PROCEEDINGS)
    short["proceeding"] = short["proceeding"][:1]
    transport = Transport(PROCEEDINGS, json.dumps(short).encode())
    with FccEcfsReader(budget=BUDGET, api_key=KEY, transport=transport) as source:
        pages = list(source.proceedings(proceedings_url(created_from="2026-01-01", created_to="2026-01-31", limit=2)))
    assert [len(p.records) for p in pages] == [2, 1] and pages[1].next_url is None
    assert [str(c.url).rsplit("offset=", 1)[1] for c in transport.calls] == ["0", "2"]
