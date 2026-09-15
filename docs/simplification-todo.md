# Work status

- [x] **I01 — Combine the FEC and XML/CFR source work.** Local `main` combines
  FEC `e7fa9da` and XML/CFR `1c2c95c`, preserving both families and their task
  status. SpicyDocs **0.7.0** passed 1,428 repository tests (two opt-in checks
  deselected), lint/format, lock and 330 tests against the installed core wheel.
  Both CLI commands and FEC JSON resources work without optional HTTP/table
  packages. Retained metadata checks passed; source captures remain byte-exact.
  Architecture and both independent code reviews approved. Wheel, checks and
  reviews: `~/Work/corpora/supply-2026-09-02/receipts/xml-fec-merge-2026-09-12/`.
  Source merge `d9c312c` is pushed to `fork/main`. Downstream wheel adoption
  remains separate.

**SpicyDocs 0.8.1 (2026-09-14):** 2,280 repository tests; 80 of 88 source and
transport modules import on the core wheel; 2,225 tests pass against the
installed wheel with extras (same six explained failures as 0.8.0);
`spicy-docs-list` runs from the installed package. Wheel SHA-256 `4b7d188181e151dccda6c1d15c5d46594121894dc760414f17fe83d54e4886f0`.
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/release-0.8.1-2026-09-14/`.

**SpicyDocs 0.8.0 (2026-09-14):** 2,247 repository tests (two opt-in checks
deselected), lint/format and lock; the core wheel imports every public module
without httpx; 2,192 tests pass against the installed wheel with extras (six
failures are repository-layout checks and one deselected opt-in replay). Wheel
SHA-256 `5bb8e5f1f2d64150b77caef4fc4a1f22af1eb4b59f510483df2d402a48c32439`. Receipt:
`~/Work/corpora/supply-2026-09-02/receipts/release-0.8.0-2026-09-14/`.

**The source-fidelity and CFR example tasks below are complete locally.**
S21/S31 remain conditionally deferred. [SpicyRegs SR04](../../spicy-regs/PLAN.md#sr04)
owns the remaining CourtListener reader adoption. The merged source changes
are on `fork/main`; receiving changes remain on their own branches.

**Merged simplification: 23 local items complete; two conditionally deferred.**
Six original items moved to their implementation owners. A moved task is not a
completed task; follow the receiving backlog for its status.

## Shared parsing and metadata capture

**Goal (2026-09-14):** remove as much duplicated behavior and maintenance as
practical across SpicyDocs, SpicySearch, RefSpec, Rulespec, DocSpec and SpicyRegs.
Parsing and metadata capture move to SpicyDocs; other shared behavior goes to its
existing owner. Consumers adopt wheels and delete their copies. The
[ownership decision](source-ownership.md) defines the package responsibilities. The
[port-candidate swarm](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/port-candidates-swarm-2026-09-14.md>)
is one input to this effort; it inspected SpicyDocs `3386648`. The deeper
[reader inventory](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/parsing-consolidation-2026-09-14/remaining-inventory.md>)
and [Rulespec inventory](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/parsing-consolidation-2026-09-14/rulespec-inventory.md>)
add current callers, behavior differences and migration checks. An inventory
finding is not a completed port.

- [x] **PAR01 — Inventory duplicated behavior across the codebases.** The swarm
  and follow-up reviews cover source readers, metadata, format extraction,
  serialization, evidence helpers and dependencies across all six repositories.
  PAR11–PAR19 record the additional findings. This is an initial implementation
  inventory; each port still requires current caller and fixture checks.
- [x] **PAR02 — Share Federal Register subject-block parsing.** Move literal XML
  and text List of Subjects readers and their regression fixtures; add the missing
  publisher text acquisition path. Preserve window bounds, printed terms and
  source associations. Vocabulary resolution and scoring remain downstream.
- [ ] **PAR18 — Search retained DocSpec data without another catalog copy.**
  Engine reads a selected catalog revision and retained results through DocSpec's
  public wheel APIs, then builds its disposable native index. Honor current
  membership and removals; raw file discovery is not a catalog reader. Map the
  fields needed for search; require no intermediate Search-shaped Parquet catalog,
  metadata segmentation or repeated acquisition. Preserve source IDs, versions,
  dispositions and input references. Retain optional Search enrichment once in
  DocSpec, linked to its inputs; reuse the current Core model rather than extending
  the older segment-only runner. Qualify the needed provider wheel APIs before
  claiming that workflow works. **Done when:** installed-package checks reuse
  retained inputs, retrieve expected records and refuse changed inputs. Create no
  additional permanent catalog/body dataset; permit bounded disposable build
  staging only where the native reader needs it. Declare which metadata and
  retained results are searchable. [Engine EC00](../../spicyengine/PLAN.md#ec00)
  owns implementation.
  **Status:** direct retained-state search is implemented and qualified locally
  in Engine 0.2.0 using the DocSpec 0.4.0 wheel. Installed-package native checks
  cover selected membership, replacements/removals, exact parsed values, scalar
  and nested JSON, shared occurrences and changed-input refusal. Inline values
  require no staging; the JSON content-reference fixture needed 134 temporary
  bytes, deleted after building. No permanent catalog/body copy is produced.
  Generic scalar values and explicitly selected fields are searchable; no agency
  or legal interpretation is inferred. Optional Search enrichment retained and
  reused through current Core operations remains open in Engine EC02.
  Local commits: Engine `3b2b537` on `codex/docspec-catalog`; DocSpec reader
  `71386d4` and test correction `9636521` on `codex/direct-core-reader`.
  These implementation branches have not been merged or pushed.
  Evidence is under `receipts/parsing-consolidation-2026-09-14/par18/direct-core/`.
  Superseded prototypes remain in `abandoned-old-index/` and `abandoned-catalog-copy/`.
- [ ] **PAR19 — Simplify Engine around indexing and retrieval.** Retire the
  old exporter and link aliases after the direct DocSpec route works. Reuse owner
  readers for agency/reference meaning and shared search definitions. Keep only
  search/display data and source references in native storage where bounded
  DocSpec record lookup can replace the full stored record. Simplify per-request
  validation and database transport while preserving safe index replacement,
  interrupted-build recovery and bounded results. Keep the local demo useful.
  [Engine's plan](../../spicyengine/PLAN.md) owns these changes; static review is
  not implementation or performance evidence.
  **Status:** old exporters, format readers, copied normalization and domain
  policies are removed in the local Engine branch. Eight native search/reference
  fields replace the stored full record; exact details come from DocSpec. Search
  passes after native restart with source mounts removed. The demo, actual browser
  checks, installed wheel and 56 Python checks pass; independent review has no
  remaining runtime blocker. Database-client replacement and storage/lookup
  measurements remain open. Each original-record read still rechecks its selected
  source, so this is not a latency improvement claim.
- [ ] **PAR03 — Share U.S. Code structure and reference readers.** Consolidate
  section/chapter/subsection enumeration, annual itempath/usckey reading, USLM
  reference occurrences and ancestor-attributed source-credit observations.
  Preserve raw spelling, ranges, stubs and unmatched text; leave enactment
  selection, citation resolution and legal-status verdicts downstream.
- [ ] **PAR04 — Capture CFR metadata once.** Add per-part authority-note text,
  the eCFR agency roster and the Archives subject-index reader. Preserve stated
  labels, malformed entries and provenance without near-match corrections.
- [ ] **PAR05 — Complete Unified Agenda field mapping.** Reuse the existing XML
  reader for CFR references, legal authority, timetables and additional information;
  preserve repeated fields and raw text with their source locations.
- [ ] **PAR06 — Share publisher code and roster readers.** Consolidate Federal
  Register agencies, documented enums and topics, plus BILLSTATUS guide tables.
  Preserve source versions, unknown values and open-list semantics; keep vocabulary
  reconciliation and record-level interpretation in the consuming products.
- [ ] **PAR07 — Add one GovInfo PREMIS reader.** Combine the useful prior parsers
  on bounded XML scanning; retain file names, algorithms, digests and entries
  without fixity. Compare selected captured bytes with an unambiguously matched
  publisher entry and test real package shapes. Report consistency, not authenticity.
- [ ] **PAR08 — Qualify each provider and receiving change together.** Build a
  pinned wheel, run the named consumers outside source checkouts, and compare
  source facts and evidence against retained fixtures. Record intentional fixes
  separately from parity; update receiver dependency pins and public API examples.
- [ ] **PAR09 — Remove the replaced implementations.** Track adoption separately
  for every named consumer. Delete duplicate implementations,
  fixtures made redundant, compatibility wrappers and dead helpers after checks;
  retain regression cases and useful evidence. Record any remaining copy's reason.
- [ ] **PAR10 — Consolidate shared support in its owning package.** Use PAR01's
  evidence to replace duplicate helpers, models and validators alongside each
  migration. Reuse Rulespec Artifacts for its encoding/storage responsibilities
  and DocSpec for its dataset/processing responsibilities. Assess reusable
  interpretation code under its own product owner. Keep necessary differences
  explicit; avoid creating a catch-all utility package or another layer of wrappers.
- [x] **PAR11 — Reuse Rulespec's digest and source-interval helpers.** Local
  Rulespec commit `8ec1417` removes two duplicate digest/encoding functions and
  the second native XML interval index. All active callers use existing Core
  helpers and `documents.source_slicer`. Known-byte and native interval/XPath
  regressions plus the full Extrapolator suite passed: **713 tests**. Independent
  review approved with no open findings.
- [ ] **PAR12 — Share PDF page reading across three consumers.** Add the needed
  optional SpicyDocs backend and adopt it in DocSpec, SpicyRegs and RefSpec's GAO
  readers. Compare actual pypdf output before changing engines. Preserve blank
  pages and raw text; make encryption, failed-page and whitespace policies
  explicit. Retain each consumer's representation and interpretation work.
- [ ] **PAR13 — Share mapped XML/HTML text reading.** Consolidate RefSpec and
  DocSpec source parsing in SpicyDocs. Preserve named layout profiles, Unicode
  character versus original-byte positions, inserted text, entities, XPath,
  attributes and table boundaries. Reuse bounded scanning; qualify both
  receivers' real fixtures before deleting their readers.
- [ ] **PAR14 — Share source JSON decoding and record positions.** Reuse one
  SpicyDocs decoder with explicit integer, Decimal and finite-float policies.
  Preserve duplicate-key/non-finite refusals and exact record spans. DocSpec
  retains segment construction; Rulespec Artifacts retains artifact encoding.
- [ ] **PAR15 — Move image-header observations into SpicyDocs.** Have DocSpec
  adopt a core-only PNG/GIF/JPEG header reader. Distinguish stated header
  dimensions from successful image decoding and oriented display geometry;
  preserve truncated/unsupported results without requiring Pillow.
- [ ] **PAR16 — Reuse Rulespec Artifacts in Rulespec's v2 release tools.** Delete
  duplicate canonical encoding/admission logic after checking release bytes,
  Unicode key order, integer bounds, duplicate keys and refusal cases. Keep
  release-specific identities and validation. Preserve the separately named
  finite-float encoding used by other Rulespec products.
- [ ] **PAR17 — Replace Rulespec's manual URI encoder with the standard library.**
  Keep the public URI/fragment API and verify exact Unicode, percent, slash and
  invalid-surrogate behavior before deleting the byte loop.

CourtListener receiver adoption remains [SpicyRegs SR04](../../spicy-regs/PLAN.md#sr04).
Do not create another provider reader. The Rulespec FAM preparation script has
one known consumer; move it only when a supported source workflow or second
consumer makes the move useful. Preserve its declared ISO-8859-1 encoding.

**PAR02 is complete through its named receiver.** SpicyDocs `dadd1d6` supplies
the shared reader and explicit publisher-text acquisition. SpicySearch `df5a19e`
adopts its 0.9.0 wheel and deletes the old reader bodies. Its combined 741-line
module is now an 80-line resolver plus the 337-line shared provider. The 21
transferred parsing functions and constants retain their original behavior;
27 source regression cases moved to the provider, with one positive XML case
added during review. No parser forwarding wrappers remain.

The same receiving commit uses DocSpec's public admitted-catalog API and
Rulespec's canonical encoding/batch framing. It removes the obsolete SpicyRegs
test wheel and expected-failure markers. Ordinary dependencies now align
SpicyDocs **0.9.0**, DocSpec **0.3.2** (`2e333de`), RefSpec **0.1.0.dev1**
(`564e760b`) and Rulespec Artifacts **1.0.12**. DocSpec's optional provider
installation works too; its changes remain on `codex/par01-arrow-alignment`.

Provider, receiver and dependency reviews approved. SpicyDocs' full suite and
installed core/acquisition checks passed, including the added XML regression.
DocSpec's full suite and installed-wheel checks passed. SpicySearch's final
clean-commit suite, lint, package and source-to-catalog-to-search checks passed
after test-only correction `6a3b8b3` updated an obsolete landing-page assertion.
The Search runs establish functional results, not performance measurements.
One live historical text capture passed; no population coverage is claimed.

PAR08/PAR09 are complete for this family and stay open for later ports. Existing
fidelity/carrier reports need regeneration under the new two-module identity
before population use. PAR18 remains unqualified by these catalog checks.
Commits and wheels are local; nothing from this iteration was pushed or published.
Exact checks, module counts, hashes, reviews and limitations are retained in
`~/Work/corpora/supply-2026-09-02/receipts/parsing-consolidation-2026-09-14/`.

Work by source family or shared capability: identify callers, select or improve
one implementation, qualify its wheel and receivers, then delete replaced code.
PAR02–PAR07 record provider delivery; PAR08/PAR09 record receiving completion.
PAR10 applies throughout. Record before/after implementation counts, migrated
callers, removed support code and any new adapters with each completed change.
Additional candidates found by PAR01 receive named tasks before migration.
DocSpec retains dataset selection, execution history, reuse and comparison;
source-campaign replacement remains the separate S21 decision.

## PDF/image extraction

- [x] **PDF01 — Provide a unified API with injected extraction components.**
  `DocumentExtractor` accepts a reader and page strategy; OCR/vision strategies
  accept a recognition backend. Native PyMuPDF, RapidOCR, Apple Vision,
  LightOnOCR/GLM through MLX, and single/multi-turn Gemini are available as
  optional adapters, including native plus selected regions. Results separate
  source metadata, body blocks and raw observations; failures preserve completed
  regional observations. The [API guide](pdf-extraction-api.md) and
  [choice catalog](pdf-extraction-choices.json) identify the implemented choices.
  Local repository checks, mutation checks, a core/PDF installed-wheel probe and
  bounded real-provider smoke checks passed. Receipts:
  `~/Work/corpora/supply-2026-09-02/receipts/spicydocs-extraction-api-2026-09-14/`.
  The API is included in SpicyDocs 0.8.0; source-specific qualification and
  DocSpec adoption remain separate from this provider API.

## Canonical CFR/eCFR acquisition

- [x] **C01:** Inventory existing code and agree ownership: SpicyDocs acquires;
  RefSpec reads native text; DocSpec selects and runs datasets.
- [x] **C02:** Validate explicit eCFR API, annual CFR and GovInfo bulk eCFR inputs;
  preserve native identity separately from requested dates/editions.
- [x] **C03:** Implement bounded acquisition through shared HTTP and XML scanning;
  retain exact captures and failures without implicit route or date fallback.
- [x] **C04:** Provide one runnable source capture example and qualify ordinary
  installed-wheel use, including RefSpec reading supported captured XML.
- [x] **C05:** Complete focused/full checks, bounded live captures, retained-source
  replay and independent code reviews; document remaining format limits.
- [x] **C06:** Represent publisher-stated cover-only editions and original issue
  dates from GovInfo metadata; remove warnings based only on differing dates.

C06 checks: 1,211 tests passed (two opt-in tests deselected), lint/format and
focused types passed. The explicit edition metadata API returned 2025 Title 1
as `cover-only`, with original issue date `2023-01-01`, in one live request.
Retained evidence: `~/Work/corpora/supply-2026-09-02/receipts/cfr-edition-type-2026-09-12/`.

- [x] **M01:** Map GovInfo MODS package and constituent metadata using published
  MODS definitions and GovInfo field guides. Preserve repeated fields, attributes,
  namespace context, literal notes and unknown extensions with input provenance.
- [x] **M02:** Return mapped metadata from the existing annual metadata request;
  derive edition facts from that mapping and save ingestible JSON in the example.
- [x] **M03:** Verify preservation against retained full XML, qualify the wheel,
  review independently and correct the source ownership guidance.

SpicyDocs owns parsing and mapping non-body source metadata. DocSpec uses those
records for dataset catalogs and selection; domain processors interpret meaning.

M01–M03 qualification: 1,229 tests passed (two opt-in tests deselected), lint,
format and focused types passed. One live request produced exact XML and mapped
JSON. Complete 2023/2025 Title 1 replays each compared all 15,377 elements with an
independent XML parser and retained 401 constituents, 391 XML links, 400 PDF links
and 400 parent references. These are source observations, not acquired bodies.

The ordinary core-only SpicyDocs 0.5.0 wheel passed both replays without HTTPX.
Two independent static code reviews approved with no actionable findings.
Wheel SHA-256: `4b658c4a1cd8d5a1e99697440b6e6d152ae1c665233d4e8b4fe4e8cee156815a`.
Receipts, replay script and live outputs:
`~/Work/corpora/supply-2026-09-02/receipts/govinfo-mods-mapping-2026-09-12/`.
The [field guide](sources/govinfo-metadata.md) links the publisher dictionaries
and documents the mapping and format limits.

<a id="c07"></a>

- [x] **C07:** Add a DocSpec-owned annual CFR catalog example using the qualified
  SpicyDocs wheel. Preserve MODS metadata, select one explicit annual section,
  inject acquisition and processing, then prove a changed processor reuses
  retained bytes after the source client closes. Local DocSpec commit `1d37bcb`
  is isolated on `codex/cfr-dataset-example`; it pins SpicyDocs `0.6.0` from
  source commit `5a9c4e9`. DocSpec D55 owns its receiving completion record.

C07 checks: **1,162 tests passed**, one opt-in test deselected; regression-map,
lint, lock, build and installed-wheel checks passed. The examples work without
Dagster, and DocSpec's base install remains independent of SpicyDocs. Independent
review approved after fixing joined Federal Register format selection and policy
type checks. Both standalone and joined catalogs prefer one publisher XML offer
while retaining alternative formats as evidence.

The bounded live example used two requests: full volume MODS metadata (401
constituents) and one selected annual section. Reprocessing after closing the
source client added no captures, representations or segments. Exact source bytes,
complete mapped metadata and native publication identity remain available.
Receipts and review: `~/Work/corpora/supply-2026-09-02/receipts/source-fidelity-2026-09-12/`
(`docspec-check/` and `docspec-cfr-live/`).

Earlier C01–C05 validation: 1,162 tests passed (two opt-in tests deselected), lint/format and
focused types passed. All seven request shapes succeeded live. Source validation
passed all 49 retained August 24 titles (810,674,584 bytes); that snapshot is not
current coverage. Two independent code reviews approved the implementation.

SpicyDocs 0.4.0, source commit `29a2be4`, wheel SHA-256
`728affb3721707087c90987cbf3362295b7c527332ba7dbb15459e8ce0521fb4`, passed 11
installed-wheel replays. RefSpec read captured Title 1 and returned 274 addresses
with 14 explicit unsupported-range issues. Its format and numbering limits
remain visible in the [source guide](sources/cfr.md).

Source receipts: `~/Work/corpora/supply-2026-09-02/receipts/cfr-canonical-qualification-2026-09-12.json`
and `cfr-retained-validation-2026-09-12.json` in the same directory. This completes
the local source API; receiving application migration and public release remain
separate work.

## GovInfo bill integration

First deliverable: explicit bill IDs and text versions, exact status/text XML,
and installed-wheel consumers. Collection discovery and new regulatory sources
remain separate work with their own scope and coverage checks.

- [x] **G01:** Parse current BILLSTATUS and bill XML; preserve source fields, summaries and every stated text-version link; prove bill/version identity.
- [x] **G02:** Share bounded HTTP capture with Federal Register; expose status and explicitly selected XML text acquisition.
- [x] **G03:** Replace SpicyRegs' duplicate BILLSTATUS subject acquisition with the qualified SpicyDocs wheel.
  Local receiving commit `b990062` on `codex/govinfo-bill-source`; 1,040 tests
  passed, and the base CLI/MCP wheel works without the optional provider.
- [x] **G04:** Add a DocSpec-owned catalog, injected fetcher and processing example; prove later processing reuses captured bytes.
  Local receiving commit `4df1b44` on `codex/govinfo-bill-example`; the installed-wheel
  example explicitly selects one version and reprocesses after closing the source
  client, with zero new captures. Final checks: 1,277 tests passed, lint and lock
  checks passed; separate test-maintenance commit `e0580ce` updates stale Rulespec
  error assertions and removes an unused import.
- [x] **G05:** Run source/receiver checks, bounded live captures, installed-wheel qualification and independent reviews; document the supported formats and limits.

Source checks: 1,016 tests passed (two opt-in tests deselected), lint/format and
focused types passed. Three live bills supplied six validated status/text captures;
all three pairs replayed through the installed wheel. Source and receiving
independent reviews approved. [API and supported formats](sources/congress-bills.md).

At bill integration, both receivers pinned SpicyDocs 0.3.0 from source commit `8e485fe`, wheel
SHA-256 `bef15f967b0840ccc119c812edca92b38c63adb8943074be17655b86c96f83f1`.
DocSpec's later C07 work above advances its wheel to 0.6.0 in an isolated worktree.
Live receipts: `~/Work/corpora/supply-2026-09-02/receipts/bill-acquisition-2026-09-12/`.

CFR/eCFR already has acquisition examples, retained XML and active readers across
the sibling repositories; see the [reuse inventory](source-reference.md#cfr-metadata-and-separately-acquired-xml).
The canonical acquisition work is tracked above. Preserve SpicyRegs metadata
and DocSpec catalog/run ownership; receiving application migration remains
separate from adding this source API.

Deferred until a named workflow needs them: GovInfo discovery *publication* as a
release (bounded discovery itself landed as M04), standalone BILLSUM coverage, and
Federal Register issue acquisition justified by batch measurements.

## Public laws and statute compilations

- [x] **U01:** Pin the keyless COMPS and PLAW bulkdata zips and listings with both-direction
  listing checks. Receipt: `~/Work/corpora/supply-2026-09-02/receipts/comps-plaw-pin-2026-09-14/`.
- [x] **U02:** Add explicit USLM sources: selections, locators, native identity validation,
  bounded archive readers and an acquirer sharing the bounded HTTP capture. The identity
  scanner moved from the CFR package to `sources/xml.py` so both families share it.
  Validators were qualified offline against every pinned file (2,155 laws, 2,681
  compilations); one stub compilation is accepted and flagged. [Guide](sources/uslm-laws.md).
- [x] **U03:** Extract the acquisition budget and `_acquire` shape shared by the CFR, bill,
  Federal Register body and USLM acquirers into `transport/source_acquirer.py`: budget checks,
  client lifecycle and capture-then-validate with refusal evidence. CFR and USLM subclass it
  fully; bills take its lifecycle and checks; the Federal Register body flow keeps its
  multi-step route and takes the checks. 1,657 tests unchanged.

## Fetcher format review

The [format review](fetcher-formats.md) covers all implemented fetchers and
network tools. Implementation and validation are tracked below.

The [local pre-work review](remaining-source-prework.md) identifies existing
implementations and tests for F02–F05, P01 and the DocSpec CFR example.

- [x] **F01:** Review structured-format opportunities with parallel source reviewers and architecture consensus.
- [x] **F06:** Test GovInfo issue XML with retained live evidence. Extraction is feasible; no additional recovery demonstrated. Keep the default unchanged. [Result and limits](fetcher-formats.md#opportunities-that-need-more-evidence).
- [x] **F07:** Review all 23 tracked GovInfo bulk-data assets, including PDF guides, XML pairs and HTML samples; refine source-format guidance. [Findings and scope](fetcher-formats.md#what-the-complete-govinfo-asset-review-adds).
- [x] **F02:** Reuse the FEC/main media-type fix; pin aliases and final URL-path inference in Regulations.gov/public-comment policy `1.2`. JSON publication, retained replay and prior-policy refusal pass; source schemas stay unchanged.
- [x] **F03:** Preserve Federal Register `full_text_xml_url` and emit `body-xml`. Source schema `1.1`, policy `1.3`, embedded schema, admission and replay agree. Empty/malformed values become retained record failures; Parquet columns stay unchanged.
- [x] **F04:** Preserve native CRS `version` values, explicit null and absence on new captures. Resume leaves earlier successful rows untouched; a new output file obtains fresh evidence.
- [x] **F05:** Preserve CourtListener quoted empty strings, nulls and literal
  backslashes using the publisher's CSV dialect. Bound record size, decompression
  and compressed reads; refuse malformed text, rows and incomplete bzip2 members.
  Resume and cleanup checks pass. [SpicyRegs SR04](../../spicy-regs/PLAN.md#sr04)
  owns adoption of the reader and the separate table-normalization audit.

F05 checks: 103 CSV, bulk-reader and listing tests passed. Retained CourtListener
data produced 3,361 rows with 16,096 nulls and 11,808 empty strings. Re-encoding
with the publisher's quoting rules reproduced all 765,809 decompressed bytes.
Independent review findings about truncated input, byte limits and cleanup were
fixed and covered by regressions. Evidence shares the receipt directory below.

F02–F04 and P01 checks: 342 focused tests and 40 XML-acquisition tests passed;
lint, format and focused types passed. Independent review approved P01/F02/F04;
F03 review caught and corrected the empty-link refusal. One bounded live Federal
Register request returned 20 metadata records with publisher XML links. It did
not acquire bodies or establish coverage. Receipts and review:
`~/Work/corpora/supply-2026-09-02/receipts/source-fidelity-2026-09-12/`.

Local source commits: `f3b9137` (P01/F02–F04) and `5a9c4e9` (F05).
Combined qualification: **1,312 tests passed**, two opt-in tests deselected;
lint, format and focused types passed. Independent source reviews approved.
The ordinary SpicyDocs `0.6.0` wheel replayed retained Federal Register records,
both CFR MODS packages and CSV fidelity cases with no HTTP dependency installed.
Wheel SHA-256: `c6c364190dfab74d22e77843a8b3dee5c392ed983de21e524dd73be72647c532`.

## Public-comment attachment provenance

- [x] **P01 — Preserve original attachment-format positions.** Rendition IDs
  and source fields keep their original indexes when invalid entries appear
  before or between valid formats. Publication and replay preserve the raw
  JSON, diagnostics and noncontiguous positions under policy `1.2`.
  [DocSpec's comment example](../../DocSpec/docs/spicyregs-comments.md) retains
  provider-declared locations and exact input bytes; the source fix belongs here.
  Receiving mixed-validity coverage accompanies the C07 wheel adoption.

## XML body preference

- [x] **X01:** Prefer validated Federal Register XML; retain HTML fallback only after XML 404/410.
- [x] **X02:** Demonstrate XML and fallback with retained bytes; update callers and source guidance.
- [x] **X03:** Check identity, refusal, shared bounds, live XML and installed-wheel use; independently review.

Validation: 916 tests passed (two opt-in tests deselected), lint/format passed,
and independent architecture/code reviews approved. Four live XML samples and
both installed-wheel examples passed. [Usage and limits](federal-register-body-sources.md).

## Readability pass

- [x] **R1:** Consolidate Markdown around current tasks, rules and ownership.
- [x] **R2:** Compact comments/docstrings while preserving intent and behavior.
- [x] **R3:** Review meaning, links, CLI help and executable-code equivalence.

Validation: 802 tests passed (two opt-in tests deselected), lint/format passed,
and both independent reviews approved. Python logic and TOML settings are
unchanged; seven CLI help checks and local link/example checks passed.

## Official FEC acquisition

The [FEC reader and CLI](sources/fec.md) cover the researched official collection
families through shared JSON, XML listing, sitemap and explicit page-link readers.
Selected originals use the shared blob writer independently of metadata. Full
historical acquisition, financial normalization and SpicyRegs/DocSpec adoption
remain caller work; the source integration does not mark those complete. The
[updated T01–T19 task list](/Users/mikewolfd/Documents/Codex/fec-handoff-fixes/integration-task-list.md)
records completed capabilities, remaining acceptance criteria and the next delivery.
The [selected 2023–2024 and 2025–2026 bulk slices](/Users/mikewolfd/Documents/Codex/fec-data-research-2026-09-11/integration/README.md)
now have retained originals, source-shaped local tables, independent row/field
parity and caller interruption/retry evidence. Scoped API/history lookups are
complete; empty results, invalid candidate references and the official list of
unverified filers remain explicit. A local SpicyRegs wheel accepts selected retained API
rows through its existing mapping. The [filing slice](/Users/mikewolfd/Documents/Codex/fec-data-research-2026-09-11/integration/filings.md)
adds selected original statements, daily archives, separate Form 99 PDFs and a
source-reported amendment chain. The offline reader preserves positional fields
and separate body references without financial mappings. Complete distribution
adoption, historical profile/statement coverage, filing/attachment backfills and
downstream publication remain open. The [selected relationship delivery](/Users/mikewolfd/Documents/Codex/fec-data-research-2026-09-11/integration/relationships.md)
now covers all selected bulk relationship rows, the complete current committee
census and retained gap observations, and every relationship record in the
selected original statements. SpicyRegs preserves reported roles, names, source
dates and empty/invalid values with exact source references. The
[handoff repairs and fresh qualification](/Users/mikewolfd/Documents/Codex/fec-handoff-fixes/integration/fixes-2026-09-12/README.md)
close the selected legacy CSV TEXT, archive-only descriptor, empty sponsor-list
and input-membership defects. SpicyDocs includes its source repairs in merged
`main`; downstream complete FEC distribution/catalog/search adoption remains open.

- [x] Add a [retained committee census profile](sources/fec.md#publish-a-retained-committee-census)
  through the existing release publisher. Pin exact captures and replay source
  JSON; keep the selected observed scope and metadata/body separation explicit.
  Stream success evidence once for bulk consumer joins. Existing release formats
  and other source policies are unchanged.
- [x] Qualify the installed release and consumer wheels against the retained
  census. The [delivery evidence](/Users/mikewolfd/Documents/Codex/fec-handoff-fixes/integration/census-delivery-2026-09-12.md)
  covers original-JSON parity, committee table fields, complete catalog facts
  and rejected missing members/pins. The catalog contains committee metadata,
  with no acquired-body claim; default rollup and search paths remain unchanged.

SpicyDocs-only execution continues below. Each task uses the existing readers,
transport, blob store and publisher; dataset selection across products and
financial interpretation stay with their callers. Prefer bulk and XML/JSON/XHTML,
retain exact originals separately, and use the authorized bounded Zyte fallback
when a public route denies access.

- [x] **FEC01 — Publish the selected retained filing queries (T02/T04/T09).**
  The filing-query profile uses the existing publisher and shared retained-page
  reader. Every selected query has original-JSON parity and offline replay;
  overlaps retain separate observations. Known-answer controls cover empty
  queries, nullable file numbers and embedded bodies. Filing schema 1.1 corrects
  the initial non-identity field requirement; committee release identity remains
  unchanged and the first filing qualification artifacts remain retained.
- [x] **FEC02 — Add documented legacy TEXT layouts and explicit CP1252 (T05).**
  Exact CSV versions 5.0–5.3 separate narrative bodies from positional metadata.
  Retained-file replay preserves literal fields and body byte coordinates; two
  Form 99 originals have reversible CP1252 decoding. Added versions 5.0–5.2 have
  workbook evidence and synthetic controls, with real-original qualification
  still open below. No encoding is guessed or silently retried.
- [x] **FEC03 — Capture advisory-opinion number year 2024 (T08).** Complete
  observed JSON search and XML listing, opinion details and all selected
  supporting originals are retained. Offline replay checks metadata, associations
  and every original's bytes. Retry controls cover invalid detail responses,
  listing-only cases, refusals and interruption. PDF content is not parsed.
- [x] **FEC04 — Acquire the selected financial CSV histories (T06).**
  Communication-cost, electioneering and bundled-contribution originals passed
  complete selected-prefix XML enumeration and transfer bounds. Independent XML
  membership and CSV comparisons preserve source headers and literal fields.
- [x] **FEC05 — Prove refresh for that selected history (T18).** Fresh live
  listings reused verified originals; retained-response replay worked offline.
  Known-answer controls cover changed validators, missing previously listed keys,
  failed-object retry, corrupted local blobs, refusal and preflight bounds.
  Missing keys are observations, not proof of publisher deletion.

Selected scope, commands, source pins and limits are in the lane receipts under
`~/Work/corpora/supply-2026-09-02/receipts/fec-source-expansion-2026-09-13/`:
`releases-v1.1/qualification.json`, `formats/qualification.json` and
`bulk/qualification.json`, plus `legal/ao-2024/verification.json`. These are local
source deliverables; they do not
complete the broader T02/T04/T05/T06/T08/T09/T18 integration tasks.

Integrated checks passed through `./scripts/check`, including the offline suite,
lint and format checks. The ordinary core wheel also passed selected FEC tests,
retained filing-release/raw-file replay and offline CLI use without HTTP/table
extras. Legal originals replayed against the integrated code. Independent filing,
bulk and legal reviews preceded the manual sample follow-up below. Exact checks
and the corrected qualification caller are retained in `integrated/checks.json` and
`integrated/completion.json` under the same receipt root. The source expansion
and manual-review fixes below are merged into local `main`. Package release and
downstream adoption remain separate.

- [x] **FEC11 — Address the manual input/output review findings (T02/T05/T08/T19).**
  Retain optional S3 checksum/storage fields and add native positions for repeated
  sitemap entries and HTML links. Keep filing HTML navigation in metadata and
  document the explicit asset-selection rule. Offline reprocessing retains earlier
  captures and outputs. Direct sample review confirms legacy CSV body resolution
  and selected CP1252 excerpts; it does not establish whole-corpus text fidelity.
  Evidence and resolved bodies: `manual-review-fixes/` under the receipt root above.
  FEC11 validation covers retained originals, not extracted text. The optional
  PDF/image extraction adapters are tracked separately in PDF01 below.
  The [saved PDF choices](pdf-extraction-choices.md) and
  [configuration catalog](pdf-extraction-choices.json) preserve tested alternatives
  by source/page type; automatic routing and DocSpec adapters remain separate
  work. The regional approach improved selected outputs but failed its
  no-regression gate.

### Interface implementation

Existing `FecClient` methods cover the researched official JSON operations,
XML listings/sitemaps, explicit collection links and independent original files.
An unfetched year, large file or unavailable URL is an acquisition outcome;
it does not imply a missing interface. Native archives and filings retain their
published formats; XML/JSON/XHTML precede equivalent HTML.

- [x] **FEC12 — Share public-source denial recovery.** `BoundedAcquirer` accepts
  an injected Zyte fetcher and explicit public-URL predicate. FecClient delegates
  to it; FOIA.gov/Oversight.gov callers no longer need a separate proxy transfer
  implementation. Direct/proxy originals share prefix, size, digest and storage
  checks. Request budgets, source credentials, direct redirect chains and ETag
  conditions remain explicit. Opaque proxy redirects and unavailable transfer
  headers cannot be checked as direct responses are. Historical campaign receipts
  retain their original scripts; new callers use the public interface.
- [ ] **FEC10 — Extend immutable source-release interfaces.**
  - [x] Admit genuine negative F13 `file_number` values unchanged in filing schema
    1.2; retain `sub_id` identity, explicit filter checks and acquisition policy 1.0.
    Earlier releases retain their schema and pins. The shared publisher and
    retained-page reader need no F13-specific implementation.
  - [ ] Add source identity/count/scope rules for the next selected family beyond
    committee census and processed filing queries. Raw acquisition already works;
    each additional immutable profile needs source-specific admission evidence.
- [x] **FEC13 — Promote reusable agency-report parsing.** Offline
  `parse_foia_annual_report` and `parse_oversight_report` expose retained source
  fields through the [agency-report API](sources/agency-reports.md). Native NIEM
  1.02/1.03 parsing shares the XML scanner and preserves every element, namespace
  declaration and repeated association. Oversight uses the optional `html` extra;
  descriptions and recommendation tables remain separate from metadata, with
  literal values, repeated items/links and source positions. Word Flat OPC refuses
  as a distinct representation. Collection selection, interpretation, downloads
  and campaign loops remain with existing callers. Historical research scripts
  remain dated evidence; package adoption and full-population imports stay open.
  [Qualification and limits](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-agency-interfaces-2026-09-14/README.md>).
- [x] **FEC14 — Add evidence-backed raw filing field mappings.** The core-only
  [filing-field API](sources/fec-filing-fields.md) exposes pinned electronic/paper
  dictionaries and explicitly selected positional annotations. Native versions,
  unknown columns, repeated labels, absent/blank values and separate body references
  survive. Ambiguous source rows require a row selector; matching width is not a
  compatibility verdict. Dictionary notes and rules stay outside repeated records.
  Source-cell replay and selected real filings qualify the supplied definitions;
  automatic routing, new dictionary editions, amendment selection and financial
  views remain separate. [Evidence and scope](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-filing-fields-2026-09-15/README.md>).

Interface code and focused regression checks are on `codex/fec-interfaces`.
[Qualification receipts](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-interfaces-2026-09-14/>)
record checks and source replay separately from full-data acquisition.

### Representative qualification and acquisition backlog

These tasks exercise and run the interfaces above. Full-population transfers,
database restoration, recurring refresh and downstream catalogs are separate work.

- [ ] **FEC06 — Extend historical filing qualification and acquisition.** The
  selected `5.00`, `5.1`, `5.2` and v3.00 originals and supplied F13 raw filings
  are retained. Literal `5.0`, broader layout/encoding evidence, oversized PDFs
  and missing raw URLs remain separate qualification or acquisition gaps.
- [ ] **FEC07 — Extend legal and agency collection acquisition.** Continue the
  named large enforcement originals, unresolved exact case associations and
  additional legal/agency years using existing readers. A related case or filename
  does not establish identity. FEC13 tracks reusable agency parsing separately.
- [ ] **FEC08 — Acquire remaining financial bulk families.** Extend beyond the
  selected financial histories and 2024 files. Large A/B dump restoration needs
  scratch, restored-table and index capacity before transfer; it does not need
  another downloader. Source field mapping is FEC14; financial views are downstream.
- [ ] **FEC09 — Extend refresh qualification and historical coverage.** The F13
  metadata query has a new observation; imported research captures retain their
  observation times. Reuse the existing acquisition/resume path. Source-specific
  replacement/deletion checks need selected examples; scheduling stays with the caller.

The [September 14 collection qualification](research/fec-next-collections-2026-09-14.md)
records completed scopes, source pins, checks and the remaining file and identity
gaps for FEC06–FEC08. The research follow-up shares the existing acquisition/resume
code across all three collections; only source selection and qualification differ.
[Local integration and combined checks](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-local-integration-2026-09-14/integration.json>)
record code delivery separately from captured data. Wider refresh remains FEC09
and additional release interfaces FEC10.

The [earlier full check](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-next-collections-2026-09-14/checks.json>)
passed before the follow-up proxy-refusal fix. After that fix,
[focused FEC tests, mutation, lint/format and shared controls](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-research-integration-2026-09-14/checks.json>)
passed on the acquisition worktree. The integration receipt above records the
subsequent combined full-suite check; installed-wheel qualification and a package
release remain separate.

## SpicyRegs fetcher merge

Decision (2026-09-14): every SpicyRegs reader connector that fetches a publisher
moves into SpicyDocs as an explicit source; SpicyRegs adopts the wheel and
deletes its copy. RefSpec's source acquisition and parsing now enter the
[shared parsing effort](#shared-parsing-and-metadata-capture); vocabulary building
remains in RefSpec. SpicyRegs'
`cloudflare.py` is a cache purge, not a fetcher, and stays. Adoption needs a
wheel newer than the 0.3.0 SpicyRegs pins today.

| SpicyRegs module | Publisher route | SpicyDocs disposition | Item |
| --- | --- | --- | --- |
| `federal_register.py` | FR API v1 documents; 90-day windows under the 10,000 cap | Covered by `sources/federal_register/native.py` | adopt |
| `fec_committees.py` | OpenFEC `/v1/committees/`, keyset paging | Covered by the FEC committee profile | adopt |
| `courtlistener_bulk.py` | CourtListener bulk CSV exports | Covered; SpicyRegs SR04 | adopt |
| `bill_subjects.py` | GovInfo BILLSTATUS | Already on the wheel (G03) | done |
| `gao_reports.py` | `gao.gov/rss/reports.xml` listing | Port: RSS listing route beside product pages | M01 |
| `crs_reports.py` | `api.congress.gov/v3/crsreport`, offset/limit, keyed | Port: listing route beside `crs_summaries.py` | M02 |
| `congress_bills.py` | `api.congress.gov/v3/bill`, offset/limit, keyed | Port: bill listing route | M03 |
| `cfr_sections.py` | `api.govinfo.gov` `/published` and `/packages/{id}/granules`, keyed | Port: bounded GovInfo JSON discovery; this names the workflow the deferral above waited for | M04 |
| `courtlistener.py` | CourtListener REST v4 search, token | Port | M05 |
| `unified_agenda.py` | `reginfo.gov` `REGINFO_RIN_DATA_{edition}.xml` | Port | M06 |
| `lobbying_filings.py` | `lda.gov/api/v1`, page/page_size, keyed | Port | M07 |
| `sam_entities.py` | `api.sam.gov/entity-information/v4`, date windows, keyed | Port | M08 |
| `usaspending.py` | `api.usaspending.gov/api/v2` recipients, page/limit | Port | M09 |
| `fcc_ecfs.py` | `publicapi.fcc.gov/ecfs`, date windows, keyed | Port | M10 |

Order: U03 first, so ports land on one acquirer. Then M01–M04, which extend
source families that exist. M02, M03, M07, M08, M09 and M10 are keyed JSON
traversals; build the shared traversal once (host allowlist, header-only
credential, declared pagination mode, records path, exact page captures with
evidence) and register each publisher against it, the way the FEC client reads
its retained Swagger. Every port keeps exact page bytes, checks the publisher's
declared continuation and counts, retains refused bytes, and ships tests on
retained fixtures plus a guide.

- [x] **M01** — GAO RSS listing: `sources/gao/rss.py`, keyless, links must name canonical products. [Guide](sources/listings.md).
- [x] **M02** — CRS report listing: `sources/congress/listing.py` on the shared traversal.
- [x] **M03** — Congress.gov bill listing: same module; continuation spaces re-encoded before request.
- [x] **M04** — GovInfo JSON discovery: `sources/govinfo/discovery.py` (`/published`, `/collections`, package granules); zero count is an observation.
  Shared traversal: `sources/paged_json.py` (host, next path, count path as data; header-only credential; declared-count checks). Pinned pages: `receipts/spicyregs-merge-probes-2026-09-14/`.
- [x] **M05** — CourtListener REST search: `sources/courtlistener_search.py`, keyless or token; cursor continuations.
- [x] **M06** — Unified Agenda edition XML: `sources/unified_agenda.py`; 202510 capture matched RefSpec's pin. [Guide](sources/unified-agenda.md).
- [x] **M07** — LDA lobbying filings: `sources/lda.py`, keyless or token.
- [x] **M08** — SAM entity management: `sources/sam.py`; needs the SAM.gov key (`SAM_GOV` in `.env`); placeholder `api_key` dropped from continuations.
- [x] **M09** — USAspending recipients: `sources/usaspending.py`; POST page-number walk with request bodies recorded.
- [x] **M10** — FCC ECFS filings and proceedings: `sources/fcc_ecfs.py`; offset walk with no publisher count.
  The traversal gained three continuation kinds, a request method and a credential format as family data, and the bounded client gained POST with a recorded body. SpicyRegs adoption (deleting its copies, bumping the pinned wheel) is the receiving side's work and has not started.
- [x] **M11** — Audit of every other outbound path in SpicyRegs (all mechanisms, not only HTTP libraries): `sources/mirrulations.py` is the same reader SpicyDocs already ships; `sources/pdf.py` (attachment PDF by URL) is covered by `transport/download.py`'s bounded asset capture; four transforms import `requests` without calling it; `r2.py`, `iceberg.py`, `cloudflare.py` and the `data.spicy-regs.dev` clients are its own storage and site, not publisher fetches. No publisher route remains without a SpicyDocs equivalent.
- [x] **M12** — Live multi-page walks through every list reader (73 requests): next-URL, POST page-number and offset continuations each ran to the publisher's terminal page or refused at the bound as designed. Receipt: `~/Work/corpora/supply-2026-09-02/receipts/spicyregs-merge-live-walks-2026-09-14/`.

## Remaining publisher fetches outside SpicyDocs

Inventory of 2026-09-14 across spicysearch, RefSpec, DocSpec and every corpora
tree including archived and salvaged copies, keyed by publisher host and route
rather than by file. PAR01 reopens source acquisition and parsing exclusions,
including vocabulary sources such as OSTI and LOC FAST; their vocabulary-building
policies stay in RefSpec. Own-site and own-storage traffic keeps its existing owner.

| Item | Publisher route | Where it is fetched today | Disposition |
| --- | --- | --- | --- |
| P01 | OLRC U.S. Code: release-point USLM per title and whole corpus, annual XHTML archives, Popular Name Tool page, Table III per-act pages and bulk zip (`uscode.house.gov`) | RefSpec tools and oracle scripts; salvaged SpicyRegs `uscode_olrc.py` | Done 2026-09-14: `sources/uscode.py`, `uscode_acquisition.py`. OLRC uses USLM 1.0 in the House namespace; absent Table III acts answer 200 truncated; the Table III bulk URL is stated on `table3years.htm` and matched RefSpec's retained zip byte for byte. [Guide](sources/uscode.md). |
| P02 | Supreme Court slip opinions: term index page to case metadata and official PDF (`supremecourt.gov/opinions/slipopinion/{term}`) | Salvaged SpicyRegs `supreme_court_opinions.py` | Done: `sources/supreme_court.py`, keyless. The index is a live render that differs between requests; PDF names carry revision tokens. [Guide](sources/supreme-court.md). |
| P03 | CRS report files (`congress.gov/crs_external_products/{type}/PDF/{id}/{id}.{version}.pdf`) | Salvaged evaluation; `crs_summaries.py` says PDFs are fetched separately | Done: `sources/congress/crs_files.py`, keyless GET (HEAD is 403). Family directories are not always the id prefix, so the publisher's stated URL is the primary selection. [Guide](sources/crs-files.md). |
| P04 | GAO report files (`files.gao.gov/reports/{id}/`) | Salvaged evaluation; the GAO guide excludes linked report files | Done: `sources/gao/files.py`. The file host is keyless; only `www.gao.gov` is gated. About half the products have an online-report index, so the one-request PDF route is universal. [Guide](sources/gao-files.md). |
| P05 | regulations.gov API v4 documents and `downloads.regulations.gov/{id}/content.pdf` attachments, keyed | DocSpec `tools/fetch_attachment_sample.py`; salvaged evaluation | Done: `sources/regulations_gov/api.py`, `attachments.py`. No `links.next`; a boolean `hasNextPage` and a forty-page cap with a drifting count. The download host needs a browser User-Agent, not the key. [Guide](sources/regulations-gov-api.md). |
| P06 | CBO cost-estimates XML feed and RSS (`cbo.gov/cost-estimates/xml`) | RefSpec `cbo_topic_codes.py` for topic labels | Done: `sources/cbo.py` reads the per-Congress feeds; the site's XML feed and estimate documents are behind a bot wall and were never acquirable. [Guide](sources/cbo.md). |

Shared changes the six ports converged on, made once (2026-09-14): the bounded
client clears cookies per request and keeps 401/403 bodies as evidence on
keyless routes; the shared acquirer refuses credential echo centrally and
carries `check_final_url`; the traversal accepts a boolean has-next flag,
advisory counts and per-family media types; `sources/pdf_bytes.py` holds the
one PDF magic-and-trailer check.

Follow-up (same day, three parallel workstreams):

- [x] **D01** — One USLM scanner: `UslmScan(root, *, namespace, body_sections, referring_sections, ...)` in `govinfo/uslm.py` serves GovInfo and OLRC; `uscode.py` lost its copy (−65 lines). One bounded zip reader in `sources/zip_archive.py` replaced two. Re-qualified against every pinned file with identical counts; the GovInfo scan gained the OLRC path optimization (70.9 to 88.4 MB/s on the largest compilation). Receipt: `receipts/dedup-uslm-zip-2026-09-14/`.
- [x] **Q01** — FCC ECFS: `[gte]D[lte]E` bounds at E's midnight instant, so a same-day window matched nothing; locators now send an inclusive end. **Q02** — regulations.gov attachment 403s are named from the publisher's words (`client-rejected` versus `object-access-denied`; neither is absence). **Q03** — CBO has no keyless document route; the wall is path-scoped and a same-client control served the feed. **Q04** — SAM serves at most 10,000 records per query shape (page 1000 at size 10 is a 400), not the ~5,000 SpicyRegs recorded. Receipts: `receipts/publisher-questions-2026-09-14/`.
- [x] **C01** — `spicy-docs-list`: one command over the paged traversal, family chosen by name from a registry (`cli/list_pages.py`), exact page bytes into a content-addressed store and one JSONL row per page. Live smoke: five GovInfo granule pages. Receipt: `receipts/cli-list-smoke-2026-09-14/`.
- [x] **D02** — Reach bounds moved onto `JsonPageFamily` as data (`max_reachable_records`, `max_page_number`, `window_hint`), so the generic walk the command uses refuses in one request where the SAM and regulations.gov readers used to; their copies are deleted.

Existing routes support adoption by spicysearch's presidential-body scripts
and RefSpec's eCFR title captures. Route coverage does not establish complete
parsing or metadata coverage. The [shared parsing effort](#shared-parsing-and-metadata-capture)
tracks the additional readers, publisher tables and PREMIS comparison identified
by the later swarm. DocSpec's generic content fetchers remain its injected
dataset adapters; source-specific parsing follows the shared ownership decision.

## Deferred local work

<a id="s21"></a>

- [ ] **S21 — Replace the campaign after a better workflow exists.** The current
  campaign publishes independent source releases. Reopen when a named workflow
  and DocSpec D22 demonstrate source ordering, interruption, root ownership,
  resource bounds, retained pins and stale-resume refusal. Then remove replaced
  pools, receipts, locks and recovery branches while preserving useful diagnostics.

<a id="s31"></a>

- [ ] **S31 — Use DocSpec wheels for a concrete local dataset caller.** The audit
  found no remaining local catalog, document-capture, processor or dataset-resume
  loop to replace. Reopen when such a caller exists and qualified public APIs
  preserve source/fetcher/processor injection. Remove its replaced loops after
  parity checks; keep source users independent and package dependencies acyclic.

The [caller decision](source-ownership.md#current-campaign-and-dataset-callers)
explains both deferrals. DocSpec D51/D52 own the completed GAO/comment examples,
and D55 records the annual CFR example;
creating a new source-side loop merely to migrate it adds no value.

## Completed local work

### Outcomes and evidence

<a id="s01"></a>

- [x] **S01 — Expose collection outcomes.** Reader and CLI distinguish success, empty, partial and total rejection, with bounded failure access. [Guide](source-native-outcomes.md).

<a id="s03"></a>

- [x] **S03 — Remove repeated campaign verification.** Normal publication replays once; pinned resume checks and explicit full audits remain. [Guide](cli.md#campaigns-replay-and-source-tools).

<a id="s04"></a>

- [x] **S04 — State the product boundaries.** Guides distinguish source records, retained evidence, body links, tables and dataset work. [Guide](source-workflows.md).

<a id="s05"></a>

- [x] **S05 — Require current formats.** Current producer, schemas, policies and required counts replace historical acceptance. [Guide](decisions.md#current-source-release-format-and-retained-evidence).

<a id="s06"></a>

- [x] **S06 — Separate storage accounting.** Read/reused/written-byte measurements live in run results, outside sealed source metadata. [Guide](releases.md).

<a id="s07"></a>

- [x] **S07 — Replay failure provenance.** Independent verification detects omitted, invented, duplicated or relinked deterministic failures. [Guide](releases.md#choose-the-right-check).

<a id="s08"></a>

- [x] **S08 — Retain refused evidence.** Bounded rejected response bytes remain diagnosable without producing an accepted release. [Guide](cli.md).

<a id="s09"></a>

- [x] **S09 — Explain coverage.** Selectors and source-specific assumptions distinguish observed scope from publisher-wide completeness. [Guide](source-native-outcomes.md).

<a id="s10"></a>

- [x] **S10 — Match comment claims to discovery.** Captured comments describe observed contiguous-part discovery, including empty, gap and request-failure cases. [Guide](sources/public-comments.md).

### Ownership and removal

<a id="s11"></a>

- [x] **S11 — Assign component ownership.** The inventory records useful consumers, retained responsibilities and selected removals. [Guide](source-ownership.md).

<a id="s12"></a>

- [x] **S12 — Retire unused catalogs and policy.** Removed generators, commands, seals and misplaced processor/region declarations together; retained source knowledge. [Guide](source-reference.md).

<a id="s13"></a>

- [x] **S13 — Keep useful tables; retire Iceberg attachment.** Immutable Parquet remains supported; the unused attachment surface and location plumbing are removed. [Guide](releases.md).

<a id="s14"></a>

- [x] **S14 — Share strict CourtListener parsing.** The public listing/filename parser serves the source reader; receiver adoption has its own tasks. [Guide](sources/raw-readers.md#courtlistener).

<a id="s15"></a>

- [x] **S15 — Keep proportionate drift diagnostics.** Pinned comparisons and explicit refresh remain source-maintainer tools, with no automatic acquisition gate. [Guide](source-domain-drift.md).

<a id="s16"></a>

- [x] **S16 — Remove superseded code and fix state/types.** Retired wrappers and declarations; kept purposeful optional APIs, source rules and bounded state. [Guide](architecture.md).

<a id="s17"></a>

- [x] **S17 — Preserve literal GAO topics.** Offline examples and bounded evidence access demonstrate matching, unexpected and refused inputs. [Guide](sources/gao.md).

### Public APIs and qualification

<a id="s19"></a>

- [x] **S19 — Package bounded GovInfo body acquisition.** Explicit routes preserve requested/resolved identity, enforce request/byte bounds and return reusable exact captures. [Guide](federal-register-body-sources.md).

<a id="s22"></a>

- [x] **S22 — Adopt the shared physical writer.** Rulespec handles bounded durable writes; SpicyDocs retains source references and result mapping. [Guide](source-ownership.md).

<a id="s23"></a>

- [x] **S23 — Qualify source docs and package.** The merged candidate was exercised from clean core/extras installations, with exact schemas and resources. [Guide](installation.md).

<a id="s24"></a>

- [x] **S24 — Review contributor value.** Independent reviews resolved findings; a simulated contributor ran source-only examples and added a mutation-checked regression. [Guide](../CONTRIBUTING.md).

<a id="s25"></a>

- [x] **S25 — Complete selected local handoffs.** Ownership, shared-writer adoption and receiving probes are recorded separately from upstream adoption. [Guide](source-ownership.md).

<a id="s26"></a>

- [x] **S26 — Publish an independent provider API.** The existing reader exposes records, profiles, renditions, outcomes and evidence; acquisition/Parquet dependencies are optional. [Guide](installation.md).

<a id="s30"></a>

- [x] **S30 — Use the agreed shared encoding.** Supported source values remain exact; unsupported values are refused with evidence. DocSpec adoption remains separate. [Guide](decisions.md).

## Work owned by other repositories

These links require optional sibling checkouts. Follow the destination's current
acceptance criteria; updating this ledger does not complete receiving work.

<a id="s02"></a>

- **S02 → [DocSpec D08](../../DocSpec/docs/dataset-experiments-todo.md#d08):** consume source outcomes and choose partial-input policy.

<a id="s18"></a>

- **S18 → [DocSpec D52](../../DocSpec/docs/dataset-experiments-todo.md#d52):** build the captured-comment catalog adapter and example. [SpicyRegs SR02](../../spicy-regs/PLAN.md#sr02) owns the input facts and API; local source coverage remains [S09](#s09)–[S10](#s10).

<a id="s20"></a>

- **S20 → [DocSpec D20–D23](../../DocSpec/docs/dataset-experiments-todo.md#d20):** qualify execution, interruption, bounded retry and accounting.

<a id="s27"></a>

- **S27 → [DocSpec D13–D19](../../DocSpec/docs/dataset-experiments-todo.md#d13), [D38](../../DocSpec/docs/dataset-experiments-todo.md#d38):** processing/resource injection, later processing, reuse, growth and comparison.

<a id="s28"></a>

- **S28 → [DocSpec D02–D04](../../DocSpec/docs/dataset-experiments-todo.md#d02), [D19–D21](../../DocSpec/docs/dataset-experiments-todo.md#d19), [D32](../../DocSpec/docs/dataset-experiments-todo.md#d32):** configuration, stage references and local/Dagster composition.

<a id="s29"></a>

- **S29 → [DocSpec D19](../../DocSpec/docs/dataset-experiments-todo.md#d19), [D24–D29](../../DocSpec/docs/dataset-experiments-todo.md#d24):** usable retained stages, comparison, optional export and admission.

Other handoffs: [DocSpec D41–D46](../../DocSpec/docs/dataset-experiments-todo.md#d41)
for provider reuse; [SpicyRegs SR01/SR03](../../spicy-regs/PLAN.md#sr01) for selected
upstream source reuse; [Rulespec RS01–RS03](../../rulespec/TODO.md#rs01) for shared
encoding/artifact/storage operations. DocSpec D28/D31 own encoder/writer adoption.

<a id="product-ownership-to-preserve"></a>

The [ownership page](source-ownership.md) governs product boundaries. No package
merger, legacy layer or search consumer is required. Keep independent source use,
injected fetchers/processors, exact evidence and meaningful failure distinctions.

## Merged baseline and evidence

[PR #1](https://github.com/mikewolfd/spicy-docs/pull/1) merged as `3ff8011`.
Its final source qualification used `296f20d`: 802 local tests passed, two opt-in
checks were deselected; CI passed with one unavailable saved sample skipped.
The exact installed wheel passed 64 focused tests and 44 canonical cases in both
core/extras environments. Reviews and contributor simulations establish their
stated scope, not human usability, live coverage or deployment.

Retained candidate: `spicy_docs-0.2.0-py3-none-any.whl`, SHA-256
`ecaa5ebc15df7cad12952e5fdeb8e1cef71614471dfb81b5f43316049d246c4e`.
Rulespec Artifacts `1.0.12`, from `bf59d63`, SHA-256
`3f6c946c60ff2ddbe854fce7f74f4358ddb21e3ba3f6ad10caa8a0d8d59fd0a5`.
These identify the merged baseline, not a newly rebuilt wheel after later edits.

The [merged execution record](https://github.com/mikewolfd/spicy-docs/blob/3ff8011b221d4508778996c4a479c54a038f406c/docs/simplification-todo.md#execution-record)
retains per-item criteria, decisions and commit evidence. Local command receipts
remain in the originating Codex task's `validation/s19-s22-s26-s30/` directory.
That record also documents the qualified Rulespec probe and local DocSpec receiving
commit `bf38ef1`; it does not establish their later upstream state.
