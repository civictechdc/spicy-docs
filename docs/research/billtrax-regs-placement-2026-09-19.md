# Where BillTrax's interpretation layer lives in spicy-regs

Status: research, not started. Written 2026-09-19 against spicy-regs `main`
(`ee65b33` at the parent checkout), spicy-docs `ee65b33` (v0.20.0), and
BillTrax `a6b685f` (read-only). File:line cites were read on those trees;
re-verify line numbers before acting on them.

## 0. Framing: this document's job, and the correction it follows

This was drafted first against the assumption in
[`billtrax-port-2026-09-15.md`](billtrax-port-2026-09-15.md) §C ("Stays in
BillTrax (interpretation)": stage rules, `classifyMoneyBill`,
`generateBillSummary`, `matchVotesToBills`, `matchReleasesToBills`, member
matching all listed as BillTrax-side, :59-67) — i.e. that spicy-regs would
host the interpretation *code*. **The maintainer corrected this mid-task.**
The corrected split, verbatim from
[`billtrax-value-inventory-2026-09-19.md`](billtrax-value-inventory-2026-09-19.md)
(written the same day, superseding §C above):

> - **spicy-docs is the one DRY home for code** — acquisition, publisher-format
>   parsing *and* shared interpretation logic. Stage rules, money-bill
>   classification, version kind, vote and release matching, interest areas,
>   classifications, signal extraction, PDF normalization, the agency-block
>   parser and the diff engine all land here. There is no second Python home
>   for logic.
> - **spicy-regs is metadata hosting only** — table schemas, the data
>   dictionary, the publishing pipeline and MCP exposure of tables that
>   spicy-docs code produces. It receives *tables*, never code.
> - **A UI keeps only** auth, email, per-user rows and pages.
> (`billtrax-value-inventory-2026-09-19.md:19-28`)

That document is a **module-level** ledger (every `src/lib/*.ts` and
`scripts/*` file, its line count, callers, tests, and target). It already
does the assignment this task's original §4 asked for, in more detail than I
would re-derive. It also names the exact spicy-docs target module for every
interpretation rule (`billtrax-value-inventory-2026-09-19.md:102-123`), so §4
below reuses those names rather than inventing new ones.

**What that document did not finish when this was drafted** (it has since
been completed: §2 sealed vocabularies, §3 schema, §4 DeltaTrack measured
function by function, §5 API routes, §6 discarded publisher fields and §7
open questions all exist in the committed 1,467-line file, and the
[raw-data measurement](billtrax-raw-data-2026-09-19.md) settled the port
plan's decisions 1, 3, 5 and 7 the same day). The paragraph below is kept
as the record of what this study could and could not check at the time.
It repeatedly forward-referenced sections not yet written: `(§2)` (a sealed-vocabulary appendix, cited at
lines 99, 108, 118, 121, 187, 203), `(§3)` (the table/schema contract, cited
at lines 128, 134, 153), `(§4)` (measured behavioral divergences, cited at
lines 94, 111, 113, 121, 194), and `(§7 Q3)` (open questions, cited at lines
95, 197). The file is 230 lines and ends mid-§1b; none of §2/§3/§4/§7 exist
in it. **This document's §3 is written to fill that specific gap** — the
table/schema contract for the tables that receive the interpretation
modules' output — cross-checked directly against BillTrax's own migrations
rather than only against the inventory's summary. The other gaps (§2's
sealed vocabularies, §4's measured divergences, §7's open questions) are
still missing and are named as a maintainer action item in §6 below, not
re-created here from memory.

This document also covers ground the inventory doesn't: how spicy-regs
mechanically adds a table today (§1), the live state of spicy-regs' existing
Congress sources (§2), how spicy-regs would host a spicy-docs-computed table
without computing it (§4, spicy-regs side), and what a thin replacement app
needs on top of the published tables (§5).

## 1. How spicy-regs adds a dataset today

Traced end to end on `congress_bills` (list-level Congress.gov bills — the
closest existing analog to a BillTrax table: same publisher, same
`{congress}-{type}-{number}` identity, same incremental-by-update-date
shape). The numbered path, file:line:

1. **Source** — `src/spicy_regs/sources/congress_bills.py` (238 lines).
   Subclasses `spicy_regs.sources.base.Reader`, implements `iter_records()`
   to yield **raw** publisher dicts — no shaping (`sources/congress_bills.py:99-149`).
   Pages `offset`/`limit` to exhaustion inside a server-bounded
   `fromDateTime`/`toDateTime` window (`:152-187`); resolves its API key from
   a fallback chain of env vars shared with regulations.gov/GovInfo
   (`:66-71, :86-96`).
2. **Transform** — `src/spicy_regs/transforms/build_congress_bills.py` (210
   lines). Defines the published column tuple and an explicit
   all-`VARCHAR` Arrow schema (`:62-74`); `_bill_id()` builds the
   `{congress}-{type}-{number}` identity key and returns `None` (row
   dropped, never a placeholder) when any part is missing (`:84-91`);
   `_shape()` maps one raw payload onto the schema (`:94-108`);
   `build_congress_bills()` downloads the prior table from R2 best-effort,
   fetches only the incremental window, and DuckDB-merges old ∪ new
   deduped on `bill_id` preferring the fresh row (`:135-210`).
3. **Pipeline (rollup)** — `src/spicy_regs/pipelines/rollups/congress_bills.py`
   (43 lines). Subclasses `RollupPipeline` (`pipelines/rollups/base.py:35-91`):
   `inputs = ()` because this rollup *ingests* an external source rather than
   reading published base tables (`congress_bills.py:32`, `base.py:17-20`);
   `build()` calls the transform (`:35-40`). The base class's `run()` does
   prime → build → load: download required inputs from R2 (none here),
   materialize, then shrink-guarded upload unless `skip_upload` (`base.py:50-68`).
4. **Schema** — no separate `schemas/` entry for this table. Congress bills
   defines its schema inline as a plain `pa.schema` tuple
   (`build_congress_bills.py:62-74`), the same pattern every "complementary
   source" rollup uses. The `schemas/` package (`RecordType`, `base.py:8-38`)
   is only used by the core regulations.gov shapes
   (`schemas/regulations.py`) that the main ETL's `Reader → Transform →
   Writer` pipeline shares across `dockets`/`documents`/`comments`
   (`CONTRIBUTING.md:159-165`).
5. **CLI registration** — `pyproject.toml:69`:
   `run-rollup-congress-bills = "spicy_regs.pipelines.rollups.congress_bills:app"`.
   `make_rollup_app()` (`pipelines/rollups/base.py:94-115`) builds the same
   two-flag (`--output-dir`, `--skip-upload`) cyclopts CLI every rollup gets
   for free.
6. **CI cron** — `.github/workflows/rollup-congress-bills.yml`: its own cron
   (`15 20 * * *`), its own `workflow_dispatch` inputs (`since`/`until`
   backfill bounds, `skip_upload`), delegating to the reusable
   `.github/workflows/_rollup.yml`, which runs `uv run <command>
   --no-skip-upload` on a real run. One rollup, one workflow, one cron — a
   failing source cannot block another (`README.md:212-215`).
7. **Data dictionary** — `data_dictionary/descriptions.yaml:295-318`: a
   `label`, a `coverage` statement (must open with its kind — "True range" /
   "Window" / "Sampled" etc.), a `measured_on` date, a `summary`, and a
   per-column description for every published column.
   `uv run spicy-regs-dict check` fails the build if any column is
   undocumented or a description no longer matches the schema
   (`README.md:290,295-300`); `uv run spicy-regs-dict generate` regenerates
   `docs/tables/*.md` and `data_dictionary/catalog.json` (the vendored
   contract other repos pin by digest, `PLAN.md:107-113`) from the same file.
8. **MCP exposure** — add the table's filename (minus `.parquet`) to the
   `TABLES` tuple, `src/spicy_regs/mcp_server.py:30-53` (`congress_bills` is
   at `:42`). `_build_connection()` then does, for every name in `TABLES`,
   `CREATE VIEW {name} AS SELECT * FROM read_parquet('{R2_BASE_URL}/{name}.parquet')`
   (`mcp_server.py:275-278`) — the *entire* registration cost for a new
   table already living on R2 is one tuple entry. `list_sources()`,
   `describe_table()` and `query_sql()` then see it automatically
   (`:361-432`).
9. **Tests** — `tests/test_congress_bills.py` (250 lines), hermetic (no
   network, per `addopts = "-m 'not integration'"`, `pyproject.toml:104-107`):
   asserts the exact published schema shape (`test_congress_bills.py:44-49`),
   the `_bill_id`/`_shape` mapping, the pagination request params (the
   `sort=updateDate+desc` space-not-plus regression cover named in the
   module docstring's "510-day freeze" story,
   `sources/congress_bills.py:18-24`), and the window-bounding math.
10. **CI gate** — `.github/workflows/ci.yml`: `lint` (`ruff check` +
    `ty check`), `test` (`pytest`), `data-dictionary` (`spicy-regs-dict
    check` + regenerate-and-diff `docs/tables`). All three block merge; none
    touches R2 or the network (`ci.yml`, 87 lines total).

**Load-bearing conventions** (apply to any new table, BillTrax or not):

- **Naming.** Table name = R2 object key = MCP view name = data-dictionary
  key, always snake_case, always singular concept plural rows
  (`congress_bills`, not `CongressBill`).
- **Identity columns are the dedup/primary key, always synthesized as a
  readable string**, never a surrogate UUID: `congress_bills.bill_id =
  "{congress}-{type}-{number}"` (`build_congress_bills.py:84-91`), and every
  sibling complementary source follows the same shape (`crs_reports.py`
  keys on `report_id`, `unified_agenda` keys on `(rin, agenda_edition)`,
  `data_dictionary/descriptions.yaml:332-336`). BillTrax's own tables key on
  an internal `CHAR(36)` UUID (`migrations/001_initial_schema.ts:16`,
  `:37`) with the natural key as a separate `UNIQUE` constraint
  (`:31`, `:48`) — the opposite convention. §3 below carries the natural key
  forward and drops the UUID.
- **All-VARCHAR Parquet schema.** Every complementary-source table stores
  every column as a string, including numbers and JSON arrays-as-strings
  (`build_congress_bills.py:74`; confirmed repo-wide by
  `data_dictionary/descriptions.yaml`'s repeated "All columns are stored as
  VARCHAR" summaries, e.g. `:308`, `:334`). Typed comparisons happen at query
  time in DuckDB, not at rest.
- **Provenance.** Two different conventions coexist and neither is "the"
  spicy-regs pattern:
  - **Carrier column.** `bill_subjects` (BILLSTATUS subject enrichment)
    stamps which of two possible publishers answered a given row —
    `CARRIER_API = "congress-api"` vs. `CARRIER_BULKDATA =
    "govinfo-billstatus"` — directly into the row
    (`sources/bill_subjects.py:55-56`). Simple, cheap, sufficient when a row
    is still one publisher's *fact*, just sourced from either of two places.
  - **Attestation columns.** The `ontology/` package's five-column
    provenance block — `method`, `actor_id`, `run_id`, `asserted_at`,
    `supersedes_id` (`ontology/common.py:17-23`) — is what spicy-regs
    already uses when a row is *not* a bare publisher fact: `RunContext`
    stamps every row produced in one pipeline run with a shared `run_id` and
    timestamp (`:33-68`), and `NON_DETERMINISTIC_METHODS = {"llm",
    "embedding", "human"}` (`:25`) is explicit that this column set already
    anticipates a non-deterministic (e.g. model-derived) method value. It is
    used today by the rulemaking-dataset concept-graph transforms
    (`transforms/build_regulatory_agenda.py`, `build_comment_periods.py`,
    `build_proceedings.py`, `build_rule_targets.py`) — a different lane from
    Congress data, but it is the closest existing precedent for "this
    column was computed, here is who/what/when/how," and §3/§4 below reuse
    it rather than inventing BillTrax's ad hoc `classified_by`/`classified_at`
    pair (`BillTrax/migrations/011_money_bill_metadata.ts:18-19`).
- **How spicy-docs captures are consumed.** Not through
  `spicy_docs.public_tables` — that mechanism exists
  (`spicy-docs/src/spicy_docs/public_tables/*.py`, profiles for
  `dockets`/`documents`/`comments`/`federal_register` only,
  `spicy-docs/src/spicy_docs/public_tables/profiles.py:110-165`) but
  spicy-regs never imports it (`grep public_tables src/spicy_regs` — zero
  hits), and spicy-docs' own docs say why: **"SpicyRegs' public pipeline and
  this package's optional public-table export are separate products"**
  (`spicy-docs/docs/source-workflows.md:57`). Instead, spicy-regs imports
  spicy-docs **library code** — reader/parser classes and functions — inside
  its own source or transform modules, at whatever version is pinned in
  `vendor/` (`spicy-regs/pyproject.toml:22-26,93-95`, currently
  `spicy-docs[acquisition,pdf-pypdf]==0.20.0`). Concrete precedent:
  `sources/bill_subjects.py:54,262,274-275` imports
  `spicy_docs.sources.congress.bill_acquisition.BillAcquirer` and
  `spicy_docs.sources.congress.bill_status.BillIdentity`; `sources/unified_agenda.py:19,42-49`
  imports `spicy_docs.sources.unified_agenda`; `transforms/court_scope.py`
  and `transforms/build_court_opinion_{clusters,bodies}.py` import
  `spicy_docs.sources.courtlistener.bulk.CourtListenerBulkReader`;
  `transforms/pdf_text.py:70` imports `spicy_docs.extraction.pypdf`. In
  every case spicy-regs still does its own shaping, dedup and publish — it
  imports spicy-docs' *acquisition*, not a finished table. §4 extends this
  same pattern to spicy-docs' *interpretation* modules once they exist.

## 2. What spicy-regs already has for Congress

**Live today, in `main`, checked into CI:**

- `sources/congress_bills.py` + `transforms/build_congress_bills.py` +
  `pipelines/rollups/congress_bills.py` — the `/bill` list endpoint,
  10-column schema, described above. Cron
  `.github/workflows/rollup-congress-bills.yml`. Documented:
  `data_dictionary/descriptions.yaml:295-318`,
  `docs/tables/congress_bills.md`. Exposed via MCP
  (`mcp_server.py:42`). README-advertised (`README.md:105`) as a
  "Lifecycle" complementary source, ~430K bills as of 2026-08
  (`sources/congress_bills.py:81-82`).
- `sources/crs_reports.py` + `transforms/build_crs_reports.py` +
  `pipelines/rollups/crs_reports.py` — parallel structure, 8-column schema
  (`build_crs_reports.py:45-53`), same incremental-merge shape. Cron
  `.github/workflows/rollup-crs-reports.yml`.
- `sources/bill_subjects.py` — CRS `policyArea` + legislative-subjects
  enrichment for `congress_bills` rows, walking the published table and
  fetching per-bill from whichever of two carriers (Congress.gov API or
  GovInfo BILLSTATUS) the environment can reach
  (`sources/bill_subjects.py:1-70`; cron
  `.github/workflows/rollup-bill-subjects.yml`). This is publisher-assigned
  metadata (Library of Congress classification), not BillTrax logic — see
  §3's note on "interest areas."

**Superseded, but the supersession has not landed on the spicy-regs side.**
Two independent decisions say the same thing from opposite ends:

- spicy-docs' `docs/simplification-todo.md:911-935`, "SpicyRegs fetcher
  merge" (decided 2026-09-14): *"every SpicyRegs reader connector that
  fetches a publisher moves into SpicyDocs as an explicit source; SpicyRegs
  adopts the wheel and deletes its copy."* The table there lists
  `congress_bills.py` as item **M03** ("Port: bill listing route") and
  `crs_reports.py` as **M02** ("Port: listing route beside
  `crs_summaries.py`") — both still marked as pending ports, not `done`, as
  of that table's last edit.
- spicy-docs' `docs/sources/listings.md:234-238` confirms the *target*
  landed: its own route table
  (`spicy-docs/src/spicy_docs/sources/congress/listing.py`) now has both a
  `"bill"` route (`LIST_ROUTES["bill"]`, `:192-198`) and a `"crsreport"`
  route (referenced at `:398`, `:423-426`), and states outright: **"These
  routes replace SpicyRegs' `congress_bills.py`, `crs_reports.py`,
  `cfr_sections.py`, `gao_reports.py`, `lobbying_filings.py`,
  `courtlistener.py`, `sam_entities.py`, `usaspending.py` and `fcc_ecfs.py`
  readers."`** `billtrax-port-2026-09-15.md:1-2` corroborates the landing
  date: *"spicy-docs side of Phases 4 and 6 landed 2026-09-19
  (`congress/listing.py` route table, `congress/bulk_status.py`)."*

So: **the replacement exists upstream; spicy-regs has not adopted it.**
spicy-regs' `PLAN.md:164-184` (task `SR01`, unchecked) is exactly this
open loop — *"Review actual source connectors... KEEP/SHARE/REMOVE/DEFER
decision"* — coordinated with spicy-docs' own `S11`/`S25` and DocSpec's
`D41`, still open. Until `SR01`/`SR03` land, `congress_bills.py` and
`crs_reports.py` keep running their own hand-rolled pagination
(`sources/congress_bills.py:150-225`) in parallel with spicy-docs' newer,
tested `listing.py` route table doing the identical job. This is a live
duplication, not a hypothetical one, and it is the same duplication a
BillTrax port would otherwise re-create for a third time (BillTrax's own
`congress-api.ts` `fetchAmendments`/`fetchCommitteeBills` is a *fourth*
implementation of Congress.gov list pagination, already marked `landed` /
superseded by `listing.py` in
`billtrax-value-inventory-2026-09-19.md:74`). **A BillTrax port should
target spicy-docs' `listing.py`/`bulk_status.py`, not spicy-regs'
`congress_bills.py`,** and spicy-regs' own migration off its hand-rolled
reader (`SR01`/`SR03`) is a prerequisite worth sequencing ahead of new
Congress tables, not after — a second table copying the soon-to-be-deleted
pattern doubles the migration surface.

## 3. Proposed table set

Every BillTrax table below is one of the 18 in `CATALOG_TABLES`
(`BillTrax/scripts/catalog-tables.ts:12-31`) — BillTrax's own "shareable
data" boundary, cross-checked against the 22 migrations
(`BillTrax/migrations/001*.ts`–`022*.ts`). The 8 `USER_TABLES`
(`catalog-tables.ts:37-45`: `users`, `user_subscriptions`, `notes`,
`bill_topics`, `user_interest_areas`, `shareable_links`, `password_resets`,
`notification_log`) and the 2 `SCHEMA_TABLES` (`:50`) are **excluded from
this table set entirely** — private account data and Knex bookkeeping never
belong in a public bucket, and BillTrax's own export tooling already refuses
to touch them (`catalog-export.ts:17` — *"Never touches USER_TABLES"*).
`diff_jobs` (`migrations/015_diff_jobs.ts`) is absent from `CATALOG_TABLES`
too — it is a job queue, not data, and
`billtrax-value-inventory-2026-09-19.md:136` independently rules it
`delete`: *"a queue is orchestration, not a published table. spicy-docs
pipelines own their own scheduling."* All three exclusions agree, so this
table set does not re-litigate them.

Identity columns use the joins `legislative-data-map-2026-09-18.md:396-483`
validated: Congress/type/number for bills, bioguide for members, system code
for committees, PN for nominations, jacket for hearings, event id for
meetings, session+roll number for House votes, package id for GovInfo
bodies, and the community legislators JSON as the LIS-id crosswalk for
former senators (`decisions.md:151-168`).

| Table | Grain | Identity | spicy-docs supplies | Interpreted columns / rule | Fact vs. interpretation |
|---|---|---|---|---|---|
| **congress_bills** *(extend, exists)* | 1 row / bill | `bill_id = {congress}-{type}-{number}` (existing) | Already live: `sources/congress_bills.py` (target migration: `congress/listing.py` "bill" route, §2) | **new columns**: `stage` ← `interpretation/bill_stage.py` (was `STAGE_RULES`/`inferStageFromAction`, `congress-api.ts:5-90,142-149`); `money_bill_kind`, `fiscal_year`, `appropriations_subcommittee` ← `interpretation/money_bills.py` (was `classifyMoneyBill`, `money-bills.ts:123-201`); `public_law_number`, `statutes_at_large_cite`, `signed_date` | Existing columns (title, sponsor, latest_action_*, url) are publisher fact. `stage` is interpretation over `latest_action_text`. `money_bill_kind`+`fiscal_year`+`appropriations_subcommittee` are interpretation over `title` + committee-referral signals (`fromAppropriationsCommittee` etc., `money-bills.ts:97-105` — those booleans are themselves derived from which committee-listing route discovered the bill, so the classifier needs that context threaded through, not just the bare title). `public_law_number`/`statutes_at_large_cite`/`signed_date` are publisher fact (`bill.laws[]`, `congress-api.ts:228-229,241-252`) but the *current* `signedDate` derivation is a known-buggy heuristic over `latestAction.text` (two disagreeing implementations, `billtrax-port-2026-09-15.md:98-99` fix-ledger item 2) — fix before porting, don't preserve the bug. |
| **bill_versions** *(new)* | 1 row / (bill_id, version_code, source) | `(bill_id, version_code, source)` — BillTrax widened this exact key in `migrations/020_version_uniqueness_includes_source.ts` to let an XML row and its `govinfo-pdf` twin coexist | `sources/congress/bill_text.py` / `bill_status.py` (`text_versions`, already typed: `BillTextVersion(type, date, formats, package_id)`, `spicy-docs bill_status.py:106-109`) | `kind` ← `interpretation/version_kind.py` (was `classifyVersionKind`, `version-kind.ts:101-124`); `equivalent_xml_version_id` ← `interpretation/pair_type.py` (was `pair-type.ts`, decides pdf-pdf/pdf-xml/xml-xml, `billtrax-value-inventory-2026-09-19.md:121`) | `label`, `version_code`, `date`, `text`, `xml`, `source`, `is_base`, `congress_url` are fact. `kind` is interpretation over the `version_code` slug + body size. `cleanup_applied` (was `pdf-normalize.ts` diagnostics) is **processing provenance**, not interpretation of bill content — same shape as spicy-regs' own `pdf_extraction_results_json` diagnostics field (`spicy-regs/README.md:267-277`); model it the same way, not as a data column. **Dropped**: `uploaded_by_user_id` — ties to a BillTrax user account, not a publisher fact; user-submitted alignment stays entirely in a thin app, never spicy-docs/spicy-regs (spicy-docs acquires *public* sources, `source-workflows.md:3-4`). `aligned_to_congress_bill_id` is kept only if a thin app still supports user uploads (§5) — if not, drop it too. |
| **bill_sections** *(new)* | 1 row / (bill_id, version_code, match_path) | `(bill_id, version_code, match_path)` | `sources/congress/bill_tree.py` (proposed target for `bill-tree.ts`, **parsing, not interpretation**: `billtrax-value-inventory-2026-09-19.md:94` — "a *fork* of DeltaTrack `bill_tree.py` with four measured divergences") | none — structural parse of publisher XML | Fact-adjacent: the publisher's own XML encodes section structure (why XML is preferred over text, `congress-api.ts:151-153` "preserves element IDs and structure needed for section diff"); `match_path`/`display_path`/`heading`/`body`/`seq` are a faithful transcription, not a judgment call. Belongs in spicy-docs' **parsing** bucket per the corrected split, hosted as a spicy-regs table like any other. |
| **section_diffs / section_diff_items / financial_changes** *(new, or one wide table)* | 1 row / (from_version, to_version) parent, child rows per section pair | `(from_version_id, to_version_id)` | n/a — computed, not acquired | `interpretation/section_diff.py`, merging the TS fallback's two learned guards (`GREEDY_PAIR_GROUP_CAP = 200`, `SECTION_COUNT_THRESHOLD = 10`, `section-diff.ts:26,40`) into DeltaTrack's `diff_bill.py` (`_similarity_pair`, `match_nodes`, `reconcile_moves`, `compute_financial_change`) — `billtrax-value-inventory-2026-09-19.md:111-113,194` rules `financial.ts` and `diff.ts` (TS re-implementations) `delete` outright, keeping only the Python | Fully interpretation — a diff is a computed comparison, never a publisher fact. `word_segments_json` (word-level diff rendering, `migrations/014_word_segments.ts`) is a rendering cache of the same computation, not new information; recompute or drop rather than publish redundantly. |
| **amendments** *(new)* | 1 row / amendment | `(congress, bill_type, bill_number, amendment_number)` | `congress/listing.py` amendment route (`billtrax-value-inventory-2026-09-19.md:74`) | none | Fact. One bug to not preserve: `amendments.status` is hardcoded `"Proposed"` in current BillTrax (`billtrax-port-2026-09-15.md:101` fix-ledger item 7) — carry the real source field once the listing route lands. |
| **committee_reports / report_sections** *(new)* | 1 row / (bill_id, chamber); child rows per agency block | `(bill_id, chamber)` (BillTrax's own existing unique key, `migrations/003_committee_reports.ts:14`) — recommend keying instead on the GovInfo **package id** (CRPT), the identity `sources/govinfo/body_acquisition.py` already proves before any body byte (`decisions.md:169-200`) | `sources/govinfo/body_acquisition.py` (CRPT package body) | `report_sections.agency_label`/`body` ← `interpretation/agency_blocks.py` (was `parseAgencyBlocks`, "pure and dependency-free," `billtrax-value-inventory-2026-09-19.md:96`) | `committee_reports.text` is fact (a GovInfo body fetch by package id). The agency-block split is parsing (structural), not classification — same bucket as `bill_sections`. |
| **hearing_transcripts** *(new)* | 1 row / hearing | GovInfo CHRG **package id**, not BillTrax's UUID (no natural key exists in the current schema) | `sources/govinfo/body_acquisition.py` (CHRG package body); explicitly named as the re-hydration target in `legislative-data-map-2026-09-18.md:513-514`: *"hearing_transcripts.text, committee_reports.text in BillTrax catalog-tables.ts:54-59"* | none | Fact. `status` (`pending`/etc., `migrations/006:49`) is BillTrax's own ingest-pipeline state, not publisher data — drop it from the public table; a spicy-regs pipeline's own manifest (`manifest.py`) already tracks processing state the equivalent way. |
| **press_releases** *(new)* | 1 row / release | `source_url` (BillTrax's own existing unique key, `migrations/005_press_releases.ts:15`) | new `sources/congress/press_releases.py`, cloned from `sources/gao/rss.py` discipline (`billtrax-value-inventory-2026-09-19.md:87`; also billtrax-port doc's Phase-2 placement, `billtrax-port-2026-09-15.md:8`) | `bill_id` (the match) ← `interpretation/release_matching.py` (was `matchReleasesToBills`, `press-releases.ts:131-160`) | `source_url`/`feed_url`/`source_name`/`title`/`excerpt`/`published_at` are fact (RSS). `bill_id` is interpretation — and the current implementation is an O(unmatched × bills) regex-per-pair loop the inventory measures explicitly: *"500 × 1000 = 500k compilations per run"* (`billtrax-value-inventory-2026-09-19.md:115`). Re-derive the matching algorithm's cost bound when porting, don't just relocate the loop. |
| **roll_call_votes** *(new)* | 1 row / roll call | `(congress, chamber, session, roll_number)` (BillTrax's own existing unique key, `migrations/009_roll_call_votes.ts:21`) | `congress/listing.py` bill-actions/votes route for House; publisher files (Clerk XML, Senate LIS) for the two gaps the API doesn't cover (`decisions.md:121-150`, `legislative-data-map-2026-09-18.md:428-436`) | `bill_id` (the match) ← `interpretation/vote_matching.py` (was `matchVotesToBills`, `roll-call-votes.ts:133-159`) | `question`/`result`/`yea`/`nay`/`present`/`not_voting`/`vote_date`/`source_url` are fact. `bill_id` is interpretation — and the inventory flags the current regex as measured-broken: *"Port the intent, not the regex — measured broken (§2)"* (`billtrax-value-inventory-2026-09-19.md:114`). That `§2` measurement doesn't exist in the committed file (see §0) — a maintainer needs to either finish it or re-run it before this rule ports. |
| **member_votes** *(new)* | 1 row / (roll_call, bioguide_id) | `(congress, chamber, session, roll_number, bioguide_id)` | same vote source as above | none | Fact. Note: BillTrax's own `upsertMemberVote` (`roll-call-votes.ts:108-123`) has **zero callers anywhere in the app** despite the table being migrated, cataloged and exported (`billtrax-value-inventory-2026-09-19.md:166`) — the table exists but nothing populates it today. Confirm the intended population path before porting rather than assuming it works. |
| **members** *(new, or reuse spicy-docs' legislators crosswalk directly)* | 1 row / member | `bioguide_id` | `sources/legislators.py`, already landed 2026-09-19 (`decisions.md:151-168`) — pinned, byte-bounded, keyless, keys every member by bioguide and carries LIS/FEC/ICPSR/GovTrack/OpenSecrets ids on the same record | `interpretation/member_matching.py` (was `getMemberByName`, exact-then-last-name sponsor-string matching, `members.ts:75-93`) is a **lookup helper**, not a stored column — it resolves a free-text sponsor string to a `bioguide_id` at query/ingest time, it doesn't classify anything about the member row itself | Almost entirely fact, and **arguably redundant with a table spicy-docs already acquires** — BillTrax's own `members` schema (`name`, `party`, `state`, `district`, `chamber`, `start_date`, `end_date`, `migrations/010_members.ts:6-15`) substantially overlaps the legislators crosswalk. `photo_url` is explicitly **not** a fact: BillTrax constructs it rather than fetching it (`billtrax-value-inventory-2026-09-19.md:76`: *"photo URL is **constructed**, not fetched"*) — drop it from any published table; a thin app builds the URL client-side the same way. |
| **section_classifications** *(new)* | 1 row / (section_id, label) | `(bill_id, version_code, match_path, label)` | n/a — computed from `bill_sections.body` | `interpretation/section_classification.py` (was `classifyVersion`, LLM-labeled in batches of 30, `classifications.ts:47-103`) | Fully interpretation (LLM). The five-label vocabulary (`funding_opportunity`/`directive`/`deadline`/`restriction`/`other`, `classifications.ts:5`) and its prompt are called out as **sealed** — preserve exactly (`billtrax-value-inventory-2026-09-19.md:118`). `confidence` is a model output, not a fact — carry it, and carry attestation (`method="llm"`, model id, prompt version) via the `ontology.ATTESTATION_COLUMNS` shape (§1), not BillTrax's ad hoc pair. |
| **bill_summaries / diff_summaries** *(new)* | 1 row / version (bill_summaries); 1 row / (from_version, to_version) (diff_summaries) | `(bill_id, version_code)` / `(from_version_id, to_version_id)` | n/a — computed from `bill_versions.text` | `interpretation/bill_summaries.py` (was `generateBillSummary`, `bill-summaries.ts:107-208`) — the inventory places this in the "shared logic, DRY home" bucket too (`billtrax-value-inventory-2026-09-19.md:119`), **which is a change from `billtrax-port-2026-09-15.md:65`'s "Stays in BillTrax" listing for AI summaries specifically** — flagged as a supersession in §0, not independently re-derived here | Fully interpretation (LLM). `model`, `prompt_version`, `content_hash`, `input_tokens`, `output_tokens` are exactly the provenance columns to keep (`bill-summaries.ts:17` `PROMPT_VERSION = "v1"`) — again, map onto `ontology.ATTESTATION_COLUMNS` rather than BillTrax's bespoke set if consistency with the rest of spicy-regs' derived tables matters more than a 1:1 port. |
| **public_activity_events** *(new)* | 1 row / event | none stated in BillTrax (auto UUID) — recommend `(bill_id, event_type, occurred_at)` | n/a — derived from the other tables' own timestamps as they publish | none (it's a log of *other* tables changing, not a new judgment) | Fact-shaped (an append-only log of `bill_added`/`version_added`/`stage_changed`/`summary_generated`), and the inventory rules it `spicy-regs hosting` directly: *"`public_activity_events` (`spicy-regs hosting`); `describeEvent` is UI"* (`billtrax-value-inventory-2026-09-19.md:135`). Open design question in §6: BillTrax writes this as an explicit log at ingest time; a spicy-regs pipeline has no live ingest-time hook to write from — it would need to be a small rollup that diffs consecutive published snapshots, not a direct port of the write pattern. |
| **interest_areas** — **no table** | — | — | — | `interpretation/interest_areas.py` (was `findMatchingSections`, `interest-areas.ts:83-141`) | **Not a per-bill column at all.** BillTrax's "interest areas" are user-defined keyword sets (`user_interest_areas`, a `USER_TABLE`, `migrations/006:17-25`) matched live against `bill_sections.body` with `MATCH ... AGAINST` full-text search (`interest-areas.ts:117-126`) — a **query-time** operation parameterized by a private, per-user row, not a precomputable classification. There is nothing to publish here; §5 covers it as a thin-app query capability instead. Separately, **spicy-regs already publishes a real, publisher-assigned "what is this bill about" fact** — `bill_subjects` (CRS `policyArea` + legislative subjects, `sources/bill_subjects.py`, §2) — which a thin app should prefer over reinventing keyword search, since it's Library-of-Congress-assigned rather than user-guessed. |

**Column accounting.** Every `CATALOG_TABLES` table (18) is addressed above,
directly (12 rows) or folded into a sibling row where BillTrax already
folds it (`section_diffs`+`section_diff_items`+`financial_changes` as one
computation, `diff_summaries` alongside `bill_summaries`). Every column
inside those tables is either carried (with its fact/interpretation label
stated), explicitly dropped with a reason (`uploaded_by_user_id`,
`photo_url`, `hearing_transcripts.status`, `word_segments_json`), or named
as needing a fix-not-preserve pass before porting (`signed_date`,
`amendments.status`, the vote/release matching regexes). Nothing is silently
omitted.

## 4. Where each interpretation rule goes, and how spicy-regs hosts the result

**Location: a new top-level `spicy_docs/interpretation/` package.** It does
not exist yet (`find src/spicy_docs -maxdepth 1 -type d` — no
`interpretation/`), but its shape is already named module-by-module in
`billtrax-value-inventory-2026-09-19.md:102-123`:
`interpretation/bill_stage.py`, `money_bills.py`, `version_kind.py`,
`vote_matching.py`, `release_matching.py`, `member_matching.py`,
`interest_areas.py` (the matching half only — the CRUD half is per-user and
stays in a UI, `:117`), `section_classification.py`, `bill_summaries.py`,
`pair_type.py`, and `section_diff.py` (merged with the vendored DeltaTrack
`diff_bill.py`). This sits as a peer to `sources/`, `extraction/`,
`public_tables/`, `releases/` — and the closest existing precedent for a
non-acquisition, derived-computation package living beside `sources/` is
already `extraction/`: *"`spicy_docs.extraction` exposes the PDF/image data
types, reader and page strategies... These reusable components support the
requested source-specific processor choices... They do not change
source-release schemas or defaults"* (`decisions.md:88-92`). `interpretation/`
would follow the same shape: reusable pure logic, imported by a caller that
owns the data flow, not a pipeline in its own right.

**Import boundary these rules must meet.** spicy-docs already enforces a
reader-closure rule — *"Reader imports must avoid eager HTTP/S3,
logging/progress, Parquet and DuckDB imports... `tests/test_reader_closure.py`
guards these boundaries"* (`decisions.md:79-83`). The BillTrax modules
targeted for this package are mostly already pure in this sense
(`STAGE_RULES`, `classifyMoneyBill`, `classifyVersionKind` take plain
data in, return plain data out) — but two are not, today: `matchVotesToBills`
and `matchReleasesToBills` are tangled with BillTrax's own MySQL layer
(`import { query, execute } from "./db"`, `roll-call-votes.ts:1`,
`press-releases.ts:2`). Porting them means extracting the pure matching
function (question text + candidate bill identities → a match or none) from
the database read/write wrapper around it — the same separation BillTrax's
own `bill-identify.ts` `extractSignals` (pure) vs. `identifyBill` (does a DB
lookup) already models, per the inventory's own split of that file
(`billtrax-value-inventory-2026-09-19.md:109-110`).

**Dependency direction: unchanged from today.** spicy-regs already depends
on spicy-docs as a pinned wheel (`spicy-regs/pyproject.toml:22-26,93-95`);
nothing here reverses that. A spicy-regs transform imports the rule
function the same way `sources/bill_subjects.py` imports
`spicy_docs.sources.congress.bill_acquisition.BillAcquirer` today (§1) —
just from `spicy_docs.interpretation.*` instead of `spicy_docs.sources.*`.
Concretely, for `congress_bills.stage`:

```python
# spicy-regs: src/spicy_regs/transforms/build_congress_bill_stages.py (new)
from spicy_docs.interpretation.bill_stage import infer_stage_from_action


def _add_stage(row: dict) -> dict:
    row["stage"] = infer_stage_from_action(row["latest_action_text"])
    return row
```

spicy-regs never re-implements the rule; it calls it, over rows it already
published, and writes the result as a new column (or a new table, per §3) in
its own Parquet/Iceberg output. **This is the entire meaning of "spicy-regs
hosts a table whose rows are computed elsewhere"**: the transform module,
the schema, the rollup pipeline, the cron, the data-dictionary entry and the
MCP view all live in spicy-regs and are spicy-regs' own code — only the cell
values inside one or more columns come from a spicy-docs function call.
Nothing about the numbered path in §1 changes shape; step 2 ("Transform")
just imports more.

**Why not spicy-docs' own `public_tables`/`releases` machinery instead.**
Those modules already *can* take a "source-native release" (an admitted,
provenance-pinned capture, `SourceNativeTableInput` protocol,
`public_tables/format.py:65-79`) and project it into a public Parquet table
(`PublicTableProfile.project()`, `public_tables/profiles.py:75-93`) — a
mechanism that could, in principle, publish a spicy-docs-computed
interpretation table directly, bypassing spicy-regs' pipeline entirely. Two
things argue against that for BillTrax's tables specifically: (1) it is
explicitly a *separate product* from spicy-regs' pipeline today
(`source-workflows.md:57`, quoted in §1), so routing through it would be a
second, currently-unused publishing path rather than an extension of the
one spicy-regs already operates, tests, and has CI/cron/MCP wiring for; and
(2) none of its four existing profiles cover Congress data at all
(`public_tables/profiles.py:168-175` — `federal_register`,
`regulations-gov-{document,docket,comment}` only), so adopting it here would
mean building out a second table-publishing mechanism for one dataset family
while the other twenty-three published tables keep using the first. The
plainer path — spicy-regs imports the function, spicy-regs publishes the
table, exactly as it already imports `spicy_docs.sources.*` — reuses working
machinery instead of standing up a parallel one. This is a recommendation,
not a landed decision; a maintainer should confirm it before relying on it.

**What the test looks like, each side:**

- **spicy-docs side** (the rule itself). A hermetic, pure-function unit
  test — no network, no DB, no Parquet — table-driven over the exact
  matchers/slugs/thresholds the rule encodes. BillTrax's existing TS tests
  are the acceptance-parity target, not a starting point to discard:
  `money-bills.test.ts` (18 `it` cases), `version-kind.test.ts` (32 `it`
  cases), `congress-api.test.ts`'s 26 `inferStageFromAction` cases
  (`billtrax-value-inventory-2026-09-19.md:106-108`) are the specification
  for what the ported Python function must still do, case for case, plus
  whatever the fix-not-preserve ledger changes (§3, `billtrax-port-2026-09-15.md:83-102`).
  This mirrors how spicy-regs itself tests `_shape`/`_bill_id` in
  `test_congress_bills.py` (§1, step 9) — a pure mapping function tested
  against fixed input/output pairs, nothing about network or storage in the
  test at all.
- **spicy-regs side** (the hosting). Much thinner, because the rule's
  correctness is no longer spicy-regs' claim to test. What spicy-regs' own
  suite should assert: the transform calls the imported function and places
  its result in the right column (a mapping test, same shape as
  `test_shape_maps_and_serializes_fields` in `test_congress_bills.py:52-...`,
  but asserting "the `stage` column equals what
  `spicy_docs.interpretation.bill_stage.infer_stage_from_action` returns for
  this input" rather than re-deriving the stage logic itself); the schema
  includes the new column with the right type and dedup-key behavior; the
  data-dictionary description exists and matches (`spicy-regs-dict check`,
  §1 step 10, already enforces this repo-wide with no BillTrax-specific
  work needed); and the MCP view surfaces it (covered for free once the
  table name is in `TABLES`, §1 step 8). spicy-regs' tests should **not**
  re-assert the 32 `version-kind.test.ts` cases or the 26 stage cases — that
  coverage belongs where the logic lives, and duplicating it in spicy-regs
  would be exactly the kind of second-copy drift the whole port exists to
  eliminate.

## 5. What a thin app needs

A replacement UI is almost entirely a query layer over the published
tables, plus the pieces BillTrax's own inventory already ruled `keep in a
UI` (`billtrax-value-inventory-2026-09-19.md:139-153`: auth, email,
per-user notes/topics/interest-areas CRUD, upload handling, the privacy
policy inside `bills.ts`'s `visibilityClause`). Concretely, against the
table set in §3:

- **Already answered by the MCP server today, unchanged.** `list_sources()`,
  `describe_table(table)`, `query_sql(sql)` (`mcp_server.py:361-432`) work
  over *any* table in `TABLES` the moment it's added — a bill-detail page,
  a "what changed on this bill" feed, a money-bill filter, a stage
  breakdown, a roll-call lookup are all just `query_sql` calls once
  `congress_bills`, `roll_call_votes`, `press_releases`, etc. exist as
  published tables. No new MCP code, only new rows in `TABLES`.
- **New, but a query, not new logic.** BillTrax's "interest areas" (§3):
  once `bill_sections` is published, a thin app runs the same
  `MATCH(body) AGAINST(?)`-shaped full-text query BillTrax already runs
  (`interest-areas.ts:117-126`), just against DuckDB/Parquet full-text
  search instead of MySQL, parameterized by the user's own saved keywords —
  a UI-side feature, not a spicy-docs/spicy-regs one. `getMemberByName`
  fuzzy sponsor-string matching is the same shape: a lookup helper a thin
  app calls at render or ingest time, not a stored column (§3).
- **New, and it's a small aggregate query someone still has to write.**
  The inventory flags two `committee-reports.ts` queries
  (`getAgencyRecurrence`, `getSectionsForAgency`) as "shared logic," i.e.
  candidates for `interpretation/` alongside the classification rules
  (`billtrax-value-inventory-2026-09-19.md:134`) — I did not read
  `committee-reports.ts` directly (outside this task's reading list) and
  cannot characterize what these compute beyond the inventory's one-line
  description; a maintainer should read that file before assuming these
  fold neatly into §4's package the same way the others do.
- **Not answered by anything published, and needs a decision.** The public
  activity feed / RSS (`describeEvent`, `public-activity.ts:113-138`) reads
  natively off a live event log BillTrax writes at ingest time
  (§3's `public_activity_events` open question). A thin app either gets an
  equivalent rollup that diffs `update_date`/`created_at` across
  publish runs, or the nightly pipeline gains an explicit event-log step —
  either way this is unresolved, not a query away.
- **Privacy/visibility policy stays entirely in the UI.** BillTrax's
  `bills.ts` `visibilityClause` (:63-71, per the inventory) governs which
  bills a given account may see — this is authorization, not data shape,
  and has no spicy-regs analog: spicy-regs' published tables are public,
  anonymous-read, no concept of a private row (`README.md:40-43`). A thin
  app that wants private/draft bills needs its own private store layered on
  top of the public tables, exactly as BillTrax's `users`/`notes`/`topics`
  tables already do for the current app.

## 6. Constraints and open questions

- **Push rules.** spicy-regs' `origin` (`github.com/civictechdc/spicy-regs`)
  is Eugene Kim's; **do not push there unless Mike names the branch**
  (`PLAN.md:9-25`) — this document changes nothing about that, and any
  follow-on implementation work (new transforms, new rollup workflows) is
  fork-only until explicitly authorized. spicy-docs has no equivalent
  statement read in this pass; confirm its push posture separately before
  landing an `interpretation/` package there.
- **CI gate, already strict, will need to extend cleanly.** `ci.yml`'s three
  jobs (§1 step 10) are dataset-agnostic — a new BillTrax-derived table adds
  itself to the same `pytest`/`ruff`/`spicy-regs-dict check` gate with no
  new CI machinery, *provided* its transform tests stay hermetic (no
  network, `addopts = "-m 'not integration'"`, `pyproject.toml:104-107`) the
  way `test_congress_bills.py` already is. A rule imported from
  `spicy_docs.interpretation` that pulls in an LLM call (classification,
  summaries) needs its *test* to mock or fixture that call — the pattern
  already exists in spicy-regs (BILLSTATUS/PDF consumers use recorded
  fixtures, not live network, per `PLAN.md:243-244`) but hasn't been done
  for an LLM-backed rule yet.
- **Nightly pipeline shape.** Every complementary source is its own rollup,
  own cron, own timeout (§1 step 6) — a BillTrax-derived table set would add
  roughly a dozen new workflows on the same reusable `_rollup.yml`, not one
  big job. Sequencing matters: `bill_sections` needs `bill_versions`;
  `section_diffs` needs two versions of `bill_sections`; `section_classifications`
  needs `bill_sections`; vote/release matching needs `congress_bills`
  published first. `RollupPipeline.inputs` (`pipelines/rollups/base.py:38-40`)
  already expresses "read this base table from R2 first" for exactly this
  kind of dependency — but the *contract* today is explicitly "never another
  rollup's output" (`pipelines/rollups/base.py:17-20`): *"a rollup reads
  only the ETL's published base tables... never another rollup's output, so
  pipelines stay independently schedulable with no cross-pipeline race."*
  BillTrax's dependency chain (versions → sections → diffs/classifications)
  is rollup-on-rollup by construction, which the existing contract
  forbids. This is a real design conflict, not a detail — either the
  contract gets an explicit exception for this family, or the chain gets
  collapsed into fewer, larger rollups that read raw sources once and
  produce several tables internally. A maintainer needs to pick one before
  writing the pipelines.
- **PLAN.md conflicts.** `SR01` (adopt spicy-docs' listing routes, remove
  spicy-regs' hand-rolled ones, §2) is unchecked and, per its own text,
  gates `SR03` (implement the selected changes) — a new BillTrax table
  built against the *current* `congress_bills.py`/reader pattern inherits
  code that `SR01` may delete out from under it. Sequencing a BillTrax port
  after `SR01`/`SR03` land avoids building on a reader spicy-regs itself
  plans to delete.
- **DeltaTrack: settled 2026-09-19 as a dependency** (port plan decision 3):
  the canonical repo moved to `civictechdc/DeltaTrack` and is an installable
  package far ahead of BillTrax's copy, so spicy-docs pins it by git commit
  and adapts over it; BillTrax's two copies are deleted. The original question, for the record:
  `interpretation/section_diff.py`
  (§4) is described as merging with DeltaTrack's `diff_bill.py`
  (`billtrax-value-inventory-2026-09-19.md:112`), but DeltaTrack is a
  separate, existing Python package (vendored as a BillTrax git submodule,
  11 files / 2,846 lines, `billtrax-value-inventory-2026-09-19.md:53`), not
  spicy-docs code. Does spicy-docs absorb DeltaTrack's source, or depend on
  it as a library the way it does `rulespec-artifacts`? Neither this
  document nor the port plan nor the value inventory says; a maintainer
  needs to decide before `interpretation/section_diff.py` can be written.
- **The value-inventory's gaps are closed** (§0): its §2, §4 and §7 now
  exist, and the vote-matching "measured broken" claim is verified there
  (§2.10) and in the raw-data study §5 (`recordedVotes` is six
  always-present structured fields, so no regex is needed). Original
  wording, for the record:
  `§2` (sealed vocabularies — including the vote-matching regex's "measured
  broken" claim this document repeats in §3 without being able to verify
  it), `§4` (measured behavioral divergences between the TS `bill-tree.ts`
  fork and DeltaTrack's `bill_tree.py`), and `§7` (that document's own open
  questions) are cited throughout `billtrax-value-inventory-2026-09-19.md`
  but do not exist in the 230-line committed file. Finishing those sections
  — or confirming they were dropped on purpose — is a prerequisite for
  treating this placement as final, not just a nice-to-have.
- **Recommended resolution of the rollup-chain conflict** (the build
  proceeds on this assumption; the maintainer can reverse it): collapse
  the chain inside spicy-docs, not across spicy-regs rollups. A spicy-docs
  table builder reads the captured sources once and produces the whole
  bill family (versions, sections, diffs, classifications) as sibling
  tables in one pass, so every spicy-regs rollup keeps `inputs = ()` and
  the "never another rollup's output" contract needs no exception. The
  same builder derives `public_activity_events` by comparing against the
  prior published snapshot, the way `build_congress_bills` already
  downloads the prior table, so no ingest-time writer is needed. Row
  shaping (column tuples, identity keys, provenance columns) lives in
  spicy-docs beside the logic that fills it, and the spicy-regs transform
  only converts rows to Arrow, merges with the prior table and publishes.
- **What a maintainer must decide, gathered in one place:** (1) confirm the
  "spicy-regs imports the function" pattern over the unused
  `public_tables`/`releases` alternative (§4); (2) resolve the rollup-on-rollup
  dependency contract conflict above; (3) decide DeltaTrack's relationship
  to spicy-docs; (4) finish or explicitly drop the value inventory's
  §2/§4/§7; (5) decide whether `public_activity_events` gets a live
  ingest-time writer or becomes a derived rollup (§3, §5); (6) confirm
  spicy-docs' own push/branch posture before any `interpretation/` work
  lands there.

---

**Ten-line summary.** spicy-regs adds a dataset via `Reader → Transform →
RollupPipeline`, one cron workflow, a `data_dictionary/descriptions.yaml`
entry, and one line in the MCP server's `TABLES` tuple — traced end to end
on `congress_bills` (§1). spicy-regs already has `congress_bills.py` and
`crs_reports.py` live, but spicy-docs' `listing.py`/`bulk_status.py` are
meant to replace both and spicy-regs' own `PLAN.md` `SR01` task (open) is
that migration, not yet done (§2). The maintainer corrected this task's
premise mid-flight: interpretation logic (stage, money-bill kind, version
kind, vote/release matching, section classification, AI summaries, the diff
engine) belongs in a new spicy-docs `interpretation/` package, not
spicy-regs or BillTrax; spicy-regs only hosts the resulting tables (§0, §4).
§3 proposes 14 tables (extending `congress_bills`, 13 new) covering every
column in BillTrax's 18 `CATALOG_TABLES`, with each column marked fact or
interpretation and photo_url/uploaded_by_user_id/status-style columns
explicitly dropped with reasons; "interest areas" turns out not to be a
column at all but a live per-user query. spicy-regs hosts a spicy-docs-computed
column exactly the way it already hosts spicy-docs-acquired facts: a
transform imports the function, shapes the row, and publishes — no new
mechanism needed (§4). A thin app is mostly `query_sql` over the published
tables plus the auth/email/private-data slice BillTrax's own inventory
already scoped to a UI (§5). The rollup contract's "never read another
rollup's output" rule conflicts with BillTrax's versions→sections→diffs
dependency chain and needs a maintainer decision before pipelines get
written (§6).
