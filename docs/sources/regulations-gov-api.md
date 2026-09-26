# Regulations.gov through the official API

Capture documents from the keyed `api.regulations.gov` v4 routes, and their PDF
renditions from the keyless `downloads.regulations.gov` host. This is the live,
per-document route. The bulk route stays the
[Mirrulations S3 mirror](regulations-gov.md); the two are separate observations
of the same publisher and neither supersedes the other.

| Route | Selection | Rows | Credential |
| --- | --- | --- | --- |
| Document list | Posted-date and/or last-modified window, docket, agency, search term | `data` | api.data.gov key |
| Document detail | One document id | one `data` object | api.data.gov key |
| Docket detail | One docket id | one `data` object | api.data.gov key |
| Attachments relationship | One document id | `data`, unpaged | api.data.gov key |
| Attachment or content PDF | One publisher-declared `fileFormats[].fileUrl` | the file | none |

The docket detail is the object the mirror retains as
`text-<docket>/docket/<docket>.json`. It fills dockets the mirror never
captured: on 2026-09-26, 165 dockets named by mirrored documents or comments
had no docket record in the mirror, and the API still served some of them. It
answers 404 for a docket it no longer publishes, and 400 "Invalid ID" for an id
outside its grammar, such as legacy `-RULEMAKING` suffixes. These are different
answers, and `docket()` raises them differently.

## The list pages, and what their numbers mean

The list is built on the [shared paged-JSON traversal](listings.md): the family
states the host, the `X-Api-Key` header and `meta.totalElements` as data, and
the shared reader owns capture, byte bounds, the credential-echo refusal and
the JSON rules. Three facts pinned from live bytes on 2026-09-14 shape the rest
(receipt `supply-2026-09-02/receipts/port-P05-regulations-gov-2026-09-14`):

- **There is no `links` object.** A windowed page and a docket-filtered page
  both answered with exactly two top-level keys, `data` and `meta`. The
  continuation is `meta.hasNextPage` together with the current
  `meta.pageNumber`, so `documents()` advances `page[number]` itself and every
  requested URL is caller-authored. The family still names `links.next` as its
  continuation path — the JSON:API spelling — so a page that ever does supply
  one is noticed rather than silently ignored: it refuses, naming the check.
- **`meta.totalElements` is the query's size, not what a walk can reach.**
  `page[number]` is capped at 40 whatever the page size: `totalPages` read 40
  at `page[size]=250` and 40 at `page[size]=100` alike, and page 41 answered
  `400 Page number parameter is greater than allowed. Maximum value is 40.`
  A query matching 57,383 documents exposes at most `40 × page[size]`, so
  window by date until a walk fits. `DocumentListPage.reachable_elements`
  states that bound; running into it is a refusal, not an end.
- **The declared count moves while you walk.** One fixed
  `filter[postedDate][ge]=2026-01-01` query declared 57,380 and then 57,383
  eighty-five seconds later. A count is the publisher's statement for that
  query at that instant, and zero is not absence.

Every page's `meta` is read from the retained bytes, not inferred from the
request, and the publisher's three statements about the same page are
cross-checked: `pageNumber`/`pageSize` against what was asked for,
`numberOfElements` against the rows that arrived, and `hasNextPage` against
`lastPage`. A page served for a different request, or truncated, refuses rather
than reading as a short last page. That second parse costs 0.38 ms on the
9,029-byte five-row fixture and 9.8 ms on a 211,509-byte 250-row page, against
1.1–2.6 s of wall time for the request itself.

Bounds and sorts are the publisher's own, quoted from its `400` bodies:
`page[size]` is 5 to 250, `page[number]` at most 40. Sorting accepts
`commentEndDate`, `lastModifiedDate`, `postedDate` and `title`, each optionally
prefixed `-`; `agencyId` and `documentType` answer `400 Invalid 'Sort By'
fieldName` and are therefore not offered. The rate limit observed on
2026-09-14 was 1,000 requests per hour, and api.data.gov meters GovInfo and
regulations.gov against **one** budget — do not run a GovInfo census beside a
document walk.

The list row is a projection, not the record: it carries `lastModifiedDate` and
`highlightedContent`, which the full document does not, and omits most of the
detail's attributes. Read identity and dates from the list; read the record
from the detail route.

One publisher, two media types: the list route answers `application/json`
while the detail and attachment routes answer
`application/vnd.api+json;charset=utf-8`. The shared page reader requires
`application/json`, so those two routes are captured directly on the shared
acquirer instead, accepting either spelling and repeating the page reader's
credential-echo refusal. This was found only by running the modules against
the live publisher: the offline tests had asserted `application/json`
everywhere because the mock was written to send it.

## The files, and the host that serves them

Every file the publisher knows about is declared as a `fileFormats[].fileUrl`
on the document's own `attributes` or on an attachment row. Those URLs are the
only locators this route accepts — it parses the publisher's spelling and
checks its grammar, and never builds one from an id and a guessed extension.
Two file names occur, both under `https://downloads.regulations.gov/{documentId}/`:
`content.{ext}` for the document's own rendition and `attachment_{n}.{ext}` for
an attachment's. Across 2,745 declared renditions on 2,676 documents in the
retained 2026-09-05 attachment sample, every declared URL had exactly that
shape, on that host, with no query and no fragment.

- **The host takes no key and must not be sent one.** Keyless and keyed
  requests for the same file returned the identical 200, 2,620 bytes and
  digest. It is S3 behind CloudFront, not api.data.gov, so it costs nothing
  from the hourly budget.
- **It refuses a non-browser User-Agent.** With
  `spicy-docs-regulations-gov/1.0` the same URL answered `403` with a 919-byte
  HTML page; with the browser agent it answered 200 and the file. The agent is
  a named constant carrying its evidence, because without it the whole route
  reads as "the unmetered host does not work", which is a clean and completely
  wrong answer.
- **Its two `403`s are named, and neither establishes absence.** A rejected
  client gets `403` with a 919-byte CloudFront block page — `text/html`,
  `Server: CloudFront`, `Request blocked.`, and a per-request `Request ID` that
  changes its digest every time. A key the host serves nothing at gets `403`
  with S3's 111-byte `application/xml` `<Code>AccessDenied</Code>` document —
  `Server: AmazonS3`, digest
  `a824bc7739e226e1b40ea0f8c4e4f4c6f796fc3b4abfa6e9abe3bd119a30d938`, the same
  bytes on both 2026-09-14 captures. Because the route is keyless the shared
  capture client retains the refusal body, so `attachment_refusal_kind()` reads
  which refusal it is from those bytes and
  `RegulationsGovAttachmentRefusedError` carries it as `refusal_kind`:
  `"client-rejected"`, `"object-access-denied"`, or `"unrecognized"` for a body
  in neither shape rather than a guess. It stays a `CredentialRefusedError`
  subclass, so every caller that aborts on a refusal still aborts.
  **`object-access-denied` is the bucket policy speaking, not a missing file**:
  the body states a permission decision and says nothing about existence, and
  S3's own missing-object answer (`NoSuchKey`, `404`) has never appeared on
  this host. Only `404`/`410` —
  `RegulationsGovAttachmentUnavailableError` — is this host saying the exact
  URL has nothing. The classification is read from the publisher's words, not
  from the byte count or the media type, so it does not depend on a length the
  host is free to change; it is qualified in the tests against all six
  retained refusal bodies from both 2026-09-14 receipts.
- **Identity is proved four ways**: `application/pdf`, the `%PDF-` magic, a
  final URL equal to the locator, and — when the publisher declared a size —
  a byte count equal to it. Declared equalled actual on all 1,324 documents
  that yielded files in the 2026-09-05 sample, so the size check is a real
  binding the publisher passes. The magic check earns its place separately:
  three of those 2,736 files were named `.xlsx` and began with the OLE2
  signature of a legacy `.xls`. A `format` of `pdf` is a claim; `%PDF-` is
  evidence.
- **Bounds come from measured files.** Median 289,436 bytes, 95th percentile
  5,913,955, maximum 562,644,355 across those 2,736 files. The 16 MiB default
  covers 98.7% of them and the 640 MiB cap clears the maximum, so the tail is
  reachable by an explicit caller bound rather than silently truncated.

Two shapes have no error to announce them and both would otherwise produce a
clean, confident, wrong count. One attachment is commonly published in several
formats of the same pages — 2,745 renditions across 2,509 attachments — so
counting `fileFormats` entries overstates attachments and double-counts bytes.
And an attachment can exist with `fileFormats: null` and a
`restrictReasonType`: withheld content, which is a different answer from no
attachment. `declared_files()` returns one entry per rendition and an empty
tuple for the withheld case, so both stay visible.

## Use the routes

Install the `acquisition` extra. Read the key with `read_api_key`; the variable
name across the api.data.gov publishers is `API_GOV`.

```python
from pathlib import Path

from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.regulations_gov.api import RegulationsGovApiReader, document_list_url
from spicy_docs.sources.regulations_gov.attachments import (
    AttachmentBudget,
    RegulationsGovAttachmentAcquirer,
    declared_files,
    pdf_files,
)
from spicy_docs.transport.credentials import read_api_key

budget = PagedJsonBudget(
    max_requests=3, max_page_bytes=16 * 1024**2, timeout_seconds=60, min_request_interval_seconds=3.7
)
with RegulationsGovApiReader(budget=budget, api_key=read_api_key(Path(".env"), "API_GOV")) as api:
    url = document_list_url(posted_from="2026-09-02", posted_to="2026-09-02", page_size=250, sort="postedDate")
    for page in api.documents(url, max_pages=40):
        print(page.page_number, page.total_elements, page.reachable_elements, page.document_ids)
    detail = api.document("FAA-2016-6907-0001")
    files = declared_files(detail.data) + pdf_files(api.attachments(detail.document_id).records)

with RegulationsGovAttachmentAcquirer(budget=AttachmentBudget(2, 16 * 1024**2, 60, 1)) as host:
    for file in files:
        if file.locator.is_pdf:
            got = host.acquire_pdf(file)
            print(got.locator.file_name, got.capture.byte_size, got.sha256)
```

`DocumentListPage` carries the shared `JsonPage` (exact bytes, URLs, status,
time, hash; rows with decimal numbers preserved) plus the publisher's paging
statement and the page's document ids. `AttachmentAcquisition` carries the
locator, the exact capture and the declared size. Retain `capture.body` in
caller-owned storage; the parsed views are a reading of those bytes, not
evidence.

## Change and check

[`sources/regulations_gov/api.py`](../../src/spicy_docs/sources/regulations_gov/api.py)
owns the list and detail routes;
[`attachments.py`](../../src/spicy_docs/sources/regulations_gov/attachments.py)
owns the locators and the file capture. Both reuse this package's document-id
grammar, so an id that the Mirrulations profiles refuse is refused here too.

```sh
uv run --frozen pytest -q tests/test_regulations_gov_api.py tests/test_paged_json.py
```

Cover the paging statement's three cross-checks, the `page[number]` bound, both
media-type spellings, the locator grammar for both file names, the
withheld-attachment shape, the credential-echo refusal on a list page and on an
item route, each of the four identity proofs on the file, and both named
refusal kinds — including that an unrecognised `403` stays unrecognised and
that a refusal is never read as absence. Offline tests alone cannot see a media
type the mock was written to send: qualify a change against the live routes as
well, as the receipt records.

## Evidence

Pinned pages with hashes are in
[`tests/fixtures/listings/README.md`](../../tests/fixtures/listings/README.md)
and the file in
[`tests/fixtures/regulations_gov_attachments/README.md`](../../tests/fixtures/regulations_gov_attachments/README.md).
The fixture PDF's digest matches the one recorded independently nine days
earlier in the pinned PDF floor population, by a different tool. Headers, the
refused `400`/`403`/`404` bodies, rate-limit readings and the attachment-size
measurements are in
`corpora/supply-2026-09-02/receipts/port-P05-regulations-gov-2026-09-14/` and
`corpora/supply-2026-09-02/receipts/attachment-sample-2026-09-05.md`. The two
`403` shapes were re-probed on 2026-09-14 through this module and again through
plain HTTPX in
`corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-14/q2-regulations-gov-403/`:
one request per case per tool, which establishes that the shapes still hold and
nothing about how often either is served.
