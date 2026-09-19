# Appropriations committee press releases

Capture each chamber's own RSS 2.0 press-release feed whole: every channel
and item field the publisher sends, not a truncated excerpt. This is the
source BillTrax's `press-releases.ts` (`pollFeeds`) and
`sync-press-releases.ts` are retired in favor of; both are keyless GET routes,
and both feeds are small enough to read in one bounded request each.

## The four BillTrax spellings are dead; two canonical feeds replace them

Measured 2026-09-19 (`docs/research/billtrax-raw-data-2026-09-19.md` §4, with
captured bodies in the sidecar `.json` beside it):

| Spelling | Where it lived in BillTrax | Answer | Content type | Bytes | Verdict |
| --- | --- | --- | --- | ---: | --- |
| `appropriations.house.gov/news/press-releases.rss` | `press-releases.ts:6` | **404** | `text/html` | — | gone |
| `appropriations.house.gov/rss/` | `sync-press-releases.ts:20` | **404** | `text/html` | — | gone |
| `www.appropriations.senate.gov/news/press-releases.rss` | `press-releases.ts:10` | **410 Gone** | `text/html` | — | gone; the publisher's own statement that this address is permanently retired |
| `www.appropriations.senate.gov/rss/` | `sync-press-releases.ts:24` | **200** | `text/html` | 606 | a ColdFusion error page — a 200 that is not the requested object, the same shape `sources/govinfo/error_page.py` already names for GovInfo |
| `appropriations.house.gov/rss.xml` | (the site's own link) | 200 | `application/rss+xml` | 13,808 | **canonical, House** |
| `www.appropriations.senate.gov/rss/feeds/?type=press` | (the CMS route) | 200 | `text/xml` | 9,011 | **canonical, Senate** |

Neither publisher declares a feed with `<link rel="alternate">`. The House
URL is the only RSS-like `href` on `appropriations.house.gov/` and its
`/news` page; the Senate declares nothing at all, and its route was found by
probing the CMS's known shape. Both canonical feeds are RSS 2.0 with no
default namespace (`<rss version="2.0">`, no `xmlns`); neither publisher has
ever been observed serving Atom, so this source never looks for one — the
single-item-list collapse that crashes BillTrax's `fast-xml-parser` reader
(`item` becomes an object instead of an array when a feed has exactly one
item, silently swallowed by the `catch {}` in `pollFeeds`) does not reproduce
here, because `xml.etree` never collapses a one-item list to a non-list.

## The request URL never proves the response

An unrecognized Senate `?type=` answers 200 with a **byte-identical default
channel** instead of failing: `?type=majority`, `?type=minority` and
`?type=nonexistenttype` all measured `sha256:999e9250…`, titled "United
States Senate Committee on Appropriations Feed". `?type=press` answers a
distinct, correctly-typed channel titled "… Committee on Appropriations
**Press** Feed" — a title the default channel's own text fails to contain.
So `acquire_press_releases` never trusts the request URL alone; it checks the
response body itself, against each feed's own `PressReleaseFeed` row:

- **`identity_title_contains`** — substrings the channel `<title>` must all
  contain. House: `("Committee on Appropriations",)`. Senate:
  `("Committee on Appropriations", "Press")` — the second substring is the
  one the byte-identical default channel fails, which is the whole point: if
  the Senate ever silently stops honoring `?type=press`, this check catches
  it as a refusal, not as a feed quietly full of the wrong content.
- **`identity_link_host`** — the hostname the channel `<link>` must name
  (`appropriations.house.gov` / `www.appropriations.senate.gov`), checked
  independently of the title so a same-host proxy or a plausible-sounding
  title from elsewhere cannot pass alone.

Both checks must pass or the whole capture is refused
(`PressReleaseFeedSourceError`), with the exact bytes retained as evidence —
the "outcome, not the URL" is what proves identity, the same discipline
`gao/rss.py`'s product-link check and `gao-files.md`'s PDF-magic check use.

## What each publisher's feed carries

Everything the feed states is kept; nothing is truncated to an excerpt.
Measured against the pinned captures in
[`tests/fixtures/press_releases/`](../../tests/fixtures/press_releases/README.md):

| Channel field | `PressReleaseChannel` attribute | House | Senate |
| --- | --- | --- | --- |
| `title` | `.title` | yes | yes |
| `link` | `.link` | yes | yes |
| `description` | `.description` | yes (empty element → `None`) | yes |
| `language` | `.language` | yes (`en`) | yes (`en-us`) |
| `copyright` | `.copyright` | — | yes |
| `docs` | `.docs` | — | yes |
| `lastBuildDate` | `.last_build_date` | **never stated** | yes (`EST`, see below) |
| `ttl` | `.ttl` (parsed `int`) | — | yes (`1`) |
| `skipDays` | `.skip_days` (tuple of `<day>` text) | — | yes (`("Saturday", "Sunday")`) |
| `skipHours` | `.skip_hours` (tuple of `<hour>` as `int`) | — | yes (`(1, 2, 3, 4, 5)`) |

`ttl`/`skipDays`/`skipHours` are the Senate's own polling contract — how
often and when it wants a reader to re-fetch — and BillTrax dropped all
three along with `lastBuildDate`; here they land on the channel record
whole, not just noted as absent.

| Item field | `PressRelease` attribute | House (10 items) | Senate (15 items) |
| --- | --- | --- | --- |
| `title` | `.title` | yes | yes |
| `link` | `.link` | yes | yes |
| `description` | `.description` (raw) / `.description_text` (stripped) | yes, HTML | **never stated** (`None`) |
| `author` | `.author` | — | yes, a shared `webmaster@appropriations.senate.gov` mailbox, not per-article |
| `dc:creator` | `.creator` | yes, a named staffer's `mail.house.gov` address | — |
| `pubDate` | `.pub_date` (as spelled) / `.pub_date_instant` (parsed) | yes, `+0000` offset | yes, spelled `EST` (see below) |
| `guid` | `.guid` / `.guid_is_permalink` | yes, `isPermaLink="false"`, value **not a URL** (`"14637 at http://appropriations.house.gov"`) | yes, no attributes (`isPermaLink` defaults `true` per RSS 2.0), value **equal to `<link>`** |
| `category` | `.categories` (tuple) | not observed | not observed |
| `enclosure` | `.enclosure_url` / `.enclosure_length` / `.enclosure_type` | not observed | not observed |

`.categories` and the three `.enclosure_*` fields are `()`/`None` on both
measured feeds today, populated the day either publisher adds one, since the
reader (`reading/rss.py`) is a generic RSS 2.0 item reader, not one fit only
to today's two bodies.

## The Senate spells its zone `EST` in September

The Senate's `pubDate` values read `EST` (for example `Wed, 16 Sep 2026
11:11:00 EST`), captured in September, when the real Eastern zone is `EDT`.
`pub_date_instant` is parsed with `email.utils.parsedate_to_datetime`, which
applies RFC 822's fixed abbreviation table — `EST` is always UTC-5, never
DST-aware — so a Senate item's parsed instant can read up to an hour earlier
than the wall-clock Eastern time the publisher meant. `pub_date` keeps the
exact string the publisher spelled; `pub_date_instant` is the literal RFC 822
reading, not a corrected one. This is the publisher's own quirk, recorded,
not silently normalized away.

## Use the route

Install the `acquisition` extra. No key, no env variable.

```python
from spicy_docs.sources.congress.press_releases import (
    PRESS_RELEASE_FEEDS,
    PressReleaseAcquirer,
    PressReleaseBudget,
)

budget = PressReleaseBudget(max_requests=2, max_bytes=4 * 1024**2, timeout_seconds=30, min_request_interval_seconds=1.0)
with PressReleaseAcquirer(budget=budget) as source:
    house = source.acquire_press_releases(PRESS_RELEASE_FEEDS["house"])
    senate = source.acquire_press_releases(PRESS_RELEASE_FEEDS["senate"])

print(house.channel.title, len(house.channel.releases))
first = senate.channel.releases[0]
print(first.title, first.pub_date, first.pub_date_instant, first.description_text)
```

`result.capture` carries the exact bytes, both URLs, status, observed time
and SHA-256 (`sha256:...`); retain `capture.body` as the pin.
`result.channel.releases` is a reading of those bytes as frozen `PressRelease`
records, in feed order.

## Diagnose a refused response

Every failure keeps its exact bytes as evidence on `refused_response`, the
same discipline as every other keyless source in this package:

| Condition | Result |
| --- | --- |
| 404 or 410 | `PressReleaseFeedUnavailableError`, capture attached |
| 401 or 403 | `PressReleaseFeedRefusedError` — a bot wall, not a rejected key; there is no credential here to reject (`named_challenge`, like `LegislatorsAcquirer` and `CboAcquirer`) |
| Content-Type outside `application/rss+xml`, `application/xml`, `text/xml` | `PressReleaseFeedSourceError`, "Content-Type differs" |
| Not RSS 2.0, not exactly one `<channel>`, malformed XML, or a DOCTYPE | `PressReleaseFeedSourceError` naming the failed check |
| Channel title/link fails the identity check (§ above) | `PressReleaseFeedSourceError`, "does not confirm" / "does not name" |
| An item lacks `title` or `link` | `PressReleaseFeedSourceError`, "requires a title and a link" |
| `pubDate` present but not a valid RFC 822 date | `PressReleaseFeedSourceError`, "not a valid RFC 822 date" |

## Decision

See ["Appropriations press releases: two canonical feeds, identity from the
channel body"](../decisions.md#appropriations-press-releases-two-canonical-feeds-identity-from-the-channel-body)
in `docs/decisions.md`.

## Change and check

Owner: [`press_releases.py`](../../src/spicy_docs/sources/congress/press_releases.py),
built on the shared RSS 2.0 reader in
[`reading/rss.py`](../../src/spicy_docs/reading/rss.py) (also used by
[`gao/rss.py`](../../src/spicy_docs/sources/gao/rss.py)).

```sh
uv run --frozen pytest -q tests/test_congress_press_releases.py tests/test_gao_rss.py
```

The two `@pytest.mark.integration` tests make one live, keyless request per
feed and are excluded by default (`-m 'not integration and not httpfs'`); run
them explicitly with
`uv run --frozen pytest -q -m integration tests/test_congress_press_releases.py`
before trusting a re-pin. Pinned bytes and their provenance are in
[`tests/fixtures/press_releases/README.md`](../../tests/fixtures/press_releases/README.md).
