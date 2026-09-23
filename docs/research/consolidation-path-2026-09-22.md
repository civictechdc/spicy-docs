# Consolidation path: subtract, time, then admit by reference

Status: proposal, 2026-09-22, re-validated the same day against the trees in
§10. The 2026-09-23 [survey](parsing-survey-2026-09-23.md), validated the
same evening, adds A5–A12 and B6–B12, runs B4's bakeoff and adds rulings 5–7;
its metadata pass (survey §9) adds B18–B19, C4, D6 and rulings 8–9. The same
day's filemap duplication validation (§11) confirms B9, refines B4 and adds
B13–B17. The survey supersedes the earlier
shared-catalog-admission note, which reached for
an R2 profile the work does not need. Nothing here is decided; §5 lists the
rulings. File and line cites were read on the §10 trees; re-verify before
acting on them.

## 1. The rule

Subtract first, time second, add last. Every step leaves fewer moving parts
than it found. No new sealed format, no new storage substrate, no upstream
work. Each item is a small commit behind the repo's own runner, built by a
detached Codex worker, reviewed before merge, gated before push, with the
status table in §9 updated per event and committed on its own.

## 2. What is established

The split between spicy-docs and spicy-regs is sound and mostly followed:
spicy-docs owns the contracts, shapers and rules; spicy-regs imports them and
owns the pipeline. Four copies with drift and a handful of misplaced source
rules remain (Track A and B). DocSpec is not a faster substrate for spicy-regs;
its own copy of spicy-regs tables is the duplication that costs (Track D).
Nothing in spicy-regs's merge or publish path has been timed (Track C).

| Measurement | Value | Source |
| --- | ---: | --- |
| DocSpec import of the retained Federal Register catalog, one thread | 1,007,639 rows in 16 min 49 s; 0.613 GB base Parquet; 8.80 GiB peak | `DocSpec/docs/history/probes/2026-09-14-iceberg-catalog-reimport.md:15-24` |
| DocSpec import of the retained Regulations.gov catalog | 2,221,713 rows in 50 min 42 s | same |
| Small revision after import | 0.35–1.38 s to publish | same, `:33-35` |
| Ledger overhead outside base data files | about 0.69 KB per record | derived from the rows above |
| Per-record operation path | 25 ms and about 26 KB of ledger per record | `DocSpec/docs/core-model-implementation-tasks.md:983-989` |
| Fork-host `federal-register` generation, read 2026-09-23 | 1,009,005 rows, 155,924,250 bytes, sha256 `731984ca92583f93350fa0c029d7bfa32809c0240b41b5607cd05967996bed28` | `https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/publication.json`; the 2026-09-22 read's truncated `18afcd6e…` is not recoverable in full |
| Fork-host managed families, same read | 41 on 2026-09-23; largest `court-opinion-clusters` 10.07 M rows / 3.95 GB, `fec-observations` 13.9 M rows / 1.17 GB, then `court-citations` 1.01 GB | same |

## 3. Tracks

Suggested ids are the next free ones in each repo's living plan and become
rows only on the owner's approval. SR ids are spicy-regs `PLAN.md`'s own series,
distinct from the SR01–SR15 in `remaining-gaps-2026-09-21.md`; a cite across
repositories carries the repository name (decision 15 in the spicy-regs decisions record (`docs/research/fork-delivery-decisions-2026-09-22.md`)).

### Track A. Stop the quiet bugs. Days.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| A1 | spicy-regs SR05 | Retire the legacy `congress_bills` list writer, or restrict it to columns the family writer does not own. | both console scripts `pyproject.toml:74,89`; own `_bill_id` and API `url` at `transforms/build_congress_bills.py:101,124`; coalesce merge at `transforms/table_merge.py:291-294` on a premise both writers break | one writer per column; the coalesce comment matches the code |
| A2 | spicy-regs SR06 | Carry a shaper rule version on the laws and rosters held-row skips. | skips on `update_date` alone at `transforms/build_laws.py:259` and `transforms/build_committee_rosters.py:174`; the pattern to copy at `transforms/committee_report_reads.py:39` | a changed `shape_law` or `shape_committee` republishes held rows |
| A3 | spicy-docs S33, then a wheel bump | One bill-key rule in spicy-docs; committee reports import it. Decide zero padding and unknown types once. | `int()` and `None` at `spicy-regs/.../build_committee_reports.py:188-195`; digits and fallback at `spicy-docs/src/spicy_docs/schemas/document_citation_tables.py:281` | the same MODS bill yields one key in `committee_reports`, `hearing_bill_links` and `document_citations` |
| A4 | spicy-regs docs | Correct the ownership sentence, the upstream paragraph and the docs-site link. | the **Owners:** sentence under "Consolidated task queue" in `docs/fork-generation.md`; `PLAN.md:9-24`; `mkdocs.yml:4-5`; the `origin` remote was removed 2026-09-22 | prose matches the code and the remote list |
| A5 | spicy-regs | Stop `bill_subjects` logging the Congress.gov key: delete its own client and read through `CongressListingReader` (a `bill-subjects` route) or BILLSTATUS; 401/403 abort. | key in the query at `sources/bill_subjects.py:238-244`, logged at `:347,:350`; [survey](parsing-survey-2026-09-23.md) §2 | no request of this family carries the key in its URL |
| A6 | spicy-docs, then spicy-regs | Mirrulations comment text: numeric attachment order, one tool per comment, per-attachment key/tool/digest; move the fetch to `sources/mirrulations.py`. | string sort at `spicy-regs/.../sources/derived_text.py:82`; [survey](parsing-survey-2026-09-23.md) §2, §6 | a 10-attachment comment reads 1…10; `pdf_extraction_results_json` filled; status `derived`, one tool per comment by a measured, pinned preference order (ruling 7) |
| A7 | spicy-regs, with spicy-docs' docket reader | Label-aware docket reads (spicy-docs 0.31.0's `normalize_docket_reference`, moved from RefSpec; delete the unused local copy) and unpadded FR numbers in `rule_targets`, `proceedings`, `comment_periods`; one actor-id bump per table; unresolved links stay as rows. | `build_rule_targets.py:204,222`; counts re-derived in [survey](parsing-survey-2026-09-23.md) §2 | ruling 6 |
| A8 | spicy-docs, then spicy-regs (T11) | CFR part from the volume's enclosing `PART` heading via a section-ancestry scan in `sources/cfr/annual.py`. | titles 43 and 41 wrong, 14 vol 4 NULL, plus typo and range rows; counts in [survey](parsing-survey-2026-09-23.md) §4 | MODS and eCFR agree on sampled parts; title 43 `cfr_ref` is the printed citation, and a test ties it to the Federal Register side's spelling (ruling 5) |
| A9 | spicy-docs | One bill-number reader; delete the patterns in `release_matching` and `bill_signals`. | `interpretation/release_matching.py:23-53`, `interpretation/bill_signals.py:57-63`; counts in [survey](parsing-survey-2026-09-23.md) §2 | "CR S4530" and "President's 2004" yield no bill |
| A10 | spicy-docs | `document_citations` keys: strip trailing punctuation, fold dashes, split ranges, read "Part" in any case. Folds into B4. | `interpretation/citations.py:287,446,455`; counts in [survey](parsing-survey-2026-09-23.md) §2 | every published key parses back |
| A11 | spicy-docs, then spicy-regs | Vote day as the publisher's local day in spicy-docs `votes.py`; `roll_call_votes` gets a sortable version column. | `spicy-regs/.../build_member_vote_terms.py:57-69`, `build_bill_family.py:832-880`; counts in [survey](parsing-survey-2026-09-23.md) §2 | `vote_day` agrees with the chamber's date on every vote |
| A12 | spicy-regs | One day rule for instants across the rulemaking tables, and a distinct-count check on the bill walk (after B6). Widen to `rulemaking_lifecycles`, `agency_monthly_volume` and `sources/iceberg.py`, which still take the UTC day. | [survey](parsing-survey-2026-09-23.md) §2, §11 | ruling 6 covers the table changes |
| A13 | spicy-docs, then DocSpec, spicysearch, spicyengine | One owner for the Regulations.gov day rule: deadlines are 23:59:59 Eastern, so DocSpec's `commentCloseDate` (UTC date) is one day late on every record and Engine's "through date X" filter omits documents closing on X; spicysearch's publication day is late on about 1.5%. Add the helper in spicy-docs `sources/regulations_gov` (in progress, wt/gaps); the consumers switch under ruling 10. | DocSpec `application/catalog_policy.py:80-93`; spicysearch `metadata/preparation.py:444`; spicyengine `search/queries.py:131-146`; [survey](parsing-survey-2026-09-23.md) §11 | 1,458 of 1,458 sampled deadlines; ruling 10 |
| A14 | spicy-docs | `validate_annual_cfr_xml` wrongly refuses two real volumes (combined Title 34/35; a volume with no sections); GovInfo discovery checks neither a declared count nor repeated ids; Congress.gov date windows are spelled three ways in spicy-regs. Fix the validator, add the discovery checks, and one measured window helper (in progress, wt/gaps). | [survey](parsing-survey-2026-09-23.md) §11 (map P2, P5, P12) | 262 of 262 retained volumes validate |
| A15 | spicysearch | The RIN facet publishes damaged values (98 distinct, e.g. `0648-XAO6`); use the strict published key and RefSpec's `corrected_rin` against a roster. | spicysearch `metadata/preparation.py:413-418`; [survey](parsing-survey-2026-09-23.md) §11 | no facet value outside the strict shape |

### Track B. Remove the second copies. One to two weeks.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| B1 | spicy-docs S32 | Delete `public_tables`. | no importer outside `src/spicy_docs/cli/`; DocSpec pins the `public-table` extra for its dependencies only; `docs/source-workflows.md:64` still calls it a product | `./scripts/check` green; the sentence rewritten |
| B2 | spicy-regs; the `federal_register.py` adopt row of spicy-docs `docs/simplification-todo.md` | Replace the Federal Register shaper copy with the spicy-docs projection; add `topics_json` or record why it is dropped. The readers are already gone. | own `_shape` at `transforms/build_federal_register.py:88`, column tuple `:49-73`; readers deleted in `9837fae`, `f7f5c73`, `bca689d`, `a3b3ddc`, `f808ecf` | no `_shape` left; column list equals `spicy_docs.schemas.federal_register.FEDERAL_REGISTER_COLUMNS` plus `rin` |
| B3 | spicy-regs decision, SR07 | Decide that a generation is the Parquet artifact for every managed family and the Iceberg catalog is the write side for comments and dockets with a mirror. No code. | Iceberg scope at `pipelines/regulations.py:255,354`; `docs/generation-publication.md:86` excludes it; the two paths grew from different needs (`4413ca5`, `9fd4bc5`, `de7c2a8`) | the decision names what would move a family to Iceberg: Track C numbers |
| B4 | spicy-docs S35 | Move RefSpec's `citation_grammar` and `identifier_shapes` into spicy-docs as the canonical grammar; RefSpec imports them back; spicy-regs keeps a dict reader and validators; the projection drops its copy; SpicySearch's query grammar stays behind its boundary test (§11, decision 14). The bakeoff ran in the [survey](parsing-survey-2026-09-23.md) (§5): five grammars, not three. | 1,364 / 1,042 / 789 lines in `spicysearch/src/spicysearch/identifiers.py`, `spicy-regs/src/spicy_regs/ontology/citations.py`, `spicy-docs/src/spicy_docs/interpretation/citations.py`, plus RefSpec's and rulespec-projection's | the RIN published key stays `\d{4}-[A-Z]{2}\d{2}` |
| B5 | spicy-docs S34 | Move `backfill_status` and the Senate report selection rules into spicy-docs sources. | `spicy-regs/.../build_bill_family.py:1063`; `REPORT_TITLE` at `build_senate_expenditures.py:77` | spicy-regs imports both |
| B6 | spicy-docs, then spicy-regs | Pooled enumeration (by set, not count) and a typed `DeclaredCountMismatch` in `reading/paged_json.py`; delete `pooled_walk.py` and the error-text match in `walk_route`. | [survey](parsing-survey-2026-09-23.md) §3 | CRS, amendments, FCC and bills use it |
| B7 | spicy-docs | ECFS count, ceiling and count-first splitting in `sources/fcc_ecfs.py`. | `spicy-regs/.../build_fcc_ecfs.py:197-395`; [survey](parsing-survey-2026-09-23.md) §3 | the window decision is made on page 1 |
| B8 | spicy-docs | Response-envelope checks in their readers (USAspending, CourtListener, FEC, GAO `product_id`, LDA pacing, `Retry-After`). | [survey](parsing-survey-2026-09-23.md) §3 | the spicy-regs copies are deleted |
| B9 | spicy-regs | Build the regulations host types from spicy-docs' extractors plus enrichment columns. | fork at `spicy-regs/src/spicy_regs/schemas/regulations.py`; [survey](parsing-survey-2026-09-23.md) §3 | ~220 lines deleted |
| B10 | spicy-docs, then spicy-regs | Congress routes and contracts: `bill-detail`, `CRS_REPORTS`, `BILL_VOTE_REFERENCES` with `parse_bill_id`, printing order, scope constants. | [survey](parsing-survey-2026-09-23.md) §3 | the spicy-regs shapers are deleted |
| B11 | spicy-docs | One Unified Agenda field-path projection. | spicy-regs and RefSpec navigators disagree; [survey](parsing-survey-2026-09-23.md) §3 | both consume it |
| B12 | spicy-docs | One visible-text layout in `reading/` with named profiles; pypdf and PDF folds shared; GPO normalization per collection. | [survey](parsing-survey-2026-09-23.md) §6 | DocSpec extractor v3 |
| B13 | spicy-docs S36 | Delete the source-domain drift gate fork: module, script, test and observed snapshot; spicy-regs keeps the gate, and spicy-docs keeps only the publisher-capture pins its acquisition needs. | publisher captures byte-identical in both repos while the observed halves drifted: spicy-docs pins 2026-08-03 citing the fork's old R2 URLs, spicy-regs re-pinned 2026-09-22 with the `table_urls()` fix (`15dc2d6`, `cc63661`) the fork lacks; both forks CI-gated; §11 | no drift gate outside spicy-regs; `./scripts/check` green |
| B14 | RefSpec | Migrate RefSpec's Zyte adapters, tools and tests to `spicy_docs.sources.zyte`; delete `registry/infrastructure/zyte_transport.py`. The spicy-docs decision ledger already rules the RefSpec copy a known copy, not a second design. | same fetcher written twice — identical URL, token validation and error strings; spicy-docs' is the superset (`browserHtml`, `request_id`, the reflected-credential refusal at `sources/zyte.py:296-315`); the vendored 0.26.6 wheel already contains the module; `docs/decisions.md:924-928`; §11 | no second Zyte protocol implementation; RefSpec's tests expect the credential-reflection refusal |
| B15 | RefSpec, at the next scheduled rebuild | Re-point `usc_act_index.py` and `tools/build_usc_popular_names.py` at `sources/uscode/table3.py` and `sources/uscode/popular_names.py`; re-pin per the rebuild runbook. | both parse the same OLRC Table III bulk XML and Popular Name Tool page with independent stdlib parsers; RefSpec's copies predate the spicy-docs routes (2026-08-31/09-05 vs 2026-09-14); §11 | rebuild, adjudicated delta, re-pin; the provenance test forces the re-pin |
| B16 | RefSpec, at cache regeneration | Extract the eCFR authority-notes cache through `sources/cfr/authority.py` instead of the local research scripts; re-pin. | the frozen 2026-08-24 cache was extracted by independent stdlib scripts from unretained full-title XML; the reusable scanner post-dates it; §11 | parse deltas surface as counted differences at re-pin |
| B17 | spicy-regs | Extract the shared candidate-selection, partition-walk and catalog-upsert driver behind `enrich_pdf.py` and `backfill_derived_text.py`; the two text sources stay distinct. | near-identical candidate SQL (`enrich_pdf.py:493-501` vs `backfill_derived_text.py:352-360`) and twin mains, about 200 lines; the docstring names the sibling; both touch the durable R2 catalog write path; §11 | both CLIs' dedicated tests stay green on the shared driver |
| B18 | spicysearch, then spicy-regs | Delete spicysearch's unread vendored `vendor/spicy-regs-catalog-dictionary.json` (with its sidecar and source-commit record), and spicy-regs' obligation to re-vendor it (`spicy-regs/PLAN.md:164-181`; stale `README.md:309`, "24 → 45 classes"). By ruling 8, also delete spicy-regs' `data_dictionary/catalog.json`, its `.sha256` sidecar, the `catalog` subcommand and its tests; `table_metadata.json` stays. | no reader (rg); stale: 75 classes against 79; [survey](parsing-survey-2026-09-23.md) §9 | nothing in spicysearch references spicy-regs' catalog |
| B20 | spicy-docs, then spicy-regs, spicysearch and rulespec-projection | Move RefSpec's `iri_minting` into spicy-docs beside the grammar (in progress, wt/iri); spicy-regs drops `_agenda_item_id` and its seven minters, spicysearch and the projection their copies. Whether spicy-regs adopts the Federal Register document-number space (`urn:spicy-regs:frdoc` → rkaf; 429,131 values) is ruling 11. | spicy-regs `build_regulatory_agenda.py:78`, `ontology/citations.py:390-620`; {SV} §11 | RIN, CFR and EO minting agree 100% on the retained tables |
| B21 | RefSpec, after its repin | RefSpec imports the spicy-docs readers it re-writes (`parse_ecfr_titles`, the CBO estimates feed, the source-domain code parsers, `PypdfReader`, `read_html_events`, `parse_xml`, `load_bounded_json`), folding its stricter refusals into spicy-docs first and keeping the old parsers as test oracles; collapse its 28 `_verify_payload`/`_publish_payload` copies (2,629 lines) onto one pinned-acquisition helper. | {SV} §11 | RefSpec's gate green with the old parsers as oracles |
| B22 | RefSpec | One docket reader: `agency_crosswalk.normalize_docket_id` delegates to the moved docket reader, keeping its whitespace fold (17,016 more links join; 101 only the crosswalk reads). | RefSpec `agency_crosswalk.py:176`; {SV} §11 | spicysearch's docket facets gain the links |
| B23 | spicysearch | Delete the orphaned half of `identifiers.py` (field classifiers, `is_cfr_section`, `unread_identifier_shapes`, `identifier_values`; about 400 lines with no callers since `0422da3`) and its contract-test halves; `canonical.py` delegates to `rulespec_artifacts`; D6 reads `sourceObservedTopics` instead of re-deriving topics. | {SV} §11 | no caller lost; digests unchanged |
| B24 | spicy-regs | `bill_subjects` from BILLSTATUS (one request per bill today, silently stopping after 4 pages), the API only below the 108th Congress; adopt `match_member`, `parse_package_id().collection`, `parse_xml` and `load_integer_json` where spicy-regs re-implements them (in progress, wt/regs-gaps). | {SV} §11 (map P6, P14) | published subjects unchanged |
| B25 | spicy-regs | The remaining map gaps: `enrich_pdf` through `RegulationsGovAttachmentAcquirer` (with B17); one versioned rulemaking-stage rule (proceedings vs lifecycles); A7 widened to `fr_docket_links.docket_id`; the vote version columns after the backfill; timetable dates, RSS `pubDate` and FEC id shapes through spicy-docs; a public capture hook and an FR record-id decoder; one watermark and one env helper for the seven and five copies. | {SV} §11 (map P3, P8–P11, P13, P14) | each copy deleted with a test |
| B26 | spicy-docs, then each family | Table contracts and projections for the non-Congress families (lobbying, SAM, USAspending, CourtListener, FCC, FEC, agenda, GAO), which today have only spicy-regs `_shape` functions; gives D3 and D6 an identity source. | {SV} §11 (map P7) | every published table has a contract |
| B27 | RefSpec | Use rulespec-conformance's release digest (`reference_release_digest.compute_digest`) instead of its copy in `atlas/model.py:125`, which differs on 4 of 11 control-character literals (latent); delete the unused shell-out in `release_graph.py:395`; keep the copy as a test oracle. | [survey](parsing-survey-2026-09-23.md) §11 | atlas digests unchanged on current data |
| B28 | spicy-docs | Adopt rulespec-artifacts' v2 DocumentCapture provenance checks and delete `schemas/document_capture/provenance.py` (253 lines; accepts 4 malformed inputs rulespec rejects); move the seven captures, `PINS.json` and the family profiles to v2. | [survey](parsing-survey-2026-09-23.md) §11 | rulespec's retained replay reproduces the seven captures |
| B29 | rulespec-extrapolator, after B4 | Read references with spicy-docs' grammar instead of spicysearch's query grammar (`references.py:19,69`; spicysearch 0.2.0 pinned, current 0.4.2); B4 first adds position-returning readers for public laws, Statutes at Large, executive orders, dockets and RINs. | [survey](parsing-survey-2026-09-23.md) §11 | spicysearch and DocSpec leave the extra's dependencies |
| B30 | spicy-regs, spicyengine, RefSpec | One canonical-JSON helper (`rulespec_artifacts`; byte-identical on 2,204,970 of 2,204,970 values; keep the projection's copy, which digests floats) and one exported `verify_file_pin` for the five pinned-file hashers. | [survey](parsing-survey-2026-09-23.md) §11 | no identifier changes |
| B31 | spicy-docs, then spicy-regs | Multi-part committee reports as one row per part (ruling 13): read constituent parts from a package's MODS, carry `part_id` and `part_number` in the report contracts with identity `(package_id, part_id)` (`committee_report_reads` stays keyed by package; parts replaced as a set), and until spicy-regs adopts it, hold any part-only row (`part_id` set) out of the table. | wt/pt1 records `part_id`; 119hrpt455, 119hrpt620, 108hrpt24 offer nothing at package level; 119hrpt494 reads Part 1 silently | hrpt811, hrpt494 and the two-part reports each publish every published part |
| B19 | spicy-regs | Build `DERIVED_SCHEMAS` from the producers' column constants (18 of 26 entries repeat one) and declare identity beside each transform's `COLUMNS` (23 of 74 published tables have none in `table_metadata.json`); after B2, FR's list is `FEDERAL_REGISTER_COLUMNS + ("rin",)`. Gives D3 an identity source. | `src/spicy_regs/data_dictionary.py:250-648`; [survey](parsing-survey-2026-09-23.md) §9 | catalog bytes unchanged; every published table declares identity |

### Track C. Put a timer on it. Parallel, cheap.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| C1 | spicy-regs SR08 | Phase timers on one real bill-family run: fetch, shape, merge, generation build, upload, read-back. | no timer in `pipelines/rollups/base.py`, `generations.py`, `sources/publication.py`, `transforms/table_merge.py`; structural costs: full rewrite and sort per table (`table_merge.py:282-325`), serial re-upload with read-back (`publication.py:388-403`), about three decodes per table (`generations.py:151-172`) | numbers in the fork output ledger |
| C2 | spicy-regs, existing fork-generation item | Time one comments sweep, then apply the written agency partition if it pays. | catalog unpartitioned; `PARTITION BY` at `sources/iceberg.py:232` is a window, not a table partition; plan and probe under "Catalog performance: partition the comments table by agency" in `docs/fork-generation.md`, `scripts/probe_iceberg_partition.py` | before and after per-batch index rebuild time |
| C3 | spicy-regs decision | Only with C1 numbers, decide whether the three large families (`court-opinion-clusters`, `fec-observations`, `court-citations`) become Iceberg snapshots plus a Parquet mirror. | sizes in §2 | — |
| C4 | spicy-regs | Time the MCP server's cold start (it re-reads every table's footer, about 35 s) and, if it is the cost, read columns from `publication.json`. | `src/spicy_regs/mcp_server.py`; [survey](parsing-survey-2026-09-23.md) §9 | measured before and after |

### Track D. The one addition: DocSpec admits generations by reference, locally. After A and B1.

Engine PM01 (`spicyengine/PLAN.md`) already derives prepared metadata from the
row-copied catalog states this track replaces. Its steps 1–3 are implemented;
the gate, the Search 0.5.0 and Engine 0.8.0 releases and the cutover from the
8091 index remain. D1 names occurrences by a hash of pin and key, so an
admitted state is likely a new state rather than a revision of the copied one:
the first derive over it would then be a full derive, and Engine would
republish every row once. Ruling 4 in §5 orders the two.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| D1 | DocSpec decision 0007 | A table-shaped state may be a pinned copy of a producer's sealed artifact, stored locally like every other layer, one ledger row per generation, occurrence ids by hash of pin and key. | the model permits it (`docs/core-model.md:72,82,104,146`); the implementation refuses it (`adapters/storage/records.py:287,457`); Search 0008 condition 5 is met by a copy in the workspace | owner ruling |
| D2 | DocSpec spike, one hour | Does `iceberg_scan` read Parquet without Iceberg field ids through a name mapping on the local fixture? Fallback: one vectorized `CREATE TABLE AS SELECT` through the REST fixture. | reads are catalog-free at `records.py:340`; `pyiceberg==0.12.0`, `rulespec-artifacts==1.1.1` pinned | answer recorded with its receipt |
| D3 | DocSpec C27 | Admission: read `publication.json`, admit the root and members through the rulespec admission DocSpec already uses, download the members, register into a local Iceberg table, pin the metadata, write one ledger row. Identity source order: artifact fields if present, else `spicy_docs.schemas.TABLE_CONTRACTS`, else DocSpec decision 0003 for Federal Register, else refuse. | — | §6 |
| D4 | DocSpec C28 | Delete the row-copy catalog example once D3 passes. Admit comments from spicy-regs's catalog by a pinned-snapshot copy, which needs a read token. | `examples/spicyregs_comments.py`; `docs/spicyregs-comments.md:67` | example gone; comments admitted by snapshot id |
| D5 | DocSpec 0.10.0; spicysearch; spicyengine | Release; delete identifier enrichment in favour of derive over the admitted state: in spicysearch `catalog_enrichment.py`, the `enrich-identifiers` command, its test and doc; in spicyengine `indexing/enrichment.py`, `load --enrichment` and `tools/check_enrichment.py`; in DocSpec `runtime/selected_outputs.py`, left without a caller. | 0.9.1 (`2cdde74`) is 0.9.0's code on SpicyDocs 0.26.6 and Rulespec Artifacts 1.1.1, and Search `b150fdd` and Engine `31f7959` already pin `docspec==0.9.1`, `spicy-docs==0.26.6` and `rulespec-artifacts==1.1.1`; PM01 already deleted metadata's per-record path (`spicysearch/PLAN.md`, Prepared metadata) and derives at `spicysearch/src/spicysearch/metadata/enrichment.py:159,176`; identifier enrichment still calls `resolve_many` at `spicysearch/src/spicysearch/catalog_enrichment.py:123`, Engine reads its outputs through `open_selected_outputs` at `spicyengine/src/spicyengine/indexing/enrichment.py:45`, and no Search plan row retires it; measured, it added no key the prepared identifiers lacked on 8,663 records and costs one DocSpec operation per record (≈7 h / 26 GB for 1.0M FR records), [survey](parsing-survey-2026-09-23.md) §9 | no `resolve_many` or `open_selected_outputs` caller left outside DocSpec |
| D6 | spicysearch | A preparer reader for rows shaped like spicy-regs generations, keyed on spicy-docs' `TABLE_CONTRACTS` (0.26.6 covers 38 of 39 tables as 0.29.0 does); today `prepare` refuses them ("requires exactly one identity-matched native fact"). Needed before D5's derive over admitted generations. | `spicysearch/src/spicysearch/metadata/preparation.py:164`, refusing through `source_facts` at `:83`; [survey](parsing-survey-2026-09-23.md) §9 | prepared values over a generation equal those over the source state for the same records |

## 4. Sequence

- Week one: A1–A4, C1, D1, D2.
- Week two: B1, B2, D3.
- Week three: B3, D4, D5, C2.
- After: B4 and B5, now that the bakeoff has run (survey §5); C3 behind C1's
  numbers.
- From the survey: A5 first, then A6–A11; A12 after B6. B6–B11 before B12,
  which is large and changes DocSpec output; B18–B19 with B9; D6 before D5.
- From §11: B13 with week two; B14 when RefSpec next re-vendors; B15–B16 ride
  the scheduled rebuilds and cache regenerations; B17 independently.
- PM01's remaining steps sit before or after D3, as ruling 4 decides.

## 5. Rulings this plan needs

1. Decision 0007 as stated in D1.
2. The generation decision in B3.
3. The bill-key rule in A3: zero padding and unknown types.
4. Whether PM01 cuts over on the row-copied catalog states and D5 re-derives
   after D3, or PM01's cutover waits for D3.
5. `cfr_ref` for title 43's subpart-numbered sections (A8). **Decided:** the
   printed citation (`43-1601.0-1`), with part 1600.
6. Whether the rulemaking tables admit label-derived dockets and unpadded FR
   numbers, changing three published tables (A7, A12). **Decided:** both, one
   actor-id bump per table.
7. The comment text status without an extraction record, and which
   Mirrulations tool wins (A6). **Decided:** `derived`; one tool per comment by
   a measured, pinned preference order.
8. Keep `catalog.json`, or keep only `table_metadata.json` (B18). **Decided:**
   only `table_metadata.json`.
9. Who normalizes Federal Register and Regulations.gov search fields:
   DocSpec's stored `normalizedMetadata` or spicysearch's preparer (D6, with
   D3). **Decided:** spicysearch for now; spicy-docs after D3.
10. Whether DocSpec's Regulations.gov policy version moves so that `commentCloseDate` and the publication day use the Eastern rule (A13); it changes every stored deadline. **Decided:** not now; spicysearch and Engine derive their day fields through the spicy-docs helper, and DocSpec's policy moves with the Track D rebuild (decision 26).
11. Whether spicy-regs mints Federal Register document-number IRIs in RefSpec's rkaf space instead of `urn:spicy-regs:frdoc` (B20; 429,131 values). **Decided:** the rkaf spaces; no published column carries the local prefix, so nothing moves (decision 27).
12. Where the IRI minters live (B20): spicy-docs as standard-library modules beside the grammar, which reaches spicy-regs at once, or Rulespec Core per REF-024, which would add `rulespec-conformance` (rdflib, pyshacl) to spicy-regs; the identifier shapes stay in spicy-docs either way. **Decided:** spicy-docs; REF-024's wording is narrowed so Core owns the lexical spaces, an amendment Mike confirms (decision 28).
13. How the committee-report tables represent multi-part GovInfo reports (the `-pt1` fix on wt/pt1 records a `part_id` no table carries). **Decided:** one row per part, identity `(package_id, part_id)` plus `part_number`; `committee_report_reads` stays keyed by package; hold `CRPT-119hrpt811` out until it lands (decision 29; Mike confirms the identity move).

Rulings 5–12 were decided on 2026-09-23 by delegation, with reasons, as decisions
17–21 and 26–28 in the spicy-regs decisions record (`docs/research/fork-delivery-decisions-2026-09-22.md`); the owner can overturn any of them.

Everything else is a reversible commit.

## 6. The gate that decides Track D

- **Claim:** D3 admits the fork-host `federal-register` generation into a
  state whose contract columns equal the retained catalog from the 2026-09-14
  reimport probe on every document number that catalog holds.
- **Population:** the generation pinned in §2, all 1,009,005 rows.
- **Reference:** the retained probe catalog (`catalog-B-composite`, 1,007,639
  records per `DocSpec/docs/history/probes/2026-09-14-iceberg-federal-register-reimport.json`),
  built by the row-copy path, so the reference does not recompute the rule
  under test. The counts differ, so a zero-row two-way `EXCEPT` over all rows
  is impossible.
- **Threshold:** two-way `EXCEPT` on the contract columns over the
  reference's (`document_number`, `publication_date`) keys returns zero rows in
  both directions; generation-only keys are counted, each must post-date
  2026-09-14, and any exception is listed by key in the receipt (decision 25);
  wall time, bytes downloaded, ledger bytes per record and peak memory
  recorded beside the 16 min 49 s, 0.69 KB and 8.80 GiB baselines.
- **What would make a clean result wrong:** a comparison in the same engine
  session that admitted the rows; the comparison opens a fresh process. A
  zero-row `EXCEPT` over an empty or narrowed key set also passes; the test
  first asserts the admitted record count equals the artifact's `recordCount`
  and the compared-key count equals the reference's record count.
- **Falsifier:** if wall time is not materially below the baseline, the row
  re-encode was not the cost and Track D stops at D2.
- **Receipt:** `~/Work/corpora/supply-2026-09-02/receipts/consolidation-path-2026-09-22/`.

## 7. Not doing

- A remote object-store profile for DocSpec. Everything in the DocSpec, Search
  and Engine chain reads locally today. Off-machine readers would be a new
  ruling.
- Pointing DocSpec at spicy-regs's catalog without a copy. Only comments and
  dockets are in it, spicy-regs mutates and may expire snapshots, and Search
  0008 forbids it.
- New artifact fields in the spicy-regs generation root. D3's identity source
  order covers the first families without them.
- Anything on upstream `civictechdc`.

## 8. Risks and what reverses the plan

| Risk | Handling | Reverses the plan if |
| --- | --- | --- |
| `iceberg_scan` cannot read files without field ids (D2) | vectorized `CREATE TABLE AS SELECT` fallback | both paths fail the §6 wall-time falsifier |
| The bill-key decision (A3) changes published keys | rule version on the affected tables (A2) carries the correction | — |
| Deleting `public_tables` (B1) removes a CLI command someone uses | the release format and its readers stay; only the projection path goes | a consumer of `publish-public-table` appears |
| C1 shows the rewrite is not the cost | C3 is not taken; B3 stands | — |

## 9. Status

Update one row per event; commit each update on its own.

| Item | Status | Evidence |
| --- | --- | --- |
| A1 | proposed; url provenance labelled (`6d34a1b`, a spicy-regs commit) | — |
| A2 | proposed | — |
| A3 | proposed; disagreement measured 2026-09-23, latent in published keys; also covers `house_committee_repository`'s `bill_key_*` | [survey](parsing-survey-2026-09-23.md) §3, §11 |
| A4 | proposed; remote removed 2026-09-22 | git config only |
| A5 | done in spicy-regs `81cfee7` (pushed 2026-09-23): key only in `X-Api-Key`, no URL or exception text in logs, 401/403 abort, redirects not followed (decision 23); the reader route stays with B10. spicy-docs `sources/congress/crs_summaries.py:54-60` still puts the key in the query but scrubs errors before writing them (its rule 5); moving it to the header would retire the scrub | [survey](parsing-survey-2026-09-23.md) §2 |
| A6 | spicy-docs done (`d12c17b`, in 0.30.0); spicy-regs on wt/regs-a6 (`f90cc2d`, reviewed): the 65,994-row repaired staging is built into a `comments.parquet` candidate whose other 23,824,409 rows equal the live parent, awaiting publication | [survey](parsing-survey-2026-09-23.md); receipt `comment-text-repair-2026-09-23/` |
| A7 | code complete and reviewed on wt/regs-a7 (`cbb7b04`, `ac836d9`): label-aware docket reads, unpadded FR keys that refuse different-width padding, folds named in status; the candidate is rebuilt and published after the 0.31.0 re-vendor | [survey](parsing-survey-2026-09-23.md); receipt `rulemaking-joins-2026-09-23/` |
| A8 | done: spicy-docs 0.30.0 scan (`eae0812`, `1183d0c`); spicy-regs `5f4423c` places from the heading with a publish-first marker; `cfr_sections` republished at `de703ffe…` (2026-09-23) and its workflow re-enabled; title 41 citations join after A7 | receipt `cfr-ancestry-fix-2026-09-23/` |
| A9 | proposed | [survey](parsing-survey-2026-09-23.md) |
| A10 | in progress (wt/b4, under rework); gate: RefSpec's `usc_section_oracle` finds 331 unresolvable rows | [survey](parsing-survey-2026-09-23.md) §2, §11 |
| A11 | done: spicy-docs 0.30.0 owns `vote_day` and appends `roll_call_votes.vote_day` (`c5bd161`, `6e1bb3b`); spicy-regs `57a68bc` backfills prior rows and adds `term_match = undated`; the version column stays `vote_date` until the backfill is published (next scheduled roll-call run) | receipt `vote-day-2026-09-23/`, `vote-day-backfill-2026-09-23/` |
| A12 | rulemaking half on wt/regs-a7 with A7 (one Eastern-day rule, `eastern_day` → `regulations_gov_day` at the re-vendor); the bill-walk distinct count follows B6; the wider tables stay proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| A13 | spicy-docs helper done (`b4fd806`, `1f80bee`, on the 0.31.0 release branch); DocSpec, spicysearch and spicyengine adoption proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| A14 | spicy-docs done (`5847505`, `4c67e1e`, `a17fa2f`, `197937c`, on the 0.31.0 release branch); spicy-regs `acquire_annual` adopts the validator at the re-vendor (`TODO(A14)` in `sources/cfr_sections.py`) | [survey](parsing-survey-2026-09-23.md) §11 |
| A15 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B1 | proposed | — |
| B2 | partial: readers deleted on main; shaper copy remains (re-confirmed 2026-09-23) | `9837fae`…`f808ecf`; `build_federal_register.py:88` |
| B3 | proposed | — |
| B4 | bakeoff run 2026-09-23; move proposed | [survey](parsing-survey-2026-09-23.md) §5 |
| B5 | proposed; re-confirmed 2026-09-23 | [survey](parsing-survey-2026-09-23.md) |
| B6 | spicy-docs done (`9d53b32`…`61c86c1`, on the 0.31.0 release branch): pooled identities across up to four differently paged walks, settled on a clean walk or a pool equal to the declared count, typed `DeclaredCountMismatch`/`DeclaredCountChanged`/`IncompleteWalkError`; spicy-regs adoption on wt/regs-b6 (`41054ee`) awaits the re-vendor | [survey](parsing-survey-2026-09-23.md) |
| B7 | proposed | [survey](parsing-survey-2026-09-23.md) |
| B8 | proposed | [survey](parsing-survey-2026-09-23.md) |
| B9 | proposed | [survey](parsing-survey-2026-09-23.md) |
| B10 | proposed; the key resolver is copied in nine spicy-regs modules, not five | [survey](parsing-survey-2026-09-23.md) §11 |
| B11 | spicy-docs done (`1967f7d`, `3c62e5d`, on the 0.31.0 release branch); RefSpec and spicy-regs adopt it at their repins | [survey](parsing-survey-2026-09-23.md) §11 |
| B12 | proposed | [survey](parsing-survey-2026-09-23.md) |
| B13 | proposed | §11 |
| B14 | proposed; wheel API parity unverified | §11 |
| B15 | proposed; rides the next scheduled rebuild | §11 |
| B16 | proposed; rides cache regeneration | §11 |
| B17 | proposed | §11 |
| B18 | proposed | [survey](parsing-survey-2026-09-23.md) §9 |
| B19 | proposed | [survey](parsing-survey-2026-09-23.md) §9 |
| B20 | spicy-docs on wt/iri (`46aea16`, on the B4 rework): reviewed, byte-identical to RefSpec's minter on 3,966,225 paired calls except the `-RULE`-family docket suffixes B4 admits; merges with B4 into 0.31.0; its home is ruling 12; REF-024's wording amendment awaits Mike (decision 28) | [survey](parsing-survey-2026-09-23.md) §11 |
| B21 | proposed; after RefSpec repins | [survey](parsing-survey-2026-09-23.md) §11 |
| B22 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B23 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B24 | in progress (wt/regs-gaps) | [survey](parsing-survey-2026-09-23.md) §11 |
| B25 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B26 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B27 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B28 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B29 | proposed; after B4 | [survey](parsing-survey-2026-09-23.md) §11 |
| B30 | proposed | [survey](parsing-survey-2026-09-23.md) §11 |
| B31 | spicy-docs on wt/parts (`2bdd428`): reviewed and fixed (a NULL part refuses, a 1..N part set is required, a budget refusal precedes any body request); held out of 0.31.0 until Mike confirms the identity move, and spicy-regs must adopt (pass `part_id`, backfill `COALESCE(part_id, package_id)`, merge `committee_reports` with `replace_parents` by package, size `BODY_BUDGET` per part) in the same release it vendors | decision 29 |
| C1 | proposed | — |
| C2 | proposed | — |
| C3 | not before C1 | — |
| C4 | proposed | [survey](parsing-survey-2026-09-23.md) §9 |
| D1 | proposed | — |
| D2 | proposed | — |
| D3 | proposed | — |
| D4 | proposed | — |
| D5 | partial: PM01 deleted metadata's per-record path; Search and Engine already on 0.9.1; identifier enrichment left in Search, Engine and DocSpec, scope extended to delete it | `spicysearch/PLAN.md`; `catalog_enrichment.py:123`; `spicyengine/.../indexing/enrichment.py:45`; [survey](parsing-survey-2026-09-23.md) §9 |
| D6 | proposed; before D5 | [survey](parsing-survey-2026-09-23.md) §9 |

## 10. Baseline trees and sources

Validated 2026-09-22 against: spicy-docs `6673fa3`, spicy-regs `bf35bc9`,
DocSpec `2cdde74`, spicyengine `056cb04`, spicysearch `66a0eb1`. The
2026-09-23 survey read spicy-docs `5d8c396`, spicy-regs `5780702`, RefSpec
`f83c0d7a`, DocSpec `2cdde74`, spicyengine `31f7959`, spicysearch `b150fdd` and
rulespec `23d5f2d9`. The fork's output ledger and backlog (spicy-regs
`docs/research/fork-output-ledger-2026-09-21.md`, `docs/fork-generation.md`)
track which published tables items A5–A12 touch. The §11 validation passes
read the 2026-09-23 working trees without commit pins and ran no repository
gate. A1's and C1's line cites were re-read at spicy-regs `b89c7dc`.

- DuckDB iceberg extension, catalogs and writing.
  <https://duckdb.org/docs/current/core_extensions/iceberg/catalogs>
  <https://duckdb.org/docs/current/core_extensions/iceberg/writing_to_iceberg>
- PyIceberg API, `add_files`. <https://py.iceberg.apache.org/api/>

## 11. Filemap duplication validation, 2026-09-23

A scan of the workspace filemap's descriptions flagged candidate duplications
across and inside repositories; four parallel validation passes then read the
code, decision records and git history on the working trees. Most flags were
the intended layering — one parser, several owners adding acceptance rules,
pins or normalization on top through vendored wheels. The residue is below;
confirmed items entered Track B as B13–B17, and the refutations are recorded
so the next scan does not re-flag them.

| Flag | Verdict | Disposition |
| --- | --- | --- |
| `schemas` package, spicy-docs vs spicy-regs | fork mid-migration: extract functions identical except `pdf_extraction_results_json` and the polars column types; `pipelines/repair_regulations.py` already runs spicy-docs extract against the host schema while `pipelines/regulations.py` still runs the local fork; no equivalence test exists | confirms B9; add a test asserting both extract implementations agree on shared fixtures |
| Zyte fetcher, RefSpec vs spicy-docs | same fetcher written twice; the spicy-docs ledger already names the RefSpec copy "a known copy, not a second design", and the vendored 0.26.6 wheel contains the shared module | B14 |
| OLRC Table III bulk and Popular Names parsers | RefSpec parses both artifacts with independent stdlib parsers that predate the spicy-docs routes (which landed 2026-09-14) | B15 |
| eCFR authority-notes cache | frozen 2026-08-24 cache extracted by independent research scripts from unretained XML; the reusable spicy-docs scanner post-dates it | B16 |
| `enrich_pdf` / `backfill_derived_text` drivers | complementary text-fill gates, but parallel partition/catalog scaffolding of about 200 lines | B17 |
| source-domain drift gate | the whole gate exists twice; publisher captures byte-identical, observed snapshots drifted apart, and the spicy-regs copy carries fixes the fork lacks | B13 |
| citation grammars | RefSpec's `citation_grammar` is the declared union and spicysearch's preparation path already imports it; spicy-regs' serving grammar and spicysearch's query grammar stay independent by adjudicated boundary | refines B4: move spicy-regs only on a measured disagreement on real corpus data, under a contract test over the bakeoff corpus (survey §5), never the sealed query-side shapes |
| DocSpec blob store | D31's two blockers (ctime false-positive, root pinning) are fixed in the vendored rulespec-artifacts; Core C07's retention now rests on sequencing, not incompatibility | DocSpec C07 owns it: bounded retry with the existing concurrency probe as the gate; not a row here |
| `billstatus_codes`; FR topics reader; List of Subjects; Unified Agenda; CourtListener listing; `with_iceberg`; the two filemap generators; spicy-docs' two Zyte modules; the Iceberg trio; the PDF-text trio; sealed canonical-JSON emitters; blob wrappers | intentional layering: one parser or one delegation, several owners; each borrow is docstring- or ledger-recorded | no action |
| identifier shapes, spicysearch vs RefSpec | contract-governed dual implementation: boundary test, exception table and wheel-digest tripwire re-exercised 2026-09-22 (325 checks pass, the 99 adjudicated divergences skip unchanged) | no action; re-measure at every re-vendor |
| spicysearch `wiki/` | generated 2026-09-01, two days before the runtime retirement; the ten flagged pages describe code deleted 2026-09-21, and only the README disclaims it | S, spicysearch's plan: retire `wiki/http_api.md` beside the retired API spec; banner or regenerate the rest |
| spicysearch run-notes pair | `docs/history/2026-09-02-reference-run-notes.md` and `2026-09-02-semantic-p3-round1-RUN_NOTES.md` are byte-identical, both carrying the same wrong self-referencing H1 | S, spicysearch's plan: keep one, leave a stub at the other name |
| agency rollups wrapper; court-dockets API/bulk pair; text-fill cascade; RefSpec explorer JS port; rulespec stub and oracle | documented layering (compat wrapper, candidate-vs-live routes, gated cascade, local/deployed pair, prescribed oracle) | no action; optional attribution fixes where the data dictionary still credits the wrapper |

Premises the scan got wrong, corrected during validation: RefSpec's
`storage.py` holds canonical JSON and Parquet helpers, not blob storage;
rulespec's `atlas_membership_stub` is an original seam that removed vendored
RefSpec code, not a copy; and the UI-migration note expected at
`spicyengine/docs/history/` lives only in spicysearch. The validation passes
ran no repository gate, pinned no commits, and did not diff the vendored
`spicy_docs` wheel against the checkout — B14 in particular needs the wheel's
API checked before migration.
