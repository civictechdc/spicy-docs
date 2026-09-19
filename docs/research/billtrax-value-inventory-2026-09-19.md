# BillTrax value inventory: every module, column and publisher field, with a destination

Written 2026-09-19 against BillTrax `a6b685f` (read-only), spicy-docs `ee65b33`
(v0.20.0) and spicy-regs `main`. Companion to the
[intake plan](billtrax-port-2026-09-15.md), which sequences the work; this
document is the *ledger* — nothing in BillTrax may be left without a
destination or a stated deletion.

Every line count is `wc -l`. Every caller count is `grep` over `src/`,
`scripts/`, `migrations/` and `e2e/` excluding the module's own file and test.
Every behavioural claim about a divergence was executed, not read (§4).
BillTrax's docker gate was not run; nothing in BillTrax was modified.

## The split this inventory assigns to

Corrected 2026-09-19 by the maintainer, and it is narrower than the intake
plan assumed:

- **spicy-docs is the one DRY home for code** — acquisition, publisher-format
  parsing *and* shared interpretation logic. Stage rules, money-bill
  classification, version kind, vote and release matching, interest areas,
  classifications, signal extraction, PDF normalization, the agency-block
  parser and the diff engine all land here. There is no second Python home for
  logic.
- **spicy-regs is metadata hosting only** — table schemas, the data
  dictionary, the publishing pipeline and MCP exposure of tables that
  spicy-docs code produces. It receives *tables*, never code.
- **A UI keeps only** auth, email, per-user rows and pages.

So the disposition vocabulary is:

| Disposition | Meaning |
|---|---|
| `landed` | already in spicy-docs; the named module supersedes it |
| `spicy-docs / acquisition` | fetches from a publisher |
| `spicy-docs / parsing` | reads a publisher format into typed fields |
| `spicy-docs / shared logic` | interprets facts; source-agnostic; the DRY home |
| `spicy-regs hosting` | a table to host and document; no code moves |
| `delete` | dead, duplicate or superseded; reason given |
| `keep in a UI` | auth, email, per-user data, pages |

## Size of the thing being ported

| Tree | Files | Lines | Note |
|---|---|---|---|
| `src/lib/*.ts` (non-test) | 38 | 6,847 | the logic |
| `src/lib/*.test.ts` | 14 | 2,870 | 232 `it()` cases |
| `scripts/` | 30 | 6,885 | 27 TS, 3 Python |
| `migrations/` | 22 | 897 | 27 tables |
| `src/app/api/` | 38 | 2,612 | 36 routes + 2 tests |
| `src/app/` total | — | 9,035 | pages included |
| `src/components/` | 25 | — | UI |
| `submodules/DeltaTrack/` | 11 | 2,846 | 124 KB, vendored copy |
| `node_backend/` | 6 | 567 | zero callers (§1) |
| `e2e/` | 6 | 308 | Playwright |
| `ui-reference/` | **0** | 0 | two empty directories, `legitrack-hub/` and `visual-echo-virtuoso/` |

`ui-reference/` is measured empty — it costs nothing and needs no decision.

---

## 1. Per-module inventory

### 1a. `src/lib/*.ts` — sorted by disposition, then by value

Callers exclude the module's own file and its test. "Tests" names the test
file and what it actually asserts.

#### `landed` — spicy-docs already supersedes these

| Module | Lines | Does | Consumes | Produces | Callers | Tests | Superseded by |
|---|---|---|---|---|---|---|---|
| `congress-api.ts` fetch half (`congressGet` :169-191, `fetchBillMetadata` :212-268, `fetchBillVersions` :270-309, `downloadVersionText` :311-322, `downloadVersionXml` :436-446) | 463 total | Congress.gov v3 client: 3-attempt retry, 429/5xx backoff | `GET https://api.congress.gov/v3/bill/{c}/{t}/{n}` and `/text` (:217, :275); format URLs from the payload (:314, :440) | `BillMetadata`, `CongressVersion[]`, raw text/XML | 12 | `congress-api.test.ts` (26 `it`) — **only** `inferStageFromAction`; **no test covers any fetch path** | `sources/congress/bill_acquisition.py`, `bill_text.py`, `bill_status.py` |
| `congress-api.ts` `fetchAmendments` (:335-374), `fetchCommitteeBills` (:387-434) | — | Two listing routes with hand-rolled pagination (:398-431) | `/bill/{c}/{t}/{n}/amendments`, `/committee/{chamber}/{code}/bills` | `CongressAmendment[]`, `CommitteeBillRef[]` | `ingest.ts`, `discover-money-bills.ts` | none | `sources/congress/listing.py` route table (landed 2026-09-19) |
| `scripts/sync-govinfo.ts` ZIP + parse layer (:32-35 URL, :468-511 zip walk, :189-268 parse) | 550 | Downloads a BILLSTATUS zip per (congress, type), parses each XML, ingests | `https://www.govinfo.gov/bulkdata/BILLSTATUS/{c}/{t}/BILLSTATUS-{c}-{t}.zip` (:34) | `bills`, `bill_versions`, `public_activity_events`, `diff_jobs` | package.json `sync:govinfo` | `govinfo.test.ts` (12 `it`) — covers only `extractPublicLawNumber` / `extractSignedDate` | `sources/congress/bulk_status.py` + `reading/zip_archive.py` |
| `scripts/sync-members.ts` | 82 | Pulls the community legislators file, upserts `members` | `https://unitedstates.github.io/congress-legislators/legislators-current.yaml` (:14); photo URL is **constructed**, not fetched (:15) | `members` | package.json | none | `sources/legislators.py` (landed 2026-09-19, JSON not YAML, pinned and byte-bounded) |

The intake plan's "not ported (deliberate): legislators YAML" is now **stale**:
`sources/legislators.py` landed on 2026-09-19 reading the pinned JSON. The YAML
fetch in `sync-members.ts:14` is superseded, not kept.

#### `spicy-docs / acquisition`

| Module | Lines | Does | Consumes | Produces | Callers | Tests | Target module |
|---|---|---|---|---|---|---|---|
| `govinfo-pdf-fetch.ts` fetch half (:64-74, :168-197) | 289 | Builds a govinfo BILLS package URL from a `version_code` and downloads the PDF | `https://www.govinfo.gov/content/pkg/BILLS-{c}{type}{n}{slug}/pdf/….pdf` (:73), `fetch` at :175 | PDF bytes → `bill_versions` row, `source='govinfo-pdf'` (:220-239) | 5 | `govinfo-pdf-fetch.test.ts` (13 `it`): URL construction, 404/timeout/extract-failed paths, idempotency, `uploaded_by_user_id IS NULL` | extend `sources/govinfo/body_acquisition.py` — it already fetches `BILLS` bodies by package id and proves identity from summary + MODS before any body byte |
| `press-releases.ts` `pollFeeds` (:87-129) | 161 | Fetches two committee RSS feeds, extracts item fields | `appropriations.house.gov/news/press-releases.rss`, `www.appropriations.senate.gov/news/press-releases.rss` (:6, :10) | `press_releases` | 3 | none | new `sources/congress/press_releases.py`, cloned from `sources/gao/rss.py` discipline |
| `scripts/sync-roll-call-votes.ts` | 139 | Walks bill actions for recorded votes, upserts roll calls | `https://api.congress.gov/v3` (:19) bill actions | `roll_call_votes` | package.json | none | `sources/congress/listing.py` (`bill actions` route already landed) |

#### `spicy-docs / parsing` — publisher format → typed fields

| Module | Lines | Does | Consumes | Produces | Callers | Tests | Target module |
|---|---|---|---|---|---|---|---|
| `bill-tree.ts` | 489 | GPO bill-XML → flat `BillSection[]`; division/title/appropriations aware; plus a plain-text fallback splitter (:455-489) | `bill_versions.xml` | `bill_sections` rows via `section-parser.ts:55-58` | **1** (`section-parser.ts:11`) | **none** | `sources/congress/bill_tree.py`, beside `bill_text.py`; bytes through `sources/xml.py::parse_xml(allow_external_doctype=True)`. It is a *fork* of DeltaTrack `bill_tree.py` with four measured divergences — see §4 |
| `pdf-normalize.ts` | 186 | Strips GPO line numbers, VerDate/DSK footers, page numbers, bullet identifiers; rejoins hyphen breaks; merges small-caps splits | pdf-parse text | normalized text + `PdfCleanupRecord` | 11 | `pdf-normalize.test.ts` (27 `it`, 9 describes: detector, metadata stripping, trailing line numbers, hyphen rejoin, small-caps merge, space collapse, encoding, full IH doc, ENR doc) | post-extraction step over `extraction/pages.py` `PageResult` text. Its heuristics were derived against pdf-parse line layout; re-derive against pypdf/pymupdf (§7 Q3) |
| `report-parser.ts` `parseAgencyBlocks` | 66 | Splits committee-report text into agency-headed blocks | `committee_reports.text` | `report_sections` | **1** (`api/reports/route.ts:5`) | **none** | `sources/congress/report_blocks.py`; pure and dependency-free |
| `section-parser.ts` | 88 | Chooses XML vs text path, persists and caches sections | `bill_versions.xml`/`.text` | `bill_sections` | 10 | none | folds into the bill-tree module as its entry point; the DB half stays behind a table writer |
| `congress-api.ts` `stripMarkup` (:448-462) / `sync-govinfo.ts:55-70` | — | Identical 13-step markup stripper, **duplicated verbatim in two files** | raw XML/HTML | plain text | — | none | one helper; `reading/markup.py` already exists in spicy-docs |
| `congress-api.ts` `slugify` (:130-132) / `sync-govinfo.ts:40-42` / `version-kind.ts:103` | — | Identical slugifier, **three copies** | version type name | `version_code` slug | — | indirectly | one helper beside the `version_code` vocabulary (§2) |
| `congress-api.ts` `chooseFormat`/`chooseXmlFormat` (:151-163), `sync-govinfo.ts pickVersionUrls` (:255-268) | — | Format preference: XML → Text → PDF; `sync-govinfo` adds a `.xml`-suffix fallback (:262) when `<type>` is absent | `textVersions[].formats[]` | selected URL | — | none | one format-choice function; the URL-suffix fallback is the behaviour to keep (port contract) |

#### `spicy-docs / shared logic` — interpretation, the DRY home

| Module | Lines | Does | Consumes | Produces | Callers | Tests | Target module |
|---|---|---|---|---|---|---|---|
| `congress-api.ts` `STAGE_RULES` (:5-90) + `inferStageFromAction` (:142-149) + `inferStage` (:134-140) | — | 7-stage ladder from free action text; ordered, first-match-wins | `bills.status` (untruncated) or a version type string | `bills.stage` | 8 via `stages.ts` | `congress-api.test.ts` (26 `it`) — the only tested rule set in this row | `interpretation/bill_stage.py`. Must move out of the network module; see fix ledger item 1 |
| `money-bills.ts` | 201 | 10-rule priority classifier → `MoneyBillKind`, subcommittee, fiscal year, reason codes | `BillMetadata.title` + committee-referral booleans | `bills.money_bill_kind`/`fiscal_year`/`appropriations_subcommittee`/`classified_by` | 9 | `money-bills.test.ts` (18 `it`) | `interpretation/money_bills.py` |
| `version-kind.ts` | 124 | Slug → `full_text` / `procedural_amendments` / `procedural_summary` / `kind_uncertain` / `unknown`, with a size heuristic | `bill_versions.version_code` + `body_bytes`/`section_count` | `bill_versions.kind` | 5 | `version-kind.test.ts` (32 `it`) | `interpretation/version_kind.py`. The slug vocabulary is sealed (§2) |
| `bill-identify.ts` `extractSignals` (:93-215) | 464 | Extracts bill type/number, congress, title (3 tiers), sponsor last name, first 5 section headings from normalized PDF text | normalized PDF text | `ExtractedSignals` | 9 (incl. `identifyBill`) | `bill-identify.test.ts` (36 `it`, 5 describes on `extractSignals` alone) | `interpretation/bill_signals.py`; the acceptance harness is `scripts/audit-bill-identify.ts` and moves with it |
| `bill-identify.ts` `identifyBill` (:264-463) + weights (:49-53) + thresholds (:40-43) | — | Weighted candidate scoring against the catalog (0.55/0.20/0.10/0.10/0.05), ≤3 heading queries | `bills`, `bill_sections` | `BillCandidate[]` | 4 | `bill-identify.test.ts` (3 describes) | same module; the DB lookup becomes a table read |
| `financial.ts` | 209 | Extracts and pairs dollar amounts, computes deltas | section bodies | `financial_changes` | **2** | **none** | **`delete`** — see below. It is a TS re-implementation of `diff_bill.py:24-161` and carries two measured bugs the Python fixed (§4) |
| `section-diff.ts` TS-fallback core (:84-275) | 586 | Hyphen-tolerant similarity, greedy pairing with an O(N·M) cap, move reconciliation | `bill_sections` | `section_diff_items` | 11 | `section-diff.test.ts` (18 `it`): `canonicalToken`, body equivalence, the asymmetric-pair guard | `interpretation/section_diff.py` — merge with DeltaTrack `diff_bill.py:164-522`, which already has `_similarity_pair`, `_match_collision_group`, `match_nodes`, `reconcile_moves`. Keep the two guards the TS side learned: `GREEDY_PAIR_GROUP_CAP = 200` (:26) and `SECTION_COUNT_THRESHOLD = 10` (:40) |
| `diff.ts` `diffWords` | 40 | O(N·M) LCS word diff | two strings | `DiffSeg[]` | **1** | none | `delete` — DeltaTrack `diff_text` (`diff_bill.py:322`) is the survivor; see §4 |
| `roll-call-votes.ts` `matchVotesToBills` (:133-159) | 160 | Joins votes to bills by a bill-number regex in the question text | `roll_call_votes.question` | `roll_call_votes.bill_id` | 2 | none | `interpretation/vote_matching.py`. **Port the intent, not the regex** — measured broken (§2) |
| `press-releases.ts` `matchReleasesToBills` (:131-160) | — | Joins releases to bills by a per-bill regex built in a nested loop | `press_releases`, `bills` | `press_releases.bill_id` | 3 | none | `interpretation/release_matching.py`. O(releases × bills) with a regex compiled per pair (`:146-149`): 500 × 1000 = 500k compilations per run |
| `members.ts` `getMemberByName` (:75-93) | 93 | Sponsor-string → member, exact then last-name | `members` | `Member` | 2 | none | `interpretation/member_matching.py` |
| `interest-areas.ts` `findMatchingSections` (:83-141) | 141 | Boolean full-text match of user keywords against section bodies | `bill_sections` | matched excerpts | 5 | none | `interpretation/interest_areas.py` for the matching; the CRUD half (:23-81) is per-user and **stays in a UI** |
| `classifications.ts` `classifyVersion` (:47-103) + label vocabulary (:5, :79-84) | 104 | LLM-labels each section as funding_opportunity / directive / deadline / restriction / other, in batches of 30 | `bill_sections` | `section_classifications` | 1 | none | `interpretation/section_classification.py`; the five-label vocabulary and the prompt are the sealed part (§2) |
| `bill-summaries.ts` | 235 | LLM bill summary with model + prompt-version + content-hash provenance (`PROMPT_VERSION = "v1"`, :17) | `bill_versions.text` | `bill_summaries` | 4 | none | `interpretation/bill_summaries.py`; keep the provenance columns exactly |
| `version-kind.ts` labels/warnings (:80-93) | — | Display strings for each kind | — | UI text | 5 | covered | travel with the vocabulary so the UI cannot re-invent them |
| `pair-type.ts` | 40 | Derives `pdf-pdf` / `pdf-xml` / `xml-xml` from a version pair and the presence of a `govinfo-pdf` twin | version list | comparison strategy | 2 | `pairTypeFor.test.ts` (10 `it`) | `interpretation/pair_type.py` — it decides which diff path runs, so it belongs with the diff engine |
| `stages.ts` | 26 | The 7-stage ladder, labels and progress | — | UI + rules | 8 | none | ships with `bill_stage.py`; labels are UI, the order is logic |

#### `spicy-regs hosting` — tables, no code

`db.ts` (153 lines, 95 callers) is the mysql2 pool; `catalog-tables.ts` (77
lines) is the authoritative catalog/user split. Neither ports: spicy-regs
publishes Parquet, not MySQL. What ports is the *shape* — §3.

| Module | Lines | Role | Disposition |
|---|---|---|---|
| `db.ts` | 153 | mysql2 pool, `query`/`queryOne`/`execute`/`withTransaction`/`ensureDb` | `delete` — replaced by spicy-regs' Parquet/R2 reader and a thin UI DB |
| `catalog-tables.ts` | 77 | `CATALOG_TABLES` (18), `USER_TABLES` (8), `METADATA_STRIP_COLUMNS` (4), `TABLES_WITH_CREATED_AT` (14) | **keep as the partition map**: `CATALOG_TABLES` is exactly the `spicy-regs hosting` set, `USER_TABLES` exactly the `keep in a UI` set |
| `committee-reports.ts` | 210 | CRUD + `getAgencyRecurrence` (:136) and `getSectionsForAgency` (:178) | table access → `spicy-regs hosting`; the two aggregate queries are logic → `spicy-docs / shared logic` |
| `public-activity.ts` | 138 | Append-only public event log; `describeEvent` (:113) renders it | `spicy-regs hosting` (`public_activity_events`); `describeEvent` is UI |
| `diff-queue.ts` | 173 | Job queue over `diff_jobs` with a generated `is_active` column and a claim index | `delete` — a queue is orchestration, not a published table. spicy-docs pipelines own their own scheduling |
| `activity.ts` | 126 | Per-user feed joining `user_subscriptions` | `keep in a UI` |

#### `keep in a UI`

| Module | Lines | Callers | Why |
|---|---|---|---|
| `users.ts` | 89 | 7 | accounts |
| `password-reset.ts` | 46 | 2 | hash-only reset tokens |
| `email.ts` | 113 | 2 | SMTP; `email.test.ts` (3 `it`) |
| `notifications.ts` | 46 | 2 | version-alert dedup via `notification_log` |
| `notes.ts` | 61 | 4 | per-user notes |
| `topics.ts` | 47 | 3 | per-user topics |
| `interest-areas.ts` CRUD (:23-81) | — | 5 | per-user rows |
| `upload-cache.ts` | 114 | 4 | in-memory inspect→commit handoff, 15-min TTL; `upload-cache.test.ts` (10 `it`) |
| `utils.ts` | 15 | 14 | `cn()` (tailwind) + `formatDate` |
| `ai.ts` | 20 | 5 | provider wiring |
| `bills.ts` | 968 | 29 | the query layer: privacy `visibilityClause` (:63-71), catalog reads, ingest upserts (:557-685). The *privacy model* is UI policy; the *upsert column list* is the schema contract (§3). `bills.test.ts` (8 `it`) + `bills-privacy.test.ts` (20 `it`, 7 describes) |

#### `delete`

| Module | Lines | Reason |
|---|---|---|
| `financial.ts` | 209 | duplicate of `diff_bill.py:24-161`, with two bugs the Python already fixed (§4) |
| `diff.ts` | 40 | duplicate of `diff_bill.py:322` `diff_text`; one caller |
| `mock-data.ts` | 156 | fixture data; only `formatDate` (:154) is reachable and `utils.ts:12` already has it |
| `python-diff.ts` | 108 | the subprocess bridge; disappears when the diff engine is in-process Python |
| `db.ts` | 153 | see above |
| `diff-queue.ts` | 173 | see above |
| `node_backend/` | 567 (6 files: `bill_compare_service.js` 338, `server.js` 127, README 55, lockfile 27, `package.json` 13, Dockerfile 7) | deployed in all three compose files, **zero callers** — a drifted duplicate |
| `roll-call-votes.ts` `upsertMemberVote` (:108-123) | 16 | **no callers anywhere**; `member_votes` is migrated (009), listed in `catalog-tables.ts:27` and exported, but never written |

### 1b. `scripts/*.ts|py` — 30 files (27 TS, 3 Python), 6,885 lines

`package.json:5-32` names **14 of 27** TypeScript scripts. Three more are
legitimately unnamed (`catalog-tables.ts` is a constants module,
`discover-money-bills.ts` is dynamic-imported at `ingest.ts:449`,
`ingest.test.ts` is reached by the vitest glob `vitest.config.ts:21`). The
remaining **ten have no caller anywhere** — not `package.json`, not a
Dockerfile, compose file, README or CI workflow.

#### `spicy-docs / acquisition` — the fetchers

| Script | Lines | Consumes (publisher route, file:line) | Produces | Callers | Tests | Target |
|---|---|---|---|---|---|---|
| `ingest.ts` | 483 | `api.congress.gov/v3/bill/{c}/{t}/{n}` (`congress-api.ts:218`) at :116-119; `/amendments` at :283; format URLs at :204-207 | `bills`, `bill_versions`, `bill_sections`, `section_diffs`+`_items`+`financial_changes`, `amendments` (`bills.ts:943`), `public_activity_events`, `bill_summaries`, `notification_log`, `press_releases`; direct `UPDATE bills SET status, stage` :373; `DELETE FROM bill_sections` :399 | `package.json:14`, `README.md:148/337` | `ingest.test.ts` — **does not import this file**; it re-implements the sequence against mocked `@/lib/congress-api`, so `parseArgs`, `parseBillRef`, `ingestBill`, `reextractAll`, `restageAllBills` are uncovered | replaced by a spicy-docs acquisition run + a table writer |
| `sync-govinfo.ts` | 550 | bulk zip :34; per-version format URLs :373-376 | as §1a | `package.json:25`; imported as a module by `g1-identify-gaps.ts:24` and `govinfo.test.ts:10` (hence the entry guard at :545, the only one in the directory) | `govinfo.test.ts` (12 `it`) | `landed` — `bulk_status.py` |
| `poll-congress.ts` | 101 | `fetchBillVersions` via `poll.ts:28`; `fetchBillMetadata` :69 | `bill_versions`, `notification_log`, `public_activity_events`; direct `UPDATE bills SET stage, status` :72-75 | `package.json:18`, `README.md:184/341` | none | delta path over `listing.py` by update date |
| `sync-members.ts` | 82 | legislators YAML :14 | `members` | `package.json:17` | none | `landed` — `sources/legislators.py` |
| `sync-press-releases.ts` | 102 | `appropriations.house.gov/rss/` :20, `www.appropriations.senate.gov/rss/` :24 | `press_releases` | `package.json:15` | none | the RSS source. **These two URLs differ from `press-releases.ts:6/10`** — open decision 5 |
| `sync-roll-call-votes.ts` | 139 | `api.congress.gov/v3` :19; `/bill/{c}/{t}/{n}/actions?limit=50` :59. Its header names the authoritative `clerk.house.gov/evs/{year}/roll{N}.xml` (:6) and Senate LIS XML (:7) — **neither is fetched** | `roll_call_votes` only; never `member_votes` | `package.json:16` | none | `listing.py` bill-actions route |
| `discover-money-bills.ts` | 229 | `/committee/{chamber}/{code}/bills` (`congress-api.ts:400`) at :42; committee codes `hsap00/ssap00/hsbu00/ssbu00/hsas00/ssas00` at :29-34 | nothing directly — writes through an injected `ingestBill` (:119-129, called :214) | dynamic import at `ingest.ts:449` | none (`money-bills.test.ts` covers the classifier it calls) | the six committee codes are a **sealed vocabulary** (§2); the crawl is a `listing.py` route |
| `repair-xml.ts` | 130 | re-fetches `bill_versions.congress_url` :20 | `UPDATE bill_versions SET xml` :85; `bill_sections`; `section_diffs` | `package.json:27` | none | re-hydration from captures, not re-fetch |

#### `spicy-docs / shared logic` — the Python bridge and its harnesses

| Script | Lines | Role | Callers | Disposition |
|---|---|---|---|---|
| `diff_service.py` | 148 | stdin/stdout JSON bridge to DeltaTrack; imports `normalize_bill` (`bill_tree.py:590`) and `diff_bills`/`compute_financial_change`/`financial_change_to_dict` (`diff_bill.py:523/125/153`); `sys.path.insert` relative to `__file__` at :19 | `python-diff.ts:69-70`; `Dockerfile:38-39`; `README.md:338` | **`delete`** — the bridge exists only because the engine is out-of-process. In spicy-docs the diff engine *is* the process. Its two contributions survive as code: `BODY_CAP = 30_000` (:31) and the three-stage `real_quick_ratio`/`quick_ratio`/`ratio` < 0.4 bail-out (:47-51) |
| `audit-bill-identify.ts` | 263 | Runs `extractSignals` over `LEFT(bv.text, 8192)` for every bill, writes `artifacts/audit-bill-identify-*.csv` | **none** | **keep as the acceptance harness** for the `extractSignals` port, then delete. It is the only evidence that the signal extractor works at catalog scale |
| `validate-pdf-normalization.ts` | 80 | before/after of `normalizePdfText` + reduction stats | `package.json:31` (`validate:pdf`) | keep until the PDF normalizer is re-derived against pypdf, then delete |
| `validate-pdf-pdf-concordance.ts` | 247 | Two hardcoded HR 7148 scenarios: same PDF twice (expect ~100%), IH vs EH (expect < 100%). No DB access | **none**, and **not in `package.json`** | the intake plan calls this "the gate" for Phase 5. It is not wired to anything. Either wire it or stop calling it a gate (§7 Q3) |

#### `delete` — one-shot harnesses and duplicates

| Script | Lines | Callers | Reason |
|---|---|---|---|
| `validate-pdf-xml-concordance.ts` | 587 | none | largest script in the tree; carries a **private, drifted copy** of the slug map at :44-64 (§2). Methodology stays in git history |
| `gamma-6-validation.ts` | 463 | none | γ.6 five-bill simulation; **writes `bill_versions` rows it never cleans up** (:248 → `govinfo-pdf-fetch.ts:221`) |
| `p3_prototypes.py` | 482 | none | similarity bake-off against 10 inline fixtures + `p2_db_results.json`; its *conclusion* is the 0.4 threshold already in the code |
| `p2_catalog_survey.py` | 374 | none | reaches MySQL by shelling out to an embedded Node script with **hardcoded credentials** (`host: 'mysql', user: 'billtrax', password: 'billtrax'`, :142) |
| `g1-identify-gaps.ts` | 283 | none | a **second** BILLSTATUS zip parser (:61) beside `sync-govinfo.ts:34` |
| `privacy-curl-test.ts` | 244 | none | HTTP probes against a running app; `bills-privacy.test.ts` (20 `it`) is the vitest equivalent and is wired |
| `gamma-7-smoke.ts` | 202 | none | seeds a real row in **`users`** (:49-52) |
| `check-govinfo-pdf-coverage.ts` | 110 | none | HEAD-probe coverage tally. **Blocked**: `govinfo-pdf-fetch.test.ts:57` asserts the canonical slug map "matches check-govinfo-pdf-coverage.ts slug list" — deleting the script orphans that test's premise. Rewrite the assertion against the canonical map first |
| `title-recon.ts` | 88 | **zero grep hits repo-wide**, not even a usage comment | throwaway recon over a hardcoded `/tmp/hr7148ih.pdf` |
| `identify-spotcheck.ts` | 23 | none | `console.log` wrapper over `extractSignals`/`identifyBill` |

#### `keep in a UI` / orchestration

| Script | Lines | Callers | Why |
|---|---|---|---|
| `catalog-tables.ts` | 77 | `catalog-export.ts:25-30`, `catalog-import.ts:20` | the partition map (§3) |
| `catalog-export.ts` | 335 | `package.json:22` | derived-data replication, not a publisher contract. spicy-regs publishing replaces it |
| `catalog-import.ts` | 452 | `package.json:23/24` | same; its four pre-flight gates and FULLTEXT drop/rebuild are MySQL-specific |
| `diff-worker.ts` | 116 | `package.json:30`; all three compose files; `README.md:66/125/240/243`; `.env.example:70` | `delete` with `diff-queue.ts` |
| `backfill-deltatrack.ts` | 113 | `package.json:28` | `delete` — a one-time migration off TS-fallback diffs |
| `precompute-catalog.ts` | 150 | `package.json:29` | `delete` — batch warming; a pipeline replaces it |
| `repair-sections.ts` | 81 | `package.json:26` | `delete` — repairs a gap that a pipeline would not create |
| `ingest.test.ts` | 151 | vitest glob | `delete` with `ingest.ts` |

**Count.** 8 acquisition · 4 shared logic (2 keep-then-delete) · 10 delete
(harnesses) · 8 orchestration of which 6 delete. Deleting the ten
no-caller scripts removes **2,856 lines** — 41% of `scripts/` — before any
port work begins.

---

## 2. Sealed vocabularies and rules

These are the things that must move *intact*. Changing any of them silently
reclassifies stored rows. Each is marked **publisher fact** (a vocabulary the
publisher defines; spicy-docs parsing) or **interpretation** (a judgement
BillTrax makes; spicy-docs shared logic).

### 2.1 The `version_code` slug map — publisher fact, with a drifted second copy

`version_code` is a slug of the publisher's human-readable version type
(`"Engrossed Amendment Senate"` → `engrossed-amendment-senate`), produced by
three identical copies of `slugify` (`congress-api.ts:130-132`,
`sync-govinfo.ts:40-42`, and inline at `version-kind.ts:103`). It is keyed
into SQL in `migrations/016_version_kind.ts:7-59` and into
`uq_version (bill_id, version_code, source)`
(`migrations/020_version_uniqueness_includes_source.ts:37`). **It must not
change.**

The canonical slug → govinfo package-suffix map,
`VERSION_CODE_TO_GOVINFO_SLUG` (`govinfo-pdf-fetch.ts:26-58`), 16 slug keys
plus 14 passthrough short codes:

| slug | govinfo | slug | govinfo |
|---|---|---|---|
| `introduced-in-house` | `ih` | `held-at-desk-senate` | `hds` |
| `introduced-in-senate` | `is` | `returned-to-the-house-by-unanimous-consent` | `rfh` |
| `engrossed-in-house` | `eh` | `engrossed-amendment-senate` | `eas` |
| `engrossed-in-senate` | `es` | `engrossed-amendment-house` | `eah` |
| `enrolled-bill` | `enr` | `reported-in-house` | `rh` |
| `public-law` | `enr` | `reported-in-senate` | `rs` |
| `placed-on-calendar-senate` | `pcs` | `placed-on-calendar-house` | `pch` |
| `referred-to-senate` | `rds` | `referred-to-house` | `rfh` |

Two entries collide deliberately: `public-law` → `enr` (:32) and
`returned-to-the-house-by-unanimous-consent` → `rfh` (:38). Both are correct
and both must survive.

The package URL is built at `govinfo-pdf-fetch.ts:72-73`:

```
const pkg = `BILLS-${congress}${billType.toLowerCase()}${number}${slug}`
return `https://www.govinfo.gov/content/pkg/${pkg}/pdf/${pkg}.pdf`
```

**The drift.** `validate-pdf-xml-concordance.ts:44-64` carries a private
`VERSION_CODE_TO_SLUG` missing `pch`, `rds`, `rfh` and `hds`. Worse, the test
that is supposed to catch this — `govinfo-pdf-fetch.test.ts:57`, *"matches
check-govinfo-pdf-coverage.ts slug list"* — checks only the **ten** slugs
`ih,is,eh,es,enr,pcs,eas,eah,rh,rs` that appear in the file it compares
against. A one-directional check over a subset chosen by the thing under test
is exactly the shape that reports agreement with itself; it cannot see the
four missing entries. **The port's check must be bidirectional over the full
key set**, and must fail when either side gains a key.

### 2.2 `STAGE_RULES` and `inferStageFromAction` — interpretation

`congress-api.ts:5-90`. Seven stages, **ordered, first-match-wins**, matched
as lowercase substrings. Order is load-bearing and the code says so twice
(:6 `"Must stay first — 'public law' substring appears in many action texts"`;
:76-77 `"ordered before 'introduced' because 'reported' can appear alongside
'introduced'"`).

| # | Stage | Matchers |
|---|---|---|
| 1 | `law` | `public law`, `public print`, `became public law`, `signed by president`, `approved by president` |
| 2 | `presented` | `enrolled`, `presented to president`, `sent to the president`, `transmitted to president` |
| 3 | `conference` | `conference report`, `conference committee`, `resolving differences`, `requests a conference`, `sent to conference`, `appointed conferees`, `returned to house from senate with amendment`, `returned to senate from house with amendment`, `house insisted on its amendment`, `senate insisted on its amendment` |
| 4 | `passed_chamber` | `engrossed`, `passed house`, `passed senate`, `passed/agreed to`, `on passage`, `agreed to in house`, `agreed to in senate`, `passed by recorded vote`, `passed by voice vote`, `failed of passage` |
| 5 | `other_chamber` | `received in the senate`, `received in the house`, `referred`, `placed on calendar`, `placed on the union calendar`, `placed on senate legislative calendar`, `calendar`, `held at the desk`, `motion to proceed`, `cloture`, `star print` |
| 6 | `committee` | `reported`, `ordered to be reported`, `markup` |
| 7 | `introduced` | `introduced` |

Two entry points share the rules: `inferStage(versionType)` (:134-140) feeds
a **version type string**, `inferStageFromAction(actionText)` (:142-149) feeds
**action text**. Both default to `introduced`. This is proven source-agnostic
— `sync-govinfo.ts:308` feeds it raw BILLSTATUS `latestAction.text`.

The ladder itself is `stages.ts:1-18`, with `stageIndex` (:20) and
`stageProgress` (:24).

**Fix before porting.** `sync-govinfo.ts:248` does
`status: rawStatus.slice(0, 100)` and `:308` then infers the stage from that
truncated string, even though `migrations/021_widen_bills_status.ts:25`
widened the column to 500 precisely because NDAA-class actions exceed 100.
Infer from untruncated text.

### 2.3 `classifyMoneyBill` — interpretation

`money-bills.ts:123-201`. Ten rules, most specific first; the docstring at
:111-121 states the priority and the code matches it.

| # | Rule | Test | Result |
|---|---|---|---|
| 1 | manual override | `${congress}-${type}-${number}` in `MANUAL_OVERRIDES` (:93-95, **empty on day one**) | that kind |
| 2 | NDAA | `/national\s+defense\s+authorization/i` (:143) | `ndaa` — **must precede** the appropriations checks, because NDAA authorizes, it does not appropriate (:142) |
| 3 | CR | `/continuing\s+(resolution\|appropriations)/i` (:148) | `continuing_resolution` |
| 4 | supplemental | `/supplemental\s+appropriations/i` (:153) | `supplemental` |
| 5 | rescission | `/rescissions?\s+act\|^rescissions?\b/i` (:158) | `rescission` |
| 6 | omnibus | `/(consolidated\|further\s+consolidated\|further\s+continuing)\s+appropriations/i` or `/\bomnibus\b/i` (:164-165) | `omnibus` |
| 7 | reconciliation by title | `/budget\s+reconciliation\|reconciliation\s+act/i` (:171) | `reconciliation` |
| 8 | reconciliation by referral | budget committee **and** `/reconciliation/i` (:176) | `reconciliation` |
| 9 | regular | appropriations committee **and** `/appropriations/i` (:182) | `regular_appropriations` + subcommittee |
| 10 | other money | appropriations committee **and** `/\b(appropriat\|fund\|rescind\|rescission\|transfer\|reprogram\|spend\|outlay\|budget\|fiscal)\w*/i` (:193) | `other_money` — the bare referral alone is explicitly too noisy (:188-190) |
| — | otherwise | | `null` — not a money bill |

Only rules 1 and 9 set a subcommittee; every other rule returns
`subcommittee: null` even when the title matches a subcommittee pattern.
That asymmetry is deliberate and easy to lose in a port.

**The twelve statutory subcommittees** (`money-bills.ts:48-61`), each a regex
→ canonical name, and the same twelve strings repeated as a display list at
`bills.ts:251-264`. Two copies; one must survive:

`Agriculture, Rural Development, FDA` · `Commerce, Justice, Science` ·
`Defense` · `Energy and Water Development` ·
`Financial Services and General Government` · `Homeland Security` ·
`Interior, Environment` · `Labor, HHS, Education` · `Legislative Branch` ·
`Military Construction, Veterans Affairs` · `State, Foreign Operations` ·
`Transportation, HUD`

Fiscal year (`detectFiscalYear`, :70-77) accepts two forms:
`/fiscal\s+year\s+(\d{4})/i` and `/appropriations\s+act,?\s+(\d{4})/i`, both
rendered `FY{year}`.

The eight `MoneyBillKind` values (:12-20) are an **ENUM in MySQL**
(`migrations/011_money_bill_metadata.ts:6-15`) — adding one is a migration.
`reasonCodes` (`manual_override`, `title_ndaa`, `title_continuing_resolution`,
`title_supplemental`, `title_rescissions`, `title_omnibus`,
`title_reconciliation`, `budget_committee_reconciliation`,
`approps_committee_plus_title`, `subcommittee_match`,
`approps_committee_plus_money_keyword`) are **computed but never persisted** —
no column holds them. Give them one (§3).

**The six committee codes** that produce the referral booleans
(`discover-money-bills.ts:29-34`) are part of this vocabulary:
`hsap00`/`ssap00` (appropriations), `hsbu00`/`ssbu00` (budget),
`hsas00`/`ssas00` (armed services). In the bulk path the same booleans come
from substring matching on committee names instead
(`sync-govinfo.ts:292-294`: `includes("appropriations")`, `"budget"`,
`"armed services"`). **Two different derivations of the same three inputs** —
pick one in the port.

### 2.4 `classifyVersionKind` — interpretation over a publisher vocabulary

`version-kind.ts:101-123`. Five kinds (:8-13). The slug is re-normalized
defensively at :103 with the same slugify expression.

- **`PROCEDURAL_AMENDMENTS_SLUGS`** (:17-28), 10 entries — edit-instruction
  documents, not bill text. These cause the "+0 added / −N removed" trap
  (:16): `engrossed-amendment-senate`, `engrossed-amendment-house`,
  `amendment-senate`, `amendment-house`, `amendment-engrossed-senate`,
  `amendment-engrossed-house`, `amendment-senate-house`,
  `additional-sponsors-house`, `failed-amendment-senate`,
  `failed-amendment-house`.
- **`PROCEDURAL_SUMMARY_SLUGS`** (:31-36), 4 entries:
  `statement-of-substance`, `held-at-desk-senate`, `held-at-desk-house`,
  `previously-passed-senate`.
- **`FULL_TEXT_SLUGS`** (:39-78), 29 entries: the introduced/engrossed/
  enrolled/public-law core, committee referral and reporting, calendar
  placement, passage variants, discharge, failed passage, reference change,
  unanimous-consent returns, originals and agreed-to.

Then three fallbacks, in order (:108-123):

1. a `FULL_TEXT` slug with `section_count < 20` **or** `body_bytes < 10_000`
   → `kind_uncertain` (:111-113);
2. an unlisted slug containing `"amendment"` → `procedural_amendments`
   (:119);
3. an unlisted slug with `body_bytes >= 10_000` → `full_text`, else
   `unknown` (:122-123).

`migrations/016_version_kind.ts:7-59` **inlines the same three lists** into
SQL — the comment at :5 says *"Mirrors src/lib/version-kind.ts — inlined here
to avoid importing app code."* A second copy that no test compares. The
migration's backfill also applies only the size half of the heuristic
(`LENGTH(text) < 10000`, :88-89), never the section-count half. Port the
vocabulary once and generate the backfill from it.

`VERSION_KIND_LABELS` (:80-86) and `VERSION_KIND_WARNINGS` (:89-93) are the
user-facing strings; they should travel with the vocabulary so a UI cannot
invent its own.

### 2.5 `extractSignals` — interpretation

`bill-identify.ts:93-215`. Five signals, with fixed windows the docstring
states (:11-15) and the code honours.

| Signal | Window | Pattern | file:line |
|---|---|---|---|
| bill type + number, prose | first 3 KB | `/\b(H\.?\s*R\.?\|S\.?\|H\.?\s*J\.?\s*Res\.?\|S\.?\s*J\.?\s*Res\.?\|H\.?\s*Con\.?\s*Res\.?\|S\.?\s*Con\.?\s*Res\.?\|H\.?\s*Res\.?\|S\.?\s*Res\.?)\.?\s*(\d{1,5})\b/i` | :101-102 |
| bill type + number, GPO bullet | first 3 KB | `/[•·]\s*(HR\|S\|HJRES\|SJRES\|HCONRES\|SCONRES\|HRES\|SRES)\s+(\d{1,5})\s/i` | :110 |
| congress | first 3 KB | `/(\d{2,3})(?:st\|nd\|rd\|th)?\s*Congress/i` | :119 |
| title tier A | **full text** | ``/may be cited as (?:the\s+)?(?:''\|["'`“‘]) *(.+?) *(?:''\|["'`”’])/i`` — the `''` alternative consumes GPO's doubled single-quote as one delimiter (:126-128) | :129 |
| title tier B | first 10 KB, **last** marker | `/\b(?:A\s+BILL\|AN\s+ACT)\b/ig` scanned to the last hit (:148-151, "not a quoted reference that appears later"), then stopped by `/Be it enacted\|SECTION\s+1[\s\.—]\|SEC\.\s*1[\s\.—]/i` within 250 chars | :148, :156 |
| title tier C | chars 200–600 | positional fallback | :171 |
| sponsor last name | first 6 KB | `/\b(?:Mr\|Ms\|Mrs\|Mx\|MR\|MS\|MRS\|MX)\.?\s+([A-Z])\s*\n?\s*([A-Z]{2,})(?:[a-z]+\|\b)/` — two groups concatenated so the small-caps line break can fall anywhere (:188-196) | :199 |
| section headings | full text, first 5 | `/^SEC(?:TION\|\.)?\s*(\d+)\.?\s*[—\-.]?\s*(.+)$/gim` | :206 |

`titleSource` is recorded as one of `may-be-cited-as` / `fallback-marker` /
`fallback-position` / `none` (:66) and logged (:314) — it is the only
observability on extraction quality, and it belongs in the port.

`normalizeForComparison` (:218-224) — lowercase, non-word → space, collapse,
trim — is applied to titles and headings and is part of the contract.

**The scoring half** (`identifyBill`, :264-463) is separate and equally
sealed: weights `0.55 / 0.20 / 0.10 / 0.10 / 0.05` (:49-53, "must sum to
1.0"), thresholds `high: 0.85, medium: 0.55` (:40-43), congress off-by-one
scored `0.3` (:360), heading overlap accepted at Jaccard `>= 0.5` (:415),
results capped at 5 and filtered at `confidence >= 0.1` (:437-438), and at
most 3 heading queries (:388, :392).

### 2.6 The agency-block parser — publisher fact

`report-parser.ts:1-66`. Twelve `KNOWN_PATTERNS` (:6-19) matched against a
trimmed line, all anchored `^…$` with the `m` flag:

`DEPARTMENT OF …` · `OFFICE OF …` · `BUREAU OF …` · `AGENCY FOR …` ·
`NATIONAL … (ADMINISTRATION|AGENCY|FOUNDATION|INSTITUTE|SERVICE|COUNCIL)` ·
`CORPS OF …` · `UNITED STATES …` · `FOOD AND …` · `GENERAL SERVICES …` ·
`SMALL BUSINESS …` · `ENVIRONMENTAL …` ·
`FEDERAL … (AGENCY|COMMISSION|BOARD|AUTHORITY)`

plus three fallbacks in `isAgencyHeader` (:21-28): a length gate of 5–100
characters (:23), any all-caps line of ≥ 2 words matching
`/^[A-Z][A-Z\s,()&/'-]+$/` (:26), and the generic
`AGENCY_HEADER = /^([A-Z][A-Z\s,()&/'-]{4,})\s*$/m` (:4).

Note the docstring says *"5+ words"* (:25) while the code tests
`>= 2` (:26). The **code** is what produced every stored `report_sections`
row; port the code and correct the comment.

When no header matches, the whole text becomes one block labelled
`"Full Report"` (:62) — a sentinel a UI may rely on.

### 2.7 PDF normalization rules and `PdfCleanupRecord` — publisher fact

`pdf-normalize.ts`. Seven named artifacts of GPO PDFs are listed at :4-14 and
handled in six ordered steps.

Detectors (:39-51):

| Constant | Pattern | Effect |
|---|---|---|
| `VERDATE_RE` | `/^VerDate\s/` | dropped, sets `gpoFooters` |
| `DSK_USER_RE` | `/^\w+ on DSK\w+ with \$/` | dropped, sets `gpoFooters` |
| `PAGE_NUM_RE` | `/^\d{1,4}\s*$/` | dropped silently |
| `BULLET_BILL_RE` | `/^[•·]\s*[A-Z]/` | dropped silently |

`detectLineNumbered` (:64-74): **≥ 3 content lines AND > 30% of them ending
in `/[\s-]\d{1,2}$/`** (:58, :73). The 1–2 digit bound is the page line range
(:57).

The six steps of `normalizePdfText` (:80-186), **in this order**:

1. encoding — CRLF/CR → LF, `[‘’]` → `'`, `[“”]` → `"`, NBSP → space (:82-87);
2. metadata filtering (:101-105);
3. line-number stripping, hyphen form `/^(.*\w)-(\d{1,2})$/` (:119) tried
   **before** space form `/^(.*\S) (\d{1,2})$/` (:122) — the hyphen is kept
   and stripped later;
4. small-caps merge: a lone `/^[A-Z]$/` line followed by a line starting
   `/^[A-Z]/` (:141-143);
5. hyphen rejoin, stripping the break hyphen and leaving a `"\x00"` sentinel
   (:159-166);
6. **collapse `/  +/g` → one space, then filter the sentinels** (:172-174).

**The order in step 6 is the one the intake plan flags:** the collapse runs
over already-merged lines, so a space introduced by the merge is collapsed,
and the sentinel filter runs before the collapse in the chained expression.
Reproduce the chain, not a description of it.

`PdfCleanupRecord` (:22-28) is **persisted** as JSON in
`bill_versions.cleanup_applied` (`migrations/017_cleanup_applied.ts:6`) and
written at `bills.ts:670` and `govinfo-pdf-fetch.ts:236`:

```ts
export interface PdfCleanupRecord {
  lineNumbers: boolean        // detectLineNumbered() verdict
  gpoFooters: boolean         // a VerDate or DSK line was dropped
  spacingNormalized: boolean  // always true (:181)
  smallCapsMerges: number     // count
  hyphenRejoinCount: number   // count
}
```

`spacingNormalized` is hardcoded `true`, so it carries no information; keep
the key for compatibility with stored rows and stop writing meaning into it.

### 2.8 The classification label vocabulary — interpretation

`classifications.ts:5` and the zod enum at :25:
`funding_opportunity` · `directive` · `deadline` · `restriction` · `other`,
stored in `section_classifications.label VARCHAR(50)`
(`migrations/006:8`) under `UNIQUE (section_id, label)` (:11).

The **definitions live only in the prompt** (:80-84) and are the actual
vocabulary:

- `funding_opportunity` — allocates funds, makes appropriations, authorizes spending
- `directive` — mandates an action or behavior by an agency or entity
- `deadline` — sets a due date, reporting requirement, or time limit
- `restriction` — prohibits or limits an action
- `other` — doesn't fit the above

Batch size 30 (:64), body truncated to 500 chars per section (:72). Unlike
`bill_summaries`, **no model or prompt version is recorded** for
classifications — rows cannot be attributed to a prompt (§3).

### 2.9 The interest-area vocabulary — per-user, not sealed

`interest-areas.ts` has **no fixed vocabulary**: `user_interest_areas.keywords`
is a JSON array the user supplies (:39), matched with
`MATCH(bs.body) AGAINST(? IN BOOLEAN MODE)` over a space-joined keyword
string (:112, :123). The sealed part is the *matching contract* — MySQL
boolean full-text semantics, a 200-character excerpt (:131), one query per
area and a global `limit` applied twice (per-area at :124 and again at :140).
Re-implementing this outside MySQL changes results; that is a measurement, not
an assumption (§7 Q5).

### 2.10 Two rules that are broken and must be ported as intent, not as code

**Vote matching.** `roll-call-votes.ts:143` is
`/\b([HS])\.?\s*R\.?\s*(\d+)\b/i`. The `R` is **not optional**, so the
branch at :146 (`m[1] === "h" ? "hr" : "s"`) is unreachable. Measured:

| question text | match |
|---|---|
| `On Passage of H.R. 4366` | `H`, `4366` |
| `On Passage HR4366` | `H`, `4366` |
| `On Passage of S. 123` | **null** |
| `On the Motion S.Res. 45` | **null** |
| `S 123` | **null** |

Every Senate bill's votes are silently unmatched. Port the intent — the full
bill-number grammar already exists in `bill-identify.ts:101-102`.

**Release matching.** `press-releases.ts:146-149` builds a regex **per
(release, bill) pair** inside a nested loop bounded 500 × 1000, so up to
500,000 `new RegExp` compilations per run, and the third alternative
`${bill.number.toUpperCase()}` is an unescaped raw bill number — for a bill
numbered `1` it matches any `1` in any title. Port the intent: index bill
numbers once, scan each release once.

---

## 3. The database schema — every table, every column, every key

27 tables across `migrations/001`–`022`. `catalog-tables.ts` splits them 18
catalog / 8 user; `diff_jobs` is in neither list (`catalog-tables.ts:12-45`),
because it is operational. That split is the disposition:

- **18 `CATALOG_TABLES` → `spicy-regs hosting`**
- **8 `USER_TABLES` → `keep in a UI`**
- **1 `diff_jobs` → `delete`**

"Publisher identity" names which publisher key the column carries. A column
with no publisher identity is either derived (a spicy-docs computation) or
local (a surrogate key or timestamp).

### 3.1 `bills` — 24 columns (001, +011, +021, +022)

Unique key `uq_bill (congress, bill_type, number)` (`001:31`) — **the
publisher identity is the composite (congress, type, number)**, not `id`.
`id CHAR(36)` is a local UUID.

| Column | Type | Publisher identity / origin | Destination |
|---|---|---|---|
| `id` | CHAR(36) PK | local UUID | `spicy-regs hosting` — replace with the natural key `{congress}-{type}-{number}`, which spicy-regs `congress_bills.bill_id` already uses |
| `number` | VARCHAR(50) | **bill number** | hosting |
| `bill_type` | VARCHAR(10) | **bill type** | hosting |
| `congress` | INT | **congress** | hosting |
| `chamber` | VARCHAR(10) DEFAULT 'house' | derived from type (`congress-api.ts:208-210`) — **not** the publisher's `originChamber`, which is discarded (§6) | hosting; source it from `originChamber` instead |
| `title` | VARCHAR(1000) | publisher `title` | hosting |
| `short_title` | VARCHAR(1000) | publisher `titles[]`, "Display Title" then "Short Title…" (`sync-govinfo.ts:202-208`) | hosting |
| `sponsor` | VARCHAR(255) | publisher `sponsors[0].fullName` — **the bioguide id is discarded** (§6) | hosting; add `sponsor_bioguide_id` |
| `introduced` | VARCHAR(20) | publisher `introducedDate` | hosting |
| `status` | VARCHAR(500) (widened, 021) | publisher `latestAction.text` | hosting; rename `latest_action_text` to match `congress_bills` |
| `stage` | VARCHAR(50) | **derived** by `STAGE_RULES` (§2.2) | hosting, produced by spicy-docs shared logic |
| `summary` | TEXT | **never written** — `ingestCatalogBill` accepts it (`bills.ts:568`, inserted :584) but no caller passes it | **delete** — superseded by `bill_summaries` |
| `related_bill_id` | CHAR(36) | local; set by `PUT /api/bills/[id]/link` (`bills.ts:963`) | hosting as a bill-to-bill relation keyed on natural ids; the publisher's own `relatedBills` is discarded (§6) |
| `prev_year_bill_id` | CHAR(36) | same (`bills.ts:967`) | same |
| `money_bill_kind` | ENUM(8) (011) | **derived** by `classifyMoneyBill` (§2.3) | hosting |
| `fiscal_year` | VARCHAR(8) | derived, `detectFiscalYear` | hosting |
| `appropriations_subcommittee` | VARCHAR(64) | derived, `detectSubcommittee` | hosting |
| `classified_by` | VARCHAR(32) | `'auto'` or null (`sync-govinfo.ts:324`) | hosting |
| `classified_at` | BIGINT | local timestamp (`bills.ts:579`) | hosting |
| `public_law_number` | VARCHAR(32) (022) | **publisher `laws[].number`** where `type` contains "public" | hosting |
| `statutes_at_large_cite` | VARCHAR(64) (022) | **never written.** Declared `bills.ts:29`, surfaced `bills.ts:107`, but no INSERT or UPDATE sets it — permanently NULL | hosting, but **fill it**: GovInfo MODS carries the Statutes-at-Large citation for a PLAW package |
| `signed_date` | DATE (022) | derived two incompatible ways — see below | hosting |
| `created_at` | BIGINT | local | hosting |
| *(missing)* | | `classifyMoneyBill`'s `reasonCodes` are computed and thrown away | **add a column** — without it no classification can be audited |

**Two `signed_date` derivations that disagree** (intake-plan ledger item 2):

- `congress-api.ts:246-252` — uses `latestAction.actionDate`, gated on
  `latestAction.text` containing `"signed"` **or** `"became public law"`
  **or** `"public law"`, **and** a PL number being present.
- `sync-govinfo.ts:225-232` — scans **all** `actions[]` for the first whose
  text matches `/became.*public law/i` and takes that action's date.

The bulk path is correct (a signing is a specific action, not necessarily the
latest one); the API path returns null whenever any later action supersedes
the signing. Port the bulk rule.

### 3.2 `bill_versions` — 18 columns (001, +016, +017, +018, +019, +020)

Unique key `uq_version (bill_id, version_code, source)` after 020 (`020:37`)
— widened so an XML row and its `govinfo-pdf` twin can coexist (`020:9-11`).

| Column | Type | Publisher identity / origin | Destination |
|---|---|---|---|
| `id` | CHAR(36) PK | local UUID | hosting |
| `bill_id` | CHAR(36) FK | local | hosting via the natural bill key |
| `label` | VARCHAR(255) | publisher `textVersions[].type` verbatim | hosting |
| `version_code` | VARCHAR(50) | **slug of the publisher type** — the sealed vocabulary (§2.1) | hosting |
| `date` | VARCHAR(20) | publisher `textVersions[].date` | hosting |
| `text` | LONGTEXT NOT NULL | derived: `stripMarkup` of the text or XML rendition | hosting, **and** in `METADATA_STRIP_COLUMNS` (`catalog-tables.ts:55`) — re-hydratable |
| `xml` | LONGTEXT | **raw publisher bytes** | hosting; strip column; in spicy-docs this is the capture itself |
| `source` | VARCHAR(20) | `congress` / `govinfo` / `upload` / `govinfo-pdf` — a **provenance vocabulary**, part of the uniqueness key | hosting |
| `is_base` | TINYINT | **per-user baseline**, set by `setBaselineVersion` (`bills.ts:705,709`), yet stored on a catalog table | **split**: this is user state on a shared row. Move to `user_subscriptions.baseline_version_id`, which already exists (`001:58`) |
| `congress_url` | VARCHAR(500) | **the resolved publisher URL** | hosting; the port contract requires requested *and* resolved URL |
| `created_at` | BIGINT | local | hosting |
| `kind` | VARCHAR(32) (016) | derived by `classifyVersionKind` (§2.4) | hosting |
| `cleanup_applied` | JSON (017) | derived `PdfCleanupRecord` (§2.7) | hosting |
| `uploaded_by_user_id` | VARCHAR(64) (018) | local — the whole privacy model keys on `IS NULL` (`bills.ts:63-71`) | **keep in a UI**; a published table has no private rows |
| `aligned_to_congress_bill_id` | VARCHAR(64) (018) | local | keep in a UI |
| `equivalent_xml_version_id` | VARCHAR(64) (019) | local — links a `govinfo-pdf` row to its XML twin | hosting |
| *(missing)* | | `sha256`, `byte_size`, `observed_at`, requested-vs-resolved URL, `content_type` | **add** — the port contract already names them, and `classifyVersionKind` needs `body_bytes` |
| *(missing)* | | the GovInfo **package id** | **add** — `body_acquisition.py` keys on it, and `bill_status.py` already carries `BillTextFormat.package_id` |

### 3.3 Section and diff tables (002, +014)

| Table | Columns | Keys | Publisher identity | Destination |
|---|---|---|---|---|
| `bill_sections` | `id`, `version_id`, `match_path` VARCHAR(1000), `display_path` VARCHAR(1000), `heading` TEXT, `body` LONGTEXT, `seq`, `created_at` | `KEY (version_id)`; FULLTEXT `ft_sections_body`, `ft_sections_heading_body` (007) | none — **derived from publisher XML** by `bill-tree.ts` | hosting. `match_path`/`display_path` are joined with `" > "` (`section-parser.ts:55-56`) and split back (:74-75) — **a separator collision waiting to happen**; store them as lists |
| `section_diffs` | `id`, `from_version`, `to_version`, `created_at` | `UNIQUE (from_version, to_version)` | none — derived | hosting |
| `section_diff_items` | `id`, `diff_id`, `from_sec_id`, `to_sec_id`, `op` VARCHAR(10), `similarity` FLOAT, `moved` TINYINT, `seq`, `word_segments_json` MEDIUMTEXT (014) | FKs to `section_diffs` and `bill_sections` | none — derived | hosting. `op` ∈ {`added`,`removed`,`modified`,`unchanged`,`moved`} (`section-diff.ts:46`) is a sealed vocabulary |
| `financial_changes` | `id`, `diff_item_id`, `label` TEXT, `from_amount` BIGINT, `to_amount` BIGINT, `delta` BIGINT | FK to `section_diff_items` | none — derived | hosting. **`label` is always `""`**: `financial.ts` sets `label: ""` at every construction site (:143, :146, :160, :163, :165, :173) and `section-diff.ts:476` writes `pair.label \|\| ""`. Either populate it from the section heading or drop it |

### 3.4 Report, amendment, release, vote and member tables

| Table | Columns | Keys | Publisher identity | Destination |
|---|---|---|---|---|
| `committee_reports` (003) | `id`, `bill_id`, `chamber`, `label`, `date`, `text` LONGTEXT, `source` DEFAULT `'upload'`, `created_at` | `UNIQUE (bill_id, chamber)` — **only one report per chamber per bill**, which the publisher does not guarantee | report number (not stored) | hosting; **key on the GovInfo CRPT package id**, which `body_acquisition.py` already fetches. `text` is a strip column |
| `report_sections` (003) | `id`, `report_id`, `seq`, `agency_label` VARCHAR(500), `body` LONGTEXT, `created_at` | `KEY (report_id)`; FULLTEXT `ft_report_sections_body` | none — derived by `parseAgencyBlocks` (§2.6) | hosting; `body` is a strip column |
| `amendments` (004) | `id`, `bill_id`, `number`, `sponsor`, `party` CHAR(1), `date`, `status` DEFAULT `'Proposed'`, `description` TEXT, `congress_id` VARCHAR(100), `created_at` | `UNIQUE (bill_id, congress_id)` | `congress_id` = `{congress}-{TYPE}-{number}-{amendmentNumber}` (`congress-api.ts:371`) | hosting. **`status` is hardcoded `"Proposed"` at `ingest.ts:292`** and the real `latestAction.text` is put in `description` instead (:293) — ledger item 7. Carry the publisher's amendment type and latest action separately |
| `press_releases` (005) | `id`, `bill_id`, `source_url` VARCHAR(500), `feed_url`, `source_name`, `title` TEXT, `excerpt` TEXT, `published_at` BIGINT, `created_at` | `UNIQUE (source_url(255))` — a **255-byte prefix**, so two releases sharing a 255-char URL prefix collide | the item link | hosting. `excerpt` is `desc` stripped of tags and truncated to 500 (`press-releases.ts:111`); the full body is discarded (§6) |
| `roll_call_votes` (009) | `id`, `bill_id`, `congress`, `chamber`, `roll_number`, `session`, `question` TEXT, `result`, `yea`, `nay`, `present`, `not_voting`, `vote_date`, `source_url`, `created_at` | `UNIQUE (congress, chamber, session, roll_number)` — **the publisher identity for a vote** | (congress, chamber, session, roll number) | hosting |
| `member_votes` (009) | `id`, `roll_call_id`, `bioguide_id` VARCHAR(20), `member_name`, `party`, `state`, `position` | `UNIQUE (roll_call_id, bioguide_id)` — **bioguide is the member identity** | bioguide id | hosting — but **nothing writes this table** (§1a). Populate it from the House Clerk / Senate LIS files the legislative data map names, or drop it |
| `members` (010) | `bioguide_id` PK, `name`, `party`, `state`, `district`, `chamber`, `photo_url`, `start_date`, `end_date`, `updated_at` | PK is the **bioguide id** | bioguide | hosting. `photo_url` is *constructed* from `PHOTO_BASE` (`sync-members.ts:15,68`), never fetched — keep constructing it. **Missing**: LIS id and FEC candidate id, which `sources/legislators.py` now supplies |

### 3.5 AI provenance and activity

| Table | Columns | Keys | Destination |
|---|---|---|---|
| `bill_summaries` (012) | `id`, `bill_id`, `version_id`, `summary` TEXT, `model` VARCHAR(64), `prompt_version` VARCHAR(16), `content_hash` CHAR(64), `input_tokens`, `output_tokens`, `created_at` | `UNIQUE (version_id)` | hosting. **This is the provenance pattern to copy everywhere**: model + prompt version (`PROMPT_VERSION = "v1"`, `bill-summaries.ts:17`) + content hash + token counts |
| `diff_summaries` (006, +012) | `id`, `bill_id`, `from_version`, `to_version`, `summary_json` LONGTEXT, `created_at`, then `model`/`prompt_version`/`content_hash`/`input_tokens`/`output_tokens` all NULLable (012) | `UNIQUE (from_version, to_version)` | hosting; written only by `api/bills/[id]/summarize/route.ts:134` |
| `section_classifications` (006) | `id`, `section_id`, `label` VARCHAR(50), `confidence` FLOAT, `created_at` | `UNIQUE (section_id, label)` | hosting. **No model or prompt-version columns** — unlike the two above, a classification cannot be attributed to a prompt. Add them |
| `public_activity_events` (013) | `id`, `bill_id`, `event_type` VARCHAR(32), `event_data` JSON, `occurred_at` | `KEY (occurred_at)`, `KEY (bill_id, occurred_at)` | hosting. Four event types (`public-activity.ts:15-19`): `bill_added`, `version_added`, `stage_changed`, `summary_generated` — a sealed vocabulary |
| `hearing_transcripts` (006) | `id`, `bill_id`, `title`, `date`, `committee`, `text` LONGTEXT, `status` DEFAULT `'pending'`, `created_at` | FK `bill_id` nullable | **nothing writes this table** — it appears only in `catalog-tables.ts:24`, `catalog-export.ts:206` and `db.test.ts:42`. `body_acquisition.py` fetches CHRG packages today, so **keep the table and fill it**, or delete it. Do not port it empty |

### 3.6 `keep in a UI` — the 8 `USER_TABLES`

| Table | Columns | Keys |
|---|---|---|
| `users` (001, +008) | `id`, `email` UNIQUE, `name`, `password_hash`, `created_at`, `username` UNIQUE, `phone`, `organization`, `email_verified`, `last_login` | `UNIQUE (email)`, `uq_users_username` |
| `user_subscriptions` (001, +008) | `id`, `user_id`, `bill_id`, `baseline_version_id`, `created_at`, `email_notifications` | `UNIQUE (user_id, bill_id)` |
| `notes` (001) | `id`, `user_id`, `bill_id`, `title` TEXT, `body` TEXT, `created_at` | FK `bill_id` ON DELETE SET NULL |
| `bill_topics` (001) | `id`, `user_id`, `bill_id`, `name` VARCHAR(500), `matches`, `created_at` | `UNIQUE (user_id, bill_id, name(255))` |
| `user_interest_areas` (006) | `id`, `user_id`, `name`, `keywords` TEXT (JSON array), `created_at` | FK `user_id` CASCADE |
| `shareable_links` (006) | `id`, `token` CHAR(32) UNIQUE, `bill_id`, `from_version`, `to_version`, `view_type` DEFAULT `'diff'`, `created_at` | `uq_token` |
| `password_resets` (008) | `id`, `user_id`, `token_hash` CHAR(64) UNIQUE, `expires_at`, `used_at`, `created_at` | hash-only storage (`008:13`) |
| `notification_log` (008) | `id`, `user_id`, `bill_version_id`, `kind` VARCHAR(32), `sent_at` | `UNIQUE (user_id, bill_version_id, kind)` |

### 3.7 `delete`

`diff_jobs` (015) — `id`, `from_version`, `to_version`, `status`,
`is_active` (a **generated virtual column**, `015:10-11`, used to make
`UNIQUE (from_version, to_version, is_active)` mean "one active job per
pair"), `priority`, `account_id`, `source`, `attempts`, `error`, `worker_id`,
`enqueued_at`, `claimed_at`, `finished_at`, `diff_id`. A queue, not a
published table. The generated-column trick is worth remembering; the table
is not worth porting.

### 3.8 Indexes that encode an access pattern

Three FULLTEXT indexes (`007:16-18`) — `ft_sections_body`,
`ft_sections_heading_body`, `ft_report_sections_body` — carry the search and
interest-area features. MySQL boolean full-text is not a Parquet operation;
whatever replaces it changes results (§7 Q5). `idx_bills_money
(money_bill_kind, fiscal_year)` (`011:20`) and `idx_public_law_number`
(`022:30`) name the two catalog filters that matter.

---

## 4. DeltaTrack — measured, and the recommendation

### 4.1 What it is and how big

| Fact | Measurement |
|---|---|
| Size | 11 files, **2,846 lines**, **124 KB** (`du -sh`) |
| Files | `diff_bill.py` 804 · `bill_tree.py` 635 · `formatters/diff_html.py` 503 · `formatters/canonical.py` 417 · `formatters/adapters.py` 262 · `formatters/view_model.py` 72 · `formatters/text_serializer.py` 61 · `pyproject.toml` 43 · `formatters/_text.py` 37 · `README.md` 12 · `formatters/__init__.py` 0 |
| Upstream | `https://github.com/AgoraDMV/civic_tech_appropriations_bills` (`README.md:4`) |
| **Not a git submodule** | `.gitmodules` does not exist; `git submodule status` is empty; `git -C submodules/DeltaTrack log` returns **BillTrax's own history** and `remote -v` returns **`civictechdc/BillTrax`**. It is a directory committed into this repo, despite the path and the README's "Vendored into BillTrax as `submodules/DeltaTrack/`" (`README.md:6`) |
| Pinned version | **none** — no commit, tag or hash records which upstream revision this is |
| Declared deps | `httpx>=0.28`, `pypdfium2>=5.8.0`, `python-dotenv>=1.0` (`pyproject.toml:7-11`) — **none of which the diff engine uses**; they belong to `fetch_bills.py`, a file the vendored copy does not include (`pyproject.toml:39`) |
| Runtime deps actually used | stdlib only: `re`, `xml.etree.ElementTree`, `dataclasses`, `pathlib`, `difflib`, `collections` |
| Tests | **none vendored** — `pyproject.toml:33` sets `testpaths = ["tests"]` and there is no `tests/` directory |

The README says *"Do not edit files here directly — changes belong in the
upstream repo"* (`README.md:7`). With no pin and no upstream remote, that
instruction is unenforceable.

### 4.2 What the two modules do

**`bill_tree.py`** — XML → `BillTree(congress, bill_type, bill_number,
version, nodes)` where each `BillNode` (`:9-21`) carries `match_path`,
`display_path`, `tag`, `element_id`, `header_text`, `body_text`,
`section_number`, `division_label`. Entry point `normalize_bill(xml_path)`
(:590) handles three structural shapes (:593-596): divisions → titles →
appropriations; titles directly under the body; sections directly under the
body. `find_bill_body` (:52) accepts a bill `legis-body` or an amendment-doc
`amendment-block`.

**`diff_bill.py`** — two halves.

*Financial* (:14-161): `extract_amounts` (:24), `_extract_word_amounts`
(:40), `match_amounts` (:55, `SequenceMatcher(autojunk=False)` at :86),
`FinancialChange` (:115), `compute_financial_change` (:125),
`financial_change_to_dict` (:153).

*Structural* (:164-637): `_similarity_pair` (:164),
`_match_collision_group` (:211), `match_nodes` (:276), `diff_text` (:322),
`NodeDiff` (:347), `BillDiff` (:363), `_SIMILARITY_THRESHOLD = 0.4` (:375),
`_normalize_text` (:378), `_text_similarity` (:383),
`_text_similarity_at_least` (:388), `_move_candidates` (:407),
`_MOVE_THRESHOLD = 0.6` (:443), `reconcile_moves` (:446), `_count_changes`
(:517), `diff_bills` (:523), `bill_diff_to_dict` (:639), `filter_diff` (:684),
plus a CLI (`cmd_compare` :719, `build_parser` :758, `main` :792).

BillTrax's `SIMILARITY_THRESHOLD = 0.4` (`section-diff.ts:21`) and
`MOVE_THRESHOLD = 0.6` (:22) are **the same two constants**, independently
declared. One home.

### 4.3 The bridge

`diff_service.py` (148 lines) injects `submodules/DeltaTrack` onto
`sys.path` relative to `__file__` (:19), imports six symbols from two
modules (:21-28), of which three are invoked: `normalize_bill`,
`diff_bills`, `compute_financial_change` (+`financial_change_to_dict`).
Because `normalize_bill` takes a `Path` but the bridge receives strings, it
writes **two temp files per call** (:121-123) and unlinks them (:127).
Protocol: one JSON object `{from_xml, to_xml}` on stdin (:139-140), one JSON
array on stdout (:141); any failure is a stderr line plus `exit(1)` (:143-144)
behind a blanket `except Exception` (:142), so malformed input and an engine
crash are indistinguishable.

`python-diff.ts` (108 lines) spawns `python3` with a `process.cwd()`-relative
script path (:69-70), caps concurrency at `MAX_PYTHON_CONCURRENCY ?? 2` via a
hand-rolled FIFO semaphore (:41-53) that the comment at :38-40 warns **does
not stack across processes**, times out at `DIFF_TIMEOUT_MS ?? 120_000` with
an unconditional `SIGKILL` (:36, :78-81), and casts the parsed output to
`PythonDiffItem[]` with **no schema validation** (:96).

Two constants the bridge contributes and that must survive: `BODY_CAP =
30_000` (`diff_service.py:31`) skips word-segment precompute for oversized
bodies, and the three-stage bail-out `real_quick_ratio()` → `quick_ratio()`
→ `ratio()`, each `< 0.4` (:47-51), returning `None` to signal a stacked
rather than inline rendering. Note `:42-43` returns `[]`, not `None`, when
both sides are empty — a distinction the TS side reads.

### 4.4 `bill-tree.ts` vs `bill_tree.py`, function by function

Every claim below was **executed**, not inferred: Python 3 and
`@xmldom/xmldom@0.9.10` (the version `package.json:54` pins), in a scratch
directory, with BillTrax untouched.

| Python | TypeScript | Verdict |
|---|---|---|
| `normalize_header` :34 | `normalizeHeader` :56 | equivalent |
| `normalize_division_title` :39 | — | **missing in TS** (used by `diff_bill.py`) |
| `find_bill_body` :52 | `findBillBody` :90 | **divergent** — see D5 |
| `extract_text_content` :75 | `extractTextContent` :51 | **divergent** — D1, D2 |
| `get_header_text` :87 | `getHeaderText` :85 | equivalent |
| `_build_paths` :123 | `buildPaths` :107 | equivalent, including the `leaf !== major && leaf !== intermediate` guard (:153 / :134) |
| `_process_appro_element` :160 | `processApproElement` :182 | equivalent; TS mutates a ctx object where Python returns a tuple |
| `_process_section_element` :270 | `processSectionElement` :256 | **divergent** — D3 |
| `_walk_structural_children` :360 | `walkStructuralChildren` :312 | equivalent, including the save/restore of major/intermediate/prev (:435-437 / :350-352) and the third-level `f"{intermediate} - {header}"` concatenation (:418 / :340) |
| `walk_title` :442 | `walkTitle` :361 | equivalent |
| `_extract_appropriations_text` :470 | `extractApproText` :146 | equivalent — both `" ".join`, both skip `enum`/`header` |
| `_extract_section_text` :485 | `extractSectionText` :156 | equivalent — both `"".join`, both apply the `text`-and-no-`subsection` short circuit |
| `walk_body_sections` :509 | `walkBodySections` :368 | **divergent** — D3 |
| `_extract_metadata` :550, `_CONGRESS_WORDS` :97, `_LEGIS_NUM_RE` :120 | — | **missing in TS** — no congress, bill type, bill number or version is recovered from the XML at all |
| `normalize_bill` :590 | `parseBillXml` :401 | divergent signature (`Path`→`BillTree` vs `string`→`BillSection[]`); division/title selection differs in cost, not result — D6 |
| — | `normalizeBodyText` :455, `SECTION_HEADING_RE` :453 | **TS-only** — the plain-text fallback splitter, the entire non-XML path |

#### D1 — CDATA content is silently dropped by the TS fork

Python `extract_text_content` calls `element.itertext()`; ElementTree merges
CDATA into `.text` when parsing. TS `iterText` (:35-49) accumulates **only**
`node.nodeType === 3`, and xmldom emits a CDATA section as nodeType **4**.

Measured on `<r><text>alpha<![CDATA[BETA]]>gamma</text></r>`:

| | result |
|---|---|
| Python `"".join(itertext())` | `alphaBETAgamma` |
| TS `iterText` (`bill-tree.ts:38`) | `alphagamma` |
| TS `textContent` (what `bill-tree.ts:267` uses for `enum`) | `alphaBETAgamma` |
| xmldom child node types | `3,4,3` |

So the TS fork is **internally inconsistent**: body text drops CDATA, `enum`
text keeps it. This matters directly — spicy-docs measured on 2026-09-19 that
984 BILLSTATUS files across three bill types wrap summary text in a `<cdata>`
wrapper (`docs/sources/congress-bulk-status.md`, "Decision 4, measured"). The
Python behaviour (keep it) is the correct one; port that, and say so in the
commit.

#### D2 — `﻿` falls in different whitespace classes

Python `.split()` splits on `str.isspace()`; JavaScript `\s` follows
ECMAScript `WhiteSpace`, which **includes U+FEFF**. Measured:

| char | Python `isspace()` | dropped by `.split()` | JS `/\s/` |
|---|---|---|---|
| U+FEFF ZWNBSP | **False** | **no** | **true** |
| U+00A0 NBSP | True | yes | true |
| U+200B ZWSP | False | no | false |
| U+2007 FIGSP | True | yes | true |
| U+180E MVS | False | no | false |
| U+000B VT | True | yes | true |
| U+000C FF | True | yes | true |
| U+1680 OGHAM | True | yes | true |

One character disagrees: **U+FEFF**. `"a﻿b"` stays `a﻿b` in Python
and becomes `a b` in the TS fork (`bill-tree.ts:52`). A BOM inside a GPO text
node therefore splits a word in TS and not in Python — and the two stored
section bodies differ by a space, which is enough to make a diff report a
change. The Python port must state which side it takes; a Python
re-implementation gets the Python behaviour **by default**, which is the
behaviour DeltaTrack's own stored output assumes.

`pdf-normalize.ts:87` separately normalizes NBSP → space, which is the same
class of decision made explicitly. Do that for U+FEFF too rather than leaving
it to the language.

#### D3 — `enum` text extraction and trailing-dot stripping

| | Python | TS |
|---|---|---|
| source | `enum_el.text` (`:290`, `:527`, `:612`) — direct text only | `enumEl.textContent` (`:267`, `:378`, `:418`) — all descendants |
| trailing dots | `.rstrip('.')` — **all** trailing dots | `.replace(/\.$/, "")` — **one** |

Measured on `<enum>1.<sub>x</sub>tail</enum>`: Python `.text` → `"1."`, TS
`textContent` → `"1.xtail"`. And `"Sec. 1.."` → Python `"Sec. 1"`, TS
`"Sec. 1."`.

`section_number` feeds `match_path` (via `sec_label`), so a divergence here
**re-keys the section** and breaks cross-version pairing for exactly the
documents where `<enum>` has markup.

#### D4 — the `" "` vs `""` join asymmetry is faithfully preserved

`_extract_appropriations_text` joins with `" "` (`:482`);
`_extract_section_text` joins with `""` (`:505`). The TS fork reproduces
both (`:153`, `:167`). This asymmetry is **not a bug to fix** — it is what
every stored `bill_sections.body` was produced with. Preserve it, and the
collapse-then-marker order in `extract_text_content` (collapse whitespace
first, then remove the space before `(1)`/`(A)`/`(iv)` markers — Python
`:83-84`, TS `:52-53`, already the same order in both).

#### D5 — amendment-doc lookup depth

Python `root.find(".//engrossed-amendment-body/amendment/amendment-block")`
(`:64`) searches **any descendant path**. TS `findDescendant(root,
"engrossed-amendment-body", "amendment", "amendment-block")` (`:94`) walks
**strictly direct children** from the root. For any amendment-doc whose
chain is nested one level deeper, Python finds the body and TS throws
`"Could not find bill body in XML"` (`:100`) — which `section-parser.ts:33`
catches and silently degrades to `normalizeBodyText` on the plain-text
column. That is intake-plan open decision 7 (`resolution-body`), and it is
the same failure shape.

#### D6 — division/title selection costs more in TS

Python `body.findall("division")` (`:606`) and `div.findall("title")`
(`:619`) are direct-child scans, O(children). TS uses
`getElementsByTagName(...).filter(parentNode === body)` (`:409-411`,
`:424-426`, `:434-436`) — O(**all descendants**) three times per document,
to obtain the same set. On an omnibus with tens of thousands of elements
this is the difference between a scan of dozens and three scans of tens of
thousands. Same result, worse complexity; port the Python form.

### 4.5 `financial.ts` vs `diff_bill.py` — two live bugs the Python already fixed

**The dollar regex.** Python (`diff_bill.py:20`), with the reason in the
comment above it (`:16-19`, citing issue #34):

```python
_DOLLAR_RE = re.compile(r"\$\d{1,3}(?:,\d{3})+|\$\d+")
```

TS (`financial.ts:13`): `const DOLLAR_RE = /\$[\d,]+/g`.

Measured on `"...appropriated $17,40022% of the fund and $5,000,000 more..."`:

| | matches |
|---|---|
| Python | `$17,400`, `$5,000,000` |
| TS | **`$17,40022`**, `$5,000,000` |

The TS copy reads **$17,400,022** where the bill says $17,400 followed by a
percentage. That value went into `financial_changes.from_amount` /
`to_amount` as a BIGINT. The upstream fixed this; the fork did not inherit
the fix, because a fork does not inherit anything.

**The stateful `test()`.** `financial.ts:14` declares `AMENDMENT_RE` with the
`g` flag, and `:186` calls `.test()` on it **twice in one expression**:

```ts
const hasAnnotations = Boolean(
  (fromText && AMENDMENT_RE.test(fromText)) || (toText && AMENDMENT_RE.test(toText))
)
```

A global regex carries `lastIndex` across calls. Measured with a `fromText`
whose annotation sits at index 50 and a `toText` whose annotation sits at
index 0:

| call | result |
|---|---|
| `test(fromText)` | `true` (lastIndex advances) |
| `test(toText)` immediately after | **`false`** |
| `test(toText)` after `lastIndex = 0` | `true` |

`hasAmendmentAnnotations` is therefore wrong whenever the left side matched
first. The reset at `:189` runs **after** both calls. Python uses
`_AMENDMENT_RE.search()` (`:134`), which is stateless.

**Two further divergences, not bugs but not equivalences either.** Python
pairs amounts with `difflib.SequenceMatcher(autojunk=False)` (`:86`); TS
hand-rolls an **O(N·M) LCS DP table** (`financial.ts:81-84`) — an
`Array.from({length: m+1})` of `Array(n+1)` — so two 10,000-word sections
allocate 10⁸ cells. And the TS traceback **never emits `delete` or `insert`
opcodes** (only `equal` at `:114` and `replace` at `:110`/`:125`), so the
`op === "delete"` and `op === "insert"` branches at `:162-165` are dead, and
an adjacent deletion-plus-insertion that SequenceMatcher reports as two
separate ops is merged into one `replace` and **cross-paired positionally**.
Measured: `SequenceMatcher` on `"fund of $100 for roads"` vs
`"grant of $200 for roads"` returns
`[('replace',0,1,0,1),('equal',1,2,1,2),('replace',2,3,2,3),('equal',3,5,3,5)]`.

`amountsChanged` (`financial.ts:198-200`) compares
`JSON.stringify([...a].sort())` — `Array.prototype.sort()` with no comparator
is lexicographic, so `[9,10,100]` sorts to `[10,100,9]`. Both sides get the
same wrong order, so the multiset comparison is still *correct*; it is only
misleading. Python uses `Counter(...) != Counter(...)` (`:147`). Port the
`Counter`.

### 4.6 Recommendation: **port it into spicy-docs, and delete both copies**

Not a git pin. Not a vendored wheel. A port.

The three options, against what was measured:

- **Pin it as a dependency.** The thing in `submodules/DeltaTrack` is not a
  submodule and has no pin to preserve — `git submodule status` is empty and
  the directory's git history is BillTrax's own. There is no revision to pin
  *to* without first reconciling this copy against
  `AgoraDMV/civic_tech_appropriations_bills` and discovering what, if
  anything, has drifted. A pin also imports `httpx`, `pypdfium2` and
  `python-dotenv` (`pyproject.toml:7-11`) for an engine that uses none of
  them, into a repo whose convention is tier-1 acquisition with a minimal
  dependency surface.
- **Vendor it** (the `vendor/rulespec_artifacts` shape). Vendoring is right
  when the artifact is opaque and stable — a compiled ruleset, a generated
  schema. This is 1,439 lines of readable stdlib Python that spicy-docs must
  *modify* on day one: it must take bytes instead of a `Path` (§4.3's temp
  files exist only to work around that), it must route XML through
  `sources/xml.py::parse_xml(allow_external_doctype=True)` per the repo's own
  rule, and it must absorb the two guards the TS side learned in production
  (`GREEDY_PAIR_GROUP_CAP`, `SECTION_COUNT_THRESHOLD`). A vendored copy that
  is edited is a fork with extra ceremony — which is exactly the state
  `bill-tree.ts` is in today, and §4.4 is the bill for it.
- **Port it.** 1,439 lines of the two core modules (the 1,352 lines of
  `formatters/` are HTML and text rendering — UI, and none of it is imported
  by `diff_service.py`). It arrives with tests, which the vendored copy does
  not have (§4.1), and with the TS fork's four divergences resolved on
  purpose rather than by accident.

**Where it belongs: spicy-docs, on the parsing side for `bill_tree`, on the
shared-logic side for `diff_bill`.** Reading GPO bill XML into a node tree is
publisher-format parsing by the same argument that puts `bill_status.py`
there. Deciding that two nodes are "the same section, modified" at a 0.4
similarity threshold, or "moved" at 0.6, is a judgement — it is
interpretation, and under the corrected split interpretation lives in
spicy-docs too. So both halves land in spicy-docs and the seam between them
is a module boundary, not a repository boundary.

**What the port deletes.** `bill-tree.ts` (489), `financial.ts` (209),
`diff.ts` (40), `section-diff.ts`'s TS-fallback core (~190 of 586),
`python-diff.ts` (108), `diff_service.py` (148), `formatters/` (1,352, never
imported by the bridge), the `@xmldom/xmldom` dependency, and the `python3`
lines in `Dockerfile:6` and `:33`. Roughly **2,536 lines of duplicate logic**
and one language boundary.

**What the port must carry forward**, each already cited above: the four
divergences of §4.4 resolved toward Python (CDATA kept, U+FEFF decided
explicitly, `enum` direct-text with full trailing-dot strip, direct-child
scans); the two Python fixes of §4.5 (the comma-grouped dollar regex, the
stateless annotation search, plus `Counter` equality and `SequenceMatcher`
opcodes); `BODY_CAP = 30_000` and the three-stage similarity bail-out from
`diff_service.py:31,47-51`; and `GREEDY_PAIR_GROUP_CAP = 200`
(`section-diff.ts:26`) and `SECTION_COUNT_THRESHOLD = 10` (`:40`), which the
TS side learned from a real 120-second SIGKILL on the 118th NDAA
(`section-diff.ts:28-39`) and which the Python engine has never had.

**First move, before any code.** Write Phase-0 golden fixtures from the
*current* BillTrax behaviour for division, title, appropriations, subsection
and resolution shapes — because the port changes results on D1, D2, D3 and
D5, and without goldens there is no way to tell an intended change from a
regression. The four divergences are the test cases.

---

## 5. The API routes — 36 handlers, 2,612 lines

Measured by grepping every `fetch(` reachable from `src/app/api`: the only
five are `congress-api.ts:176`, `:314`, `:440`, `press-releases.ts:98` and
`govinfo-pdf-fetch.ts:175`. Everything else is a DB read, a DB write, an
LLM call, or a Python spawn.

### 5.1 Request-time acquisition — intake-plan decision 6

| Route | Method | Publisher endpoint (file:line of the `fetch`) | Persisted? | Replacement |
|---|---|---|---|---|
| `congress/versions/route.ts` (31) | GET | `/bill/{c}/{t}/{n}` + `/text` (`congress-api.ts:176`) | **No** — returned to the client at `:26`; the route never calls `ensureDb()` | a read of spicy-regs' version table. It is a live proxy with no cache and no persistence; nothing is lost |
| `bills/route.ts` (124) | POST | the same two, **plus one text download per selected version** (`congress-api.ts:314`) | `bills`, `bill_versions` | an acquisition run, then a table read. Synchronous fan-out over N versions inside one HTTP request is the reason this route is slow |
| `catalog/import/route.ts` (89) | POST | the same two, **plus XML and text per version** (`congress-api.ts:440`, `:314`) | `bills`, `bill_versions` (incl. raw `xml`), `user_subscriptions` | same. Note `:83` `const alreadyExisted = !selected.length` is always `false` — `:45` already returned 404 on the empty case. Dead field in the response |
| `catalog/upload/commit/route.ts` (250) | POST, attach mode only | `govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf` (`govinfo-pdf-fetch.ts:175`, URL built `:73`) | `bill_versions` with `source='govinfo-pdf'` | a capture lookup. The route already treats the fetch as non-fatal (`:205`, `:228`, `:237`), and `commit/route.test.ts:286-317` **pins that contract**: a 404 or a throw must still return 201 |
| `press-releases/route.ts` (18) | POST | two committee RSS feeds (`press-releases.ts:98`) | `press_releases` | the RSS source. **This route has no auth on either method** — an unauthenticated POST triggers outbound fetching and DB writes |

All five become table reads. Decision 6 resolves to *capture-backed*: none of
the five needs live data, and one of them (`congress/versions`) does not even
persist what it fetches.

### 5.2 What the rest serve, and what replaces them

| Group | Routes | Reads | Replacement |
|---|---|---|---|
| Bill and version reads | `bills/[id]/versions`, `.../[versionId]`, `.../base-text`, `.../section-bodies` | `bill_versions`, `bill_sections` | spicy-regs `query_sql` over the hosted tables |
| Diff reads | `bills/[id]/diff`, `.../financial`, `.../export` (CSV), `.../precompute`, `diff-jobs/[id]` | `section_diffs`, `section_diff_items`, `financial_changes` | hosted diff tables. `precompute` and `diff-jobs` are queue surface and **delete** with `diff_jobs` |
| Report reads | `reports/[billId]`, `.../agency` | `committee_reports`, `report_sections` | hosted tables |
| Vote reads | `roll-call-votes` | `roll_call_votes` | hosted table |
| Search | `search` (117) | FULLTEXT over `bill_sections` ⋈ `bill_versions` ⋈ `bills`, with an optional LLM query expansion at `:27` | hosted table + whatever replaces MySQL boolean full-text (§7 Q5) |
| AI writes | `bills/[id]/classify` POST, `.../summarize` GET, `topics/match` POST | write `section_classifications`, `diff_summaries` | spicy-docs shared logic producing hosted tables; these stop being request-time |
| Upload flow | `catalog/upload`, `.../inspect`, `.../commit` | `upload-cache`, `bill_versions`, `bill_sections` | **keep in a UI** — a private PDF upload is per-user by construction |
| Per-user CRUD | `notes`, `notes/[id]`, `topics`, `topics/[id]`, `interest-areas`, `interest-areas/[id]`, `subscriptions`, `subscriptions/[billId]`, `bills/[id]/baseline`, `bills/[id]/link`, `share` | the 8 `USER_TABLES` | keep in a UI |
| Auth | `auth/[...nextauth]` (3) | NextAuth | keep in a UI |

### 5.3 What a thin app actually needs

Three things, and nothing else:

1. **Read access to the 18 hosted tables** — spicy-regs already exposes this
   as MCP `query_sql` over Parquet.
2. **The 8 user tables** in its own small database, plus `bill_versions`'
   three per-user columns (`uploaded_by_user_id`,
   `aligned_to_congress_bill_id`, and `is_base`, §3.2), which today sit on a
   shared table and are the entire reason `bills.ts` carries a
   `visibilityClause` (`:63-71`) threaded through every catalog query.
3. **A way to ask spicy-docs to acquire one bill on demand** — the only
   genuinely interactive acquisition is "import this bill I just typed in"
   (`bills` POST and `catalog/import` POST). Everything else is a crawl.

### 5.4 Two things a reader should not carry forward

**Auth is absent from routes that write or spend.** `press-releases` POST
(outbound fetch + writes, no auth), `bills/[id]/precompute` POST
(unauthenticated trigger for a Python diff), `share` POST (mints a share
token for any `billId`), and every read route listed above. In a published
world most of these stop mattering because the data is public — but
`precompute` and `press-releases` are *compute and network* triggers, not
reads, and they must not be reproduced unauthenticated.

**The Python spawn is reachable in-request** from `bills/[id]/diff:71`,
`bills/[id]/financial:94` and `bills/[id]/precompute:44`, through
`section-diff.ts:559`, with a 120-second `SIGKILL` at the end of it
(`python-diff.ts:78-81`). That is the failure mode `SECTION_COUNT_THRESHOLD`
was added to dodge (`section-diff.ts:28-39`). Diffs belong in a pipeline.

---

## 6. Publisher fields BillTrax fetches and discards

spicy-docs keeps exact captures. Everything in this section is therefore
**free** once acquisition moves — the bytes are already being downloaded and
thrown away. Listing them is the point of the inventory: these are the
columns spicy-regs can host at zero acquisition cost.

Three levels of discard, and the third is the expensive one:

1. **Declared in the type, never read** — the code knows the field exists.
2. **Read, then narrowed** — the field is parsed and most of it dropped.
3. **Never declared** — present in every response and invisible to the code.

### 6.1 BILLSTATUS bulk XML (`sync-govinfo.ts`, `GviBill` :164-179)

**Declared, never read:**

| Field | Declared at | Why it matters |
|---|---|---|
| `originChamber` | `:170` (present in the test fixture, `govinfo.test.ts:35`) | `bills.chamber` is instead *inferred from the bill type* (`congress-api.ts:208-210`). The publisher states it; BillTrax guesses it |
| `committees.item[].systemCode` | `:139` | the committee identity. Only `name` is read, lowercased, and used for substring matching (`:199`, `:292-294`). `discover-money-bills.ts:29-34` uses the codes; the bulk path throws them away |
| `latestAction.actionDate` | `:174` | the date of the latest action — the single most useful recency signal, and the one `congress_bills.latest_action_date` already has |
| `actions.item[].type` | `:159` | action type; only `text` and `actionDate` are read, and only to find a signing action |

**Read, then narrowed:**

- `sponsors.item[]` → only `[0].fullName` (`:241`). Every co-sponsor, and the
  **bioguide id of the sponsor**, are dropped. `bills.sponsor` is a display
  string that `members.ts:75-93` then has to reverse-engineer back into a
  member by fuzzy last-name matching.
- `committees.item[]` → three booleans (`:292-294`). The committee list
  itself is never stored.
- `titles.item[]` → one string, "Display Title" or the first title whose type
  starts with "short title" (`:202-208`). Every other title — official,
  popular, short-title-as-passed-house/senate — is dropped.
- `actions.item[]` → the first action matching `/became.*public law/i`
  (`:228-230`). **The entire action history is discarded**, which is why
  `bills` has a single `status` string instead of an actions table.
- `textVersions.item[].formats` → one URL (`:255-268`). The other renditions,
  and their types, are dropped.

**Never declared** (every one of these is in `bill_status.py`'s `BillStatus`,
so spicy-docs already reads them):

`version` (the BILLSTATUS schema version — in the fixture at
`govinfo.test.ts:31` as `3.0.0`, and the field by which spicy-docs refuses a
superseded 1.0.0 file) · `updateDate` · `updateDateIncludingText` ·
`legislationUrl` · `policyArea` · `subjects` · `summaries` (with their
`versionCode`, `actionDate`, `actionDesc`, `updateDate`) ·
`actions[].actionCode` · `actions[].actionTime` ·
`actions[].sourceSystem.code` and `.name` · `sponsors[].bioguideId` ·
`textVersions[].formats[].packageId`.

The last one is worth naming twice: **the GovInfo package id is in the
payload BillTrax already downloads**, and it is the key
`govinfo/body_acquisition.py` uses.

### 6.2 Congress.gov v3 bill API (`congress-api.ts:220-234`)

**Declared, never read:** `actions.count` and `actions.url` (`:230-233`) —
declared in the response type and referenced nowhere.

**Read, then narrowed:** `laws[]` → `number` only, from the first entry whose
`type` contains "public" (`:243-244`); `type` itself is dropped, so a private
law is indistinguishable from an absent one in storage.

**Never declared:** the `/bill` detail response's `cosponsors`, `subjects`,
`summaries`, `relatedBills`, `committees`, `committeeReports`,
`cboCostEstimates`, `policyArea`, `constitutionalAuthorityStatementText`,
`notes`, `updateDate` and `updateDateIncludingText`. `bills.related_bill_id`
and `prev_year_bill_id` are set **by hand** through
`PUT /api/bills/[id]/link` (`bills.ts:963`, `:967`) while the publisher
supplies `relatedBills` for free.

### 6.3 Amendments (`congress-api.ts:335-374`)

**Fetched and dropped at the persist boundary:** `CongressAmendment.type` and
`.congress` are returned by `fetchAmendments` (`:366`, `:365`) and **not
passed** to `saveAmendments` (`ingest.ts:287-295`).

**Read, then narrowed:** `sponsors[0].party` is collapsed to
`D`/`R`/`I`/`null` (`:360-361`); `latestAction.text` is stored in
`amendments.description` while `amendments.status` is hardcoded
`"Proposed"` (`ingest.ts:292-293`).

**Never declared:** the amendment endpoint's `purpose`, `description`,
`proposedDate`, `submittedDate`, `chamber`, `updateDate`, `amendedBill`,
`actions` and `cosponsors`.

### 6.4 Committee bills (`congress-api.ts:387-434`)

Reads `congress`, `type`, `number` (`:416-418`) and nothing else. The
endpoint's `relationshipType`, `actionDate` and `updateDate` — the *reason*
a bill is on a committee's list — are dropped, which is why
`classifyMoneyBill` has to work from three booleans instead of a referral
record.

### 6.5 Roll-call votes (`sync-roll-call-votes.ts:59-96`)

This is the worst case in the tree: **three columns are derived by regex from
prose when the publisher supplies them as fields.**

| Column | How BillTrax fills it | file:line |
|---|---|---|
| `yea`, `nay` | `action.text?.match(/\((\d+)[–\-](\d+)\)/)` — parsed out of `"Passed by (224-201)"` | `:82-83` |
| `result` | `yea > nay ? "Passed" : yea < nay ? "Failed" : null` — **derived from the regex**, not read | `:91` |
| `present`, `not_voting` | never set; they take the schema default `0` (`009:16-17`) | — |
| `question` | `action.text` — the whole action sentence, not the vote question | `:90` |

**Declared, never read:** `recordedVotes[].fullActionName` (`:68`),
`actions[].actionCode` (`:61`).

**Never fetched at all:** the authoritative sources the file's own header
names — `https://clerk.house.gov/evs/{year}/roll{N}.xml` (`:6`) and the
Senate LIS roll-call XML (`:7`). These carry the real tallies **and the
member-level positions**, which is why `member_votes` (§3.4) has never been
written. The legislative data map already identifies Senate member-level
votes as one of exactly three things no API route supplies.

### 6.6 Press releases (`press-releases.ts:103-119`)

Reads `link`/`guid`, `title`, `description`/`summary`/`content`,
`pubDate`/`published`/`updated`. **Narrowed hard:** the body is stripped of
tags and truncated to **500 characters** (`:111`), the title to 500 (`:116`).
The full item content, `author`/`dc:creator`, `category`, `enclosure` and the
feed-level channel metadata are dropped.

Two bugs to fix rather than port: a single-item feed makes
`parsed?.rss?.channel?.item` an **object, not an array** under
`fast-xml-parser`, so `for (const raw of items)` at `:103` throws — the whole
feed is lost inside the silent `catch {}` at `:122`. And the lib and the
script disagree on the feed URLs (`press-releases.ts:6,10` uses
`/news/press-releases.rss`; `sync-press-releases.ts:20,24` uses `/rss/`) —
intake-plan decision 5.

### 6.7 The legislators file (`sync-members.ts:44-71`)

Reads `id.bioguide`, `name.official_full`/`first`/`last`, and **only the last
term** (`:54` `leg.terms[leg.terms.length - 1]`) for `type`, `party`,
`state`, `district`, `start`, `end`.

Discarded — and this is the sharpest example in the document:

- **`id.lis` and `id.fec`.** These are precisely the two identifiers
  `sources/legislators.py` was written to capture, and the decision record
  "Community legislators JSON is the identifier crosswalk"
  (`docs/decisions.md`) exists because *no publisher route carries them*.
  BillTrax downloads the file that contains them, on every sync, and drops
  them on the floor.
- `id.thomas`, `id.govtrack`, `id.opensecrets`, `id.icpsr`, `id.wikipedia`,
  `id.house_history`, `id.ballotpedia`.
- `bio.birthday`, `bio.gender`.
- **Every term but the last** — so a member's full service history, including
  a chamber switch, is invisible. `members` has one `start_date` and one
  `end_date`.
- `terms[].url`, `.address`, `.phone`, `.contact_form`, `.office`,
  `.caucus`, `.state_rank`, `.class`.

Also narrowing: party is collapsed to `D`/`R`/`I` (`:56-59`), so every
Independent, Libertarian and Democratic-Farmer-Labor member becomes the same
letter.

### 6.8 Summary — what hosting gains for free

| Source | Fields available at zero extra cost |
|---|---|
| BILLSTATUS | schema version, update dates, policy area, subjects, full summaries, **full action history with codes and source systems**, sponsor bioguide ids, committee system codes, origin chamber, **GovInfo package ids** |
| Congress.gov bill | cosponsors, related bills, committee reports, CBO cost estimates, constitutional authority statement, update dates |
| Amendments | purpose, description, proposed and submitted dates, chamber, amended bill, real status |
| Committee bills | relationship type and action date |
| Roll-call | real tallies including present and not-voting, the vote question, and — from the Clerk and LIS files — **member-level positions**, which fill `member_votes` |
| Press releases | full item body, author, category |
| Legislators | **LIS and FEC ids**, every other crosswalk id, full term history, birth date |

Nine of those are columns `bills`, `bill_versions`, `members`,
`roll_call_votes` and `member_votes` already have space for or badly want
(§3). None of them costs a new request.

---

## 7. Open questions, each with the measurement that settles it

The intake plan's seven open decisions stand; these are the ones this
inventory raises or narrows. Each names a measurement, not an opinion, and
each is phrased so that a clean result and an internally-consistent result
look different.

**Q1 — Does the DeltaTrack copy differ from its upstream?**
`submodules/DeltaTrack` is not a submodule and carries no pin (§4.1), so
"it's vendored, just re-vendor it" is not yet a statement anyone can make.
*Measurement:* clone `AgoraDMV/civic_tech_appropriations_bills` and diff
`bill_tree.py` and `diff_bill.py` against the committed copy, file by file.
Report the upstream commit that matches, or the hunks that do not. Until that
runs, the port is working from an unidentified revision. Blocks: the Phase-7
decision.

**Q2 — Which side of D1/D2/D3 does the port take, and what breaks?**
The four divergences in §4.4 change stored output. *Measurement:* run both
implementations over a fixed corpus — the bill XML already in
`bill_versions.xml` — and count sections whose `match_path` or `body`
differs, bucketed by cause (CDATA present, U+FEFF present, `<enum>` with
child elements, deep amendment-doc nesting). A cause with zero occurrences is
a free choice; a cause with many is a migration. Run it in **both**
directions, because "the new parser reproduces the old output" and "the old
parser reproduces the new output" are different claims and only the pair of
them is evidence. Blocks: Phase 3.

**Q3 — Do the PDF heuristics survive the extractor change?**
`pdf-normalize.ts` was derived against `pdf-parse` line layout; spicy-docs
extracts with pypdf/pymupdf. The hyphen-embedded line-number detector
(`:119`) is the fragile one, because it depends on the extractor emitting the
number glued to the word. *Measurement:* extract the same PDFs with both
libraries and compare `PdfCleanupRecord` field by field —
`lineNumbers` verdict, `hyphenRejoinCount`, `smallCapsMerges`. A
`hyphenRejoinCount` of zero under the new extractor means the rule has
silently stopped firing, which is not the same as the artifact being absent.
Note the stated gate for this, `validate-pdf-pdf-concordance.ts`, has **no
caller and is not in `package.json`** (§1b) — wire it before calling it a
gate. Blocks: Phase 5.

**Q4 — Is `acquire_text` too strict for the versions already stored?**
Settled on the status side (0 of 1,566 refuse; one file in 40,260 refused by
name), unmeasured on the text side. *Measurement:* run `acquire_text` against
every distinct `(congress, bill_type, number, version_code)` in
`bill_versions` where `source IN ('congress','govinfo')` and count refusals by
rule — exactly-once XML link, DC-title grammar, congress-in-words ≤ 199.
Report refusals as a fraction of rows the current system serves today, not as
a fraction of attempts. Blocks: Phase 4/8.

**Q5 — What replaces MySQL boolean full-text, and does it return the same
sections?** Three FULLTEXT indexes (`007:16-18`) carry search
(`api/search/route.ts:57`), interest areas (`interest-areas.ts:123`) and the
agency cross-reference (`api/reports/[billId]/agency/route.ts:26`). Parquet
has no equivalent. *Measurement:* take 50 real interest-area keyword sets and
50 search queries, run them against MySQL today and against the candidate
(DuckDB FTS, or a trigram index), and report overlap at k=20 **in both
directions** — a candidate that returns a superset and a candidate that
returns a subset are different failures. Do not measure recall against a
ground truth the candidate defines.

**Q6 — Does `member_votes` get filled or deleted?** It is migrated
(`009:28-39`), exported (`catalog-tables.ts:27`) and **never written**
(§1a). The data exists in the Clerk and LIS files the legislative data map
already identifies. *Measurement:* fetch one House Clerk roll and one Senate
LIS roll, parse them, and count how many of the bioguide ids join to
`members`. A high join rate makes the table worth filling; a low one says the
crosswalk has to land first (and `sources/legislators.py` is the crosswalk).

**Q7 — Which of the two `signed_date` rules is right on real data?**
§3.1 argues for the bulk rule on principle. *Measurement:* for every bill with
a `public_law_number`, compute both derivations and count disagreements,
then check the disagreeing bills against the GovInfo PLAW package's own
signing date. The API rule should lose on every bill with an action after the
signing; confirm that is the shape of the disagreement and not something
else.

**Q8 — Is `hearing_transcripts` worth keeping?** It has no writer, and
`govinfo/body_acquisition.py` already fetches CHRG packages. *Measurement:*
count CHRG packages that join to a bill in the 119th by any publisher key.
If the join rate is usable, keep and fill the table; if hearings do not join
to bills cleanly, delete it rather than porting an empty table.

**Q9 — Do the two money-bill referral derivations agree?**
`discover-money-bills.ts:29-34` uses six committee codes;
`sync-govinfo.ts:292-294` uses substring matching on committee names (§2.3).
*Measurement:* for one Congress, compute both sets of three booleans for
every bill and count disagreements, then check whether any disagreement
changes the `classifyMoneyBill` verdict. The code-based derivation is the
one with a publisher identity behind it; confirm the name-based one is not
catching something the codes miss (subcommittees, select committees) before
dropping it.

**Q10 — What is the real cost of the diff pipeline?** Two superlinear paths
are in the port's way: `financial.ts:81-84` allocates an O(N·M) DP table
(10⁸ cells for two 10,000-word sections) and `press-releases.ts:146-149`
compiles up to 500,000 regexes per run. Both disappear if ported as intent
(§2.10, §4.5). *Measurement:* before porting, profile one full diff of the
118th NDAA (the pair that produced the 120-second SIGKILL,
`section-diff.ts:28-39`) and record where the time goes. The existing guards
— `SECTION_COUNT_THRESHOLD`, `GREEDY_PAIR_GROUP_CAP`, `BODY_CAP` — were each
added in response to a specific failure; the profile says which of them the
Python engine still needs.

---

## Counts

Rows, not files — several modules split across dispositions, and the tables
in §1a/§1b are the authority. `congress-api.ts` splits four ways;
`bills.ts` and `interest-areas.ts` two ways each.

| Disposition | `src/lib` rows | `scripts` rows | Tables | Routes |
|---|---|---|---|---|
| `landed` | 2 (`congress-api` fetch + listing halves) | 2 (`sync-govinfo`, `sync-members`) | — | — |
| `spicy-docs / acquisition` | 2 | 6 | — | 5 (become table reads) |
| `spicy-docs / parsing` | 7 | — | — | — |
| `spicy-docs / shared logic` | 15 | 2 (kept as acceptance harnesses, then deleted) | — | 3 (AI writes, leave request time) |
| `spicy-regs hosting` | 0 code; 1 partition map (`catalog-tables.ts`) | — | **18** | 12 (become `query_sql`) |
| `delete` | 7 modules + `node_backend/` | 16 | **1** (`diff_jobs`) | 2 (queue surface) |
| `keep in a UI` | 11 | — | **8** | 14 |

No code moves to spicy-regs. That is the corrected split working as intended:
spicy-regs receives 18 table schemas, their data-dictionary entries and their
publishing pipeline, and spicy-docs receives every line of logic that
produces them.

**Four numbers worth carrying into the next conversation.**

1. **2,856 lines — 41% of `scripts/`** — belong to ten scripts with no caller
   anywhere: `validate-pdf-xml-concordance` (587), `gamma-6-validation` (463),
   `p3_prototypes` (482), `p2_catalog_survey` (374), `g1-identify-gaps` (283),
   `privacy-curl-test` (244), `gamma-7-smoke` (202),
   `check-govinfo-pdf-coverage` (110), `title-recon` (88),
   `identify-spotcheck` (23). Deleting them costs nothing and shrinks the
   port before it starts. One caveat: `govinfo-pdf-fetch.test.ts:57` asserts
   the slug map "matches check-govinfo-pdf-coverage.ts", so that assertion is
   rewritten first (§2.1).
2. **764 lines, one caller each, zero tests** — `bill-tree.ts` (489),
   `financial.ts` (209), `report-parser.ts` (66). These are the three
   highest-value publisher-text parsers in the repo, and §4 measured two live
   bugs in `financial.ts` and four divergences in `bill-tree.ts`. Every
   `bill_sections` and `financial_changes` row in the database was produced by
   untested code.
3. **~2,536 lines of duplicate diff logic** disappear when DeltaTrack is
   ported rather than pinned or vendored (§4.6), along with one language
   boundary, the `@xmldom/xmldom` dependency and the `python3` lines in the
   Dockerfile.
4. **§6 is the largest source of new value, and it is not code.** The
   publisher fields BillTrax already downloads and discards — sponsor bioguide
   ids, GovInfo package ids, the full action history, policy area and
   subjects, real vote tallies, and the LIS and FEC ids from a file it fetches
   on every member sync — cost nothing to keep once acquisition moves.

**One thing this inventory could not see.** Every caller count is a `grep`
over static imports plus the one dynamic import at `ingest.ts:449`. A call
reached only through a string built at runtime would not appear, and a script
invoked by hand from a shell history leaves no trace in the repo at all. The
ten "no caller" scripts are all documented as hand-run in their own
docstrings — all but `title-recon.ts`, which has **zero grep hits repo-wide,
not even a usage comment**. So "no caller" means "not wired", not "never
used", which is the right basis for deleting them but not the same claim.
