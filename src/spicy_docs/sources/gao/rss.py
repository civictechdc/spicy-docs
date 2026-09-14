"""The GAO reports feed: the one keyless, machine-readable listing of recent products.

GAO's product, sitemap and search routes refuse non-browser clients; product
pages are captured through Zyte (``native.py``). The public RSS feed at
``www.gao.gov/rss/reports.xml`` serves anonymously and lists about 25 recently
published products with title, link, GUID, description and publication date.
It is a recent-items window, not an archive: a feed capture is an observation
of what the publisher listed at that moment, never a catalog. Each item's link
must be a canonical product URL, which supplies the product identifier.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

from spicy_docs.sources.gao.native import SOURCE_SYSTEM_ID, GaoProductSourceError, gao_product_url
from spicy_docs.sources.xml import parse_xml
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

GAO_REPORTS_FEED_URL = "https://www.gao.gov/rss/reports.xml"
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_FEED_BYTES = 64 * 1024 * 1024
MAX_FEED_ITEMS = 1000
_ITEM_FIELDS = ("title", "link", "guid", "description", "pubDate")


class GaoFeedSourceError(ValueError):
    """The feed response cannot establish a GAO product listing."""


class GaoFeedUnavailableError(GaoFeedSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"GAO feed answered HTTP {capture.status_code}")
        self.capture = capture


@dataclass(frozen=True, slots=True)
class GaoFeedItem:
    """One listed product as the feed spelled it; ``product_id`` comes from the canonical link."""

    index: int
    product_id: str
    title: str
    link: str
    guid: str | None
    description: str | None
    pub_date: str | None


@dataclass(frozen=True, slots=True)
class GaoReportsFeed:
    title: str | None
    link: str | None
    last_build_date: str | None
    items: tuple[GaoFeedItem, ...]


def gao_reports_feed_locator() -> str:
    return GAO_REPORTS_FEED_URL


def _text(element: Element, tag: str) -> str | None:
    children = [child for child in element if child.tag == tag]
    if len(children) > 1:
        raise GaoFeedSourceError(f"GAO feed repeats {tag}")
    if not children or children[0].text is None or not children[0].text.strip():
        return None
    return children[0].text.strip()


def _product_id_from_link(link: str) -> str:
    parts = urlsplit(link)
    prefix = urlsplit(SOURCE_SYSTEM_ID)
    if (
        parts.scheme != prefix.scheme
        or parts.hostname != prefix.hostname
        or not parts.path.startswith(prefix.path + "/")
    ):
        raise GaoFeedSourceError("GAO feed item link is not a product URL")
    slug = parts.path.removeprefix(prefix.path + "/")
    try:
        canonical = gao_product_url(slug)
    except GaoProductSourceError as error:
        raise GaoFeedSourceError("GAO feed item link does not name a product") from error
    if link != canonical:
        raise GaoFeedSourceError("GAO feed item link differs from the canonical product URL")
    return slug


def parse_gao_reports_feed(body: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> GaoReportsFeed:
    """Read the RSS 2.0 channel; every item must link a canonical product page."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_FEED_BYTES:
        raise GaoFeedSourceError("max_bytes must be a positive integer no greater than 64 MiB")
    root = parse_xml(body, max_bytes=max_bytes, error_type=GaoFeedSourceError, label="GAO feed")
    if root.tag != "rss" or root.get("version") != "2.0":
        raise GaoFeedSourceError("GAO feed is not an RSS 2.0 document")
    channels = [child for child in root if child.tag == "channel"]
    if len(channels) != 1:
        raise GaoFeedSourceError("GAO feed requires exactly one channel")
    channel = channels[0]
    items = []
    for index, element in enumerate(child for child in channel if child.tag == "item"):
        if index >= MAX_FEED_ITEMS:
            raise GaoFeedSourceError("GAO feed lists more items than supported")
        title, link = _text(element, "title"), _text(element, "link")
        if title is None or link is None:
            raise GaoFeedSourceError("GAO feed item requires a title and a link")
        items.append(
            GaoFeedItem(
                index,
                _product_id_from_link(link),
                title,
                link,
                _text(element, "guid"),
                _text(element, "description"),
                _text(element, "pubDate"),
            )
        )
    if len({item.product_id for item in items}) != len(items):
        raise GaoFeedSourceError("GAO feed lists a product more than once")
    return GaoReportsFeed(
        _text(channel, "title"), _text(channel, "link"), _text(channel, "lastBuildDate"), tuple(items)
    )


@dataclass(frozen=True, slots=True)
class GaoFeedBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_FEED_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class GaoFeedAcquisition:
    feed: GaoReportsFeed
    capture: CapturedBodyResponse
    request_count: int
    budget: GaoFeedBudget


class GaoFeedAcquirer(SourceAcquirer):
    """Keyless capture of the reports feed; the product pages remain a separate, Zyte-backed capture."""

    def __init__(
        self,
        *,
        budget: GaoFeedBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, GaoFeedBudget):
            raise TypeError("budget must be a GaoFeedBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-gao-feed/1.0",
            label="GAO feed",
            error_type=GaoFeedSourceError,
            context_key="gao_feed_acquisition",
            transport=transport,
            clock=clock,
        )

    @property
    def budget(self) -> GaoFeedBudget:
        return self._budget

    def acquire_reports_feed(self) -> GaoFeedAcquisition:
        feed, capture = self.capture_validated(
            gao_reports_feed_locator(),
            media_types=("application/rss+xml", "application/xml", "text/xml"),
            parse=lambda response, limit: parse_gao_reports_feed(response.body, max_bytes=limit),
            max_bytes=self.budget.max_bytes,
            unavailable=GaoFeedUnavailableError,
            context={"operation": "reports-feed", "url": gao_reports_feed_locator()},
        )
        return GaoFeedAcquisition(feed, capture, self.request_count, self.budget)
