# Decisions behind the rules

Use [source guides](README.md#work-on-a-source) for current procedures and the
[release specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
for exact requirements. This page keeps the reasons that future changes must preserve.

## SpicyDocs owns document parsing and exact captured text; the capture shape is Rulespec's

**2026-09-19 owner ruling**, recorded in the sibling rulespec repository's
`docs/decisions.md` under that date and indexed in the stack `DECISIONS.md`
under "Product boundaries". It amends the
rulespec 2026-08-02 entry, which had assigned DocSpec "document parsing, exact
captured text, durable structural passages, and model-input segmentation"
under RefSpec REF-048. Three of those four move here: SpicyDocs owns document
parsing and the exact captured text, and the durable structural shape is
Rulespec's `DocumentCapture v1` parent schema composed by the family profiles
in this repository. DocSpec keeps model-input segmentation over captures it is
given, and REF-048's catalog ownership is untouched.

What that means in this repository, and what a later change must preserve:

- **The parent shape is not ours to change.** `DocumentCapture v1`, the
  profile meta-schema that states how a family composes it, and the validator
  for the invariants JSON Schema cannot see all live in Rulespec and ship in
  the `rulespec-artifacts` wheel. The copies under
  [`src/spicy_docs/schemas/document_capture/1.0/`](../src/spicy_docs/schemas/document_capture/1.0/README.md)
  now retain only the family profiles and the separately pinned source-fragment
  schema. The parent, meta-schema and invariant validator come directly from
  installed `rulespec-artifacts==1.1.2` (1.0.14 adopted 2026-09-21; 1.1.0 on
  2026-09-22 adds only opt-in DocumentCapture v2; 1.1.1 ships its repaired
  platform fixtures; 1.1.2, adopted 2026-09-26, carries that corpus under its
  own version, with code, schemas and encoder unchanged); no fallback copy
  remains. Parent and profile bytes are unchanged; the installed validator
  additionally refuses parents after children and duplicate node IDs.
- **The family profiles and the converters are ours.** A family is a grammar
  from the publisher's element names to structural roles, plus a closed
  extension block. A new family is a profile file, never a change to the
  parent.
- **Capture is not interpretation.** This is the same boundary `AGENTS.md`
  draws: node kinds are structural, the publisher's own element name travels
  in `source.element`, and any rule that placed a node names itself in
  `decision`. A kind that meant "requirement" would be an extraction result
  wearing a capture's clothes.
- **The artifact is always the publisher's bytes.** A PDF capture names the
  PDF in `artifact` and the retained extractor document in
  `rendition.intermediate`, so a consumer that follows `artifact.locator.url`
  and checks `artifact.sha256` lands on what the publisher issued. The first
  draft put the extractor's JSON in the artifact slot with the PDF's URL
  beside it, and the 2026-09-19 architecture review found that a consumer
  doing both would see two different documents.

The design record, the six worked conversions and the two reviews behind this
shape are in
[`docs/research/document-capture-schema-2026-09-19.md`](research/document-capture-schema-2026-09-19.md).

## Reversible capture XML names the capture's structures

**2026-09-20, G1:** use a generic, capture-shaped XML vocabulary in
`urn:spicy-docs:document-capture:xml:1`. It represents every JSON property and
value, including ordered nodes and spans, extension values, geometry,
unresolved reasons, artifacts, and profile and converter provenance. The
[format and measurement record](research/document-capture-xml-roundtrip-2026-09-20.md)
defines the mapping. This is a SpicyDocs serialization of the pinned Rulespec
shape; it changes neither the parent nor the profiles.

A publisher vocabulary is a separate, lossy projection of a capture: it has
no general place for capture decisions, coordinates, or converter provenance.
The existing example is [`reconstruction/serialize.py`](../src/spicy_docs/reconstruction/serialize.py):
`serialize_cfr` consumes `ReconstructedDocument`, emits `CFRGRANULE` under
`CFRMergedXML.xsd`, flattens paragraph nesting, and keeps evidence and rules
in a separate JSON source map. That output remains unchanged. Its XML alone
cannot reconstruct a capture, and concatenated span text cannot prove that
capture structure survived. G1 requires full JSON value equality after XML
encoding and decoding.

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

## GAO's own listing: the robots ruling, the class rule and the major-rule exception

**Access, owner ruling 2026-09-28.** `robots.txt` disallows
`/reports-testimonies` by prefix and asks every agent for `Crawl-delay: 420`.
The owner accepted the disallow for the GAO listing backfill. The library
default keeps the delay: one worker, 420 seconds apart, and it stays that way
so the reviewed path is the polite one. The owner then overrode the delay for
the backfill of 2009-2025 and January-August 2026 with run flags
(`--concurrency 3 --delay-seconds 0`, after six workers stalled). That is a
decision about one run, not a new default. The guide
([GAO's own listing](sources/listings.md#gaos-own-listing-month-in-review-and-annual-index))
keeps the run's settings and why.

**The number decides the class.** A `GAO-` number is a product, a `B-` number a
legal decision, and anything else, or no number, is set apart. The heading
does not decide: GAO files GAO-numbered major-rule reports under a legal
heading, and three B-numbered decisions under topic headings. Over all 1,212
pages (29,996 teasers, re-read independently in review), the number is the one
field that agrees with what the product is.

**The major-rule exception, owner ruling 2026-09-28.** `gao_reports` carries
every Federal Agency Major Rule Report, so a teaser with that label is a
product whatever its number. GAO switched numbering in 2017: `GAO-` numbers up
to 2017-02-17, `B-` numbers from 2017-04-20. Every one of the 1,655 carries
both the label and the heading, checked before the rule was written. None
had to be guessed. Reports before 2009 are a gap: GovInfo's GAOREPORTS holds
none, measured 2026-09-28 (no major-rule report among the 12,579 rows
spicy-regs keeps from it, and none in a random 34 of the 3,743 B-numbered
packages issued 1996-2008, all Comptroller General decisions; receipts in
`corpora/fork-execution-2026-09-21/gao-month-in-review-review/finish/govinfo/`).

**Keys.**
- A product is keyed on the page the listing links. A GAO number's page is the
  number lowercased. A prerelease path keys on the number.
- A `-N` twin page folds into its base page when every other field agrees,
  and stays its own product when one differs (`gao-14-280r-0`).
- A decision or other entry is keyed on its page, since one B-number can have
  two pages released months apart.
- The stated number stays whole; a link must agree with it token for token.

**A dropped provider read is the provider's error.** `ZyteHttpFetcher` and
`FirecrawlFetcher` raise their own `ZyteTransportError` or
`FirecrawlTransportError` for every `http.client` failure: a malformed status
line from `urlopen`, a body cut short, a cut error body. The one catch lives in
`transport.provider_api.read_provider_payload`. A raw `IncompleteRead` had
escaped the walled-fetch ladder, which catches only each adapter's own error,
and ended the whole fallback chain.

### What an importer must change

- spicy-regs `sources/gao_listing.py` reads `read_listing_run`,
  `GaoListingRun` (`pages`, `products`, `decisions`, `others`,
  `complete_scopes`, `incomplete_scopes`) and `GaoListedProduct`
  (`product_id`, `product_number`, `label`, `heading`, `released`,
  `published`, `topics`, `title`).
  - `products` now includes the B-numbered major-rule reports. Their
    `product_id` is the page (`b-333095`) and their `product_number` the
    B-number.
  - A `-N` twin that agrees with its base page is no longer a separate product.
  - Its text still states the rule this one replaces. The data dictionary's
    `gao_reports` coverage says "Only GAO-numbered products are taken". The
    module docstring puts every B-numbered entry outside the table, and its
    type comment counts 707 major-rule reports, the GAO-numbered ones. The
    code takes `products` as it is.
- `ZyteTransportError` callers: `sources/walled_fetch.py`,
  `sources/usitc_edis/credentialed.py`, `cli/fec.py` and
  `transport/acquisition.py`. Each now also receives the failures that used to
  escape as raw `http.client` errors, so the walled-fetch ladder moves on to
  its next rung rather than aborting. No call site changes.
- RefSpec imports `ZyteHttpFetcher` and `ZyteTransportError` in
  `registry/adapters/crs_zyte.py` and `icpsr_zyte.py`, and `ZyteHttpFetcher`
  in `tools/fetch_registry_source_via_zyte.py`. The adapters' handlers now
  also catch a dropped read, and the tool still lets it propagate. RefSpec
  takes this at its next spicy-docs bump, with no code change.
- `walk_listing` takes `proxy_record` (a URL to its latest `ZyteProxyRecord`,
  e.g. `ZyteTransport.record_for`) in place of `proxy_records`. `concurrency`
  is capped at 8, and `sleep` defaults to an interruptible wait.

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

**Revised 2026-09-19** to add a third family beside the two publisher ones:
appropriations committee press releases, captured whole from each chamber's
own RSS 2.0 feed rather than from Congress.gov or GovInfo. Two canonical feed
URLs replace BillTrax's four dead spellings, and identity is proved from the
channel `<title>`/`<link>` rather than the request URL, because an
unrecognized Senate `?type=` answers 200 with a byte-identical default
channel instead of failing. See "Appropriations press releases: two
canonical feeds, identity from the channel body" below.

## Appropriations press releases: two canonical feeds, identity from the channel body

Adopted 2026-09-19 with the [press-release source](sources/press-releases.md).

Measured 2026-09-19 (`docs/research/billtrax-raw-data-2026-09-19.md` §4): all
four of BillTrax's spellings across `press-releases.ts` and
`sync-press-releases.ts` are dead — two 404s, a 410 Gone, and a 200 that is a
ColdFusion error page, the same shape `sources/govinfo/error_page.py` already
names for GovInfo. The two live, canonical feeds are
`https://appropriations.house.gov/rss.xml` and
`https://www.appropriations.senate.gov/rss/feeds/?type=press`, both RSS 2.0
with no default namespace; BillTrax's single-item Atom-collapse bug in
`fast-xml-parser` does not reproduce here because `xml.etree` never collapses
a one-item list to a non-list.

**The request URL never proves the response.** An unrecognized Senate
`?type=` answers 200 with a byte-identical default channel instead of
failing, so `acquire_press_releases` checks the response body itself against
each feed's own `identity_title_contains` and `identity_link_host` rather
than trusting the URL that was requested. Both checks must pass or the whole
capture is refused, with the exact bytes retained as evidence — the same
"outcome, not the URL" discipline as `gao/rss.py`'s product-link check and
the GAO-files PDF-magic check.

Everything either channel or item states is kept whole, including fields
BillTrax dropped (`ttl`, `skipDays`, `skipHours`, `lastBuildDate`); nothing is
truncated to an excerpt. This closes [port decision 5](research/billtrax-port-2026-09-15.md).

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

**Extended 2026-09-19** to bill-version PDFs. `bill_pdf.acquire_bill_pdf`
(see [bill-version codes](sources/congress-bill-versions.md)) is the same
identity-first fetch through this acquirer: no second HTTP path, no
independent proof rule. A caller passes the publisher's own stated
`package_id` when it has one; only when none exists does it fall back to
`bill_version_package_id`, a name-derived package id built from the sealed
`version_code` vocabulary. That fallback cannot tell a numbered reprint from
its original by name alone, so a stated package id always wins when both are
available — see "Bill-version codes are a sealed, additions-only vocabulary"
below.

## USLM joins the sealed body preference; granules and committee prints join the grammar

Adopted 2026-09-19 with [GovInfo bodies](sources/govinfo-bodies.md)
(updated); gaps B7, B2 and the CPRT row of A10 in
[closing the gaps](research/closing-the-gaps-2026-09-19.md).

**`uslm` is inserted into `BODY_PREFERENCE` right after `xml`, not merely
appended after `pdf`.** BILLS states a USLM rendition (`uslm/{id}.xml`)
alongside its own `xml` on the same package — measured 2026-09-19 on
`BILLS-119hconres11enr` (the raw-data sidecar's one file-name-matched USLM
package) and then on every other BILLS package in the same sample offering
USLM: five enrolled packages in all, each MODS offering `htm`, `pdf`, `xml`
and `uslm` together, pinned per package in
`tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json`. (The
sidecar's "10 of 240" USLM aggregate counts each sampled bill once per
version code that pinned it: `hconres11` is the sample for both `enr` and
`rds`, so its one USLM entry is counted twice. Of the 9 distinct entries, 4
are PLAW-collection packages — the `Public Law` version on a bill's `/text`
endpoint — outside this BILLS grammar, in `sources/govinfo/uslm.py`'s
territory.) So an order was needed between two structured renditions of one
document, not only between structure and prose. `xml` keeps the top slot
because every BILLS package that offers USLM offers XML too (both are
Formatted-XML siblings on the same publisher record), so trying XML first
costs nothing;
`uslm` still outranks `htm` and `txt` for the same structure-first reason
the original ruling already applied between XML and everything else — it is
markup over the same structured source, not a plain-text reduction of it.
The sealed order is now `("xml", "uslm", "htm", "txt", "pdf")`, and
`bill_versions.DEFAULT_FORMAT_PREFERENCE` carries the same slot in
Congress.gov's own spelling, still pinned equal to it by test.

USLM's text is read through `extraction/body_text.py`'s existing
`markup-reader` branch — the same one `xml` uses, not a dedicated USLM
parser. The fetched body's root varies by bill type (`<resolution>` on the hconres
fixture, `<bill>` on the four H.R. packages; `<jointResolution>` and others
named by type), where
`sources/govinfo/uslm.py`'s grammar validates identity against one fixed
root per selection (`PublicLawSelection`, `StatuteCompilationSelection`,
built for PLAW/COMPS) and has no bill identity to check against, so that
grammar does not apply here; the generic reader, which needs no schema,
does. `uslm` and `xml` also share a file extension (`uslm/{id}.xml` vs
`xml/{id}.xml`, folder differs), so the fallback that labels a rendition
found at an unexpected folder can no longer rely on extension alone;
`_FORMAT_BY_EXTENSION` tie-breaks toward `xml`, the pre-existing and more
common of the two.

**Granule bodies for the Record (B2).** The Record is PDF-only at package
level, but its granules — one speech, one page range — carry their own
HTML, measured on `CREC-2026-09-18` (a three-page issue, 11 granules, every
one offering HTML and PDF through the granule's own locator).
`GovInfoBodyAcquirer.acquire_granule` mirrors `acquire`'s three-request
shape (granule summary, granule MODS, then the body) with identity proved
before bytes the same way, plus one departure the granule route itself
forces: a granule that does not belong to the requested package answers
HTTP 400, not 404 — confirmed both directions (a wrong-day granule id under
the right package, and the fixture's own real granule id under the wrong
day) — so a 400 whose body is exactly the documented
`{"message": "invalid granuleId"}` is typed `GovInfoPackageUnavailableError`
the same way a package's own 404/410 is, and any other 400 is left as a
generic refusal with its capture.
`GRANULE_BODY_PREFERENCE` (`("htm", "pdf")`) is a separate, granule-scoped
constant, not a second reading of `BODY_PREFERENCE`: the whole-issue
package PDF stays reachable unchanged through `acquire(package_id)`.

**Committee prints join the package-id grammar (A10).**
`CPRT-{congress}{HPRT|SPRT|JPRT}{number}` — verified upper-case on a real
package summary (`CPRT-118HPRT57104`), unlike CRPT's own lower-case
`hrpt`/`srpt`/`erpt`, so this is measured, not inferred from CRPT's
spelling. No locator or validator code changed: CPRT packages address
their HTML, PDF and XML renditions at the same
`content/pkg/{id}/{folder}/{id}.{extension}` shape every other collection
already uses.

**Correction to "Bill-version codes are a sealed, additions-only
vocabulary" below:** that section's last paragraph stated USLM "is
recognized by name and folder but not yet fetchable: no acquirer supports
it for a BILLS package today." This record is what makes that false;
`PACKAGE_BODY_FORMATS["uslm"]` now reads a BILLS package's own
`uslm/{id}.xml` rendition directly.

## Bill-version codes are a sealed, additions-only vocabulary

Adopted 2026-09-19 with [bill-version codes and bill PDFs](sources/congress-bill-versions.md).

`sources.congress.bill_versions.VERSION_CODES` ports BillTrax's
`bill_versions.version_code` slug map. **The vocabulary is sealed: this
module only adds slugs; it never renames or removes one**, even where the
publisher's measured 119th-Congress data contradicts a slug's own name
(`referred-to-senate` really names "Received in Senate"). The slug is a
BillTrax identifier now, not a live claim about the publisher's own wording;
that claim lives in the table's `version_types` field.

**One correction, not a rename.**
`returned-to-the-house-by-unanimous-consent` kept its slug but had its
`govinfo_suffix` corrected from `rfh` to `rhuc`: BillTrax's canonical map
deliberately collided it with `referred-to-house` on `rfh`, and the 119th
measurement shows the publisher never spells it that way. `rhuc` is added as
its own passthrough entry rather than silently overwriting the collision.

24 distinct package-id suffixes were measured across the 119th Congress's
21,947 BILLS files; BillTrax's map reached 12 of them correctly, had no entry
for 12 more (1,027 files, 4.7% of the corpus), and mapped one (`rfh`) to the
wrong document. The vocabulary was then cross-checked against DeltaTrack
upstream's own authoritative govinfo code list
(`civictechdc/DeltaTrack:tools/fetch_govinfo.py`) and extended with the 30
further codes it carries that neither BillTrax nor the 119th measurement
produced, each marked `measured_119th=False` and cited to that source.
`VERSION_CODES` now holds 72 entries.

**The package id is the identity; a name-derived slug is a flagged
fallback.** A version-type name is not unique per version — a numbered
reprint shares its original's name (`eas`/`eas2`, `eh`/`eh1s`, `rfs`/`rfs2`)
— so `bill_version_package_id`/`version_slug` remain for a caller that holds
only a slug or type name, but `acquire_bill_pdf` requires the caller's own
stated `package_id` in place of `slug`, never alongside it, when one exists.
`version_slug_reprints` names every other slug a shared type name could
mean, so the ambiguity is queryable rather than merely present.

**Format is chosen by GovInfo rendition folder, not file extension.**
`BillTextFormat` is built in exactly one place today, from BILLSTATUS XML,
which carries no `<type>` — so `choose_format`'s type-string table is dead
code against the data this repository actually parses, and the live path
names a format from the URL's rendition folder (`xml/`, `html/`, `text/`,
`pdf/`, `uslm/`), because BILLS states its USLM rendition at `uslm/{id}.xml`,
indistinguishable from `xml/{id}.xml` by extension alone. USLM is recognized
by name and folder and, since "USLM joins the sealed body preference;
granules and committee prints join the grammar" above,
`PACKAGE_BODY_FORMATS["uslm"]` fetches it directly for a BILLS package.

## DeltaTrack is a pinned dependency, not a port

Adopted 2026-09-19 with [bill sections and section diff](sources/congress-bill-tree.md).

SpicyDocs depends on [DeltaTrack](https://github.com/civictechdc/DeltaTrack),
pinned by commit sha in `[tool.uv.sources]`, behind the optional `bill-diff`
extra. BillTrax's vendored `submodules/DeltaTrack` and its TypeScript fork
(`bill-tree.ts`, `financial.ts`, `diff.ts`, `section-diff.ts`'s fallback
core, `python-diff.ts`, `scripts/diff_service.py`) **are to be deleted**.

The reason is measurement, not preference. A port was planned because the
vendored directory carried no pin and no upstream remote — true of the
directory, false of the project: the canonical repository has since moved to
the same Civic Tech DC organisation as SpicyDocs and SpicyRegs, and at
`c636448` (2026-09-13) is an installable package with 12,479 lines across 25
modules (against the vendored snapshot's 2,846), 120 test files, and every
divergence and bug the port's own inventory had flagged already fixed,
including the `resolution-body` gap. Porting 1,439 lines by hand to reach a
place 12,479 maintained lines already occupy preserves effort and nothing
else.

A git pin rather than a PyPI range because nothing is published to PyPI yet:
`deltatrack` is an unclaimed name on the index. **Move the pin to a release,
and drop the `[tool.uv.sources]` entry, as soon as upstream publishes one** —
a git rev names a commit on a branch that can be force-pushed out from under
it.

**Consequence for the gate.** `uv sync --extra bill-diff` clones from GitHub
the first time a cold environment resolves it; uv caches the checkout, so
later syncs and every `--frozen` run are offline, and the lock records the
resolved commit either way. Without the extra, `./scripts/check` still runs;
the adapter tests skip and say why.

Gaps this port found in upstream and left there rather than patching
locally — a collision-group cap, an asymmetric-pair guard, a body-size cap
on inline word segments, hyphen-tolerant matching tokens, the `" "`/`""`
join change's effect on stored rows, version derived from a file name
instead of a keyword argument, an entry point that reparses bytes already
parsed once, and the XML path importing the PDF stack — are listed with
file:line citations in "To raise upstream" on the bill-tree page; raise them
with DeltaTrack's maintainers rather than working around them here.

## GPO PDF text normalization runs after extraction, gated by evidence

Adopted 2026-09-19 with [GPO PDF text normalization](extraction-gpo.md).

`extraction/gpo_normalize.py` is a post-extraction step, not part of PDF
extraction itself: given the page texts `DocumentExtractor` already
produced, it strips the seven GPO print artifacts BillTrax's
`pdf-normalize.ts` named and rejoins line-wrap hyphens, gated on page-level
evidence rather than running unconditionally. Two of the seven artifacts
changed shape under this repository's PyMuPDF-based extractor and were
re-derived, not just ported: GPO line numbers move from a suffix to their
own physical line, and the per-page footer spans several physical lines
whose job-code pattern no longer matches BillTrax's literal `DSK`-prefixed
regex against real 2025-session output. `is_gpo_layout` detects a content
line followed by a bare one- or two-digit line and gates hyphen-rejoin on
that adjacency — never on a document without a corroborating gutter number —
which is what keeps a genuine hyphenated compound like "President-elect"
from being merged on an unnumbered (ENR-style) document.

`sources/agency_reports/report_blocks.py` (see "Agency-report blocks are
parsing an uploaded artifact, not acquisition" below) expects this step to
have already run: BillTrax's own call site skipped `normalizePdfText`
entirely, and the hyphen-wrap fragments that produced are a direct
consequence of that omission, not of the heading grammar itself. Route every
PDF-derived text body through `normalize_gpo_pages` before any
heading/section/agency splitter reads it — the two modules are not yet
wired together, so a caller does this itself today.

**Compared against upstream DeltaTrack, and kept as its own port.**
DeltaTrack solves the same problem ahead of its own diff engine, but
extracts with pypdfium2 rather than PyMuPDF — a **licensing** choice there
(PyMuPDF is AGPL-3.0), not a quality one — which makes its raw text a third,
incompatible line shape: its rules anchor on a leading gutter digit and a
PDFium-specific soft-hyphen glyph, neither of which PyMuPDF's output ever
produces. Feeding PyMuPDF text through DeltaTrack's functions would not
raise; it would silently match nothing and return the input unchanged — the
same "formatting assertion, not a verification" failure shape a clean no-op
result presents. Two extractor-shape-independent design choices carried over
anyway, re-derived against this repository's own fixtures rather than
assumed from DeltaTrack's: truncating from the VerDate line to the end of
the page, and collapsing GPO's doubled-single-curly-quote convention to one
straight double quote. DeltaTrack's own unconditional hyphen-rejoin was not
adopted — measured unsafe against a real fixture, where it would delete the
hyphen in a genuine compound like "President-elect".

## Agency-report blocks are parsing an uploaded artifact, not acquisition

Adopted 2026-09-19 with [agency-report blocks](sources/agency-report-blocks.md).

`parse_agency_blocks` and its two aggregates, `agency_recurrence` and
`sections_for_agency`, are a straight port of BillTrax's `report-parser.ts`
and the two read-side queries of `committee-reports.ts`. **This is parsing
of an uploaded artifact — a committee report a user attaches to a bill — not
acquisition.** There is no publisher endpoint to fetch here; the parser and
aggregates take already-retrieved text and rows, exactly as `bill_tree.py`
takes already-fetched bill XML. That is why the parser lives under
`sources/agency_reports/` (alongside the other publisher-format-to-typed-
fields parsers) and the two aggregates live under `interpretation/` (shared
logic over the facts those parsers produce), rather than either gaining
fetch code of its own. The GovInfo CRPT package body that would feed
`committee_reports.text` in a hosted system is the separate, already-
existing `sources/govinfo/body_acquisition.py`; this module does not depend
on it and is tested entirely offline.

**It expects normalized input.** GPO line numbers, footers and hyphenated
line-wrap rejoining are the sibling `gpo_normalize` concern (see "GPO PDF
text normalization runs after extraction, gated by evidence" above) — this
module does not do that work itself, and feeding it raw extraction text
reproduces BillTrax's own measured defect of a hyphen-wrapped heading tail
becoming its own spurious block. Despite the inherited name,
`parse_agency_blocks` is **not** an agency-name detector: measured on real
committee reports it fires as readily on a section title (`CONTENTS`,
`INTRODUCTION`) as on a real heading (`DEPARTMENT OF THE ARMY`); a returned
block's `agency` field is "the text of a heading", never "a verified federal
agency."

## Interpretation lives in spicy-docs; hosted tables carry its outputs

Adopted 2026-09-19 with the [interpretation package](interpretation.md).

**Interpretation lives in spicy-docs; the tables it produces are hosted
elsewhere.** spicy-docs is the one home for code — acquisition,
publisher-format parsing and shared interpretation alike; a metadata host
receives tables and their documentation, never logic, and an application
keeps only auth, email, per-user rows and pages. `spicy_docs.interpretation`
holds the shared logic that reads publisher facts and decides something
about them: bill stage, money-bill kind and reason codes, identification
confidence, vote and release bill links, classification and summary
provenance. Each module states its rule vocabulary as a tuple of frozen
records read in order, and every output is a frozen finding naming the rule
and the identifiers it fired on, so a hosted row can carry its own
provenance. Every module is pure: no network, no database, no clock except
an injected one.

This corrects several of BillTrax's own behaviours in the port rather than
carrying them forward, each covered by a test showing the old outcome beside
the new one: stage inference now reads untruncated action text
(`interpretation/bill_stage.py`, was truncated to 100 of 500 stored
characters); one signing-date derivation replaces two that disagreed;
committee referrals come from system codes, not substring name matching;
model classifications now carry their model and prompt version, which
BillTrax's classification table did not hold.

## Row shaping lives in spicy-docs; spicy-regs converts and publishes

Adopted 2026-09-19, design from
[the table-contract layer](research/table-contracts-2026-09-19.md); landed
the same day as `src/spicy_docs/schemas/` (twenty-two contracts, 407
columns) and `src/spicy_docs/interpretation/bill_family.py`, documented in
[Tables](tables.md).

**Row shaping lives in spicy-docs; spicy-regs converts and publishes.** One
module per table family under `src/spicy_docs/schemas/`, stdlib-only
(`dataclasses`, `json`, `typing`, `collections.abc`, `hashlib`; no pyarrow,
no DeltaTrack, no `sources.*`/`interpretation.*` imports), holds each
table's column tuple, identity, version column and one pure `shape_*`
function — `schemas/` stays the leaf `public_tables/profiles.py` already is,
so spicy-regs can import a column tuple without pulling DeltaTrack, pyarrow
or an HTTP client. spicy-regs's own transform imports `spicy_docs.schemas.*`
only, builds an all-VARCHAR Arrow schema from the column tuple, and merges
through the existing shrink-guarded upload path; it does not re-derive any
rule.

The family builder that composes interpretation findings with parsed
documents (`build_bill_family`) lives at
`src/spicy_docs/interpretation/bill_family.py`, not in `schemas/`, because
composing them requires importing `sources/` and `interpretation/`, which
the leaf must not do. **The bill family is one pass**: for a bill with A
actions, C committees, V versions and S sections per version, building every
table but the diff is O(A + C + V + ΣS), linear in rows produced, with no
table re-reading another's output. Diffing is the one superlinear operation
in the family, and it is bounded on purpose — consecutive version pairs
only, V-1 diffs rather than V², each further bounded by DeltaTrack's own
retrieval gate — because it is the only place in the pass where letting it
run unbounded would cost more than the rows it produces justify.

## Reconstruction is a derivative layer behind an extra, proved on CFR before it touches bills

Adopted 2026-09-19, from [the gap-closing proposal](research/closing-the-gaps-2026-09-19.md)
§3; landed the same day as `src/spicy_docs/reconstruction/` (merge 1580899),
measured by [the CFR benchmark](research/reconstruction-benchmark-2026-09-19.md)
and documented in [Reconstruction](reconstruction.md).

**Retrieve, then reconstruct, then interpret.** A body is taken in the
publisher's most structured rendition first (the sealed body preference).
Reconstruction runs only where retrieval has nothing structured to give, and
its output is a derivative: every node carries the evidence spans and the
named rule that placed it, every serialized element maps back through a
sidecar, and a hosted row built from it says `derivation = reconstructed`.
It never rewrites text beyond three named, evidence-gated repairs (small-caps
case, print-wrap hyphens, GPO quote pairs), and it interprets nothing.

**Why an extra.** Schema validation needs lxml against a bundle pinned by
digest, resolved from a local catalog with no network. Core stays free of it:
the package imports without lxml, reports the schema finding as "not
checked" rather than "valid" when the extra is absent, and the subprocess
test proves both.

**Why CFR first, bills second.** Every CFR edition GovInfo serves has XML, so
hiding it gives a paired benchmark that can fail: text precision and recall,
hierarchy F1, critical discrepancies, coverage and acceptance are scored
against the publisher's own structure. The corpus that has no XML is bill
text from the 103rd to the 112th Congress, HTML and PDF only; its profile
(`bill_dtd`, targeting the DTD DeltaTrack already parses) is the deployment
target and is written only after the benchmark holds. The HTML rendition,
not the PDF, is the input wherever it exists: the committee-report
measurement showed PDF text splitting words and dropping the rows the HTML
keeps.

**What a measurement must carry.** Rules are frozen before the scored
corpus is read, and the run records which rules were derived from which
documents so a contaminated split is labelled rather than presented as
blind. The critical-discrepancy class must see the corpus's own spellings
(en and em dashes in citations, `$`, `%`, word suffixes); a check that could
not fail on the dominant form is not a check. Acceptance reads the review
flags the parser raised. Every request is logged, the corpus manifest pins
each body's digest, and the pin names a reachable revision.

**What it does not do.** No byte recovery of lost XML, no GovInfo signature
on derived files, no legal-effect interpretation or amendment
consolidation, no forcing reports into a legislative schema, no OCR of
scans in the pilot, no private documents. The optional model call for
undecidable regions stays an injected seam with abstention until a corpus
shows a region rules cannot place; forty CFR sections showed none.

**Open, and whose call.** Whether the CFR benchmark has answered its
question, whether a dash-spelling disagreement between two publisher
renditions counts as critical, and whether the model seam is ever wired are
put to the maintainer at the end of [Reconstruction](reconstruction.md).
## Enacted-law identity is the publisher's number folded onto public/private

Adopted 2026-09-19 with the [A8 contracts](research/table-contracts-2026-09-19.md) (`schemas/law_tables.py`,
`sources/uscode/classification.py`), documented in [Tables](tables.md) and
[the classification tables](sources/uscode-classification.md).

**One law has one key across three publishers' spellings.** The Congress.gov list route says `Public Law` /
`Private Law`, the PLAW bulk folder says `publ` / `pvtl`, and the PLAW USLM `meta` says `public` / `private`;
`laws` seals `law_type` to the USLM's spelling (`public`/`private`), keeps the list route's own string beside it
in `publisher_law_type`, and derives the package id (`PLAW-119publ1`) by the bulk-file rule, so the list route,
the bulk folder and the USLM file join without a crosswalk. The citation is taken only from a USLM `meta` whose
own congress, kind and number match the row — a `meta` for another law refuses rather than annotating the
nearest row — and a NULL citation is read through `uslm_outcome` (`captured` / `unavailable` / `not_requested`),
never as absence: four of the 119th's 108 laws lagged in PLAW bulk on 2026-09-19.

**`congress_bills.statutes_at_large_cite` stays NULL in the family build on purpose.** The family sees one
BILLSTATUS document and its printings; the citation lives in a different package the laws rollup acquires once
per law, so filling it inside the family would fetch every PLAW twice or make the family read another table's
output, which the one-pass rule forbids. The host joins `laws` on `bill_id` at merge time.

## Committee assignments come from the chamber files; the legislators JSON stays the crosswalk

Adopted 2026-09-19 with the [A9 contracts](research/table-contracts-2026-09-19.md)
(`schemas/roster_tables.py`, `sources/congress/committee_rosters.py`), documented in
[Tables](tables.md) and [Committee rosters](sources/committee-rosters.md).

**`committees` is keyed on the publisher's `systemCode`** — the identifier every bill, report and communication
already refers to — with the detail record folded onto the same row only when its own `systemCode` matches.
**`committee_assignments` is keyed `(congress, system_code, bioguide_id)`**: both chamber files state the
bioguide on every seated member, so unlike `member_votes` there is no file-stated id to prefer over it, and the
key's target is `members.bioguide_id`. The chamber files' own committee codes are kept beside the joined
`system_code`, and the two join rules (House `II00`→`hsii00`, Senate `SPAG00`→`spag00`) are the legislative
data map's measured edges, not a normalization the reader invented.

**A row says where its Congress came from.** The House file states its Congress and session, and the reader
refuses a file whose statement differs from the request; the Senate file states no Congress, so its rows carry
the caller's Congress with `congress_basis = "caller"` — weaker provenance published, not hidden. The Senate
file's LIS id is published as one seat fact; the LIS crosswalk itself remains the legislators JSON, still the
only route to a former senator's LIS id, and nothing here duplicates it.

## A prompt states the JSON shape its reader parses, from one declaration

Adopted 2026-09-19 from the first live model run (register row C1 of
[closing the gaps](research/closing-the-gaps-2026-09-19.md)), landed in
`interpretation/model_call.py`, `bill_summaries.py` and
`section_classification.py`, documented in [Interpretation](interpretation.md).

**The sealed prompt asked for prose; the reader required keys the prompt never
named.** `SUMMARY_PROMPT_TEMPLATE` (`v1`) asked for "a single paragraph", "a
short phrase describing the most-affected audience" and "up to three notable
provisions" while the adapter asked for `application/json`, so the key spelling
was left to the model. One live `summarize_bill` call over the repository's own
fixture bill (119 HR 6028, `gemini-3.8-flash`, HTTP 200, 204 input and 206
output tokens) came back with `summary`, `most_affected_audience` and
`notable_provisions`; `_read_answer` requires `summary`, `audience` and
`topThreeProvisions`, so it refused the answer. **The model did not even choose
the same wrong spelling twice**: the retained `c1-provenance.json` records
`most_affected_audience`, while that receipt's own README tabulates
`affected_audience` from another invocation of the byte-identical prompt. Both
miss the same two keys and refuse identically, which is why the fix is a prompt
that states its key set rather than a reader taught one more synonym. **A keyed production run would
have published zero `bill_summaries` rows**, every bill refused. Every test
stubbed the call with the right keys, so nothing offline could see it. The
evidence is the C1 receipt,
`~/Work/corpora/supply-2026-09-02/receipts/d1-measured-run-2026-09-19/`
(`c1-provenance.json`, `scripts/c1_model_run.py`). The fix is proved live in
`c1-prompt-fix-2026-09-19/` beside it: three keyed calls, one per prompt kind,
over the same fixture bill — the summary and the diff summary are now answered
in the named keys and read into rows, and the classification answer came back
in the named keys too but was refused by the batch guard for naming a section
id it was never sent, which is a different defect and is recorded, not fixed
here.

**A prompt and its reader are now one statement.** Each module declares its
answer's keys, types and enforced counts once as `AnswerField` records;
`answer_shape_block` turns that declaration into the lines the prompt sends and
the reader looks its values up through the same records, so neither side can
name a key the other does not. A test derives both sides from the declaration,
and a second feeds `_read_answer` the exact shape the live call returned and
requires the refusal to name every missing key.

All three prompts moved to `v2` and their digests were re-pinned, because all
three left something to the model: the summary prompt named none of its keys;
the classification prompt named its three but not their types; the diff prompt
named its five but not theirs, so a list with nothing in it could arrive as
`null` and refuse the whole answer. Spellings a model may reasonably choose
instead — `top_provisions`, `section_id`, a `classifications` wrapper around a
requested array — stay accepted by the reader and unoffered by the prompt: a
one-directional tolerance, declared beside the key, never a second name the
answer may choose between. Neither spelling the `v1` prompt provoked —
`most_affected_audience`, `affected_audience` — nor `notable_provisions` was
added as an alias: teaching the reader the answers a defective prompt provoked
would have left the prompt defective, and there was no end to the list.

**BillTrax never relied on prompt prose for the key set; the port dropped the
half that carried it.** Each of the three originals declares a zod schema and
passes it *on the request*: `bill-summaries.ts:41-45` (`summary`
`.min(60).max(1200)`, `audience`, `topThreeProvisions` `.max(3)`) to
`generateObject` at `:163-165`; `summarize/route.ts:13-19` to `streamObject` at
`:116-121`; `classifications.ts:21-29` (a `classifications` array of
`sectionId`/`label` enum/`confidence` 0-1) to `generateObject` at `:76-78`.
`SUMMARY_CHARS`, `MAX_PROVISIONS`, the key spellings and the `classifications`
wrapper this repository tolerates are all transcriptions of those schemas. The
port copied the prompt bytes and left the schema behind, so the request stopped
stating what the reader still enforced — and only a live call could show it.
This is recorded so nobody later "restores" a prompt to its original bytes
believing the original asked in prose alone. **Follow-up, not taken here:**
widen `ModelCall` to carry an optional response schema derived from the same
`AnswerField` tuples — `extraction/gemini.py:154-157` already sends
`responseJsonSchema` — putting the enforcement back on the request where
BillTrax had it, with the declaration still in one place.

**Two ported prompts therefore lost their byte-for-byte seal, on purpose**: the
diff prompt against `summarize/route.ts:119-129` and the classification prompt
against `classifications.ts:86`, both keeping their source's wording and order
and adding only the answer's shape. A prompt reproduced exactly, stripped of
the schema that made it work, and refused on arrival is a faithful copy of
nothing. No row of any of the three model tables has ever been published under
`v1` for the change to invalidate: the R2 read taken immediately before the D1
run (`~/Work/corpora/supply-2026-09-02/receipts/d1-measured-run-2026-09-19/prior-tables.json`)
found 35 of 36 tables `404` — never published, which that file distinguishes
from a zero-row table — including `bill_summaries`, `diff_summaries` and
`section_classifications`; only `congress_bills` existed. BillTrax's own
`diff_summaries` rows, written from these same prompt bytes, carry no version
label to invalidate either: `migrations/012_ai_provenance.ts:26` adds
`prompt_version` to that table as NULLable, and the route's insert
(`summarize/route.ts:134-136`) writes only `id`, `bill_id`, `from_version`,
`to_version`, `summary_json` and `created_at`, so the column is never filled.
The claim here is about the spicy-docs `v1` label.

### Addendum, 2026-09-20: the shape is on the request, and the prompt's remaining ambiguity is measured

The follow-up named above is taken. `model_call.answer_schema` derives a draft
2020-12 schema from the same `AnswerField` tuple the prompt and the reader are
built from; `ModelCall` carries it as an optional `response_schema`; the three
generators pass it; and the Gemini adapter sends it as `responseJsonSchema`
through `extraction/gemini.py`'s `json_generation_config`, which is now the one
home for those two request keys rather than one spelling per caller. The
schema requires every declared key, allows nothing else, bounds the summary by
`SUMMARY_CHARS` and the provisions by `MAX_PROVISIONS`, bounds `confidence` to
0–1 and draws `label` from the five sealed labels — that last one restoring
`classifications.ts:21-29`'s `z.enum`. **No alias appears in a schema**, for
the reason none appears in a prompt: a tolerance offered on the request stops
being one-directional.

**The prompt bytes did not move.** The schema travels in the generation config,
so all three `PROMPT_VERSION`s stay `v2` and all three pinned digests are
unchanged, which the prompt-seal tests assert. **`require_fields` and every
reader stay exactly as they were**: a provider may accept a schema and answer
around it, so the schema is what was asked for and the reader is what is
accepted. Only the reader's refusal keeps a row out of a table.

`AnswerField` now declares `shape` and `bounds` — the type and the range *the
reader enforces* — and derives both its prompt words (`kind`) and its schema
from them. Before, the prose was the declaration and a schema would have been a
second one; two statements that agree on the day they are written is the shape
of the defect this entry is about. Each shape carries its schema *and* the
words the prompt pronounces it in, in one record, so a fourth cannot be added
that renders silently; and a bound a shape's phrase cannot state is refused at
construction, so the request can never enforce more than it says. That guard is
load-bearing and mutation-checked: removing it fails six cases.

**The adapter moved into spicy-docs** (`interpretation/gemini_call.py`). It was
in spicy-regs (`transforms/model_call.py`), which is why the 2026-09-19 run had
to load it by path; the register's own C1 row always named spicy-docs as its
home. Both halves it joins are here, the schema it now sends is derived here,
and no hosting application needs its own copy of a request body. **This widens
`ModelCall` for every implementation**: a call site now passes
`response_schema`, so an adapter that takes only `model` and `prompt` raises.
spicy-regs' copy is one such, and should become an import of this module rather
than a second body shape kept in step by hand.

**`build_bill_family` no longer dies with a refused answer.** Found by
spicy-regs adopting 0.21.3: a `ModelCallError` escaped the builder and aborted
the whole rollup, and a caller that caught it outside had to report a refused
answer as a *declined* one — "its text is below the minimum" — which is false
about the printing. The three model call sites now run inside the same guard
the shapers do (`_model_answer`), filing a `FamilyRefusal` with the model's own
message and finishing the bill. Only the message: `ModelCallError.details` is
the answer itself, which for a summary is model prose about the document. Every
refusal the pass files now names its bill first, `section_classifications`
included — it was the one table whose refusals omitted the bill key, so a
rollup reading `identity[0]` across bills could not place the printing.
`CredentialRefusedError` and `ExtractionError` still abort, because a 401 must
end a run rather than be filed per row and a transport failure establishes
nothing about the printing.

**What one live call then measured** (receipt
`~/Work/corpora/supply-2026-09-02/receipts/c1-classification-2026-09-20/`; same
fixture batch, prompt digest `6add710c…` byte-identical to the day before, 263
in / 80 out, USD 0.000279). The classification answer honoured the schema in
every respect it constrains — a bare array, three rows, the three keys and no
others, a sealed label, a confidence in range — and was refused again by the
batch guard, because **the model returned each section id with the prompt's own
square brackets still around it**: `[introduced-in-house|govinfo|0]` for
`introduced-in-house|govinfo|0`. `section_block` writes `[<id>] <heading>` and
the field asks for "the section's bracketed id, copied exactly as given below",
so a model that copies exactly what it is shown includes the brackets; the
reader requires the bare id. That is the same defect family as the `v1` key
spellings one layer down — the prompt describes its value ambiguously and the
reader enforces something else — and every stub ever written answered with what
the reader wanted, so nothing offline could see it. A keyed production run
publishes **zero** `section_classifications` rows.

**Fixed as `v3`, and proved, the same day.** The `sectionId` field now asks for
"the section's id: the text inside the square brackets below, without the
brackets", `section_classification.PROMPT_VERSION` is `v3` and its digest is
re-pinned. `section_block` is **not** touched: `[<id>] <heading>` is BillTrax's
own rendering, and the phrase that misled the model was this repository's own
2026-09-19 addition, so the wording is what moves. `_read_row` is not touched
either. Two identical keyed calls over the same fixture batch
(`c1-classification-v3-2026-09-20/`, prompt digest `411e9f67…` recorded beside
the `v2` `6add710c…`, 534 in / 200 out, USD 0.00066) each answered in the
batch's own ids and each stored three `section_classifications` rows under
`prompt_version` `v3`, with no refusal and no substituted id — two because one
success does not establish a route. `classify_sections` is now
module-measured, and all three model-backed modules produce live rows.

The `v2` answer stays in the repository exactly as it came back, as a committed
fixture with a test asserting both that the schema accepts it and that the
reader refuses it: the counter-example is what keeps the reworded phrase from
quietly regressing, and it is the standing demonstration that a schema the
provider honours is not the contract.

The two summary prompts stay at `v2`. A `PROMPT_VERSION` is per prompt so a
stored row remains attributable to the bytes that produced it; only the
classification prompt's bytes moved.

`sectionId`'s schema is deliberately `{"type": "string"}` and **not** narrowed
to the batch's own ids, although `_read_row` refuses one outside them.
Narrowing it would have forced an exact match, produced three rows, and hidden
why the earlier run failed. Now that the cause is named, the prompt is the
thing to fix: an `enum` of the batch's ids would make a badly worded prompt
produce correct rows, which is how a defect survives a fix.

## The shared Zyte transport lives in spicy-docs and records that a capture was proxied

Every `SourceAcquirer` here takes an injected `transport: httpx.BaseTransport`,
but the Zyte adapter was a standalone fetcher, so the two routes the
[PDF-only census](research/pdf-only-corpus-2026-09-19.md) recorded as walled —
CBO's DataDome-protected documents and Congress.gov's CRS HTML — could not be
reached through the acquirers that already know their locators, byte bounds and
identity proofs. `transport/zyte.py` is that adapter in the injectable shape,
over the same `sources/zyte.py` fetcher; it adds no second HTTP client and no
second copy of the provider protocol.

**It lives here because RefSpec depends on spicy-docs, not the reverse.**
RefSpec's `registry/infrastructure/zyte_transport.py` and this package's
`sources/zyte.py` are the same adapter written twice. Acquisition is this
package's job, so the shared copy is this one and RefSpec imports it; until it
does, the duplicate there is a known copy, not a second design.

**A proxied body is evidence of what Zyte's client was served — a weaker
statement than a direct capture makes.** `transport/capture.py` requires that an
injected transport add no hidden request and no authentication to the
publisher. This transport honours that literally: exactly one provider call per
`handle_request`, no retry of its own, and no credential reaching the publisher
— the token authenticates *to Zyte*. What the publisher saw was Zyte's client,
so every response carries a `ZyteProxyRecord` naming the provider's request id,
the mode and the proxy, on the response's `extensions` and in order on the
transport, and a receipt row that omits it would report a proxied capture as a
direct one. A resolved URL other than the requested one is refused rather than
reported under the requested URL, because the caller's client follows no
redirect and would otherwise never see the hop.

`browserHtml` stays distinct from `httpResponseBody` for the same reason: a
rendered DOM is not bytes any publisher sent, it states no publisher
`Content-Type`, and `ZyteHttpResponse.mode` is what says which of the two a
retained body is.

**What this bought, measured.** [The PDF-family rollup
measurement](research/pdf-family-rollup-yield-2026-09-20.md) ran both walled
routes through it on 2026-09-20. Congress.gov's CRS HTML answered `200`
directly and through the proxy, byte-identical both ways. CBO answered
`200` through the proxy on its *unwalled* feed — byte-identical to the keyless
capture, which is the control that says the wiring works — and yielded no
document at all on nine walled URLs over eleven attempts in both modes. Read
those failures carefully: 3 carry Zyte's own `/download/temporary-error` slug
and the other 8 are a bare provider HTTP 520, which is the proxy's transport
failing. Under this repository's rule that a transport failure is not a record,
**none of the eleven establishes that CBO refused the proxy** — only that this
proxy could not fetch those paths. A paid
proxy is therefore not a way past that wall, and `ZyteBudget` exists so the
next attempt cannot find that out expensively: it is one ceiling shared by
every transport drawing on it, since a per-acquirer request budget cannot bound
spend across a run that opens one acquirer per family.

## A citation is keyed on where it was read, and its rule carries a version

`document_citations` is one shared link table over every document family
(`schemas/document_citation_tables.py`), built first on the House committee
activity reports as the
[rollup's build order](research/pdf-family-rollup-yield-2026-09-20.md#recommended-build-order)
asked. Three choices in it are load-bearing.

**The identity is `(document_key, text_sha256, cite_kind, target_key,
span_start)`, and the span is in it because the span is the yield.** (Since
0.50.0 `document_kind` leads it; see
[citations are keyed by source kind](#document_citations-is-keyed-by-source-kind-first).) The
obvious identity — document, kind, target — would collapse CRPT-118hrpt968's
267 bill mentions into 179 rows and throw away which page each discussion is
on. The aggregate shape is derivable from this one (`GROUP BY document_key,
cite_kind, target_key` with `COUNT(*)` and `MIN(span_start)`) and the reverse
is not, so keeping the occurrence is what keeps the table evidence rather than
a lossy copy of the MODS. And a lossy copy is exactly the risk, because of
what building this measured:

> **The package MODS already states the bills, laws, U.S. Code sections and
> Statutes pages the print names.** Across all eight sampled activity reports
> at full page depth, print-only is **0 of 1,406 bills, 0 of 174 laws (the one apparent survivor is the print's misprint 188-11), 0 of 37
> Code sections and 0 of 7 Statutes pages**
> ([MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)); on the two
> packages this branch pins, 179 of 179 and 39 of 39 bills, 3 of 3 and 1 of 1
> laws, 1 of 1 Code sections (receipt `document-citations-2026-09-20/`,
> `tests/test_citations.py`).

The Code line was the second correction, found reviewing the first: this
record originally claimed U.S. Code sections as surviving yield, and
-118hrpt968's whole printed Code yield is `2 U.S.C. 190`, which its MODS
states. The test that was supposed to hold the claim compared bills and laws
and no Code set at all, so it passed while the prose beside it was wrong.

**So the MODS is the authoritative source for those four kinds**, and
`house_activity_reports.associated_bills_json` / `.associated_laws_json` is the
document-to-target join for them; the print's list is a floor bounded by
`pages_read`. What the print adds outright is the committees beyond the one
that submitted the report (27 resolved codes), **87 RINs**, **38 agency
dockets** and 5 GAO product ids — which is why `rin` and `docket_number` are
stored kinds rather than measurement-only rules. No sampled MODS in any
collection states a Federal Register cite, a GAO product id, a CRS report id,
an agency docket, a case docket, a U.S. Reports cite or a dollar figure, so
`stated_by_index` is NULL for those kinds rather than `false`: "compared and
absent" and "no comparison was possible" are different answers.

The rollup reported 883 bills "beyond the index" for this family because it
compared against the `published` listing row — seven fields, no bill — and not
against the MODS the body acquirer already fetches for every package it reads.
That is a real instance of the failure this repository warns about: a check
that could only ever look one way. Under the owner's do-not-recreate rule the
bill *key* is not yield here; the offset at which a 282-page print discusses
that bill is, and no GovInfo record carries it. So `stated_by_index` is a
column, set per row from the MODS, and NULL — not `false` — where no index
record was read, because "not compared" and "the index does not state it" are
different answers. `WHERE stated_by_index IS NOT TRUE` is the consumer's
predicate for the kinds that are genuinely new.

**`text_sha256` is in the identity, and the table is append-only per digest.**
Without it two extractions of the same document collide on one identity and
the merge picks between rows whose offsets mean different things. With it they
are disjoint, which does not retire the superseded rows — nothing here can —
but does stop them from being silently merged; a consumer filters to the
digest `house_activity_reports.text_sha256` states for that document.

**An unsettled key is stored, not dropped.** A bill named without a stated
Congress, and a committee name no supplied roster reaches, keep the rule's
canonical printed form as `target_key` and set `target_resolved` to `false`.
Dropping them would lose exactly what only the print holds; giving them a
NULL key would make them unkeyable. The pinned Senate roster excerpt reaches
only the committees its sampled senators sit on, so `committees_unresolved` is
a floor on what a full roster would settle and never a defect count.

**A settled key says how it was settled.** The committee resolver has four
routes and they are not equally strong: `exact` and `roster_prefix` are
lookups in the supplied vocabulary, while `name_prefix` (a roster name with
prose after it) and `sibling_prefix` (a fragment settled by the same
document's other candidates) are inferences from one print. `target_rule`
carries the route so a consumer can decline the inferences, and two guards
were added in review because the inferences were reaching wrong answers, not
merely weak ones: a run-on candidate whose remainder begins `AND` is refused
(the Senate's *Homeland Security and Governmental Affairs* begins with the
House's *Homeland Security*, and the route published `hshm00`), and a sibling
fragment shorter than `Committee on` plus four characters is refused
(`Committee on A` took Appropriations). Both guards remove published codes
from the rollup measurement and add none; the activity reports' 20 distinct
`system_code`s are unchanged, because a print that wraps a name also spells it
out.

**The bill Congress is an assumption, checked rather than trusted.** A print
writes `H.R. 7806` and never a Congress, so every bare designator is stamped
with the document's own and a cross-Congress mention would publish a wrong
`bill_id` as resolved. `bills_congress_mismatch` runs the index comparison a
second time on `(bill_type, number)` alone: a bill the MODS states only under
another Congress misses the strict key and matches the loose one, so it shows
as a discrepancy rather than as confident wrongness. Zero on both packages.

**Corrected 2026-09-26: the bill Congress is the one the report states it
covers, never the filing Congress.** A Senate committee files its activity
report early in the *following* Congress, so the package id, the summary and
every MODS `<bill>` carry the filing Congress: the eight Senate reports on the
117th in the print-citations window published 1,915 citations and 369 actions
against 118th-Congress bills (CRPT-118srpt99's `H.R. 5376`, the reconciliation
act, as `118-hr-5376`), and because the MODS made the same mistake
`bills_congress_mismatch` stayed zero. The check above could only look one way:
it compared the print with an index that shared the assumption.
`sources.govinfo.activity_reports.covered_congress` now reads the Congress from
the report's own words -- the index title, else the cover's `during/for/in the
Nth Congress`, else the same phrase in the first five pages -- and the host
builds bill keys in it. `house_activity_reports` keeps both: `congress` (filed)
and `covered_congress` with `covered_congress_source`. `bills_congress_mismatch`
then counts the MODS disagreeing, truthfully nonzero on every Senate report. A
report that states no Congress, or whose first stating source states several,
gets no bill key, no bill comparison (NULL, not `false`) and no action row,
rather than the filing Congress as a guess. Measured over all 40 reports:
33 read from the title, 4 from the cover, 3 from the front matter, none wrong
(`~/Work/corpora/supply-2026-09-02/receipts/fix-print-citations-2026-09-26/`).
The same audit's two bill misreads moved `bill_number` to 003: a number with an
attached parenthesized subdivision (`CLAUSE S 2(N)`) and a year opening a line
and closing with a colon (`S. Con. Res.\n2022:`) are refused -- exactly those
three matches of the 31,955 the 002 rule reads over the retained corpora.

**Corrected 2026-09-26: a bill printed under a Congress subheading is that
Congress's (`bill_number` 004).** Two Transportation and Infrastructure
reports set a predecessor bill's history inside the current bill's entry
under a line such as `116th Congress`, and -118hrpt967 heads each Congress of
its committee history, 107th to 118th, the same way; every bill under them
took the report's covered Congress. The join-gaps receipt counted 41 action
keys joining the wrong bill silently and 2 (`117-hr-5119`, `117-hr-5919`)
joining none. `find_citations` now keys a bill inside a subheading's scope
in that subheading's Congress (`congress_subheading_scopes`). The rule reads
only a line that is an ordinal Congress in digits and title case, never the
capitalized or spelled-out lines -- on every Senate report those are the
filing header and roster headings, naming the Congress after the one its
bills belong to -- and not a line the one before continues into (`...
House Resolution 965 of the` / `116th Congress`). **The scope ends at the
next bill entry, not at the next Congress heading**: the reports never close
an in-entry subheading with one of their own Congress, and closing only there
moves 3,926 citations over the 40 reports, 329 of them against the date or
law the print states beside them. An entry starts at a line made only of
bills and public-law labels (`H.R. 8416`, `PUBLIC LAW 117–146 S. 3580 (H.R.
4996)`), except one the next line restates (`S. 4321` / `S. 4321 was
introduced ...`, a paragraph of the same history) and a lone bill a law
table's next cell follows (-118hrpt967's rows). `Prior Congresses` ended a
scope and opened none until `bill_number` 005 (below). A subheading keys its bills even in a report whose
`covered_congress` is NULL, since it is a stated Congress (none of the 40 is
such a report). Replayed over all 40 reports against 0.36.0: 501 bill
citations and 462 action rows move, all in CRPT-117hrpt705, -118hrpt967 and
-118hrpt974; nothing else moves in any report or kind; 40 of the 41 wrong
joins and both orphans are fixed, and every one of the 282 moved keys is
confirmed by the stated introduction date, the law-table row's `Pub. L.`,
the bill catalog's title or, for 16, by reading. Not read: a bill that states
its own Congress inline (`H.R. 6752, 115th Cong.`, `S. Res. 116 of the 112th
Congress`), 31 citations in 11 reports, which still take the document's
Congress, as do the six bills listed under `Prior Congresses` (four of them
among the 31) and that paragraph's `H.R. 1132`, the one wrong join of the 41
left (receipt `fork-execution-2026-09-21/print-subheading-2026-09-26/`).

**Corrected 2026-09-26: a bill the print sets its own Congress beside is that
Congress's (`bill_number` 005).** `S. Res. 116, 112th Congress` in a Senate
report on the 118th published `118-sres-116`; so did every bill a print
qualifies inline. `find_citations` now reads the Congress set right after a
bill (`inline_congresses`): `, 115th Cong.`, `, 112th Congress`, `of the 94th
Congress`, `in the 117th Congress`, `(117th Cong.)` -- the five shapes that
follow a bill in the 40 reports, 446 times, and in none of the budget, bill
or Federal Register texts. It beats a subheading over the bill, which beats
the report's covered Congress. A list one qualifier closes takes it whole
when only `and` or `/` joins its members (`H.R. 1140 and S. 596, 114th
Cong.`; `S. 559/S. 4882/S. 870 (118th Cong.)`); a semicolon ends a group, and
a Congress on the next line with nothing joining it is a subheading, not a
qualifier (-118hrpt967's `H.R. 5005` / `108th Congress`). `Prior Congresses`
no longer ends a scope: its list now states each bill's Congress, and its
subject, `H.R. 1132`, is the 116th-Congress entry's own bill, which the stop
had left `117-hr-1132`. Replayed over the 40 reports against 0.39.2, whose
keys equal the live print-citations generation's (8f2502b6) at all 25,614
spans: 38 bill citations and 10 action rows move in 13 reports, nothing
else in any report or kind -- 35 by a qualifier, 2 by the list it closes, 1
by the scope -- and every new key is that Congress's bill by the catalog
title or the public law the print names beside it, but one: `S. 3907 (117th
Cong.). Became Public Law No: 117–324` is the print's misprint of S. 3905,
kept faithfully, like `118-hr-14106`. A candidate replay that read only the
comma and preposition shapes found 34; the four more are `(117th Congress)`
and `(114th Cong.)`. Not read: `H. Res. 5, rules for the 106th Congress`
(3 in -118hrpt961), an appositive rather than a qualifier (receipt
`fork-execution-2026-09-21/print-inline-congress-2026-09-26/`).

**Corrected 2026-09-26: a committee name both chambers hold is the committee
of the chamber whose print it is.** `committee_vocabulary` collapsed the two
roster files by name with the House first, so *Committee on the Judiciary*,
*on the Budget*, *on Veterans' Affairs*, *on Armed Services* and *on
Appropriations* always resolved to the House: the Senate activity reports in
the print-citations window published 1,746 House codes for their own
committees, 1,717 of them `hsju00` in the two Senate Judiciary reports. The
function now takes a required `chamber` and gives a shared name to it; the two
chambers' vocabularies differ on those names and nothing else. The host reads
the chamber off the package id (`CHAMBER_BY_DOCUMENT_TYPE`) and refuses an id
that states neither, and the same chamber reaches `find_bill_actions`, whose
hearing and markup codes follow the committee that acted: 75 Senate action
rows move from House codes (`H21000`, `H15000-B/H15001/H22000`) to `13100`
and `13200`, with no row gained or lost. Replayed over all 40 reports with the
retained rosters, which reproduce every published committee row
(`fix-print-citations-2026-09-26/replay-chamber.json`).

**A chamber the print names before a committee selects that chamber's
committees (`committee_name` 002).** `Senate Committee on Armed Services` in a
House report read as the report's chamber, and so did `Senate Committee on
Homeland Security` -- a wrapped *and Governmental Affairs* -- which matched only
the House's name. `find_citations` now reads `House` or `Senate` right before
the candidate (`NAMED_CHAMBER`) and settles that occurrence with
`chamber_committees`, each chamber's own committees
(`committee_vocabulary(..., own_only=True)`); a bare name reads as before.
Among its own committees alone, a named name that meant the other chamber's
stays unresolved rather than taking a wrong code. Replayed over the 40
reports: 76 committee rows move, every one a named occurrence -- 11 shared
names (`hsas00`->`ssas00` and the like), 25 Senate-named rows off a
differently named House committee (24 `hshm00`->`ssga00`, `hsru00`->`ssra00`),
36 named prefixes one chamber alone now settles (`House Committee on Small
Busi-` -> `hssm00`), 1 to unresolved and 3 only in route -- and no bare row,
no other kind and no action (`replay-qualified.json`). The known wrong one
is not a federal committee at all: an Arkansas resolution's `House Committee
on Ag-riculture, Forestry, and Economic Development` now settles `hsag00`,
where the same sentence's Senate one had. Not settled: 7 bare names in Senate
reports reach a name only the House roster holds (5 `hshm00`, 2 `hsso00`)
and keep the House's code, because the print names no chamber.

**A rule change moves that rule's version and re-pins its fixture counts.**
Each `CitationRule` in `interpretation/citations.py` carries a `version`, and
`document_citations.rule_version` is the table's version column, so a
re-extraction under a corrected rule wins the merge the way a newer
`prompt_version` does. Versions are zero-padded decimals (`001`) because the
published column is a string and `v10 < v2`. `CITATION_RULE_SET_VERSION` is
*derived* — a digest over every rule's name, version, pattern **and rejects** —
so editing any of them moves it even when someone forgets to move that rule's
own version, and the pinned assertion in `tests/test_citations.py` then names
both. The rejects are in the input because a deleted reject is a silent
weakening: removing three of `public_law`'s once passed the entire suite,
since a reject that is no longer asserted cannot fail. The
procedure when it fails: move the changed rule's `version`, re-pin the digest,
and re-pin the per-print counts the fixtures assert.

The September 24 print audit exercises that procedure with retained source
snippets in `tests/fixtures/document_citations/a10-regressions.json`.
`public_law` 003 admits a numeric schedule label before the law label;
`cfr_section` 003 reads a heading wrapped after its dash and emits one part
link for a subpart-letter list. `rin` 004 rejects fragments inside slash
tokens. `usc_section` 003 emits no link when glued digits or a misplaced
hyphen leave only the prefix of a damaged section readable; the grammar
keeps the full occurrence with `usc_coordinate_continuation_unresolved`.
Other unresolved scope readings retain their existing behavior. The before
and after replays are in
`~/Work/corpora/supply-2026-09-02/receipts/a10-grammar-followup-2026-09-24/`.

**The rules have one home.** `tools/analysis/pdf_family_rollup.py` imports
them rather than declaring them, so the measurement and the product cannot
drift. Proof that the lift itself changed nothing: re-running `analyze` over
the same retained bytes reproduced every count, distinct set, presence figure
and resolved system code in the committed sidecar, with only per-page timings
and the rules' own prose differing
(`document-citations-2026-09-20/diff-sidecar.txt`; the differing-value total
is run-dependent, because the timings are). The resolver guards above then
moved the committee numbers on purpose, and the rollup document states which
and by how much. The committed sidecar was deliberately **not** regenerated —
it is the measurement as run, and a re-run's timings would contradict the
prose the report quotes from it.

## The stack's citation grammar and identifier shapes live here

RefSpec's `citation_grammar` and `identifier_shapes` are now
`interpretation/citation_grammar.py` and `interpretation/identifier_shapes.py`
(consolidation item B4, 2026-09-23). They import only the standard library
(and the grammar the stdlib-only `schemas.tables` leaf, for decision 30's
section fold), spicy-docs cannot import RefSpec (RefSpec depends on it), and RefSpec's pin
cannot be installed beside spicy-regs', so the one place every repository can
reach a shared grammar is here. They were chosen, not merely the first to
move: five prose grammars were run over the same retained inputs and RefSpec's
was right on every hand-read specimen but three range cases
([parsing survey](research/parsing-survey-2026-09-23.md), section 5). The
move itself kept behaviour exactly, and the module docstrings record the
RefSpec path and commit. spicysearch keeps its query grammar: it reads intent
in a query, not a citation in a document (spicy-regs decision 14).

This is the canonical copy now, and it has changed since the move, so
RefSpec's repin moves its receipts' identity and must say so. The changes:
the grammar is linear in its text (a 12-million-character budget volume took
479 s through four readers), with its output unchanged over the survey's
retained inputs; it locates Public Law, Statutes and Federal Register
citations in running text; and it reads four shapes it dropped -- a
zero-padded law number, a part or section followed by its printed heading, a
space after a part's inner hyphen, and a doubled or one-sided dash between
two Code sections -- a range where the two ascend, and one section with a
lost space where they do not (`16 U.S.C. 460l- 9`). The docket column reader also takes the prose reader's
closed trailing tokens (`GIPSA-2006-FGIS-0029-NONRULE`): 67 of the retained
Regulations.gov documents table's docket ids end on one, and it refused them
all. Of the 2,531 RefSpec tests that exercise the two modules, two
expectations see a difference, and both move at the repin:
`tests/test_cfr_ranges.py` expects "41 CFR 60- 1" to stay an unread
coordinate, which reads as the title-41 part it prints now, and
`tests/test_identifier_shapes.py` expects the column reader to refuse
"GIPSA-2008-FGIS-0002-NONRULEMAKING". A third test calls the sort helper by
its old name, `_usc_section_key`, renamed `_usc_section_order` for decision
30, and follows the rename.

What a later change must preserve:

- **A grammar kind is keyed from what the grammar parsed.** Seven
  `document_citations` kinds read through the two modules -- U.S. Code, CFR,
  Public Law, Statutes and Federal Register cites through the grammar, RINs
  and dockets through the identifier shapes -- so every key parses back to
  itself, a range is its two endpoints, and a refusal publishes the key
  unresolved instead of a malformed one. The grammar's refusals are
  respected, not overridden in `citations.py`: fixing a refusal is a change
  to the grammar.
- **A change inside either module moves the reading kind's version.** The
  rule-set digest sees a grammar reader by name only, so
  `tests/test_citations.py` pins what each grammar kind reads over the
  committed fixtures, at its version, and names the version to move when that
  changes.
- **The unpadded Federal Register number is a comparison key, never an
  identifier.** The Register pads some years and not others and the literal
  string is what it issued; `unpadded_federal_register_document_number` exists
  so a join can meet Regulations.gov's padded spelling, and a join reduces
  both sides, tries the exact string first, and refuses a key that reaches two
  documents. spicy-docs holds no join helper; the consumer's index does that.
  Since 2026-09-26 the key also folds the separators Regulations.gov types
  where the hyphen stands (`99 20888`, `2011 - 7212`, `2020--19543`,
  `E-9-18682`): no held number's key moves, and a value only gains a key it
  lacked. The strict SEC comments join does not fold them; they were
  measured on the rulemaking inputs, not its mirror.
- **A docket column is read whole, then walked, then read as prose.**
  `normalize_docket_reference` reads a value that IS one docket;
  `normalize_docket_references` walks the dockets a value opens on, behind a
  longer label, before a note, or in a list, and a list member after the
  first must share the first one's organization or carry the prose reader's
  four-digit-year shape, which is what ends a list at a note's own numbers
  (`FRL-8231-8`). What follows is read with the prose reader's docket
  grammar, except a number another system's label counts (`File No.`,
  `CIS No.`) and a former identifier (`formerly X`); a docket a space broke
  after a hyphen (`EPA- HQ-OAR-2023-0119`) is read whole and as its tail.
  Until 2026-09-26 the reader never searched: over the rulemaking build's
  `fr_docket_links` the walk read 5,389 of the 5,825 link rows naming a held
  docket in full and 67 in part, and left 369 open on prose (`Public
  Notice:`, `FAR Case 2017-014, Docket No. X`). The owner reversed that after
  the rulemaking drift audit found 442 (FR document, held docket) pairs
  missed, 175 from action documents; the reader now gains 490 such pairs,
  432 of the 442, and loses one former docket. The docstring carries the
  measurement.
- **The other-label fence has a closed exception, by the owner's ruling.**
  Four counted labels were measured fronting Regulations.gov dockets rather
  than another system's numbers, and are not fenced: `DHS No.` (5 link rows),
  `FRA Waiver Petition No.` (4), `Administrative Record No.` (1) and `Legacy
  ID` (1), the 11 held pairs (7 from action documents) the fence cost. What
  follows them is still read only with the prose reader's docket grammar.
  A new label joins the list only on the same kind of measurement.
- **A label's counter word ends at a word boundary or its own period.**
  Unfenced, it took the head of the next word (`Docket NOAA-NOS-2024-0104`
  read as `AA-NOS-2024-0104`; a value opening `Notice-MVC-2015-01` as
  `TICE-MVC-2015-01`). Over the audit's values four plural answers moved
  (three `Notice-…` values and `NOP-13-01`), none a held docket, and the
  single and prose readers' answers did not change, so no citation version
  moved.
- **Limits left in place, counted 2026-09-26 over the audit's 612,342
  docket values** (receipt `~/Work/corpora/fork-execution-2026-09-21/
  drift-qualification-2026-09-26/regulatory/d1d2-fix/limits.json`). The
  column shape reads another system's number of docket shape as a docket:
  EPA Federal Register locators (`FRL-8241-1`: 36,601 values, 37,196 link
  rows, nearly all read
  whole by the single reader), AMS dairy document numbers (`DA-00-05`: 224
  values) and NRC enforcement actions (`EA-18-130`: 282 values). The FERC
  fence is keyed on prefix, year and sequence, so FERC's year-less
  interlocking-directorate filings (`ID-3467-000`: 299 values, 317 link rows)
  read as dockets. None of these readings is a held docket, so a join on held
  dockets drops them. `numbering_system` also answers a Regulations.gov
  docket for them, because the docket shape answers first.
- **The RIN key stays `\d{4}-[A-Z]{2}\d{2}`, written once.**
  `identifier_shapes.PUBLISHED_RIN` and `published_rin` are the only published
  key shape; `document_citations.rin` and `communication_rin` key through them.
  The wider shapes admit only damage or placeholders and are for detection
  alone -- `normalize_rin` is never a key.
- **`bill_actions` keeps the 001 public-law spelling on purpose.** Its
  `became_public_law` phrase embeds the pattern the `public_law` citation rule
  read before the grammar, byte for byte, because the phrase vocabulary is
  sealed (`PRINT_ACTION_RULE_SET_VERSION` digests it) and the phrase matches
  raw print text, where an en dash stands that the grammar only reads after
  folding. The key a cite names is the grammar's; the phrase decides only
  whether a sentence says a bill became law.
- **The two dated measurement tools run the rules they measured with.**
  `tools/analysis/pdf_family_rollup.py` reads its join-key rules back from the
  2026-09-20 sidecar it wrote, and the MODS re-check runs on the same rules,
  so both receipts stay reproducible while the product's rules move.

## The stack's identifier minting lives beside the shapes

RefSpec's `iri_minting` is now `interpretation/iri_minting.py` (2026-09-23).
spicy-regs, rulespec-projection and spicysearch each re-implement RIN, CFR,
executive-order, Federal Register and docket minting, and spicy-regs decision
28 puts the minters here, beside the identifier shapes they refuse over, not in
Rulespec Core: spicy-docs is the one place all of them can import. REF-024
(RefSpec `docs/decisions.md`) still assigns identity functions to Rulespec
Core. Decision 28 narrowed that clause so Core owns the lexical spaces and
spicy-docs' tests hold its minters to them; the owner confirmed it on
2026-09-24 and REF-024 carries the amendment (RefSpec `56a76e78`).

Behaviour is RefSpec `4a680c81`'s but for three dockets. Over 3,966,225
paired calls (RefSpec's pinned Federal Register and Unified Agenda columns,
every literal in its minting, zero-part and shape tests, and fuzz) the two
minters' outputs, `ValueError` messages included, are byte-identical except
the dockets this repository's column docket reader newly reads since
2026-09-23, those ending in a `-RULE`-family token:
`GIPSA-2008-FGIS-0002-NONRULEMAKING`, `GIPSA-2010-FGIS-0014-NONRULEMAKING` and
`Docket #GIPSA-2010-FGIS-0014-NONRULEMAKING` mint here and are refused there.
The last is real, the one such value in the pinned Federal Register
`docket_ids_json`. The minter wraps that reader and adds no opinion of its
own, so RefSpec's expectation at `tests/test_identifier_shapes.py:365` moves
when it adopts the module. The module docstring records the RefSpec path and
commit.

What a later change must preserve:

- **The partner namespace stays `refspec`.** It is spelled into every
  `urn:rkaf:partner:refspec:` identifier already minted.
- **Both copied tables are checked only in RefSpec, once it adopts.**
  `_FR_COLLISION_VERDICTS` restates the seven REF-066 rows of RefSpec's
  `hand_validated_interpretations`, whose census, witnesses and audit stay
  there, and `IDENTIFIER_SPACES` restates the compiled profiles in RefSpec's
  vendored `rulespec-conformance` wheel. spicy-docs can read neither source:
  RefSpec is not a dependency, the wheel deliberately is not
  (`tests/releases/test_compatibility.py`), and `rulespec-artifacts`, which
  is, carries no identifier space. RefSpec's adoption therefore adds a test
  holding its collision table equal to the imported `_FR_COLLISION_VERDICTS`,
  and points `test_the_minted_spaces_are_the_contract_verbatim` at the
  imported `IDENTIFIER_SPACES`. A new collision lands in RefSpec's evidence
  first and must then be carried here.
- **spicy-regs' adoption is a question of timing only.** Its decision 27
  chose these rkaf spaces and the deletion of `urn:spicy-regs:frdoc`, having found
  that no published spicy-regs column carries that prefix; its one writer,
  `federal_register_identifier` (`ontology/citations.py`), has no build
  caller. The RIN, CFR and executive-order minters agree with spicy-regs' on
  every measured value but two en-dash RINs, which only this one mints.

## A Mirrulations key that produced no record is unresolved, never processed

**2026-09-20**, closing candidate F2 of the
[gap register](research/closing-the-gaps-2026-09-19.md#26-candidates-from-the-2026-09-20-validation-filed-unmeasured),
filed by [the outside validation](research/register-validation-codex-2026-09-20.md).
The reader wrapped *every* download failure into a key it skipped and carried
on. Two consequences, both of which the fetcher rules in `AGENTS.md` forbid: a
401/403 from the mirror became a skipped key rather than an abort, so a refusal
over a whole prefix would have read downstream as those objects being absent;
and a malformed object was recorded as **processed**, so a repair — upstream,
or to this package's own parsing — could never come back. A test required the
second one, which is how it survived.

What changed, and what a later change must preserve:

- **A refusal ends the run.** Agency-object listings and `download_object_bytes`
  share the check that turns a 401/403 into `MirrulationsAccessRefusedError`, a
  `CredentialRefusedError`, including failures during lazy pagination.
  The mirror is read anonymously, so this is the bucket refusing access
  rather than a key being rejected — but the
  subclass keeps every caller that already aborts on a refusal aborting, the
  way `RegulationsGovAttachmentRefusedError` does for that keyless host. No key
  is written for it, and `fail_fast` does not reach it: that switch governs
  unresolved-key failures.
- **Nothing is marked processed on a failure.** `last_keys` now means "produced
  a record" and is empty until a pass completes; every other key is on
  `failed_keys` with a `KeyOutcome(key, status, reason, attempted_at, attempts)` on
  `unresolved`. `status` is `transport`, `unreadable`, or `requested-empty`.
  The in-run retry still covers `transport` alone — the other two cannot change
  without a new request — but all three are retried on the next run, and
  `unresolved_keys=` puts them ahead of newly listed work so a capped or
  interrupted run cannot keep postponing them. Passing the prior outcomes also
  carries `attempts` forward, counting reader download attempts and in-run
  retries, but not botocore's internal retries. A retention or retirement rule
  remains an unmade decision: permanent corruption is retried indefinitely,
  at the cost stated in the [raw-reader guide](sources/raw-readers.md#mirrulations).
- **An empty 2xx is an answer, not an absence.** A body of zero bytes, `{}`,
  `null`, `[]` or a bare scalar used to be yielded as a record and manifested:
  an empty answer became apparent coverage. It is now `requested-empty`, with
  the shape named in the reason.
- **A populated object must carry record identity.** The downstream review
  reproduced `{"data":{}}` and `{"errors":[{"detail":"upstream failed"}]}`:
  both passed the original object check, yielded null-id rows, and made their
  keys eligible for the processed manifest. Dockets, documents, and comments
  now require their shared source identity, a nonblank string at `data.id`.
  Identity establishes that a record arrived; validating every field would
  exceed the raw reader's role. Both reproduced bodies now yield no record and
  stay unresolved as `requested-empty`, with the missing identity named. Error
  envelopes are named explicitly, and their publisher message passes through
  `scrub_credential` before truncation, logging, or raising. The
  [raw-reader guide](sources/raw-readers.md#mirrulations) owns the API rule.

The spicy-regs host carries a temporary identity guard until it adopts the
release containing this fix. Release adoption and repair of already manifested
null-id rows remain downstream work.

**What callers relied on that is gone.** `DownloadFailures` is replaced by the
`list[KeyOutcome]` that `download_keys(outcomes=...)` fills; `parse_failed_keys`
survives as the non-`transport` subset of `unresolved`, but those keys are no
longer manifested, so a caller that treated it as "done, do not ask again" now
asks again. `iter_source_objects` raises the typed refusal where it used to let
botocore's `ClientError` escape. `last_keys` is no longer populated eagerly with
the whole listing: a partial pass reports nothing, because a partial pass
establishes nothing.

The original regression set mutation-checks both load-bearing changes, with
seven failures each. Dropping the abort fails the four
`test_an_access_refusal_aborts_the_run_and_writes_no_key` cases and both
enumeration cases plus `test_an_access_refusal_is_not_retried_as_a_transient_answer`;
putting the non-transport keys back into `last_keys` fails
`test_iter_records_keeps_parse_failures_out_of_last_keys`, the five
`requested-empty` cases and the two-run repair test. `scrub_credential` grew the
three AWS presigning parameters alongside `api_key`, because an injected signed
resource renders a presigned URL into botocore's message; both of its passes
stay separately mutation-checked.

The identity regression covers every registered Mirrulations record type,
empty and misplaced identities, raw-field preservation, direct and bounded
downloads, and recovery across runs. Disabling identity validation while
retaining publisher-error rejection fails 38 cases, including all six
empty-data reproductions across record types and download branches. Removing
the publisher-message scrub fails its dedicated test, which checks the raised
error, retained reason, and log. These are offline fixture proofs.

The review declined a wider refactor of the 1,012-line module to keep this fix
focused on recovery behavior.

## BUDGET and the GPO-prefixed CDOC reprints join the package-id grammar

Adopted 2026-09-20 with [GovInfo bodies](sources/govinfo-bodies.md) (updated)
and the `budget_volumes` contract; the B4 row of
[closing the gaps](research/closing-the-gaps-2026-09-19.md).

**Why now.** The [MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)
read 24 records across three collections and could prove only eight of them
through `validate_package_mods`: `bodies.py`'s grammar covered CRPT and neither
`BUDGET-*` nor the `GPO-`-prefixed CDOC reprints. The other sixteen were proved
by a fallback that checks the root `accessId` and nothing else — **no final-URL
check and no `collectionCode` check**, because the module derived neither for a
collection it did not cover. That is acceptable for a measurement and not for a
contract, and both families are now hosted targets: the budget volumes carry the
largest real citation yield in the corpus (504 print-only public laws of 518),
and the Senate Secretary's reprints are the `senate_expenditures` table. The
re-check said this record was owed before either family was acquired in product
code; this is it.

**The grammar, as the publisher spells it.**

- `BUDGET-{fiscal year}-{part}` — `BUDGET-2027-APP`. A four-digit fiscal year
  and one of six parts: `APP`, `BALANCES`, `BUD`, `FCS`, `MSR`, `PER`. No
  Congress anywhere in the id, which is the first thing that makes this
  collection unlike every other one here.
- `GPO-CDOC-{congress}sdoc{number}` — `GPO-CDOC-119sdoc3`.

Both are read off the 24 retained MODS records' own `accessId`s and the
re-check's request log, not inferred. **Both vocabularies are sealed to what
was measured**, the same standard the CPRT row held itself to when it declined
to infer `HPRT` from CRPT's `hrpt`: a budget part this sample never saw is a
part whose address is not established, and `hdoc`/`tdoc` are real CDOC document
types that no `GPO-CDOC-` id has been measured carrying. Each is one line plus
the id that showed it.

**Why these are not the neighbouring-collection ids the refusal exists to
reject.** `parse_package_id` refuses `ERP-2009` and `GPO-J6-REPORT` because a
collection-scoped `published` walk returns them and they live at other
addresses. `GPO-J6-REPORT` states `collectionCode` `GPO` — and so, it turns
out, do both of these families. So the discriminator cannot be the collection
code, and it is not: the registered collection is the **whole id prefix**,
matched longest-first, so `GPO-CDOC` is a collection and `GPO` is not.
`GPO-J6-REPORT` therefore still refuses by name, and a test holds it refusing.
The positive half is what the id-prefix match buys: for all eleven retained
package records the MODS's own `raw object` rendition URL is *exactly*
`package_body_locator(id, "pdf")`, so the address is the publisher's statement
and not a construction.

**What replaces the `collectionCode` check that could not run.** Nothing is
dropped; the check is corrected. It compared the record's `collectionCode`
against the id's own prefix, which is true for seven collections and false for
these two. Each entry in `_GRAMMARS` now carries the code its records state
(`PackageGrammar.collection_code`, `stated_collection_code()`), and summary,
MODS, granule summary and granule MODS all compare against that. BUDGET and
GPO-CDOC state `GPO`; the other seven state their own prefix, unchanged.
Measured 2026-09-20 on 11 MODS records, 5 granule MODS and 3 package summaries
— and the refusal still bites, asserted on a record stating `CRPT`.

**What the widening buys, re-derived.** Every one of the sixteen records the
re-check could prove only by `accessId` now passes the sealed validator that
covers it: 11 `validate_package_mods` and 5 `validate_granule_mods` (host
package included), zero refusals. The three package summaries fetched for the
budget contract pass `validate_package_summary` on top of those sixteen, and
the same bytes offered under another real package id of the same collection are
refused (`budget-volumes-2026-09-20/reprove-identity.py`, offline, no request).

**`BODY_PREFERENCE` does not move, and `PACKAGE_BODY_FORMATS` gains no entry.**
Every retained record in both families offers `pdf` and nothing else, so the
sealed order needs no new opinion. The renditions these records state *beside*
the PDF are a JPEG thumbnail (5 of 11) and, on `BUDGET-2027-FCS`, an XLS —
neither is a body text rendition and `extraction/body_text.py` has no
derivation for either, so both stay in `other_renditions` as evidence. The two
Balances volumes state an XLS as well, but inside a constituent record and at a
*granule* stem (`xls/BUDGET-2026-BALANCES-1.xlsx`): an address this module's
package locator does not derive, and a record its root-only reader never reads.
That is a second reason not to admit the format on one sample.

**One fact the widening exposes, and the contract acts on it.** A BUDGET
summary states no `congress` at all. `interpretation/citations.py` stamps the
document's own Congress onto every bare bill designator, so for a budget volume
the print side can only produce `HR7806` while the MODS states `119-hr-7806`.
Those are not comparable, and reporting `false` for every printed bill would be
a `stated_by_index` value no comparison earned. `budget_volume_tables.
budget_index_stated_keys` therefore drops `bill_number` from the comparison, so
those rows land NULL, and the MODS's own bill list is published whole in
`associated_bills_json`.

The congress-blind comparison the re-check *did* make is still worth
publishing, as a count and never as a key: `distinct_bills` and
`distinct_bills_beyond_index_congress_blind` reduce both sides to
`{bill_type}-{number}` through `index_stated_bill_pairs`, which is how **6 of
the 8** distinct printed bills across the eight volumes are print-only. (Six is
what the re-check's own table publishes; the 7 beside it in the sidecar is
print-only *link rows*, a different denominator.) Those two columns say
congress-blind in the name and in their prose, because `{bill_type}-{number}`
addresses no hosted row -- `congress_bills.bill_id` needs the Congress this
family never states -- and the per-row `stated_by_index` stays NULL, since the
strict comparison a row would have to claim still cannot be made.

**The budget-part vocabulary widened once, on a wider walk, and stays sealed to
measured parts** (2026-09-20, receipt `budget-parts-2026-09-20/`). The six
above were measured on a `published/BUDGET` walk from 2025-01-01. The first
hosted run of the PDF-family rollups walked the same route from **2023-01-01**,
served 40 rows and **refused 17 by name** — real budget volumes carrying
`OBJCLASS`, `TAB`, `DB`, `CLIMATE`, `LRB`, `CROSSCUT` or `DOD`. The rollup's
behaviour was correct and is the reason this is recoverable at all: the refusal
named the id, the run logged all seventeen, and nothing was fetched at a
guessed address. Seven parts join the vocabulary, each with the id that showed
it, on the same standard the first widening held itself to: one package summary
and one package MODS fetched per part (14 keyed requests against a cap of 20
declared before the run), all seven stating `collectionCode` `GPO` in both
records and passing `validate_package_summary` and `validate_package_mods`;
the same bytes under another real `BUDGET-` id of the same part refuse, and
`APPENDIX`, `TOC`, `SUPP` and a lower-case `objclass` still refuse by name, so
this is thirteen measured parts and not a token. What the widening also
established is that **an address is not a body**: only three of the seven state
a PDF at `package_body_locator(id, "pdf")`; three state theirs only inside a
constituent at a granule stem, where `acquire` answers
`GovInfoFormatNotOfferedError` and `acquire_granule` is the route; and `LRB`
states one XLS and no body rendition at all. Those are the publisher's own
answers, and none of them was reachable while the id itself refused. One id per
part was measured, which is what is claimed.

## A print's bill-action rows are hosted with their error rate on every row, keyed on the phrase

A House committee activity report says *that* it names `H.R. 1093` — the
package MODS says that too — and it says *what happened to the bill*, which no
index in the [MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)
states. `bill_committee_actions` hosts that relationship. Three choices in it
are worth the record.

**The reliability is a column, not a footnote.** Measured on 60 hand-checked
mentions: a published row is both the right kind and the right bill **83.3%**
of the time where its sentence names one bill and **50%** where it names
several. So `attachment_confidence` carries the class on every row,
`bills_in_sentence` carries the raw predicate it is derived from, and
`docs/tables.md` tells a consumer that `WHERE attachment_confidence = 'single'`
is the trusted view. **The `multi` rows are kept**, at 50%, because they are
readable: the row carries `sentence_start` and `matched_text`, so a consumer
can open the sentence and judge it. A dropped row is a fact nobody can check.
Separately and always stated separately: **recall is 59.6%**. The 83.3% says
what is published is right, never that what the document contains is captured.

**Identity is the action phrase's own span**, not the bill mention's:
`(document_key, text_sha256, bill_id, print_phrasing, span_start)`. One
sentence states *signed by the President* and *became Public Law No: 118-83*
about one bill, which is two rows, and only the phrase offset separates them.
`text_sha256` is in the identity for the reason it is in `document_citations`':
a re-extraction that moves one character moves every offset after it.

**The phrasing vocabulary is sealed and additions-only.** `print_phrasing` is
published, so renaming or deleting a key rewrites rows that are already out;
new phrasings are appended and `PRINT_ACTION_VOCABULARY_VERSION` moves.
`PRINT_ACTION_RULE_SET_VERSION` is derived over the patterns **and** over the
action-code mapping and the chamber rules, because those fill
`billstatus_action_code` on every row and an edit to either changed what is
published while leaving the patterns untouched. Rungs are never invented here:
`sealed_stage` runs the matched phrase through `bill_stage` and records `NULL`
where nothing reads it — 1,670 of 4,456 rows. `passed the House` is one word
from the sealed `passed house` and stays NULL rather than widening a sealed
matcher list to a second publisher's register.

### What the table is for, after two wrong answers

The justification was wrong twice, in opposite directions, by the same
mechanism: **a check validated against a record that was not the publisher's
answer, and so agreed with itself.**

1. It read codes `72` *Hearing held in House* and `74` *Markup in House* from
   the BILLSTATUS guide as proof the publisher already holds this, and
   concluded the table was not worth building. Both are **section 5** values —
   LOC *summaries* version codes, the `<versionCode>` child of `<summaries>` —
   and the self-check scanned the whole guide, validating against a 123-code
   superset drawn from three tables.
2. Scoped to section 3, it found no House hearing or markup code and concluded
   the publisher **has** none, so the print was the only structured source.
   Section 3's own first paragraph says it is representational and that no
   authoritative list exists; **13 of the 35 distinct codes in the retained
   responses appear nowhere in it**, including `H21000` and the three markup
   codes. The overlap that should have caught it asked only whether the
   publisher states a code *this repository maps the phrasing to* — empty by
   construction for those two — so `code_matched == 0` was an identity, and a
   test asserted it as a finding.

**What the bytes support, and what the table is built on:** on a 20-bill probe
of whole action lists, the publisher has **no counterpart at all to 10 of the
15** subcommittee hearings these prints state; the 5 it does state come from
two bills, both coded `H21000`. **All 8 markups are stated and coded**, so
there the print is a second, coded source. `GuideCode.source` now records, per
code, whether a committed fixture can check it or only the receipt can, and the
overlap reads the publisher's codes off the response matched on the event's
wording rather than on this repository's mapping.

## A hearing's bills are a link table keyed on the source that stated them

Adopted 2026-09-20 with the `hearing_bill_links` contract
(`schemas/hearing_bill_link_tables.py`), the two link rules
(`interpretation/hearing_bill_links.py`) and the House Committee Repository
reader (`sources/congress/house_committee_repository.py`); the A2 and A7 rows
of [closing the gaps](research/closing-the-gaps-2026-09-19.md), measured in
[the linkage note](research/hearing-bill-linkage-2026-09-20.md) (198 requests,
receipt `hearing-bill-linkage-2026-09-20/`).

**Why a table and not a column.** `hearing_transcripts.bill_id` was left NULL
on 2026-09-19 because no hearing in 52 stated a `PRIMARY` bill and no meeting
in 12 named one in `relatedItems.bills`. Both findings were re-measured and
both still hold. **The conclusion drawn from them was wrong**, and in the shape
this repository keeps warning about: the measurement asked the two sources a
committee *report* answers and read their silence as the absence of any source.
A hearing has no `PRIMARY` bill because a hearing is not filed against one
bill. A legislative hearing is convened on a **list** — twelve bills on
`CHRG-118hhrg56198` — and four publishers state that list. So the column stays
NULL and the *reason* moves: from "no source states it" to "the relationship is
one-to-many and a scalar column is the wrong shape". `shape_hearing_transcript`
lost its `bill_id` argument, so the contract's claim is now something the code
cannot contradict.

**Why the source is in the identity.** `(package_id, bill_id, link_source)`,
not `(package_id, bill_id)`. Two publishers naming the same pair is the
strongest evidence in this measurement — where the MODS cover and the House
agenda agree, the bill's own *Hearings Held* action confirms **18 of 18** —
and one row per pair would collapse the agreement into a single row whose
`evidence_text` came from whichever source was written last. The aggregate is
derivable from the per-source rows (`GROUP BY package_id, bill_id` with
`COUNT(*)`); the reverse is not, which is the same argument
`document_citations` makes for keeping the span.

**Why `COVER` links and `BODY` only counts.** The MODS `context` marker is the
publisher's own distinction between the bills a hearing was convened on and the
bills its transcript happens to mention, and the bill side agrees with it:
**19 of 20** `COVER` pairs carry a *Hearings Held* action by that committee on
that date (the one exception has three actions in total, so the bill side is
silent, not contradicting), against **0 of 23** `BODY`-only mentions. Six
set-comparisons of the `COVER` list against a list produced by a different
process — the Congress.gov hearing title three times, the Daily Digest
committee entry, `relatedItems.bills`, the transcript's own front page — are
**6 of 6 set-equal over 55 bills**. A mention is evidence of citation, not of
convening; it belongs in `document_citations` with its span, and nothing
promotes one to a link.

**Why the agenda is `noticed` and not `held_on`.** docs.house.gov states what
was scheduled. Where the agenda and the cover agree the bill side confirms 18
of 18; where the agenda alone states a bill it confirms **1 of 18**,
**contradicts 1** (`118-hr-2997`, noticed for 2023-05-23 and recorded as heard
2023-06-22) and is silent on 16. A sealed two-value `relation` keeps the
distinction the numbers make; publishing both as `held_on` would publish a
calendar as a record of events, and 16 of those 18 are unverifiable rather than
wrong, so dropping them would lose evidence a consumer can check.

**Why the identity check is per row.** The route only works because
docs.house.gov's `EventID` is Congress.gov's `eventId` — 9 of 9 sampled, and
all 9 passed a *committee-and-date* check rather than a status check. Neither
publisher documents the equality; Congress.gov's endpoint documentation never
mentions docs.house.gov and its OpenAPI spec spells the field `eventid` while
the wire spells it `eventId`. A measured regularity is not a contract, so
`check_meeting_identity` refuses unless this meeting's `<calendar-date>` equals
this hearing's MODS `heldDate` and one of its committees' parent codes equals
one of the MODS's `congCommittee` authority ids. A one-time assumption would
notice nothing when the equality stops holding.

**Why a type-less `<legis-num>` is refused.** `BILLS-118226ih.pdf` beside
`<legis-num>226</legis-num>` states no bill type. The long-standing community
scraper (`unitedstates/congress`) defaults it to `hr`; a bare `226` at a House
hearing can be a Senate measure, and a silently wrong linkage is worse than a
refusal. The rule falls through to the `<description>`, which usually spells
the designator in full under the **same** `bill_number` citation rule a
committee print is read with — taken, not respelled, so one designator reduces
to one key whichever document it was read in. **36 of 46** retained `BR`
documents resolve; the 10 that do not are `BILLS-118Xih.pdf` discussion drafts
with no number at all, and each carries its refusal reason rather than
vanishing.

**Why the vocabulary names sources it does not implement.** `link_source` is
published and is part of the identity, so a rename rewrites rows already out.
All five measured sources are in the sealed tuple from the start —
`daily_digest_entry`, `congress_related_items` and `front_matter_designator`
carry their measured figures and `implemented=False` — so taking one later is
an addition. `link_rule_version` is *derived* over every rule's name, version,
publisher, relation and reader, the way `CITATION_RULE_SET_VERSION` is, so
changing what a rule reads moves it even when someone forgets to move that
rule's own version; it is blind to a change inside a reader, which is what the
per-rule `version` is for.

**What this does not establish.** Every number above is the 118th Congress.
Recall is unmeasured: 2 of 20 sampled House hearings carry a `COVER` bill at
all and hearing type was never classified, so that is a floor over all hearings
and not a rate over legislative ones. **0 of 3 sampled Senate hearings state a
bill in any context**, so a missing Senate row and a correct silence on an
oversight hearing are indistinguishable, and nothing in the table says which.
Three is not a rule; the per-chamber census is the open measurement, and
`daily_digest_entry` — both chambers, back to 1994 — is the route that would
close it.

## What a host restates is a rule this package failed to own

Adopted 2026-09-20 from the first hosted run of the PDF-family rollups
(spicy-regs `adopt-spicy-docs-0.23.0`; receipt
`rollups-pdf-families-2026-09-20/`), with [GovInfo bodies](sources/govinfo-bodies.md)
and [table contracts](tables.md) updated; the B4 row of
[closing the gaps](research/closing-the-gaps-2026-09-19.md).

The run built the four tables of the `print-citations` rollup and published
them, and two of the three follow-ups it exposed are the same defect seen from
two sides: **a rule this package had measured but not published, which the host
therefore had to restate or invent.** A restated rule is a rule that will
drift, and the drift is silent — both copies keep passing their own tests.

**The activity-report title rule lives in the package now.** Nothing in a CRPT
package's id, `docClass` or MODS says it is an end-of-Congress committee
activity report; only its title does. The rule was written in
`tools/analysis/pdf_family_rollup.py`, the wheel ships `src/` and not `tools/`,
and the host's own docstring names the consequence: "the one selection rule in
this module that is a copy rather than an import". It is now
`sources/govinfo/activity_reports.py`, beside the collection walk whose rows it
selects, and the analysis tool imports it — the arrangement
`interpretation/citations.py` already has with the citation rules, for the same
reason: a rule corrected in one place must not stay wrong in the other.

What moved with it is what makes it checkable: the pattern, **the bare-word
alternative it rejects**, and a version digested over both. Keeping the
rejected rule beside the chosen one is the point — the precision this rule was
selected on is a ratio, and a ratio whose denominator lives only in prose
cannot be re-derived. Re-derived where it now lives, request-free from the CRPT
index page the rollup retained (`activity-report-title-rule-2026-09-20/`): 71
packages walked, 20 titles carrying `activit`, **15 the phrase rule matches**.
Three of the five rejects are the false positives it exists to reject; **two
are real activity reports it misses**, both naming a Congress and no committee.
The rule is not widened to reach them, because dropping the committee
requirement is exactly what readmits the other three and this window does not
measure what that would cost. 15 is published as a floor with the two named,
and widening it means a window that separates the classes and a new
`ACTIVITY_REPORT_RULE_VERSION`.

**A per-family body preference belongs beside the sealed one, not in the
host.** `BODY_PREFERENCE` is right and does not move: "Why PDF is last" was
measured on committee reports, whose `htm` keeps account rows joined and words
whole, and it still decides every collection whose contract states no page. But
`house_activity_reports` and `budget_volumes` publish four columns that state a
page — `pages_read`, `stated_page_count`, `pages_capped` and every citation
row's `evidence_page` — and **no GovInfo `htm` body of any collection carries a
page boundary**. `extraction/body_text.py` already said so structurally, in
that `BodyText.pages` is `None` for every rendition but `pdf`; the run measured
what ignoring it costs. Under the sealed order, **10 of 41** activity reports
refused outright on HTML nesting depth and the 31 that were read published **0
page attributions across 29,308 citation rows**. Under PDF-first: 41 reports
and 23 budget volumes, zero refusals, an `evidence_page` on all 49,792 rows.

So `PRINT_BODY_PREFERENCE` sits beside `BODY_PREFERENCE` and
`GRANULE_BODY_PREFERENCE`, **derived from the sealed order** rather than
spelled out, so a rendition added to one joins the other and the two cannot
disagree about what the renditions are. It is a permutation with PDF first, not
`("pdf",)`: the whole sealed order follows, so a package offering no PDF — four
of the thirteen measured BUDGET parts state none at the package root — still
yields a body instead of being refused for want of one. A test holds both
properties, including that the sealed order itself did not move, because that
is exactly what a second named preference must not cost.

**The rule this leaves.** A host restating something to build a table is a
finding about this package, not about the host: the thing restated is either a
published contract that should have been importable, or a rule that was never
measured. Either way it comes back here. The third follow-up from the same run
— seventeen BUDGET package ids refused by a sealed vocabulary measured on a
narrower window — is the second kind, and is recorded in the grammar's own
entry above.
## The Record's executive-communication entries land in `house_communications`, and the official/agency split does not publish

**2026-09-20.** Congress.gov decomposes a House executive communication only
from the 114th Congress; the Congressional Record printed the same sentence for
the ten Congresses before it, in its House `EXECUTIVE COMMUNICATIONS, ETC.`
section, as a titled CREC granule with HTML back to 1994. The
[backfill research](research/executive-communications-backfill-2026-09-20.md)
measured that the publisher's `abstract` **equals** that printed entry under
named normalizations, and that every other typed field is a span of the same
sentence. Two decisions follow, and a later change must preserve both reasons.

### One contract, not a sibling table

The reconstructed rows land in `house_communications` with provenance columns
(`source_route`, `record_package_id`, `record_granule_id`, `record_entry_text`,
`reconstruction_rule_version`) rather than in a `record_communications` sibling.
The grain is identical — one row per House executive communication — and
`(congress, communication_type, number)` is the publisher's own address on both
sides of 2015. A sibling would split one fact across two contracts and force
every consumer to union them; a consumer that wants the publisher's own
decomposition alone filters `source_route = 'congress-gov-detail'` instead.

Three rules hold across the two eras, each of which is a bug if missed: a
reconstructed row's `url` is NULL (the detail route 404s for every pre-114th
communication, measured); the merge prefers `source_route` over `update_date`,
so a `congress-gov-detail` row wins whatever the version column says and a
later publisher backfill overwrites the reconstruction rather than the reverse;
and an unresolved field is NULL beside the retained sentence, never a guess.

### The split columns stay NULL, because the measurement said so

`submitting_official` and `submitting_agency` are the one field pair a
punctuation rule cannot produce: the boundary sits after two comma groups in
114th EC 4329 and after one in EC 4350. A candidate rule — the agency begins at
the first comma group whose head noun is an organization word — reproduced the
publisher's split on both ground truths, which is exactly the agreement that
means nothing on its own.

It was therefore scored against the publisher on the overlap era, where both
records exist ([the score](research/record-communications-overlap-2026-09-20.md),
296 requests under caps declared first). **The pair is one boundary decision,
so it is scored on one declared denominator — the rows where the rule answered
and the publisher decomposed the from-clause at all — and on that denominator
it fails on both sides: agency 88.4%, official 85.3% on 129 held-out rows,
against a 90% threshold declared before the run.** Neither publishes.

The denominator had to be declared because it decides the story. Scored per
side instead — each field only over the rows the publisher states *that* side
on — the same run reads agency 94.2% and official 90.9% over 121 rows, and the
pair looks like one passing field and one failing one. The whole difference is
eight rows from one granule, `118-ec-4522`..`4530` of
`CREC-2024-06-12-pt1-PgH3973`, where Congress.gov put the entire printed
from-clause in `submittingAgency` and stated no official at all. They can only
ever count against the agency. Under either view at least one side misses 90%,
so the decision does not turn on the choice; its *reason* does, and the reason
is that the pair is one decision and the declared view fails on both sides.

The rule stays in `sources/congress/record_communications.py` — it is a
capability with a measured limit, not a dead end — and the whole from-clause
survives on every row inside `record_entry_text`, where it matches the
publisher's two fields concatenated on 97.8% of held-out rows.

**What would reverse it**: `submitting_split` — both sides, on the declared
denominator — at 90% or better on a fresh held-out draw under a newly declared
cap, from a resolver against a published organization roster, and not from
fitting the four sub-agency units this run's disagreements happened to name.

### The referral's names publish; its identity does not

`referral_committee_name` and `committees_json` carry the Record's own words on
a reconstructed row. They are a fact the print states — the committee's name on
the day — and the referral tail is read correctly: `referral_count` agrees with
the publisher on 95.1% of held-out rows. Dropping them would throw away the
only referral information the pre-114th era has.

They are **not** the publisher's spelling of the same committee, and the column
prose says so: 71.5% agreement under a normalized comparison, because the 116th
Record prints *Oversight and Reform* where Congress.gov states *Oversight and
Government Reform Committee*. That drift is why identity belongs to
`referral_system_code` and why nothing joins on the name.

`referral_system_code` is NULL on every reconstructed row, because **the
resolver from a printed committee name to a `committees.system_code` does not
exist yet**. It is the next piece of work this table needs, and the name drift
this run measured is the thing it has to absorb: a resolver matching on the
current spelling alone would miss a renamed committee, which is exactly the
116th case.

### What the measurement was worth

It can fail, and it did. The first score was **58.4% on `abstract`**, against
two ground-truth rows that had agreed perfectly. Three GPO print artifacts
explained nearly all of it — the hyphenated line wrap the PDF path already
handles, a fourth publisher normalization (`Pub. L.`), and a print dash the
Record spells with four hyphens — and a fourth finding came from the sections
rather than from any field comparison: the 117th and 118th parsed to **zero**
entries, because the Record numbers an entry `EC-1205.` from 2021 and `1205.`
before it. A field-by-field score cannot see that; a section yielding no
entries yields nothing to disagree about. The rules revised against the
114th-115th disagreements are reported as an in-sample upper bound, separately
from the 116th-118th rows no field rule was changed against.

## The CBO estimate index is a new table; its letter hangs off the report, joined on the bill

CBO's own site refuses every document path and Zyte's error names the ban, so
the estimate family had no route at all until
[the routes measurement](research/cbo-cost-estimate-routes-2026-09-20.md)
found two that never touch `cbo.gov`. Building them raised three choices worth
the record, and all three were settled by looking rather than by arguing.
Numbers are [the build measurement](research/cbo-cost-estimates-build-2026-09-20.md)'s,
re-derived offline from retained bytes through the product code.

**Step zero: the family published none of it, so the index is a new table.**
The owner's rule is that data an index already gives is never recreated, so
the first question was whether `congress_bills` already carried the estimates
— in which case only the text side and the link were left to build, and a
partial answer would have meant appending columns rather than a new contract.
It carried nothing: `parse_bill_status` read neither `<cboCostEstimates>` nor
`<committeeReports>`, and `docs/tables.md` had no occurrence of `cbo`. So
`cbo_cost_estimates` is a new contract — filled in the bill family's same one
pass, off the same document, through the same reader rather than a second XML
walk.

**The identity folds on `(bill_id, publication_id)`, and the fold keeps what
it folds.** The publisher states one publication twice on 37 of 1,468 measured
items, and **nine of those 37 disagree** — every one in `title` alone, CBO
re-spelling the measure. Two items naming one publication are one estimate, so
they fold; but a fold that dropped the second spelling would lose the
publisher's own correction. `restatements_json` carries every differing later
item with only its differing fields, and `stated_count` says how many there
were. `[]` on the other 1,459 rows.

**The letter's span lands on `committee_reports`, and the relation to the
index is a join on the bill.** Two alternatives were considered and both are
refused on evidence:

- *A `document_citations` row under a new sealed `cite_kind`.* That table's
  grain is one occurrence **of a cited key**, and its identity includes
  `target_key`. Across all 17 retained CRPT bodies there is exactly **one**
  `cbo.gov` locator — a footnote in `CRPT-118hrpt930` to an unrelated 2018 CBO
  study — **no** `/publication/{id}` page at all, and none inside any located
  letter. The print states no key to carry, so the row would carry an invented
  one. The letter is also one span per document, not one occurrence per key,
  which is exactly the aggregate-versus-occurrence distinction that table's
  design defends.
- *`letter_*` columns on `cbo_cost_estimates`.* That row is shaped from one
  BILLSTATUS document in one pass, and the report is a different package — the
  same reason `congress_bills.statutes_at_large_cite` is a preserved NULL. And
  it could not be filled correctly even with the report in hand: **61 of the
  1,368 scored bills of the 118th carry more than one estimate, and 28 of those
  also carry a report**, so attributing one reprinted letter to one of several
  estimates would be a guess on 28 bills.

So the letter is a property of the report, appended to the package-keyed row,
and the relation is `cbo_cost_estimates.bill_id` joined to
`committee_reports.recital_bill_id`. Every identity stays where it was:
`(bill_id, publication_id)`, `(package_id,)`, and `document_citations`'s
sealed `cite_kind` vocabulary untouched.

**`recital_bill_id` sits beside `bill_id` rather than replacing it.** The
cover's `[To accompany H.R. 801]` is the *print's* answer to the report-to-bill
join, with the Congress taken from the package identity because the cover
states none. `bill_id` remains whatever index record the caller read. Two
columns for one fact, on purpose and in this repository's own house style: what
a print says and what an index says are different claims, and the two agreeing
is the check — the same reason `document_citations.stated_by_index` exists.

**The bill carries the empty observation.** Append
`congress_bills.cbo_cost_estimates_outcome`, leaving every existing column in
place. NULL means unread; `populated` means estimate items were read;
`requested-empty:absent` and `requested-empty:present-and-empty` distinguish a
missing element from an empty one; `requested-empty:unexpected-shape:<shape>`
names an unsupported structure without copying source text. This is the plain
home because `cbo_cost_estimates` has one row per estimate and no row on which
to record an empty answer. A populated block can still yield an unkeyable item:
its refusal names `cbo_publication_url`, host and path shape, never the URL,
and free-text reasons are scrubbed before truncation. Zero report citations
means this BILLSTATUS names no report, not that no CRPT package exists.

The original build's empty-element counter could not fail: it returned zero
whenever any bill had estimates. The corrected offline measurement uses these
reader outcomes and a mixed-shape synthetic zip that detects that defect.
The retained 16,213 bills yield 1,368 populated blocks, 14,845 absent, zero
present-and-empty and zero unexpected. No count establishes an unscored bill.

**The gate is the cover recital, and a heading is never one.** House Rule XIII
cl. 3(a)(1)(B) makes the cover carry the recital when the estimate is in the
report, identically in both chambers. The corpus breaks every looser gate:
three retained reports print a CBO heading over a section that then says the
estimate was **not** received; one prints the estimate under a heading the
routes measurement's five patterns missed; and `CRPT-118srpt99` states
`Director, Congressional Budget Office.` in a **witness list** with a
`Washington, DC, March 1, 2023.` dateline on the committee's *own* transmittal.
The heading vocabulary is therefore a floor used only to *locate* a span the
recital already declared, and a declared letter it misses publishes a NULL span
— visible as a shortfall, never as an absence.

**A missing estimate is requested-empty with the publisher's reason.** Four of
the seventeen bodies say why in their own words, and the rule returns that
paragraph whole with its span rather than a NULL. The reason is **not** gated
on a heading, because one of the four sits under a heading no pattern matched.

**Support PDF with a bounded heading rule.** The routes plan prefers PDF.
The first implementation located zero letters in the four retained PDFs after
`rendition_text` removed indentation. CRPT-118hrpt53, -118hrpt276, -118hrpt930
and -118srpt289 all print whole uppercase section headings. Accept that form
alongside the existing indented HTM blocks, reject dot leaders, and still
require an exact heading-vocabulary match and the cover recital. The two newer
PDF attributions also wrap between `Congressional` and `Budget Office`.
This locates all four letters; all 17 HTM findings, including exact spans and
digests, stay unchanged except for the rule version. The caller can select the
preferred PDF rendition; no HTM-only deviation remains. Raster figures remain
outside this capability.

**Version every input that controls the letter rule.** The digest now includes
reason guards, numbering, dot leaders, whitespace and paragraph boundaries,
regex flags, heading thresholds, trailing punctuation and the control-flow
revision, as well as the named patterns and their rejects. Tests pin
`cf790f0f814a` literally and mutate each input. Paragraphs are scanned once,
heading blocks are reused, and letter digests use `schemas.tables.digest`.

**No letter date is read, and that is a measurement.** Zero of the seventeen
bodies states a CBO letterhead dateline. Writing a pattern against a form
nothing retained has shown is the guess this repository refuses elsewhere, and
it is unnecessary: the estimate's date is CBO's own `pubDate`, published on
`cbo_cost_estimates.pub_date`. Re-deriving it from prose would recreate what
the index states. One retained body whose reprint carries the letterhead
reverses this.

**What the capability does not claim.** No cost figure is published by either
table: the summary card is a raster in every rendition and no extraction was
attempted over it. The ~35% of scored bills with no committee report — and
every current-year estimate — have no text route at all; their index rows
still carry the bill, the stage, the date and the locator, and the figures are
recorded as absent. Under the retain-value rule that is a capability with a
measured limit, not a gap to hide.

## The Unified Agenda's citation paths have one reading, here

Adopted 2026-09-23 as B11 of the
[consolidation path](research/consolidation-path-2026-09-22.md); the rules
live in `sources/unified_agenda/projection.py`, documented in the
[Unified Agenda guide](sources/unified-agenda.md#project-citations-and-timetables).

The raw reader left whitespace, the 2004 byte repair and `ADDITIONAL_INFO`
continuations to its receivers. SpicyRegs and RefSpec then read the same three
paths two ways: SpicyRegs stripped and RefSpec collapsed whitespace, and only
RefSpec read continued authorities. It is the case
[a host restating a rule](#what-a-host-restates-is-a-rule-this-package-failed-to-own)
describes. RefSpec's rules move here because, over all 60 retained editions,
they lose nothing that SpicyRegs' `strip()` kept. The receipt is
`corpora/supply-2026-09-02/receipts/unified-agenda-projection-2026-09-23/`.

The move is not verbatim. These changes alter no projected value in the 60
editions:

- An absent or blank timetable action or date is `None`; RefSpec wrote `""`.
- Only `CFR` and `LEGAL_AUTHORITY` items are read inside their lists; RefSpec
  read every child.
- Every list is read, where RefSpec read only the first.
- RefSpec refused an edition whose `0x19` presence disagreed with its roster.
  Here a roster edition without the byte reads normally, and one with more
  than a single byte is refused.
- The search for another field's label stops at the paragraph mark or blank
  line, and a label's words are capped at 64 letters and spaces. RefSpec's
  search ran to the end of the field and grew with the cube of a whitespace
  run: 5 s at 2,000 spaces, where a record may hold 4 MiB. All 65,128
  `ADDITIONAL_INFO` fields give the same result either way.

- **Whitespace.** The only differences are spacing, in 1,562 CFR lists, 1,959
  authority lists and 1,373 timetables. Collapsing also respells a lone
  non-ASCII space, which a check for whitespace runs misses: edition 202510
  changes 38 CFR and 24 authority cells, not 37 and 23.
- **Repeated lists.** Every list is read, which cannot differ from reading the
  first: the XSD allows one of each and no edition repeats one.
- **The 2004 byte.** The repair covers the one byte measured in each of the
  two editions. A second one in those editions is refused, the raw reader and
  acquisition still refuse the byte, and so does any other edition. An
  unmeasured defect stays a refusal and does not become a guessed character.
- **Continued authorities.** 98 records carry them, and RefSpec's grammar reads
  1,310 citations from them. They are returned beside the list, not appended to
  it, because whether a host publishes them is the host's choice.

## U.S. Code section join keys are lower-cased on both sides

Blind ruling 2026-09-23, recorded as decision 30 in spicy-regs'
`docs/research/fork-delivery-decisions-2026-09-22.md`. The key is built by
`schemas.tables.usc_section_key` and is documented in [Tables](tables.md) and
[the classification tables](sources/uscode-classification.md#where-the-rows-land).
The receipt is `corpora/supply-2026-09-02/receipts/usc-section-key-2026-09-23/`
(`measure.py`, `annual_case.py`, `cut_fixture.py` and their output).

**The citation grammar's `usc_section` key stays as it is**: it lower-cases the
section letters (`31-5318a`), and its rule version does not move.
`law_code_sections` and `table3_records` instead each append a derived
`usc_section_key` beside the printed `usc_section`. Both identities
(`(congress, session, seq)` and `(act_key, seq)`) and `usc_section` are
unchanged. The key is appended last because spicy-regs' `merge_table` selects
a column that a prior Parquet file lacks as NULL. Rows published before the
column keep NULL until their scope is captured again.

**Case carries no identity in the Code, and the publishers disagree about it.**
The retained 119th-Congress `law_code_sections` has 3,632 rows. Of these, 814
print a lettered section and 142 print it upper-case: 64 distinct pairs, 51 of
them in Title 26 (`25A`, `45Q`, `199A`, `1400Z-1`). A join on the printed
spelling misses all 142. None of the following sources has a pair of sections
that differ only by case or dash:

- that table;
- the OLRC release point `xml_uscAll@119-102`, read as printed: 59,362
  sections, 470 of them printed with a capital;
- the 31 annual editions from 1994 to 2024, re-read as printed: 1,572,225
  year, title and section rows, 8,978 of them printed with a capital.

RefSpec's oracle stores lettered sections lower-cased and its
`normalize_section` folds on lookup. The oracle's own zero cannot show such a
pair, because it lower-cases at extraction, so the zeros above come from
re-reading the publishers' files before any fold. Table III itself prints four
sections both ways (28 U.S.C. 599A and 599a, 530A and 530a; 42 U.S.C. 300V and
300v; 10 U.S.C. 2380B and 2380b) in 307,473 bulk records, so without the fold
Table III would not join to itself.

**The dash fold earns its place from the Code's side.** No retained
classification row or Table III record prints a Unicode dash, but the release
point spells all 5,311 of its compound sections with an en dash and none with
a hyphen. `usc_section_key` is `normalize_section` exactly: it trims,
lower-cases, and turns each of the same nine dash spellings into an ASCII
hyphen. It does not strip subsection detail or zero pads, because neither
table prints either. Table III's note and chapter spellings (`1 nt`,
`ch. 12A`) stay in the key, lower-cased.

**A derived column instead of a fold at join time.** Every consumer was left
to fold at join time, and that is how the miss went unnoticed. A printed column
beside a derived key is these tables' existing pattern: `stated_key` sits beside
`act_key`, and `publisher_law_type` beside `law_type`.

**The helper is in the `schemas` leaf, not in `interpretation/`.** `schemas`
may not import `interpretation` (see [Tables](tables.md)), and
`interpretation.citations` already imports `schemas.tables`, so a helper there
would have made an import cycle. **Both sides now fold through it (done
with B4).** `document_citations`' `usc_section` reads through B4's grammar,
whose `citation_grammar._usc_section` folds each section through
`usc_section_key` and whose dash fold reads `DASH_SPELLINGS`, so the key a
citation publishes (`26-199a`, `26-1400z-1`) and the tables' `usc_section_key`
are folded by one function and one list; the grammar kept no list of its own.
Over the parsing survey's 60,000 Federal Register texts the change moved no
key (77,545 keys read before and after). The grammar's sort helper, which
shared the name, is now `_usc_section_order`, because it returns an ordering
tuple and not this key; RefSpec's test that calls it by name follows the
rename at its repin. Rule 001 citation rows published before B4 keep the
printed case (`26-199A`), and fold through `usc_section_key` to join.

**Repinning spicy-regs moves its data dictionary.** Both tables gain a
column, so the repin regenerates `data_dictionary/catalog.json` and its
`.sha256`, `src/spicy_regs/table_metadata.json`, and the
`docs/tables/law_code_sections.md` and `docs/tables/table3_records.md` pages
(`uv run spicy-regs-dict generate`).

## Table III absence is read from the chain of pages, never from a page's bytes

**2026-09-24.** spicy-regs' Table III walk had stopped at the same three acts
on every run since 2026-09-22. OLRC answers an act without a page with HTTP
200, the first 16,134 or 16,209 bytes of its site template, and a dropped
connection. This package retried that answer as a transport failure (four
requests, about 70 seconds an act), and three in a row stopped the walk. A
stopgap there typed those bytes as a definite absence: the site menu is present
and the page's content is not. Measured against every retained answer, that
test cannot separate the two cases. On served pages the menu opens at about
2.3 KB and the content at about 27 KB. All 44 template answers are byte-exact
prefixes of served pages, session id aside, so a served page dropped anywhere
in that window reads the same. The receipt is
`corpora/fork-execution-2026-09-21/table3-walk-2026-09-24/spicy-docs/`.

A dropped answer is a failed request, and the publisher states absence through
the links between its pages. Each page names its prior and next act, and on
2026-09-24 the 119th-Congress chain from 119-1 was the same 40 acts that
`fulldump@119-73.xml` lists. Repetition does not establish absence either:
RefSpec's 2026-08-02 build received the template for 119-21 on four attempts.
The bulk file RefSpec retained on 2026-08-06, already at 119-73, lists that act.

What a later change must preserve:

- **No refusal type means "the table lacks this act".** `iter_table3_chain`
  follows `Table3Page.next_act` from a starting act. The acts a link passes
  over are the absent ones. A named act that fails ends the walk as the
  ordinary failure it is.
- **A drop stays a retried transport failure on every route.** The Table III
  act route alone passes `retain_dropped_body` to the capture, which keeps the
  last attempt's bytes as `response-incomplete` evidence on the escaping error,
  whatever `httpx.RequestError` cut the body short. Retries and every other
  route are unchanged. Only a keyless acquirer may ask for it, because those
  bytes never reach the credential-echo check. It reads chunks as they arrive,
  because HTTPX's chunker drops what it buffered when the stream fails, and a
  16 KB answer fits inside one 64 KiB chunk.
- **The walk keeps spicy-regs' chain rules.** It walks one Congress. It stops
  at a page whose next act is not a public law, is in another Congress, does
  not follow, is outside the caller's bound, or is after the release point the
  page states itself current through. The last page, 119-73 at 119-73, names
  119-74, which answered only the template on 2026-09-24. Without that stop,
  every walk would end in that act's retried failure. These are the rules
  and the order of spicy-regs' `build_laws._table3_rows` at `b2fd9a0`. To move
  that walk here, spicy-regs spends its per-run cap and checks its deadline in
  the `acquire` wrapper, once per request, and raises from it to stop. A page's
  stop rules run inside the following `next()`, so a cap spent before each
  `next()` would spend one at every natural end. It publishes rows only for
  acts it does not already hold, since the start act is yielded like any
  other. It reads the end reason from `StopIteration.value`. A start with no
  page is a failure. The previous Congress's last page should name a seed.
  That is inferred from 119-1 naming 118-273 as its prior act, not yet
  observed. The index page `congress{N}th.htm` is not read.

**Amended 2026-09-26: absence is read from the bulk file, and the walker is
gone.** spicy-regs now derives `table3_records` from Table III's bulk file, one
request a run, and nothing calls `iter_table3_chain`, so it is removed with its
tests and chain fixtures. The bulk file lists every act the table holds, so it
states absence where a walk could only infer it, and it holds what a forward
walk skipped: 119-30 and 119-53, whose pages exist and state the file's record
(receipt `corpora/fork-execution-2026-09-21/table3-bulk-2026-09-26/`). The
seed is observed now: 118-273 names 119-1. The first two rules above still
hold: no refusal type means an act is absent, and a drop stays a retried
transport failure on the page route, which `parse_table3_page` and
`acquire_table3_act` keep serving.

## A multi-part committee report is one row per part, keyed on the publisher's granule id

Decision 29, delegated 2026-09-23 and confirmed by the owner on 2026-09-24.
`committee_reports` moves from `(package_id)`
to `(package_id, part_id)` and `report_sections` from `(package_id, seq)` to
`(package_id, part_id, seq)`; the host's acquisition checkpoint stays keyed by
package, because one read yields every part and a package's part rows are
replaced as a set. `REPORT_SECTION_READER_VERSION` moves to
`report-headings-002` so every report is re-read into part rows. Behavior and
measurements: [Table contracts](tables.md#a-multi-part-committee-report-is-one-row-per-part)
and [multi-part reports](sources/govinfo-bodies.md#multi-part-committee-reports).

**The single-part spelling is the package id, not a blank.** `TableContract.key`
refuses a NULL identity part, so a report in one part needs a value. The record
already states one: its root names the granule's `accessId`, and it is the
package id (`CRPT-119hrpt1`). `CRPT-119hrpt494` spells its real, numbered Part 1
the same way. Taking the publisher's id means `part_id` is always a value some
record states and always the stem of `requested_url`; the `treaties.suffix`
blank would have been neither. But `part_id` and `part_number` do not say how
many parts a package has. On the package-id spelling `part_number` separates Part 1 of two
(`CRPT-119hrpt494`, 1) from a report in one part (NULL), but the eight packages
whose one part is spelled `-pt1` are `(CRPT-119hrpt811-pt1, 1)`, the same shape
as `CRPT-119hrpt455`'s Part 1. A reader tells Part 1 of two from a lone part by
counting the package's rows.

**A host adopts it in the release that vendors it.** `shape_report_section`
now requires `part_id` and `shape_committee_report` refuses a body that names
no part, so a host that vendors this without adopting it breaks, and a host
that adopts only the shapers loses rows: its merge keeps only whole
identities, and every prior row reads `part_id` as NULL. In the same release a
host passes `part_id`, backfills prior rows with
`COALESCE(part_id, package_id)`, and merges `committee_reports` with
`replace_parents` by package, as it already merges `report_sections`
([Table contracts](tables.md#a-multi-part-committee-report-is-one-row-per-part)).
That is why this change waited for the owner's confirmation of decision 29
and ships in 0.32.0, whose consumer must adopt it in the same release it vendors.

**Why not read two parts as one package.** Joining the parts' text under the
package id would publish two bodies, two digests and two CBO findings as one,
and `CRPT-119hrpt494`'s Part 2 is a supplemental report correcting Part 1's
committee votes, not a continuation of it.

## A table contract declares its member-key spelling, and the Regulations.gov tables key on the publisher's id

2026-09-25, for DocSpec decision 0007 (admitting a generation by reference),
whose owner ruling R6 left key spellings to this package. DocSpec puts each
table's member key in every admitted state's identity and in every Engine id,
so the spelling belongs to the contract that owns the identity, not to its
reader. `TableContract.key_spelling` names an entry of
`schemas.tables.KEY_SPELLINGS`; each entry is a `name/version` with a Python
reference, and `spelled_key(row)` applies it. Every contract with a one-column
identity declares `value/1`, the value itself, and a test holds every
composite to none. Behavior and measurements:
[Table contracts](tables.md#the-regulationsgov-tables-are-keyed-on-the-publishers-id).

**What a later change must preserve.** An entry's output never changes, even
to fix it: a different spelling is a new `name/version`, and adopting it is an
explicit re-key downstream. A composite identity declares no spelling until it
needs one; that one spells the ordered canonical JSON array of its components
under its own name, and says so in its docstring.

**Why the publisher's id alone.** DocSpec decision 0004 found a cross-filed
document to be one document under one `documentId`, not an identity question,
and that finding is what the key rests on. A composite such as `(agency_code,
document_id)` would split what the publisher states is one record. The published
files agree, but for `dockets` and `documents` they cannot disagree: the host's
merge keeps one row per id. Only the `comments` export, which has no such step,
could have shown a duplicate, and showed none.

**What `modify_date` versions.** It is the publisher's instant. The host fills
`text_content`, `text_extraction_status` and `pdf_extraction_results_json`
without changing it (spicy-regs `transforms/regulations_correction.py`,
`ENRICHMENT_COLUMNS`; `sources/derived_text.py`, `derived_fill`), so an admitted
row can change while its version does not. For DocSpec that is ruling R5's
churn, and a declared projection without those columns is the candidate.

**What adopting it costs spicy-regs.** Read at spicy-regs `5df0722`; another
session owns that repository, and nothing there is changed here.
`TABLE_CONTRACTS` drives spicy-regs' Arrow schemas, merges, data dictionary and
MCP views, as this package's `schemas/__init__.py` states. Adopting this
release fails its `test_every_hosted_table_is_registered_everywhere`: the
contract count moves, and the three new names are neither hosted nor unhosted.

- `UNHOSTED_CONTRACTS` cannot take them, because that test requires an unhosted
  contract to be absent from `data_dictionary.TABLES`, which already lists
  `dockets`, `documents` and `comments` first.
- Hosting them in `CONTRACT_TABLES` would list them twice in `TABLES`, which
  appends every hosted table but `congress_bills`. It would also replace
  spicy-regs' own column prose for them in `descriptions.yaml` with these
  contracts' sentences.

The change spicy-regs needs, in the release that vendors this one: a third
class beside hosted and unhosted, the contracts it publishes through its own
`RECORD_TYPES`; the partition assertion covering all three classes; the new
contract count; and a test that each of its record types' schemas and dedup
keys equal the contract's columns and identity, so the two declarations
cannot drift. Both hold today. Its `TABLES`, `CONTRACT_TABLES` and prose stay
as they are.

## A bill section is keyed on its position, and a dateless enrolled printing is paired by its stage

2026-09-26, from spicy-regs' qualification of its published bill family
(receipt `fork-execution-2026-09-21/drift-qualification-2026-09-26/bills-citations/`
under `~/Work/corpora`). Both faults were this package's, not the host's.

**`bill_sections` was keyed on a path that repeats inside a printing.** Its
identity was `(bill_id, version_code, source, match_path, body_index)`, and
`match_path` is the division-free cross-version key. Real printings break it:

- 119 HR 5334 enrolled: Division A's and Division B's `Sec. 1` both path
  `sec. 1` (seqs 3 and 80).
- 119 HR 9022 reported: two paragraphs under one appropriations heading share
  its path and the same empty division (seqs 68 and 69), so `division_key`
  would not separate them either.

The builder emitted every row, and the host's merge kept one per identity: it
published 83 of 84 and 150 of 151 sections without a word, and one diff item
named the dropped section. The identity is now `(bill_id, version_code,
source, seq)`, and `section_classifications` gains `seq` and keys on
`(bill_id, version_code, source, seq, label)`. `match_path` stays the
cross-version join key.

Measured on the published generation `5990abbb…` (receipt
`receipts/bill-section-identity-2026-09-26/`):

- The new key is unique over all 20,912 published rows in 1,802 printings, and
  no `seq` is NULL. A merge under it keeps all 20,912 rows and changes none.
- `seq` runs from 0 without a gap in every printing but the two above.
- `seq` is a function of the bytes: 69 printings whose native bodies are
  retained re-parse identically, and every one of their 916 published rows
  names the same element, path, body index and body digest at its `seq`. A
  different engine could renumber; the host replaces a re-parsed printing's
  sections whole, so a renumbering replaces rather than duplicates.
- `element_id` is unique within every printing and never NULL, so
  `section_diff_items` resolves its sides by element id unchanged.

**The pairing sorted an empty date first.** BILLSTATUS states no date for an
enrolled printing, so `_sorted_versions` put it before the introduced text:
13 of 401 published comparisons ran enrolled -> introduced, and the last
printing -> enrolled comparison was never made. The order now lives in
`sources.congress.bill_versions.printing_order` and `consecutive_pairs`
([Printing order](sources/congress-bill-versions.md#printing-order)), and
`CONSECUTIVE_PAIR_RULE` moves from `consecutive_by_date` to
`consecutive_by_date_then_stage` so each row names the rule that paired it.

**A repeated identity is refused.** The family's admission step files a
`FamilyRefusal` for a row whose identity it already admitted in the pass,
rather than emitting both for a merge to collapse.

**What adopting it costs spicy-regs.** Re-keying the published `bill_sections`
is a no-op, as measured. `section_classifications` rows published before `seq`
would NULL-fill that key column and be dropped by the merge; the published
table is empty (0 rows at `5990abbb…`). Comparisons published under the old
rule stay until a rebuild retires them: the host should import
`printing_order`/`consecutive_pairs` in place of its own order and retire any
published pair they do not establish.

## A numbered reprint is its own printing

2026-09-26, from spicy-regs' live bill-family generation `d380cdc0…` (receipt
`fork-execution-2026-09-21/repeated-printings-2026-09-26/` under
`~/Work/corpora`).

**Two printings shared one identity.** 119 HR 6644 went back and forth between
the chambers: the Senate engrossed an amendment on 2026-03-12
(`BILLS-119hr6644eas`) and another on 2026-06-22 (`…eas2`). Congress.gov types
both "Engrossed Amendment Senate", so both took the `version_code`
`engrossed-amendment-senate`, and `(bill_id, version_code, source)` could not
tell them apart. The family refused the second printing's version row and its
first 198 sections as repeats of the first's 198, but admitted its last 78
sections under the same key: the published printing mixed two documents, and
each comparison into or out of the second named 198 sections never published.

**The identity.** `sources.congress.bill_versions.printing_version_code` gives a
numbered reprint its own package suffix as its code (`eas2`), and leaves every
other printing its stage slug ([Printing identity](sources/congress-bill-versions.md#printing-identity)).
Measured:

- 26 of 89,024 bills in the retained BILLSTATUS of the 110th–113th and
  118th–119th Congresses list one stage twice. The stage is most often the
  Senate engrossed amendment (14), then the House's (4) and the Senate
  referral (4). The rule separates 16 of them. In the other 13 the listing
  states no package on either printing, or the same package twice; all 13
  are in the 110th–113th.
- On the published generation, 2 of 47,905 `bill_versions` rows re-key
  (119 HR 6644's `eas2` and 118 HR 7643's `rh2`), both the later printing of
  a repeated stage. No `bill_sections`, `section_diffs` or
  `section_diff_items` row re-keys, and the new key has no duplicate.

**A printing that still repeats is refused whole.** The family now withholds
every row of a printing whose `(version_code, source)` an earlier printing of
the bill carries -- its version row, sections and model rows -- and refuses
each comparison it would be a side of, so no printing mixes two documents and
no diff item names a withheld section. The row-level repeat refusal stays for
the other tables. A numbered reprint's kind is its stage's (`eas2` is an
edit-instruction document like `eas`).

**What adopting it costs spicy-regs.** The host derives each printing's code
with `printing_version_code` where it now calls `version_slug`, so host and
provider key printings alike. Its existing re-read and stale-pair repair fix
the published tables: 119 HR 6644's mixed printing publishes 276 rows against
the 198 its version row states, so the bill is re-read, and the two
comparisons published under the first printing's code are no neighbour pair
any more and retire.

## BILLSTATUS 1.0.0 is read under the guide's names

2026-09-26. The BILLSTATUS bulk zips still serve 13 files in schema 1.0.0 across
the 108th-119th Congresses: 113 HR 4200, 115 HR 3354 and eleven reserved 117th
House numbers (2, 9-17, 20). The reader refused them, so spicy-regs' bill family
held 115 HR 3354 -- an omnibus appropriations bill with 359 actions and three
printings -- and 113 HR 4200 as list-era rows only, and lacked 117 HR 11
(receipt `fork-execution-2026-09-21/bill-family-bulk-2026-09-26/partA/` under
`~/Work/corpora`).

**What 1.0.0 is.** The schema the publisher's user guide still documents. Every
field the reader returns is there under the guide's name: `<billType>` and
`<billNumber>` for the identity, `<version>` inside `<bill>`, committees under
`<committees><billCommittees>`, subjects and their policy area under
`<subjects><billSubjects>`, summaries under `<summaries><billSummaries><item>`
with the same children. Actions, sponsors, cosponsors, text versions, laws,
titles, related bills, CBO estimates and committee reports keep their 3.0.0
names. `<actions>` also states `<actionTypeCounts>` and `<actionByCounts>`,
tallies the publisher derives from the items. The element-path inventory of the
13 against 900 3.0.0 files from the same zips is in the receipt.

**What does not map.** 1.0.0 lists `<recordedVotes>` once for the bill, not on
the action that took the vote, so its actions carry no recorded votes: 2 votes,
both on 115 HR 3354. `updateDateIncludingText` and `legislationUrl` are absent
and read `None`. Nothing else the reader returns differs.

**Checked against Congress.gov.** For each of the 13, the detail record agrees
on title, introduced date, chamber, policy area, sponsor, latest action and the
counts of text versions, committees, summaries and committee reports. Where
counts differ, the API is newer than the file (115 HR 3354's file is from
2020-05-28; its related bills, titles and display title have since changed; 113
HR 4200 has since gained a CBO link), counts the policy area among subjects, or
lists one of the two identical introduction actions (117 HR 2).

## Bill text is read from the BILLS bulk zips from the 113th Congress on

2026-09-26. spicy-regs' bill family held a body for 3,548 of its 228,587
`bill_versions` rows (225,631 distinct printings; 2,956 carry both a `congress`
placeholder and a `govinfo` row), because its only body route was the
per-package one: three keyed requests per printing under a per-run cap of 600.
GovInfo publishes the same bytes in bulk (receipt
`fork-execution-2026-09-21/bill-family-bulk-2026-09-26/partB/` under
`~/Work/corpora`).

**What bulk covers.** The BILLS collection lists the 113th through 119th
Congresses: 112 folders, 135,395 printings, 1,039,459,484 zip bytes. It holds
137,467 of the 137,572 published printings in those Congresses (the other 105
name a package it does not list, or none), 133,919 of them without a body today.
The 108th-112th are not in it; their 88,059 printings reach only the
per-package route, and 110th-112th printings still offer XML there.

**The same bytes.** Every member of the 119th H.R. zips equals the per-package
XML captured for it, 3,516 of 3,516 by SHA-256, and every member of the three
zips measured is named in its folder listing with the same size and
`application/xml`. So a bulk member is the printing's body, and
`sources.congress.bulk_bills` checks it the way the per-package route checks
its response: identity by address (the member name), media type (the listing's
statement), not the error page. Its body record names the zip as the request
and carries the member's own size and digest.

**Not the content check.** `validate_bill_text` proves a printing's identity
from its XML, and refuses about 8% of real printings (titles it cannot read,
`amendment-doc` roots: 7,408 of 8,042 pass in 119/1/hr). The per-package route
does not apply it, so the bulk route does not either; applying it would refuse
printings the per-package route accepts.

**The listing first.** A folder's listing states each printing and the zip's
own stamp and size. It decides whether the zip moved (`zip_entry_unchanged`,
shared with the BILLSTATUS folders) and whether it holds any printing the
caller still needs, so the zip is downloaded only for a folder that does, read
once, and decompressed only for the members a `keep` predicate names.

**Printings apart from status.** `interpretation.bill_family.build_bill_printings`
builds one bill's printing tables from its listed printings without a fresh
BILLSTATUS, with a `context` set that takes part in order and comparison but
emits no rows: a caller reading bodies in bulk passes the newly read printings,
the held neighbours they are compared with, and the rest as placeholders. A
plain-language summary needs the bill's title, stage and money-bill kind, not its
status document, so it reads them from the bill's published `congress_bills` row.

## A volatile document tie goes to the latest write

2026-09-27, the owner's ruling on the Mirrulations re-fetch measurement.
Document acquisition policy `1.3` (`DOCUMENT_ACQUISITION_POLICY_VERSION`)
replaces `1.2`'s last-listed rule. Among observations of one document version
that differ only in `openForComment` or `withinCommentPeriod`, the one whose
listed S3 `LastModified` is more than an hour (`VOLATILE_TIE_MARGIN_SECONDS`)
after every other's publishes. Otherwise the smallest record digest among the
observations written within that hour of the newest publishes: stable under
reordered input, and never asserted to be the latest
(`releases.observations.volatile_tie_choice`). Document evidence packs record
each object's `LastModified` (`mirrulations-evidence-pack-v2`), so replay reaches
the same choice from evidence alone. Docket and comment packs and policies do
not move; their selection never reads it. The raw reader's
`MirrulationsReader.iter_keyed_records()` yields each payload as a
`KeyedPayload(key, last_modified, payload)` for callers that merge re-fetches,
such as spicy-regs' publication session. A reader handed to the document
acquisition must now give each source object a timezone-aware `last_modified`;
an object without one is refused ("lacks a listed LastModified"), never guessed.

**The key's suffix is not an order.** Listed 2026-09-27 over ACF and FMC whole
and eleven other agencies' dockets and documents: 1,604,507 records, 57,483 of
them with several copies (157,462 files). The mirror has written two suffix
grammars: stacked `X(1)(2)…(k).json`, in which chain length does follow fetch
order, and flat `X(n).json`. But it rewrites `X.json` in place, so the no-suffix
key sits anywhere in the order (2,408 groups). And a flat `X(2).json` written
after a stacked chain collides with the chain's `(1)(2)` and sorts far below
its end (438 groups). Where `LastModified` can tell, the last-listed object was
the newest write in 1,852 of 10,583 groups.

**Why `LastModified`, and why an hour.** The April 2025 bulk upload (2025-04-06
to 14) wrote each record's copies at most
12 seconds apart (48,508 groups), in upload order, not fetch order. The only
wider groups were five whose `X.json` was rewritten live the next day, which
their bodies' `modifyDate` confirms. Of 19,723 consecutive later writes of one
record, 5 fall within an hour. So an hour clears the upload 300-fold and sends
closer writes to the content choice, never to a guessed order. A second signal
comes from the publisher's own clock. Across 248,468 pairs of docket and document
copies written more than an hour apart, `modifyDate` never falls from the earlier
write to the later. In all 10,546 docket and document groups the rule resolves,
the chosen copy holds the greatest `modifyDate`. That signal cannot rank copies
sharing one `modifyDate`, which is the tie itself; only S3's write order does.

**What it resolves today.** Re-measured through `volatile_tie_choice`: all
10,583 groups whose writes span more than an hour resolve to the newest write,
and none falls back. The other 46,900 take the content choice. The real document
ties, found by reading every copy of those agencies' 30,709 multi-copy documents,
number 12. All 12 lie inside the bulk upload, so all take the content choice.
The independent review found 2 more in 15 other agencies. In all 14, the later
fetch closed the comment window. The content choice publishes
`openForComment=true` for 10 of them, whose windows closed in 2023-24; the
last-listed rule published `true` for all 14. The rule is right for every tie
the nightly re-fetches make from now on. The upload-era ties keep a stable but
stale flag, which is why the attribute tables describe these flags as the
publisher stated them on the latest version and read the window's state from
its dates.

**What a later change must preserve.** A `1.2` document release replays with
SpicyDocs 0.44.0, and current readers refuse it. It cannot be converted to `1.3`
offline: its `v1` packs never recorded `LastModified`, so its receipts stay
verifiable only with SpicyDocs 0.44.0. Another margin, fallback or
write signal is a new policy version, measured the same way. Receipts:
`~/Work/corpora/mirrulations-keys-2026-09-27/` (`measure_suffix_order.py`,
`margin_evidence.py`, `remeasure_tie_rule.py`, `verify_lastmodified_order.py`,
`run-2026-09-27/`).

## A comment's missing attachment text comes from the next tool

2026-09-27, spicy-regs owner decision 41 (publication session
`spicy-stack-75`), amending decision 19 (both in spicy-regs
`docs/research/fork-delivery-decisions-2026-09-22.md`). Decision 19 took one
Mirrulations extraction tool per comment in the pinned `DERIVED_TEXT_TOOLS`
order, and recorded the tool per attachment. Under it, 13 CMS comments from
2009-2010 each lost the text of one attachment that only the second tool held.
`list_docket_derived_text` now takes each attachment number from the
best-ranked tool that lists an object for it.

- The comment's `tool` stays the primary, its first available tool.
- Each `DerivedAttachment.tool` records where that attachment came from.
- `only_in_other_tools` keeps its name, the JSON field spicy-regs reads. It used
  to name numbers left unfilled; it now names the numbers filled from a tool
  other than the primary.

**Existence decides, not content.** A primary object that exists but is empty
stays the attachment: `pdfminer` left 1,446 zero-byte objects in decision 19's
measurement, and filling one from another tool would turn a stated extraction
into a guess. Nothing merges two tools' text within one attachment.

**No version moves.** Derived-text selection has no versioned identity of its
own, and the release-path policy never reads derived text. spicy-regs'
`pdf_extraction_results_json` is `CommentDerivedText.to_json()`, with no version
field. The provenance still tells the two rules apart. Under decision 19, a
number in `only_in_other_tools` never appears among `attachments`; under
decision 41 it always does, carrying its own `tool`. Rows spicy-regs filled
before adopting this keep their text until it refills them. Its
`sources/derived_text.py` docstring, which says one tool per comment, is
spicy-regs' to update.

## A composite identity is spelled `at-joined/1`

2026-09-27, requested by DocSpec's owner (spicy-stack-f5), within the spelling
authority DocSpec ruling R6 left to this package. It replaces the plan the
member-key decision above stated for composites, the ordered canonical JSON
array of their components. No contract had declared that spelling, so nothing
re-keys.

`at-joined/1` joins an identity's components in contract order with `@`. A
component that is empty or holds `@` is refused, not escaped, so splitting the
key on `@` always recovers the components. It needs two or more components; a
single column is `value/1`.

**Why not JSON.** DocSpec compiles every declared spelling to SQL once and
tests it against the Python reference, byte for byte. A join on a forbidden
separator compiles with no escaping rules. Canonical JSON would have to
reproduce the encoder's separators, key order and escaping of every string in
SQL, which is many chances for a mismatch that only a rare value reveals. The
refusal costs nothing where a component's grammar already excludes `@`, and a
contract declares the spelling only there.

**Declared on:**
- `bill_sections`, over `bill_id`, `version_code`, `source`, `seq`: a
  congress-type-number id, a publisher printing code, a fixed source vocabulary
  and a decimal ordinal;
- `fec_committee_history`, over `committee_id`, `cycle`: `C` plus eight digits,
  and a four-digit year.

None of the 2,659,863 live `bill_sections` rows or 298,395
`fec_committee_history` rows had an empty or `@`-holding component on
2026-09-27.

`federal-register-source-record-id/1` keeps its sealed name. For its two
components it yields the same bytes as `at-joined/1`.

## A bill section carries its Congress, so a host can store the table one file per Congress

2026-09-27, from spicy-regs' multi-file table design
(`docs/research/multi-file-tables-2026-09-26.md` §4.2 there). The owner chose
`bill_sections` as the first table spicy-regs publishes as several files, one
per Congress.

**The partition value is a column, derived from the identity.** A split
member's partition column must be stored inside the Parquet: its readers read
with Hive partitioning off, so a view's columns stay the declared ones. And
the value must be a function of the identity, or one row could sit in two
files and a carried-forward file could keep a stale copy of a row whose fresh
copy landed in another. `congress` is `bill_id`'s prefix, spelled by one
helper, `schemas.tables.bill_congress`, which the shaper and the host's split
both use. A `bill_id` with no decimal prefix refuses rather than naming a file.

**The identity does not change.** It stays `(bill_id, version_code, source,
seq)`: an identity naming the new column would re-mint every row downstream,
and `congress` adds nothing to it. The column is appended, so a prior table
without it NULL-fills in a host's merge; spicy-regs derives it from `bill_id`
when it first splits the table instead.

## 0.50.0 keys citations by source kind and names its branch builds

2026-09-27, release of `8844068`: the Codex branch
`codex/native-relationship-qualification` (PR #4) merged with 0.47.0. The
branch's commits state no reasons, so this entry records what moved and the
contract each move leaves. Review receipts:
`~/Work/corpora/fork-execution-2026-09-21/codex-pr-review-2026-09-27/spicy-docs-pr4/`.

### `document_citations` is keyed by source kind first

The identity is now `(document_kind, document_key, text_sha256, cite_kind,
target_key, span_start)`. It supersedes the five-column identity in
[the citation decision](#a-citation-is-keyed-on-where-it-was-read-and-its-rule-carries-a-version).

`document_key` is each family's own spelling, and one table serves every
family, so two families can hold the same key value. spicy-regs reads a House
communication's report nature and its legal authority as two kinds keyed by
the same communication. Under the old identity, one key, text digest, cite
kind, target and offset read under two kinds was one identity, and a keyed
merge kept one row and dropped the other without a word.
`tests/test_citation_context_qualification.py` holds the two rows apart.

The contract declares no key spelling, so no DocSpec member key moves. Every
row already carried `document_kind`, so only a cross-kind collision becomes two
rows. On the fork's `print-citations` generation (`sha256:c8e49dbb…`, read
2026-09-27), two document keys appear under more than one kind, and no
five-column group spans two kinds.

### A bill citation names where its Congress came from

`target_rule` for `bill_number` is now `bill_number:<basis>`, and it was
`bill_number`. The basis is one of:

- `inline_congress`: the print sets a Congress beside the bill;
- `congress_subheading`: a Congress subheading governs the text;
- `document_fallback`: the caller's document Congress, which is context, not
  proof that the bill belongs to it;
- `unstated`: no Congress was supplied, so the key stays the printed form;
- `document_fallback_refused`: `explicit_only` declined the document Congress.

Under the default policy `target_key` and `target_resolved` are unchanged; only
`target_rule`'s published value moves. That is why the rule moved from `005` to
`006`, and `CITATION_RULE_SET_VERSION` from `ef5f36c0a43b` to `fffaef3303b1`.
spicy-regs' print citations record the rule-set version in their processing
identity. Committee routes and every other kind keep their values.

`find_citations(bill_congress_policy=...)` takes `document_fallback`, the
default and the earlier behavior with its basis named, or `explicit_only`. Under
`explicit_only`, a bill with no inline Congress and no governing subheading
keeps its printed form with `target_resolved` false, rather than taking the
document's Congress. Neither policy reads a Congress from the clock, and any
other value is refused.

### Two occurrence tables carry their input digest and no current marker

- `bill_cosponsors`, keyed `(bill_id, input_sha256, cosponsor_index)`: one row
  per cosponsor entry of one BILLSTATUS document.
- `member_party_affiliations`, keyed `(bioguide_id, input_sha256, term_index,
  affiliation_index)`: one row per nested `party_affiliations` entry of one
  community-crosswalk capture.

`input_sha256` is the `sha256:` digest of the complete input bytes, so a
repeated member or interval stays its own occurrence and two captures never
share an identity. Neither table declares a version column, and neither
`congress_bills` nor `member_terms` carries the digest, so these tables alone
cannot say which capture is current. `congress_bills.cosponsors_outcome` and
`member_terms.party_affiliations_state` say whether the list was read, not
which capture it came from.

**The host replaces the scope it re-read; that is the contract.** A merge by
identity alone would keep every capture's list side by side. spicy-regs
replaces a bill's prior `bill_cosponsors` rows whenever its run read that
bill's list (`cosponsors_outcome` absent, empty or populated) and refused none
of them. It rewrites `member_party_affiliations` whole, from both complete
rosters, on every run.

### Three hosted tables take new columns mid-table

- `comments`: `comment_on_document_id`, `comment_on_object_id`,
  `original_document_id` and `comment_reference_values_json`, after `docket_id`;
- `documents`: `attachment_records_json`, after `attachments_json`;
- `house_communications`: `rin_occurrences_json`, after `rin`.

**The owner kept this inserted order as the contract** (2026-09-27), rather
than moving the columns to the end. It departs from the append-last convention
the other contracts follow ([tables](tables.md)); `congress_bills`' frozen
prefix is untouched.

Read 2026-09-27 over the fork's MCP, the fork's `comments` and `documents`
serve the contract order. Its `house_communications` generation
(`sha256:94d28167…`) has the same columns with `rin_occurrences_json` last, so
its order differs from the contract's until a host rewrites it from the
contract. A reader selecting these tables' columns by name sees no difference.

The published rows `tests/test_table_contracts.py` retains for `comments` and
`documents` predate the new columns. The round-trip test projects them onto the
contract order, so for those two tables it no longer compares the contract with
a published footer. (0.50.1 re-read them from the rewritten objects and
compares again: [below](#the-published-row-fixture-holds-the-column-order-again).)

### A RIN occurrence's field digest is bare hex

`rin_occurrences_from_report_nature` returns `RinOccurrence` values whose
`field_sha256` is the bare hexadecimal SHA-256 of the report nature's UTF-8
bytes. It has no `sha256:` prefix, unlike `tables.digest`,
`BillStatus.input_sha256` and `LegislatorsFile.input_sha256`. Hosts publish it
in `house_communications.rin_occurrences_json`, and bare hex is its current
spelling. The Senate payment review and candidate readers spell
`input_sha256` the same bare way, and neither is a table.

The occurrences come from the shared `rin` citation rule (version `004`). That
rule does not require the `RIN` label the scalar `report_nature_rin_label` rule
does, so the list can name a RIN where `rin` is NULL. (0.50.1 builds the scalar
from the list: [below](#the-scalar-rin-is-the-first-labelled-occurrence-of-the-list).)

### Native legal-reference rows have no table contract

`schemas.native_reference_rows` shapes U.S. Code reference and source-credit
observations and eCFR `AUTH`/`SOURCE` notes into rows. It has no entry in
`TABLE_CONTRACTS`: no declared identity, key spelling, version column or column
descriptions, and the three shapers return different column sets.
spicy-regs' `transforms/native_legal_references.py` states the
`native_legal_references` columns itself, and the fork publishes that table.
(Both tables have contracts now:
[below](#the-native-legal-reference-tables-have-contracts-and-an-observation-is-spelled-at-joined1).)

### Branch builds before 0.50.0 resolve to these commits

The branch built wheels under plain release numbers, and spicy-regs vendored
and pinned each; fork generations were built on them. Its first build took
0.47.0 about an hour before the bills lane released a different 0.47.0 from
`f549c16`. 0.50.0 takes the next number neither lane had used.

**The owner decided branch builds may take release numbers, with their lineage
recorded afterwards in release notes** (2026-09-27). This table is that record
for the branch "0.47.0", 0.48.0, 0.48.1 and 0.49.0. Each wheel below was
rebuilt from a `git archive` of its commit with `uv build --wheel` (uv 0.11.21)
and matched the vendored file byte for byte. `SOURCE_DATE_EPOCH` does not
change the output. The spicy-regs commits in the four branch-build rows are
on `codex/mcp-research-chaos`.

| Version | SpicyDocs commit | Wheel SHA-256 | Bytes | spicy-regs commits pinning it |
| --- | --- | --- | --- | --- |
| 0.47.0, branch build | `7440dd4a3c446962174b5c3048e313d34a3b287b` | `3a614d4aa16b0416e58690e7659037fef3397d3d6ce7ca21c1cc0e2c8ab42d29` | 1,685,325 | `d42c1b5` through `8173f5e` |
| 0.47.0, release | `f549c16c599e9fbf664b0d672b97be052e85ae87` | `ff3d9bb0ada5e38df4224533b6f41a3c989b25fd4ce7f3a161d9d054150346c5` | 1,677,512 | `0d63173`, main `516e78f` |
| 0.48.0 | `983463c9eca35fc93913fd798811e148b531516d` | `ee138dd86e62c254058ce9fe5f2f159dc6aa7d82ccc4580ed47edf09d28fd7fb` | 1,690,539 | `8082191`, `38379e7` |
| 0.48.1 | `8bcfef5e63361e3e780b2b4197afd1ce8ada78bc` | `6f5ca008096fe60765a49183345fc78acde2ffa99c2451720d53c14a5b554a0b` | 1,690,533 | `5afd01f`, `4466d85` |
| 0.49.0 | `1fda69252209685e12b3a037ed6d2d48e55574e2` | `b6ca1fed2508f42a363d9af35981ce7dabe9cb2252aee646945eb5d6b895d09c` | 1,692,410 | `1a020c9` |
| 0.50.0 | `8844068b355c41cd5ab7e7310cc5ba51798f741a` | `c739bc6f6bd488ca2afcb37d1bbcff57f14c0abe051638d4679ed17abf9eb64b` | 1,692,745 | `3e423cd` onward |

The bill-family generation `401302170a91…`, published outside the coordinated
path, names no provider version or digest in its publication receipt or its
Parquet footers. Its receipt was written at 22:14 UTC on 2026-09-27, before the
0.48.1 commit existed. The spicy-regs branch head then, `38379e7`, pinned
0.48.0. The `bill_cosponsors` contract is the same in every build from
`7440dd4` on.

**A record holding only the version string resolves through the commit that
wrote it.** SpicyDocs' `sources/fcc_ecfs_capture.py` writes `packageVersion`
from the installed distribution's version, and spicy-regs'
`pipelines/repair_regulations.py` records `spicy_docs_version` the same way. A
"0.47.0" from either names the branch build if a spicy-regs commit from
`d42c1b5` through `8173f5e` wrote it, and the release if a commit containing
`0d63173` did. A code digest recorded beside it also settles it: spicy-regs'
`spicy_docs_code()` digests the installed package and enters some processing
identities.

## 0.50.1 fixes what the PR #4 review found and reads the older CBO urls

2026-09-28. The fixes the independent review of PR #4 listed for 0.50.1, one
from the 108th-112th bill-text backfill, and the fixes and owner decisions from
the independent review of this release. Receipts, under `~/Work/corpora`: the
PR #4 review in `fork-execution-2026-09-21/codex-pr-review-2026-09-27/spicy-docs-pr4/`
(its `FOLLOWUPS-0.50.1.md` numbers the items), the measurements here and this
release's review in `fork-execution-2026-09-21/spicy-docs-0501/` (`review/`).
The owner's two 0.50.0 rulings stand: the inserted column order is the
contract, and branch builds may take release numbers. Items 8-10 (a native
legal-reference contract, a current-observation column, one digest spelling)
are not in this release.

### Published values that change

A host's rows change **on the next rebuild of each bill or communication**,
not on adoption: spicy-regs skips a bill whose publisher timestamp has not
moved, whatever the SpicyDocs version (the review read `build_bill_family.py`
there). Until a forced rebuild, `bill_cosponsors.source_xml` is mixed and the
108th-111th CBO rows keep their 0.50.0 values. The bills lane forces the
rebuild when it adopts 0.50.1.

| Table | Columns | Rows | Change |
| --- | --- | --- | --- |
| `bill_cosponsors` | `source_xml` | every row | loses the whitespace that followed `</item>` in the list |
| `house_communications` | `rin_rule` | 2,045 of the 5,006 retained | 2,040 rows are renamed only, `report_nature_rin_label` to `report_nature_rin_label/2`; 2 go from `unmatched` to `report_nature_rin_label/2`; 3 go to `unmatched` |
| `house_communications` | `rin`, `rin_matched_text` | 5 of the 5,006 retained | the three NOAA RINs read cut short become NULL; the two `RIN: 2120-Aa64` rows gain `2120-AA64` and that printed text |
| `cbo_cost_estimates` | `stated_count`, `restatements_json` | every 108th-111th row (4,762) | 1 becomes 2, and the http twin joins `[]` |

Nothing else a row publishes moves: in `cbo_cost_estimates` the `url`,
`description`, `title`, `pub_date` and `estimate_index` of every 108th-111th
row are the ones 0.50.0 published, and the 113th-119th rows measured (3,079)
are identical (`cbo-shape/compare-*.json`).

**Rule and identity names.** `rin_rule` moves, because values change under it.
`cbo_cost_estimates` keeps its identity `(bill_id, publication_id)` and
`publication_id_rule` `cbo_publication_url`: every `publication_id` is the one
0.50.0 published, the rule yields the same id for every url it read before,
and the two columns that change record the fold, not the estimate. No other key
spelling, row digest or rule version depends on a changed value:
`bill_cosponsors` is keyed on the input document's digest, not `source_xml`,
and `document_citations.target_rule` does not move. spicy-regs labels its GAO
page read `gao-qualified-page-heading-publication-block/1`; the read's
`pdf_url` is unchanged on every retained page, but it now refuses a page
without exactly one Full Report asset link, so the adopter decides whether that
label moves. spicy-regs is not edited here.

### The bill family refuses an unshapeable cosponsor instead of aborting

`shape_bill_cosponsor` raised `ValueError` without an input digest, and let
`AttributeError` escape for an entry that is not a `BillCosponsor` (0.47.0
typed the list as `BillSponsor`) and `IndexError` for an index outside the
list. None is in `SHAPER_REFUSALS`, so each lost every table of the bill's
pass. Every refusal is now a `TableContractError`, and the family files one
refusal per occurrence.

### `schemas` is a stdlib-only leaf again

`DOCUMENT.extract` imported `sources.regulations_gov.attachment_records` on
every call, and `schemas.fec_committee_history` imported the committee master's
header for an import-time check. `DOCUMENT.extract` now takes the
already-validated `attachment_records_json` string as a keyword, and
`sources.regulations_gov.attachment_records.attachment_records_json(document,
relationship)` stays the one validator. The FEC check is a test. Two tests hold
the rule: one imports every `schemas` module and runs each record type's
extract under a finder that refuses anything but the stdlib and `schemas`; the
other reads every `import` statement in `schemas/`, inside functions too.

### `source_xml` stops at `</item>`

`tostring` serializes an element's tail, so every `BillCosponsor.source_xml`
ended in the whitespace before the next item or `</cosponsors>`: all 506,301
entries in the PR #4 review's 39,147 documents, where its sample of first and
last rows had counted 55,723. The tail is set aside for the serialization.

Parse time does not move with it (`billstatus-timing/`): `parse_bill_status`
over those documents takes 15.5 s at 0.47.0, 22.0-23.2 s at 0.50.0 and 22.4 s
at 0.50.1 on 2026-09-28's machine, where the PR #4 review measured 18.9 s and
32.5 s. The reserialization is about 5.6 s of it, 11 microseconds an entry and
linear in entries; the six more fields and the input digest are about 1.3 s.
This release's review measured the same shape (8.7 microseconds an entry) and
found no stdlib call that serializes without the tail; slicing the publisher's
bytes by expat's offsets during the one parse is the cheaper route left open.

### The scalar RIN is the first labelled occurrence of the list

Before 0.50.1 `rin` came from its own pattern, `REPORT_NATURE_RIN`: the `RIN`
label, then a RIN in ASCII hyphen and capitals, with no right edge. So it
published the first eight characters of NOAA's five-character-suffix RINs
(`RIN: 0648-XE368` gave `0648-XE36`), missed the RIN the list reads from
`RIN: 2120-Aa64`, and on three inputs this release's review constructed
(`RIN2060-AV12`, `RIN: 2060-AV12–A`, `RIN: 2060-AV12/2060-AV13`) read a RIN
the list does not.

The owner chose to build it from the list. `rin_from_report_nature` returns the
first occurrence of the shared `rin` rule that the `RIN` label (the word, an
optional colon, optional whitespace) directly precedes: `rin` is that
occurrence's folded key and `rin_matched_text` the label and the RIN as
printed. Every scalar RIN is therefore in `rin_occurrences_json` at the same
span, and the three constructed inputs give neither. The rule is
`report_nature_rin_label/2`; `unmatched` keeps the name every matcher here
shares, so an `unmatched` row does not say which version ran until it is
rebuilt. `REPORT_NATURE_RIN` is removed, and the legislative data map tool
reads `rin_from_report_nature`. A host that publishes both columns passes the
list it read as `rin_from_report_nature(field, occurrences=...)`, so the
shared reader runs once per field; the list must carry the field's digest. The occurrence reader's `target_resolved`
filter removed nothing, because the `rin` rule keys every hit through
`published_rin`, and is gone.

The list still holds more than the scalar, by design: later members of a
labelled list, later labelled RINs, and RINs under a plural, spelled-out or
misspelled label. Over the fork's `house_communications` retained 2026-09-27
(5,006 rows, `rin-agreement/`), 2,042 rows have a scalar RIN, every one in the
list at its span, and the list holds 34 more.

### CBO urls on http fold with their https twin

Every 108th-112th bill-family run refused 4,762 `cbo_cost_estimates` rows as
outside the publication-page shape. Over all 40 BILLSTATUS zips of those
Congresses (`cbo-shape/`): the 112th states no estimate, and each of the
108th-111th's 9,524 items is one of a pair naming one publication in one bill,
`http://www.cbo.gov/publication/{id}` and `https://www.cbo.gov/publication/{id}`.
There are 4,762 pairs and no other shape. CBO's sitemap lists 4,761 of the ids,
every one on https and none on http, and a plain GET of either scheme for six
sampled ids gets the same 403 challenge. So the http url names the page CBO
serves on https.

`publication_id` now accepts exactly `http` or `https`, `www.cbo.gov` and
`/publication/{positive integer}`. The two statements fold onto one row, and
the owner chose the https statement as the row, else the first statement: the
http twin comes first in 4,673 pairs and wraps its description in `<p>` (and
once misspells a title, 108 S. 1978), where the https statement is plain and
is the row 0.50.0 already published. The http twin is a restatement in
`restatements_json`, which is why every such row's `stated_count` and
`restatements_json` change and nothing else does.

### The published-row fixture holds the column order again

The retained `comments` and `documents` rows are re-read by id from the fork's
2026-09-28 objects, which carry the 0.50.0 columns in the contract's order;
every value the 2026-09-25 rows held is unchanged. The round-trip test takes
them as published, so moving a column in either contract fails it.

### Smaller fixes

- `GaoTargetMetadata.pdf_url` is the path of the page's own `Full Report` link
  on `files.gao.gov`, the host that serves it without a browser, so it matches
  `GaoReportIndex.pdf_url` for the same product. A link off `www.gao.gov` or
  `files.gao.gov`, outside `/assets/` or with a query refuses; a fragment
  (`#page=2`) names a place in the same file and is dropped. Links are counted
  by the asset path they resolve to, so one PDF linked relatively and
  absolutely is one link, and a page with no Full Report path or two different
  ones refuses. All 47 product pages retained on 2026-08-22 link
  `/assets/{product-id}.pdf`, so the value equals 0.50.0's locator on each.
- `CitationContext.congress_basis` left unset follows `congress`:
  `document_fallback` with one, `unstated` without. A basis outside the
  vocabulary, or one that contradicts `congress`, refuses. Fields keep their
  order.
- The withdrawal-date claim in `BillCosponsor` and the bills guide is corrected:
  positive dates are retained as stated; the 119 S 1224 fixture carries one and
  the PR #4 review's sweep found 243.
- `sources/public_comments/native.py` states its scope: upstream's tree at
  `data.spicy-regs.dev`, 15 columns per partition file. The fork's mirror (20
  columns) is refused by design; the `comments` contract describes it (S4).
  This release's review read upstream's footer live and confirmed both.

### What an importer must change

- `DOCUMENT.extract(payload, attachment_relationship=...)` is now
  `DOCUMENT.extract(payload, attachment_records_json=attachment_records_json(payload, relationship))`.
  No repository in the stack calls the old form; spicy-regs has its own extract.
- `communication_rin.REPORT_NATURE_RIN` is removed; `RIN_LABEL` is the label
  pattern and `RIN_LABEL_RULE` the rule name. A filter on
  `rin_rule = 'report_nature_rin_label'` matches only rows read before 0.50.1.
  `rin_from_report_nature` takes an optional `occurrences=` keyword.
- `shape_bill_cosponsor` raises `TableContractError` where it raised
  `ValueError`, `IndexError` or `AttributeError`.
- `CitationContext.congress_basis` is typed `str | None`; the instance always
  holds a string. `CitationContext()` names `unstated`, and a basis outside
  the vocabulary or contradicting the Congress refuses.
- `product_page_metadata` refuses a page without exactly one `Full Report`
  asset link.
- `schemas.fec_committee_history` no longer imports `COMMITTEE_MASTER_FIELDS`;
  import it from `sources.fec.committee_master`.
- `publication_id` accepts http, and `fold_cbo_cost_estimates` rows the https
  statement.

spicy-regs, when it adopts 0.50.1 (read there at its current checkout; not
edited here):

- `tests/test_congress_index.py:145` expects `rin_rule`
  `report_nature_rin_label`; under 0.50.1 it is `report_nature_rin_label/2`.
- Its data dictionary names the old rule (`data_dictionary/descriptions.yaml`
  and the generated `table_metadata.json`), and the contract descriptions it
  reads changed on three `house_communications` columns (`rin`, `rin_rule`,
  `rin_matched_text`) and three `cbo_cost_estimates` columns
  (`estimate_index`, `stated_count`, `restatements_json`), so its dictionary
  generate and check steps move with them.
- `transforms/build_congress_index.py:129-140` (`_repair_rin_occurrences`)
  repairs rows it does not re-read by filling `rin_occurrences_json` from the
  retained `report_nature`. `rin`, `rin_rule` and `rin_matched_text` need the
  same repair, or those rows keep the 0.50.0 scalar under the old rule name;
  `rin_from_report_nature(field, occurrences=...)` can reuse the list the
  repair reads.
- Its GAO target build labels the page read
  `gao-qualified-page-heading-publication-block/1`; see above.

## 0.51.0 reads failed and vetoed bills in publisher order, two more citation spellings and two new sources

2026-09-28. Four groups from the unitedstates reuse review
(`docs/unitedstates-review-2026-09-28/` in the spicy-stack workspace), each
reviewed independently before release: bill-stage corrections, two citation
spellings, the administration-policy statements reader over a bounded YAML
loader, and the Inspector General archive metadata reader. Receipts, under
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/`:
`release-0.51.0/` (stage and citation replays, gate log, wheel) and `sap/`
(the administration-policy archive replay).

The owner's decisions of 2026-09-28:

- Bill stage and the citation spellings ship now.
- Same-day actions follow the publisher's list order in this release, not a
  later one (the review found the defect; see below).
- The administration-policy reader ships; its spicy-regs table is the bills
  lane's next item.
- The Inspector General archive reader ships: an IG reports table starts in
  the bills lane.
- The legislator-companion and historical-statute readers have no consumer.
  They wait on the tagged branch `unitedstates-spare-readers-20260928`, not
  main, until a consumer names them.
- The Congressional Record parser is being forked under mikewolfd, with an
  upstream PR and a separate adapter branch; nothing of it is in this release.

### Published values that change

`congress_bills.stage` and its provenance columns, and `bill_actions.stage`,
change on the next rebuild of each bill. Measured on live `congress_bills`,
artifact sha256:6b8ce7a2bf9a240078ba4cd438e151fe43594a4fdb10369af3ece42f6cd5c063,
queried 2026-09-28 through the fork MCP, by the 0.50.1 matcher that fired:

- 421,465 rows; 248,469 have NULL stage (every bill before the 108th
  Congress; pre-existing, unrelated to this change);
- 48,941 rows staged `other_chamber` by the matcher `referred` become
  `committee`;
- 194 rows staged by `star print` lose that stage (no rule fires on the
  action; the bill's stage comes from its latest action a rule does read);
- 56 rows staged `law` by the bare substring `public law` are re-read (the
  rule now needs the action to start with an enactment phrase);
- 11 rows staged `passed_chamber` by `failed of passage` become `failed`, or
  `vetoed` where the failed vote was an override: the replay below reads all
  11 as `vetoed`;
- 45 rows staged `passed_chamber` by `on passage` now depend on the vote's
  result text;
- 0 rows were staged `law` by `public print`, so the headline bug of the review
  has no live incidence.

The whole column, replayed (`release-0.51.0/stage-replay/`): the live
bill-family generation `c28ed5b1…` (the same 421,465 bills and the same counts
above) folded through the 0.50.1 rules reproduces every published `stage`,
`stage_rule`, `stage_matcher` and `stage_action_index` on all 172,991 bills with
actions. The rules as first reviewed change 50,762 of them. With publisher-order
ties, which this release ships, 154,374 change. The 0.50.1 fold read the
newest-first BILLSTATUS list as chronological, so a day's oldest action won a
same-day tie: 93,075 of the 98,768 bills published as `introduced` were referred
to committee the same day. The largest moves, live to 0.51.0:

| From | To | Bills |
| --- | --- | --- |
| `introduced` | `committee` | 92,981 |
| `other_chamber` | `committee` | 49,264 |
| `committee` | `other_chamber` | 5,682 |
| `introduced` | `passed_chamber` | 4,884 |
| `introduced` | `other_chamber` | 610 |
| `passed_chamber` | `other_chamber` | 341 |
| `committee` | `passed_chamber` | 181 |
| `passed_chamber` | `failed` | 126 |

After it, 265 bills read `introduced`, 182 `failed` and 43 `vetoed`; the full
transition table is `transitions-live-to-0.51.0.csv`. Across the live
`bill_actions` rows no adjacent pair runs forward in date and none of 106,013
same-day timed pairs runs forward in time, which is why the list's order, not
`actionTime`, orders a day.

`bill_committee_actions.sealed_stage` reads print phrases through the same text
rules: `referred` becomes `committee`, and the became-law matcher is
`became public law`.

`document_citations` gains the two spellings on the next read of a document.
Replayed over the parsing survey's 60,000 Federal Register texts
(`release-0.51.0/citation-replay/`): 61 new findings (3 `usc_section`, 58
`cfr_section`), none lost; each is a section or part the text states.

### Review fixes folded in

- Same-day actions follow publisher order: `infer_stage(actions, *,
  newest_first=False)`, and `bill_family` passes `True`. The time key the
  first draft used would have put a timed House vote after the untimed Senate
  receipt that followed it.
- A pocket veto records `pocket vetoed by president` as its matcher; the code
  map is one module constant and the code is read once per action.
- The `stage_matcher` contract text names vote-result readings too, and
  `docs/interpretation.md` no longer says a referral reads `other_chamber`.
- The section-first U.S.C. pattern sat between `_USC_CODE_FORMS` and its doc
  comment; both patterns now cite the survey replay.
- The YAML loader refuses explicit `!!timestamp`, `!!binary`, `!!set`,
  `!!omap` and `!!pairs` tags, so a tagged date cannot come back as a date;
  aliases are named as aliases.
- The Inspector General reader checks the caller's locator before the body.
- Tests added for every qualified code and unknown codes, suspension and
  override votes, the `bill_family` action rows, the YAML tags and missing
  extra, the policy budget caps and the `AdministrationPolicyRefused` type.

### What an importer must change

- The stage vocabulary gains `failed` and `vetoed` (`OUTCOME_STAGES`).
  `stage_index` returns -1 and `stage_progress` raises `ValueError` for them;
  a fixed allowlist of stage values must add both.
- `STAGES`' label for `law` is **Became law**, not "Signed into law" (it covers
  a veto override). No repository in the stack reads the label.
- `stage_matcher` can hold a publisher code (`36000`, `8000`, ...) or a
  vote-result reading (`failed passage vote`, `successful passage vote`), not
  only a text pattern; `stage_rule` adds `failed_passage`, `vetoed`,
  `action_code` and `became_law_code`.
- `infer_stage` takes `newest_first`; a caller passing a BILLSTATUS list in
  publisher order must pass `True`. `infer_stage_from_action` is new and is
  what `bill_family` uses for both tables.
- The `stage` and `stage_matcher` contract descriptions changed in both
  `congress_bills` and `bill_actions` (`schemas/bill_tables.py`), so spicy-regs
  regenerates its dictionary.
- spicy-regs suppresses `stage_changed` activity events for the generation that
  adopts 0.51.0 (owner decision): they are rule changes, not legislative
  events, and the replay above would otherwise emit one for each re-read bill.
- Citation rules `usc_section` and `cfr_section` are version 004; the rule-set
  digest is `5609cfaab8bb`.
- The `yaml` extra (`PyYAML>=6,<7`) exists; the administration-policy reader
  needs it with `acquisition`.

## The native legal-reference tables have contracts, and an observation is spelled `at-joined/1`

2026-09-28. The owner decided that this package owns the table contracts of
the fork's published native legal-reference tables, item 8 of the
[0.50.1 follow-ups](#0501-fixes-what-the-pr-4-review-found-and-reads-the-older-cbo-urls),
and that row shaping and the reading of each observation move here with them.
spicy-regs' `transforms/native_legal_references.py` stated their columns and
identities and read each observation itself (`_interpret`), so DocSpec could
not admit the tables and Search could not serve them. Behavior and
measurements:
[Table contracts](tables.md#the-native-legal-reference-tables-are-a-scanners-observations-and-its-reads).
Receipts: `~/Work/corpora/fork-execution-2026-09-21/native-refs-contract/`.

**The identities and columns do not move.** `native_legal_references` and
`native_legal_reference_reads` are the published tables as they stand: their
columns in the fork's footer order, and the identities its host merges on,
`(scope_id, input_sha256, occurrence_index)` and `scope_id`. The rows are live,
and moving an identity would re-key every one downstream; nothing here needed
it. Neither declares a version column. `rule_version` supports equality only,
and a complete read replacing its whole scope, not a version, decides which
rows are current.

**Why `at-joined/1`.** The observation identity is composite, and DocSpec
admits a table only on a declared spelling. Its components are two `sha256:`
digests and a decimal ordinal, so none can hold `@` by its grammar, and the
shapers refuse an input digest spelled any other way. None of the 881 live rows
had an empty or `@`-holding component on 2026-09-28. The read identity is one
column, spelled `value/1`, and each observation's `scope_id` references it.

**Shaping and the reading live here; the host looks targets up.**
- `shape_uscode_reference`, `shape_uscode_source_credit` and `shape_ecfr_note`
  return whole contract rows, checked and keyed. They set `source_family` and
  compute `scope_id` through `native_reference_scope_id`, as the host did. The
  scope's preimage keeps non-ASCII characters literal, the host's spelling
  rather than `json_column`'s escapes, so a record key or edition outside ASCII
  keeps the scope the host already minted; none published has one.
- `interpretation.native_legal_references` is the host's `_interpret`, moved
  unchanged (read at its `fork/main` `63a18d7`). It types an exact native href
  and reads a note's text with the shared citation rules.
  `interpret_native_references` fills a run's three remaining columns:
  `interpretation_status`, `target_candidates_json` and `rule_version`.
- `shape_native_reference_read` shapes the read row. The selected and
  unsupported shapes it lists are the scanners', so they are stated beside them.
- Whether a typed target is held is the host's lookup in the tables it selected.
  That lookup runs DuckDB over the host's own Parquet (spicy-regs
  `citation_resolution.resolve_citations`), which a stdlib leaf and a pure
  reading cannot do. So `interpret_native_references` requires it as
  `resolve`: one call for the whole run, as before, so each distinct key is
  read once and the host's bounds apply per run. Every row therefore carries
  a lookup outcome.
- The lookup is given a deep copy of the candidates, and each outcome must keep
  every field of its candidate, type included (`true` is not `1`, nor `125`
  `125.0`), in candidate order, or the run refuses. No more than one outcome
  past the candidates is read, so an endless lookup refuses rather than runs. So a
  lookup that sorts, pops or rekeys the list it was given, or returns a
  candidate with another `target_key` or `document_key`, cannot move a
  candidate into another row or change what it names. Two rows naming one
  observation (one `scope_id` and `occurrence_index`, differing only in
  `input_sha256`) refuse before the lookup, since their candidates would share
  keys.

**The rule version moves to `native-legal-reference/003`, because published
values move.** `NATIVE_LEGAL_REFERENCE_RULE` names it for both tables. It
versions the scanners' selected shapes and the reading, including the citation
rules the reading calls, so any change among them that moves a published value
moves it. Two such changes land in this republish, which the owner accepted as
one (2026-09-28): `json_column` re-spells 14 `target_candidates_json` values,
and citation rules 004 re-version 51 text candidates in 31 eCFR notes, both
below. The href typing, the kinds read, the shapes and the status vocabulary
did not change. `/002` names the rows spicy-regs read before the reading moved
here. The review of the rebased branch found the version move owed after a
first draft of this entry had kept `/002` on the ground that each candidate
names its own citation rule's version. That still holds, but a row-level
version that stays put while the row's value moves would tell a reader that
nothing changed.

**One published value changes, by spelling only: `target_candidates_json` is
`json_column`'s.** The host wrote it with non-ASCII characters literal. The
owner accepted the change once, with no outside users (2026-09-28). Fourteen
live values change, each a U.S. Code Title 1 source credit whose
`matched_text` holds an en dash (`Pub. L. 104–199`), now `\u2013`. They are
occurrences 94, 294, 309, 355, 447, 459, 490, 546, 590, 634, 665, 776, 786
and 798 of scope `sha256:d4bb5775…`. Each decodes to the same JSON as before.
The re-spelling moves no other value, and a reader of the JSON sees no change.

**0.51.0's citation rules move 51 candidates' versions.** 0.51.0 took
`usc_section` and `cfr_section` to version 004. Read on it, 51 text candidates
in 31 eCFR Title 1 notes name `derivation_version` `004` where the published
rows name `003`: 49 `usc_section` and 2 `cfr_section`. They are occurrences 0,
1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 29, 31, 33, 34, 35, 36, 38, 40,
43, 44, 45, 47, 50, 52, 54, 56 and 58 of scope `sha256:ed5b5c65…`. No
candidate is added or lost, and no key, span, status or other field moves. The
U.S. Code source credits hold neither kind.

**Digest spelling.** The owner unified digests on `sha256:`. Every published
digest column here is already spelled that way: `scope_id`, `input_sha256`,
`manifest_sha256`, and the digests nested in `target_candidates_json`. So the
spelling changes no value. The shapers refuse a bare-hex input or manifest
digest. The CFR scanner's `EcfrAuthorityScan.input_sha256` is bare hex, and a
caller prefixes it; it is never published.

**What was measured.** The fork's generation `sha256:53755e3e…` (881
observations, 2 reads) was measured on 2026-09-28. Both footers and the
publication index list exactly the contracts' columns, all VARCHAR, and every
member key spells, is distinct and splits back into its components. The run was
then rebuilt on 0.51.0 from its retained manifest and inputs, with the host's
own resolver copied unmodified as the lookup:
- every row of both tables names `native-legal-reference/003` where the
  published row names `/002`;
- besides that, 836 observations equal the published rows on the other 19
  columns;
- 14 differ also in the re-spelled `target_candidates_json` above;
- 31 differ also in the 51 candidate versions citation rules 004 move;
- both read rows equal the published ones on the other 12 columns.

No row differs in any other way.

**What changes for an importer.**
- The three observation shapers return every contract column in order: `scope_id`
  and `source_family` filled, the three reading columns NULL until
  `interpret_native_references` fills them.
- They refuse with `TableContractError`, still a `ValueError`. They also refuse
  three inputs they accepted: an input digest not spelled `sha256:` plus 64
  lowercase hex, an empty-string edition, and an empty-string eCFR title.
- Their `observation` parameters are typed by `Protocol`s naming the fields
  each reads (`UsCodeReferenceObservation`, `TextObservation`,
  `EcfrNoteObservation`); the scanners' observations satisfy them unchanged.
- New: `interpretation.native_legal_references`, `shape_native_reference_read`
  and `NATIVE_LEGAL_REFERENCE_RULE`. `TABLE_CONTRACTS` holds two more
  contracts. `schemas.tables.digest` is typed by overload, so a `str` argument
  types as `str`; its behavior is unchanged.

**What the first republish changes.** Every row of both tables, in
`rule_version`; 14 `target_candidates_json` values by spelling; and 51
candidates' `derivation_version` in 31 of them. Nothing else, by the rebuild
above.

**What spicy-regs must change to adopt it.** Read at its `fork/main`
(`c2cd4a5`, whose native files equal `63a18d7`'s); nothing there is changed
here.
- Pin the release that carries this: both `spicy-docs[...]` requirements
  (`pyproject.toml:25` and `:39`, `==0.50.1` today), the vendored wheel path
  (`pyproject.toml:128`, `vendor/spicy_docs-0.50.1-py3-none-any.whl`), the wheel
  itself in `vendor/`, and the lock.
- In `transforms/native_legal_references.py`, delete `_interpret`, `RULE`,
  `REFERENCE_COLUMNS`, `READ_COLUMNS`, `SCHEMAS`, the literal identities and
  the hand-built read row. Keep the manifest, pins, evidence, qualification
  and scan loop. `OUTPUTS` becomes the two contracts' names plus `.parquet`;
  `pipelines/rollups/native_legal_references.py:10` imports it.
- Pass the run's rows to `interpret_native_references`, with its lookup as
  `resolve`: `resolve_citations(cursor, candidates, snapshots,
  source_digests=texts)["occurrences"]`, recording its `coverage` as it does
  now. Build each read row with `shape_native_reference_read`, and merge both
  tables through their contracts with its existing scope replacement.
- Host both contracts in `CONTRACT_TABLES` and move `ADOPTED_CONTRACT_COUNT` by
  two. `TABLES` already names both tables before it appends `CONTRACT_TABLES`,
  so it must drop those two entries or list them twice. Their prose then comes
  from the contract (`columns_from: spicy_docs`), not `descriptions.yaml`, and
  `expected_schemas` from the contract, not its `SCHEMAS`.
- Declare the join `native_legal_references.scope_id` to
  `native_legal_reference_reads.scope_id` in `table_joins`, whose test requires
  a declared join for every contract reference.
- Run `spicy-regs-dict generate` and commit what it rebuilds from the new
  prose, descriptions and join: `src/spicy_regs/table_joins.json`,
  `table_metadata.json` and `table_qualification.json` beside it,
  `data_dictionary/catalog.json` with its `.sha256`, and
  `docs/tables/native_legal_reference*.md`.
- Rewrite `docs/native-legal-references.md`, which says spicy-regs reads each
  observation, to point at this reading and its contracts.
- Update the tests that use the removed names:
  - `tests/test_native_legal_inputs.py:77` imports `_interpret`; it should call
    `interpret_native_reference`;
  - `tests/test_native_legal_references.py:14` imports `SCHEMAS`;
  - `tests/test_join_delivery_registration.py` iterates `SCHEMAS`;
  - any assertion on the shapers' old partial rows.
- After the first republish under `/003`, re-qualify the native entry in
  `docs/research/fork-output-ledger-2026-09-21.md`: its T12/T13 row
  (`run-rollup-native-legal-references`) and its qualification section both pin
  `53755e3e…`, as does `table_qualification.json` (`pin` `53755e3e`), which
  `spicy-regs-dict generate` rebuilds from the ledger.

## CBO's own feed is read for every Congress

2026-09-28, for the next release. Receipt:
`~/Work/corpora/fork-execution-2026-09-21/cbo-112-113/`, with every script, the
fetched feeds (`feeds/`, 108th-119th) and zips, and the independent reviews'
work in `review/` and `review-2/`.

**BILLSTATUS states no CBO estimate for the 112th and 113th.** Over every bill
type's zip (fetched keyless 2026-09-28; GovInfo's Last-Modified is January
2024), the 112th's 12,299 documents and the 113th's 10,637 carry no
`<cboCostEstimates>` item, where the 111th's carry 2,156 items in 902
documents. A regex over the raw bytes and `parse_bill_status` agree: the one
113th element is empty (H.R. 4200, `requested-empty:present-and-empty`), and
every other document is `requested-empty:absent`.

**The rows come from CBO's keyless per-Congress feed, `source` `cbo_feed`.**
The first route built for this asked Congress.gov's bill record, keyed, about
each bill the feed names (`congress_api`, 56 requests sampled). The
independent review of that branch showed the record's 112th-113th lists are
the feed regrouped by `Bill_Number`: the same instants and bytes, CBO's wrong
numbers followed (112 H.R. 1707 lists CBO's estimate of S. 1707) and nothing
for an item whose `Bill_Number` is empty. The keyed route added nothing, so
the owner chose (2026-09-28) to build the rows from the feed itself and to
remove the Congress.gov reader, its `bill-detail` listing route, tests and
fixtures; the branch history keeps them. `congress_api` stays in the sealed
vocabulary, reserved, and `cbo_feed` is added.

`build_cbo_feed_cost_estimates(feed, congress, report_citations=...)` maps
each item to a bill by its `Bill_Number` or, where that is empty, by the
citation its title leads with (below), and shapes the items through the same
fold, publication-url rule, refusals and shaper as the BILLSTATUS route. The
identity `(bill_id, publication_id)` and `publication_id_rule` do not move.
The 112th feed gives 914 rows and the 113th 1,101, with no refusal.

**The host builds feed rows for every Congress and merges them** (owner
decision 2026-09-28, after the second review). `merge_cbo_cost_estimates`
keeps the BILLSTATUS row wherever both routes state one bill and publication,
so outside the 112th-113th the feed adds only what no BILLSTATUS record lists.
Over the retained zips and feeds, with a law map built from the zips' `<laws>`
(`every-congress/merge.json`):

| Congress | 108 | 109 | 110 | 111 | 112 | 113 | 114 | 115 | 116 | 117 | 118 | 119 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BILLSTATUS rows | 1,200 | 1,031 | 1,453 | 1,078 | 0 | 0 | 1,299 | 1,665 | 1,250 | 1,136 | 1,462 | 1,158 |
| Feed rows the merge adds | 0 | 0 | 11 | 9 | 914 | 1,101 | 2 | 1 | 1 | 3 | 2 | 4 |

Every one of the 12,732 BILLSTATUS rows comes out of the merge unchanged, and
the 33 feed rows added outside the 112th-113th include the 111th's H.R. 1, H.R.
3200 and two estimates of H.R. 3590, the 110th's P.L. 110-50, a row of 110
S. 966 through the law map (`found_by` `title_law`), and the two bare numbers
below. On 8 bills both routes publish rows; `estimate_index` is each row's
place in its own route's list, so two rows of one bill can share one, and the
column says so. Over the 108th-119th the feed refuses 9 items by name: seven
titles citing a bill after their start, an amendment (`S.A. 948`) and a
trailing comma (119th `H.R. 7529,`). Only the last is an estimate BILLSTATUS
lists, so eight have no row on either route.

**A bare-number `Bill_Number` reads through the title's citation of that
number** (owner decision 2026-09-28, after the second review). Two feed items
state a number and no type, and neither estimate is in any BILLSTATUS record:
the 117th's `700`, titled `H.R. 700, an act to designate ...` (58395), and the
118th's `106`, titled `S. 106, Commitment to Veteran Support and Outreach Act`
(58967). `sources.cbo.bare_number_bill` takes the type from the citation the
title leads with, only where its number is the same: a title leading with
another number refuses (`title-disagrees`), and one leading with no single bill
(prose, a law, two bills) refuses as the bare number did (`N`). The rows are
117 H.R. 700 and 118 S. 106, `found_by` `bill_number_title`, a value appended
to the sealed vocabulary; the merge adds one row each to the 117th and 118th.
`feed_item_bills`, the `Bill_Number` grammar alone, still refuses a bare
number.

**One publication can stand under two bills, and both rows publish.** The
identity is `(bill_id, publication_id)`, never the publication alone: the 112th
feed files 22065, CBO's estimate of P.L. 111-322, under the 112th's H.R. 3082,
and the 111th's H.R. 3082 BILLSTATUS lists it; the 113th feed files 52538 under
the 113th's H.R. 1422, and the 115th's H.R. 1422 BILLSTATUS lists it too; and
BILLSTATUS lists 51369 under both 114 H.R. 3347 and H.R. 3447. `publication_id`
says so, and a test merges 22065's two rows and keeps both.

- `pub_date` is the item's RFC 2822 `Date` as the same instant in UTC, spelled
  as BILLSTATUS spells a `pubDate`, because a version column has to sort as
  text; Congress.gov lists that spelling for all 43 items sampled.
- A bill's items are ordered oldest first, then by publication id, for
  `estimate_index`: the feed runs newest first and its order within one `Date`
  changes between captures of the same items.
- The report citations are the bill's own BILLSTATUS `<committeeReports>`,
  which the host passes in; a bill it passes none for publishes NULL in both
  citation columns rather than a zero no document stated.
- If BILLSTATUS and the feed ever state one `(bill_id, publication_id)`,
  BILLSTATUS wins: it is the publisher's own record of that bill.
  `merge_cbo_cost_estimates` applies `SOURCE_PRECEDENCE` (`billstatus_bulk`,
  `congress_api`, `cbo_feed`) before the larger `pub_date`, and a test holds
  it. A host merge must apply it.

**The CBO `bill-detail` route is removed, and why** (owner decision
2026-09-28). The branch had added `bill-detail` (`bill/{congress}/{type}/{number}`)
to `LIST_ROUTES` for the Congress.gov CBO reader. Congress.gov's 112th-113th
CBO list is CBO's feed regrouped, so the reader and its route went together;
nothing else used the route. A later subjects route for spicy-regs'
`bill_subjects` (the consolidation plan's B10, which waits on a run deadline
in spicy-docs) is unrelated to this removal and is designed when it comes, with
its deadline.

**A `Bill_Number` maps by a grammar every measured form fits, and nothing
else.** Every form in the 108th-119th feeds is a type's abbreviation words,
each ended by a period, a space or both, then the number. The 112th and 113th
refuse no item. The rule refuses an amendment, trailing text and a list rather
than guess a type or split a list, because no item in any measured feed needed
that; a bare number reads only through its title (below).

**Where `Bill_Number` is empty, the title's leading citation names the bill**
(owner decision 2026-09-28). 92 and 186 items leave `Bill_Number` empty, and 61
and 170 of them have a title that leads with a bill citation: 44 and 137 bills
no `Bill_Number` names, which now have rows. `title_citation` reads the
leading citation in the `Bill_Number` grammar, written capitalized so prose
("Obama's 2013") cannot read as one, and refuses by shape a second citation of
another bill, a citation after the start and an abbreviation and number that is
no bill type. `CboFeedBill.found_by` says how each item named its bill.

**`title_bill_id` publishes the bill an estimate's title names, on every
route** (owner decision 2026-09-28). The new, nullable column of
`cbo_cost_estimates` is the bill the title leads with, by the same rule, or
NULL. Where it differs from `bill_id`, `bill_id` is a numbering error as
published and `title_bill_id` is the bill scored. A bill citation reads in
the row's own Congress, so the column cannot show a link to the same number in
another Congress: 115 H.R. 1422's BILLSTATUS lists 52538, CBO's 2013 estimate
of the 113th's H.R. 1422, and `title_bill_id` reads `115-hr-1422`. The grammar
moved twice in this round, so `title_bill_id_rule` is appended too, on every
row, naming the rule that read it (`cbo_title_citation/1`), as
`publication_id_rule` does for its column. On a feed row found by its title
(`found_by` `title`, `title_law` or `bill_number_title`) the title chose
`bill_id`, so the two agree by construction and agreement there proves
nothing: 237 such rows with a law map, 235 without. Over the 108th-119th,
re-measured at the head that added bare numbers (`title-bill/title-bill.json`,
`title-bill-no-map.json`):

| Route | Rows | Differs by a bill title | Title names a public law | Differs with a law map | NULL: cites after the start | NULL: no citation | NULL: other form |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BILLSTATUS, 108th-111th and 114th-119th | 12,732 | 5 | 6 | 2 | 275 | 46 | 0 |
| Feed, 108th-119th | 14,770; 14,772 with a law map | 5 | 7 | 3 | 296 | 67 | 1 |

The feed's five are CBO's own numbers: 112 H.R. 1707 for S. 1707, 115 S. 2416
for S. 2461, 117 S. 2671 for S. 2761, 119 H.R. 648 for H.R. 658 and 119 H.R.
5201 for H.R. 5021. BILLSTATUS repeats the last four and adds 114 H.R. 3347,
whose record lists CBO's estimate of H.R. 3447 although the feed item states
3447, so there the bill record is wrong, not CBO. `bill_id` keeps what the
source published, because the identity is the source's statement and a
corrected key would be a guess the column beside it already states.

**A title leading with a public law names its bill through the host's `laws`
table** (owner decision 2026-09-28). The 112th feed files CBO's estimate of
P.L. 111-322 under Bill_Number H.R. 3082, which was that law's bill in the
111th Congress, so the 112th's H.R. 3082 is the wrong Congress, and no bill
title shows it. `title_citation` reads a leading `P.L. 111-322` or `Public Law
112-8` as that law, in the Congress the citation states, with the same
discipline: a second law refuses; a bill cited after it is its subject (P.L.
119-21's two estimates cite H. Con. Res. 14, the resolution it followed), as a
law cited after a leading bill is (a bill "to amend Public Law 97-435").
spicy-docs reads no table, so the host supplies the map: `law_bills` on
`build_bill_family` and `build_cbo_feed_cost_estimates`, from `laws.law_id` to
`laws.bill_id`. With it `title_bill_id` is the law's bill; without it, or for a
law it does not map, NULL, and such rows are counted apart as "title names a
public law" (6 BILLSTATUS and 7 feed rows over the 108th-119th). A map value
that is no `bill_id`, or a bill of another Congress than the law's (a law is
enacted from a bill of its own Congress), refuses by name. With a map
built from the retained BILLSTATUS `<laws>`, all 13 resolve and three more
rows differ: the 112th feed's P.L. 111-322, and P.L. 119-21's two estimates,
which both routes file under H. Con. Res. 14.

**A blank item titled by a law is a row through the host's `laws` table, and
`found_by` says so** (owner decision 2026-09-28: title-found bills get rows,
and these are found through a law). The 110th's P.L. 110-50 and the 112th's
P.L. 112-8 have an empty `Bill_Number` and a title that leads with the law.
With `law_bills`, `cbo_feed_bills` names the bill that enacted each (110 S. 966
and 112 H.R. 1363, from the retained BILLSTATUS `<laws>`), and each is a row
with `bill_id` that bill. Without the map, or for a law it lacks, the item is
counted as `public_law` and has no row. A map value that is not a `bill_id`
refuses by name (`law_bills`, `not-a-bill-id`). `cbo_cost_estimates` appends
`found_by`, so a reader sees how each link was made: `billstatus` on every
BILLSTATUS row, and on a feed row `bill_number`, `title` or `title_law` (and
`bill_number_title`, above). With
the map, the 110th feed gives 1,464 rows (1 `title_law`) and the 112th 914
(852 `bill_number`, 61 `title`, 1 `title_law`); the 113th's 1,101 have no law
title. `CboFeedBill.found_by` is each item's way, in the order of its
publication ids. `FOUND_BY`, the sealed vocabulary, is spelled once, in
`schemas.cost_estimate_tables`, and `sources.cbo` imports its values.

**The report citations are the bill's own.** A `cbo_feed` row's
`report_citation_count` and `report_citations_json` are those of the bill's
own BILLSTATUS `<committeeReports>`, which the host passes in (the owner
confirmed this source for them); a bill it passes none for publishes NULL.

**The contract changes only by adding.** The grain names CBO's feed beside the
BILLSTATUS document, read for every Congress and merged. `source` adds
`cbo_feed`, reserves `congress_api` and states what a missing 112th-113th row
means, which route a merge keeps and what a feed row elsewhere is.
`bill_id`, `publication_id`, `pub_date`, `description`, `estimate_index`,
`stated_count` and the two citation columns say how a `cbo_feed` row fills
them, `stated_count` drops "usually 1 from the 112th on", which BILLSTATUS
contradicts, and `title_bill_id`, `found_by` and `title_bill_id_rule` are
appended, in that order. No identity, type or existing vocabulary value moves.
A host's dictionary regenerates from the new text. What an importer must
change is in the one list below.

## A cosponsor's `source_xml` is the publisher's bytes

2026-09-28, for the next release. The 0.50.1 review's suggestion. Receipt:
`~/Work/corpora/fork-execution-2026-09-21/cbo-112-113/source-xml/`.

`BillCosponsor.source_xml` was `tostring(item)`, a reserialization. It
re-spelled a self-closed element with a space and cost about 11 microseconds
an entry, the main cost of BILLSTATUS parsing since 0.50.0.
`reading.xml.parse_xml_with_spans` now records, during the one expat parse the
tree already needs, the byte span of every element at a given path, and
`parse_bill_status` slices `billStatus/bill/cosponsors/item` out of the input
bytes `input_sha256` pins.

- A span runs from the element's `<` to just past its own end tag. A
  self-closed element ends with its own tag, because expat reports its end at
  the next token; a `>` inside a quoted attribute is skipped.
- The parser's offset function is released after the parse. It held the
  parser, whose handlers held the tree, and that cycle kept every document
  alive until the cyclic collector ran: 31 s against 25 s over the corpus
  while a caller kept its results, before the fix.

Over the retained corpus (the 113th, 115th and 117th `hr` and 119th `hr` and
`s` zips: 39,147 documents, 506,301 entries), every `source_xml` equals the
item bytes an independent regex tokenizer cuts from the raw document. Nine
entries change value, all in 113 H.R. 4200, where `<middleName/>`,
`<sponsorshipWithdrawnDate/>` and `<gpoId/>` had been re-spelled with a space;
every other entry is byte-identical to before. Parsing takes 21.7 and 20.8 s
against 24.6 and 23.5 s, two interleaved rounds.

| Table | Column | Rows | Change |
| --- | --- | --- | --- |
| `bill_cosponsors` | `source_xml` | 9 of the corpus's 506,301 (113 H.R. 4200) | a self-closed element loses the space before `/>` |

The row's identity is keyed on the input digest, so nothing else moves.

## Every published digest is spelled `sha256:`

2026-09-28, for the next release (owner decision). `tables.digest`, every
capture and every other published digest already use `sha256:` plus the hex
digest. Five published values were bare hex, and each now carries the prefix,
computed by `schemas.tables.digest` over text or `schemas.tables.bytes_digest`
over bytes rather than spelled at each site:

| Table or output | Column | Rule or version |
| --- | --- | --- |
| `house_communications` | `rin_occurrences_json`, each occurrence's `field_sha256` | the occurrence rule moves to `report_nature/shared_rin/2` |
| `section_classifications` | `prompt_hash` | none: see below |
| `bill_summaries`, `diff_summaries` | `content_hash` | none: see below |
| Senate payment review and candidates (`reading.senate_payment_*`) | `input_sha256` | the candidate rule moves to `senate-b-payment-candidates/3`; the retained truth set's digest is re-spelled |
| `comments` | `pdf_extraction_results_json`, each attachment's `sha256` (`sources.mirrulations.DerivedAttachment`) | none: the derived-text selection has no versioned identity |

The prompt versions do not move: they name the prompt text, which did not
change, and a bump would regenerate every summary and classification for a
spelling. spicy-docs stays strict and reads no bare hex (owner decision): the
summary cache (`needs_regeneration`) and the `summary_generated` activity event
compare the values as stored. So a host re-spells its prior rows once, at
merge, before it asks either (the importer list below names the columns); a
compatibility layer that read both spellings forever was built and dropped.
`rin_from_report_nature(occurrences=...)` refuses occurrences that name
another rule or carry another field's digest: they are re-read, which is cheap,
not reused.

Left bare on purpose, each for a reason:

- The 12-character rule-version tokens (`rule_set_version`,
  `link_rule_version`, `estimate_rule_version` and the like). They are
  versions compared for equality, truncated, and name rules rather than bytes;
  re-spelling one would read as a changed rule.
- Readers' own `input_sha256` fields (Federal Register reference data and
  topics, the eCFR authority scan, Unified Agenda scans, the BILLSTATUS codes
  guide, Zyte records). They are an API, not a published column; a consumer
  that publishes one spells it there.
- The sealed document-capture 1.0 schemas' `sha256` values
  (`schemas/document_capture/provenance.py`), which the sealed schemas define
  as bare hex; re-spelling them is a new schema version, not this change.
- Each attempt's `source_sha256` in `documents.pdf_extraction_results_json`
  and `comments.pdf_extraction_results_json`, which spicy-regs' `enrich_pdf.py`
  computes and writes; the prefix belongs there (a host change below). A
  comment's `attachments[].sha256` is different: spicy-regs serializes
  spicy-docs' `DerivedAttachment`, so that digest is prefixed here.

## The Clerk's archive reads whole: the voting-body element, files before 2003, capital months

2026-09-28, for the next release. Receipt:
`~/Work/corpora/fork-execution-2026-09-21/cbo-112-113/clerk-all/`: every House
roll call the Clerk's EVS archive serves, 1990-2026 (22,512 files, each fetched
keyless once and kept gzip-compressed, with `receipt.jsonl`), and the survey
script, which a regex over the raw bytes and `parse_clerk_vote` both run.

**The Committee of the Whole is visible only as an element name.** A Clerk
file names its voting body in `<chamber>` or, on 3,830 files from 2007 on, in
`<committee>`, and both read `U.S. House of Representatives`. The reader kept
`<chamber>` alone, so those votes read `chamber_raw` `None` and nothing
published could tell them apart. Putting the `<committee>` text in
`chamber_raw` would not have helped, because the text is the same; the element
is the fact. `RollCallVote.committee_raw` now keeps `<committee>` verbatim, a
file naming neither element or both refuses (none of the 22,512 does), and
`roll_call_votes` appends `clerk_body_element`: `committee` or `chamber`, NULL
off the Clerk. Of the 3,830, 3,791 are amendment votes, 29 motions for the
committee to rise or calls in committee, 5 rulings of the chair, 3 vacated votes
and 2 House questions. The Clerk calls none of them a Committee of the Whole
vote, so the column states the element, and "Committee of the Whole" stays the
inference it is.

**`member_votes.state` says what `XX` marks, in the file's own terms.** The
Clerk marks the non-voting delegates and the Resident Commissioner `XX` on
2,169 roll calls, in 1993-1994, 2007-2010, 2019-2020 and from 2022 (none in
2021), every one an amendment
vote or a motion in committee, filed under `<committee>` from 2007 and under
`<chamber>` in 1993-1994. The earlier text, from the 118th alone, said
"Committee of the Whole amendment votes": the review found that an inference,
and the archive shows `XX` on `<chamber>` files too.

**Files before 2003 read, keyed by name.** No file of 1990-2002 (7,327) carries
a legislator `name-id`, and every file from 2003 on carries one for each
legislator. The reader refused every file without it, so the archive's first 13
years never read at all. A file with no `name-id` now reads with
`bioguide_id` `None`, and each `member_votes` row keys on `name:` plus the
Clerk's name, the spelling the contract already gave a member a file does not
identify. A file mixing the two forms, a file from the 108th Congress (2003) on
without them, or a file naming one member twice, by name or by bioguide id,
refuses. A `name:` key identifies the row within its roll call, not a person:
the Clerk's labels are last names disambiguated within a Congress, and over
1990-2002 at least 21 name two different members (18 whose state changes,
such as `Allen`, `Schiff` and `Wilson`, and `Jones (NC)`, `McHugh` and `Smith
(WA)` in one state; the second review's `review-2/clerk/names.py`). Nor does
(congress, name, party, state) identify a person: one Congress can seat a
successor of the same surname, party and state. Where the Clerk states
bioguide ids, 5 such keys name two (109th Matsui D-CA, 110th Carson D-IN, 112th
Payne D-NJ, 117th Letlow R-LA, 119th Grijalva D-AZ), and in 1990-2002 the same
shows as a gap inside one Congress (the 105th's Capps and Bono, CA, and the
107th's Shuster, PA; `review-2/round2/clerk/`). The `member_key` docstring,
`member_votes`' contract text and the importer list say so: a host crosswalks
persons on (congress, name, party, state) and the vote date, checked against
each member's service dates, and the key does not move.

**Nine files print the month in capitals.** `3-JAN-1991` on seven Speaker
elections and two other votes of 1991-2003 refused as "not the chamber's own
spelling", though it is the Clerk's. `vote_day` reads a capital month too, and
no other spelling.

**A vote vacated before any position was recorded is a row without members**
(owner decision 2026-09-28). Five files of 2011-2016 (112-1-484, 112-2-327,
113-2-275, 114-1-300, 114-2-44) list no recorded vote, total zero and say in
`<vote-desc>` that the House vacated the vote by unanimous consent ("This vote
was vacated by unanimous consent on 4-Jun-2015."). `parse_clerk_vote` reads
such a file with no member votes, and `roll_call_votes` appends `vote_desc`,
the Clerk's `<vote-desc>` verbatim (13,780 of the 22,512 files state one,
most often the measure's title), so the row states the file's own words; it
has `member_vote_count` 0 and no `member_votes` rows. A file listing no
recorded vote that does not say so, or whose totals are not zero, still
refuses. A vote vacated after its positions were recorded reads as any other:
110-2-640 (2008) lists 433 members and says "Proceedings on Roll Call 640 were
vacated by unanimous consent.", which its `vote_desc` carries. What still refuses is the publisher's own contradiction, one of the
22,512: 2003's Speaker election, whose candidate totals (Hastert 228) disagree
with its member choices (227).

| Table | Column | Rows | Change |
| --- | --- | --- | --- |
| `roll_call_votes` | `clerk_body_element` (appended) | every House row read again | `committee` or `chamber`; NULL on Senate, linkage-only and earlier rows |
| `roll_call_votes`, `member_votes` | every column | the 101st-107th Congresses, 7,327 roll calls and their members | newly readable; members key `name:` with `bioguide_id` NULL |
| `roll_call_votes` | `vote_day` | the nine capital-month files | newly read |
| `roll_call_votes` | `vote_desc` (appended) | every House row read again | the Clerk's `<vote-desc>`; NULL on Senate, linkage-only and earlier rows |
| `roll_call_votes` | every column | the five vacated votes | newly readable, with no `member_votes` rows |
| `member_votes` | `state`, `member_key` | none | the descriptions only |

## What an importer must change for the CBO, `source_xml`, digest and Clerk entries

Collected from the four entries above. The release's other entries carry their
own lists; the 0.52.0 entry at the end points to each.

- `cbo_cost_estimates`: **host builds feed rows for every Congress**, 108th-119th,
  with `interpretation.bill_family.build_cbo_feed_cost_estimates(feed,
  congress, report_citations=..., law_bills=...)` (the new `source` value
  `cbo_feed`), passing each bill's own BILLSTATUS report citations, and merges
  them with the BILLSTATUS rows through `merge_cbo_cost_estimates`, which keeps
  the BILLSTATUS row where both state one bill and publication. That adds all
  of the 112th-113th's rows and 33 elsewhere and changes no BILLSTATUS row. A
  merge keys on `(bill_id, publication_id)`, never the publication alone: one
  publication can stand under two bills.
- **Host supplies `law_bills`**, `laws.law_id` to `laws.bill_id` from its
  `laws` table, to both `build_cbo_feed_cost_estimates` and
  `build_bill_family`; without it a title leading with a public law leaves
  `title_bill_id` NULL and a blank item titled by a law has no row. A map value
  that is no `bill_id`, or a bill of another Congress than the law's, refuses.
- `cbo_cost_estimates` appends `title_bill_id`, `found_by` and
  `title_bill_id_rule`, in that order. `found_by` is a sealed, additions-only
  vocabulary (`billstatus`, `bill_number`, `title`, `title_law`,
  `bill_number_title`);
  `title_bill_id_rule` is `cbo_title_citation/1` on every row. A host rebuilds
  or backfills its prior rows with them (`billstatus` on every
  `billstatus_bulk` row). `report_citation_count` and `report_citations_json`
  are NULL on a `cbo_feed` row shaped without the bill's BILLSTATUS record.
  The Congress.gov reader of the unreleased branch is gone; nothing released
  used it.
- `bill_cosponsors.source_xml`: nine rows of 113 H.R. 4200 change on the next
  read. `parse_bill_status` refuses a document in any encoding but UTF-8 by
  name (every BILLSTATUS measured is UTF-8).
- Digests: `house_communications.rin_occurrences_json` (`field_sha256`, rule
  `report_nature/shared_rin/2`), `section_classifications.prompt_hash`,
  `bill_summaries.content_hash`, `diff_summaries.content_hash` and the Senate
  payment review's and candidates' `input_sha256` (rule
  `senate-b-payment-candidates/3`) are spelled `sha256:`, and spicy-docs
  compares them strictly. **Host step, once, at merge**, before the summary
  cache or the activity events read them, with no permanent compatibility
  layer: prefix `sha256:` to every prior bare value of
  - `section_classifications.prompt_hash`;
  - `bill_summaries.content_hash` and `diff_summaries.content_hash`;
  - `content_hash` in the `event_data_json` of prior `summary_generated`
    `public_activity_events` (`schemas.activity_events` compares the summary
    rows strictly, and the events repeat the value);
  - any retained payment-candidate or review `input_sha256`;
  - `documents.pdf_extraction_results_json[].source_sha256` and
    `comments.pdf_extraction_results_json[].source_sha256`, which spicy-regs'
    `enrich_pdf.py` writes (a host change: it writes `sha256:` from now on);
  - `comments.pdf_extraction_results_json[].attachments[].sha256`, which now
    arrives prefixed from spicy-docs' `DerivedAttachment`.

  Stored RIN occurrences are re-read under the new rule rather than re-spelled.
- `roll_call_votes` appends `clerk_body_element` and then `vote_desc`;
  `RollCallVote.committee_raw` is a new last field; a Clerk file naming
  neither or both body elements refuses.
- House roll calls of 1990-2002 now read. **Host backfill:** fetch and shape
  the 101st-107th Congresses' 7,327 Clerk files into `roll_call_votes` and
  `member_votes`; their member rows key `name:` plus the Clerk's name
  (`Ackerman`) with `bioguide_id` NULL, as the contract's `member_key` already
  allows. That key identifies a row within its roll call, never a person: at
  least 21 labels of 1990-2002 name two different members, and one Congress
  can seat a same-surname, same-party, same-state successor (109th Matsui,
  110th Carson, 112th Payne, 117th Letlow, 119th Grijalva; the 105th's Capps
  and Bono, the 107th's Shuster), so a host crosswalks persons on (congress,
  name, party, state) and the vote date, checked against each member's service
  dates, and the key does not move. The same backfill re-reads the nine capital-month files for
  `vote_day`, and the five vacated votes of 2011-2016, which now publish a
  `roll_call_votes` row (`vote_desc` states it, `member_vote_count` 0) and no
  member rows. A Clerk file from the 108th Congress on without name-ids now
  refuses (none measured).
- A host's data dictionary regenerates from the changed descriptions
  (`cbo_cost_estimates`, `bill_cosponsors.source_xml`,
  `house_communications.rin_occurrences_json`, the model tables' hashes,
  `roll_call_votes`, `member_votes.state` and `member_key`).
- New helpers: `reading.xml.parse_xml_with_spans`,
  `sources.cbo.title_citation` (a bill or a `PublicLawCitation`),
  `bare_number_bill`, `feed_item_pub_date`, `CboFeedBillError`, `LawBills`,
  `law_bill`,
  `schemas.tables.bytes_digest`, and `schemas.cost_estimate_tables`'
  `FOUND_BY_*` and `TITLE_BILL_ID_RULE`. `sources.cbo` imports
  `sources.congress.bill_status` for `BillIdentity` and
  `schemas.cost_estimate_tables` for the `found_by` spellings, and
  `interpretation.bill_family` imports `sources.cbo`.

## congressionalrecord is a pinned fork dependency, not a port

Adopted 2026-09-28 with [Congressional Record speech
turns](sources/congressional-record-speeches.md). The owner's decision that day:
fork the @unitedstates parser in mikewolfd's organization, make the fix, pin it
here, open the upstream pull request, and write the adapter.

SpicyDocs depends on [`congressionalrecord`](https://github.com/unitedstates/congressional-record)
behind the optional `record-speeches` extra, installed from
[mikewolfd/congressional-record](https://github.com/mikewolfd/congressional-record)
at the commit `PARSER_PIN` names, on its `spicy-docs-pin` branch, through
`[tool.uv.sources]`.
`sources/congress/record_speeches.py` is an adapter over it; nothing here
reimplements its segmentation.

**Why a fork rather than upstream.** Upstream cannot be installed and used as a
library at `84a5af4`: nothing is published under the name on PyPI, and a wheel
built from its main branch ships only the top-level package, without the
`govinfo` subpackage the parser lives in. It also returned a partial parse as
if it were complete, and it required dependencies the parser never imports:
its PostgreSQL writer's stack, and `numpy` and others nothing imports. The pinned branch carries
[unitedstates/congressional-record#92](https://github.com/unitedstates/congressional-record/pull/92),
which fixes the packaging, admits a speaker line indented up to three spaces
and adds `parse_status`/`parse_error`, and
[#93](https://github.com/unitedstates/congressional-record/pull/93), which
declares what the package's non-PostgreSQL modules import (the parser, the
downloader and the schema) and moves the PostgreSQL writer's dependencies
behind a `postgres` extra this repository does not install. After the
adapter's review it also carries
[#94](https://github.com/unitedstates/congressional-record/pull/94) -- a
line-kind table per document, `None` for absent values, `CRParseError` for an
unreadable header, an accessId index -- and merges
[#90](https://github.com/unitedstates/congressional-record/pull/90)'s speaker
pattern, so the adapter no longer serializes parses or maps `"None"` strings.
Fork-only commits pin the build backend so a vendored wheel is reproducible
and prune the tests from the sdist.
The adapter refuses any build whose parser files are not the pin's, by the
digests the installed `RECORD` states, so the pin cannot silently regress to
one that hides a partial parse.

**Why not a port.** The segmentation rules -- speaker, recorder, clerk, title
and rule lines, the MODS speaker table -- are upstream's accumulated knowledge
of how the Record prints, and a copy would stop receiving its fixes. The adapter
adds only what a library consumer here needs: bounded inputs, the bounded MODS
read before upstream's, refusals in this package's terms, completion status,
and line spans.

**Consequence for the gate.** `./scripts/check` syncs every extra, so a cold
environment clones the fork the first time it resolves; uv caches the checkout
and `--frozen` runs after that are offline. With #93 on the pin, the extra
installs only what those modules import, with `beautifulsoup4` held at the
version the `html` extra pins; the source page lists the clean-install set and
what a host that vendors the wheels declares.

**When to drop the source.** When upstream merges #92, #93, #94 and #90 and
publishes a release, delete the `[tool.uv.sources]` entry and pin that release in the
extra. Until then the git revision names a commit on a fork branch; move it
only with `PARSER_PIN` and the lock, which a test holds together, and rebuild
the vendored wheel by the rule on the source page.

**Speech turns are parsing, not acquisition.** The adapter reads bytes a caller
already retained -- the granule body and its own MODS or its issue's package
MODS, from the [GovInfo body routes](sources/govinfo-bodies.md) -- and makes no
request. Which granules to read, and where the turns are published, stay with
the host.

## A Record issue's package id is its first book's stem

2026-09-28, from the independent review of the Congressional Record speech-turn
adapter. `record_issues.package_id` is the GovInfo CREC package an issue is
published as, the id the speech-turn adapter's `package_id` joins on. The rule
came from the [legislative data map](research/legislative-data-map-2026-09-18.md)'s
`record→package` edge and landed with the index tables (`c3b1d42`): the
issue's own whole-issue link names the package by its file stem, so no package
id is inferred from a date. That reason stands.

What was wrong is which link. An issue printed in several books lists one PDF
per book in `fullIssue.entireIssue`, each with its `part`; a later book's stem
is `-bk{N}` of the same package, and the list is not in part order. The rule
read the first link, so an issue whose later book was listed first published a
package id GovInfo does not have. `entire_issue_url_stem/2` reads the link
whose `part` is `1`, and is NULL where the detail lists no part 1 or lists it
under two stems. The map's own sample showed it: its 18 of 20, with issues
205 and 208 failing on HTTP 404, were two of the seven rows below.

### Published values that change

Measured on the live generation (`record-issues` family, artifact
`sha256:7bb2005c62c489cff55f53a80f53e0b904703a70a92ff55ddd9c966c3022f81f`,
`record_issues.parquet` `sha256:da41732c…c82f`), fetched and re-shaped from
each row's own `entire_issue_json` on 2026-09-28. Every row has a detail, and
every detail lists exactly one part-1 link. 361 rows keep their `package_id`.
Seven change, and for each the keyed GovInfo package summary of the published
id answers 404 while the new id's answers 200 with a title naming the same
volume and issue:

| Volume | Issue | Date | Published `package_id` | Becomes |
| --- | --- | --- | --- | --- |
| 171 | 45 | 2025-03-11 | `CREC-2025-03-11-bk2` | `CREC-2025-03-11` |
| 171 | 57 | 2025-03-31 | `CREC-2025-03-31-bk2` | `CREC-2025-03-31` |
| 171 | 86 | 2025-05-21 | `CREC-2025-05-21-bk2` | `CREC-2025-05-21` |
| 171 | 174 | 2025-10-21 | `CREC-2025-10-21-bk2` | `CREC-2025-10-21` |
| 171 | 205 | 2025-12-08 | `CREC-2025-12-08-bk2` | `CREC-2025-12-08` |
| 171 | 208 | 2025-12-10 | `CREC-2025-12-10-bk2` | `CREC-2025-12-10` |
| 172 | 5 | 2026-01-08 | `CREC-2026-01-08-bk3` | `CREC-2026-01-08` |

`package_id_rule` moves from `entire_issue_url_stem` to
`entire_issue_url_stem/2` on every row with a package id, because values changed
under the rule. The identity `(volume, issue)` and every other column are
unchanged. A host sees the new values when it re-shapes an issue: spicy-regs
reads only the details its published table lacks and merges on `update_date`
(`build_index_table`), so a held issue keeps its old row until its detail is
read again or the table is rebuilt. **Host step:** rebuild `record_issues` once,
or re-read the seven details above. Receipt:
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/review-fixes/record-issues/`
(`measure.py`, `measure.json`, `changed.csv`, the package summaries).

## Comments carry the agency's submitter class and campaign count

Unreleased, 2026-09-28; the owner approved carrying both fields in the fork's
`comments` table. `schemas.regulations` extracts Regulations.gov `subtype` and
`duplicateComments` into `comments.subtype` and `comments.duplicate_comments`,
as stated, appended last in that order. The `comments` contract types
`duplicate_comments` `INTEGER`; every other column stays VARCHAR. NULL means the
record did not state the field, stated it null, or the host has not read it; a
stated 0 stays 0. The extract never coerces a count: anything but an int (not a
bool) from 0 to 2**31 - 1 raises, which a reader turns into an unreadable
record, rather than reaching a host's integer column that would turn `"5"` into
5 or `true` into 1. The comment validator admits the same range, and admits
`pageCount` only as an int in that range; its JSON schema, sealed into
released evidence, is unchanged.

Why: `comments` counts posted records. An agency posts one record for a
mass-mail campaign, and some classify submitters only in `subtype`. EPA's PFAS
drinking-water docket (EPA-HQ-OW-2022-0114) has 1,629 posted records; their
`duplicateComments` sum to 53,707, 52,086 of them on 23 `Mass Mail Campaign`
records. EPA's response to comments counts about 122,200 received, so the sum
is the agency's posted accounting, not its total. A stratified sample of 5,945
Mirrulations comment objects (179 agencies, 2026-09-28) stated
`duplicateComments` on every record: 0 on 5,281, 1 on 660, more on 4. Only EPA
and a few others use it as a count; 0 is the default elsewhere. `subtype` was
stated on 2,041 and NULL on 3,904; most agencies state a generic label. Submitter
classes are mostly EPA's, but not only: the spicy-regs re-read of every comment
finds `Company/Organization Comment` at AMS (188), COE (171), EEOC (11), DOD (4)
and ATBCB (3), `Member of Congress` at AMS (20), and `Mass Mail Campaign` at
BSEE (1,077) and CMS (14), among the agencies it had read (ACF to EPA,
2026-09-28). The receipt is
`supply-2026-09-02/receipts/comments-subtype-duplicates-2026-09-28/` under
`~/Work/corpora`.

**Both are appended, after the host's `pdf_extraction_results_json`.** Every
new column is appended ([tables](tables.md)), as `bill_sections.congress` was.
The 0.50.0 ruling ([above](#three-hosted-tables-take-new-columns-mid-table))
kept an order that was already live; it is not a rule to insert. Appending
keeps every live column at its position in the fork's mirror, and it matches
the host's catalog, whose `ADD COLUMN` appends. A first draft placed them
after `category`; the release owner's review moved them. The
extract's columns therefore no longer all precede the host's: the test now
holds each table to the extract's columns in the extract's order plus the named
host columns (`_REGULATIONS_HOST_COLUMNS`).
`tests/test_table_contracts.py` appends both as NULL to the retained published
comment rows, which predate them (`_UNPUBLISHED_REGULATIONS_COLUMNS`), and
refuses a pending column that is not last; empty that entry when the host has
republished and the rows are re-read. The
`public_tables` comment profile takes its columns from `COMMENT.schema`, so it
gains both, as it gained the reference columns without moving its ids. Its shape
changed, so both ids move: schema `public-comments:1.1` and projection `1.1`
(the Federal Register precedent [above](#federal-register-public-tables-preserve-composite-identity)
kept its schema id only because its columns did not change).

### What an importer must change

- The `comments` contract is now typed (`duplicate_comments` INTEGER), so
  DocSpec's `_contract_types` check applies to it: a published comments member
  must carry that column as INTEGER, or admission refuses. The fork's mirror
  exports it typed.
- A host adds `subtype` and `duplicate_comments` last, as nullable columns; rows
  read before them stay NULL until re-read.
- The comment extract raises on a malformed `duplicateComments`; a host that
  calls it outside a reader must treat the raise as an unreadable record.
- `KeyedPayload` carries `etag` and `size`; `_download_record` returns the GET's
  `DownloadedObject` with the payload.
- The public-comments profile ids moved to `public-comments:1.1`, projection
  `1.1`; a reader requiring 1.0 refuses the new shape.

## A keyed Mirrulations payload carries its GET's ETag and size

Unreleased, 2026-09-28. `KeyedPayload` gains `etag` and `size`, from the same
GET as `last_modified`, so a caller that keeps only fields of a record can still
say which bytes it read without a listing or the body. The spicy-regs comment
re-read (owner decision 2026-09-28, option a) keeps them per object. Both are
optional fields with defaults; `_download_record` now returns the GET's
`DownloadedObject` with the payload, and `download_and_parse` is unchanged.

## 0.52.0: CBO for every Congress, native legal references, the Congressional Record, comment fields and GAO's listing

2026-09-28. Five branches, each reviewed independently and re-reviewed after
its fixes, merged without rebasing so each keeps the reviewed commits. Receipts
are under `~/Work/corpora/fork-execution-2026-09-21/`: each branch's review is
its `REVIEW.md` (`native-refs-contract/`, `cbo-112-113/review-2/`,
`record-speeches-review/rereview/`, `comments-fields-review/`,
`gao-month-in-review-review/`), and the release's gate log and wheel are in
`spicy-docs-0520/`.

What it carries, by entry above:

- **The native legal-reference tables have contracts:** both native tables
  under contract, the interpretation moved here from RefSpec, `json_column`, and
  observations spelled `at-joined/1`.
- **CBO's own feed is read for every Congress:** feed rows for the 108th-119th
  (the merge keeps BILLSTATUS), `title_bill_id` with `title_bill_id_rule`,
  `found_by`, and a bare number read through its title when the two agree.
- **A cosponsor's `source_xml` is the publisher's bytes.**
- **Every published digest is spelled `sha256:`,** with rule bumps where a rule
  names the spelling and a one-time re-spell of the host's prior rows.
- **The Clerk's archive reads whole:** the voting-body element, files before
  2003 with name-keyed members, capital months, and the five votes vacated by
  unanimous consent as vote rows without members (`vote_desc`).
- **congressionalrecord is a pinned fork dependency, not a port,** and **a
  Record issue's package id is its first book's stem**
  (`entire_issue_url_stem/2`).
- **Comments carry the agency's submitter class and campaign count:**
  `subtype` and `duplicate_comments`, appended, never coerced, and the
  public-comments profile ids at 1.1. The `comment_attributes` contract is not
  in this release: its column order is fixed only once the full census of
  comment fields is folded in, and it ships in the next release.
- **A keyed Mirrulations payload carries its GET's ETag and size.**
- **GAO's own listing:** the Month in Review and Annual Index reader, the class
  rule with every major-rule report 2009-2026 as a product, and
  `ZyteTransportError` for a provider read that breaks.

The owner's decisions of 2026-09-28, each recorded in its entry: CBO feed rows
for every Congress; the five vacated votes as rows without members; a bare CBO
number read through an agreeing title; the 1994 Record read by chamber section;
the dropped marker-line prose fixed in the parser fork (upstream #94); email,
phone and fax left out of the future `comment_attributes`, by attribute; and
every GAO major-rule report in `gao_reports`, with the 1996-2008 reports a gap
that a Congressional Review Act listing reader will fill after this release.

What an importer must change: each entry's own list. They are under the GAO
listing entry, the native legal-reference tables entry ("What changes for an
importer" and "What spicy-regs must change to adopt it"), the importer list for
the CBO, `source_xml`, digest and Clerk entries, the two Congressional Record
entries (the host's wheel declaration and the `record_issues` rebuild), and the
comments entry.

## Comments get an attribute table: `comment_attributes`

Unreleased, 2026-09-28; the owner ruled it in, for the same 0.52.0 release as
the comment columns above. `comment_attributes` is to `comments` what
`document_attributes` is to `documents`: one row per comment, keyed
`comment_id` spelled `value/1`, referencing `comments`, built by the same
`_attribute_contract` and projected by `project_comment_attributes`, the one
spelling spicy-regs' build and DocSpec share. Columns follow decision 66's
naming and decision 67's typing: `withdrawn` BOOLEAN, `page_count` INTEGER,
`postmark_date` TIMESTAMPTZ, `display_properties_json` in `json_column`
spelling, everything else VARCHAR as stated.

**Contact details follow decision 66, less `email` and `phone`** (owner,
2026-09-28). `address1`, `address2`, `city`, `state_province_region`, `zip`,
`country`, `fax` and `submitter_rep` are published. `email` and `phone` are
left out on purpose: documents state neither, so decision 66 never ruled on
them, and on comments they are private individuals' contact details,
bulk-queryable once published, with little analytic value.

Left out, as `COMMENT_ATTRIBUTES_LEFT_OUT` lists, and the thin table's own
attributes (what `COMMENT.extract` reads; a test derives the set by changing
each attribute and watching the extracted row):

| Reason | Attributes |
| --- | --- |
| Private contact details (owner ruling) | `email`, `phone` |
| Never stated | `field1`, `field2`, `submitterRepAddress`, `submitterRepCityState` |
| Constant | `openForComment` (false) |

Unlike documents, `withdrawn`, `reasonWithdrawn` and `fileFormats` are
columns here: the thin `comments` table carries none of them (its
`attachments_json` comes from the record's `included` attachments, while
`fileFormats`, as `file_formats_json`, lists renditions of the comment's own
content file).

"Never stated" and "constant" are measured on the spicy-regs re-read of every
comment: on the first 4,368,949 objects read, `restrictReason` (25),
`restrictReasonType` (22) and `fileFormats` (4) are stated after all, so they
are columns, which the 5,945-comment sample had missed; `openForComment` is
false on all of them. Receipts under `~/Work/corpora/supply-2026-09-02/receipts/comments-full-reread-2026-09-28/comment-attributes/`:
`sample_census.json`, `partial_census.json`, and `project_live_sample.json`,
where `project_comment_attributes` projected every one of the 5,945 live
sampled records with no refusal. The full read re-measures; an attribute
stated there after all becomes an appended column.
