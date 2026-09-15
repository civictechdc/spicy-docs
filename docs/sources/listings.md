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
- The declared count may not change between pages, the observed total may not
  exceed it, and at the publisher's terminal page the two must agree.
  Reaching `max_pages` with a continuation outstanding is a refusal, not an
  end. Pages already yielded remain partial observations.
- 404 and 410 raise `PagedJsonUnavailableError` with the capture; 401 and 403
  abort with `CredentialRefusedError`; 429 and 5xx retry within the request
  budget, and exhaustion is not absence.

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
  observed was 36,000 requests per hour.
- LDA and CourtListener serve keyless requests at lower rate limits; a
  token raises them. CourtListener's cursor pagination requires `dateFiled`
  ordering, and `type=r` pages also state a `document_count`.
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
