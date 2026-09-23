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
  installed `rulespec-artifacts==1.1.1` (1.0.14 adopted 2026-09-21; 1.1.0 on
  2026-09-22 adds only opt-in DocumentCapture v2; 1.1.1 ships its repaired
  platform fixtures); no fallback copy
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
span_start)`, and the span is in it because the span is the yield.** The
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
would have made an import cycle. On this branch the lower-casing grammar does
not exist yet. `document_citations` still keys through `citations.py` rule 001,
which keeps the printed case. The grammar that lower-cases is B4's
`citation_grammar._usc_section`, which has its own `_DASH_SPELLINGS`. When B4
lands, its grammar should fold through `usc_section_key` and `DASH_SPELLINGS`
so that only one fold remains.
