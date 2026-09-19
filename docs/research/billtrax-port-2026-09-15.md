# Intake plan: BillTrax acquisition & parsing → spicy-docs

Status: planned, not started. Written 2026-09-15 against BillTrax `a6b685f`
and spicy-docs `2cc2f4e` (v0.19.0). Every claim below was validated against
those trees (file:line cites); re-verify line numbers before acting on them.
Revised 2026-09-19 after the
[legislative data map](legislative-data-map-2026-09-18.md) and the families
record in `docs/decisions.md`: bulk status backfill runs ahead of the listing
routes for bills, Phase 4 is table-driven, the press-release source lands in
Phase 2, and the zip reader lives at `src/spicy_docs/reading/zip_archive.py`.

## Goal and boundary

BillTrax (sibling Next.js/TS app, `~/Work/BillTrax`) sheds all fetching and
publisher-format parsing; spicy-docs becomes the single acquisition front
door. The boundary is spicy-docs' own charter: it acquires source facts and
evidence; downstream applications interpret. BillTrax keeps interpretation:
stage inference, money-bill classification, AI summaries, diff
orchestration, DB, UI.

The port is two movements, not one:

1. **Acquisition** — new spicy-docs sources replace BillTrax fetch code.
2. **Single-sourcing** — most of BillTrax's "parsing" already has Python
   twins in that repo (a DeltaTrack submodule, a `diff_service.py` bridge).
   The parsing port is reunification and deletion, not translation.

## Inventory of value

### A. Acquisition ports (new spicy-docs code)

| BillTrax code | Ports as | spicy-docs home |
|---|---|---|
| `congress-api.ts` fetchBillMetadata/Versions/Text | already covered | `src/spicy_docs/sources/congress/bill_acquisition.py` (exists) |
| `congress-api.ts` fetchAmendments (:335-374) | new listing endpoint | `src/spicy_docs/sources/congress/listing.py` on `CONGRESS_GOV` family |
| `congress-api.ts` fetchCommitteeBills (:387-434) | new listing endpoint | same |
| `sync-roll-call-votes.ts` actions fetch (:36-59) | new listing endpoint | same |
| `sync-govinfo.ts` bulk BILLSTATUS ZIP (:32-86) | bulk ZIP reader | `src/spicy_docs/reading/zip_archive.py` + `parse_bill_status` |
| `press-releases.ts` / `sync-press-releases.ts` RSS | RSS source | clone `src/spicy_docs/sources/gao/rss.py` discipline |
| `govinfo-pdf-fetch.ts` fetch half (:64-74, :169-197) | PDF capture mode | extends bill acquisition (decision record first) |
| `reports/route.ts:29-48` uploaded-report PDF parse | extraction channel | extraction module + report parser |

Not ported (deliberate): legislators YAML (`sync-members.ts` — PyYAML is
forbidden here, community source, ~6 portable lines); photo URLs are
constructed, not fetched.

### B. Parsing single-sourcing (the publisher-text family)

| BillTrax code | Action | Note |
|---|---|---|
| `bill-tree.ts` | port + reconcile | it is a live TS fork of DeltaTrack `bill_tree.py`; two independent GPO-XML parsers exist in that repo today. Single-source them. |
| `financial.ts` | **delete** | TS re-implementation of Python `compute_financial_change` that already runs there via `diff_service.py:25-114` |
| `section-diff.ts` pure core + `diff.ts` | merge or retire | TS fallback diff brain; DeltaTrack duplicate |
| `bill-identify.ts` `extractSignals` | port | acceptance harness = BillTrax `audit-bill-identify.ts` (its 3 duplicated helpers die with it) |
| `pdf-normalize.ts` | port | GPO artifact cleanup, 9 call sites; NOT subsumed by our page-text extraction (different layer) — lands as post-extraction step over `PageResult` text |
| `report-parser.ts` `parseAgencyBlocks` | port | pure, dependency-free agency-header parser |
| `version-kind.ts` | port | pure publisher taxonomy (version-code → kind) |

### C. Stays in BillTrax (interpretation)

STAGE_RULES + `inferStageFromAction` (proven source-agnostic: fed raw
BILLSTATUS text at `sync-govinfo.ts:308` today) — but see fix ledger;
`classifyMoneyBill`, `generateBillSummary`/AI wiring, `matchVotesToBills`,
`matchReleasesToBills`, member matching, all DB layers, diff orchestration
(`python-diff.ts` becomes the spicy-docs seam), catalog export/import
(derived-data replication, not a publisher contract), auth/email/UI.

### D. BillTrax deletions (dead weight, do first)

- `node_backend/` entire service — deployed but consumed by nothing (zero
  `:3001` refs; its README:124 "optional"); drifted duplicate of 7 things.
- One-shot harnesses: `title-recon.ts`, `identify-spotcheck.ts`,
  `privacy-curl-test.ts`, `gamma-6-validation.ts`, `gamma-7-smoke.ts`,
  `check-govinfo-pdf-coverage.ts` (its URL builder 404s on long slugs —
  broken already), `g1-identify-gaps.ts` (second BILLSTATUS ZIP parser),
  `p2_catalog_survey.py`, `p3_prototypes.py`, `validate-pdf-xml-concordance.ts`
  (keep methodology in git history; it carries the drifted slug map).
- `mock-data.ts` — only `formatDate` is used; move to `utils.ts`.
- Keep despite looking dead: `discover-money-bills.ts` (dynamic import from
  `ingest.ts:449`), `diff_service.py` (spawned), `validate-pdf-normalization.ts`
  (pymupdf QA gate), repair/backfill scripts (wired in package.json).

## Fix-not-preserve ledger

Bake these fixes into the port; do not port the bugs:

1. `sync-govinfo.ts:248` slices status to 100 chars **before** stage
   inference; schema allows 500 (`migrations/021`). Unify on untruncated.
2. Two `signed_date` derivations that disagree (`congress-api.ts:245-252`
   latestAction-keyword vs `sync-govinfo.ts:225-232` `/became.*public law/i`).
   Pick one.
3. Slug-map drift: `validate-pdf-xml-concordance.ts:44-64` missing `pch,
   rds, rfh, hds`; its test only checks the 10 slugs it uses — a
   one-directional check hiding exactly the drift. Canonical map lives in
   `govinfo-pdf-fetch.ts:26-58`.
4. `sync-roll-call-votes.ts:39-43` unbounded 429 recursion.
5. Press-release lib crashes on single-item Atom; lib and script disagree on
   feed URLs, env semantics, timeouts.
6. Dead `/api/feed.xml` reference (`public-activity.ts:6`) — build or delete.
7. `amendments.status` hardcoded `"Proposed"` at `ingest.ts:292` — carry the
   real source field once amendments port.

## Port contract

The capture manifest is the only coupling. Per captured document it must
carry: raw body bytes, `sha256`, `byte_size` (needed by BillTrax
`classifyVersionKind`), requested + resolved URL (persisted as
`congress_url`), content type, `observed_at`, and parsed typed fields —
title, shortTitle, laws (PL number), committees, sponsors, actions
(untruncated), introducedDate, originChamber, textVersions with formats
(URL + type; format items can lack `<type>` — keep the URL-suffix
fallback from `sync-govinfo.ts:262`), version code/type strings (the
`version_code` slug vocabulary is keyed into BillTrax SQL in `bills.ts`
and `diff-worker.ts` — it must not change).

Re-hydration contract: BillTrax `catalog-tables.ts:54-59`
`METADATA_STRIP_COLUMNS` (`bill_versions.text/xml`, `committee_reports.text`,
`hearing_transcripts.text`, `report_sections.body`) is the set the capture
path must be able to re-fetch for metadata-mode catalog seeding.

`PdfCleanupRecord` shape is persisted in BillTrax (`cleanup_applied`) —
port as-is.

## Conventions every port must follow (this repo's rules)

- Tier-1 library acquisition only (like `bill_acquisition.py`); no CLI
  registry entries, no releases, unless a later decision adds them.
- Credentials header-only (`X-Api-Key`); never query params
  (`crs_summaries.py:54` is the legacy exception — do not copy it); scrub
  before truncating; 401/403 aborts the run.
- Empty success ≠ absence; preserve method; refusals carry captures;
  byte-bounded; paced; budget counts retries.
- New scope (PDF capture, bulk ZIP) needs a decision record in
  `docs/decisions.md` first. One `docs/sources/*.md` page per new source.
- Checks via `./scripts/check` (`uv run --frozen` only — never bare python).
- BillTrax-side phases use its docker gate:
  `docker compose run --rm web sh -c "npm run typecheck && npm run lint && npm test && npm run build"`.
- Pin ≥ 0.20.0 (needs `src/spicy_docs/reading/zip_archive.py`, moved from `sources/` in 0.20.0).

## Open decisions (ruling needed before the named phase)

| # | Question | Blocks |
|---|---|---|
| 1 | PDF capture success semantics: no structural identity proof exists for PDFs. Byte bounds + package URL + content-type + magic-prefix (FEC `download.py` precedent), or stronger? | Phase 5 |
| 2 | Settled 2026-09-19 by the families record in `docs/decisions.md`: each crawl states its bound and byte budget (one Congress and one bill type; 52 MB of status zips for the 119th). | Phase 6 |
| 3 | DeltaTrack relationship: spicy-docs vendors/imports it, absorbs reconciled implementations, or it stays BillTrax-side? | Phase 7 |
| 4 | `acquire_text` is stricter than BillTrax (exactly-once XML link, DC-title grammar, congress-in-words ≤ 199): relax, or accept that some currently-stored versions refuse on re-fetch? Settled 2026-09-19 on the status side: the 113 refusals in the 119th H.Res. zip were two publisher shapes the parser now reads (summary text inside a `<cdata>` wrapper, 984 files across three types; an action item with no text, 7 files), with every identity check unchanged; 0 of 1,566 refuse now, and a 40,260-file sweep over three Congresses leaves one file in the superseded 1.0.0 schema, refused by name (`docs/sources/congress-bulk-status.md`, "Decision 4, measured"). The text side (`acquire_text`'s exactly-once link, DC-title grammar, spelled-out Congress) is still unmeasured. | Phase 4/8 |
| 5 | Canonical press-release feed URLs (lib vs script divergence). | Phase 2 |
| 6 | The 5 request-time routes (`congress/versions`, `bills` POST, `catalog/import`, `upload/commit`, `press-releases`): migrate to capture-backed cache or keep live fetch? | Phase 8 |
| 7 | `resolution-body` in bill-tree: support it, or keep the current throw→text-fallback behavior deliberately? | Phase 3 |

## Phased sequence

Each phase ends green on the gate named above (per repo).

- **Phase 0 — Golden tests (BillTrax only).** Lock `bill-tree`,
  `extractSignals`, `pdf-normalize` behavior with fixtures covering
  division/title/appropriations/subsection/resolution shapes. Apply ledger
  items 1-2 here so the port doesn't inherit them.
- **Phase 1 — Deletions (section D).** Kills duplicate helper copies for
  free; update compose files for node_backend removal.
- **Phase 2 — In-repo dedup.** One `slugify`, one `stripMarkup`, one slug
  map + `buildGovinfoPdfUrl`, upload wrapper calls a shared
  `extractNormalizedPdfText`, press-release feed unification (decision 5);
  the press-release RSS source then lands here in spicy-docs as a clone of
  `gao/rss.py` discipline.
- **Phase 3 — bill-tree extractor here** (`src/spicy_docs/sources/congress/`,
  beside `bill_text.py`; **not** `extraction/` — PDF/image charter,
  `docs/decisions.md:89-93`). Bytes via `sources/xml.py::parse_xml`
  (`allow_external_doctype=True`). Preserve DOM quirks: CDATA exclusion,
  `\ufeff` whitespace-class difference, `" "` vs `""` join asymmetries,
  collapse-then-marker order. New fixtures; parity against Phase-0 goldens.
- **Phase 4 — Typed fields + table-driven listing routes** (after Phase 6
  for bills). `bill_status.py` gains committees/titles/laws for the API
  delta path; `listing.py` becomes a route table (URL builder + `records_key`
  + fixture + live pagination check; the map's Table A records which routes
  honor sorting) and gains amendments/committee-bills/actions as planned,
  then nominations, hearings, committee reports and House executive
  communications in that order. Routes the status zip already supplies serve
  the delta path only.
- **Phase 5 — PDF pipeline.** Decision 1, then PDF capture mode; port
  `normalizePdfText` as post-extraction step; revalidate heuristics against
  pymupdf line layout (BillTrax `validate-pdf-pdf-concordance.ts` is the
  gate; expect hyphen-embedded line-number detector to need re-derivation).
  Port `report-parser`. BillTrax keeps `cleanup_applied` persist,
  upload-cache, twin-row semantics.
- **Phase 6 — Bulk ZIP, ahead of Phase 4 for bills.** Decision 2 is settled
  by the families record; each run states its bound (one Congress, one bill
  type). Build on `reading/zip_archive.py`
  (`open_archive`/`read_member`/`inspect_archive_stream`), filename →
  `BillIdentity`, validate → `parse_bill_status`; then API deltas by update
  date. The map's bulk-status comparison is the parity run.
- **Phase 7 — Parsing family reunification.** Decision 3, then: delete
  BillTrax `financial.ts` (call the Python one), merge/retire
  `section-diff.ts` core + `diff.ts`, port `extractSignals` (+ audit
  harness moves with it) and `version-kind`. STAGE_RULES stay, fed
  untruncated action text; preserve the version-type stage path at
  `api/bills/route.ts:96`.
- **Phase 8 — Bridge & switchover.** `bill-capture` compose service in
  BillTrax (python:3.12-slim, wheel install per `docs/installation.md` +
  vendored rulespec wheel), content-addressed store + JSONL manifest on
  shared bind (`staging-data/captures` / `artifacts/captures`), CLI shape
  per `src/spicy_docs/cli/fec.py` (stdout JSON, exit 0/1/2, `--env-file`
  for keys). BillTrax call sites swap to the manifest;
  `src/lib/spicy-docs-ingest.ts` is the single mapper. Request-time routes
  per decision 6. e2e + one full ingest cycle on captures only.
- **Phase 9 — Final BillTrax deletion pass.** `congress-api.ts` shrinks to
  pure interpretation + relocated types (`BillMetadata` must move out of
  the network module); delete `sync-govinfo` parse layer, govinfo-pdf fetch
  half, `pdf-parse` dependency, remaining validator downloaders.

## Runtime shape (validated against BillTrax's current compose topology)

The BillTrax web image has stdlib-only python3 (no uv/pip — deliberate,
DeltaTrack only), so no in-container `uv run`. Orchestration is
`docker compose run --rm bill-capture … && docker compose run --rm web npm
run …` chaining, matching its existing README command grammar. GovInfo
BILLSTATUS acquisition is credential-free; Congress-API keys travel as an
explicit `--env-file`, never container env. Precedent for the whole shape
in BillTrax: `diff-worker` service + `python-diff.ts` bridge + shared
`uploads` volume.

## Verification commands

- spicy-docs: `./scripts/check` (always; `uv run --frozen pytest` for focus).
- BillTrax: the docker gate above; `npm run validate:pdf` for the PDF gate.
- Parity harnesses: Phase-0 goldens, `validate-pdf-pdf-concordance.ts`
  (until pdf-parse dies), `audit-bill-identify.ts` CSV (until Phase 7).
