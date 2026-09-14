"""The GAO reports feed is read as a recent-items observation whose links name products."""

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.gao.rss import (
    GAO_REPORTS_FEED_URL,
    GaoFeedAcquirer,
    GaoFeedBudget,
    GaoFeedSourceError,
    GaoFeedUnavailableError,
    gao_reports_feed_locator,
    parse_gao_reports_feed,
)
from spicy_docs.transport import retry

FEED = (Path(__file__).parent / "fixtures" / "listings" / "gao-reports-rss.xml").read_bytes()
BUDGET = GaoFeedBudget(3, 4 * 1024 * 1024, 7, 0)
MINIMAL = (
    b'<rss version="2.0"><channel><title>Reports</title><link>https://www.gao.gov/rss/reports.xml</link>'
    b"<lastBuildDate>Mon, 14 Sep 2026 11:01:17 -0400</lastBuildDate>"
    b"<item><title>A</title><link>https://www.gao.gov/products/gao-26-107879</link><guid>/products/gao-26-107879</guid>"
    b"<pubDate>Mon, 14 Sep 2026 07:16:14 -0400</pubDate></item></channel></rss>"
)


def response(body=FEED, status=200, *, content_type="application/rss+xml; charset=utf-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


def test_pinned_feed_yields_products_in_feed_order_with_publisher_spellings():
    feed = parse_gao_reports_feed(FEED)
    assert feed.title == "Reports News from the GAO" and feed.link == GAO_REPORTS_FEED_URL
    assert feed.last_build_date == "Mon, 14 Sep 2026 11:01:17 -0400"
    assert [item.index for item in feed.items] == [0, 1]
    first = feed.items[0]
    assert first.product_id == "gao-26-107879"
    assert first.link == "https://www.gao.gov/products/gao-26-107879"
    assert first.guid == "/products/gao-26-107879"
    assert first.pub_date == "Mon, 14 Sep 2026 07:16:14 -0400"
    assert first.title.startswith("National Register of Historic Places")
    assert first.description and "What GAO Found" in first.description


def test_minimal_feed_keeps_absent_fields_absent():
    feed = parse_gao_reports_feed(MINIMAL)
    assert feed.items[0].description is None and feed.items[0].product_id == "gao-26-107879"


@pytest.mark.parametrize(
    "body,message",
    [
        (MINIMAL.replace(b'<rss version="2.0">', b'<rss version="1.0">'), "RSS 2.0"),
        (MINIMAL.replace(b"<rss", b"<feed").replace(b"</rss>", b"</feed>"), "RSS 2.0"),
        (MINIMAL.replace(b"</channel>", b"</channel><channel/>"), "exactly one channel"),
        (MINIMAL.replace(b"<title>A</title>", b""), "title and a link"),
        (
            MINIMAL.replace(b"<link>https://www.gao.gov/products/gao-26-107879</link>", b"<link> </link>"),
            "title and a link",
        ),
        (MINIMAL.replace(b"<title>A</title>", b"<title>A</title><title>B</title>"), "repeats title"),
        (MINIMAL.replace(b"products/gao-26-107879</link>", b"reports/gao-26-107879</link>"), "not a product URL"),
        (
            MINIMAL.replace(
                b"https://www.gao.gov/products/gao-26-107879</link>",
                b"http://www.gao.gov/products/gao-26-107879</link>",
            ),
            "not a product URL",
        ),
        (
            MINIMAL.replace(b"products/gao-26-107879</link>", b"products/GAO-26-107879</link>"),
            "does not name a product",
        ),
        (
            MINIMAL.replace(b"products/gao-26-107879</link>", b"products/gao-26-107879/</link>"),
            "does not name a product",
        ),
        (
            MINIMAL.replace(b"</item>", b"</item>" + MINIMAL[MINIMAL.index(b"<item>") : MINIMAL.index(b"</item>") + 7]),
            "more than once",
        ),
        (b"<!DOCTYPE rss [<!ENTITY x 'y'>]>" + MINIMAL, "DOCTYPE"),
        (MINIMAL[:-6], "malformed"),
        (b"<html><body>Checking your browser</body></html>", "RSS 2.0"),
        (b"", "nonempty"),
    ],
)
def test_feed_refusals_name_the_failed_check(body, message):
    with pytest.raises(GaoFeedSourceError, match=message):
        parse_gao_reports_feed(body)


@pytest.mark.parametrize("max_bytes", [0, True, 64 * 1024**2 + 1])
def test_feed_bounds_are_explicit(max_bytes):
    with pytest.raises(GaoFeedSourceError):
        parse_gao_reports_feed(MINIMAL, max_bytes=max_bytes)
    with pytest.raises(GaoFeedSourceError, match="max_bytes"):
        parse_gao_reports_feed(MINIMAL, max_bytes=len(MINIMAL) - 1)


def test_acquirer_captures_exact_feed_bytes_keyless():
    transport = Transport(response())
    with GaoFeedAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_reports_feed()
    assert result.capture.body == FEED and result.capture.requested_url == gao_reports_feed_locator()
    assert len(result.feed.items) == 2 and result.request_count == 1 and result.budget == BUDGET
    assert "x-api-key" not in transport.calls[0].headers
    assert transport.calls[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "answer,error",
    [
        (response(b"<html>Access denied</html>", content_type="text/html"), GaoFeedSourceError),
        (response(b"<html>Access denied</html>"), GaoFeedSourceError),
        (response(b"gone", 404), GaoFeedUnavailableError),
        (response(b"", 410), GaoFeedUnavailableError),
    ],
)
def test_wrong_shape_or_unavailable_feed_never_succeeds(answer, error):
    transport = Transport(answer)
    with GaoFeedAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error) as raised:
        source.acquire_reports_feed()
    assert raised.value.refused_response.response_bytes is not None
    assert raised.value.gao_feed_acquisition["operation"] == "reports-feed"
    assert len(transport.calls) == 1


def test_budget_and_client_configuration_are_explicit():
    for fields in ({"max_requests": 0}, {"max_bytes": 64 * 1024**2 + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            GaoFeedBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        GaoFeedAcquirer(budget=(3, 4096, 7, 0), transport=Transport())
