# Decisions behind the rules

Use [source guides](README.md#work-on-a-source) for current procedures and the
[release specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
for exact requirements. This page keeps the reasons that future changes must preserve.

## Community supply precedes origin acquisition

Prefer spicy-regs public tables where they carry the required data; origin
acquisition fills gaps. Capture and pin whole named agency Parquet objects
before classifying rows, including locator, fetch time, stated freshness, size
and SHA-256. A live query result cannot replace pinned input.

Sources are explicit CLI choices; fallback is not automatic. The original
“Supply-precedence ruling” cited a platform `PLAN.md` that is not retained here.
Commits `48dac81` and `b25a3e9`, the captured-comment adapter and its tests retain
the implemented decision; they do not reconstruct the missing plan.

<a id="federal-register-identity-and-fields-version-separately"></a>

## Federal Register identity and fields version separately

A document number can name different documents on different dates. Identity
therefore uses `(document_number, publication_date)`; conflicting observations
of the same pair refuse publication. Policy `1.1` introduced that identity;
policy `1.2` added the limits of stable observed crawls without changing fields.

Current policy `1.3` adds publisher-stated `full_text_xml_url`, a `body-xml`
rendition and explicit field/rendition rules. Source schema `1.1` admits the
nullable field; the generic release schema remains `2.0`. Requests and replay
require all 23 selected fields and the exact canonical URL. Source record
identity and public Parquet columns remain unchanged. The proposed
`correction_of` field was deferred and never accepted.

Historical rationale: SD-24 / DocSpec decision 0003,
`docs/decisions/0003-federal-register-record-identity.md` in that repository.
It contains superseded proposals; the current source profile, fields and tests
remain the implementation evidence.

## Federal Register public tables preserve composite identity

Projection `1.1` uses `primaryKey: ["document_number", "publication_date"]`.
A number-only key would reject valid reused numbers. Both columns, their types
and literal values remain unchanged, so the Parquet schema ID stays `1.0`.

Compound-key duplicate checks use Rulespec canonical JSON and the source identity
function. Other profiles keep scalar keys. Readers require the exact current
projection version and key; the earlier number-only projection is unsupported.

## Similar sources can need different rules

Regulations.gov documents and dockets select the newest observation and may
collapse identical same-instant records. Document ties changing only
`openForComment` or `withinCommentPeriod` use a narrower comparison while keeping
the full observation digest. Equal-version comment ambiguity is refused.

Regulations.gov and captured comments share integer-only JSON decoding, with
source-specific exceptions. Federal Register retains its finite/non-finite float
diagnostics and response checks; GAO requires canonical capture manifests.
Share mechanics without erasing those distinctions.

## GAO evidence is bounded and literal

The profile covers only the named product IDs. Exact HTML and the literal
publisher topic survive; interpreting that topic belongs downstream. The
[GAO guide](sources/gao.md) owns capture limits and refusal rules.

## Supported entry points

The package root keeps one public export module for current consumers, with
the rest of the family under the `spicy_docs.source_native` package (the flat
`*_source_native` addresses were deprecated aliases, removed after 0.19):

- `spicy_docs.source_native`: release publishing, reading, schemas and verification.
- `spicy_docs.source_native.profiles`: source profile exports.
- `spicy_docs.source_native.federal_register`: Federal Register source operations.
- `spicy_docs.source_native.regulations_gov`: Regulations.gov source operations.
- `spicy_docs.source_native.store`: source blob-store API.

Implementations live under their [owning packages](architecture.md). Public
tables use `spicy_docs.public_tables.api` and `.profiles`; raw readers stay under
`sources/`. Installed commands are `spicy-docs-source-native` for releases and
`spicy-docs-fec` for independent FEC metadata and asset acquisition.

Reader imports must avoid eager HTTP/S3, logging/progress, Parquet and DuckDB
imports. Federal Register profile/replay imports also avoid GAO, Zyte and live
transports. `tests/test_reader_closure.py` guards these boundaries. Existing
`source_native.schema_bundle_digest` remains available; new code uses Rulespec.
Patch implementation owners in tests; private forwarding wrappers are not supported.

`spicy_docs.extraction` exposes the PDF/image data types, reader and page strategies;
`.ocr` and `.gemini` expose optional recognition adapters. These reusable components
support the requested source-specific processor choices. Constructors accept their
dependencies directly; model selection and retained lifecycle stay with callers.
They do not change source-release schemas or defaults. See the [API design](extraction/pdf-extraction-api.md).

## Current source-release format and retained evidence

- Source-native format/schema/verifier: **2.0**; public-table format/verifier: **1.0**.
- Producer: **`spicy-docs`**. Require the current schema bundle and profile policy.
  Older `spicy-regs` names in format identifiers remain data identifiers.
- Historical inputs are retained but refused by current readers/replay. There is
  no automatic conversion or legacy reader. Historical test schemas are not packaged.
- All three nonnegative failure counts are required and must sum to
  `failedRecordCount`, even at zero. Transient and unclassed failures cannot publish.
- Storage byte accounting lives in the run result, outside sealed receipts.
  Fixed sealed inputs retain the same artifact pin regardless of store reuse.
  Changing the release schema can still change logical identity.

## Share work without sharing mistakes

Keep source callbacks and scope registration in `cli/sources.py`; the generic
release engine needs no source-specific branch. Close partially consumed source
iterators before their transports. Cache digests of immutable schemas instead
of recomputing them for each record.

Share routine test encoding and inspection. Keep malformed artifacts and semantic
replay independent of the writer they check. Preserve coupled traversal, selection
and accounting state in cohesive functions; file length is a review prompt, not a quota.

## Congress.gov and GovInfo collections are each one family

Adopted 2026-09-19 from the
[legislative data map](research/legislative-data-map-2026-09-18.md).

A new Congress.gov collection route is a URL builder and a records key on the
existing listing family, landed with a fixture and a live pagination check;
the map's Table A is the route table, and it records per route whether the
API honors sorting, since only five routes do. A new GovInfo collection is a
body fetch on the existing discovery and MODS readers, cloned from the
Federal Register body acquisition and keyed on the package id. Listing any
collection the API serves is in scope.

Crawling a whole collection or its bulkdata stays separate scope, as the
bills source page already says, and each crawl carries its own record naming
the bound and the byte budget before it is built. The measured costs for the
119th Congress are 52 MB of status zips, 8 MB of summaries and 3 MB of laws;
bulk lags the API by days, and a crawl states what an empty result means,
because a zero count never establishes absence.

The Congress.gov API is the index and GovInfo or the publisher file is the
body or the crosswalk. Where both hold an item they agree: seven pairs
measured on 2026-09-18 showed no content disagreement, and twenty-three
joins followed from twenty items each held wherever the publisher's own data
did. Prefer the API for listing, key bodies on the GovInfo package id, and
take a publisher file only for a field the API lacks: committee assignments,
the Senate LIS crosswalk, and Senate member-level votes. For senators who
have left, the community legislators JSON is the crosswalk, pinned and
cadence-checked, because no publisher file carries their LIS ids.

## Community legislators JSON is the identifier crosswalk

Adopted 2026-09-19 with the [legislators source](sources/legislators.md).

This module adds a pinned civil-society crosswalk
(`unitedstates/congress-legislators`), taken specifically for the two ids no
publisher route carries: a *former* senator's Senate LIS id, and FEC
candidate ids generally. It is a capture-and-check source like CBO's
per-Congress feed, not a listing or release-publishing source: two fixed
keyless routes, byte-bounded (16 MiB for the historical file, matched to its
measured 12.86 MiB), shape-checked record by record, with duplicate
bioguide/LIS/FEC ids refused. Because the source carries no publisher version
or date, its pin is the observed capture (bytes, SHA-256, time), and its
only cadence signal is the GitHub repository's own commit history, not the
JSON. This confirms and implements the crosswalk role already recorded in
"Congress.gov and GovInfo collections are each one family" in
`docs/decisions.md`.

## GovInfo package bodies are fetched by package id, never crawled

Adopted 2026-09-19 with the [GovInfo bodies source](sources/govinfo-bodies.md).

**A GovInfo collection is a body fetch on the existing readers, not a new
source family.** This adds one operation: fetch the body of one package named
by its package id, over the existing discovery, MODS and transport readers,
with the Federal Register body module's identity rules reused rather than
rewritten. It adds no crawling, no release publication and no dataset
selection; callers choose packages and retain bytes.

Two departures from that plan, both measured:

- **The offered set comes from the package MODS, not the summary's download
  block.** The summary lists no body rendition for CRPT, CHRG or CDOC while
  those packages do serve HTML and PDF; the MODS `raw object` renditions
  matched the served routes exactly in both directions for every package
  measured. Following the weaker statement would have refused the three
  collections this work exists to fetch.
- **MODS is fetched before the body, not after.** Identity is then proved
  before any body request, a missing or mismatched package costs no body
  bytes, and the format choice is made from the publisher's own statement.

The one rule that did not transfer is the printed-marker check: a GovInfo
package body prints no package id, so the smaller rule here is locator plus
MODS rendition agreement plus the shared error-page exclusion.

The error-page rule itself moved to `sources/govinfo/error_page.py`, a module
that imports nothing from `spicy_docs`, so the Federal Register validator can
call it without importing this family. That validator's wording and check
order are unchanged: its refusal text reaches command receipts, and its two
error-page witnesses must stay on either side of the locator check.
