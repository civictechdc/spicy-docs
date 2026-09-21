# Legislative readiness: source corrections and publication evidence

**2026-09-21 — local implementation and retained evidence.** The immediate
priority is correcting source facts and making corrections reach output rows.
The handoff's proposed withdrawal of six derived tables is contradicted by
their public files. The 67 declared schemas, locally produced files, and
publicly available files describe different populations.

The implementation and documentation are committed locally on `main` in their
own repositories. No push, package release, upload, or deployment was performed.
Rulespec was not changed. Normal SpicyRegs runs still use the vendored
SpicyDocs 0.24.2; the corrected candidate explicitly selected the local source
checkout.

| Repository | Commit | Change |
| --- | --- | --- |
| SpicyDocs | `7335034` | Count the native cosponsor list, with real-source regression fixture. |
| SpicyDocs | `f20904d` | Qualify interpretation accuracy without changing extraction rules. |
| SpicyRegs | `e7cc6f3` | Replay corrected print and Senate reads with successful-read checkpoints. |
| SpicyRegs | `23d32c9` | Distinguish supported schemas, local production, and public availability. |

SpicyRegs' generated column descriptions still come from that pinned wheel.
Its table-level notes now explicitly flag the incorrect cosponsor description
and supersede the unqualified "hosted-quality" wording until package adoption.

## What the evidence establishes

| Question | Direct observation | Practical consequence |
| --- | --- | --- |
| Are all 67 tables publicly available? | 24 documented URLs returned Parquet; 43 returned HTTP 404. Twenty available files match the declared column names and order; four differ. | A declared schema or `measured_on` date cannot establish publication. |
| Should the six derived tables be withdrawn as unproduced? | All six exist publicly and have rows. | Keep their definitions; H3's premise is refuted. |
| Is the expanded bills table public? | Public `congress_bills` has 419,571 rows and 10 columns; the local adoption output has 16,213 rows and 49 columns. | Treat the expanded output as a separate candidate. |
| Are source facts in the retained bill output correct? | 13,154 bills said zero cosponsors despite entries in native XML. Other inspected native fields agree. | Repair the parser/shaper before combining or publishing more generations. |
| Do corrected rules reach print and Senate rows? | Previous timestamp-only skips ignored processing changes. | Persist processing checkpoints, retry stale reads, and replace successful results even when empty. |
| Are interpretation fields qualified for factual use? | This source audit does not measure inferred stages, signing dates, money classifications, or referral interpretations. | Keep qualification open; no new acceptance threshold was invented. |

The public column mismatches are `documents`, `comments`, `congress_bills`, and
`federal_register`. The six retained derived tables are `agency_stats`,
`agency_monthly_volume`, `discovery_signals`, `feed_summary`,
`rulemaking_lifecycles`, and `org_committee_links`. `bill_subjects` returned 404
despite a retained local output.

The Git ancestry claim also needed correction: at the start of this audit,
SpicyRegs upstream `1f02a7f` was an ancestor of local `2b7b5e4`, 111 commits
behind. Public availability matches
the upstream 24-table declaration, but neither fact proves which job deployed
those files.

## Corrected source facts and bounded candidate

The parser now reads the publisher's separate cosponsor list. The table shaper
counts that list, rather than counting sponsors after the first. An unexamined
list remains NULL; an examined empty list produces zero. Counts include every
listed entry, including withdrawn entries, and do not claim active membership.

The reduced real `118-hr-1` fixture retains one sponsor and 49 cosponsors. Its
source-member digest and reduction procedure are documented beside the fixture.
An independent XML reader compared the complete retained 118th Congress House
and Senate bill archives with the old output and the corrected candidate.

| Corrected candidate table | Rows |
| --- | ---: |
| `congress_bills` | 16,213 |
| `bill_actions` | 75,239 |
| `bill_committees` | 26,029 |
| `bill_publisher_summaries` | 10,806 |
| `cbo_cost_estimates` | 1,431 |

All 1,189,950 named native-field comparisons pass against the candidate. The
five tables have no missing or extra source keys, duplicate or NULL keys, or
orphan rows. The 1,468 native CBO items fold into 1,431 keyed estimates, retaining
differing restatements. The complete old/new output comparison changes exactly
13,154 `cosponsor_count` cells and nothing else.

These comparisons cover the fields named in the validation receipt, not every
schema column or the truth of inferred values. The candidate was built with
network connections disabled, no model calls, and no prior tables. It proves
agreement with the retained bytes, not current publisher freshness. No laws
input was supplied, so `statutes_at_large_cite` remains NULL.

The broader retained output has 119th Congress expanded rows with the same
count defect. Their native archives were not located during this audit. A
larger union would preserve those wrong counts. The existing coalescing merge
also cannot express clearing a stale non-NULL field. The observed NULL conflict
in these inputs concerns URLs from different sources; it is not proof either
source is wrong. A broader release needs explicit source and clearing rules.

## Correction handling

SpicyRegs now records successful processing checkpoints in the same Parquet
files as the rows. The checkpoint identifies publisher revision and relevant
rule, reader, vocabulary, and read-limit inputs. An unchanged source becomes
eligible when processing changes. Rows without checkpoints are read again once.

- Print corrections replace findings for the same document and text digest,
  including a successful empty result, while retaining earlier text versions.
  Parent and child checkpoints must agree before skipping.
- Senate corrections replace only the successful `(package_id, file_name)`
  result. A truncated page stream or failed sibling preserves previous rows.
- Stale retained packages remain eligible outside the discovery window when
  processing changes. This does not establish fresh source polling there.

Direct replay reproduced all 340 actions from the retained 167-page committee
report. Of their evidence spans, 339 match literally and one crosses the
phrase matcher's `HEAR-\nING` line-end normalization. The Senate replay reproduced
69 tables and 357 rows from the requested first 80 pages of a 1,335-page PDF;
the retained page image was also checked against selected account values.
This establishes the stated prefix and examples, not whole-report extraction
quality or coordinate qualification.

The uploader still publishes files sequentially and has a per-file shrink
guard. Checkpoint disagreement enables retry after partial publication; it
does not make a multi-table release atomic. H7 remains open.

## Retained receipts and verification

All campaign receipts are outside the repositories under
`~/Work/corpora/supply-2026-09-02/receipts/`. Existing receipts were read-only.

- `publication-audit-2026-09-21/`: exact declaration, response observations,
  raw Parquet footers, footer digests, column lists, counts, and audit procedure.
  This proves availability and metadata shape, not row contents or a shared
  generation. Footer digests are not whole-file digests.
- `legislative-release-candidate-2026-09-21/`: native member pins, independent
  comparisons, paired raw/output examples, five candidate files, source-module
  pins, and replay commands.
- `correction-lifecycle-2026-09-21/`: raw-source replays, page image, regression
  probes, and independent review. Repository checks are recorded here as well.

Final repository checks passed:

| Repository | Checks | Result |
| --- | --- | --- |
| SpicyDocs | `./scripts/check` (frozen environment, lint, formatting, tests) | 7,251 passed; 5 skipped; 46 deselected |
| SpicyRegs | `uv run --frozen pytest -q` | 1,846 passed; 3 deselected |
| SpicyRegs | `uv run --frozen ruff check .`, `uv run --frozen ty check`, `uv run --frozen spicy-regs-dict check` | All passed; dictionary covers 67 declared schemas |

The initial SpicyDocs gate stopped on one formatting difference; it was fixed
and the complete gate reran successfully. Both logs are retained. Default test
gates exclude their configured live integrations; they do not establish public
deployment or continuing publisher availability.

Independent code review approved the source-count/shared-merge changes and
the final print/Senate correction paths. The latter ran 107 focused tests and
independent failure/retry probes. Review caught and closed three defects during
implementation: deletion of prior print text history, omission of stale Senate
files outside discovery, and repeated reads of already-corrected sibling files.
Certificates are `root-changes-review.md` and `review.md` in the correction
receipt. Existing sequential uploads and the shrink guard remain explicit
publication limits.

The final catalog/readiness review also approved the corrected wording and
artifact counts. It verified that all 67 table identities, column lists and
their order, and the catalog format version remain unchanged. The final
dictionary-specific test run passed all 34 tests after those wording changes.

## Remaining sequence

1. Adopt the committed source-count correction in the host's package pin and
   carry the reviewed correction handling into the publication candidate.
   The local checkout is not the released wheel.
2. Recover or reacquire native inputs for the wider bills population and repair
   affected rows. Define field-clearing and mixed-source rules before merging.
3. Prepare one declared publication generation, compare actual output schemas
   and keys, and exercise replacement and failure recovery with the uploader.
4. Set interpretation acceptance criteria before qualification. Resume the
   highest-value existing joins after source facts and publication are reliable.

New acquisition families and parent-schema changes are outside this correction.
