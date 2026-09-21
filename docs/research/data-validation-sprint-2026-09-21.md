# Data validation sprint — 2026-09-21

## Decision and scope

Determine whether the current source readers and output tables preserve source
facts accurately, retain the useful information the publisher supplies, and
support useful analysis and joins. Cover every declared SpicyRegs table, every
additional table emitted by its pipelines, and every SpicyDocs source family,
including source-native releases and readers without a hosted table.

The audit starts at SpicyDocs `22f6a78` and SpicyRegs `23d32c9`; the host still
uses the SpicyDocs 0.24.2 wheel. Treat retained local generations, current source
code, and public artifacts separately. Existing receipts remain read-only.
New evidence belongs in
`~/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/`.

## Questions and predeclared checks

| Dimension | Question | Evidence needed |
| --- | --- | --- |
| Conversion | Do source identity, literal fields, units, dates, counts and nested relationships survive? | Direct comparisons with retained native bytes, independent of the product parser where practical; contextual inspection of PDF/HTML examples. |
| Completeness | What source fields, records, periods, bodies or relationships are omitted? | Source/output key accounting, null/empty distinction, pagination and refusal accounting, explicit scope and current code paths. |
| Shape | Can a consumer distinguish grain, source version, empty success, missing data and inference? | Keys, duplicates, types, JSON shape, timestamps, provenance, foreign-key checks, and correction behavior. |
| Usefulness | Which real question does this output answer, and what prevents it? | At least one concrete analytic or retrieval use per table/family; executable joins or aggregates where artifacts permit. |

Default useful outcomes are cross-government research, legislative tracking,
and evidence-backed retrieval. User steering may prioritize one without
removing tables from the audit.

For source-stated facts, an unexplained mismatch is a defect in the inspected
scope. Schema validity or reproducible replay alone cannot establish semantic
accuracy. For interpreted fields, report observed errors and existing declared
thresholds; do not invent a passing threshold after seeing the sample.

Use all rows of practical retained outputs for structural profiles; use
deterministic, named raw/output samples for deeper semantic review when a full
census is impractical. Record sample selection, denominators and byte/input
pins. Do not report sample results as population accuracy. Older measurements
may support a finding but must retain their date and scope.

Bound fresh read-only probes to evidence gaps, use existing reader/transport
facilities, and record refusals. No model spending, full-population acquisition,
package release, upload or deployment is part of this validation sprint.

## Decision rules

- **Supported in inspected scope:** named checks passed against actual inputs
  and outputs; state the scope and remaining uncertainty.
- **Defect demonstrated:** retain a counterexample and identify the conversion
  or data-shape failure. Fix a bounded defect when its intended behavior is
  established; verify and commit the fix separately.
- **Limited usefulness:** facts may be accurate, but scope, missing fields,
  shape or unavailable joins prevent the stated use.
- **Unvalidated:** required raw inputs or produced artifacts were not found or
  could not be inspected. This is an evidence gap, never a pass.

Every inventory entry needs a disposition on all four dimensions and a next
action. Multiple dimensions may have different verdicts. A completed sprint
means a reconciled inventory and evidence-backed dispositions, not a claim
that every source or inferred field has become production-qualified.

## Work streams

1. Legislative sources and bill, vote, member, committee, law and print outputs.
2. Regulatory sources, core docket/document/comment outputs, and derived tables.
3. Spending, organizations, oversight, courts, elections and other source families.
4. Cross-cutting inventory, full output profiles, missing sources/tables,
   cross-table usefulness, independent challenge and final reconciliation.

## Result

The program has useful, often source-faithful metadata and retained evidence.
It does **not** yet provide a consistently complete, analytically safe public
dataset. Three different failures need separate treatment: current conversion
defects, public artifacts that lag working source readers, and interpretations
or aggregates whose names imply more certainty than their inputs support.

The sprint reconciles **70 output tables**: 67 declared tables plus
`bill_subjects`, `court_opinion_clusters` and `court_opinion_bodies`. It also
covers all **20 source families**, including native releases that have no
hosted table, and checks the separate docket-search derivative.
Only 24 table files were publicly observable in the retained URL probes; the
other 46 table profiles describe local artifacts, not additional public data.
Every table and family has conversion, completeness, shape and usefulness
dispositions, evidence scope and a next action in the linked scorecards:

- [All tables and source families](data-validation-tables-2026-09-21.md).
- [Legislative inputs and outputs](data-validation-legislative-2026-09-21.md).
- [Regulatory inputs and outputs](data-validation-regulatory-2026-09-21.md).
- [Organizations, spending, elections, oversight and courts](data-validation-other-2026-09-21.md).

These dispositions complete the inventory review. They do not certify every
publisher record or every inferred field. An empty output or a missing native
input receives an explicit limitation rather than a passing semantic verdict.

## What was actually inspected

The structural scan reads every row of 23 pinned whole public tables, three
pinned row groups from public `comments` (212,733 of 23,889,661 rows), and
retained local artifacts for the remaining 46 tables. It profiles actual
columns, nulls, identity keys, JSON syntax, date representations and counts.
Three additional bill generations are compared separately. Large court-text
field cardinalities use an approximate count after an exact profile exhausted
its memory allowance; key and null checks remain exact.

The public artifacts were observed independently, not as one atomic release.
The documents object changed during acquisition: a conditional request refused
the old version, then a new footer and version were observed and pinned before
downloading it. Small derived-table differences consistent with those changing
inputs are not automatically classified as calculation defects.

Direct semantic checks include retained publisher JSON/XML, fresh bounded
metadata probes, source-native release members, literal FEC byte slices,
HTML and rendered PDF pages. For example, checked fields agree for all 2,966
committee assignment records, all 2,204 nomination records, all 3,954 records
in the retained Fall 2025 Unified Agenda, and 391 ACF dockets plus 546 ACF
documents through the current source conversion. Four complete retained CBO
Congress feeds also pass 36,225 field comparisons over 5,175 listed items.
These scopes do not establish
coverage of other Congresses, agencies, releases or source routes.

The structural scan found nine empty tables and 47 entirely null columns in
nonempty outputs. Neither count is a defect count: a field can be optional,
inapplicable, unsupported in that generation or not yet produced. Four public
schemas lag current declarations: bills lack 39 appended columns, documents
and comments lack `pdf_extraction_results_json`, and Federal Register lacks
the scalar `rin`. All inspected non-null `*_json` values parse as JSON; that
does not establish that their contents are correct or complete.

Evidence resides below the receipt root named above. Start with
`table-profiles-final.json`, `artifact-selection.json`,
`structural-summary.json`, the three stream assessment files and
`independent-witness-review-v2.json`. Acquisition receipts retain HTTP status,
version, byte range and digest information. Earlier failed or superseded
measurement attempts remain present and are not used as final results.

## Findings that change the next work

| Priority | Finding and practical consequence | Next action and acceptance evidence |
| --- | --- | --- |
| 1 | Public data loses fields that current source readers preserve. An ACF document with the same publisher modification timestamp has native PDF/HTML links and a Federal Register number but null public fields. Across the inspected ACF cohort, 496 attachment arrays and 488 Federal Register references differ; timestamp-equal losses are demonstrated, while changed records remain separately qualified. Public document text is null in all 2,001,222 inspected rows. | Adopt corrected readers and backfill retained raw inputs into a pinned generation. Compare source keys and every intended mapped field before publishing; document which bodies were acquired and extracted. |
| 1 | Federal Register `document_number` is not globally unique. Fresh daily responses contain two distinct `00-111` documents on 2000-01-14 and 2000-01-18; the public table retains only the latter, and current merging deduplicates on the number alone. | Use the documented date-plus-number identity throughout merge, dictionary and consumers; replay both native records and prove that references remain unambiguous. Backfill the lost record, rather than expecting a recent-date overlap to rediscover it. |
| 1 | Court body output can advertise available text without carrying that text. A retained 250,000-row output has 73 rows with a positive text count and `html` availability but neither stored body field. | Retain every supported source text rendition with its format and provenance, or report an explicit unsupported outcome. Recover the original bulk bytes before claiming exact source-text equality. |
| 1 | CFR part labels lose letters: `1203a` and `1203b` collapse to `1203`. This affects 336 of 319,186 inspected public granule identifiers. A separate fused-section hierarchy risk remains outside this fix. | **Fixed locally** in SpicyRegs `cb75404`. Four regression cases and the full identifier census verify the narrow correction. Regenerate and validate the public artifact before calling the published data corrected. |
| 2 | Some derived labels and event rows are misleading. Generic report headings become `agency_key` values; a rendered committee report exposes omitted bills, duplicate action findings and a hearing identifier attached to the wrong date block. | Preserve literal headings separately from resolved agencies. Qualify action rules against a declared error threshold and context-aware gold set before using them for counts or assertions. |
| 2 | Rulemaking lifecycle grouping merges unrelated records when docket IDs are absent. The 19 retained unknown-docket agency groups collapse 48 source proposals; the wider population has 5,132 such proposals, with 56 other groups excluded by the earliest-date floor. Another 647 non-null proposal groups disappear when the earliest final rule predates the earliest proposal. | Keep unresolved document-level events and explicit pairing outcomes. Define and test the intended lifecycle relationship before presenting elapsed-time or “stuck” statistics as policy facts. |
| 2 | Precision and relationships are lost in useful-looking scalar fields. Unified Agenda month-only dates become first-of-month dates; a meeting's off-site address disappears; four committee codes occur only in nested parent records. | Preserve source date text and precision, represent location variants, and expose nested committee relationships without inventing unavailable child details. |
| 2 | Citation detection is incomplete even in the inspected budget PDF: five printed references to 31 USC 1106 produce three rows. Numeric financial tables in that document are not available as numeric hosted facts. | Add reverse-order citation wording to a declared extraction evaluation; retain page context. Treat financial-table extraction as a separately qualified capability with units, periods, row/column labels and provenance. |
| 2 | Coverage is fragmented across generations. Several legislative outputs are local, nine selected outputs are empty, and public bill metadata still has the old shape. Some missing rows differ between independent paginated runs. | Produce a coherent generation with explicit source scope, input/output manifests and parent-child key accounting; expose absent and unproduced outputs as such. |
| 3 | Valid joins can still yield invalid aggregates. 100,954 of 113,051 inspected recipient rows join SAM by UEI, but 32,497 UEIs have multiple recipient rows. Organization-to-FEC links join successfully but use unqualified heuristics. | State each table's grain and time scope. Require deliberate aggregation before one-to-many joins; label heuristic identity links and measure their precision independently. |

## Where the data is useful today

Source metadata supports discovery and traceable retrieval: finding a docket,
bill, vote, report, opinion or filing and returning to its publisher evidence.
Stable identifiers also enable useful bounded joins, such as recipient-to-SAM
lookups and committee assignments. Source-native FEC, FOIA and oversight
outputs retain information that the hosted-table count does not describe.
Their individual profiles and successful/refused routes are recorded in the
other-source report; successful byte preservation is not semantic extraction
qualification.

The present outputs are less suitable for questions that require complete
document bodies, current registration status, exhaustive hearing/bill links,
trusted agency attribution, exact lifecycle durations, numeric budget analysis
or comparable longitudinal populations. Many of those questions need existing
source evidence carried through more faithfully, not another acquisition
family.

The useful common shape is a source observation with a stable key, literal
value, source version and evidence locator; any normalized value must retain
its precision and rule identity. Many-valued relationships need link rows or
explicit arrays. Derived findings need their rule/model version, supporting
context and measured qualification status. A release needs a manifest that
ties these outputs to the same declared input scope. Add these features where
the demonstrated findings require them; do not redesign every table at once.

## Delivery and limits

The CFR correction is committed locally. The audit reports and inventory are
committed separately, followed by the register update. No public artifacts,
packages, deployments or remote branches changed during this sprint. Rulespec
needed no schema change for this audit.

The full SpicyDocs gate passed: 7,251 tests, five skipped and 46 deselected.
SpicyRegs passed 1,850 tests with three deselected, Ruff lint, type checks and
the 67-table dictionary check; the two changed files pass formatting. An
additional repository-wide formatting check reported 31 unchanged files that
already need formatting. They were preserved rather than mixed into this fix.
These software checks supplement the source/output evidence; they do not
establish data accuracy by themselves.
