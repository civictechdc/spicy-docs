# USITC EDIS: investigation dockets, documents and attachments from EDIS's own web service

Acquire USITC investigations and their dockets from the Electronic Document
Information System at `edis.usitc.gov`. Mirrulations holds no USITC, so EDIS
is the source of record for trade-remedy investigations (731-TA-…), section
337 proceedings, 332 studies and sunset reviews. EDIS is investigation-centric
rather than document-centric: one investigation number has one row **per
phase** (`Final`, `Prelim`, `Review`, `Review2`), and each phase row names its
own document listing — the docket.

| Route | Selection | Rows | Credential |
| --- | --- | --- | --- |
| `GET /data/investigation[/{number}[/{phase}]]` | Path number/phase; query `investigationType`, `investigationStatus` | `<investigations><investigation>`, paged by `pageNumber` | none |
| `GET /data/document` | Query `investigationNumber`, matched as a partial number (+ `investigationPhase`, `documentType`, `firmOrg`, `securityLevel`) | `<documents><document>`, paged by `pageNumber` | none |
| `GET /data/document/{documentId}` | One known document, including a feed-stated id | One document row in the same XML wrapper; one request | none |
| `GET /data/attachment/{documentId}` | One document | `<attachments><attachment>` metadata rows | none |
| `GET /data/download/{documentId}/{attachmentId}` | One attachment's PDF bytes | `application/pdf` stream | EDIS-issued Bearer token. `EDIS_TOKEN` supplied both offered PDFs of public document 894762 through the explicit Zyte route; direct access was walled during that qualification. |
| Web bulk-job endpoints or Download Basket → Download as ZIP → Job List | Selected public documents | Generated ZIP with attachments and an HTML index; direct HTTP creation, polling and download passed for public document 894762 in a receipt harness. The package validates a retained ZIP; it has no bulk-job client. | Signed-in EDIS web session and CSRF token. `EDIS_TOKEN` alone redirected to login on the tested status and ZIP routes. Larger batches remain unqualified. |
| `GET /external/rss/render.rss/` | Newly arriving documents | RSS 2.0 items | none |

## How the service was found, and what the host answers

EDIS publishes an XML web service under `/data`, documented in USITC's
[EDIS Data Web Service guide](https://www.usitc.gov/sites/default/files/press_room/documents/edis_data_web_service_guide.pdf)
(v1.1, 2024-06-14). It updates the 2010 guide's authentication instructions.
The retained
Wayback captures (2019–2023, one per route, trimmed row-by-row) parse with the
same XML structure the guide states. The public search UI is a web application at
`edis.usitc.gov/external/search`, and the RSS notification feed ships from the
same host.

**Access varies by request and time.** Earlier probes on 2026-09-24 found
Akamai's `Access Denied` on the sampled paths with curl and httpx, while
the same URLs served a real WebKit browser. The proxies also answered them:
Zyte `httpResponseBody` and Firecrawl v2
`rawBase64` both returned the real XML for the metadata routes (receipts
`zyte-client-smoke-2026-09-24`, `firecrawl-client-smoke-2026-09-24`). The
listing acquirer therefore accepts an `httpx.BaseTransport`. A later
direct download probe reached EDIS's authentication boundary without a wall:
anonymous GET answered 401 and the available DataWeb Bearer token answered
403. A previous wall is not proof that direct access always fails.

**The attachment-PDF route runs the shared walled ladder.** `acquire_attachment_pdf`
fetches `/data/download/{documentId}/{attachmentId}` through the shared
[`walled_fetch`](../../src/spicy_docs/sources/walled_fetch.py) ladder via
`SourceAcquirer.capture_walled`: DIRECT on the acquirer's own client and
transport, then ZYTE_HTTP and FIRECRAWL_RAW, so a wall on one rung
escalates instead of reading as the publisher's answer, and a clean 404/410
short-circuits to `UsitcEdisUnavailableError`. Measured 2026-09-24 on the
fixture locator (`/data/download/111112/111112`): the direct rung answered
the Akamai wall, the Zyte rung reached the origin and got **HTTP 401
without wall markers** — the guide's token requirement holds — and
Firecrawl's engines all failed (receipt
`usitc-edis-download-ladder-2026-09-24`). The ladder holds every answer to
the byte bound and the exact locator; the PDF proof stays in the module:
media type, `%PDF-` magic and trailer, final URL equal to the locator, and
agreement with the metadata route's declared `fileSize`.

**Downloads use a source-specific credential.** The [EDIS Data Web
Service guide](https://www.usitc.gov/sites/default/files/press_room/documents/edis_data_web_service_guide.pdf)
(v1.1, 2024-06-14) supersedes the 2010 guide's Basic
`username:secretKey` form: the EDIS web application's "API Token Generator"
issues an API token, sent as `Authorization: Bearer <token>`. Passing
`token=` to `acquire_attachment_pdf` takes the credentialed route — one
bounded direct GET carrying that header, in
[`credentialed.py`](../../src/spicy_docs/sources/usitc_edis/credentialed.py),
with the same proof gates afterwards. `credentialed_transport="zyte"`
explicitly selects the shared Zyte adapter for a known direct wall; it
forwards the Bearer header to the target, so the token is disclosed to Zyte.
A credential refusal never triggers fallback, and naming a transport without
a token refuses rather than taking the anonymous ladder. The token must be at
least 8 characters, the shortest secret the shared scrubber removes. It
travels only as the call argument (read at call time via `read_api_key`),
never in module state, locators or logs, and a credentialed 401/403 raises
`CredentialRefusedError` before body validation, with body retention
suppressed. Direct requests do not follow redirects, retry, or require a
proxy credential. Previous Bearer requests through Zyte failed
at its provider boundary with 520 (`usitc-edis-credentialed-2026-09-24`);
that result did not test token validity.

The later qualification in `scraper-completion-2026-09-24T235248Z/edis`
separated those boundaries. Public document 894762's metadata offered
attachment 2620262 and declared 216,215 bytes. Direct GET of that exact
locator returned 403 with the configured `DATAWEB_API_KEY`, then 401 in an
anonymous control. DataWeb's documented read-only saved-query endpoint
returned the same 200 empty-list response with and without the token, so
that control does not establish DataWeb token validity. Its locally decoded
JWT issuer was `dataweb`; this local decoding alone was not a
signature verification. The [DataWeb guide](https://www.usitc.gov/applications/dataweb/api/dataweb_query_api.html)
documents its separate token generator and API host. The configured
credential was refused for EDIS. No credentialed retry followed the 403,
and no confidential attachment was requested.

**The supplied EDIS token passed live qualification on September 25, 2026.**
`EDIS_TOKEN` in the workspace `.env` was sent through the existing
`credentialed_transport="zyte"` path as `Authorization: Bearer <token>`.
Fresh attachment metadata for public document 894762 offered two PDFs. Both
returned HTTP 200: attachment 2620262 contained 216,215 bytes and one page;
attachment 2620275 contained 3,357 bytes and two pages. Every byte count and
page count matched the metadata, and retained bytes passed offline PDF checks.
The total was 219,572 bytes. No transport implementation change was needed.

Direct metadata and the direct credentialed download answered 403. A separate
anonymous control returned access-denied HTML for the same download, so that
direct result did not establish token invalidity. The explicit proxy request
then reached the file successfully. This is qualification of one public
document's complete offered attachment set, not of an entire investigation or
permanent direct/proxy availability. Exact evidence, source pins and runnable
checks are retained under campaign receipt `edis-token-qualification-2026-09-25`.

## The investigation filters, measured

The guide documents two investigation query filters. Measured live
2026-09-24 through a browser-backed transport, against the returned rows'
own fields (receipt `usitc-edis-filters-2026-09-24`):

- `investigationType` **applies**: every row returned for `Sec 337` stated
  type `Sec 337`.
- `investigationStatus` **applies under the guide's parameter-table
  spelling** (camelCase): `?investigationStatus=Active` returned rows that
  all state `Active`, from a different slice of the listing than the
  unfiltered first page.
- The guide's example-URL spelling `investigationstatus` (all lowercase,
  the spelling the 2019 Wayback capture of this route also carried) is
  **ignored** in 2026: Active, Inactive and a nonsense value all answered
  the same unfiltered first page, byte-identical. The URL builder therefore
  writes `investigationStatus`, and callers that keep lowercase URLs should
  filter the rows instead — the proven fallback.

## The listing walk, and what its pages mean

The guide documents one pagination contract: up to 100 rows per request under
a `pageNumber` query parameter, and an **empty** page beyond the last row. The
walk advances the page number it generated, stops at the first empty page, and
refuses to end any other way: a repeated row identity, more than 100 rows on
one page, or a page bound reached before the empty page. A first page that
answers empty is a requested-empty observation of that query on that day, not
source absence.

**A walk sees a shifting listing in one direction only.** An insertion into
pages already read pushes a served row onto the next page; the repeat
refuses. A deletion from pages already read pulls an unread row back onto a
page already read; the walk skips it silently and still ends clean. No
declared total travels with the rows, so no count can reveal the skip, and the
pooled walks in [`reading/paged_json.py`](../../src/spicy_docs/reading/paged_json.py)
do not apply because they settle against a declared total. Periodic re-walks
and targeted `document(id)` refreshes are the reconciliation.

**An EDIS investigation is its phase.** `731-1103` Final, Prelim, Review and
Review2 are four rows with four document dockets. The reader therefore reads
exactly one `(number, phase)` pair, and proves the phase exists on the
investigation listing before requesting any document — a complete listing
walk that states no such phase refuses, rather than reading an empty docket
as the docket's contents.

**The document query matches a partial number.** The guide says partial
investigation numbers may be specified, and the publisher does match them:
on 2026-09-25 `investigationNumber=337-145` answered 20 rows, every one for
337-1451, 337-1453 or 337-1454 and none for 337-145, while `337-1458`
answered only its own rows (receipt
`edis-partial-number-probe-2026-09-25`). A docket whose number is a prefix of
another would therefore receive the other's documents. The reader keeps a row
whose number extends the requested one on `partial_match_rows` (document id,
number, phase and page digest) and leaves it out of the docket; it applies the
same rule to the investigation route, whose matching is unmeasured. A row with
any other number, or with another phase under the exact number on the
document listing, still refuses the pass with its page retained. Both
document reads that day answered exactly 20 rows on page 1; the walk depends
only on the empty terminal page, not on a page size.

## Identity keys

- **Investigation**: the pair `(number, phase)` — `("731-1103", "Final")`;
  the publisher's `docketNumber` is its own internal key for the same phase
  and is absent in older rows, so it is not the identity here.
- **Document**: the publisher's numeric `id` (e.g. `793615`); it is stated in
  every route that names the document and in the feed's `<guid>`.
- **Attachment**: the numeric `id` within one document; its download locator
  is `/data/download/{documentId}/{attachmentId}` when the metadata route
  offers one in `downloadUri`. An explicit empty `<downloadUri/>` is retained
  as `None`; the document and attachment metadata remain usable, and no
  download URL is invented. See the [retained empty-URI fixture](../../tests/fixtures/usitc_edis/README.md).

Party fields (`firmOrganization`, `filedBy`, `onBehalfOf`) are kept where the
publisher states them; `securityLevel` marks `Public`/`Confidential` rows.
Dates arrive in at least three publisher spellings across capture eras
(`2020/07/09 00:00:00`, `2023/04/03 00:00:00`, and the guide's
`2005-01-25 00:00:00.0`), so every date is kept verbatim, never read.
The optional attachment `originalFileName` is retained as metadata; it can be
an internal publisher path and must not be used as a local output path. The
guide notes that `lastModifiedDate` may reflect OCR processing rather than a
textual change, so it does not establish that a file's content changed.

## Efficient mirror reads

Build the initial inventory with paginated investigation and document queries.
Use `document_list_url(security_level="Public", ...)` when the caller wants
public documents; anonymous metadata can otherwise include limited and
confidential documents. Follow each document's offered attachment metadata and
download URLs.

For a known document id, including one announced by `parse_edis_feed`, call
`record, capture = acquirer.document(document_id)`. This makes one bounded GET
to `/data/document/{documentId}` and checks that the response names that id.
It returns `None` with the retained capture for an empty success, while 404/410
raise `UsitcEdisUnavailableError`. Wrong identities and multiple rows refuse
with evidence. The live single-document response for 894762 is retained in
receipt `edis-guide-review-2026-09-25` and the corresponding test fixture.

The web-service guide documents no update-date filter, cursor, declared total,
or adjustable page size. The feed is a notification window; refresh known ids
directly and periodically re-walk listings to reconcile the mirror. The separate
bulk guidance below provides a ZIP workflow for selected public documents.
SpicyRegs owns scheduling, persistence, deduplication and retry state. This client
supplies the source reads and evidence.

### Bulk ZIP backfills

USITC's [EDIS Bulk Download Guidance](https://www.usitc.gov/docket_services/documents/edis_bulk_download_guidance.pdf),
linked from its [current support page](https://www.usitc.gov/press_room/edissupport.htm),
documents a Download Basket and background ZIP jobs. This newer guidance changes
the backfill options beyond the 2024 web-service guide:

- **Selection:** the detailed instructions allow external users to add only
  public documents, although searches can expose limited/confidential metadata
  and the overview uses broader language (page 1).
- **Bounds:** at most 400 total attachments across selected documents, plus a
  size limit written as “1,500 Mb (1.5 Gb)” in the guide. Exceeding the size
  limit prevents completion. Treat the basket's displayed size as authoritative
  until its exact byte threshold is qualified (page 3).
- **Delivery:** Download as ZIP starts a job; Job List exposes progress and the
  finished file. Its Document Count is not an attachment count (pages 3–4).
- **Evidence:** the ZIP includes an index with metadata and file links, with
  multiple entries for a document that has multiple attachments. The screenshot
  shows an HTML index beside the PDFs (page 5).

**A small live job passed on September 25, 2026.** Starting with an empty basket
and job list, the signed-in web application accepted public document 894762,
displayed two attachments and 0.22 MB, and completed one document. Its ZIP
contained both PDFs and `index.html`; both PDF digests and sizes matched the
previous EDWS captures exactly. Shared ZIP inspection verified every member's
CRC and digest. Receipt `edis-browser-recovery-2026-09-25` retains the archive,
index, job observations and comparison. This qualifies the selected document,
not the guide's maximum batch size or a whole investigation.

The index has one row per attachment. Its file link is the archive member:
`894762-0-2620262.pdf`; the visible label is `894762-2620262.pdf`. Preserve both
spellings and use the link for membership. Document identity, attachment
identity, declared size and exact member coverage must agree with the selected
API attachment metadata before marking a batch complete.

[`inspect_bulk_archive`](../../src/spicy_docs/sources/usitc_edis/bulk.py) performs
that reconciliation for a retained ZIP. It
reuses the shared streamed ZIP inventory, which inflates each member once:
the same pass that verifies every CRC and digest also yields the index bytes
and each PDF's bounded header and trailer. It keeps the exact index bytes and
all index columns, and returns member ordinals and digests without extracting
files. It refuses missing, unexpected, duplicate or unsafe members, non-public
index rows, identity/size mismatches and invalid PDF headers or trailers. Supply
the complete expected attachment set for this batch; the reader cannot discover
omissions from a caller's incomplete selection.

For the qualified document, with its XML and ZIP already retained:

```python
from pathlib import Path
from spicy_docs.sources.usitc_edis import inspect_bulk_archive, parse_attachments

expected = parse_attachments(
    Path("attachment-894762.xml").read_bytes(),
    document_id=894762,
)
archive = Path("download.zip")
with archive.open("rb") as stream:
    bulk = inspect_bulk_archive(
        stream,
        byte_size=archive.stat().st_size,
        expected_attachments=expected,
        max_decoded_bytes=8 * 1024**2,
    )
# bulk.index_bytes preserves the source index. Each row's member_ordinal
# points into bulk.inventory["members"], including its verified SHA-256.
```

Keep the archive digest, selection and acquisition receipt with this result.
The size limits are caller safety bounds, not claims about publisher capacity.

For backfills, use these ZIPs to consolidate public-file transfers, retaining
the API for metadata discovery, targeted updates and unresolved files. This
small sample does not measure throughput improvement or large-batch limits.
The bulk guide documents the web-application workflow; its browser JavaScript
also exposes ordinary HTTP job endpoints. These use separate authentication
from the EDWS Bearer token.

**Direct HTTP creation, polling and download also passed on September 25.**
After the user signed in, a Python `httpx` process received the browser session
and CSRF token through an in-memory pipe. It created a new job for public
document 894762, polled to completion and streamed its ZIP without browser
requests or a proxy. Both PDFs again matched the retained EDWS bytes, and
`inspect_bulk_archive` verified the exact expected attachment set. Receipt
`edis-direct-bulk-2026-09-25` retains the bounded replay script, request paths,
selected job fields, exact ZIP and comparison results. Session values were
not retained.

The document page's actual `data-dl-*` attributes and the site's JavaScript
provided this request sequence:

| Operation | Observed request |
| --- | --- |
| Create the selected document's ZIP job | `POST /external/attachment/download/bulk/SEARCH_DOC_DETAILS/894762`, with form body `documentIds%5B%5D=894762&fileName=894762` |
| Read status | `GET /external/bulkDownload/poll/download-job/{artifactId}` |
| Download the finished ZIP | `GET /external/attachment/download.zip?artifactId={artifactId}` |

Creation returns `job.artifactId`; completion requires `isCompleted: true`
and `status: "Complete"`, with the selected document count reconciled. The
site polls every ten seconds. The live test used the observed document-detail
source and selection; it does not establish arbitrary source names or
multi-document batching through that route. The account's Download Basket
was not changed.

The session includes a `JSESSIONID` cookie scoped to `/external`; selecting
cookies only for the origin's `/` path omits it. The page's `_csrf` and
`_csrf_header` metadata supplies `X-CSRF-TOKEN`. Keep these values in memory,
forward them only to the intended EDIS paths and stop on authentication
refusal or a login redirect. With the browser's request headers,
`EDIS_TOKEN` alone and an anonymous control both redirected to login on the
status and ZIP routes. The ZIP redirect even declared `application/zip`,
so content type alone cannot establish a successful download.

The reusable package currently supplies metadata, individual PDF acquisition
and offline ZIP reconciliation. Direct bulk requests are qualified in the
receipt harness; they are not yet exposed as a package client. A future thin
adapter should expose one create, one status read and one bounded download.
Do not automatically retry an uncertain create POST; retain its artifact ID
for recovery once returned. Login renewal, polling and durable job state
remain caller responsibilities.

Reuse the shared transport for these requests, minding how each client treats
the session credentials. [`BoundedAcquirer`](../../src/spicy_docs/transport/download.py)
streams large files, but it only sends `GET`, follows redirects, and checks
for echoed credentials by comparing whole header values. A `Cookie` header
holds `JSESSIONID=<value>`, so a response echoing only the value (for example
`;jsessionid=` URL rewriting on a login redirect) would pass that check.
[`BoundedHttpCapture`](../../src/spicy_docs/transport/capture.py) sends the
create `POST` and never follows a redirect, so a login redirect refuses. Use it
for create and status, and add a per-component echo check (the session id and
the CSRF value, each on its own) before either client carries these values.
Scheduling, retained job state and recovery stay in SpicyRegs. No separate job
database or acquisition framework is needed.

## Use the routes

Install the `acquisition` extra. Metadata acquisition needs no EDIS
credential; a chosen proxy transport needs its own provider credential.
The download token is supplied separately for each call.

```python
from spicy_docs.sources.usitc_edis import (
    EdisAcquirer,
    EdisBudget,
    UsitcEdisReader,
    investigation_url,
    document_list_url,
)

budget = EdisBudget(
    max_requests=64,
    max_page_bytes=4 * 1024**2,
    max_download_bytes=16 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=1.0,
)
# Live: transport=browser_backed_transport; see sources/zyte.py.
with EdisAcquirer(budget=budget) as edis:
    for page in edis.investigations(investigation_url(number="731-1103")):
        for row in page.records:
            print(row.number, row.phase, row.document_list_url)
    for page in edis.documents(document_list_url(investigation_number="337-3673", investigation_phase="Violation")):
        for row in page.records:
            print(row.id, row.document_type, row.document_date)

    reader = UsitcEdisReader(
        budget=budget,
        investigation_number="337-3673",
        investigation_phase="Violation",
        retry_keys=previous_run_failed_document_ids,
    )
    for record in reader.iter_records():
        ...  # one complete document: publisher row + attachment metadata
    print(reader.last_keys, reader.failed_keys)
```

`UsitcEdisReader` follows the fetcher rules. Records are yielded only
complete — document row plus its attachment metadata page — so `last_keys`
names the documents that produced one and `failed_keys` the documents whose
attachment page did not answer, for the next run to retry first (via
`retry_keys`). A listing failure yields nothing and raises: no docket can be
established from a refused listing, and a later run re-asks from scratch.
A retry key the listing no longer states is surfaced on `unlisted_retry_keys`
for the caller to resolve, never silently dropped. `fail_fast` turns a
failed attachment page into an immediate raise. A 404/410
on an exact requested locator raises `UsitcEdisUnavailableError` (with its
capture attached), never a zero.

The PDF route is separate: `acquirer.acquire_attachment_pdf(download_uri,
declared_size=row.file_size)` runs the shared ladder. The acquirer reads
`ZYTE_TOKEN`/`FIRECRAWL_API_KEY` from the environment once, for its proxy
rungs — those are ladder credentials, never part of the EDIS locator — and
the module's PDF proof applies to whichever rung answered. With an EDIS API
token, pass it per call to take the credentialed route instead:

```python
from pathlib import Path

from spicy_docs.transport.credentials import read_api_key

download, capture = acquirer.acquire_attachment_pdf(
    download_uri,
    declared_size=row.file_size,
    token=read_api_key(Path("../.env"), "EDIS_TOKEN"),
    credentialed_transport="zyte",  # forwards the EDIS token to Zyte
)
```

The token is read at call time, sent as `Authorization: Bearer`, and never
stored in the acquirer; a credentialed 401/403 raises
`CredentialRefusedError` with its body suppressed. Other wall-marked answers
raise `UsitcEdisSourceError` with the capture retained. `EDIS_TOKEN`
must contain a token generated in the authenticated EDIS application's
API Token Generator. The variable name is a local configuration convention,
not an alias for DataWeb's credential. The example reads the workspace root
`.env` when run from `spicy-docs`; select the credentials path for your caller.
It explicitly selects the qualified proxy route, which also requires
`ZYTE_TOKEN` in the process environment and sends the EDIS token to Zyte as a
target header: use it only where that disclosure to the proxy is acceptable.
Omit that transport argument to use direct HTTP where it is available.
Regenerate the EDIS token through its API Token Generator after the displayed
expiry date and replace the local value.

Metadata and download attempts share the same pacing clock. Each download
operation resets `request_count`, and its `max_requests` limits the anonymous
ladder as well as direct or explicitly selected proxy acquisition. A ladder
provider without a credential is skipped: it makes no request, so it is
neither counted nor paced. The explicit credentialed Zyte route counts its
one attempt even when its provider credential is missing, a conservative
acquisition-attempt count rather than a billable-request count.

The RSS feed (`parse_edis_feed`) announces newly arriving document ids for
targeted refresh; complete docket discovery still uses the `/data` listing.
The feed's internal
investigation id (`CRITERIONINVDEL:5193`) is not the `/data` `docketNumber`.

## Change and check

[`sources/usitc_edis/api.py`](../../src/spicy_docs/sources/usitc_edis/api.py)
owns the locators, the walk and the acquirer;
[`records.py`](../../src/spicy_docs/sources/usitc_edis/records.py) owns the
row parsers and identity grammar;
[`attachments.py`](../../src/spicy_docs/sources/usitc_edis/attachments.py)
owns the PDF route;
[`credentialed.py`](../../src/spicy_docs/sources/usitc_edis/credentialed.py)
owns the direct and explicitly selected Zyte credentialed download requests;
[`feed.py`](../../src/spicy_docs/sources/usitc_edis/feed.py) owns the
notification feed; [`reader.py`](../../src/spicy_docs/sources/usitc_edis/reader.py)
owns the `Reader` connector; [`bulk.py`](../../src/spicy_docs/sources/usitc_edis/bulk.py)
owns retained bulk-ZIP reconciliation.

```sh
uv run --frozen pytest -q tests/test_usitc_edis.py tests/test_usitc_edis_bulk.py
```

Cover, as the tests do: the locator grammar and its credential-refusal rule;
both date spellings pinned verbatim; empty elements reading as absent;
the walk's ends (empty terminal page, repeated identity, oversized page, page
bound, missing page parameter) and its 404-as-unavailable rule; the PDF proof
(magic, trailer, final URL) and the walled-ladder mock — a clean ladder
answer, a 404-as-absence, a refusal passthrough, and every proof still
applied to ladder bytes; the credentialed route — the bearer header the
request sends, every proof applied to credentialed bytes, a wall and a
401/403 passing through with body suppression and route context retained and the
token never in an error, and bad tokens refused before any rung — with the
listing seam untouched; the feed's guid/anchor agreement and confidential
flags; and one pilot investigation read end to end with
`last_keys`/`failed_keys`, retry-first ordering, unlisted retry keys,
partial-number rows kept as evidence outside the docket, fail-fast
and the two emptiness rules; and, for a retained bulk ZIP, exact membership,
public rows, declared sizes, unsafe or corrupt members and the single inflate
pass. A mock can only assert what it was written to send: qualify
any change against the retained captures and the live routes, and retain the
receipt.

## Open questions

- **Bulk client integration and broader qualification.** A small basket job
  and a separate direct-HTTP document job both passed. Expose the qualified
  requests through a thin client, then qualify multi-document batches,
  session/job recovery and byte/count bounds before claiming faster
  full-investigation capture. See receipts `edis-browser-recovery-2026-09-25`
  and `edis-direct-bulk-2026-09-25`.
- **A complete selected public investigation and recovery.** The EDIS-issued
  token now passes for every offered file of public document 894762. Broaden
  this to a complete selected investigation and retry/recovery qualification;
  one document's success does not establish full docket acquisition. Direct
  access remains variable, and the caller explicitly chooses the proxy route
  when direct access is walled.
- **Registration.** No EDIS account, token or registration is needed for the
  metadata routes or the feed. The token requirement applies to the
  download route, confirmed by the 401 measured above; the credentialed
  seam exists (`token=` per call) and the module never stores the token.

## Evidence

Fixture provenance, the row-level trims and the live re-verification of the
routes are in
[`tests/fixtures/usitc_edis/README.md`](../../tests/fixtures/usitc_edis/README.md).
Probes ran on 2026-09-24 from a shell and, for the denial measurement, a
real-browser fetch; the Wayback captures that became fixtures were archived
2019–2023. The walled-ladder probe of `/data/download/111112/111112` (direct
wall, Zyte 401 without wall markers, Firecrawl engines failed) is receipt
`usitc-edis-download-ladder-2026-09-24`, the credentialed-download probe and
its anonymous control are receipt
`usitc-edis-credentialed-2026-09-24`, and the filter verification (type
applies; `investigationStatus` camelCase applies; lowercase ignored) is
receipt `usitc-edis-filters-2026-09-24`, all in the campaign receipts.
