# FERC eLibrary: comments and docket documents from FERC's own systems

Acquire FERC rulemaking comments and docket documents from the eLibrary web
API at `elibrary.ferc.gov`. The Mirrulations regulations.gov mirror holds
FERC documents only — zero dockets, zero comments — so comments come from FERC
itself: eComment submissions are filed into eLibrary under the
`Comments/Protest` class, keyed by accession number like every other eLibrary
document. The eComment portal pages on `www.ferc.gov` sit behind an Akamai bot
wall (403 to a scripted browser-profiled GET, 2026-09-24) and are not a route
this package crosses; the eLibrary API answered every probe without a key,
login or registration.

| Route | Selection | Rows | Credential |
| --- | --- | --- | --- |
| `POST Search/AdvancedSearch` | Optional docket, Class/Type, dates, text, categories | `searchHits`, paged by request body | none |
| `GET Search/GetClassTypes` | Current search vocabulary | bare array; category/library variants retained | none |
| `GET Docket/getDocketDescription/{docket}` | One docket | two strings | none |
| `GET Docket/getSubDocketSearch/{docket}` | One docket | `DataList` strings (live 2026-09-24) | none |
| `GET Docket/GetATMSdocs/{mode}/{from}/{to}/{sort}` | New dockets in a date window, `mode` `rbCreateDate`/`rbFilingDate` | `DataList` docket rows (live 2026-09-25) | none |
| `POST Docket/GetSingleDocketSheet` | One docket (+ sub-docket, dates) | `DataList` document rows, paged by request body (live 2026-09-25) | none |
| `GET File/GetFileListFromP8/{accession}` | One accession | `DataList` file rows (live 2026-09-24) | none |
| `POST File/DownloadP8File` | One public file GUID from a captured file list | original file bytes | none |
| `POST File/DownloadPDF?accesssionNumber={acc}` | One accession | generated PDF bytes | none |

## How the API was found, and what it is

eLibrary is an Angular application; its own assets state the contract. The
SPA's `app-settings.json` (captured 2026-09-24) names the API base
`/eLibraryWebAPI/api/` and a public application id; its lazy bundles name the
routes, the request bodies and the response fields this module uses. Probing
budget on 2026-09-24: 24 GETs and 5 POSTs, paced at 1–3 s.

The API is keyless but expects the SPA's headers: every request carries
`x-applicationId`, one stable `x-sessionId` and a fresh `x-correlationId`
exactly as the SPA's interceptor adds them, and the walk pins a browser
User-Agent because that is the client spelling every live probe used — the
one precedent in this codebase (regulations.gov's download host) answered a
tool-branded agent with a clean 403, and an untested agent reads as "the host
does not work".

Keyed GET routes answer
`{"DataList": [...], "ErrorList": []}`; a non-empty `ErrorList` refuses,
because it is the publisher naming its own failure. The search route answers
`{"searchHits": [...], "totalHits": N, "numHits": M, "success": bool,
"errorMessage": ...}`; `success:false`, an `errorMessage`, or a `numHits` that
disagrees with the rows served all refuse. `GetClassTypes` answers a bare
array, read separately with its exact response bytes retained.

## The search walk, and what its numbers mean

The search is built on the shared paged-JSON capture (byte bounds, media-type
check, refusal evidence) but owns its own traversal, for one measured reason:
**the response names no continuation.** Paging state lives in the request
body — `curPage` and the IDOL `idolResultID` token the previous response
returned as `searchResultId` — and the shared page-number walk advances a page
only when the response declares the next one. This walk advances `curPage` by
one while pages come back full, carries the previous page's token forward as
the SPA does, ends at the first short page, and holds the shared traversal's
refusals: a declared `totalHits` that moves mid-walk
(`DeclaredCountChanged`), a terminal count disagreement
(`DeclaredCountMismatch`), more rows served than declared, a repeated
`reference`, or a page bound reached with a full page outstanding. Every
refusal carries the page it was decided on and the walk's position and
counts. The docket sheet shares the same walk. A caller-supplied body must
state a `resultsPerPage` from 1 to 100 before any request is sent.

**Populated discovery is qualified for the measured docket.** A real browser
search on 2026-09-24 returned RM24-5's eleven records. Its exact request was
retained as a sanitized HAR and replayed through the production direct HTTP
capture without browser cookies, `Origin`, `Referer`, or login. It returned
the same source identities. Three bounded pages (five, five, one rows) agreed
with the declared total and the browser's complete identity set. Selecting
`Comments/Protest` / `Rulemaking Comment` returned five records in pages of
two, two, one, also matching the browser's class-qualified identities.

**The original zero-hit reading was transient, and the full wire body is the
contract.** A same-day probe had recorded zero hits from every off-network
body it tried. A re-probe on 2026-09-24 from a plain shell carrying only the
three SPA headers, `Content-Type` and a browser User-Agent did not reproduce
it: the operator-verified full wire body, the module's then-minimal body, and
bodies with `dateSearches` removed or `idolResultID:""` all answered docket
RM24-5's eleven records, six rapid same-session requests included. The
original zero is therefore treated as transient and unexplained, not a
property of the route. The publisher's own search-form help pages settle the
date question: `eLibrary_Help_Using_This_Form.pdf` marks "Select Date Range
(required" (an asterisked required field) with a "Past 60 Days" default
preset, so the builder always sends a `dateSearches` window — a required
field is sent, never assumed optional — `1904-01-01` (the SPA's own epoch) to
today, UTC, with `allDates:true`, and callers narrow it with
`date_from`/`date_to`, which flips `allDates` to `false`. The same pages
document the docket grammar the body inherits (a trailing dash is assumed
unless a full sub-docket is entered, so `RM24` means `RM24-*`; a partial
sub-docket suffix needs a `*` or `?` wildcard) and the date-type meanings
(`filed_date` = stamped by the Office of the Secretary). Pinned copies:
`~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-help-pdfs-2026-09-25/`
(sha256 `83752867…`, `73d01bf5…`). The builder emits the SPA's full wire body,
field for field, with one difference: both retained browser requests send
`idolResultID:""`, while the builder sends `null` until a response returns a
`searchResultId` token. The `null` spelling answered identically live
(`search-page-convention.jsonl` below):

```json
{"searchText":"*","searchFullText":true,"searchDescription":true,"dateSearches":[{"dateType":"filed_date","startDate":"1904-01-01","endDate":"2026-09-25"}],"availability":null,"affiliations":[],"categories":[],"libraries":[],"accessionNumber":null,"eFiling":false,"docketSearches":[{"docketNumber":"RM24-5","subDocketNumbers":[]}],"resultsPerPage":100,"curPage":1,"classTypes":[],"sortBy":"","groupBy":"NONE","idolResultID":null,"allDates":true}
```

**The page convention is verified live beyond one page.** The SPA's paginator
sends `curPage: pageIndex+1` and overwrites `idolResultID` only when a
response returns a `searchResultId` token. On 2026-09-25 a >100-hit query
(`docketSearches` docket `RM24`, full window, `resultsPerPage:100`) answered
`totalHits: 207`: `curPage:0` and `curPage:1` served the identical first
page (100 rows), `curPage:2` the second (100 further distinct rows), and
`curPage:3` the 7-row terminal page, `searchResultId` null throughout — so
the walk's one-based advance, its short-page end, and its token carry all
match what the publisher does. Receipts:
`~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/search-page-convention.jsonl`.

A zero remains an observation, not absence, and is asked again: the comment
reader puts a docket whose walk answered zero rows in `failed_keys` with the
reason `requested-empty` and keeps the answer's timestamp in
`empty_observations`, separate from never-requested dockets (see
[the readers](#the-readers-and-their-one-recovery-rule)). A full final page was
tested too: the following empty page preserved the declared total, allowing the
walk to confirm completion.

The requests, exact responses, source bundle pins, controlled comparisons,
and complete identity checks are retained under
`supply-2026-09-02/receipts/scraper-completion-2026-09-24T235248Z/ferc/`.

Two more findings from the same probes, both pinned in fixtures or tests:

- **`POST Search/GeneralSearch` is not deployed.** The bundle calls it, but
  the live API answers the framework's 404 "No HTTP resource"; only
  `AdvancedSearch` exists. Do not add the shorter route back.
- **The SPA fallback serves HTML where JSON lives.** A missing asset under
  `/eLibrary/` answers 200 with the Angular `index.html`, so a typo'd route
  can look like success. The media-type check refuses it.

## Discover filings by date and class

Use `search_body()` without a docket to discover filings across eLibrary.
It sends the browser's empty docket selector, so the caller does not need an
inventory of docket numbers. `docket_search_body()` retains its stricter
requirement for a known docket; both builders use the same request fields
and `FercElibraryReader.search_pages()` walk.

```python
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.ferc.elibrary import FercElibraryReader, search_body

budget = PagedJsonBudget(max_requests=3, max_page_bytes=4 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1)
body = search_body(
    date_from="2026-07-27",
    date_to="2026-09-25",
    document_class=(
        ("Approved Designation", "All"),
        ("Application/Petition/Request", "All"),
    ),
)
with FercElibraryReader(budget=budget) as elibrary:
    for page in elibrary.search_pages(body):
        for row in page.records:
            print(row["reference"], row["acesssionNumber"], row["docketNumbers"])
```

`All` selects every type within the named class. It is a search selector,
not a document type in the vocabulary. An empty `document_class` selects all
classes; supplied pairs, including unfamiliar ones, pass through unchanged.
The dates select `filed_date`, and `allDates` becomes false when either date
is supplied. These are filing searches, distinct from the new-docket
enumeration's creation/filing windows below.

### Retain and replay a complete search

The [capture diagnostic](../../tools/analysis/ferc_search_capture.py) accepts
an AdvancedSearch JSON body, captures the live vocabulary, then walks the
query using the same library reader. Each response has exact bytes, a
checksum, observation time, URL, method and actual request body. The input
body is retained separately; the walk starts at `curPage:1`, even when the
browser's initial body says zero.

```sh
uv run --frozen python -m tools.analysis.ferc_search_capture \
  --request tests/fixtures/ferc/advanced-search-all-dockets-request.json \
  --out "$HOME/Work/corpora/supply-2026-09-02/receipts/ferc-search-example"
uv run --frozen python -m tools.analysis.ferc_search_capture \
  --replay "$HOME/Work/corpora/supply-2026-09-02/receipts/ferc-search-example"
```

Use a fresh output directory for each attempt. A refused or interrupted run
keeps its evidence and remains incomplete; retry the full query in a new
directory. The command permits up to three attempts per capture and applies
`--max-pages` to the search walk; its retained-response count excludes retry
attempts whose responses are not retained. Page bounds, changing totals,
repeated references and terminal count disagreements refuse completion. An empty result is
`requested-empty`, never proof of absence. Offline replay verifies byte
digests, actual request scope, continuation requests, distinct references
and the terminal count against the saved summary. Neither mode downloads
original files or publishes a source release.

## New docket enumeration

`GET Docket/GetATMSdocs/{mode}/{from MM-dd-yyyy}/{to MM-dd-yyyy}/{sort}`
lists the new dockets in a date window — the SPA's own new-docket page —
keyless, in the `{"DataList": [...], "ErrorList": []}` envelope, sorted by
`DocketFullNumber`. `mode` is one of the page's two radio options:
`rbCreateDate` (docket creation) or `rbFilingDate` (stamped by the Office of
the Secretary); both measured answering live. Ranges work in both modes:
measured 2026-09-25, `rbCreateDate` 09-20→09-25 answered 351 rows,
09-16→09-25 462, 09-14→09-25 556, and `rbFilingDate` 09-20→09-25 answered
283; the verification fetch and the two fixture-capturing fetches below
reproduced these live and are retained in the receipt directory named at the
bottom of this section.

Each row carries `DocketID`, `DocketShortNumber`, `SubDocketNumber`,
`DocketFullNumber` (the identity, e.g. `ER26-2847-002` or `ID-10800-000`), `DocketCreationDate`,
`DocketFilingDate`, `DocketDescription`, `CommaDelimitedApplicantsList`, and
`DocketSheetlink` — an HTML `<a>` string, retained verbatim. Dockets span
every prefix family (ER, CP, RP, QF, `P-{digits}`, and more); the pinned
prefix roster in [`vocabulary.py`](../../src/spicy_docs/sources/ferc/vocabulary.py)
is context, never a filter.

**The publisher's own form caps a range at 10 days from today.** The reader
defaults its window to that span (today minus ten days to today, UTC) and
lets the caller override it; a wider override is documented as beyond the
publisher's stated cap — measured answering live anyway (09-14→09-25 served
556 rows).

**A zero answer is a publisher-side bug, not "no new dockets".** Identical
windows served hundreds of rows one minute and zero the next — measured
repeatedly 2026-09-25, and the operator's own manual testing confirmed it:
the verification fetch's first two attempts at
`rbCreateDate` 09-23→09-25 answered 200 with an empty `DataList`, and the
third, identical request answered 203 rows. An empty `DataList` is therefore
an observation of that answer, never "done with nothing": `FercNewDocketReader`
puts the window in `failed_keys` with the reason `requested-empty` and its
timestamp in `empty_observations`, the same rule every FERC reader follows, so
the next run asks again. Every row's `DocketFullNumber` is checked before any
row is yielded; a row without one fails the whole window.

The enumeration composes with the comment reader: walk new dockets by day
(`rbCreateDate` or `rbFilingDate` windows), feed each docket's
`DocketFullNumber` to `FercElibraryCommentReader` or `FercDocketSheetReader`,
and each document's accession to `FercElibraryAccessionReader` for its file
list and originals. The window's live answer includes serial-numbered
`ID-` dockets, which the docket grammar admits (see [Identity keys](#identity-keys)).
Each yielded row is the publisher's row verbatim plus `identity` (its
`DocketFullNumber`) and `captureSha256` (the digest of the response that served
it); flattening is a transform's job.

```python
from spicy_docs.sources.ferc.elibrary import FercElibraryReader
from spicy_docs.sources.ferc.readers import FercNewDocketReader

with FercElibraryReader(budget=budget) as elibrary:
    window = FercNewDocketReader(elibrary, "rbFilingDate", "2026-09-20", "2026-09-25")
    for docket in window.iter_records():
        print(docket["identity"], docket["CommaDelimitedApplicantsList"], docket["captureSha256"])
    if window.failed_keys:
        ...  # a refusal or a publisher zero: re-ask this window on the next run
```

Receipts: `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/`.

## The docket sheet

`POST Docket/GetSingleDocketSheet` answers one docket's docket sheet — the
docket's own document listing — keyless, in the
`{"DataList": [...], "ErrorList": [], "Page": {...}}` envelope. The body is
the SPA's own wire shape, built by `docket_sheet_body()`:

```json
{"dockets":"er11-4046","subdockets":"001","filed_date_beg":"01-01-1960","filed_date_end":"09-25-2026","complete_flag":0,"numHits":100,"pageNumber":0}
```

`dockets` is one docket number, validated against the published prefix
grammar and **lowercased exactly as the SPA's request spells it**; `subdockets`
is the sub-docket code the SPA's form sends (`001`); the date window defaults
to `1960-01-01` through today (UTC) and is spelled `MM-dd-yyyy` in the body;
`complete_flag` is the form's 0/1 checkbox; `pageNumber` is **zero-based**.
The measured 2026-09-25 body answered ER11-4046 sub-docket 001's three
documents: `Page.totalHits: 3`, `Page.numHits: 100`, `Page.pageNumber: 0`.
`Page.numHits` echoes the requested page size, not the rows served.

Each `DataList` row nests one `DocumentsItem` list beside an `AuthorsItem`
list and a `FedCitesItem` list. The measured sheet held one document per
list; `docket_sheet_rows()` flattens a row into one document per
`DocumentsItem` entry, attaching the row's `AuthorsItem` and `FedCitesItem`
verbatim beside every document, so a multi-document row loses nothing. A
document's identity is its **`accession_no`** as served — held to the same
`YYYYMMDD-NNN(NN)` grammar the file-list URL builder applies, because it is
the join value into `File/GetFileListFromP8/{accession}`. The publisher's
`document_id` field is not read: it measured 0 on every row of the
qualification docket and cannot distinguish documents. `FedCitesItem` is the
bridge to FR citations; it measured empty on the qualification docket, so
its entry shape is unmeasured — both it and `AuthorsItem` are retained
verbatim, never interpreted, for the transform that joins them.

Paging uses the search walk: the walk advances `pageNumber` by one while
pages come back full (rows equal to `Page.numHits`), ends at the first short
page, requires the declared `totalHits` to hold across the walk and to equal
the distinct accessions served at the terminal page, and refuses — never
silently ends — on a moved count (`DeclaredCountChanged`), a terminal
disagreement (`DeclaredCountMismatch`), more rows served than `numHits`, a
repeated accession, a non-empty `ErrorList`, or a page bound reached with a
full page outstanding. Each page's records are its flattened documents; its
capture keeps the envelope verbatim.

**Paging beyond one page is unqualified.** The only live sheet fit on one page.
The `pageNumber` advance and the full-page rule are exercised by synthetic
fixtures alone (`tests/fixtures/ferc/README.md`), so qualify a sheet with more
documents than one page holds before relying on a multi-page walk. A wrong
guess refuses on the count or identity checks rather than returning a wrong
list.

**A zero answer is an observation, never absence**: the publisher-side zero
seen on new-docket windows can empty a sheet too, so `FercDocketSheetReader`
puts the sheet's key in `failed_keys` with the reason `requested-empty` and its
timestamp in `empty_observations`, and the next run asks again.

The composition chain is: enumerate dockets via `FercNewDocketReader` →
one `FercDocketSheetReader` sheet per docket → each document's
`accession_no` into `FercElibraryAccessionReader` (file list) and
`FercElibraryOriginalAcquirer`/`FercElibraryDownloadAcquirer` (bytes). Each
yielded document is the flattened publisher row verbatim — every
`DocumentsItem` field, including `FERC_CITE`, `fed_reg_num` and
`comments_due_date` — plus `identity` (its `accession_no`) and `captureSha256`.

```python
from spicy_docs.sources.ferc.elibrary import FercElibraryReader
from spicy_docs.sources.ferc.readers import FercDocketSheetReader

with FercElibraryReader(budget=budget) as elibrary:
    sheet = FercDocketSheetReader(elibrary, "ER11-4046", "001")
    for document in sheet.iter_records():
        print(document["identity"], document["category"], document["filed_date"])
    if sheet.failed_keys:
        ...  # a refusal or a publisher zero: re-ask this sheet on the next run
```

Receipts: `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/docket-sheet-er11-4046-001.json`
(raw publisher bytes) and `.../docket-sheet-2026-09-25.jsonl` (the
module-path verification).

## Identity keys

- **Docket**: `RM24-5`, `AD24-2-000`, `P-14683-000`, `ID-10800-000` —
  uppercased; two letters and a fiscal year, or a roster prefix whose dockets
  spell a hyphen and a serial number (`P` hydropower projects, `ID`
  interlocking directorates: `vocabulary.SERIAL_DOCKET_PREFIXES`, each an
  active prefix of the June 2025 docket-prefix roster, the `ID-` spelling read
  from the live 2026-09-25 new-docket answer). `docket_id()` validates.
- **Accession**: `20240418-4000` — `YYYYMMDD-NNN(NN)`; the grammar admits the
  three-, four- and five-digit tails. `accession_number()` validates.
- **Search row**: the publisher's own `reference` field (which its results
  table tracks rows by); a row without one fails its docket rather than
  reading as an anonymous record. Note the row's accession field is the
  publisher's own misspelling `acesssionNumber` — preserved, not corrected.
- **Docket-sheet document**: the row's `accession_no` as served (the join
  value into the file-list route, held to the accession grammar); the
  publisher's `document_id` measured 0 on every qualification-docket row and is
  not read.
- **New docket**: the row's `DocketFullNumber` as served.

Comments are selected by the publisher's own class vocabulary
(`Search/GetClassTypes`, captured 2026-09-24): Class `Comments/Protest`, Type
`Rulemaking Comment` — the constant `RULEMAKING_COMMENT`. Categories are only
`Issuance`/`Submittal`/`Uncertain`; comment-ness is a Class, not a Category.

## Live and pinned FERC vocabularies

`FercElibraryReader.class_types()` captures `Search/GetClassTypes` and
returns a `Listing`: the exact `capture` and publisher `records`.
Each row keeps `Class`, `Type`, `Library`, `Category`, `Accession_Number`
and any additional fields. Repeated class/type pairs remain separate rows
when their categories or libraries differ. An empty array remains an empty
observation; malformed rows and non-array responses refuse with evidence.

The live API includes legacy conversion labels and values absent from the
PDF roster. The capture diagnostic's `vocabulary` report compares exact
class/type pairs with the parsed PDF snapshot in `CLASS_TYPE_PAIRS`, naming
the PDF URL and digest. Differences can reflect wording, extraction or
scope; they neither rewrite the retained evidence nor filter search input.

[`sources/ferc/vocabulary.py`](../../src/spicy_docs/sources/ferc/vocabulary.py)
pins FERC's two published eLibrary rosters with their publication identity:

- **Docket prefixes** — the June 2025 "Docket Prefix List",
  `https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf`
  (SHA-256 `c32efae9…`, 282,729 bytes): 95 prefixes, active and discontinued,
  each with the publisher's own status. The identity grammar keeps exactly the
  published prefix shapes; a discontinued prefix stays a valid spelling for
  older dockets.
- **Document class/type** — the January 2025 "Document Class and Type" tables,
  `https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf`
  (SHA-256 `af632c9c…`, 193,934 bytes): 235 rows collapsing to the 230 unique
  `(class, type)` pairs the search route selects by.

Both PDFs are the digest-pinned bytes RefSpec acquired 2026-08-03 and parses
(RefSpec owns the parsers and the acquisition pipeline; this module pins the
parsed values and the provenance). Application is deliberately narrow:
`RULEMAKING_COMMENT` is checked against the class/type roster at import (a
drift fails loudly instead of surfacing as a zero-hit walk), and the docket
grammar keeps the roster's published prefix shapes plus the serial-numbered
spellings of `SERIAL_DOCKET_PREFIXES`. Membership is never a refusal gate: an
unknown-but-plausible value passes through to the publisher, whose answer is
the evidence, and a refused identity lands in the reader's `failed_keys` with
its reason — never dropped silently, never aborting the rest of the run.

## Use the routes

Install the `acquisition` extra. No credential is read — the family is
keyless.

```python
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.ferc.download import FercElibraryDownloadAcquirer, FercElibraryDownloadBudget
from spicy_docs.sources.ferc.elibrary import FercElibraryReader, docket_search_body, RULEMAKING_COMMENT
from spicy_docs.sources.ferc.originals import FercElibraryOriginalAcquirer
from spicy_docs.sources.ferc.readers import FercElibraryAccessionReader, FercElibraryCommentReader

budget = PagedJsonBudget(
    max_requests=4, max_page_bytes=16 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.0
)
with FercElibraryReader(budget=budget) as elibrary:
    body = docket_search_body("RM24-5", document_class=(RULEMAKING_COMMENT,), results_per_page=100)
    for page in elibrary.search_pages(body):
        print(page.page_index, page.declared_count, [row["reference"] for row in page.records])
    files = elibrary.file_list("20251125-3057")
    print(files.accession, len(files.records))

    comments = FercElibraryCommentReader(elibrary, ["RM24-5", "AD24-2"])
    for row in comments.iter_records():
        ...  # the publisher's row, untouched
    print(comments.last_keys, comments.failed_keys, comments.failure_reasons, comments.empty_observations)

    accessions = FercElibraryAccessionReader(elibrary, ["20251125-3057"])
    records = list(accessions.iter_records())

    files = elibrary.file_list("20240807-5052")
    with FercElibraryOriginalAcquirer(
        budget=FercElibraryDownloadBudget(max_bytes=16 * 1024**2, timeout_seconds=30, min_request_interval_seconds=1.0)
    ) as originals:
        for file in files.records:
            original = originals.acquire(files, file_id=file["ID"])
            print(original.file_id, original.sha256, original.file_list_sha256)

with FercElibraryDownloadAcquirer(
    budget=FercElibraryDownloadBudget(max_bytes=16 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.0)
) as download:
    acquisition = download.acquire("20251125-3057")
    print(acquisition.sha256, acquisition.requested_empty, acquisition.request_count)
```

### The readers and their one recovery rule

[`readers.py`](../../src/spicy_docs/sources/ferc/readers.py) holds the four
`Reader` connectors: comments, accession file lists, new-docket windows and
docket sheets. They are pure sources: rows arrive exactly as the publisher
spelled them (sheet documents flattened per `DocumentsItem` entry), and
flattening into schema-shaped records is a transform's job. The new-docket and
sheet rows add `identity` and `captureSha256`.

All four follow one recovery rule:
- A 401/403 is recast as `FercElibraryAccessRefusedError`, a
  `CredentialRefusedError` subclass, so aborting callers keep aborting. It is
  never a failed key.
- Every key that produced no records stays out of `last_keys` and lands in
  `failed_keys`, with its scrubbed last answer in `failure_reasons`, for the
  next run to retry. That includes a malformed input identity, a walk that
  refused partway (which yields nothing for its key), and a requested-empty
  answer.
- A requested-empty answer's reason is `requested-empty`, and
  `empty_observations` keeps the answer's UTC timestamp. This is the
  Mirrulations rule: a key recorded as done can never come back for repair.

**Publication must consume the captures, not the readers.** The readers keep no
response bytes. The exact evidence is the `JsonPage.capture` of
`search_pages`/`docket_sheet_pages` and the `capture` of `file_list` and
`new_dockets`; a release built from reader rows alone has lost it.

## File bytes

[`sources/ferc/originals.py`](../../src/spicy_docs/sources/ferc/originals.py)
acquires a public original from the file list's `ID`, retaining its metadata
row, file-list digest and exact response. The browser's **Download File** link
uses `POST File/DownloadP8File` with this body for a selected GUID:

```json
{"FileType":"","accession":"","fileid":0,"FileIDAll":"","fileidLst":["0731EC70-0165-CA3E-91B7-912DB6700000"],"Islegacy":false}
```

The acquirer requires that the captured file list names the selected GUID
exactly once, under the requested accession, with `Availability_Mode:"P"`,
file name, MIME type and byte size. Missing or restricted metadata is refused
before any download. Responses must match the declared size and MIME type
(`application/octet-stream` is also accepted); HTML is refused, and PDF
originals require `%PDF-` magic and a trailer. A declared zero-byte original
that answers empty remains a `requested_empty` observation. Other file types
are retained as uninterpreted bytes; their formats are not structurally proved.
Numeric legacy identifiers and multi-file ZIP generation are outside this API.

On 2026-09-25 UTC, a fresh RM24-5 rulemaking-comment search reached its
terminal page in a two, two, one-row walk and agreed with `totalHits:5`.
Every accession offered one public PDF; all five original downloads matched
their file lists' byte sizes, totaling **1,815,666 bytes**. The first original
was identical through the browser and direct HTTP:
`sha256:c7ef927914a7a53d17ed0f3ddf4fc67143bfb91ccbd401bab162929510fc818f`,
241,123 bytes. Direct HTTP needed no cookies, `Origin`, or `Referer`.
The exact requests, metadata and originals are retained in
`scraper-delivery-2026-09-25T003133Z/ferc/originals-walk/` under the campaign
receipt directory named below.

[`sources/ferc/download.py`](../../src/spicy_docs/sources/ferc/download.py)
owns `File/DownloadPDF`, spelled from the bundle: a POST to
`DownloadPDF?accesssionNumber={acc}` (the publisher's own misspelled
parameter) with body `{"serverLocation": ""}`. Measured live 2026-09-24 for
the public accession `20251125-3057` (a letter order under ER25-3543):
`200 application/pdf`, 1,972,667 bytes of a generated seven-page PDF, no
wall, no redirect — one POST is the common case. When the first POST answers
400 with a JSON body naming `ServerLocation`, the acquirer sends exactly one
follow-up POST carrying that location, the SPA's own two-step contract. The
two POSTs share one operation budget (retries included) and the budget's
pacing. A 400 that names none is a publisher refusal with its body kept as
evidence; both steps' captures are retained. The house attachment rules apply: bounded bytes (16 MiB default,
640 MiB cap, carried from the measured regulations.gov bounds), `%PDF-` magic
and trailer proved, only 404/410 naming absence, a 200 with an empty body
recorded as `requested_empty`, refusals named (`client-rejected`,
`redirected`, `publisher-refused`) with evidence retained.

The two outputs are distinct: the browser's **Generate PDF** action for
`20240807-5052` returned 318,445 bytes in 9.272 seconds; the unchanged
production `DownloadPDF` acquirer then returned the identical generated PDF
in 8.80 seconds. Its digest is
`sha256:5273100b8280ce9cbd4784eece7590c3dc567a8c77cbe479b931a2ae61761ace`.
The earlier 45- and 60-second timeouts produced no responses and were not
reproduced by these controls. Their cause remains unclassified; they do not
establish a wrong request body, a missing file or a permanently unavailable
route. The older bundle's `GET File/DownloadFileNetFile/{GUID}` returned 404;
the current browser uses the POST route above.

The shared `walled_fetch` ladder is not climbed here on purpose: none of its
rungs can express a POST (its direct rung carries no body, and the Zyte and
Firecrawl rungs refuse non-GET), and the route is POST-only per the bundle.
The direct POST with the SPA's headers answered cleanly live; wall detection
still reuses `walled_fetch.detect_wall`, so a walled answer on this route is
named rather than misread. If this host ever walls this route, a POST-capable
rung belongs in the shared ladder, not in this module.

## Change and check

[`sources/ferc/elibrary.py`](../../src/spicy_docs/sources/ferc/elibrary.py)
owns the routes, request bodies, envelope readers, the SPA-header transport
every FERC client uses, and the body-paged walk shared by search and the
docket sheet;
[`download.py`](../../src/spicy_docs/sources/ferc/download.py) owns the
bounded generated PDF download;
[`originals.py`](../../src/spicy_docs/sources/ferc/originals.py) owns single
public P8 originals; [`vocabulary.py`](../../src/spicy_docs/sources/ferc/vocabulary.py)
pins the publisher's rosters;
[`readers.py`](../../src/spicy_docs/sources/ferc/readers.py) owns the four
`Reader` connectors and their one recovery rule.

```sh
uv run --frozen pytest -q tests/test_ferc_elibrary.py tests/test_ferc_download.py tests/test_ferc_discovery.py
```

Cover, as the tests do: the identity grammars and their rejections; the
search body's exact field set; the envelope refusals (`ErrorList`,
`success:false`, `numHits` disagreement); the walk's ends (short page, count
mismatch, moved count, page bound, repeats) and the evidence and traversal
counts every walk refusal carries; the caller-body validation; that the live
empty answer completes a walk as an observation; the new-docket window URL
spelling, date transform and `sort` grammar, the identity refusal before any
yield, the one-window one-GET walk keyed by `DocketFullNumber`, the ten-day
default window and the allowed override, and the requested-empty re-ask rule;
the docket-sheet body's measured wire spelling (lowercase dockets,
`MM-dd-yyyy` dates, zero-based `pageNumber`), the `DocumentsItem` flattening
with `AuthorsItem`/`FedCitesItem` verbatim beside each document, the
accession-identity refusal, the page walk by body `pageNumber` with the same
refusals (drift, mismatch, overserving, page bound, repeated accession,
missing `Page` envelope), and the sheet reader's verbatim documents; the SPA
headers on every request and one stable session id; the refusal/abort split
between 401 and 404; every reader's `last_keys`/`failed_keys` semantics under
the one recovery rule, including a refused input identity; that every live
new-docket identity feeds the comment and sheet readers; the download's
two-step contract, its refusals and its magic checks; and the vocabulary pins'
counts, the serial-numbered prefixes and the import-time check on
`RULEMAKING_COMMENT`. A
mock can only assert what it was written to send: qualify any change against
the live routes and retain the receipt.

## Open questions

- **Scope beyond the qualification docket.** Complete RM24-5 discovery and
  original-file acquisition establish that observed scope. Other dockets,
  large searches, changing totals, multi-page docket sheets, legacy file
  identifiers and other original formats still need their own qualification. Durable capture, publication and
  resume remain caller-owned workflows.
- **Terms of service.** No stated API terms were found for the WebAPI; it is
  the same public system the eLibrary UI drives, probed politely at 1–3 s
  intervals. Nothing here required credentials.

## Evidence

Live captures, their URLs and dates, and the synthetic fixtures' provenance
are in
[`tests/fixtures/ferc/README.md`](../../tests/fixtures/ferc/README.md). The
probes ran from a shell on 2026-09-24 against `elibrary.ferc.gov` and, once,
`www.ferc.gov/ferc-online/ecomment` (the 403); the SPA bundles the routes were
read from (`main`, `913`, `common`, `103`, `717`, `runtime`) were fetched the
same day, and the second probe session's receipts (the login replication, the
seven search spellings, the two live route captures, the DownloadPDF capture)
are retained under
`supply-2026-09-02/receipts/ferc-elibrary-2026-09-24/` outside the repository.
The later browser download trace, current bundle pins, direct controls and
complete original-file walk are retained at
`~/Work/corpora/supply-2026-09-02/receipts/scraper-delivery-2026-09-25T003133Z/ferc/`.
The 2026-09-24 re-probe of the search route (the full wire body, the body
variants, six same-session requests) is retained under
`~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-24/`, and the
2026-09-25 page-convention walk (RM24, 207 hits, pages one through three) is
one JSONL receipt at
`~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/search-page-convention.jsonl`.

The complete date/class search from
`tests/fixtures/ferc/advanced-search-all-dockets-request.json`, its live
vocabulary, offline replay, and per-row date/class checks are retained at
`~/Work/corpora/supply-2026-09-02/receipts/ferc-discovery-20260925T171543Z/`.
See `report.md`, `command.json`, `verification.json` and the capture's
`summary.json` for the observed scope, source pins and checks.
