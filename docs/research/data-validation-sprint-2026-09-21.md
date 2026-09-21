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

Results will be linked here as each reviewed unit is committed.
