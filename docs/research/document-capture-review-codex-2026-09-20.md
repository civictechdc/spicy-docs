# Document capture: an outside review of the schema and its use

Status: review, 2026-09-20. Produced by OpenAI Codex CLI 0.155.1 in a read-only
sandbox against rulespec and this repository, at the owner's request, and
retained here verbatim below the rule as a decision input for the
[capture-schema design note](document-capture-schema-2026-09-19.md). The
reviewer could not execute `uv run` inside its sandbox (the uv cache was
refused), so every statement below is a static reading; nothing in it was run.
Paths are absolute as the reviewer wrote them. The spicy-docs coordinator's
reading of it: the ownership boundary and the composition hold; the goal's
missing halves are a reversible XML representation, PDF table observations
carried into the capture adapter, and shared source-record provenance that
is required rather than optional.

---

**Verdict: keep the architecture, but the owner’s goal is only partly delivered.** Rulespec supplies a genuinely composable structural schema, and SpicyDocs owns the family profiles and parsing as required. The implementation demonstrates six JSON captures with strong text-evidence checks. It does **not** yet demonstrate a reusable PDF-family capture path that retains all critical metadata and can regenerate equivalent JSON and XML. The largest gaps are XML export/import, PDF table preservation, and metadata requirements. The newer analytical tables are useful independent consumers of extraction; their success does not establish DocumentCapture completeness.

For compact evidence references: `R` means `/Users/mikewolfd/Work/spicy-stack/rulespec`; `S` means `/Users/mikewolfd/Work/spicy-stack/spicy-docs`.

- **P** = [parent schema]( /Users/mikewolfd/Work/spicy-stack/rulespec/release-records/schemas/document-capture-v1.schema.json)
- **M** = [profile meta-schema](/Users/mikewolfd/Work/spicy-stack/rulespec/release-records/schemas/document-capture-profile-v1.schema.json)
- **C** = `S/tools/analysis/document_capture.py`
- **F(name)** = `S/src/spicy_docs/schemas/document_capture/1.0/profiles/<name>.schema.json`
- **E** = `/allOf/1/properties/profile/properties/ext`, the document-extension schema in each profile.

### Findings against the five questions

| Question | Finding | Evidence |
|---|---|---|
| **1. Composition** | **Real parent composition, with limited extension points.** Every profile uses `allOf: [{$ref: parent}, narrowing]`. The parent closes its objects but leaves `profile.ext` and node `ext` open; profiles close those extension blocks. They add namespaced kinds without copying the parent’s nodes, spans, or artifact definitions. M permits exactly this layout and a small extension-value vocabulary; it forbids profiles from tightening other parent fields, adding reusable `$defs`/`$ref` extension blocks, or defining arbitrary per-kind conditions. A CBO/GAO **schema** can be added without changing P; a working extractor cannot be supplied by a profile alone. Validation discovers profile files, while conversion explicitly calls six Python converters. | P:7,446–470,697–854; M:51–175,309–422; `R/packages/rulespec-artifacts/src/rulespec_artifacts/document_capture.py:152–202`; [C:797](/Users/mikewolfd/Work/spicy-stack/spicy-docs/tools/analysis/document_capture.py:797), C:2346–2363. |
| **2. Round trip** | **DocumentCapture output is JSON only.** It writes capture JSON, fragment JSON, and measurements. No DocumentCapture XML encoder/decoder or full bidirectional fixture test exists in the inspected surface. The “round trip” verifies concatenated span text against independently read source text. PDF checks rejoin retained extractor blocks, not PDF structure. Separately, CFR reconstruction emits a **real CFR vocabulary**, rooted at `CFRGRANULE` and naming `CFRMergedXML.xsd`; provenance remains in a JSON source map. That serializer consumes `ReconstructedDocument`, not DocumentCapture. | C:2258–2284,2374; [text-round-trip test](/Users/mikewolfd/Work/spicy-stack/spicy-docs/tests/test_document_capture.py:208); `S/src/spicy_docs/reconstruction/serialize.py:1–28,239–313`. |
| **3. Critical metadata** | **Strong evidence primitives, incomplete guarantees and source metadata.** Artifact digest/media type, rendition kind, converter provenance, and character-span structure are required. Retrieval time, publisher URL, page coordinates, node decisions, and cell geometry are optional. MODS identity/provenance and most normalized cross-table keys are absent as structured fields. Details below. | P `/$defs/Artifact`, `TextStream`, `Converter`, `SourceLocator`, `Span`, `Node`; the six profiles’ E blocks. |
| **4. Use in practice** | **All five newer tables bypass DocumentCapture.** Budget volumes and House activity reports consume summary + MODS + `BodyText` + citation findings. Document citations and bill committee actions consume findings plus `DocumentProvenance`. Senate expenditures consumes `TableObservation` plus page text. This is reasonable layering for analytical rows. The missing piece is a reusable capture adapter and an explicit mapping between their normalized-text offsets and capture spans. Reconstruction is a second internal structure, but CFR has a one-way adapter into DocumentCapture. | `S/src/spicy_docs/schemas/budget_volume_tables.py:256–276`; `document_citation_tables.py:422–477`; `bill_action_tables.py:208–248`; `senate_expenditure_tables.py:650–680`; [CFR adapter](/Users/mikewolfd/Work/spicy-stack/spicy-docs/tools/analysis/document_capture.py:1983). |
| **5. Health** | **Substantial checks exist; delivery and coverage remain bounded.** Rulespec checks schema validity, resource bytes, fixture pins, composition, namespaces, and negative controls for partition, ownership, text, digests, and depth. Its base fixture has only two nodes and two spans. SpicyDocs checks all six committed captures, pins, independent text recovery, selected fragment resolution, and several visual-review fixes. I verified byte equality between current Rulespec and vendored parent/meta-schema/validator, and their hashes against `PINS.json`. Rulespec’s package declares **1.0.14**; SpicyDocs and SpicyRegs still pin **1.0.13**, whose wheel lacks DocumentCapture. The wheel-equality test consequently skips. | `R/tools/test_document_capture_schema.py:66–235`; `R/release-records/fixtures/document-capture-v1/minimal-valid.json#/nodes`; `R/Makefile:74–82`; `S/tests/test_document_capture.py:53–84,164–215,243–409`; `R/packages/rulespec-artifacts/pyproject.toml:7,17–19`; `S/pyproject.toml:7,58`; `spicy-regs/pyproject.toml:25,112`. |

**What the six profiles share and repeat.** All six reference P at `/allOf/0/$ref`; none defines a separate parent structure or references a shared extension schema.

| Profile | Its own blocks beyond the shared parent |
|---|---|
| `uslm-law` | Publication metadata; node identifiers, roles, numeric labels. |
| `bill-xml` | Bill identity and DeltaTrack results; node paths and element identifiers. |
| `committee-report-html` | Package identity and block rule; empty node-extension schema. |
| `federal-register-xml` | Publication identity, citation, dates, agencies; heading/table attributes. |
| `cfr-reconstruction` | Reconstruction identity, PDF details, page sizes, XML-output digest; original node IDs and XML paths. |
| `slip-opinion-pdf` | PDF details and opinion inventory; author, opinion type, page ranges. |

Evidence: each named F file at E and `/allOf/1/properties/nodes/items/allOf`. There is limited repetition: CFR and slip-opinion both redeclare `pdfSha256`/`pdfBytes`, duplicating parent artifact facts; CFR’s `pageSizes` repeats the parent’s page-size shape.

### Critical metadata inventory

“Present” below means a required structured field; it does not mean every value is independently verified.

| Metadata | Status and location |
|---|---|
| **GovInfo package/granule identity** | **Present but optional generically:** P `/$defs/Artifact/properties/locator/properties/publisherId`, plus `identifiers[]`; neither distinguishes package from granule. **Present family-specifically:** F(committee-report-html) E requires `packageId`; F(cfr-reconstruction) E requires `granuleId`. No common paired package/granule identity. |
| **MODS-stated identity and its evidence** | **Absent as a defined capture field/reference.** P’s closed `Artifact` and all six E blocks lack a MODS identity record or pinned MODS-capture link. An arbitrary identifier string cannot establish which MODS bytes stated it. |
| **Publisher URL** | **Present but optional:** P `/$defs/Artifact/properties/locator/properties/url`. The locator object itself can be empty. One existing URL/digest pairing is wrong; see gap 3. |
| **Retrieval capture** | **Present:** artifact `sha256`, `byteSize`, `mediaType`. **Present but optional:** `retrievedAt`, allowing date-only precision. `capture.capturedAt` is conversion time, not retrieval time. P `/$defs/Artifact/required`, `/properties/capture/required`. |
| **Rendition read** | **Present:** `/rendition/kind`, text-stream digest, normalization. **Present but optional:** extractor `intermediate`; no conditional requirement for PDFs, and no rendition-selection/fallback reason. P `/properties/rendition`. |
| **Page and character provenance for every node** | **Present:** span `start`, `end`, `exact`, `source`; node `evidence` array. **Present but optional:** node `source`, source `page`/`box`, page dimensions. Evidence arrays may be empty; an effective coordinate system may be `none`. Thus “every node has page/span provenance” is not guaranteed. P `/$defs/Span/required`, `Node/required`, `SourceLocator/properties`; validator:81–148. |
| **Extraction/rule versions** | **Present:** converter version, implementation revision/file digest, dependency versions, and profile version/pin. **Present but optional:** node `decision`. **Absent:** a dedicated per-rule version binding; `Decision` carries only method/rule/detail. P `/$defs/Converter`, `Decision`, `Node/properties/decision`. |
| **Bill/public-law join keys** | **Present family-specifically:** bill congress/type/number/version in F(bill-xml) E, but no normalized `bill_id`. **Present but optional/nullable:** USLM identifiers and law congress/document number in P’s identifiers and F(uslm-law) E. No common citation-target list. |
| **USC sections, FR citations, dockets, RINs, committee codes, dates** | **Absent as normalized capture join fields:** USC targets, dockets, RINs, committee system codes. Literal text/markup may retain them. **Present family-specifically:** FR publication date and required-but-nullable citation; USLM approved date is required-but-nullable. Evidence: all six E blocks; F(federal-register-xml) E, F(uslm-law) E. The separate citation tables supply normalized targets (`document_citation_tables.py:110–162,393–403`). |
| **Document tables and cell geometry** | **Present but optional:** core `table`/`row`/`cell`, `cell.row/column/rowSpan/columnSpan/header`, and source boxes. No requirement that cell nodes carry geometry. Current worked tables come from HTML/XML; PDF `TableObservation.cells/cell_boxes` never enter the line-based capture adapter. P `/$defs/Node/properties/cell`; `S/src/spicy_docs/extraction/model.py:98–148`; `reconstruction/evidence.py:370–394`; C:743–791. |

### Gaps, ranked by how much they block the goal

1. **No complete JSON↔XML composition.**  
   Smallest closure: **Rulespec** specifies a reversible XML representation of the captured structure, including extension values, node order, spans, cells, headings, footnotes, and provenance. **SpicyDocs** implements encoder/decoder functions and fixtures asserting full structural equality after round trip. If the desired output is publisher XML, define that family’s mapping and retain unsupported provenance in a pinned sidecar. Reuse CFR’s vocabulary serializer where appropriate. Its existing “round-trip” test checks paragraph text against published text, not DocumentCapture reconstruction (`tests/test_reconstruction.py:453–466`).

2. **PDF capture discards an available structural input: tables.**  
   `evidence_from_pages` reads assembled lines and never reads `PageResult.tables`. This is an implementation gap even though P can represent cells. **SpicyDocs** should add a reusable adapter that carries table/cell observations and geometry, preserves empty-cell versus missing-cell distinctions, and reconciles cell text with span ownership. Exercise it using the retained Senate expenditure PDFs. Preserve analytical shapers as independent consumers. For text-table joins, explicitly map normalized `BodyText` offsets to capture spans: their streams differ (`body_text.py:343–354` versus C:1630–1636).

3. **“All critical metadata” is neither carried consistently nor enforced.**  
   **Rulespec** should define shared source-record references and applicable provenance requirements; **SpicyDocs** should populate them from retained acquisition/MODS records. Keep normalized analytical relationships downstream, linked to capture evidence. Require meaningful coordinate fields when their coordinate system is stated and decisions for reconstructed nodes, including generated structural wrappers.

   A concrete correction is already necessary: C:1748–1758 records the public-law XML digest/media type with a **ZIP URL**. The retained fixture receipt distinguishes the XML member from its archive (`tests/fixtures/uslm/README.md:10–16`). Add archive/member provenance in **Rulespec**, populate it in **SpicyDocs**, and test the association. The current artifact test hashes the local file only (`tests/test_document_capture.py:193–204`).

4. **Family structure remains incompletely captured despite the visual review.**  
   Current slip-opinion output still contains **145 `line` nodes and no paragraphs**; masthead, docket, and caption remain lines. Committee reports retain flat headings and amendment summaries as paragraphs. These are acknowledged omissions, not missing core kinds. **SpicyDocs** should add narrowly evidenced rules and representative fixtures; ambiguity should remain explicit. The classifier only processes the running-head band (C:1370–1409). Compare the retained review’s S2/S5/S6 and R3/R4 findings with `docs/research/document-capture-schema-2026-09-19.md:419–441`; `classification` also remains a free string in F(slip-opinion-pdf).

5. **Validation does not fully enforce its declared tree guarantee.**  
   The spec requires parents to precede children, but the checker builds a dictionary of *all* nodes before checking parent membership; it checks depth and sibling ordinals, not parent precedence. It also lacks ID-uniqueness checks. **Rulespec** should add these checks and negative fixtures. Evidence: `R/spec/document-capture.md:89–91`; validator:115–136. These are static findings; I could not execute mutation probes.

6. **Consumer delivery and retained measurements lag the current schema.**  
   Release/package the current **Rulespec** surface, then update **SpicyDocs/SpicyRegs** pins and remove the temporary vendored loader when equality checks pass. Preserve the historical receipt, but add a separately identified current receipt: external `summary.json#/parentSchema/sha256` is `90515b…`, whereas current PINS and committed measurement use `a090fb…`. The external summary is an earlier run, not evidence for the current bytes.

### What is good and should remain

- The ownership boundary: Rulespec defines the shared shape and checks; SpicyDocs acquires and parses; DocSpec consumes captures (`S/docs/decisions.md:7–44`).
- Actual parent composition, closed extension blocks, explicit schema pins, and one invariant implementation.
- Separation of publisher bytes, extractor output, and derived text; exact spans; unresolved evidence with reasons.
- Independent text checks, namespace-aware fragment handling, and the implemented visual fixes: opinion boundaries, printed page numbering, report tables, and back matter.
- Publisher vocabulary XML with provenance outside that vocabulary, and analytical tables that do not depend on a research converter.

### What I could not check

Both permitted `uv run --frozen python ...` test invocations failed before execution because the sandbox refused access to `/Users/mikewolfd/.cache/uv/sdists-v9/.git`. I therefore report inspected coverage and retained results, not fresh test passes. I did not regenerate captures, build wheels, fetch publisher files, or repeat the visual inspection; broader family coverage remains unproved. No repository files were edited, created, or deleted.