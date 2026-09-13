# Acquire official FEC data

SpicyDocs reads official Federal Election Commission (FEC) metadata and acquires
selected originals separately. Use bulk XML listings for historical backfills,
OpenFEC JSON for filtered records and relationships, and XML sitemaps for website
publications. Use HTML link discovery when a collection has no structured index.

The library is `spicy_docs.sources.fec.client.FecClient`; the command is
`spicy-docs-fec`. Install the `acquisition` extra for HTTP access. These are raw
acquisition APIs, like the CourtListener reader. They do not publish sealed
releases, normalize financial tables, or manage a dataset across runs. The
separate committee and filing-query profiles below reuse the existing release
publisher without adding a second publication pipeline.

## Choose a collection and route

Run the offline registry to see the exact paths, filters, original bulk-family
labels and collection indexes:

```sh
uv run --frozen spicy-docs-fec collections
```

The packaged [collection registry](../../src/spicy_docs/sources/fec/official_sources.json)
and [API response modes](../../src/spicy_docs/sources/fec/api_operations.json)
come from the [retained research](../research/fec-data-2026-09-11.md). The latter
covers the GET operations in that research's official Swagger capture, including
finite name lists and the calendar CSV/ICS export. An operation declaration does
not establish that every filter or historical period has been acquired live.

| Official data | Preferred acquisition | Additional originals and scope |
| --- | --- | --- |
| Committee and candidate identities, affiliations, sponsors and candidate–committee links | Bulk master/linkage/leadership files; JSON histories and identities | Keep candidate IDs, committee IDs and source cycle separately. |
| Reports, filings, Forms 1/2/3/3X/3P/5/6/9/13/99 and electronic submissions | Bulk filing inventories and raw dumps; JSON filings, reports, efile and operations log | Independently fetch publisher `.fec`, PDF, CSV and text links. Efile and processed filings are different stages. |
| Contributions, disbursements, intercommittee transactions and independent expenditures | Bulk files and raw schedule archives; JSON A/B/E and aggregates | Keep amendments, memo indicators, transaction IDs, period, schedule and source version. Overlapping exports are not additive. |
| Loans, debts, guarantees, party allocations and special accounts | Raw schedule archives; JSON C/D/F/H4 and national-party accounts | Do not claim that a processed API subset exhausts the original filings. |
| Electioneering, communication costs, bundling and inaugural committees | Published bulk families; JSON where declared in the registry | Forms and original reports fill gaps in structured API coverage. |
| Financial summaries, statistics, presidential aggregates and public funding | Published summary files and JSON; public-funding collection links | Source totals and detailed transactions retain their separate units. |
| Election results, election/reporting calendars and state-office references | JSON calendar/date/reference routes; native result spreadsheets/PDFs | Calendar export is CSV/ICS and uses `download`, not the JSON iterator. |
| Statutes, regulations and rulemakings | Legal/rulemaking JSON, `legal/` XML listing, collection links | Preserve legal IDs and attached originals. FEC's legal bucket does not cover every court/audit/website publication. |
| Advisory opinions, MURs, administrative fines and alternative dispute resolution | Legal JSON search/details and `legal/` XML listing | Legal search uses `from_hit`/`hits_returned`; detail responses contain cases with nested documents. |
| Audits and court cases | Audit JSON; court/audit collection links and website sitemaps | Follow selected detail-page links to attachments. A collection index is discovery evidence. |
| Guidance, forms, manuals, meetings, agendas, minutes, news and historical website material | XML sitemaps, calendar JSON and collection links | Acquire selected XML/JSON/XHTML, PDF, media or explicit HTML originals. |
| FOIA, agency strategy/budget/performance, annual, privacy, procurement, operations and Inspector General reports | Report collection links and XML sitemaps | Prefer declared FOIA XML. The historical 2009 `.xml` publication has a different representation; an extension does not establish schema parity. |
| Data dictionaries, raw archive instructions and quality notices | Bulk XML listings and source collection links | Keep these alongside downloaded files; do not infer a raw file's schema from a current API response. |

FEC links to material from other publishers, including GovInfo and the Federal
Register. Preserve those links and use their existing SpicyDocs readers or body
APIs. FEC acquisition permits the named FEC hosts and its exact public S3 bucket;
it does not silently expand into a general web crawler. Adjacent IRS, state,
academic and commercial datasets from the research remain outside this integration.

## Read metadata first

Use a fresh observation file for each operation. Set `FEC_API_KEY` in the
process environment, or pass `--env-file /explicit/path` before the subcommand.
Credentials use `X-Api-Key`, never query parameters.

```sh
# List one cycle's original objects without downloading archives.
uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-bulk-2024.jsonl \
  objects bulk-downloads/2024/ --max-pages 10

# Scope JSON acquisition explicitly; repeat --param for multi-valued filters.
uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-committees.jsonl \
  api /v1/committees/ --param cycle=2024 --param per_page=100 --max-pages 100

uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-aos.jsonl \
  api /v1/legal/search/ --param type=advisory_opinions --param hits_returned=1 --max-pages 100

uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-site.jsonl \
  sitemap https://www.fec.gov/sitemap-wagtail.xml

uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-foia-links.jsonl \
  links https://www.fec.gov/about/reports-about-fec/foia-reports/
```

The registry includes the separate PDF and HTML sitemaps, `legal/`, raw data-dump
prefixes, and `user-downloads/`. The last contains generated user exports with
opaque names; neither its presence nor its enumeration establishes a canonical
financial dataset. Narrow a prefix using an observed key instead of constructing
unobserved download URLs.

Each page contains request/resolved URLs, acquisition time and method, an exact
response digest and blob location, source records, and continuation information.
JSON Pointer coordinates identify API records in the retained JSON. XML records
identify S3 keys or sitemap locations; they do not invent JSON coordinates for XML.
Relative FEC document links resolve against fec.gov, while the original field
remains in metadata. Decimal amounts become `Decimal` in Python and **decimal
strings** in CLI JSONL, preserving precision; the retained API response preserves
the original JSON numeric spelling.

String document body fields become `embedded_bodies` references into the retained
response. Citation and subject `text` labels remain metadata. Fields named
`body`, `html`, `document_text`, `extracted_text`, `full_text`, and other `text`
fields are lifted; unknown fields remain source metadata. No linked body is
requested by an API, listing, sitemap or link-discovery operation.

## Publish a retained committee census

`spicy_docs.sources.fec.profile` supplies `FEC_COMMITTEE_CENSUS_PROFILE`,
`committee_census_scope(captures)` and
`iter_retained_committee_pages(captures, blob_source=...)`. Use the scope in
`SourceNativeReleaseBuild` and pass the iterator to the existing
`SourceNativeReleasePublisher`. The profile requires no HTTP dependency and
makes no network request.

Each ordered capture descriptor pins `requestUrl`, `observedAt`,
`responseSha256` and `byteSize`. Preserve `resolvedUrl`, `mediaType` and `via`
when those acquisition facts are available. All pages must belong to the same
explicit `/v1/committees/` query, use `sort=committee_id`, begin at page one and
reach the publisher's exact final count. Repeated cycle filters retain their
original meaning: they select current entities, not historical field values.

Publication and offline replay enforce capture membership, response hashes,
continuations, counts and strictly increasing committee IDs. Evidence ZIPs contain
the exact `response.json` and its pinned `manifest.json` capture description.
Records preserve that capture and the existing metadata/body-pointer split;
unknown fields, nulls and empty lists survive. Linked assets remain metadata,
with no document renditions or body-download claim for this profile.

The release uses `observed-crawl` and `single-observed-traversal`. It covers only
the pinned query observation. Bulk tables, gap queries, historical profiles,
and legal collections need their own qualified delivery; this profile
does not broaden their status. Use the [release lifecycle](../releases.md) for
pin/producer admission and the [bulk evidence iterator](../source-native-outcomes.md#inspect-record-evidence)
when joining records to originals.

## Publish retained filing queries

`spicy_docs.sources.fec.filing_profile` supplies `FEC_FILING_QUERY_PROFILE`,
`filing_query_scope(captures)` and
`iter_retained_filing_pages(captures, blob_source=...)`. Use the same publisher
and capture descriptors as the committee profile. Each release contains one
complete, pinned `/v1/filings/` query with ordinary page/per-page pagination.
Publication and offline replay check page membership, exact counts and native
processed-record `sub_id` identity. File numbers, amendment fields, document
links, unknown fields and metadata/body references remain source observations.
Schema 1.1 preserves nullable or absent file numbers on unfiltered queries;
an explicit file-number selection requires a matching returned value. The
initial schema 1.0 qualification releases remain retained with their original pins.

Keep overlapping queries in separate releases. A requested-empty query retains
its evidence with zero records; a requested file number omitted from a response
does not prove that the original filing is absent. This profile neither chooses
an amendment nor acquires the referenced originals. The selected retained-query
qualification covers six releases with 47 observations of 46 file numbers;
it does not establish a full filing population. Source pins, original-JSON parity,
offline replay and committee regression controls are in
`~/Work/corpora/supply-2026-09-02/receipts/fec-source-expansion-2026-09-13/releases-v1.1/qualification.json`.

## Acquire selected originals

Select a URL from the observed `assets` or collection links and give an explicit
byte bound. For a listed object, also pass its size and quoted ETag. ETags are
publisher validators, not SHA-256 hashes.

```sh
uv run --frozen spicy-docs-fec --store /tmp/fec-blobs --output /tmp/fec-foia-body.jsonl \
  download https://www.fec.gov/documents/6100/FOIA-Annual-Report-Fiscal-Year-2025.xml \
  --max-bytes 1048576
```

The downloader streams chunks to the existing Rulespec content-addressed writer.
It checks bounds, known digest/size, source ETag when selected, identity content
encoding and recognizable file prefixes. These checks do not parse or validate
every document or archive member. Archives stay as original assets; downstream
callers can use maintained CSV/XML/archive readers without another FEC-specific
normalization pipeline in SpicyDocs.

For equivalent renditions already established by the caller, use
`choose_rendition` from `spicy_docs.sources.fec.assets`: XML, JSON and XHTML precede
HTML. It never invents alternate URLs. Pass `--allow-html` only when explicitly
selecting an HTML body. A PDF image, raw filing, table and summary are separate
source units unless the caller establishes equivalence.

Embedded text is available offline without downloading its linked original:

```python
from pathlib import Path
from spicy_docs.sources.fec.assets import embedded_text

# page and body are one observed page and one of its embedded_bodies entries.
text = embedded_text(
    store=Path("/tmp/fec-blobs"),
    sha256=page["evidence"]["sha256"],
    source_pointer=body["source_pointer"],
)
```

Known `--sha256 sha256:... --size N` inputs permit verified local reuse with no
network request. Failed transfers leave no completed blob; retry starts the
selected transfer again. There is no unpinned HTTP range append or automatic
archive extraction. Preserve the observation file, blob store and source selection
together. SpicyRegs/DocSpec can consume these facts and selected originals without
moving acquisition into their metadata model.

## Read retained raw filings offline

`spicy_docs.sources.fec.filings.filing_records` reads a retained `.fec` original
without network access or a financial schema dependency:

```python
from pathlib import Path
from spicy_docs.sources.fec.filings import filing_records

for row in filing_records(store=Path("fec-blobs"), sha256=original["sha256"]):
    if row["kind"] == "record":
        print(row["record_type"], row["fields"], row["source"])
```

The header retains its declared format version and literal fields. Data records
retain their field count and values keyed by zero-based position, including
unrecognized record types and extra fields. ASCII-FS fields preserve literal
quotes; legacy comma-delimited fields use Python's CSV reader, including quoted
multiline records. Dates, amounts, empty values and IDs stay strings. This is
source syntax, not a mapping to financial field names or amendment selection.

Bracketed free text and recognized `TEXT` fields become `embedded_bodies`
references: position 5 for ASCII-FS and position 3 for exact CSV versions
`5.0`, `5.1`, `5.2` and `5.3` (zero-based). The latter follows `4-TEXT4000`
in the publisher's historical `e-filing headers all versions` workbook, `TEXT`
rows 11–14. The amended indicator and extra fields stay positional metadata.
Other CSV versions remain positional until qualified; labels are not rounded
or interpreted as ranges. Each reference
identifies the original digest, byte offset, byte length and encoding; a delimited
body also identifies its field position. The body does not appear in row metadata.
`filing_body(store=..., body=...)` resolves one reference while preserving
whitespace and CSV quoting semantics; CSV ranges must contain exactly one record.
For many references, open the original once with `LocalBlobSource` and read the
indicated ranges; separate helper calls each reverify the whole original.

The reader checks the original digest before yielding records. Select UTF-8
(default), Latin-1 or `cp1252` explicitly for the whole file. It does not detect,
guess or retry encodings. Undefined CP1252 bytes and malformed UTF-8 fail without
replacement or restarting previously emitted rows. Latin-1 preserves byte values;
CP1252 can make legacy Windows punctuation readable, but neither establishes
the publisher's intended character set. Each reference records the selection.
The configurable record bound defaults to
1 MiB and applies across quoted CSV lines and legacy headers. Python's CSV field
limit also applies. Bracketed text is scanned one bounded line at a time without
joining the body in memory. Invalid headers, malformed CSV, unclosed text and
over-limit records fail; any earlier rows remain a partial parse. Retain the
original and failure when a layout is unsupported.

The [selected filing qualification](/Users/mikewolfd/Documents/Codex/fec-data-research-2026-09-11/integration/filings.md)
covers early, paper-entered and modern originals, registration statements, a
source-reported amendment chain, daily ZIP membership and separately acquired
Form 99 PDFs. It checks positional fields and body ranges, not financial meaning
or a full historical filing population. The existing `fecfile` package was
evaluated before this reader; its successful string-mode reads can omit extra
source fields. SpicyDocs reuses `csv` and the blob reader instead of copying its
financial mappings.

The additional format qualification preserves the recorded interpretations of
47 retained originals and proves reversible CP1252 body decoding on two Form 99
files. Versions 5.0–5.2 have official workbook evidence and known-answer tests;
this retained file selection contains no originals in those versions. The receipt
keeps that limit beside its source pins and checks:
`~/Work/corpora/supply-2026-09-02/receipts/fec-source-expansion-2026-09-13/formats/qualification.json`.

## Capture selected financial histories and refresh them

Run [the financial history example](../../examples/fec_financial_history.py)
from this checkout with the acquisition extra installed:

```sh
uv run --frozen python -m examples.fec_financial_history \
  --store /tmp/fec-history-blobs --output /tmp/fec-history-first

# Supply the actual SHA-256 of the prior observation.json.
uv run --frozen python -m examples.fec_financial_history \
  --store /tmp/fec-history-blobs --output /tmp/fec-history-refresh \
  --previous /tmp/fec-history-first/observation.json --previous-sha256 PIN
```

The selection is communication-cost and electioneering CSVs under the `19`/`20`
bulk year prefixes, plus the bundled-contribution export. It completes XML
enumeration and checks total bytes/object bounds before transferring originals.
Fresh directories retain listing responses, source metadata and every acquisition
outcome; the shared blob store preserves exact versions. A pinned prior receipt
permits reuse only after unchanged listing validators and local digest/size
verification. Failed objects are retried; previously listed keys missing from
a complete new traversal are reported without asserting publisher deletion.

The live selected history includes 19 files, 8,466,042 original bytes and periods
2010–2026. Independent XML and CSV checks compared the selected membership and
29,280 literal CSV rows. Fresh refresh listings reused every original; offline
replay made no network request. Change, missing-key and failure cases use injected
known-answer controls. These checks do not establish financial meaning, all bulk
families, large-dump capacity or recurring scheduling. Evidence and exact commands:
`~/Work/corpora/supply-2026-09-02/receipts/fec-source-expansion-2026-09-13/bulk/qualification.json`.

## Capture one advisory-opinion number year

[The legal-year example](../../examples/fec_legal_year.py) combines a complete
OpenFEC JSON search with the exact `legal/aos/YEAR-` XML listing, then requests
each selected opinion's JSON detail. The year selects AO numbers, not issuance
dates. All supporting-document associations survive; repeated FEC/S3 aliases
share one original transfer. Cited opinions remain references outside the selected
year. A listing-only opinion still receives a detail request, and an empty detail
remains an explicit unresolved outcome.

```sh
uv run --frozen python -m examples.fec_legal_year /tmp/fec-ao-2024 \
  --year 2024 --env-file /explicit/credentials.env

# Verify retained metadata, associations and original bytes without HTTP.
uv run --frozen python -m examples.fec_legal_year /tmp/fec-ao-2024 --verify-only
```

The example binds its selection only after metadata replay succeeds. Repeating
the acquisition command resumes that pinned selection, verifies successful
originals and retries unfinished objects from atomic checkpoints. Use a fresh
root for a new source observation. Credential refusals stop the run; metadata
refusals preserve available bounded response bytes. Incomplete acquisition exits
unsuccessfully even when its explicit failure records verify. The configured
aggregate bound covers retained successful originals; failed/retried transfers
can add network bytes beyond that amount.

The complete observed AO-number year 2024 selection contains 15 opinions and
163 separately acquired originals, totaling 65,959,367 bytes. Retained JSON/XML
replay checks metadata and associations, and hashes every original. This does
not parse PDF text/pages or cover other years and legal families. Evidence:
`~/Work/corpora/supply-2026-09-02/receipts/fec-source-expansion-2026-09-13/legal/ao-2024/verification.json`.

## Bounds, failures and coverage

Requests are sequential and paced. Metadata pages are bounded to 8 MiB; API,
S3 and sitemap traversals also have page bounds. Large legal responses may need
a smaller `hits_returned`. Asset storage uses bounded chunks rather than memory
proportional to archive size. Pagination state grows with the selected page bound;
there is no corpus-wide accumulation of records.

The CLI creates a new JSONL file exclusively and flushes each page. Only normal
exhaustion emits `complete`; errors emit `failed`, exit unsuccessfully and retain
available refused response evidence. Already written pages remain partial
observations. Ordinary pagination, keyset cursors (including null-sort controls),
legal offsets and S3 continuation tokens follow their respective source rules.
Estimated counts cannot end pagination. XML sitemaps follow child indexes, while
`links` reads one explicit page; it does not traverse detail pages or HTML pagination.
The caller selects those subsequent pages. A sitemap's `next_url` is the next
pending index, not a portable checkpoint for the whole traversal.

`401` and `403` stop direct acquisition. If the caller explicitly supplies
`--zyte-on-denial` and `ZYTE_TOKEN`, a public-source `403` can use the existing Zyte
extract adapter; OpenFEC authentication failures still stop. Its retained method
is `zyte_after_http_403`. Extract transfers have a 32 MiB bound and cannot bind a
selected ETag; use direct streaming for large/version-bound assets. This path is
covered with an injected provider, not a claim that every denied URL works live.

The focused tests include retained official audit, legal-detail and keyset
responses, metadata/body separation, negative response shapes, exact amounts,
continuations, credential suppression, interrupted transfers and byte bounds.
Small live qualification exercised API metadata, a bulk listing, the website
sitemap, FOIA link discovery and a selected XML original. Its local receipts are
under `~/Work/corpora/supply-2026-09-02/receipts/fec-integration-2026-09-12/`.
These observations do not establish a full historical backfill, a frozen FEC
snapshot, normalized table parity, or downstream publication.

The subsequent [2023–2024 and 2025–2026 bulk qualification](/Users/mikewolfd/Documents/Codex/fec-data-research-2026-09-11/integration/README.md)
acquired the selected identity/summary originals, verified ZIP membership and
CRC, and produced local Parquet tables with literal string fields. Independent
CSV replay matched every field and row. A caller interruption/retry proof retained
object versions and reused successful downloads without HTTP. Source references
missing from the corresponding masters remain explicit in the receipt; the
tables do not establish a closed set of entities. Scoped current/history queries
retain requested-empty outcomes and invalid references; the official list of
unverified filers supplies separate status evidence. An installed SpicyRegs wheel accepts
a selected API slice through its existing mapping. Selected original statements
and a filing/amendment slice are now retained and checked with the offline reader.
Complete distribution adoption, API-only relationship fields, full filing and
attachment coverage, and sealed publication remain open.
