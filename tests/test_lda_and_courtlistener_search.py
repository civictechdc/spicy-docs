"""LDA and CourtListener list routes: URL builders, optional token credentials, and page continuations.

Pins each family's declared credential header/format and count/next paths, the
exact built URLs with their refusal conditions, and that pinned fixture pages
parse with URL or cursor continuations and no Authorization header when keyless.
"""

import json
from pathlib import Path

import httpx
import pytest

from spicy_docs.reading.paged_json import PagedJsonBudget, PagedJsonSourceError
from spicy_docs.sources.courtlistener.search import COURTLISTENER, CourtListenerSearchReader, search_url
from spicy_docs.sources.lda import LDA, LdaFilingsReader, filings_url
from spicy_docs.transport import retry

FIXTURES = Path(__file__).parent / "fixtures" / "listings"
LDA_PAGE = (FIXTURES / "lda-filings-p1.json").read_bytes()
RECAP = (FIXTURES / "courtlistener-search-recap.json").read_bytes()
OPINIONS = (FIXTURES / "courtlistener-search-opinions.json").read_bytes()
BUDGET = PagedJsonBudget(3, 256 * 1024, 7, 0)


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


def test_families_state_optional_token_credentials():
    """Both families declare optional ``Token {key}`` Authorization credentials and ``next``/``count`` paths."""
    for family in (LDA, COURTLISTENER):
        assert family.credential_header == "Authorization" and family.credential_format == "Token {key}"
        assert not family.requires_credential and family.next_path == ("next",) and family.count_path == ("count",)


def test_lda_filings_url_and_refusals():
    """Builds the exact filings URL for year, date window and ordering, refusing values outside the declared bounds."""
    assert filings_url(filing_year=2026, page_size=2) == (
        "https://lda.gov/api/v1/filings/?filing_year=2026&ordering=dt_posted&page=1&page_size=2"
    )
    assert filings_url(posted_after="2026-09-01", posted_before="2026-09-14", ordering="-dt_posted") == (
        "https://lda.gov/api/v1/filings/?filing_dt_posted_after=2026-09-01&filing_dt_posted_before=2026-09-14"
        "&ordering=-dt_posted&page=1&page_size=25"
    )
    for kwargs in (
        {"filing_year": 1998},
        {"page_size": 26},
        {"page_size": 0},
        {"ordering": "income"},
        {"posted_after": "2026-9-1"},
        {"posted_after": "2026-09-02", "posted_before": "2026-09-01"},
    ):
        with pytest.raises(PagedJsonSourceError):
            filings_url(**kwargs)


def test_lda_pinned_page_parses_keyless_and_with_a_token():
    """A pinned LDA page parses with or without a key, sending Authorization only when one is given."""
    transport = Transport(LDA_PAGE, LDA_PAGE)
    with LdaFilingsReader(budget=BUDGET, transport=transport) as keyless:
        page = keyless.page(filings_url(filing_year=2026, page_size=2), records_key="results")
    with LdaFilingsReader(budget=BUDGET, api_key="abc123", transport=transport) as keyed:
        keyed.page(filings_url(filing_year=2026, page_size=2), records_key="results")
    assert page.declared_count == 56448 and len(page.records) == 2
    assert page.next_url == "https://lda.gov/api/v1/filings/?filing_year=2026&ordering=dt_posted&page=2&page_size=2"
    assert page.records[0]["filing_uuid"] and page.records[0]["filing_year"] == 2026
    assert "authorization" not in transport.calls[0].headers
    assert transport.calls[1].headers["authorization"] == "Token abc123"


def test_lda_walk_ends_when_the_count_is_met():
    """The walk stops at the declared count even though a next link remains."""
    first = json.loads(LDA_PAGE)
    first["count"] = 4
    second = json.loads(LDA_PAGE)
    second["count"], second["next"] = 4, None
    transport = Transport(json.dumps(first).encode(), json.dumps(second).encode())
    with LdaFilingsReader(budget=BUDGET, transport=transport) as source:
        pages = list(source.filings(filings_url(filing_year=2026, page_size=2)))
    assert [len(p.records) for p in pages] == [2, 2]


def test_courtlistener_search_url_and_refusals():
    """Builds the exact search URL per kind, order, court, filed-after and query, and refuses malformed values."""
    assert search_url(kind="r", filed_after="2026-09-01") == (
        "https://www.courtlistener.com/api/rest/v4/search/?type=r&order_by=dateFiled+asc&filed_after=09%2F01%2F2026"
    )
    assert search_url(kind="o", order_by="dateFiled desc", court="scotus", q="habeas") == (
        "https://www.courtlistener.com/api/rest/v4/search/?type=o&order_by=dateFiled+desc&court=scotus&q=habeas"
    )
    for kwargs in (
        {"kind": "d"},
        {"kind": "r", "order_by": "score desc"},
        {"kind": "r", "court": "SCOTUS"},
        {"kind": "r", "filed_after": "09/01/2026"},
        {"kind": "r", "q": " "},
    ):
        with pytest.raises(PagedJsonSourceError):
            search_url(**kwargs)


def test_courtlistener_pinned_pages_parse_with_cursor_continuations():
    """Pinned recap and opinion pages parse and expose a cursor next URL, with no Authorization when keyless."""
    transport = Transport(RECAP, OPINIONS)
    with CourtListenerSearchReader(budget=BUDGET, transport=transport) as source:
        recap = source.page(search_url(kind="r", filed_after="2026-09-01"), records_key="results")
        opinions = source.page(search_url(kind="o", filed_after="2026-09-01"), records_key="results")
    assert recap.declared_count == 48184 and len(recap.records) == 20
    assert "cursor=" in recap.next_url and recap.next_url.startswith(
        "https://www.courtlistener.com/api/rest/v4/search/?"
    )
    assert recap.records[0]["docket_id"] and "dateFiled" in recap.records[0]
    assert opinions.declared_count == 1464 and opinions.records[0]["cluster_id"]
    assert "authorization" not in transport.calls[0].headers
