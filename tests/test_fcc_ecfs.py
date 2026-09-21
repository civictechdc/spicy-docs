"""FCC ECFS routes walk explicit date windows by offset and end at the first short page.

The publisher's bracketed bounds are instants at ``00:00:00Z``, so an inclusive
caller window ending on day E is sent as ``[lte]E+1``; see the module docstring
for the live measurement behind that.
"""

import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from spicy_docs.reading.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.fcc_ecfs import FCC_ECFS, FccEcfsReader, filings_url, proceedings_url
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
PROCEEDINGS = (FIXTURES / "fcc-ecfs-proceedings.json").read_bytes()
FILINGS = (FIXTURES / "fcc-ecfs-filings.json").read_bytes()
BUDGET = PagedJsonBudget(3, 256 * 1024, 7, 0)
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


def test_family_and_window_urls():
    """The family states offset paging, no count path and a credential requirement, and URL builders send explicit
    windows.
    """
    assert FCC_ECFS.next_kind == "offset" and FCC_ECFS.count_path is None and FCC_ECFS.requires_credential
    assert proceedings_url(created_from="2026-01-01", created_to="2026-01-31", limit=2) == (
        "https://publicapi.fcc.gov/ecfs/proceedings?date_proceeding_created=%5Bgte%5D2026-01-01%5Blte%5D2026-02-01"
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
        {"created_from": "9999-12-31", "created_to": "9999-12-31"},
    ):
        with pytest.raises(PagedJsonSourceError):
            proceedings_url(**kwargs)


@pytest.mark.parametrize(
    "start,end,literal",
    [
        # A same-day window means that whole day: [gte]D[lte]D matched only the
        # midnight instant and answered zero rows live on 2026-09-14.
        ("2026-09-08", "2026-09-08", "[gte]2026-09-08[lte]2026-09-09"),
        ("2026-09-01", "2026-09-02", "[gte]2026-09-01[lte]2026-09-03"),
        # Month, year and leap-day ends roll over rather than being clamped.
        ("2026-01-01", "2026-01-31", "[gte]2026-01-01[lte]2026-02-01"),
        ("2026-12-01", "2026-12-31", "[gte]2026-12-01[lte]2027-01-01"),
        ("2024-02-28", "2024-02-28", "[gte]2024-02-28[lte]2024-02-29"),
    ],
)
def test_an_inclusive_caller_window_is_sent_as_the_publishers_following_midnight(start, end, literal):
    """An inclusive caller window is sent as the publisher's following midnight so the end day is not excluded."""
    for url, field in (
        (filings_url(received_from=start, received_to=end), "date_received"),
        (proceedings_url(created_from=start, created_to=end), "date_proceeding_created"),
    ):
        assert f"{field}={quote(literal)}" in url
        assert f"{field}={quote(f'[gte]{start}[lte]{end}')}" not in url, "the end day must not be excluded"


def test_pinned_pages_parse_and_the_walk_advances_by_offset():
    """Pinned pages parse and the walk advances by offset to the first short page."""
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
