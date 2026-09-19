# Appropriations committee press-release feed fixtures

Complete, unchanged publisher RSS bodies for the two canonical feeds, captured
keyless on 2026-09-19 with `Accept-Encoding: identity`. These U.S. government
committee press releases are public domain. Offline tests establish behavior
for these shapes; they do not establish continuing live availability or that
either publisher's item set, channel fields or `?type=` behavior will hold.

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `house-rss.xml` | [`appropriations.house.gov/rss.xml`](https://appropriations.house.gov/rss.xml), keyless | 13,808 | `66ff7ac0573b6b3330f001557d27696a6f6949a2bec9b4c190c589d3e8b38c3f` |
| `senate-rss-press.xml` | [`www.appropriations.senate.gov/rss/feeds/?type=press`](https://www.appropriations.senate.gov/rss/feeds/?type=press), keyless | 9,011 | `b5510c06de6f5c7117205fcfd4a86846f3622a9ac52aaaa0ae21a6fecd0c9bf3` |

No fixture was reduced, truncated or reformatted; both digests match the
independent measurement in
`docs/research/billtrax-raw-data-2026-09-19.json` (`sources.pressReleaseFeeds
.publisher-house-rss-xml.sha256` and `.publisher-senate-press.sha256`) taken
the same day, so the feeds were unchanged between that measurement and this
capture. Neither route takes a credential.

House's channel carries `title`, `link`, `description`, `language` only — no
`lastBuildDate`. Its ten items carry `title`, `link`, `description`, `pubDate`,
`dc:creator` and a `guid` with `isPermaLink="false"` whose value is not a URL
(`"14637 at http://appropriations.house.gov"`). Senate's channel additionally
carries `copyright`, `docs`, `lastBuildDate`, `ttl`, `skipDays`, `skipHours`.
Its fifteen items carry `title`, `link`, `author`, `pubDate` and a `guid` with
no attributes (so `isPermaLink` defaults to `true` per RSS 2.0) whose value
equals `<link>` — and no `<description>` at all. Senate `pubDate` values are
spelled `EST` even though the capture was taken in September, when real
Eastern time is `EDT`; see `docs/sources/press-releases.md`.

See `docs/research/billtrax-raw-data-2026-09-19.md` §4 for the four dead
BillTrax feed-URL spellings this pair replaces, and for the measurement that
an unrecognized Senate `?type=` answers 200 with a byte-identical default
channel rather than failing.
