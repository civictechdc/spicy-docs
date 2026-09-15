# Fetcher formats

**Most fetchers already retrieve structured data.** Federal Register releases
now expose publisher XML links, and attachment renditions identify JSON correctly.
CourtListener already carries some XML opinion bodies inside its CSV files.

The original review covered implemented fetchers and network tools at `bd30dde`;
the table now also includes the bill API. Implementation and qualification status
live in the [task list](simplification-todo.md#fetcher-format-review).

## What we fetch today

| Operation | Retrieved format | Decision |
| --- | --- | --- |
| Federal Register metadata | JSON | Keep; retain the publisher's XML link. |
| Federal Register document body | XML; HTML fallback after XML 404/410 | Keep the [XML-first behavior](sources/federal-register-body-sources.md). |
| GovInfo issue census and start-page lookup | MODS XML metadata | Keep; metadata does not contain the document body. |
| GovInfo unmatched-identifier diagnostic | Credentialed JSON | Keep. |
| Congress CRS summaries | JSON metadata, summary and format links | Keep; retain report version. |
| Congress bill status and selected text | BILLSTATUS XML and explicitly selected bill XML | Preserve all offered version links; validate the requested bill/version. [API and limits](sources/congress-bills.md). |
| GAO product topics | Exact HTML through Zyte | Keep until equivalent topic evidence is demonstrated. |
| Mirrulations / Regulations.gov | S3 listing and JSON records | Keep; attachment links are preserved, not downloaded. |
| Community public comments | Parquet parts, including extracted text | Keep the supplied dataset and its source fields. |
| CourtListener discovery | S3 listing XML | Already XML. |
| CourtListener records | Compressed CSV, including available XML/HTML fields | Keep; quoted empty strings and unquoted NULLs now remain distinct. |

Replay and drift comparison read retained evidence offline. Zyte's JSON response
wraps the target's bytes; it does not turn an HTML document into JSON. There is
no general PDF downloader here. Sources listed only in the
[reference catalog](source-reference.md) are not additional implemented fetchers.

## Format fidelity

### 1. JSON attachment labels

The shared [media-type helper](../src/spicy_docs/reading/media_types.py) maps
publisher `json` labels to `application/json`. Fallback examines only the final
URL path extension; query strings, fragments and parent directories do not
supply a type. An unknown type stays `application/octet-stream`.

Regulations.gov and public-comment policy `1.2` pin these rules and qualify
publication/replay. Public-comment attachment IDs also preserve original list
positions after invalid formats are omitted. Current readers require the new
policies; source record schemas stay unchanged. Renditions describe offered
files. These checks do not establish equivalent XML/JSON body availability.

### 2. Federal Register XML links are exposed

The [source profile](../src/spicy_docs/sources/federal_register/native.py)
requests optional `full_text_xml_url` and emits a `body-xml` rendition with the
publisher's value. HTML/PDF alternatives remain available. Missing and explicit
null values remain distinct in records; both have null rendition locators.
Field availability does not establish historical XML coverage.
[Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1).

Source schema `1.1` and acquisition policy `1.3` qualify publication, the embedded
schema and offline replay together. Admission requires the current versions.
The generic release schema remains unchanged. Constructed body-fetch URLs never
replace publisher-stated fields. Public Parquet columns remain unchanged;
a body link alone does not prove a successful download.

### 3. Keep CRS report versions

The [CRS fetcher](../src/spicy_docs/sources/congress/crs_summaries.py) retains
`formats` and the detail response's `version` on new captures. The version keeps
its native JSON value: explicit null stays null, and a missing field stays absent.
Existing successful rows are skipped on resume. To obtain missing version evidence,
run the fetcher with a new `--output` JSONL file and retain the earlier capture.
A fresh response describes the newly observed version; list metadata cannot
reconstruct the version of an earlier detail response.

The API's JSON/XML responses describe metadata and separate report files; they
do not supply XML/JSON full reports. Preserve whichever body formats the
publisher offers; do not assume every report has HTML. This follow-up does not
add a body downloader.
[Publisher's CRS fields](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CRSReportEndpoint.md).

### 4. Preserve CourtListener empty strings

The [CSV reader](../src/spicy_docs/sources/courtlistener/bulk.py) now preserves
unquoted empty fields as `None` and quoted empty strings as `""`. Its bounded
source decoder follows the
[publisher's PostgreSQL export dialect](https://github.com/freelawproject/courtlistener/blob/main/scripts/make_bulk_data.sh).
It refuses invalid UTF-8, malformed quoting, and mismatched columns; tests cover
escaped quotes, newlines, byte limits, and resumed transfers. See
[raw-reader limits](sources/raw-readers.md#courtlistener).

A retained June 30, 2026 courts dump parsed all 3,361 rows. Re-encoding them with
the publisher's quoting rules exactly reproduced all 765,809 decompressed bytes,
including 16,096 NULLs and 11,808 empty strings. SpicyRegs still uses its own
reader and normalizes some table values; its adoption remains separate.

## Opportunities that need more evidence

**CourtListener XML is already available to consumers.** Its bulk exporter
includes `xml_harvard` and `xml_scan`; SpicyDocs retains populated columns.
Evaluate these against the same opinion and edition before choosing them.
Coverage and completeness were not measured across a current dump, and the
publisher recommends `html_with_citations` for opinion text.
[Export fields](https://github.com/freelawproject/courtlistener/blob/main/scripts/make_bulk_data.sh#L105),
[case-law guidance](https://wiki.free.law/c/courtlistener/help/api/rest/v4/case-law).

**GAO RSS is useful for discovery.** No reviewed XML/JSON route established the
same literal topic label, slug, link and historical product coverage as the
current HTML capture. Live feed parity remains unqualified. Keep the current
page evidence.
[GAO feed directory](https://www.gao.gov/about/stay-connected).

**GovInfo whole-issue XML is feasible; added recovery remains unproven.** A
bounded live test extracted documents matching the publisher's exact XML bytes,
but recovered no additional document where publisher XML was unavailable.
Keep the current default. Any future issue route needs a demonstrated recovery
or bulk-workload benefit, surrounding page context, strict issue/member identity,
and retained issue bytes, extraction offsets and hashes within explicit bounds.
The [local experiment receipt](../../corpora/supply-2026-09-02/receipts/govinfo-issue-xml-2026-09-11/report.md)
retains cases, commands, input pins and limitations outside this repository.
[Federal Register formats](https://www.govinfo.gov/help/fr),
[bulk coverage](https://www.govinfo.gov/developers).

## What the complete GovInfo asset review adds

All 23 tracked assets in [`usgpo/bulk-data` at `83a8517`](https://github.com/usgpo/bulk-data/tree/83a85170ce0bdd0cf218f6290bd739df8748e2ea)
were covered: seven root files, four PDF guides, eight XML samples and four files
under `sample-xhtml`. Review included full guide/PDF text, whole-file XML/HTML
analysis and complete comparison of the XML pairs. External schemas/resources,
live collection coverage and visual fidelity were outside this review.

- **Bill Summaries is a separate dataset.** Its CRS-authored summaries follow
  congressional actions and need not match printed bill versions. Preserve
  summary identity and dates; its prose is HTML inside XML CDATA.
- **Publisher HTML can preserve useful bill structure.** Three samples contain
  legislative HTML; one `.html` file is plain text with a staging marker. Some
  IDs repeat, and a layout table contains most of an enrolled bill. Validate
  actual content; do not remove tables or use IDs as unique passage keys blindly.
- **Punctuation changes affect identity.** Every updated XML sample changes only
  en dashes to hyphens, including some document/section identifiers. Preserve
  raw spelling and hashes; any comparison keys are separate derived values.
- **eCFR needs source-specific parsing.** `NODE` is unstable; `DIV1/@N` is a
  volume number. Preserve title identity, repeated blocks, distinct source dates,
  editorial/superseded text and mixed content. XML nesting alone does not prove
  paragraph hierarchy.
- **Exact XML bytes may still need companion content.** Graphics and equations
  can be external. Preserve their locators; the caller decides which resources
  its dataset needs. The older PDF guides are references, not current coverage
  guarantees or additional data collections.

Keep the XML preference when it supplies the required document and edition.
Qualify actual structure and content, including useful publisher HTML. CSV and
Parquet are already structured; metadata, summaries and JSON wrappers cannot
substitute for a full document. Source acquisition preserves evidence; dataset
selection and processing remain with the caller. See [ownership](source-ownership.md).
