"""Appropriations committee press releases: two keyless RSS 2.0 feeds, one per chamber.

BillTrax carried four spellings of these two feeds and all four are dead
(measured 2026-09-19): both House spellings answer 404, the Senate library
spelling answers 410 Gone, and the Senate script spelling answers 200 with a
606-byte ColdFusion error page, not a feed. The two canonical addresses are
each publisher's own: ``appropriations.house.gov/rss.xml`` and
``www.appropriations.senate.gov/rss/feeds/?type=press``. Both are RSS 2.0 with
no default namespace; neither publisher serves Atom, so this module never
looks for one.

**The Senate's ``?type=`` parameter is not honored by the URL alone.** An
unrecognized value answers 200 with a byte-identical default channel titled
"United States Senate Committee on Appropriations Feed" instead of failing, so
a request URL proves nothing about what came back; ``_check_feed_identity`` is
a check the default channel's own title and link host fail.

Every item field either feed carries is kept in full: no 500-character
excerpt, no dropped ``dc:creator``/``<author>``, no dropped channel-level
``ttl``/``skipDays``/``skipHours``/``lastBuildDate``. The Senate item has no
``<description>`` at all, so that field stays optional rather than being
papered over. The Senate's ``pubDate`` spells its zone ``EST`` even in
September, when real Eastern time is ``EDT``; RFC 822's fixed abbreviation
table maps ``EST`` to a constant UTC-5 offset regardless of season, so
``pub_date_instant`` on a Senate item can read up to an hour earlier than the
true Eastern wall-clock time the publisher meant -- the publisher's own quirk,
kept, not corrected -- while ``pub_date`` keeps the exact string.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

from spicy_docs.reading.markup import MarkupReadError, read_html_events
from spicy_docs.reading.rss import DEFAULT_MAX_ITEMS, child_text, read_rss2_channel, single_child
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.source_acquirer import (
    SourceAcquirer,
    check_byte_bound,
    check_request_count,
    check_timing,
    named_challenge,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

type Chamber = Literal["house", "senate"]

MEDIA_TYPES = ("application/rss+xml", "application/xml", "text/xml")
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_FEED_BYTES = 64 * 1024 * 1024
DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"


class PressReleaseFeedSourceError(ValueError):
    """The response cannot establish an appropriations committee press-release feed."""


class PressReleaseFeedUnavailableError(PressReleaseFeedSourceError):
    def __init__(self, capture: CapturedBodyResponse) -> None:
        super().__init__(f"press-release feed answered HTTP {capture.status_code}")
        self.capture = capture


class PressReleaseFeedRefusedError(PressReleaseFeedSourceError):
    """A keyless route answered 401/403; there is no credential here to reject.

    Neither committee site names a credential, but either can still bot-wall
    a request. ``named_challenge`` recasts that refusal into this error so it
    is catchable as a ``PressReleaseFeedSourceError``, its body retained as
    evidence on ``refused_response``, the way ``LegislatorsRefusedError`` and
    ``CboChallengeError`` already do for other keyless routes.
    """

    def __init__(self, url: str) -> None:
        super().__init__(f"press-release feed refused access to {url}; no credential exists to reject")
        self.url = url


@dataclass(frozen=True, slots=True)
class PressReleaseFeed:
    """One committee's feed locator, plus the content proof its identity check requires.

    ``identity_title_contains`` are substrings the channel's ``<title>`` must
    all contain; for the Senate this includes "Press" specifically, because
    the byte-identical default channel's title lacks it (see the module
    docstring). ``identity_link_host`` is the hostname the channel's
    ``<link>`` must name -- checked separately from the request URL, since a
    same-host redirect or proxy could otherwise still pass a title-only check.
    """

    chamber: Chamber
    url: str
    identity_title_contains: tuple[str, ...]
    identity_link_host: str


PRESS_RELEASE_FEEDS: dict[Chamber, PressReleaseFeed] = {
    "house": PressReleaseFeed(
        chamber="house",
        url="https://appropriations.house.gov/rss.xml",
        identity_title_contains=("Committee on Appropriations",),
        identity_link_host="appropriations.house.gov",
    ),
    "senate": PressReleaseFeed(
        chamber="senate",
        url="https://www.appropriations.senate.gov/rss/feeds/?type=press",
        identity_title_contains=("Committee on Appropriations", "Press"),
        identity_link_host="www.appropriations.senate.gov",
    ),
}


@dataclass(frozen=True, slots=True)
class PressRelease:
    """One item exactly as its feed spelled it; nothing is truncated or dropped.

    ``guid_is_permalink`` is ``None`` when the item carries no ``<guid>`` at
    all, and ``True`` when a ``<guid>`` omits ``isPermaLink`` -- RFC 2009's
    default when the attribute is absent. ``description`` is the item's raw
    HTML exactly as the publisher wrote it; ``description_text`` is that same
    text stripped through ``reading/markup.py``'s HTML reader, not a truncated
    excerpt.
    """

    index: int
    chamber: Chamber
    title: str
    link: str
    guid: str | None
    guid_is_permalink: bool | None
    description: str | None
    description_text: str | None
    pub_date: str | None
    pub_date_instant: datetime | None
    author: str | None
    creator: str | None
    categories: tuple[str, ...]
    enclosure_url: str | None
    enclosure_length: int | None
    enclosure_type: str | None


@dataclass(frozen=True, slots=True)
class PressReleaseChannel:
    """The channel-level facts BillTrax drops entirely, plus every item.

    ``ttl``, ``skip_days`` and ``skip_hours`` are the Senate's own polling
    contract (measured 2026-09-19: the House states none of the three).
    ``skip_days`` and ``skip_hours`` are empty tuples, not ``None``, when the
    channel carries no ``<skipDays>``/``<skipHours>`` container at all.
    """

    title: str | None
    link: str | None
    description: str | None
    language: str | None
    copyright: str | None
    docs: str | None
    last_build_date: str | None
    ttl: int | None
    skip_days: tuple[str, ...]
    skip_hours: tuple[int, ...]
    releases: tuple[PressRelease, ...]


def press_release_feed_locator(chamber: Chamber) -> str:
    try:
        return PRESS_RELEASE_FEEDS[chamber].url
    except KeyError:
        raise PressReleaseFeedSourceError(f"no press-release feed is registered for chamber {chamber!r}") from None


def _check_feed_identity(feed: PressReleaseFeed, *, title: str | None, link: str | None) -> None:
    """Prove the body is this committee's feed, not a byte-identical default channel; see module docstring."""
    if title is None or any(part not in title for part in feed.identity_title_contains):
        raise PressReleaseFeedSourceError(
            f"{feed.chamber} press-release feed channel title {title!r} does not confirm the requested "
            f"{feed.chamber} committee feed; the publisher may have answered its default feed"
        )
    if urlsplit(link or "").hostname != feed.identity_link_host:
        raise PressReleaseFeedSourceError(
            f"{feed.chamber} press-release feed channel link {link!r} does not name {feed.identity_link_host}"
        )


def _read_channel_ttl(channel: Element, *, label: str) -> int | None:
    raw = child_text(channel, "ttl", error_type=PressReleaseFeedSourceError, label=label)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise PressReleaseFeedSourceError(f"{label} channel ttl is not an integer: {raw!r}") from None


def _read_channel_skip_days(channel: Element, *, label: str) -> tuple[str, ...]:
    container = single_child(channel, "skipDays", error_type=PressReleaseFeedSourceError, label=label)
    if container is None:
        return ()
    return tuple(child.text.strip() for child in container if child.tag == "day" and child.text and child.text.strip())


def _read_channel_skip_hours(channel: Element, *, label: str) -> tuple[int, ...]:
    container = single_child(channel, "skipHours", error_type=PressReleaseFeedSourceError, label=label)
    if container is None:
        return ()
    hours = []
    for child in container:
        if child.tag != "hour" or not child.text or not child.text.strip():
            continue
        try:
            hours.append(int(child.text.strip()))
        except ValueError:
            raise PressReleaseFeedSourceError(
                f"{label} channel skipHours hour is not an integer: {child.text!r}"
            ) from None
    return tuple(hours)


def _strip_description(html: str, *, label: str) -> str:
    """Plain text of an item's HTML description, read through ``reading/markup.py``'s tolerant HTML parser."""
    encoded = html.encode("utf-8")
    try:
        read = read_html_events(encoded, max_bytes=len(encoded))
    except MarkupReadError as error:
        raise PressReleaseFeedSourceError(f"{label} item description could not be read as HTML") from error
    text = "".join(event.text for event in read.events if event.kind == "text" and event.text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_pub_date(value: str, *, label: str) -> datetime:
    """Parse an RFC 822 ``pubDate``; see the module docstring for the Senate's ``EST``-in-September quirk."""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise PressReleaseFeedSourceError(f"{label} item pubDate is not a valid RFC 822 date: {value!r}") from error
    if parsed.tzinfo is None:
        raise PressReleaseFeedSourceError(f"{label} item pubDate carries no timezone: {value!r}")
    return parsed


def _read_item(feed: PressReleaseFeed, index: int, element: Element, *, label: str) -> PressRelease:
    def text(tag: str) -> str | None:
        return child_text(element, tag, error_type=PressReleaseFeedSourceError, label=label)

    title, link = text("title"), text("link")
    if title is None or link is None:
        raise PressReleaseFeedSourceError(f"{label} item requires a title and a link")

    guid_element = single_child(element, "guid", error_type=PressReleaseFeedSourceError, label=label)
    guid = guid_is_permalink = None
    if guid_element is not None:
        guid = (guid_element.text or "").strip() or None
        guid_is_permalink = (guid_element.get("isPermaLink") or "true").strip().casefold() != "false"

    description = text("description")
    description_text = _strip_description(description, label=label) if description is not None else None

    pub_date = text("pubDate")
    pub_date_instant = _parse_pub_date(pub_date, label=label) if pub_date is not None else None

    categories = tuple(
        child.text.strip() for child in element if child.tag == "category" and child.text and child.text.strip()
    )

    enclosure = single_child(element, "enclosure", error_type=PressReleaseFeedSourceError, label=label)
    enclosure_url = enclosure_type = None
    enclosure_length: int | None = None
    if enclosure is not None:
        enclosure_url = enclosure.get("url")
        enclosure_type = enclosure.get("type")
        length_raw = enclosure.get("length")
        if length_raw is not None:
            try:
                enclosure_length = int(length_raw)
            except ValueError:
                raise PressReleaseFeedSourceError(
                    f"{label} item enclosure length is not an integer: {length_raw!r}"
                ) from None

    return PressRelease(
        index=index,
        chamber=feed.chamber,
        title=title,
        link=link,
        guid=guid,
        guid_is_permalink=guid_is_permalink,
        description=description,
        description_text=description_text,
        pub_date=pub_date,
        pub_date_instant=pub_date_instant,
        author=text("author"),
        creator=text(DC_CREATOR),
        categories=categories,
        enclosure_url=enclosure_url,
        enclosure_length=enclosure_length,
        enclosure_type=enclosure_type,
    )


def parse_press_release_feed(
    body: bytes, feed: PressReleaseFeed, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> PressReleaseChannel:
    """Read one committee's RSS 2.0 channel whole; every field the publisher sent is kept.

    The channel title and link host must pass ``_check_feed_identity`` before
    any item is read, since the request URL alone cannot prove which channel
    answered.
    """
    if not isinstance(feed, PressReleaseFeed):
        raise TypeError("feed must be a PressReleaseFeed")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_FEED_BYTES:
        raise PressReleaseFeedSourceError("max_bytes must be a positive integer no greater than 64 MiB")
    label = f"{feed.chamber} press-release feed"
    channel, item_elements = read_rss2_channel(
        body, max_bytes=max_bytes, error_type=PressReleaseFeedSourceError, label=label, max_items=DEFAULT_MAX_ITEMS
    )

    def channel_text(tag: str) -> str | None:
        return child_text(channel, tag, error_type=PressReleaseFeedSourceError, label=label)

    title, link = channel_text("title"), channel_text("link")
    _check_feed_identity(feed, title=title, link=link)
    releases = tuple(_read_item(feed, index, element, label=label) for index, element in enumerate(item_elements))
    return PressReleaseChannel(
        title=title,
        link=link,
        description=channel_text("description"),
        language=channel_text("language"),
        copyright=channel_text("copyright"),
        docs=channel_text("docs"),
        last_build_date=channel_text("lastBuildDate"),
        ttl=_read_channel_ttl(channel, label=label),
        skip_days=_read_channel_skip_days(channel, label=label),
        skip_hours=_read_channel_skip_hours(channel, label=label),
        releases=releases,
    )


@dataclass(frozen=True, slots=True)
class PressReleaseBudget:
    max_requests: int
    max_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_bytes, "max_bytes", MAX_FEED_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class PressReleaseAcquisition:
    feed: PressReleaseFeed
    channel: PressReleaseChannel
    capture: CapturedBodyResponse
    request_count: int
    budget: PressReleaseBudget


class PressReleaseAcquirer(SourceAcquirer):
    """Keyless capture of one appropriations committee's RSS 2.0 press-release feed.

    Neither committee site names a credential, but either can still answer
    401/403 (a bot wall, not a rejected key), so this stays a ``keyless``
    acquirer like ``LegislatorsAcquirer`` and ``CboAcquirer`` -- ``named_challenge``
    recasts that refusal as ``PressReleaseFeedRefusedError``.
    """

    def __init__(
        self,
        *,
        budget: PressReleaseBudget,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, PressReleaseBudget):
            raise TypeError("budget must be a PressReleaseBudget")
        self._budget = budget
        super().__init__(
            max_requests=budget.max_requests,
            timeout_seconds=budget.timeout_seconds,
            min_request_interval_seconds=budget.min_request_interval_seconds,
            user_agent="spicy-docs-press-releases/1.0",
            label="appropriations committee press releases",
            error_type=PressReleaseFeedSourceError,
            context_key="press_release_acquisition",
            transport=transport,
            clock=clock,
            keyless=True,
        )

    @property
    def budget(self) -> PressReleaseBudget:
        return self._budget

    def acquire_press_releases(self, feed: PressReleaseFeed) -> PressReleaseAcquisition:
        if not isinstance(feed, PressReleaseFeed):
            raise TypeError("feed must be a PressReleaseFeed")
        with named_challenge(
            feed.url, error_type=PressReleaseFeedRefusedError, context_key="press_release_acquisition"
        ):
            channel, capture = self.capture_validated(
                feed.url,
                media_types=MEDIA_TYPES,
                parse=lambda response, limit: parse_press_release_feed(response.body, feed, max_bytes=limit),
                max_bytes=self.budget.max_bytes,
                unavailable=PressReleaseFeedUnavailableError,
                context={"operation": "press-releases", "chamber": feed.chamber, "url": feed.url},
            )
        return PressReleaseAcquisition(feed, channel, capture, self.request_count, self.budget)
