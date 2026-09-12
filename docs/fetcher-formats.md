# Fetcher formats

**Most fetchers already retrieve structured data.** The immediate opportunities
are to expose Federal Register XML links and label JSON attachments correctly.
CourtListener already carries some XML opinion bodies inside its CSV files.

This review covers implemented fetchers and network tools at `bd30dde`.
The XML-first body change is implemented; the four follow-ups below remain open
in the [task list](simplification-todo.md#fetcher-format-review).

## What we fetch today

| Operation | Retrieved format | Decision |
| --- | --- | --- |
| Federal Register metadata | JSON | Keep; retain the publisher's XML link. |
| Federal Register document body | XML; HTML fallback after XML 404/410 | Keep the [XML-first behavior](federal-register-body-sources.md). |
| GovInfo issue census and start-page lookup | MODS XML metadata | Keep; metadata does not contain the document body. |
| GovInfo unmatched-identifier diagnostic | Credentialed JSON | Keep. |
| Congress CRS summaries | JSON metadata, summary and format links | Keep; retain report version. |
| GAO product topics | Exact HTML through Zyte | Keep until equivalent topic evidence is demonstrated. |
| Mirrulations / Regulations.gov | S3 listing and JSON records | Keep; attachment links are preserved, not downloaded. |
| Community public comments | Parquet parts, including extracted text | Keep the supplied dataset and its source fields. |
| CourtListener discovery | S3 listing XML | Already XML. |
| CourtListener records | Compressed CSV, including available XML/HTML fields | Keep; fix null versus empty-string handling. |

Replay and drift comparison read retained evidence offline. Zyte's JSON response
wraps the target's bytes; it does not turn an HTML document into JSON. There is
no general PDF downloader here. Sources listed only in the
[reference catalog](source-reference.md) are not additional implemented fetchers.

## Four bounded follow-ups

### 1. Correct JSON attachment labels

The shared [media-type helper](../src/spicy_docs/sources/media_types.py) lacks a
`json` alias and infers extensions from the whole URL. Reproductions return
`application/octet-stream` for `file.json` and the invalid `org/file` for an
extensionless `https://example.org/file`.

Add the alias and inspect the parsed URL path. Cover explicit labels, query
strings, fragments and extensionless paths. This affects Regulations.gov and
public-comment rendition metadata: their lists of alternative document files.
Actual equivalent XML/JSON attachments were not established by this review.

Revise both acquisition policies and qualify publication/replay: rendition
values contribute to release hashes. Keep source schemas unchanged if their
fields and validation rules do not change. Apply current-only admission rules
explicitly; never silently reinterpret historical releases.

### 2. Expose the publisher's Federal Register XML link

The [source profile](../src/spicy_docs/sources/federal_register/native.py)
omits `full_text_xml_url` and emits only HTML/PDF renditions. The new body API
prefers XML, but general release consumers cannot discover it in that list.
The official API supplies the missing field; its availability does not establish
historical XML coverage. [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1).

Capture the nullable publisher value and emit a `body-xml` rendition. Update the
source schema, acquisition policy, schema bundle, admission and replay fixtures
together. Preserve HTML/PDF alternatives and explicit nulls. A derived XML URL
must not be described as publisher-stated. Adding a public Parquet column is a
separate decision; a body link alone does not prove a successful download.

### 3. Keep CRS report versions

The [CRS fetcher](../src/spicy_docs/sources/congress/crs_summaries.py) retains
`formats` but drops `version`. Preserve it on new captures so a later download
can be matched to the same edition. Existing successful rows are skipped on
resume; obtaining missing version evidence requires an explicit fresh capture.
Do not infer it or rewrite historical captures.

The API's JSON/XML responses describe metadata and separate report files; they
do not supply XML/JSON full reports. Preserve whichever body formats the
publisher offers; do not assume every report has HTML. This follow-up does not
add a body downloader.
[Publisher's CRS fields](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CRSReportEndpoint.md).

### 4. Preserve CourtListener empty strings

This is a related fidelity bug. The [CSV reader](../src/spicy_docs/sources/courtlistener_bulk.py)
collapses unquoted nulls and quoted empty strings into `None`. A synthetic row
`1,,""` reproduces the loss. The publisher uses PostgreSQL CSV, which distinguishes
these values. Keep CSV; correct parsing with tests for quoted empties, embedded
quotes/newlines and streaming bounds, and check raw-reader consumers.
[Publisher's bulk format](https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data).

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

Prefer XML/JSON when it supplies the same document and edition with the needed
content. CSV and Parquet are already structured; metadata, summaries and JSON
wrappers cannot substitute for a full document. Dataset selection remains with
the fetching caller; see [ownership](source-ownership.md).
