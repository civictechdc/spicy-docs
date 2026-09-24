# Walk publisher list pages

Give SpicyDocs one explicit list query. It walks the publisher's continuations
page by page, keeps every page's exact bytes, checks the publisher's declared
count against what it observed, and refuses to end early or inconsistently.
Callers own selection, retention and recovery. A list page is an observation
of that query on that day, never a frozen inventory, and a declared count of
zero never establishes absence.

| Route | Selection | Rows | Credential |
| --- | --- | --- | --- |
| Congress.gov bills | Optional Congress and bill type; optional `fromDateTime`/`toDateTime` window | `bills` | api.data.gov key |
| Congress.gov CRS reports | Optional update window | `CRSReports` | api.data.gov key |
| GovInfo published packages | Issued-date window and collection codes; optional `modifiedSince` | `packages` | api.data.gov key |
| GovInfo collection changes | Collection code and `lastModified` start, optional end | `packages` | api.data.gov key |
| GovInfo package granules | Package identifier | `granules` | api.data.gov key |
| GAO reports feed | None; about 25 recent products | RSS items | none |
| LDA lobbying filings | Optional filing year and posted-date window, ordered by `dt_posted` | `results` | optional LDA token |
| CourtListener search | `type=r` dockets or `type=o` opinion clusters; optional filed window, court, nature of suit, query | `results` | optional CourtListener token |
| SAM.gov entities | Optional registration status and registration-date window narrow enough for 10,000 records | `entityData` | SAM.gov-issued key |
| USAspending recipients | POST body: limit, page, sort, order, award type, optional keyword | `results` | none |
| FCC ECFS proceedings and filings | Explicit date window, both dates included, limit, offset | `proceeding` / `filing` | api.data.gov key |

## Table-driven Congress.gov routes

Every Congress.gov list route, including `bill` and `crsreport`, is one entry
on a single `CongressListRoute` table in
[`sources/congress/listing.py`](../../src/spicy_docs/sources/congress/listing.py)
`LIST_ROUTES`, built by one path builder (`list_route_url`) and walked by one
reader method (`CongressListingReader.records(route, url)`). (Named
`CongressListRoute`, not `ListRoute`, because `cli/list_pages.py` already
defines a different `ListRoute`.) A route's `path` names its placeholders
(`{congress}`, `{chamber}`, `{code}`, `{type}`, `{number}`, `{session}`,
`{eventId}`, `{volume}`, `{issue}`, `{commtype}`, `{law_type}`,
`{system_code}`, `{bioguide_id}`); `optional_params` names the
trailing ones a caller may omit — `bill` may omit both `congress` and
`bill_type`, but only in that order, so a bill type without a Congress
refuses; `law` may likewise omit `law_type`, since a bare `law/{congress}`
already enumerates both public and private laws for that Congress.
`bill_list_url` and `crs_report_list_url` keep their original names,
arguments and behavior as thin aliases over the same table and builder, so
existing callers are unaffected — including refusing a literal `sort=None`,
which `list_route_url`'s optional `sort` allows but these two named builders
never have.

Sort support is measured, not assumed, for every route: a 2026-09-19 pass over
the [legislative data map](../research/legislative-data-map-2026-09-18.md)
Table A found only `bill`, `amendment`, `summaries`, `committee-report` and
`committee` reorder on `sort=updateDate`; a direct probe the same day
(`limit=1`, `sort=updateDate desc` vs `asc`, comparing the first record) found
`committee-bills` and `bill-actions` both answer the identical first record
either way. `list_route_url` refuses a `sort` argument on every route that
ignores it instead of sending one the publisher would silently ignore.
`crs_report_list_url` is the one deliberate exception: it predates the
measurement and already sent `sort` unconditionally, so it keeps doing that
rather than newly refuse a call that has always worked — `list_route_url`
still refuses `sort` on `LIST_ROUTES["crsreport"]` for callers who want that.

Date-window support (`window_honored`) got the same direct probe applied to
`fromDateTime`: a one-day-old window cut `committee-bills`' declared count
from 41,822 to 9 (honored) but left `bill-actions`' declared count at 59
either way (ignored). Every other route defaults to `window_honored=True` — a
carried-forward assumption from `bill`/`crsreport`'s original, always-accepted
contract, not a measurement — and `list_route_url` refuses `from_datetime`/
`to_datetime` on a route where `window_honored` is `False`, the same way it
refuses `sort`.

On `amendment` both bounds are exclusive: a record stamped exactly at
`fromDateTime` or `toDateTime` is left out (measured 2026-09-23; other routes
are unmeasured). Spell a window of whole UTC days with
`utc_day_window(first, last)`, which opens one second before `first` and
closes at the midnight after `last`; its docstring holds the measurement and
receipt. `crsreport` returned nothing even for a one-second window around its
own printed `updateDate`, so its window reads some other field. On a route
whose rows print a date only (`bill`), inclusive bounds would make consecutive
windows overlap on their boundary seconds, deduplicated by identity, never
leave a gap.

| Route | Path | Records key | Sort honored | Window honored | Fixture |
| --- | --- | --- | --- | --- | --- |
| `bill` | `bill/{congress}/{type}` | `bills` | yes | yes (default) | `congress-bill-list.json` |
| `crsreport` | `crsreport` | `CRSReports` | no (legacy builder still sends it) | yes (default) | `congress-crsreport-list.json` |
| `amendment` | `amendment/{congress}` | `amendments` | yes | yes (measured 2026-09-23) | `congress-amendment-list.json` |
| `committee-bills` | `committee/{chamber}/{code}/bills` | `("committee-bills", "bills")` (nested; see below) | no (measured) | yes (measured) | `congress-committee-bills-list.json` |
| `bill-actions` | `bill/{congress}/{type}/{number}/actions` | `actions` | no (measured) | no (measured) | `congress-bill-actions-list.json` |
| `nomination` | `nomination/{congress}` | `nominations` | no | yes (default) | `congress-nomination-list.json` |
| `hearing` | `hearing/{congress}` | `hearings` | no | yes (default) | `congress-hearing-list.json` |
| `hearing-detail` | `hearing/{congress}/{chamber}/{number}` | `hearing` (one record, a bare object) | no (n/a) | no (n/a) | `congress-hearing-detail.json` |
| `committee-report` | `committee-report/{congress}` | `reports` | yes | yes (default) | `congress-committee-report-list.json` |
| `house-communication` | `house-communication/{congress}` | `houseCommunications` | no | yes (default) | `congress-house-communication-list.json` |
| `house-vote` | `house-vote/{congress}/{session}` | `houseRollCallVotes` | no (measured) | yes (default) | `congress-house-vote-list.json` |
| `committee-meeting` | `committee-meeting/{congress}/{chamber}` | `committeeMeetings` | no (measured) | yes (measured) | `congress-committee-meeting-list.json` |
| `committee-meeting-detail` | `committee-meeting/{congress}/{chamber}/{eventId}` | `committeeMeeting` (one record) | no (structural) | no (structural) | `congress-committee-meeting-detail.json` |
| `treaty` | `treaty/{congress}` | `treaties` | no (measured) | yes (measured) | `congress-treaty-list.json` |
| `treaty-detail` | `treaty/{congress}/{number}` | `treaty` (one record, nested in an array; see below) | no (structural) | no (structural) | `congress-treaty-detail.json` |
| `daily-congressional-record` | `daily-congressional-record/{volume}` | `dailyCongressionalRecord` | no (measured) | no (measured) | `congress-daily-congressional-record-list.json` |
| `daily-congressional-record-detail` | `daily-congressional-record/{volume}/{issue}` | `issue` (one record) | no (structural) | no (structural) | `congress-daily-congressional-record-detail.json` |
| `house-communication-detail` | `house-communication/{congress}/{commtype}/{number}` | `houseCommunication` (one record) | no (structural) | no (structural) | `congress-house-communication-detail.json` |
| `senate-communication` | `senate-communication/{congress}` | `senateCommunications` | no (measured) | no (measured) | `congress-senate-communication-list.json` |
| `senate-communication-detail` | `senate-communication/{congress}/{commtype}/{number}` | `senateCommunication` (one record) | no (structural) | no (structural) | `congress-senate-communication-detail.json` |
| `house-requirement` | `house-requirement` | `houseRequirements` | no (measured) | yes (default) | `congress-house-requirement-list.json` |
| `house-requirement-detail` | `house-requirement/{number}` | `houseRequirement` (one record) | no (structural) | no (structural) | `congress-house-requirement-detail.json` |
| `house-requirement-communications` | `house-requirement/{number}/matching-communications` | `matchingCommunications` | no (measured) | yes (default) | `congress-house-requirement-communications.json` |
| `law` | `law/{congress}/{law_type}` | `bills` | no | yes (default) | `congress-law-list.json` |
| `law-detail` | `law/{congress}/{law_type}/{number}` | `bill` (single record; see below) | no (structural) | no (structural) | `congress-law-detail.json` |
| `committee` | `committee/{congress}` | `committees` | yes | yes (default) | `congress-committee-list.json` |
| `committee-detail` | `committee/{chamber}/{system_code}` | `committee` (single record; see below) | no (structural) | no (structural) | `congress-committee-detail.json` |
| `member` | `member` | `members` | no | yes (default) | `congress-member-list.json` |
| `member-congress` | `member/congress/{congress}` | `members` | no (measured) | yes (default) | `congress-member-congress-list.json` |
| `member-detail` | `member/{bioguide_id}` | `member` (single record; see below) | no (structural) | no (structural) | `congress-member-detail.json` |
| `committee-print` | `committee-print/{congress}` | `committeePrints` | no | yes (default) | `congress-committee-print-list.json` |
| `committee-print-detail` | `committee-print/{congress}/{chamber}/{number}` | `committeePrint` (singular; a one-item array) | no (structural) | no (structural) | `congress-committee-print-detail.json` |

`law-detail`, `committee-detail` and `member-detail` answer their records key
as one JSON object, not an array (`{"bill": {...}}`, `{"committee": {...}}`,
`{"member": {...}}`, confirmed live 2026-09-19), and carry no `pagination`
object at all. `reading/paged_json.py`'s `PagedJsonReader` reads a non-empty
object at `records_key` as the page's single record, the same generic path a
tuple `records_key` already reads through, rather than shaping the object
down to a chosen field -- but only when `CongressListRoute.single_record` is
`True`, which these three carry; an empty object still refuses either way,
and a route that leaves `single_record` at its `False` default still refuses
a wrapper object outright, so a caller's wrong or mismatched `records_key`
never silently reads as one bogus record. `single_record` states a fact
about the JSON shape at `records_key` -- "this route's records key holds an
object, not an array" -- not a fact about how many records the route yields:
`committee-print-detail` is a detail route that answers exactly one record
too, with `single_record` left `False`, because the publisher answers it
with a real one-item array. `committee-print`'s
detail route needed no such opt-in: the publisher answers
`committee-print/{congress}/{chamber}/{number}` with a real one-item array
under `committeePrint` and a `pagination.count` of 1. None of the four detail
routes has a list to reorder or window against, so `sort_honored` and
`window_honored` are both `False` on that structural ground, not a
measurement. `law`'s records key `bills` is the same spelling `bill` uses;
`LIST_ROUTES["law"]` reuses `BILLS_KEY` rather than a second identical
constant. `member`'s Congress filter lives at a different URL,
`member/congress/{congress}`, not `member/{congress}` the way `committee`'s
does, so it is a second table entry (`member-congress`) rather than an
optional trailing parameter on `member`; a bare `member/congress` 404s
(the API reads it as `member/{bioguideId}` with `bioguideId="congress"`).
`sort_honored`/`window_honored` for `law`, `committee`, `member` and
`committee-print` are carried from the legislative data map's Table A
(`docs/research/legislative-data-map-2026-09-18.md`), the same way
`nomination`, `hearing`, `committee-report` and `house-communication` carry
theirs — each is the exact route Table A measured, not a sibling.
`member-congress` answers a different URL than Table A's bare `member` row,
so it got the same direct probe `house-vote` did: `member/congress/119`,
`limit=1`, `sort=updateDate desc` versus `asc` answered the identical first
record both times (bioguideId `W000832`) — sort ignored, measured 2026-09-19
(see the fixtures README).

`committee-bills` is the one route here whose rows are not a top-level array:
the publisher nests them inside a `committee-bills` wrapper object alongside
its own `count` and `url` (confirmed live 2026-09-19; see the [fixtures
README](../../tests/fixtures/listings/README.md)). `records_key` there is the
tuple `("committee-bills", "bills")`, and `reading/paged_json.py` reads a
tuple records key the same way it already reads `count_path`/`next_path`.

`house-vote` has no bare or congress-only collection: both `congress` and
`session` (1 or 2) are always required, the way `committee-bills` and
`bill-actions` require every one of theirs. Its rows carry exactly thirteen
fields every time, measured 2026-09-19 against `house-vote/119/1?limit=3`
(see the fixtures README): `congress`, `identifier`, `legislationNumber`,
`legislationType`, `legislationUrl`, `result`, `rollCallNumber`,
`sessionNumber`, `sourceDataURL`, `startDate`, `updateDate`, `url`,
`voteType` -- the same field set the raw-data study's
`congressHouseVoteListingFields` names. This is the index only: member-level
positions live at `house-vote/{congress}/{session}/{roll}/members`, one level
deeper and not in `LIST_ROUTES`.

`house-vote`'s `sort_honored=False` is a direct probe, not only the earlier
inference from its sibling `/{roll}/members` route: `house-vote/119/1?limit=1`
with `sort=updateDate desc` versus `sort=updateDate asc` answered the
identical first record both times (roll 240, `updateDate`
2025-09-09T18:53:19-04:00) and the identical declared count (362) either way
-- sort ignored, measured 2026-09-19 (see the fixtures README).

### Detail routes (A5, A6, A7, A10)

`committee-meeting-detail`, `treaty-detail`, `daily-congressional-record-detail`,
`house-communication-detail`, `senate-communication-detail` and
`house-requirement-detail` answer one record identified by its full path
(every path parameter required, no bare or partial form), not a paginated
list. Congress.gov spells that one record's row two ways, both confirmed
live 2026-09-19: `house-communication`, `daily-congressional-record`,
`senate-communication` and `house-requirement` nest a single JSON object
under their records key; `treaty` nests a one-element array instead.
`reading/paged_json.py`'s `_read_page` reads a non-empty object under the
records key as a one-row page, with no declared count and no continuation,
only when the caller opts in with `single_record` -- `CongressListRoute`'s
`single_record=True` on the five object-shaped routes here (not `treaty`,
whose one-element array already reads through the ordinary list path) is
what `CongressListingReader.records`/`.page` set it from. `single_record`
states a fact about the JSON shape at `records_key` -- "this route's
records key holds an object, not an array" -- not a fact about how many
records the route yields: `treaty-detail` is a detail route that answers
exactly one record too, with `single_record` left `False`, because its one
record already arrives inside a one-element array. The opt-in matters
because the wrapping is not safe as a blanket rule for every family this
reader serves: without it, a caller's wrong or mismatched `records_key` that
happens to resolve to a wrapper object -- reading `committee-bills` by its
own top-level wrapper key instead of the tuple that reaches inside it, for
example -- would silently read as one bogus record instead of refusing.
`sort_honored` and `window_honored` are `False` on all six by construction,
not by probe: a single record has no order to reorder and no window to
narrow, so `list_route_url` refuses both the same way it refuses them on a
route that ignores them.

`hearing-detail` (added 2026-09-19 for the `hearing_transcripts.event_id`
column) answers one hearing by jacket number as a bare object under
`hearing`, so it carries `single_record=True` like the other bare-object
detail routes; its record states `associatedMeeting.eventId`, the key the
data map's `hearing→meeting` edge resolved, and `formats[].url`, whose file
stem is the CHRG package id. Measured once, `hearing/119/house/64431`
(receipt `corpora/supply-2026-09-02/receipts/committee-meetings-edges-2026-09-19/`).

`committee-meeting` closes gap A7 (meetings, hearings and documents): its
detail record carries `relatedItems.bills`, `hearingTranscript[].jacketNumber`,
`witnessDocuments` and `meetingDocuments`, the fields the legislative data
map's `meeting->bill`, `meeting->hearing` and `meeting->documents` edges
resolve on. The detail route also accepts the publisher's `nochamber`
address, as retained meeting `119/nochamber/338692` states. The table keeps
`NoChamber` as lowercase `nochamber`; it does not infer `joint` from the
committee name. This address value is admitted only for meeting details.

`house-communication-detail` closes the regulatory-bridge half
of gap A5: `isRulemaking`, `reportNature` (which carries the RIN),
`committees[].systemCode` and `matchingRequirements[].number` are the fields
the map's `communication-typing`, `communication->committee`,
`communication->federal-register` and `communication->requirement` edges
resolve on; `senate-communication`/`senate-communication-detail` cover the
Senate side, which the map found carries an abstract, a committee referral
and a Record date but no rulemaking flag, authority or RIN field. `treaty`
and `daily-congressional-record` close gap A10: `daily-congressional-record`
answers `fullIssue.sections` (the legislative-day calendar the map's
`record->legislative-day` edge reads) on its detail record, and `treaty`
resolves to a GovInfo `CDOC` package by the map's `treaty->cdoc` rule.
`house-requirement`/`house-requirement-detail`/`house-requirement-communications`
close gap A6: the list route walks the full 3,226-requirement index, the
detail route states each requirement's legal authority and its
`matchingCommunications.count`/`.url` pointer, and
`house-requirement-communications` is that pointer's own list route,
measured `sort_honored=False` and left at the carried-forward
`window_honored=True` default rather than spending two more requests on a
route whose every record already shares one frozen `updateDate`
(2021-11-05).

```python
from spicy_docs.sources.congress.listing import LIST_ROUTES, CongressListingReader, list_route_url

route = LIST_ROUTES["amendment"]
url = list_route_url(route, congress=119, limit=250)
with CongressListingReader(budget=budget, api_key=key) as congress:
    for page in congress.records(route, url, max_pages=50):
        print(page.declared_count, len(page.records))
```

## One traversal rule for every JSON list

`reading/paged_json.py` states each publisher's contract as data: the HTTPS
host, the request method, how the next page is named, where the count lives,
and how a credential is spelled in its header. Three continuation kinds cover
every publisher here: a full next URL (Congress.gov, GovInfo, LDA,
CourtListener, SAM), a page number rewritten into a POST body (USAspending),
and an offset walk that ends at the first short page (FCC). The reader then
applies one rule everywhere:

- The credential travels only in the header the family names, `X-Api-Key`
  or `Authorization: Token …`. A URL or request body carrying a credential is
  refused, a publisher placeholder such as SAM's `api_key=REPLACE_WITH_API_KEY`
  is dropped from continuations, and a page that echoes the key is refused
  without retaining its bytes.
- Each page must be `application/json`, a JSON object without repeated keys,
  with its rows under the named key. Anything else is refused with the exact
  bytes attached, including HTML served with status 200.
- A continuation must be the same publisher's HTTPS route and must not repeat.
  Continuations are re-encoded before they are requested so the requested and
  final URLs agree; Congress.gov spells `sort=updateDate desc` with a raw
  space, and the raw form stays in the retained page.
- The declared count may not change between pages (`DeclaredCountChanged`),
  the observed total may not exceed it, and at the publisher's terminal page
  the two must agree (`DeclaredCountMismatch`). Both carry their two numbers,
  so a host never matches the message.
  Reaching `max_pages` with a continuation outstanding is a refusal, not an
  end. Pages already yielded remain partial observations.
- 404 and 410 raise `PagedJsonUnavailableError` with the capture; 401 and 403
  abort with `CredentialRefusedError`; 429 and 5xx retry within the request
  budget, and exhaustion is not absence.

## Pool a list that shifts while it is read

An offset walk over a list that reorders mid-read can repeat one record and
skip another while serving exactly its declared count: the 119th Congress
amendments walk served 7,066 rows but 7,013 distinct amendments on
2026-09-23. `pool_walks` in `reading/paged_json.py` repeats whole walks,
keyed by a caller's identity key, and settles on the first of:

- **A clean walk.** No repeated identity and a distinct count equal to the
  declared total. A record moving in the order skips one only by repeating
  another; a population change can skip one without a repeat, and the reader
  refuses it only when it moves the total (see the known limits).
- **A full pool.** The identities of every walk since the declared total last
  changed, keeping the newest version by the caller's `version`, number
  exactly the declared total. A changed total starts a new pool, and a walk
  whose total changes mid-walk (`DeclaredCountChanged`) is spent and pooling
  restarts after it.

A query still unsettled after `max_passes` (default 4) raises
`IncompleteWalkError` with `declared`, `distinct`, `passes` and `restarted`;
a pool larger than `declared` names that as records replaced under an
unchanged total.

**Known limits.** Both come from a deletion offset by an insertion, which
leaves every total unchanged, and a test pins each.

- Within one walk, the per-page count check proves an equal count, not an
  unchanged population. Ascending, a deletion in the part already read and an
  insertion in the part not yet read cancel their shifts: the walk serves the
  deleted record, skips a live one and settles clean. Descending, the walk
  misses the new record instead, which a later window reaches, so prefer
  descending order.
- Between walks, the pool keeps the deleted record. If every pooled walk
  skipped one live record, the deleted record fills its slot and the pool
  settles wrong; otherwise the pool overfills and the query refuses.

`CongressListingReader.pooled` varies the page size per walk (250, 237, 223)
and alternates `updateDate desc` and `asc` where the route honors `sort`, so
each walk's page boundaries fall on other records. With fixed boundaries a walk
tends to skip what the last one skipped. The evidence is a simulation through
the real reader, and it is conditional on its model: 250 a page, tied
`updateDate` stamps in groups of 1 to 17 reshuffled on every request (about 56
skips a walk), three walks unless stated, 30 queries a case, list sizes of
7,000, 7,004, 7,066 and 7,100.

- A churning list settled in all 30 queries at every size with varied
  boundaries, in 2.1 to 2.4 walks. With fixed boundaries it depended on the
  size, 0 of 30 at 7,000 and 30 of 30 at 7,066, as did spicy-regs'
  `pool_passes`; on a route that ignores `sort` it settled 2 to 4 of 30.
- After a changed total, varied boundaries need a fourth walk: growth then
  quiet, or a deletion before walk 2, settled 13 to 25 of 30 at three walks
  and 30 of 30 at four (measured at 7,000 and 7,066), so `max_passes`
  defaults to four. None settled wrong; spicy-regs published the deleted
  record in 7 to 30 of 30.
- The cost is the second known limit: a replacement before walk 2 settled
  wrong in 3 to 12 of 30 with varied boundaries and 0 to 10 with fixed ones,
  refusing otherwise. A replacement during a clean walk settled wrong in 10 to
  16 of 30 under every rule tried.

The receipt, with the script, is
`supply-2026-09-02/receipts/pooled-walk-simulation-2026-09-23/`.

The key must name what identifies a record, never its content. A key over the
whole record never settles once records carry fields that change between
walks: FCC ECFS proceedings do (`last_30_days`, `total_filing_count`), and one
`id_proceeding` can carry more than one document, so key them by content that
excludes the changing fields. A `version` must be present and comparable, or
the walk refuses.

For example:

```python
route = LIST_ROUTES["amendment"]
with CongressListingReader(budget=budget, api_key=key) as congress:
    pooled = congress.pooled(
        route,
        list_route_url(route, congress=119),
        key=lambda row: (row["congress"], row["type"].lower(), row["number"]),
        version=lambda row: row["updateDate"],
    )
    print(pooled.declared, len(pooled.records), pooled.passes)
```

A publisher that states its total elsewhere, such as FCC ECFS's aggregations,
passes `pool_walks` a function returning one `WalkPass(records, declared)` per
walk.

## Use the routes

Install the `acquisition` extra. Read the key with `read_api_key`; the
default variable name across GovInfo and Congress.gov tools is `API_GOV`.

```python
from pathlib import Path

from spicy_docs.sources.congress.listing import CongressListingReader, bill_list_url
from spicy_docs.sources.gao.rss import GaoFeedAcquirer, GaoFeedBudget
from spicy_docs.sources.govinfo.discovery import GovInfoDiscoveryReader, collection_url
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.transport.credentials import read_api_key

key = read_api_key(Path(".env"), "API_GOV")
budget = PagedJsonBudget(
    max_requests=3, max_page_bytes=16 * 1024**2, timeout_seconds=60, min_request_interval_seconds=0.2
)

with CongressListingReader(budget=budget, api_key=key) as congress:
    url = bill_list_url(congress=119, from_datetime="2026-09-01T00:00:00Z", to_datetime="2026-09-14T00:00:00Z")
    for page in congress.bills(url, max_pages=50):
        print(page.page_index, page.declared_count, len(page.records), page.capture.sha256)

with GovInfoDiscoveryReader(budget=budget, api_key=key) as govinfo:
    for page in govinfo.packages(collection_url("BILLS", "2026-09-01T00:00:00Z")):
        print([row["packageId"] for row in page.records])

with GaoFeedAcquirer(budget=GaoFeedBudget(2, 4 * 1024**2, 60, 1)) as gao:
    feed = gao.acquire_reports_feed()
    print(feed.feed.last_build_date, [item.product_id for item in feed.feed.items])
```

For a pipeline that needs no Python, `spicy-docs-list` walks any of these
routes from the command line, retaining every page's bytes and one receipt row
per page; see [its section in the CLI guide](../cli.md#any-publisher-json-list).

Each `JsonPage` carries `capture` (exact bytes, URLs, status, time, hash),
`records` as the publisher spelled them with decimal numbers preserved,
`declared_count` and the normalized `next_url`. Retain `capture.body` in
caller-owned storage; `records` are a reading of those bytes, not evidence.

The other routes follow the same shape: `LdaFilingsReader.filings`,
`CourtListenerSearchReader.search`, `SamEntitiesReader.entities`,
`UsaspendingRecipientsReader.recipients` (which takes the first request body
from `recipients_request`) and `FccEcfsReader.proceedings` or `filings`. Keys
live in the project env file: `API_GOV` for api.data.gov publishers and
`SAM_GOV` for SAM.gov.

## Read the result correctly

- Congress.gov `pagination.count` is the total for the query; walking a
  window to its terminal page observes exactly that many rows or refuses.
  The lists are keyed; the published rate limit was 20,000 requests per hour
  on 2026-09-14.
- GovInfo `lastModified`, which `/collections` filters on, is the time a
  package was added or updated and equals the sitemap `lastmod`; it is not
  the MODS issued or ingested date. `/published` selects by issue date and
  narrows by `modifiedSince`. Page size is at most 1,000. The rate limit
  observed was 36,000 requests per hour. Every page states its `count`, and
  `GovInfoDiscoveryReader.packages`/`granules` refuse a page without one and a
  `packageId`/`granuleId` that is missing, padded or already served in the
  walk; `spicy-docs-list` walks the raw route without those two checks.
- LDA and CourtListener serve keyless requests at lower rate limits; a
  token raises them. CourtListener's cursor pagination requires `dateFiled`
  ordering, and `type=r` pages also state a `document_count`. Docket searches
  (`type=r` and `type=d`) report [cardinality estimates](https://wiki.free.law/c/courtlistener/help/api/rest/v4/search#result-counts),
  which the publisher describes as having an error of ±6% above 2,000 results.
  Above that bound, their explicit terminal cursor establishes completion;
  observed rows need not equal the estimate. Counts at or below 2,000 and
  opinion searches retain exact-count checks.
- SAM.gov needs its own key: the api.data.gov key answered an empty 404 in
  both header and query form on 2026-09-14. **Window by `registrationDate`
  until the declared total is at most 10,000.** That is the whole of what a
  walk can reach: measured that day, `registrationStatus=A&size=10` served
  pages 0 through 999 and answered page 1000 with `400 Results Too Large`,
  "The Page and Size search has exceeded 10,000 records (Page multiplied by
  Size)"; at `size=7` the boundary moved to page 1428, so a page is refused
  once `(page + 1) × size` passes `MAX_REACHABLE_RECORDS`, and
  `reachable_records(size)` states the number. Every reachable page still
  advertises a `links.nextLink` — page 999 pointed at the page that refuses —
  so the publisher never signals the end, and following continuations spends a
  thousand requests to learn it. `SamEntitiesReader.entities` compares the
  first page's `totalRecords` against that bound and refuses there, in one
  request, with the first page attached as `first_page`. `totalRecords` for
  `registrationStatus=A` read 790,545 and then 790,559 twenty minutes later:
  a declared total is that instant's statement, and it is not reachability.
- USAspending's recipient universe exceeded eighteen million rows on
  2026-09-14; bound the walk. FCC ECFS states no count, so an offset walk
  proves only what it saw; narrow the window rather than walk far.
- **FCC ECFS date windows are inclusive of both dates, because the builders
  add the day the publisher's bound leaves out.** `[gte]D[lte]E` selects
  `D T00:00:00Z ≤ t ≤ E T00:00:00Z`, so the end date contributes only its
  midnight instant: on 2026-09-14 `[gte]2026-09-08[lte]2026-09-08` returned
  zero rows while `[gte]2026-09-08[lte]2026-09-09` returned the 8th, newest
  `2026-09-08T23:56:03Z` and oldest `2026-09-08T04:47:28Z`. `filings_url` and
  `proceedings_url` therefore send `end + 1 day`, and a same-day window means
  that day. A time component does not widen the window — `[lte]D T23:59:59`
  in either spelling answered the same zero-row page — and every empty filings
  query answers the identical 1,037 bytes, so a filter the publisher ignored
  and one that matched nothing look the same. No zero here is absence. One
  consequence of keeping the publisher's inclusive `[lte]`: adjacent day
  windows overlap by the single midnight instant between them.
- The GAO feed is a recent-items window. Every item's link must be the
  canonical product URL, which supplies `product_id`; a duplicated product or
  a non-product link refuses the whole feed. Product pages remain the
  separate, Zyte-backed capture described in [GAO pages](gao.md).

## Evidence

Complete pinned pages with hashes are in
[`tests/fixtures/listings/README.md`](../../tests/fixtures/listings/README.md).
Headers, rate limits and the complete feed are in
`corpora/supply-2026-09-02/receipts/spicyregs-merge-probes-2026-09-14/`; the
FCC window and SAM deep-page measurements above, with every probe's bytes,
status, digest and time, are in
`corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-14/`
(`q1-fcc-same-day` and `q4-sam-deep-cap`). Each is one day's observation from
one network: they establish these boundaries, not that they will hold. These
routes replace SpicyRegs' `congress_bills.py`, `crs_reports.py`,
`cfr_sections.py`, `gao_reports.py`, `lobbying_filings.py`, `courtlistener.py`,
`sam_entities.py`, `usaspending.py` and `fcc_ecfs.py` readers; the
[Unified Agenda](unified-agenda.md) route replaces `unified_agenda.py`. See
the merge ledger in the [to-do list](../simplification-todo.md#spicyregs-fetcher-merge).
