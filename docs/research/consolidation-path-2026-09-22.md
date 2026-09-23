# Consolidation path: subtract, time, then admit by reference

Status: proposal, 2026-09-22, re-validated the same day against the trees in
§10. It supersedes the earlier shared-catalog-admission note, which reached for
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
| Fork-host `federal-register` generation, read 2026-09-22 | 1,008,903 rows, 155.9 MB, sha256 `18afcd6e…` | `https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/publication.json` |
| Fork-host managed families, same read | 27; largest `court-opinion-clusters` 10.07 M rows / 3.95 GB, `fec-observations` 13.9 M rows / 1.17 GB | same |

## 3. Tracks

Suggested ids are the next free ones in each repo's living plan and become
rows only on the owner's approval.

### Track A. Stop the quiet bugs. Days.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| A1 | spicy-regs SR05 | Retire the legacy `congress_bills` list writer, or restrict it to columns the family writer does not own. | both console scripts `pyproject.toml:73,88`; own `_bill_id` and API `url` at `transforms/build_congress_bills.py:101,124`; coalesce merge at `transforms/table_merge.py:287` on a premise both writers break | one writer per column; the coalesce comment matches the code |
| A2 | spicy-regs SR06 | Carry a shaper rule version on the laws and rosters held-row skips. | skips on `update_date` alone at `transforms/build_laws.py:259` and `transforms/build_committee_rosters.py:174`; the pattern to copy at `transforms/committee_report_reads.py:39` | a changed `shape_law` or `shape_committee` republishes held rows |
| A3 | spicy-docs S33, then a wheel bump | One bill-key rule in spicy-docs; committee reports import it. Decide zero padding and unknown types once. | `int()` and `None` at `spicy-regs/.../build_committee_reports.py:189-196`; digits and fallback at `spicy-docs/src/spicy_docs/schemas/document_citation_tables.py:281` | the same MODS bill yields one key in `committee_reports`, `hearing_bill_links` and `document_citations` |
| A4 | spicy-regs docs | Correct the ownership sentence, the upstream paragraph and the docs-site link. | `docs/fork-generation.md:406`; `PLAN.md:9-24`; `mkdocs.yml:4-5`; the `origin` remote was removed 2026-09-22 | prose matches the code and the remote list |

### Track B. Remove the second copies. One to two weeks.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| B1 | spicy-docs S32 | Delete `public_tables`. | no importer outside `src/spicy_docs/cli/`; DocSpec pins the `public-table` extra for its dependencies only; `docs/source-workflows.md:64` still calls it a product | `./scripts/check` green; the sentence rewritten |
| B2 | spicy-regs, existing M-series | Replace the Federal Register shaper copy with the spicy-docs projection; add `topics_json` or record why it is dropped. The readers are already gone. | own `_shape` at `transforms/build_federal_register.py:88`, column tuple `:49-73`; readers deleted in `9837fae`, `f7f5c73`, `bca689d`, `a3b3ddc`, `f808ecf` | no `_shape` left; column list equals `spicy_docs.schemas.federal_register.FEDERAL_REGISTER_COLUMNS` plus `rin` |
| B3 | spicy-regs decision, SR07 | Decide that a generation is the Parquet artifact for every managed family and the Iceberg catalog is the write side for comments and dockets with a mirror. No code. | Iceberg scope at `pipelines/regulations.py:255,353`; `docs/generation-publication.md:86` excludes it; the two paths grew from different needs (`4413ca5`, `9fd4bc5`, `de7c2a8`) | the decision names what would move a family to Iceberg: Track C numbers |
| B4 | spicy-docs S35, gated | Run the existing bakeoff over the three citation grammars; spicy-docs owns the grammar, spicy-regs keeps IRI expansion, SpicySearch imports. | 1,364 / 1,042 / 789 lines in `spicysearch/src/spicysearch/identifiers.py`, `spicy-regs/src/spicy_regs/ontology/citations.py`, `spicy-docs/src/spicy_docs/interpretation/citations.py` | not scheduled before the bakeoff report |
| B5 | spicy-docs S34 | Move `backfill_status` and the Senate report selection rules into spicy-docs sources. | `spicy-regs/.../build_bill_family.py:1063`; `REPORT_TITLE` at `build_senate_expenditures.py:77` | spicy-regs imports both |

### Track C. Put a timer on it. Parallel, cheap.

| Item | Repo, id | What | Evidence at HEAD | Gate |
| --- | --- | --- | --- | --- |
| C1 | spicy-regs SR08 | Phase timers on one real bill-family run: fetch, shape, merge, generation build, upload, read-back. | no timer in `pipelines/rollups/base.py`, `generations.py`, `sources/publication.py`, `transforms/table_merge.py`; structural costs: full rewrite and sort per table (`table_merge.py:290-321`), serial re-upload with read-back (`publication.py:360-363`), about three decodes per table (`generations.py:151-172`) | numbers in the fork output ledger |
| C2 | spicy-regs, existing fork-generation item | Time one comments sweep, then apply the written agency partition if it pays. | catalog unpartitioned; `PARTITION BY` at `sources/iceberg.py:232` is a window, not a table partition; plan and probe at `docs/fork-generation.md:482-502`, `scripts/probe_iceberg_partition.py` | before and after per-batch index rebuild time |
| C3 | spicy-regs decision | Only with C1 numbers, decide whether the three large families become Iceberg snapshots plus a Parquet mirror. | sizes in §2 | — |

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
| D5 | DocSpec 0.10.0; spicysearch | Release; retire identifier enrichment's per-record path, a standalone command outside Engine's chain, in favour of derive over the admitted state. | 0.9.1 (`d66aebb`) is 0.9.0's code on SpicyDocs 0.26.6 and Rulespec Artifacts 1.1.1, while Search and Engine still pin `docspec==0.9.0`, `spicy-docs==0.26.5` and `rulespec-artifacts==1.1.0`; PM01 already deleted metadata's per-record path (`spicysearch/PLAN.md`, Prepared metadata) and derives at `spicysearch/src/spicysearch/metadata/enrichment.py:159,176`; identifier enrichment still calls `resolve_many` at `spicysearch/src/spicysearch/catalog_enrichment.py:123`, and no Search plan row retires it | no `resolve_many` caller left outside DocSpec |

## 4. Sequence

- Week one: A1–A4, C1, D1, D2.
- Week two: B1, B2, D3.
- Week three: B3, D4, D5, C2.
- After: B4 and B5 behind the bakeoff; C3 behind C1's numbers.
- PM01's remaining steps sit before or after D3, as ruling 4 decides.

## 5. Rulings this plan needs

1. Decision 0007 as stated in D1.
2. The generation decision in B3.
3. The bill-key rule in A3: zero padding and unknown types.
4. Whether PM01 cuts over on the row-copied catalog states and D5 re-derives
   after D3, or PM01's cutover waits for D3.

Everything else is a reversible commit.

## 6. The gate that decides Track D

- **Claim:** D3 admits the fork-host `federal-register` generation into a
  state whose contract columns equal the retained catalog from the 2026-09-14
  reimport probe.
- **Population:** the generation pinned in §2, all rows.
- **Reference:** the retained probe catalog, built by the row-copy path, so the
  reference does not recompute the rule under test.
- **Threshold:** two-way `EXCEPT` on the contract columns returns zero rows in
  both directions; wall time, bytes downloaded, ledger bytes per record and
  peak memory recorded beside the 16 min 49 s, 0.69 KB and 8.80 GiB baselines.
- **What would make a clean result wrong:** a comparison in the same engine
  session that admitted the rows; the comparison opens a fresh process. A
  zero-row `EXCEPT` on an empty table also passes; the test asserts the record
  count equals the artifact's `recordCount` first.
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
| A1 | proposed | — |
| A2 | proposed | — |
| A3 | proposed | — |
| A4 | proposed; remote removed 2026-09-22 | git config only |
| B1 | proposed | — |
| B2 | partial: readers deleted on main; shaper copy remains | `9837fae`…`f808ecf`; `build_federal_register.py:88` |
| B3 | proposed | — |
| B4 | proposed, gated | — |
| B5 | proposed | — |
| C1 | proposed | — |
| C2 | proposed | — |
| C3 | not before C1 | — |
| D1 | proposed | — |
| D2 | proposed | — |
| D3 | proposed | — |
| D4 | proposed | — |
| D5 | partial: PM01 deleted metadata's per-record path; identifier enrichment's caller left | `spicysearch/PLAN.md`; `catalog_enrichment.py:123` |

## 10. Baseline trees and sources

Validated 2026-09-22 against: spicy-docs `6673fa3`, spicy-regs `bf35bc9`,
DocSpec `d66aebb`, spicyengine `056cb04`, spicysearch `66a0eb1`.

- DuckDB iceberg extension, catalogs and writing.
  <https://duckdb.org/docs/current/core_extensions/iceberg/catalogs>
  <https://duckdb.org/docs/current/core_extensions/iceberg/writing_to_iceberg>
- PyIceberg API, `add_files`. <https://py.iceberg.apache.org/api/>
