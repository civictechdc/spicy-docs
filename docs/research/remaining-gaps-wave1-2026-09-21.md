# Remaining gaps: first implementation wave

This wave repairs shared validation, publication mechanics, retained regulatory
fields and capture provenance. It does not certify every published row or deploy
corrected data. Each implementation received independent review, including direct
input/output comparisons and failure cases. The execution rows in
[the gap register](closing-the-gaps-2026-09-19.md#20-execution-status-maintained-updated-as-each-branch-merges-or-stalls)
record the individual landings.

## What changed

| Owner | Result | Evidence and limit |
| --- | --- | --- |
| SpicyDocs | Shared JSON serialization rejects nested non-finite values through named row refusals. Rule digests establish equality, not chronology. | 7,263 branch tests passed; the retained 118th HR/S five-table replay preserves all 2,206,611 cells. Independent original XML/output comparison matches all 52 H.R. 1 subjects. General date/number/boolean declarations and mixed-rule host inputs remain open. |
| SpicyRegs | Complete table generations use the installed Rulespec artifact verifier, full Parquet decoding, byte checks and a conditional publication pointer. Managed readers pin their inputs and distinguish legacy data. | Interrupted uploads, concurrent writers, corrupt data pages, stale local caches and partial bill writers are tested. A local partial candidate cannot become a complete published family. Actual R2 behavior and public rollout remain untested. |
| SpicyRegs | An explicit local repair rereads retained regulatory sources despite old discovery checkpoints. Equal-date source corrections and NULL clearing preserve newer priors and host enrichment. Proceedings and comment periods retain complete RIN sets. | 391 dockets, 546 documents and three comments yield 10,969 raw/output comparisons with zero mismatches. Four newer prior rows remain preserved. Three comments are a named sample, not complete agency coverage. |
| Rulespec | Opt-in DocumentCapture v2 shares source receipts, MODS identity evidence, original/derived artifact relationships, coordinates and rule/converter bindings. | Independent preservation checks cover 934 nodes and 2,444 spans across seven captures. V1 schema bytes and defaults remain unchanged. The 11 known evidence gaps remain findings; archive/member proof remains a separate task. |

A Regulation Identifier Number (RIN) links related regulatory materials.
Recovery preserves literal placeholders such as `Not Assigned`; join recipes use
all usable RINs and the Federal Register's dated document identity. A matching
identifier supplies linkage evidence, not a qualified interpretation of a rule's
meaning.

The selected local repair restores 47 docket RIN fields, 496 document attachment
fields, 488 Federal Register references and 503 withdrawal values. Four newer
public observations survive unchanged. Attachment descriptions identify available
source files; this replay does not acquire their bodies.

## What independent review caught

Publication initially reused stale local priors even when it captured a newer
public pointer. Builds now use isolated retained directories. A readable Parquet
footer initially hid corrupt data pages; admission now decodes every column.
The two bill writers now share one publication family, with unchanged sibling
bytes explicitly carried forward. The existing non-table docket-search gzip
keeps its legacy path.

CLI batches now become visible only after every requested managed member passes.
MCP preserves the newer FEC dictionary descriptions and local-data mode while
adding captured generation status. Local mode makes no remote fallback request;
helper tables do not become advertised datasets.

Recovery initially treated a leftover temporary comment file as committed prior
state, and a failed index write could damage its predecessor. Both failure paths
now retain the prior result and support retry. Review receipts preserve the
original failures and their corrected reruns.

## Work still required

- **SpicyRegs:** rehearse publication in a disposable R2 bucket, then rebuild and
  adopt explicitly selected public generations. Base regulations.gov tables,
  partitioned comments and Iceberg still need their own publication treatment.
  Repair lifecycle grouping before using its rows as a census or its durations
  as reliable outcomes. Finish joins with identity and unresolved-link evidence.
- **SpicyDocs:** declare logical value types from source evidence, qualify model
  and rule interpretations against predeclared thresholds, and adopt v2 capture
  profiles through real converters. Acquire the missing provenance rather than
  relabeling absent evidence as complete.
- **Rulespec:** finish shared archive/member identity and verification. The CFR
  original PDF is unavailable in the named evidence locations; its acquisition
  time is unproven. Six Senate cell boxes remain unobserved. The additive v2
  package capability is prepared locally; source adoption and release are separate.
- **RefSpec:** continue reference-resolution and join qualification using retained
  source observations. This wave makes no RefSpec code change or new claim of
  reference coverage.

## Validation state

The committed SpicyDocs snapshot `6d33bd5` passes the full project gate:
7,273 tests, four skips and 46 deselections. That check used an isolated checkout;
unrelated in-progress main-worktree edits were preserved and are not covered by
that result. Subsequent register/report edits do not change source code.

The final combined SpicyRegs gate, including both host changes and current FEC
integration, passes 2,042 tests with three deselections. Lint, types and all 71
schema declarations pass. The retained-source comparison also repeats through
installed SpicyDocs 0.26.0 with zero mismatches. Rulespec independently passes 28
capture tests, its installed package checks and 44 canonical cases.

## Replay evidence

All campaign files are outside the repositories under
`~/Work/corpora/supply-2026-09-02/receipts/remaining-gaps-wave1-2026-09-21/`:

- `sd1/`: serialization controls, actual bill replay and independent XML witness.
- `sr1/`: publication failures, reader tests, native admission and both reviews.
- `sr2/`: admitted retained releases, original/output comparisons, failure/retry
  witnesses and separate recovery/RIN reviews.
- `rs1/`: original captures, migrated candidates, receipt decoding, preserved-field
  comparison, missing evidence and installed-wheel checks.

Older receipts remain unchanged. Fixture faults are labeled as injected controls;
they are not claims that publishers supplied corrupt values. Local checks,
commits, package adoption, public publication and deployment remain distinct.

All four changes were committed and merged into their owning local `main`
branches. This wave made no remote push, package release, upload or deployment.
