"""Appropriations committee press releases: two RSS 2.0 feeds, read whole, with a content identity proof.

``tests/fixtures/press_releases/README.md`` documents where the two pinned
feed bodies came from. Synthetic bodies below isolate one field or one
refusal at a time; the pinned fixtures prove the real publisher shapes,
including the fields BillTrax drops (`dc:creator`, plain `author`, the
Senate's missing `description`, and the channel-level fields).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.press_releases import (
    DEFAULT_MAX_BYTES,
    MAX_FEED_BYTES,
    PRESS_RELEASE_FEEDS,
    PressReleaseAcquirer,
    PressReleaseBudget,
    PressReleaseFeed,
    PressReleaseFeedRefusedError,
    PressReleaseFeedSourceError,
    PressReleaseFeedUnavailableError,
    parse_press_release_feed,
    press_release_feed_locator,
)
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "press_releases"
HOUSE = (FIXTURES / "house-rss.xml").read_bytes()
SENATE = (FIXTURES / "senate-rss-press.xml").read_bytes()
HOUSE_FEED = PRESS_RELEASE_FEEDS["house"]
SENATE_FEED = PRESS_RELEASE_FEEDS["senate"]
BUDGET = PressReleaseBudget(3, DEFAULT_MAX_BYTES, 7, 0)

HOUSE_MINIMAL = (
    b'<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>'
    b"<title>House Committee on Appropriations - Republicans</title>"
    b"<link>http://appropriations.house.gov/</link><description/><language>en</language>"
    b"<item><title>A</title><link>http://appropriations.house.gov/news/a</link>"
    b"<description>&lt;span&gt;Hello &lt;b&gt;World&lt;/b&gt;&lt;/span&gt;</description>"
    b"<pubDate>Wed, 16 Sep 2026 14:04:21 +0000</pubDate><dc:creator>staff@mail.house.gov</dc:creator>"
    b'<guid isPermaLink="false">14637 at http://appropriations.house.gov</guid></item>'
    b"</channel></rss>"
)
# The Senate's byte-identical default channel (measured 2026-09-19): title lacks "Press".
SENATE_DEFAULT_MINIMAL = (
    b'<?xml version="1.0"?><rss version="2.0"><channel>'
    b"<title>United States Senate Committee on Appropriations Feed</title>"
    b"<link>https://www.appropriations.senate.gov/rss/feeds/</link>"
    b"<lastBuildDate>Sat, 19 Sep 2026 05:05:30 EST</lastBuildDate>"
    b"<item><title>B</title><link>http://www.appropriations.senate.gov/news/b</link>"
    b"<author>webmaster@appropriations.senate.gov</author>"
    b"<pubDate>Wed, 16 Sep 2026 11:11:00 EST</pubDate>"
    b"<guid>http://www.appropriations.senate.gov/news/b</guid></item>"
    b"</channel></rss>"
)
SENATE_MINIMAL = SENATE_DEFAULT_MINIMAL.replace(b"Appropriations Feed", b"Appropriations Press Feed")


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


# --- parsing the pinned publisher bodies ---------------------------------------------


def test_house_feed_matches_the_2026_09_19_measurement():
    channel = parse_press_release_feed(HOUSE, HOUSE_FEED)
    assert channel.title == "House Committee on Appropriations - Republicans"
    assert channel.link == "http://appropriations.house.gov/"
    assert channel.last_build_date is None  # House's channel never states one (measured)
    assert len(channel.releases) == 10
    first = channel.releases[0]
    assert first.title.startswith("Diaz-Balart Remarks at Budget Hearing")
    assert first.link.startswith("http://appropriations.house.gov/news/remarks/")
    assert first.guid == "14637 at http://appropriations.house.gov" and first.guid_is_permalink is False
    assert first.creator == "Tiffany.Osborn@mail.house.gov" and first.author is None
    assert first.description is not None and "<span>" in first.description
    assert first.description_text and "<" not in first.description_text
    assert first.pub_date == "Wed, 16 Sep 2026 14:04:21 +0000"
    assert first.pub_date_instant.isoformat() == "2026-09-16T14:04:21+00:00"
    assert first.categories == () and first.enclosure_url is None  # not carried by this feed


def test_senate_feed_matches_the_2026_09_19_measurement():
    channel = parse_press_release_feed(SENATE, SENATE_FEED)
    assert channel.title == "United States Senate Committee on Appropriations Press Feed"
    assert channel.link == "https://www.appropriations.senate.gov/rss/feeds/"
    assert channel.last_build_date and "EST" in channel.last_build_date
    assert len(channel.releases) == 15
    first = channel.releases[0]
    assert first.title.startswith("Murray, Kaptur Demand Energy Department")
    assert first.guid == first.link and first.guid_is_permalink is True  # no isPermaLink attribute: defaults true
    assert first.author == "webmaster@appropriations.senate.gov" and first.creator is None
    assert first.description is None and first.description_text is None  # Senate carries no <description>
    assert first.pub_date == "Wed, 16 Sep 2026 11:11:00 EST"
    assert first.categories == () and first.enclosure_url is None


def test_press_release_feed_locator_reads_the_table():
    assert press_release_feed_locator("house") == HOUSE_FEED.url
    assert press_release_feed_locator("senate") == SENATE_FEED.url
    with pytest.raises(PressReleaseFeedSourceError, match="no press-release feed"):
        press_release_feed_locator("both")  # type: ignore[arg-type]


# --- the identity check: outcome-based, not URL-based --------------------------------


def test_senate_default_feed_fallback_is_refused_even_though_the_url_matches():
    """The Senate's own byte-identical default channel (measured) must fail this check."""
    with pytest.raises(PressReleaseFeedSourceError, match="does not confirm"):
        parse_press_release_feed(SENATE_DEFAULT_MINIMAL, SENATE_FEED)


def test_senate_press_channel_passes_identity():
    channel = parse_press_release_feed(SENATE_MINIMAL, SENATE_FEED)
    assert channel.title and "Press" in channel.title


def test_house_feed_body_under_the_senate_feed_config_is_refused():
    with pytest.raises(PressReleaseFeedSourceError, match="does not confirm"):
        parse_press_release_feed(HOUSE_MINIMAL, SENATE_FEED)


def test_right_title_wrong_host_link_still_refuses():
    """The title check alone is not enough -- the link's host must also name the requested committee."""
    wrong_host = SENATE_MINIMAL.replace(
        b"https://www.appropriations.senate.gov/rss/feeds/", b"https://appropriations.house.gov/rss/feeds/"
    )
    with pytest.raises(PressReleaseFeedSourceError, match="does not name"):
        parse_press_release_feed(wrong_host, SENATE_FEED)


def test_a_generic_unrelated_channel_fails_the_house_identity_check():
    generic = HOUSE_MINIMAL.replace(b"House Committee on Appropriations - Republicans", b"Some Other Committee")
    with pytest.raises(PressReleaseFeedSourceError, match="does not confirm"):
        parse_press_release_feed(generic, HOUSE_FEED)


# --- pubDate, including the Senate's EST-in-September quirk ---------------------------


def test_senate_est_pubdate_parses_as_a_fixed_utc_minus_five_offset():
    channel = parse_press_release_feed(SENATE_MINIMAL, SENATE_FEED)
    instant = channel.releases[0].pub_date_instant
    assert instant.utcoffset() == timedelta(hours=-5)
    assert instant.astimezone(tz=None).utcoffset() is not None  # still an aware datetime


def test_house_offset_pubdate_parses_exactly():
    channel = parse_press_release_feed(HOUSE_MINIMAL, HOUSE_FEED)
    assert channel.releases[0].pub_date_instant.utcoffset() == timedelta(0)


def test_unparseable_pubdate_refuses():
    bad = HOUSE_MINIMAL.replace(b"Wed, 16 Sep 2026 14:04:21 +0000", b"not a date")
    with pytest.raises(PressReleaseFeedSourceError, match="not a valid RFC 822 date"):
        parse_press_release_feed(bad, HOUSE_FEED)


# --- description stripping, guid, category, enclosure ---------------------------------


def test_description_is_kept_whole_and_also_stripped_to_plain_text():
    channel = parse_press_release_feed(HOUSE_MINIMAL, HOUSE_FEED)
    item = channel.releases[0]
    assert item.description == "<span>Hello <b>World</b></span>"
    assert item.description_text == "Hello World"


def test_guid_with_no_element_at_all_is_none_not_defaulted():
    no_guid = HOUSE_MINIMAL.replace(b'<guid isPermaLink="false">14637 at http://appropriations.house.gov</guid>', b"")
    channel = parse_press_release_feed(no_guid, HOUSE_FEED)
    assert channel.releases[0].guid is None and channel.releases[0].guid_is_permalink is None


def test_category_and_enclosure_are_kept_when_a_feed_carries_them():
    with_extras = HOUSE_MINIMAL.replace(
        b"</item>",
        b"<category>Budget</category><category>Hearings</category>"
        b'<enclosure url="http://x/a.mp3" length="12345" type="audio/mpeg"/></item>',
    )
    item = parse_press_release_feed(with_extras, HOUSE_FEED).releases[0]
    assert item.categories == ("Budget", "Hearings")
    assert item.enclosure_url == "http://x/a.mp3"
    assert item.enclosure_length == 12345
    assert item.enclosure_type == "audio/mpeg"


def test_enclosure_with_a_non_integer_length_refuses():
    bad = HOUSE_MINIMAL.replace(b"</item>", b'<enclosure url="http://x/a.mp3" length="big"/></item>')
    with pytest.raises(PressReleaseFeedSourceError, match="enclosure length"):
        parse_press_release_feed(bad, HOUSE_FEED)


def test_item_without_title_or_link_refuses():
    for original in (b"<title>A</title>", b"<link>http://appropriations.house.gov/news/a</link>"):
        missing = HOUSE_MINIMAL.replace(original, b"")
        with pytest.raises(PressReleaseFeedSourceError, match="title and a link"):
            parse_press_release_feed(missing, HOUSE_FEED)


# --- shape and bound refusals ----------------------------------------------------------


@pytest.mark.parametrize(
    "body,message",
    [
        (HOUSE_MINIMAL.replace(b'version="2.0"', b'version="1.0"'), "RSS 2.0"),
        (HOUSE_MINIMAL.replace(b"<channel>", b"<channel></channel><channel>"), "exactly one channel"),
        (b"", "nonempty"),
        (b"<html><body>blocked</body></html>", "RSS 2.0"),
    ],
)
def test_shape_refusals_name_the_failed_check(body, message):
    with pytest.raises(PressReleaseFeedSourceError, match=message):
        parse_press_release_feed(body, HOUSE_FEED)


@pytest.mark.parametrize("max_bytes", [0, True, MAX_FEED_BYTES + 1])
def test_bounds_are_explicit(max_bytes):
    with pytest.raises(PressReleaseFeedSourceError, match="max_bytes"):
        parse_press_release_feed(HOUSE_MINIMAL, HOUSE_FEED, max_bytes=max_bytes)


def test_a_call_may_narrow_the_byte_allowance():
    with pytest.raises(PressReleaseFeedSourceError, match="max_bytes"):
        parse_press_release_feed(HOUSE_MINIMAL, HOUSE_FEED, max_bytes=len(HOUSE_MINIMAL) - 1)


def test_feed_argument_must_be_a_press_release_feed():
    with pytest.raises(TypeError):
        parse_press_release_feed(HOUSE_MINIMAL, "house")  # type: ignore[arg-type]


# --- acquisition, mocked -------------------------------------------------------------


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def response(body=HOUSE_MINIMAL, status=200, *, content_type="application/rss+xml; charset=utf-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


def test_acquirer_captures_exact_house_bytes_keyless():
    transport = Transport(response(HOUSE))
    with PressReleaseAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_press_releases(HOUSE_FEED)
    assert result.capture.body == HOUSE and result.capture.requested_url == HOUSE_FEED.url
    assert len(result.channel.releases) == 10 and result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert "x-api-key" not in transport.calls[0].headers


def test_acquirer_captures_exact_senate_bytes_keyless():
    transport = Transport(response(SENATE, content_type="text/xml;charset=UTF-8"))
    with PressReleaseAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire_press_releases(SENATE_FEED)
    assert result.capture.body == SENATE and result.capture.requested_url == SENATE_FEED.url
    assert len(result.channel.releases) == 15


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(b"gone", 404, content_type="text/html"), PressReleaseFeedUnavailableError, "HTTP 404"),
        (response(b"", 410), PressReleaseFeedUnavailableError, "HTTP 410"),
        (
            response(b"<html>Access denied</html>", content_type="text/html"),
            PressReleaseFeedSourceError,
            "Content-Type",
        ),
        (response(SENATE_DEFAULT_MINIMAL, content_type="text/xml"), PressReleaseFeedSourceError, "does not confirm"),
    ],
)
def test_wrong_shape_or_unavailable_feed_never_succeeds(answer, error, message):
    transport = Transport(answer)
    with (
        PressReleaseAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(error, match=message) as raised,
    ):
        source.acquire_press_releases(SENATE_FEED)
    assert raised.value.press_release_acquisition["chamber"] == "senate"
    assert len(transport.calls) == 1


def test_a_malformed_200_retains_its_exact_bytes_as_refused_evidence():
    transport = Transport(response(SENATE_DEFAULT_MINIMAL, content_type="text/xml"))
    with (
        PressReleaseAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(PressReleaseFeedSourceError) as raised,
    ):
        source.acquire_press_releases(SENATE_FEED)
    assert raised.value.refused_response.response_bytes == SENATE_DEFAULT_MINIMAL


@pytest.mark.parametrize("status", [401, 403])
def test_a_public_access_refusal_on_a_keyless_route_is_named_not_a_credential_refusal(status):
    body = b"rate limited"
    transport = Transport(response(body, status, content_type="text/plain"))
    with (
        PressReleaseAcquirer(budget=BUDGET, transport=transport) as source,
        pytest.raises(PressReleaseFeedRefusedError) as raised,
    ):
        source.acquire_press_releases(HOUSE_FEED)
    assert isinstance(raised.value, PressReleaseFeedSourceError)
    assert not isinstance(raised.value, CredentialRefusedError)
    assert raised.value.url == HOUSE_FEED.url
    refusal = raised.value.refused_response
    assert refusal.response_bytes == body and refusal.request_key == HOUSE_FEED.url


def test_acquire_press_releases_requires_a_press_release_feed():
    with (
        PressReleaseAcquirer(budget=BUDGET, transport=Transport()) as source,
        pytest.raises(TypeError),
    ):
        source.acquire_press_releases("house")  # type: ignore[arg-type]


def test_budget_and_client_configuration_are_explicit():
    for fields in ({"max_requests": 0}, {"max_bytes": MAX_FEED_BYTES + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            PressReleaseBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        PressReleaseAcquirer(budget=(3, 4096, 7, 0), transport=Transport())


def test_feed_table_and_dataclass_are_frozen():
    with pytest.raises(AttributeError):
        HOUSE_FEED.url = "https://example.com"  # type: ignore[misc]
    assert isinstance(PRESS_RELEASE_FEEDS["house"], PressReleaseFeed)


# --- live, keyless, bounded to one request per feed -----------------------------------


@pytest.mark.integration
def test_live_house_feed_meets_the_2026_09_19_measured_floor():
    budget = PressReleaseBudget(2, DEFAULT_MAX_BYTES, 30, 1.0)
    with PressReleaseAcquirer(budget=budget) as source:
        result = source.acquire_press_releases(HOUSE_FEED)
    assert result.channel.title and "Appropriations" in result.channel.title
    assert len(result.channel.releases) >= 1
    assert result.capture.sha256.startswith("sha256:")
    assert result.request_count == 1


@pytest.mark.integration
def test_live_senate_feed_meets_the_2026_09_19_measured_floor():
    budget = PressReleaseBudget(2, DEFAULT_MAX_BYTES, 30, 1.0)
    with PressReleaseAcquirer(budget=budget) as source:
        result = source.acquire_press_releases(SENATE_FEED)
    assert result.channel.title and "Press" in result.channel.title
    assert len(result.channel.releases) >= 1
    assert result.capture.sha256.startswith("sha256:")
    assert result.request_count == 1
