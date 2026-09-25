# Capture CFTC comment-portal comments

Give SpicyDocs a walk over `comments.cftc.gov`, the Commission's own public
comment portal. For each requested year it returns the exact releases-listing
render — every proposed rule (and other release types) that page states, with
open/closing/extended dates and Federal Register citations — then each release's
comment-listing renders, every comment row the pages state, merged with that
comment's detail page when configured, and (as declared locators, not bytes)
the letter files each detail names. No key is required, and there is no API:
the portal is a server-rendered ASP.NET WebForms application behind Cloudflare,
and the walk follows the pages' own GET-reachable anchors.

The publisher directs comment files opened on or after **2026-04-28** to
[Regulations.gov's CFTC docket search](https://www.regulations.gov/search/docket?agencyIds=CFTC&sortBy=lastModifiedDate&sortDirection=desc).
The notice is retained in the live 2026 release page under receipt
`scraper-completion-2026-09-24T235248Z/cftc/discovery`. A portal-year walk
therefore covers the files that portal lists; current CFTC coverage also
requires the separate [Regulations.gov selections below](#select-the-post-cutover-source).

| Selection | What it supplies |
| --- | --- |
| A year (`?Type=ListAll&Year=YYYY`) | One render of `ReleasesWithComments.aspx`: `div.row` per release, each stating release type, FR citation anchor, optional FR-PDF anchor, title, deadline column, labelled open/closing/extended dates, and a `CommentList.aspx?id={ruleId}` anchor naming the rule identity. |
| A rule id | The comment listing at `CommentList.aspx?id={ruleId}`, a Telerik RadGrid paged through its own SEO-rendered pager (`ChangePage={n}`): one row per comment — comment id, date received, first/last name, organizations, release text. |
| A comment id | The detail at `ViewComment.aspx?id={commentId}`: `From:`, `Organization(s):`, `Comment No:`, `Date:`, `Comment Text:`, the return anchor naming its rule, and the `gvAttachments` grid whose rows link each letter file (`../Handlers/PdfHandler.ashx?id={fileId}`). |
| A file id a detail stated | The exact letter bytes from `Handlers/PdfHandler.ashx?id={fileId}`, proved as a complete PDF (`%PDF-` magic and trailer). |

```python
from spicy_docs.sources.cftc_comments.acquisition import CftcPortalAcquirer, CftcPortalBudget
from spicy_docs.sources.cftc_comments.reader import CftcCommentsReader

budget = CftcPortalBudget(
    max_requests=3,
    max_page_bytes=4 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=1.0,
)
with CftcPortalAcquirer(budget=budget, recover_walls=True) as source:
    reader = CftcCommentsReader(
        source,
        years=(2026,),
        release_type="Orders and Other Announcements",
        max_listing_pages=5,
        max_detail_failures=0,
    )
    records = list(reader.iter_records())
    print(reader.last_keys, reader.failed_keys)
```

`recover_walls=True` opts into DIRECT → Zyte `httpResponseBody` → Firecrawl
`rawBase64` through the shared `SourceAcquirer.capture_walled`. Set
`ZYTE_TOKEN` and `FIRECRAWL_API_KEY` in the calling process for the
corresponding provider; CFTC itself requires no key, and the acquirer reads the
provider credentials once. The DIRECT rung is the acquirer's own client, so an
injected `transport=` carries it with or without recovery. Each rung takes one
of the page's `max_requests` attempts and is paced against the preceding
attempt; a provider without a credential takes its rung's place without a
request, a charge or a pacing wait. The default remains direct acquisition.

A page carrying the portal's own content placeholder is the publisher's
answer, so a comment that quotes a block page's words ("Just a moment",
"captcha", even a Cloudflare title) is never read as a wall and never
escalates or aborts the walk. On any other successful answer only block-page
chrome counts as a wall; the generic words count only on a 401/403/429
refusal, and a body that starts `%PDF-` is never a wall.

The page methods return `CftcPageAcquisition`, including exact `capture.body`,
`request_count`, and, in recovery mode, the winning `transport` and provider
`request_id`. Retain these results when transport provenance is needed; the
reader's dictionaries retain page hashes rather than storing the bodies.

The [`CftcCommentsReader`](../../src/spicy_docs/sources/cftc_comments/reader.py)
wraps the same walk for pipeline use: keys are `rule:{id}` and
`comment:{id}`, a complete pass leaves exactly the fully established keys in
`last_keys`, and every attempted key that was not — a listing or detail that
answered 404/410, refused to parse, repeated a comment, changed its stated
total mid-walk, or ended short of it — lands in `failed_keys` for the next run
to retry. A portal refusal raises
instead of manifesting anything partial. Letter bytes are downloaded
separately through
[`attachments.py`](../../src/spicy_docs/sources/cftc_comments/attachments.py);
the reader records their locators.

## Read the result correctly

- **A page is evidence, never absence.** An empty comment grid is an
  observation the caller keeps; a page without its grid, its repeater, or
  carrying the portal's own error sentence is a challenge or error wearing
  the URL and refuses. Only 404/410 say the exact locator has nothing — never
  that comments are absent.
- **The page's own statements must agree with the request.** The releases
  render must state the requested year in its own title; the listing pager's
  current item must name the page requested, its Next anchor must advance the
  same pager parameter by exactly one page, and a listing that declares its
  totals must be walked until its distinct comments equal the total its first
  page stated. A repeated comment, a total that changes between pages, or
  totals the parser cannot read refuse: a listing that shifts while it is
  read can repeat one row and skip another while serving exactly its count
  ([listings](listings.md#pool-a-list-that-shifts-while-it-is-read)). A render
  of another page or year refuses rather than being read as what was asked for.
- **The title and dates remain separate.** The title is the item's description
  paragraph, including inline link text. An `Extended Date:` is retained as
  `extendedDate`; extension labels and related-release notices do not become
  title text. Comment filenames retain the publisher's Unicode spelling as
  display metadata; the URL and downloaded PDF bytes are checked separately.
- **Identity comes from the rows' own anchors.** A release's rule id is read
  from its `hlViewComment` link, a comment's id from its row's hidden View
  anchor, and a detail states its own `Comment No:` and return-to-listing
  rule, which must match the walk — a detail served for another comment
  refuses rather than mis-attributing a letter.
- **Two listing spellings reach the same grid.** The per-rule pages link
  `?id={ruleId}`; the portal's search-all listing spells the same route with
  a bare numeric token (`?3098`), which its own pager preserves. Both are the
  publisher's spellings, both name the listing being served, and rows belong
  to the listing the URL names. Search-all renders the release as two cells
  (citation beside the linked title); per-rule renders one.
- **The pager is SEO-rendered and the pages are walkable by GET.** The
  sibling `FederalRegister/*.aspx` routes render the same releases behind
  postback buttons with no SEO anchors, so they are not read here; the walk
  never builds a postback, and every request is a plain GET of a URL the
  publisher's own bytes stated.

## What is refused

A 200 that is not the page asked for is refused with its bytes retained. The
letter capture checks the media type, the `%PDF-` magic and a trailer within
the last 1024 bytes (the same check the regulations.gov route applies, where
the extension lied about three files in one sample), and that the final URL
equals the locator.

The Cloudflare edge in front of the portal refuses clients it cannot
fingerprint: on 2026-09-24 curl and HTTPX — each sending a browser User-Agent
— answered 403 with the same 5,479-byte `Attention Required!` page on `/`,
`/api/`, the three page routes and the PDF handler, and a real browser began
receiving block pages after repeated navigations. Portal page captures take
the shared injectable transport or opt into `recover_walls=True`. A direct
403, or exhaustion of the selected recovery ladder, raises
`CftcPortalRefusedError` (a
`CredentialRefusedError` subclass, so callers that abort on a refusal keep
aborting) naming the block-page shape from the retained bytes. Recovery
exhaustion also retains `rung_outcomes`. It says nothing about the page:
it is an access decision about this client. A clean publisher error page is
retained and rejected by the parser; recovery does not try to turn it into
a successful page. The final URL must equal the requested locator.

Letter downloads start with direct acquisition and recover through proxies:
[`attachments.py`](../../src/spicy_docs/sources/cftc_comments/attachments.py)
walks the shared walled-fetch ladder
([`walled_fetch.py`](../../src/spicy_docs/sources/walled_fetch.py)) — DIRECT,
Zyte `httpResponseBody`, Firecrawl `rawBase64` — one bounded attempt per rung,
returning the first clean answer. Measured live 2026-09-24, both proxy rungs
reach the publisher: Zyte `httpResponseBody` and Firecrawl v2 `rawBase64` each
returned the real ASP.NET page (HTTP 200, 147,003 bytes, marker `ctl00_ctl00`)
where a direct client got the 403 block page. A wall-marked answer or a 429
escalates to the next rung; a clean 404/410 is the locator having nothing
(`CftcPdfUnavailableError`); and when every rung found a wall or refused, the
exhausted error raises `CftcPdfRefusedError` (a `CftcPortalRefusedError`, so
also a `CredentialRefusedError`) carrying the retained wall bytes and naming
the block-page shape exactly as a page refusal would, through the ladder's one
canonical vocabulary. The ladder never judges the
bytes: this module's own gate — the `application/pdf` media type, the `%PDF-`
magic, the trailer proof, the final-URL equality and the byte caps — still
reads every clean answer, and neither a wall nor a refusal is an observation
that the file is absent.

`PdfBudget.max_requests` limits the attempted ladder rungs for each PDF.
The ladder stops before exceeding that limit and retains the outcomes and
wall evidence already observed. Every attempt uses `SourceAcquirer` accounting
and pacing; the count resets for each new PDF while the pacing clock persists
for that client. Page and PDF clients have separate, explicit budgets.

Measured end to end the same day (receipt `cftc-pdf-bounds-2026-09-24`): six
comment letters downloaded complete through the gate, magic and trailer
checks passing — three from the fixture-declared handler ids (2011–2016 era
letters) and three from ids one live listing walk (rule 1647) harvested. Five
answered DIRECT cleanly; one escalated past a DIRECT and a Zyte wall to
Firecrawl `rawBase64`. The edge's answer to a direct client on this route is
intermittent — the same day, the listing page answered DIRECT in one run and
Zyte in the next — so the ladder stays the route. The six letters' bytes are
retained content-addressed in the campaign blob store.

Byte bounds are runaway guards, not measured percentiles: captures of releases
renders (60–100 KB), comment listings (130–150 KB) and details (~70 KB) sit
far under the 4 MiB page default. The six live letters of receipt
`cftc-pdf-bounds-2026-09-24` measured 25,170–239,920 bytes (PDF 1.3–1.5), two
orders of magnitude under the 16 MiB letter default (regulations.gov's, which
covered 98.7% of that publisher's files), whose 640 MiB cap stays as the
runaway ceiling. What remains unmeasured is a large-sample letter size
distribution — the 2026-09-24 sample is six letters — and whether the edge's
intermittency on the handler route holds over time.

## Coverage limits

A failed comment detail keeps both its comment key and its parent rule key
out of `last_keys`, including when the detail-failure ceiling aborts the run.
Below the ceiling the listing-only row is still yielded; the failure that
crosses the ceiling re-raises before its row is yielded. Either way a caller
cannot checkpoint the rule as complete until its requested details succeed.

The later live qualification in receipt
`scraper-completion-2026-09-24T235248Z/cftc/qualification-3` completed the
2026 releases page → rule 7639 → every stated comment/detail → every declared
PDF path: five comments and five PDFs, totaling 1,212,292 bytes. A repeated
listing agreed on the comment identities. The separate rule 1647 listing was
walked by the campaign script, page by page through the acquirer's
`comment_list_page`: it reached its terminal fourth page with 34 unique
comments, matching each page's stated total. The reader's own multi-page walk
then qualified live on the same rule in receipt
`cftc-reader-multipage-2026-09-25` (`recover_walls=True`,
`fetch_details=False`): four listing pages, each stating the same 34-item
total, served 34 distinct comments, the same identities as the script's walk,
and the rule settled with no failed key. The earlier publisher error pages
remain retained in the preceding campaign; later success does not establish
continuous route availability. These bounded runs qualify those selected
scopes.

The supported `recover_walls=True` API was then qualified directly in receipt
`scraper-delivery-2026-09-25T003133Z/cftc/production-live`, without a campaign
HTTPX adapter. The reader again completed the selected rule, and the script's
page-by-page rule 1647 walk passed; three page operations recovered through
Zyte and four PDFs through Firecrawl.
The recorded totals were 15 page attempts and 13 PDF attempts. All five PDF
hashes matched the preceding campaign.

This source reads only what the portal's own GET-reachable pages state: the
releases listing (per year, or the upcoming-deadlines default), the comment
listings and the comment details. The submit-comment forms, the search UI,
the postback-only Federal Register routes, and any comments a listing does not
state are outside the capture. The portal directs files opened from
2026-04-28 onward to Regulations.gov; neither this reader nor a mirror's
retained inventory establishes current coverage of that separate source.
The letter downloads travel through the walled-fetch ladder because direct
access is intermittent.

## Select the post-cutover source

CFTC's [transition announcement](https://www.cftc.gov/PressRoom/PressReleases/9221-26)
and [submission guidance](https://www.cftc.gov/LawRegulation/PublicComments/HowtoSubmit/index.htm)
split sources by when the **comment period opened**: periods opened before
2026-04-28 stay on Comments Online; periods opened on or after that date use
Regulations.gov. A comment's received or posted date is not that boundary.
Keep portal rule/comment IDs and Regulations.gov document/comment IDs in their
own source namespaces.

The existing [Regulations.gov API reader](regulations-gov-api.md) selects
CFTC documents, their details and their declared attachments:

```python
from pathlib import Path

from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.regulations_gov.api import RegulationsGovApiReader, document_list_url
from spicy_docs.transport.credentials import read_api_key

with RegulationsGovApiReader(
    budget=PagedJsonBudget(3, 4 * 1024**2, 45, 3.7),
    api_key=read_api_key(Path(".env"), "API_GOV"),
) as source:
    query = document_list_url(
        agency_id="CFTC",
        posted_from="2026-04-28",
        posted_to="2026-09-24",
        page_size=250,
        sort="-postedDate",
    )
    pages = tuple(source.documents(query, max_pages=2))
    for page in pages:
        for identity in page.document_ids:
            detail = source.document(identity)
            print(identity, detail.attributes.get("commentStartDate"))
```

Those dates bound a document sample; they do not determine which source owns
a comment period. Retain the source's opening date and docket identity when
making that choice. The bounded live check in receipt
`scraper-delivery-2026-09-25T003133Z/cftc/cutover-live` returned 55 documents
for this window and read two details with opening dates after the cutover.
This API reader does not enumerate Regulations.gov comments or docket records.
The separate [Mirrulations workflow](regulations-gov.md) supports those
collections through `regulations-comments` and `regulations-dockets`, with
`--agency CFTC`; its date selectors mean comment posted dates and docket
modified dates, respectively. Mirror completeness concerns the observed
mirror inventory and does not prove that every current origin comment is
present. Use the [CLI publication selectors](../cli.md#publish) with explicit
dates and retain that distinction in the output.

For a mirror comment release, the existing source selection is:

```sh
uv run --frozen spicy-docs-source-native publish \
  --source regulations-comments --agency CFTC \
  --since 2026-04-28 --until 2026-09-24 \
  --destination /new/cftc-comment-release --blob-store /persistent/blobs \
  --implementation-id 'git+https://example.test/spicy-docs@<reviewed-full-commit>'
```

Use the actual producer identity and new output directory. Publication reads
the full named agency's comment inventory before applying the date selection;
this is broader than the bounded source checks recorded here.

The narrow mirror check in that campaign's `cutover-mirror` receipt reached
the end of the `CFTC-2026-` docket-prefix listing, including the current
`CFTC-2026-2113` docket. A separate complete listing of `CFTC-2026-1388`
declared comment JSON and attachment objects. This establishes that the
mirror includes post-cutover CFTC material; this check did not download or
compare every comment against the origin API.

## Evidence

The trimmed fixtures, their Wayback capture provenance, and the page-shape
findings above are in
[`tests/fixtures/cftc_comments/README.md`](../../tests/fixtures/cftc_comments/README.md).
Owners:
[`pages.py`](../../src/spicy_docs/sources/cftc_comments/pages.py),
[`acquisition.py`](../../src/spicy_docs/sources/cftc_comments/acquisition.py),
[`attachments.py`](../../src/spicy_docs/sources/cftc_comments/attachments.py),
[`reader.py`](../../src/spicy_docs/sources/cftc_comments/reader.py).

```sh
uv run --frozen pytest -q tests/test_cftc_comments.py
```
