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
  are vendored bytes pinned by digest, not a second implementation, and they
  go away at the next wheel bump.
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
