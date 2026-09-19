# spicy-docs branch modules vs. upstream DeltaTrack: overlap measurement

Measured 2026-09-19. Upstream: `civictechdc/DeltaTrack` @ `c636448` (package
`deltatrack` 0.1.0, engine dependency `pypdfium2` only), cloned read-only into a scratch directory. Branches read via `git show <branch>:<path>`
against the spicy-docs checkout. No repo was modified;
upstream's own parser was executed in place with `uv run` from its own clone,
against copies of the branch's fixtures staged beside the clone.

---

## Pair 1 — `bill_versions.py` + `version_kind.py` vs upstream version-code handling

Upstream has **no single module that plays `version_stems.py`'s role.**
`src/deltatrack/version_stems.py` is not a version-code vocabulary at all — it
resolves **local on-disk filename ordinals** (`{bills_dir}/{slug}/{n}_{label}.xml`)
back to a readable label (`version_number_from_stem`, `label_from_stem`,
`local_versions`, `resolve_version_file`, lines 15–75). It never sees a GovInfo
BILLS package id or a Congress.gov `type` string; its "vocabulary" is whatever
labels happen to be on disk. This is a different problem: BillTrax/spicy-docs
needs a **sealed slug → GovInfo suffix** map for a live `bill_versions.version_code`
SQL column; upstream needs an ordinal → filename resolver for its own test
corpus layout. `tests/test_version_stems.py` confirms the scope (parses `1_`,
`10_`, rejects `"³"` via `isdecimal`, nothing about publisher codes).

The real counterpart, found by grepping `BILLS-`/`version`/`ih`/`enr` outside
`src/`, is **`tools/fetch_govinfo.py:82-152`** (`VERSION_CODES: dict[str, tuple[str, int]]`,
53 entries) plus `resolve_code()` (lines 178-191, prefix-fallback for numbered
reprints) and `NAME_TO_CODE` (derived reverse map, line 155). This *is* a
code → (display name, tier) vocabulary, sourced from govinfo.gov's own
authoritative 53-code list (govinfo.gov/help/bills) rather than reverse-engineered
from BillTrax, and it is keyed on the short code exactly like
`bill_versions.govinfo_suffix`'s target domain — not on a long slug.

**Concordance against the 24 codes measured in
`docs/research/billtrax-raw-data-2026-09-19.md` §1** (checked by calling
upstream's own `resolve_code()` via `uv run python` from the upstream clone):

| code | upstream has it? | upstream name | measured API type | agree? |
|---|---|---|---|---|
| ih, is, eh, rh, rfs, ats, es, pcs, enr, rds, cps, eas, eah, rfh, rcs, rhuc, cdh, lth, ris | yes (literal key) | matches | matches | yes (19/19) |
| rs | yes | "Reported in Senate" | "Reported to Senate" | cosmetic diff only — upstream's own comment (line ~157) already documents this exact API-vs-canonical spelling split and patches `NAME_TO_CODE` for it |
| as | yes | "Amendment Ordered to be Printed Senate" | "Amendment Ordered to be Printed (Senate)" | cosmetic (parens) only |
| eas2, eh1s, rfs2 | not a literal key, but resolved via `resolve_code`'s longest-known-prefix fallback (eas2→eas, eh1s→eh, rfs2→rfs) | correct tier + name | — | yes, all 3 resolve non-zero |

**All 24 measured codes resolve correctly** (verified: `all(resolve_code(c)[1] != 0 for c in the 24)` → `True`). Disagreements run only one way and are cosmetic:
upstream never disagrees on which document a code names. In the other
direction, upstream's table carries **32 codes beyond the measured 24** (53
total, including `pch`/`hds`/`hdh` — the very passthrough codes the raw-data
doc flagged as unused-in-119th-but-BillTrax-carries-them) — expected, since
upstream's table is the full published vocabulary, not a one-Congress census.

**What upstream does *not* do:** classify a code's document **kind**
(full text vs. edit-instructions vs. procedural summary — `version_kind.py`'s
whole job). Upstream's `tier` (1–5) only orders versions on a legislative
timeline for diff sequencing; tier 4 lumps `eh`/`es` (full engrossed text)
together with `eah`/`eas` (amendment-only documents) — the exact "+0 added /
-N removed" trap `version_kind.py`'s docstring exists to prevent. No
`VERSION_KIND_LABELS`/`VERSION_KIND_WARNINGS`-equivalent exists anywhere in
`src/deltatrack/` (grepped `classify`, `VersionKind`, `version_type` — the
only `classify` hits are `diff_bill.classify`/`diff_pdf.classify_pdf`, diff
*change* classification, unrelated to document kind). Also absent: any
**format-choice** logic (`choose_format`/`FORMAT_TYPE_NAMES`/the
`pickVersionUrls` URL-suffix fallback) — upstream fetches XML/HTML/PDF by
fixed extension per package id (`package_content_url`, `fetch_govinfo.py:255`),
never chooses among a Congress.gov `textVersions[].formats[]` list.

Also structurally different: upstream's derivation is **code-first** with no
sealed-slug layer — `NAME_TO_CODE` is a disposable derived dict used only as a
fallback for url-less BILLSTATUS items, never a stored identity. `bill_versions.py`'s
long-form slugs (`introduced-in-house`, …) are a **hard product constraint**
(`bill_versions.version_code` is a live BillTrax SQL column that must never be
renamed) that has no reason to exist upstream and that upstream's table cannot
substitute for.

**Recommendation: keep `bill_versions.py` and `version_kind.py` as-is.**
Upstream solves a materially different problem for each of the three things
`bill_versions.py` does (sealed-slug identity has no upstream analog, format
choice has no upstream analog, and the code→name table — while genuinely more
complete than BillTrax's own — cannot replace a sealed SQL-facing vocabulary),
and `version_kind.py`'s full-text/procedural/summary classification has no
upstream counterpart at all. One narrow enhancement worth lifting regardless
of this recommendation: `resolve_code`'s longest-known-prefix fallback for an
*unrecognized* numbered reprint (`govinfo_suffix` currently just raises
`VersionCodeError` for any slug outside its closed table) would make the
fallback path degrade gracefully instead of failing hard on a future reprint
code neither table has seen.

---

## Pair 2 — `report_blocks.py` + `report_sections.py` vs upstream `parsers/committee_report.py`

**What upstream parses.** `committee_report.py` targets a narrow, specific
shape inside **Senate appropriations reports only**: 3-line "Appropriations /
Budget estimate / Committee recommendation" account summary blocks
(`parse_summary_blocks`, lines 93-125) and rows of the "COMPARATIVE STATEMENT
OF NEW BUDGET..." table (`parse_comparative_statement`, lines 168-214). Output
is `ReportAccount`/`ComparativeRow` dataclasses carrying a **dollar amount**
plus `title`/`bureau` hierarchy context — built as external validation ground
truth for DeltaTrack's own bill-vs-report dollar-figure cross-check, not a
general document index.

**Input shape.** Upstream is built for **GovInfo's HTML `<pre>` dump**
(`extract_pre_text`, lines 85-90) — GPO's ASCII layout with column alignment
*preserved on a single line* (`Committee recommendation....... $225,000,000`
all one line, per its own test fixture `BASIC_BLOCK` in
`tests/test_committee_report.py:22-30`). It is not XML and not (as shipped)
PDF-extracted text, though `parse_summary_blocks`/`parse_comparative_statement`
do accept a bare string, so plain text can be fed directly.

**Header detection vs. BillTrax's 12 patterns.** `report_blocks.py`'s
`HEADER_PATTERNS` (12 named regexes: `department`, `office`, `bureau`,
`agency_for`, `national`, `corps_of`, `united_states`, `food_and`,
`general_services`, `small_business`, `environmental`, `federal`, plus two
all-caps fallbacks) is a **broad, deliberately noisy** block-boundary splitter
— its own docstring documents that it fires on `REPORT`, `C O N T E N T S`,
`HURRICANE SANDY` exactly as often as on real agency names, because BillTrax's
stored `report_sections` rows carry that same noise. Upstream's heading logic
(`_is_heading`: >80% uppercase letters and not a qualifier line;
`_is_bureau_header`: indented, title-case, excludes lines matching
`recommendation|estimate|appropriations?|fiscal year|grand total|budget|amount|
project title|activity`; `_TITLE_NUMERAL_RE` for bare `TITLE N`) is **narrower
and purpose-built** to walk a specific title→bureau→account hierarchy and
explicitly *excludes* the financial-table-header words that would otherwise
collide with account headings. These are not the same classifier: one
over-splits generically for storage, the other narrowly anchors to a
"Committee recommendation" line and only tracks headings needed to attach
title/bureau context to that one amount.

**Run on the branch's three real fixtures** (`tests/fixtures/agency_reports/*.txt`,
pymupdf-extracted, `spicy_docs.extraction.api.DocumentExtractor(NativeText())`
over `pymupdf==1.28.2`), via `uv run python` from the upstream clone:

| fixture | upstream `parse_summary_blocks` | upstream `parse_comparative_statement` | branch `report_blocks.parse_agency_blocks` header count (pinned in `tests/test_report_blocks.py::test_the_hyphen_guard_measurably_drops_header_matches_on_real_reports`) |
|---|---:|---:|---:|
| `crpt-119hrpt105.txt` (House Rules Committee report, not appropriations) | 0 | 0 | 9 |
| `crpt-113hrpt135.txt` (Energy-Water approps, excerpted) | 0 | 0 | 29 |
| `crpt-113srpt77.txt` (Homeland Security approps, excerpted) | 0 | 0 | 139 |

**Root cause of the 0/0, confirmed by inspection, not assumed:** pymupdf's
per-page `.text` splits the GPO dot-leader line from its dollar amount across
**two separate output lines** —
```
Committee recommendation .................................................
123,600,000
```
— where upstream's `_COMMITTEE_REC_RE` requires `^Committee recommendation\.{2,}\s+\$?([\d,]+)\s*$`
on **one** line (confirmed by grepping `crpt-113srpt77.txt:494` and the
following line). The GovInfo HTML `<pre>` dump upstream expects preserves
this as a single line; pymupdf's page-text reconstruction does not. So
upstream's parser is not merely a worse fit here — as shipped, it produces
**zero output** on input the branch already has, and would need a
line-rejoining preprocessing step (which does not exist in either codebase)
before it could run. `crpt-119hrpt105.txt` is additionally the wrong report
*type* for upstream (a Rules Committee procedural report, no appropriations
table at all — confirmed 0 hits for both `"Committee recommendation"` and
`"COMPARATIVE STATEMENT"` in that fixture).

**Recommendation: keep `report_blocks.py` and `report_sections.py` as-is.**
Upstream solves a narrower, different problem (dollar-figure validation
ground truth for Senate appropriations reports specifically, from a GPO
HTML-preserved-column input spicy-docs's acquisition path doesn't produce) and,
run against spicy-docs's own real fixtures, extracts nothing; `report_sections.py`
is pure aggregation over already-stored rows with no parsing content to
compare at all. If spicy-docs later wants dollar-amount extraction from
committee reports (a capability neither branch module has today), upstream's
title/bureau hierarchy tracking and cell-tokenizing (`_parse_cells`) are a
reasonable pattern to borrow then — but that is a new feature, not a
replacement for the existing block splitter.

---

## Pair 3 — every other upstream module that overlaps something on spicy-docs `main`

| upstream module | overlaps | note |
|---|---|---|
| `tools/fetch_govinfo.py`, `tools/fetch_bills.py`, `tools/fetch_bill_archives.py`, `tools/fetch_bill_text_archives.py`, `tools/bill_index/` | `spicy_docs.sources.congress.*` (`bill_acquisition.py`, `bill_status.py`, `bill_text.py`, `bulk_status.py`, `listing.py`), `spicy_docs.sources.govinfo.*` (`bodies.py`, `body_acquisition.py`, `discovery.py`, `mods.py`, `premis.py`) | Both fetch bill text/metadata from Congress.gov and GovInfo bulk data; upstream's are one-off `tools/` CLI scripts building DeltaTrack's own test corpus (direct `httpx` GET + retry, no package-identity verification before download), spicy-docs's are production acquisition modules behind `GovInfoBodyAcquirer`/`SourceAcquirer` (budget bounds, credential handling, identity proof from summary+MODS first). Not comparable in maturity; keep spicy-docs's. |
| `src/deltatrack/parsers/pdf_text.py` | `spicy_docs.extraction` (`pypdf.py`, `pages.py`'s pymupdf backend, `api.py`, `ocr.py`) | Both extract text from PDF bytes; upstream is pypdfium2-only (this repo's sole engine dependency), spicy-docs deliberately runs pymupdf as primary (`pdf = ["pymupdf>=1.28,<2", ...]`) with pypdf as an optional secondary — chosen after `docs/research/pdf-backend-bakeoff/` already measured pdfium variants against pymupdf/pdfminer/pypdf on spicy-docs's own corpus. Re-litigating that choice against upstream's engine wasn't in scope here; flagged for visibility only. |
| `src/deltatrack/parsers/committee_report.py` | `spicy_docs.sources.agency_reports.report_blocks`, `spicy_docs.interpretation.report_sections` | Covered in full as Pair 2 above. |
| `tools/shared/http.py` (`request_with_retry`) | `spicy_docs.transport.http`, `spicy_docs.transport.retry` | Both are generic HTTP-retry helpers for acquisition tooling; spicy-docs's is the more general, already-integrated version (used across every `sources.*` module, not just Congress.gov). |
| `src/deltatrack/bill_tree.py`, `structure_tree.py` | none on `main` | Normalizes bill XML into a structured comparison tree for diffing. spicy-docs has no bill-XML structural-tree module (`bill_text.py` only validates identity, doesn't build a tree) — this is DeltaTrack-unique, not an overlap. |
| `src/deltatrack/parsers/pdf_anchors.py`, `pdf_blocks.py`, `pdf_observations.py` | none on `main` | PDF landmark/anchor extraction feeding DeltaTrack's own PDF differ. No spicy-docs counterpart; spicy-docs doesn't diff bill PDFs. |
| `src/deltatrack/diff_bill.py`, `diff_pdf.py`, `compare/`, `matching.py`, `similarity.py`, `amounts.py`, `formatters/*`, `palette.py`, `web/app.py` | none on `main` | DeltaTrack's actual product — the two-version diff engine, its formatters and the FastAPI service that exposes it. spicy-docs has no diff/compare/report-rendering surface at all; this is the whole reason DeltaTrack exists as a separate project rather than a module to port piecemeal. |

---

## Summary

| pair | recommendation | one-line reason |
|---|---|---|
| `bill_versions.py` + `version_kind.py` | **keep** | Upstream's real code-vocabulary counterpart (`fetch_govinfo.py::VERSION_CODES`/`resolve_code`) correctly resolves all 24 measured codes but has no sealed-slug identity, no format-choice logic, and no full-text/procedural-amendments/summary classification — three things this pair exists for that upstream doesn't do. |
| `report_blocks.py` + `report_sections.py` | **keep** | Upstream's `committee_report.py` targets a narrower problem (dollar-figure ground truth from Senate appropriations reports, via GPO HTML-preserved-column input) and produces zero output when run on the branch's own three real fixtures because pymupdf splits the label and amount across lines that upstream's single-line regex requires. |

No module on either branch is a candidate to adapt as a thin layer over
upstream or to drop: in both pairs upstream solves an adjacent-but-different
problem rather than a strictly larger version of the same one, and in Pair 2
upstream's parser is demonstrably non-functional against the exact input the
branch already produces.
