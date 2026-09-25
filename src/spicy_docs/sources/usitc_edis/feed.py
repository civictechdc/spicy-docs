"""The EDIS document notification feed: RSS 2.0 items for newly arriving documents.

``/external/rss/render.rss/?criteria=...`` is the public channel the RSS
Feed Generator builds (``https://edis.usitc.gov/external/rss/rssFeedGenerator.html``,
no registration): each ``<item>`` announces one document received in EDIS,
with the document id as its ``<guid>``, the docket phase in the title, the
document type as its ``<category>``, and -- in ``content:encoded`` -- the
filed date, filer, firm, party, document title and security level, plus a
link to ``https://edis.usitc.gov/external/search/document/{id}``. The
generator's criteria grammar is one or more
``CRITERIONINVDEL:{feedInvestigationId}:PHASE:{phase}`` selectors and a
``CRITERIONANOTIFY:true`` flag, joined without separators; that id is the
feed's internal investigation id (5193, 8018 in the retained capture), not
the `/data` ``docketNumber`` -- keep them apart.

**It is a notification window, not a docket.** The retained 2022 capture
holds items published in one batch instant for two investigations, and the
2026-09-24 live render of an old investigation's feed carried zero items:
the feed answers newly arriving documents, so a complete docket comes from
the `/data` document listing, and this feed is the push channel that says
when to re-walk. The document link is read only from the anchor the item's
own HTML states; no URL is derived from the guid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from spicy_docs.reading.rss import child_text, read_rss2_channel
from spicy_docs.sources.usitc_edis.records import EDIS_HOST, UsitcEdisSourceError

DEFAULT_MAX_FEED_BYTES = 4 * 1024 * 1024
#: The description marker the feed states for a confidential document.
_CONFIDENTIAL_MARKERS = ("[Confidential Document]",)
#: The document anchor an item's ``content:encoded`` HTML states.
_DOCUMENT_ANCHOR = re.compile(
    r"<a href=\"(https://" + re.escape(EDIS_HOST) + r"/external/search/document/([0-9]{1,12}))\">"
)
#: ``reading/xml.py`` expands namespaced tags to ``{uri}local``; the feed's
#: ``content:encoded`` element arrives under the RSS content module URI.
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"


@dataclass(frozen=True, slots=True)
class EdisFeedItem:
    """One notification as the feed spelled it; ``document_id`` is the `/data` document id."""

    index: int
    document_id: int
    title: str
    document_type: str | None
    published: str | None
    description: str | None
    confidential: bool
    content_html: str | None
    public_document_url: str | None
    public_document_id: int | None


@dataclass(frozen=True, slots=True)
class EdisNotificationFeed:
    """One feed render: what the channel stated at that instant, never a catalog."""

    title: str | None
    link: str | None
    items: tuple[EdisFeedItem, ...]


def _document_anchor(content_html: str | None) -> tuple[str, int] | None:
    """The document link and id the item's own HTML states, or ``None``; never derived from the guid."""
    if content_html is None:
        return None
    stated = _DOCUMENT_ANCHOR.search(content_html)
    if stated is None:
        return None
    return stated[1], int(stated[2])


def parse_edis_feed(body: bytes, *, max_bytes: int = DEFAULT_MAX_FEED_BYTES) -> EdisNotificationFeed:
    """Read one feed render's items in feed order. O(B); item fields stay verbatim."""
    label = "EDIS notification feed"
    channel, items = read_rss2_channel(body, max_bytes=max_bytes, error_type=UsitcEdisSourceError, label=label)
    parsed = []
    for index, item in enumerate(items):
        item_label = f"{label} item"
        guid = child_text(item, "guid", error_type=UsitcEdisSourceError, label=item_label)
        if guid is None or not guid.isdigit():
            raise UsitcEdisSourceError(f"{item_label} states no numeric document guid")
        title = child_text(item, "title", error_type=UsitcEdisSourceError, label=item_label)
        if title is None:
            raise UsitcEdisSourceError(f"{item_label} states no title")
        description = child_text(item, "description", error_type=UsitcEdisSourceError, label=item_label)
        content_html = child_text(item, CONTENT_ENCODED, error_type=UsitcEdisSourceError, label=item_label)
        anchor = _document_anchor(content_html)
        if anchor is not None:
            url, document_id = anchor
            parts = urlsplit(url)
            if parts.fragment or parts.query:
                raise UsitcEdisSourceError(f"{item_label} document link carries more than its path")
            if document_id != int(guid):
                raise UsitcEdisSourceError(f"{item_label} document link names a document other than its guid")
        parsed.append(
            EdisFeedItem(
                index=index,
                document_id=int(guid),
                title=title,
                document_type=child_text(item, "category", error_type=UsitcEdisSourceError, label=item_label),
                published=child_text(item, "pubDate", error_type=UsitcEdisSourceError, label=item_label),
                description=description,
                confidential=description is not None and any(marker in description for marker in _CONFIDENTIAL_MARKERS),
                content_html=content_html,
                public_document_url=anchor[0] if anchor else None,
                public_document_id=anchor[1] if anchor else None,
            )
        )
    return EdisNotificationFeed(
        title=child_text(channel, "title", error_type=UsitcEdisSourceError, label=label),
        link=child_text(channel, "link", error_type=UsitcEdisSourceError, label=label),
        items=tuple(parsed),
    )
