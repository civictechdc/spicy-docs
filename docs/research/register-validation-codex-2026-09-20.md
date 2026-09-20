# The gap register, validated by an outside read

Status: review, 2026-09-20. Produced by OpenAI Codex CLI 0.155.1 in a read-only
sandbox against spicy-docs `main` at 25e1abd and spicy-regs
`billtrax-hosting-prep` at 2d13f81, at the owner's request, and retained
verbatim below the rule as a decision input for
[the register](closing-the-gaps-2026-09-19.md). The reviewer could not execute
`uv run` inside its sandbox, so counts it reports were tallied statically and
tests were inspected, not run; its 37-contract / 766-column tally agrees with
the registry import. The register's header and the rows it names as stale,
overstated or misfiled were corrected in the same commit that retained this
file, and its nine candidate gaps were filed as §2.6 of the register as
candidates, unmeasured.

---

**The register is not a reliable completion ledger.** Most merge and implementation claims are supported, but it conflates acquisition, table definitions, hosting, measurements, and closure.

Checked spicy-docs `main` at `25e1abd` and spicy-regs `billtrax-hosting-prep` at `2d13f81`. A6 changed during review; the findings below include its merged reopening. I changed no files. `uv` failed before Python started because the sandbox denied cache/temporary-file creation; tests were inspected, not executed. A static declaration count independently gives **37 contracts / 766 columns**.

Paths below use `S` = `src/spicy_docs`, `Q` = `docs/research`, `R` = sibling spicy-regs, and `P` = `/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts`.

**1. Per-row verdicts**

All named merge hashes were found and checked for ancestry on the specified branch. Review-round claims are corroborated by commit narratives, not independently verified review transcripts.

| §2.0 row | Claims checked | Verdict | Evidence and finding |
|---|---|---|---|
| A1, A2, A3 | “Landed”; 12/12 reports; 10 hearings/31 mentions; “0-of-52”; local `_mods_bills` | **Supported; stale; overstated denominator** | `1f18898` landed. `P/report-bill-linkage-2026-09-19/README.md:57,77` confirms figures, but **52 fetches cover 50 distinct hearings**. Local copy was removed: `R/src/spicy_regs/transforms/build_committee_reports.py:395` uses `primary_bill`. |
| A4 | Senate menu reader and three named symbols “landed” | **Supported acquisition; incomplete hosting** | `S/sources/congress/votes.py:913,957,1061`; fixture tests at `tests/test_congress_votes.py:492`. Host still explicitly selects **House only**, `R/src/spicy_regs/transforms/build_roll_call_votes.py:312`; per-area A4’s hosting step remains open. |
| A5, A7, A10 | Routes, five contracts, `event_id`, RIN rule; 27/516; sample counts; rollups; “54 hosted” | **Supported historically; stale total** | `1f515bb`, `a431fef`; declarations reproduce 27/516. Named receipt JSONs confirm 18 details, 12 RINs and two meeting requests. `P/rollups-index-2026-09-19/fr-rin-measurement.txt:14` confirms 96,060/1,499. Current catalog contains **59** tables. |
| A6 | 92,450 rows; 28.9%; 50% threshold; reopened backfill measurement | **Supported measurement; no adopted threshold** | `Q/legislative-data-map-2026-09-18.md:390` and JSON histogram agree: 26,725/92,450. Line 391 explicitly says **no decision record sets 50%**. `25e1abd` corrects reopening to 87/216 RINs, matching retained `parse-rule-measurement-v2.json`. Backfill remains proposed. |
| A8, A9 | Five contracts; 32/617; source readers; laws join; bounded walks; 59 tables | **Supported** | `f86715f`, `fdc3d8e`; receipts confirm 108/104 laws and 555/541 members. Decision records: `docs/decisions.md:653,673`. Host bounds are eight over-declared entries and three consecutive Table III refusals. Installed-contract unhosted set is empty, `R/tests/test_contract_tables.py:38`. |
| A11 | Backfill landed; 767 entries; 82 requests; refusal retry | **Supported, bounded proof** | `f9a1a64`; `P/a11-pre-108th-backfill-2026-09-19/README.md:33` confirms **767 entries, 766 bills**. Only 50 details were captured; production-shaped replay regrouped the combined listing by bill type and simulated missing details as failures, lines 60–78. |
| A12, A13, E4, E5 | Map repaired; floors extended; workflow/index test; FR stale pin | **Supported implementation; stale map; proof incomplete** | `b3d00f5`; workflow at `.github/workflows/live.yml:9`; index test at `tests/test_docs_index.py:34`; extended floors documented at `Q/legislative-data-map-2026-09-18.md:484`. Map still mislabels landed sources. No first weekly-run artifact was verified. |
| B1 | 170/170 sections; 83% quoted-block recall; 141 requests; CFR 40/84 and scores | **Supported numbers; overstated readiness** | `8c0e023`, `1580899`; both sidecars match. But `Q/reconstruction-benchmark-2026-09-19.md:55` admits the blind split informed development; its precision is **99.89%**, below 99.9%. `bill_dtd` remains absent. |
| B2, B7, CPRT, accessor | Grammar/accessor landed; decision; five USLM packages parsed | **Supported; replay limited** | `077091a`; `docs/decisions.md:293`; `S/sources/govinfo/bodies.py:138,200,575`. Receipt confirms five package results, but four bodies and exploratory request logs were not retained: `P/uslm-bill-rendition-2026-09-19/README.md:47,75`. Full independent replay is unavailable. |
| B3 | Current CRS HTML structurally preferred | **Supported** | `4e9ab7c`; `S/sources/congress/crs_files.py:634` gates historical versions to PDF and retains HTML refusal evidence. Preference does **not** establish reliable HTML availability; repeated requests changed status, lines 33–42. |
| B4, B8 | PDF measurements; grammar/contracts; 37/766; action results; “hosted”; 118 requests; decision blocker | **Mixed: supported, overstated, stale** | All six cited implementation/reconciliation merges exist. Static counts confirm 34-column budget, 35-column expenditures and 27-column actions. Sidecars support 504/518 budget laws, 83/83 office pages, 4,456 actions/978 bills/1,249 pages and stated precision/recall. **“Hosted” is false on the named branch:** it vendors 0.22.0 without these five contracts. **118 counts logged rows**, not all provider calls: `P/pdf-family-rollup-yield-2026-09-20/README.md:57` says exact total is unknown. Grammar blocker is superseded by `docs/decisions.md:1064`. B8 remains deferred. |
| B5 | `TableObservation`, opt-in extraction landed | **Supported; limited yield** | `1477d84`; `S/extraction/model.py:98`, `S/extraction/api.py:131`. Actual recovery was **199/802 and 0/273**, not general table recovery: `P/gpo-pdf-tables-2026-09-19/README.md:44`. |
| B6 | 42-document validation; two layout fixes | **Supported measurement; narrower than planned proof** | `b16c77c`; `P/gpo-normalizer-corpus-2026-09-19/receipt.md:12,62`. Corpus contains **36 bill PDFs**, not the per-area target of forty. Original PDFs were not retained, line 53. |
| C1, C4 | Prompt/schema fixes; live rows, tokens/cost; refusal containment; C4 not started | **Supported; C4 open** | C1 receipts confirm three initial calls, subsequent 263/80-token refusal, then two successful three-row classifications totaling 534/200 tokens and $0.00066. `docs/decisions.md:693,783` records changes. These are module measurements; production run remains pending. |
| C2, C3 | Search defaults encoded; signed-date measurement; corrected claims | **Supported with limits** | `S/interpretation/interest_areas.py:24` documents defaults but explicitly lacks live ordering comparison, line 58. C3 receipt records **16,213 H.R./S. files, 269 laws, zero fallback**; `S/interpretation/bill_stage.py:342`. This is not all bill types. |
| C5 | “Closed as no-change: HTML removed the measured defect” | **Misfiled** | Closure addresses hyphen wrapping, while the row names all-caps title-page segmentation. That defect remains documented at `docs/sources/agency-report-blocks.md:149`. `docs/decisions.md:528` describes parser limitations, not a measured C5 closure. |
| D1, D4 | Thirteen rollups; 36 tables; findings; synthetic hearing fixture | **Supported D1; D4 still open** | `bc82c51`; `P/d1-measured-run-2026-09-19/summary.md:3,24` supports run/table figures. Some outputs have zero rows. `docs/tables.md:427` confirms D4 still substitutes CRPT bytes under CHRG identity. “Landed” cannot close D4. |
| D2 | SR01 reader replacement landed | **Supported** | `R/src/spicy_regs/sources/congress_bills.py:136,267` constructs and walks `CongressListingReader`. Historical test-pass claims were not rerun. |
| D3 | Search pin 24 tables; host pin “47, 49 once A11 merges”; waiting user | **Supported search pin; stale host state** | Search vendor digest is `01c77a4a…`, with 24 classes. Host catalog is **59**, digest `0952553b…`; A11 already merged. User-dependent upstream integration remains a documented deferral, not verified external activity. |
| D5 | 5,348 requests; rolling peak 3,680; archive reads accepted | **Supported measurement** | Independently recomputed both totals from `P/d1-measured-run-2026-09-19/requests/hour-ledger.json`. It establishes that night’s load; the acknowledged steady-state second run remains absent. |
| E1, E2 | Issues await user; git pin and wheel distribution | **Supported local state; external state unverified** | `Q/deltatrack-upstream-issues-2026-09-19.md:6` says nothing filed; `pyproject.toml:67` pins `c636448…`. No current upstream issue/release lookup was performed. |
| E3 | Ungated type checking; 1,139 diagnostics; regs gate | **Supported gate state; unverifiable counts** | `scripts/check:6` omits `ty`; regs CI/pre-commit include it. No pinned diagnostic receipt located; 1,139/553/517 and extra-dependent counts were not rerun. |
| Releases | Tags, commits, wheel hashes, adoptions | **Supported releases/adoption through 0.22.0; later progress unverified** | All four tags exist; local wheel SHA-256 values match quoted prefixes. `f198b6e`, `2d13f81` confirm adoptions. `R/vendor/README.md:8` and actual wheel confirm 0.22.0. No 0.23.0 adoption is present on the named branch. |

**2. Candidate new gaps, ranked by hosted-table consumer value**

| Rank / gap | Evidence | Consumer consequence | Suggested fix | Proof measurement | Home |
|---|---|---|---|---|---|
| **1. Incomplete regulatory joins** | `R/src/spicy_regs/transforms/build_federal_register.py:22`: 696,679 legacy rows lack RIN arrays; scalar selects only the first RIN. | Missing historical joins; additional RINs disappear from scalar joins. | Backfill source arrays and expose a document–RIN relation. | Count recovered legacy arrays and compare joins against every array element, including the 1,499 multi-RIN documents. | spicy-regs |
| **2. Mirrulations recovery violates repository rules** | `S/sources/mirrulations.py:384` wraps all download failures; default `fail_fast=False` at 565; parse failures remain processed at 714. Test explicitly requires this at `tests/test_mirrulations_reader.py:858`. | Access refusals can become skipped rows; repaired malformed records remain excluded on resume. Strict release acquisition uses a safer path. | Propagate authentication refusals; keep unsuccessful keys resumable with explicit outcomes. | Inject 401/403 and malformed-then-repaired JSON; prove abort and subsequent recovery. | spicy-docs |
| **3. Amendment bodies missing** | `tools/analysis/legislative_data_map.py:191,321`; amendment contract is metadata-only. | Consumers can identify amendments but cannot inspect or compare operative text. | Measure stated text routes, retain renditions and link bodies to amendment IDs. | Stratified amendments through acquisition, identity validation and hosted joins; report refusals. | spicy-docs → spicy-regs |
| **4. Model usefulness unqualified** | `docs/interpretation.md:138,139`: live published-printing diff and classification quality remain unmeasured. | Valid JSON can still produce incorrect classifications or misleading summaries. | Add independently judged real-bill and changed-version samples. | Per-label accuracy/abstention and source-supported summary claims on held-out documents. | spicy-docs; spicy-regs run |
| **5. Historical law bodies absent** | `tools/analysis/legislative_data_map.py:266`; `Q/legislative-data-map-2026-09-18.md:110–112` distinguishes PLAW bulk from unimplemented STATUTE XML. | Older law metadata cannot supply the corresponding structured text. | Add bounded STATUTE acquisition and section-to-law identity mapping. | Representative early volumes reconciled to publisher law identities and retained text. | spicy-docs → spicy-regs |
| **6. Senate expenditure detail incomplete** | `docs/tables.md:369,496`: payee/payment fields unparsed; compensation/mail sections unqualified. | Ruled-cell storage cannot answer payment-level questions or establish whole-report coverage. | Qualify later sections and measure payment-block interpretation. | Independently labeled payments, attribution accuracy and reconciliation across each grid/section. | spicy-docs → spicy-regs |
| **7. House spending absent** | `Q/legislative-data-map-2026-09-18.md:148`: House disbursement CSV remains candidate; USAspending excludes Congress. | Senate expenditure work leaves the other chamber uncovered. | Acquire publisher CSV with period and file provenance; define hosted rows. | Full-period counts and financial totals reconciled to the published statement. | spicy-docs → spicy-regs |
| **8. CRS run provenance incomplete** | `S/sources/congress/crs_summaries.py:127,136`: rows retain `sourceParquet` path but no run identifier, capture time or input digest. | Appended results cannot be attributed reliably when input files change in place. | Add immutable run/input pins and per-attempt observation metadata. | Resume across two input versions and reconstruct every row’s origin. | spicy-docs |
| **9. Older vote corrections undetectable** | `R/src/spicy_regs/transforms/build_roll_call_votes.py:64,316`: no publisher update field; only newest overlap rechecked. | Corrections outside the overlap persist indefinitely. | Retain update signals where supplied and schedule bounded historical refresh. | Change an already-held older vote; prove detection and corrected member/tally rows. | spicy-regs; shared schema if needed |

Credential scrubbing precedes truncation in CRS, and both scrub passes have tests. Shared HTTP acquisition aborts keyed 401/403, validates response shape, and uses GET; I found no demonstrated HEAD substitution or scrub-after-truncation defect.

**3. Structural problems**

- **False completion summary:** line 3 excludes real states explicitly present below: reopened A6, unstarted C4, incomplete D4, ungated E3 and unfinished bill reconstruction.
- **Stale snapshot:** header says `9009fd1`, 109 commits and 5,950 tests. Checked main is `25e1abd`, **200 commits** beyond v0.21.1. Current test count is unverified. §1’s 27/516 and six-rollup figures are obsolete.
- **Contradictory area tables:** A5/A7/A10 still say host work is open; C1 says never run; D1 says no production run; E4 says no schedule. Their §2.0 rows say otherwise.
- **B4 retains mutually exclusive states:** “blocked on a decision record” survives alongside the decision and grammar landing. “Hosted” contradicts Releases’ pending adoption.
- **Map refresh is incomplete:** CPRT, chamber rosters and OLRC classification remain candidates; activity reports, Senate expenditures and budget material retain rejected descriptions despite implementation. `ROWS:278` also calls CRECB bodies “have,” but the body grammar lacks CRECB.
- **Evidence layers disagree without a clear rule:** B4 says sidecars regenerated; `docs/decisions.md:1060` says deliberately not regenerated. Recheck JSON retains one flagged law and 38 dockets; prose reports zero and 37 after exclusions.
- **Missing research navigation:** the register lacks direct links to `reconstruction-benchmark-2026-09-19.md` and `senate-expenditure-tables-2026-09-20.md`. E5’s index test excludes research pages entirely.
- **Grouped rows hide unfinished work:** C1/C4, D1/D4 and B4/B8 need separate status and proof fields.

**4. Five-line summary**

Most named merges, release hashes and major receipt figures are solid.  
The registry contains 37 contracts and 766 columns by static tally; the host catalogs 59 tables.  
Acquisition and contract completion repeatedly masquerade as hosted or closed gaps.  
Recovery behavior, regulatory joins, missing bodies and semantic quality need explicit register entries.  
Tests, current type-error counts, upstream activity and deployed hosting were not independently verified.