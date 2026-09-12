# Work status

**Merged simplification: 23 local items complete; two conditionally deferred.**
Six original items moved to their implementation owners. A moved task is not a
completed task; follow the receiving backlog for its status.

## GovInfo bill integration

First deliverable: explicit bill IDs and text versions, exact status/text XML,
and installed-wheel consumers. Collection discovery and new regulatory sources
remain separate work with their own scope and coverage checks.

- [ ] **G01:** Parse current BILLSTATUS and bill XML; preserve source fields, summaries and every stated text-version link; prove bill/version identity.
- [ ] **G02:** Share bounded HTTP capture with Federal Register; expose status and explicitly selected XML text acquisition.
- [ ] **G03:** Replace SpicyRegs' duplicate BILLSTATUS subject acquisition with the qualified SpicyDocs wheel.
- [ ] **G04:** Add a DocSpec-owned catalog, injected fetcher and processing example; prove later processing reuses captured bytes.
- [ ] **G05:** Run source/receiver checks, bounded live captures, installed-wheel qualification and independent reviews; document the supported formats and limits.

Deferred until a named collection workflow needs them: bounded GovInfo JSON
discovery/publication, standalone BILLSUM coverage, annual CFR editions, eCFR
snapshots, and Federal Register issue acquisition justified by batch measurements.

## Fetcher format review

The [format review](fetcher-formats.md) covers all implemented fetchers and
network tools. Four follow-ups remain; this review did not implement them.

- [x] **F01:** Review structured-format opportunities with parallel source reviewers and architecture consensus.
- [x] **F06:** Test GovInfo issue XML with retained live evidence. Extraction is feasible; no additional recovery demonstrated. Keep the default unchanged. [Result and limits](fetcher-formats.md#opportunities-that-need-more-evidence).
- [x] **F07:** Review all 23 tracked GovInfo bulk-data assets, including PDF guides, XML pairs and HTML samples; refine source-format guidance. [Findings and scope](fetcher-formats.md#what-the-complete-govinfo-asset-review-adds).
- [ ] **F02:** Correct JSON aliases and URL-path extension inference; revise affected Regulations.gov/public-comment policies and qualify publication/replay.
- [ ] **F03:** Capture Federal Register `full_text_xml_url` and emit `body-xml`; revise source schema/policy, bundle, admission and replay together. Decide any Parquet column separately.
- [ ] **F04:** Retain CRS `version` on new captures. Document that earlier successful rows need an explicit fresh capture to obtain missing version evidence.
- [ ] **F05:** Preserve CourtListener CSV quoted empty strings versus nulls; cover escaping/newlines and bounds, and check downstream raw-reader consumers.

## XML body preference

- [x] **X01:** Prefer validated Federal Register XML; retain HTML fallback only after XML 404/410.
- [x] **X02:** Demonstrate XML and fallback with retained bytes; update callers and source guidance.
- [x] **X03:** Check identity, refusal, shared bounds, live XML and installed-wheel use; independently review.

Validation: 916 tests passed (two opt-in tests deselected), lint/format passed,
and independent architecture/code reviews approved. Four live XML samples and
both installed-wheel examples passed. [Usage and limits](federal-register-body-sources.md).

## Readability pass

- [x] **R1:** Consolidate Markdown around current tasks, rules and ownership.
- [x] **R2:** Compact comments/docstrings while preserving intent and behavior.
- [x] **R3:** Review meaning, links, CLI help and executable-code equivalence.

Validation: 802 tests passed (two opt-in tests deselected), lint/format passed,
and both independent reviews approved. Python logic and TOML settings are
unchanged; seven CLI help checks and local link/example checks passed.

## Deferred local work

<a id="s21"></a>

- [ ] **S21 — Replace the campaign after a better workflow exists.** The current
  campaign publishes independent source releases. Reopen when a named workflow
  and DocSpec D22 demonstrate source ordering, interruption, root ownership,
  resource bounds, retained pins and stale-resume refusal. Then remove replaced
  pools, receipts, locks and recovery branches while preserving useful diagnostics.

<a id="s31"></a>

- [ ] **S31 — Use DocSpec wheels for a concrete local dataset caller.** The audit
  found no remaining local catalog, document-capture, processor or dataset-resume
  loop to replace. Reopen when such a caller exists and qualified public APIs
  preserve source/fetcher/processor injection. Remove its replaced loops after
  parity checks; keep source users independent and package dependencies acyclic.

The [caller decision](source-ownership.md#current-campaign-and-dataset-callers)
explains both deferrals. DocSpec D51/D52 own the planned dataset examples;
creating a new source-side loop merely to migrate it adds no value.

## Completed local work

### Outcomes and evidence

<a id="s01"></a>

- [x] **S01 — Expose collection outcomes.** Reader and CLI distinguish success, empty, partial and total rejection, with bounded failure access. [Guide](source-native-outcomes.md).

<a id="s03"></a>

- [x] **S03 — Remove repeated campaign verification.** Normal publication replays once; pinned resume checks and explicit full audits remain. [Guide](cli.md#campaigns-replay-and-source-tools).

<a id="s04"></a>

- [x] **S04 — State the product boundaries.** Guides distinguish source records, retained evidence, body links, tables and dataset work. [Guide](source-workflows.md).

<a id="s05"></a>

- [x] **S05 — Require current formats.** Current producer, schemas, policies and required counts replace historical acceptance. [Guide](decisions.md#current-source-release-format-and-retained-evidence).

<a id="s06"></a>

- [x] **S06 — Separate storage accounting.** Read/reused/written-byte measurements live in run results, outside sealed source metadata. [Guide](releases.md).

<a id="s07"></a>

- [x] **S07 — Replay failure provenance.** Independent verification detects omitted, invented, duplicated or relinked deterministic failures. [Guide](releases.md#choose-the-right-check).

<a id="s08"></a>

- [x] **S08 — Retain refused evidence.** Bounded rejected response bytes remain diagnosable without producing an accepted release. [Guide](cli.md).

<a id="s09"></a>

- [x] **S09 — Explain coverage.** Selectors and source-specific assumptions distinguish observed scope from publisher-wide completeness. [Guide](source-native-outcomes.md).

<a id="s10"></a>

- [x] **S10 — Match comment claims to discovery.** Captured comments describe observed contiguous-part discovery, including empty, gap and request-failure cases. [Guide](sources/public-comments.md).

### Ownership and removal

<a id="s11"></a>

- [x] **S11 — Assign component ownership.** The inventory records useful consumers, retained responsibilities and selected removals. [Guide](source-ownership.md).

<a id="s12"></a>

- [x] **S12 — Retire unused catalogs and policy.** Removed generators, commands, seals and misplaced processor/region declarations together; retained source knowledge. [Guide](source-reference.md).

<a id="s13"></a>

- [x] **S13 — Keep useful tables; retire Iceberg attachment.** Immutable Parquet remains supported; the unused attachment surface and location plumbing are removed. [Guide](releases.md).

<a id="s14"></a>

- [x] **S14 — Share strict CourtListener parsing.** The public listing/filename parser serves the source reader; receiver adoption has its own tasks. [Guide](sources/raw-readers.md#courtlistener).

<a id="s15"></a>

- [x] **S15 — Keep proportionate drift diagnostics.** Pinned comparisons and explicit refresh remain source-maintainer tools, with no automatic acquisition gate. [Guide](source-domain-drift.md).

<a id="s16"></a>

- [x] **S16 — Remove superseded code and fix state/types.** Retired wrappers and declarations; kept purposeful optional APIs, source rules and bounded state. [Guide](architecture.md).

<a id="s17"></a>

- [x] **S17 — Preserve literal GAO topics.** Offline examples and bounded evidence access demonstrate matching, unexpected and refused inputs. [Guide](sources/gao.md).

### Public APIs and qualification

<a id="s19"></a>

- [x] **S19 — Package bounded GovInfo body acquisition.** Explicit routes preserve requested/resolved identity, enforce request/byte bounds and return reusable exact captures. [Guide](federal-register-body-sources.md).

<a id="s22"></a>

- [x] **S22 — Adopt the shared physical writer.** Rulespec handles bounded durable writes; SpicyDocs retains source references and result mapping. [Guide](source-ownership.md).

<a id="s23"></a>

- [x] **S23 — Qualify source docs and package.** The merged candidate was exercised from clean core/extras installations, with exact schemas and resources. [Guide](installation.md).

<a id="s24"></a>

- [x] **S24 — Review contributor value.** Independent reviews resolved findings; a simulated contributor ran source-only examples and added a mutation-checked regression. [Guide](../CONTRIBUTING.md).

<a id="s25"></a>

- [x] **S25 — Complete selected local handoffs.** Ownership, shared-writer adoption and receiving probes are recorded separately from upstream adoption. [Guide](source-ownership.md).

<a id="s26"></a>

- [x] **S26 — Publish an independent provider API.** The existing reader exposes records, profiles, renditions, outcomes and evidence; acquisition/Parquet dependencies are optional. [Guide](installation.md).

<a id="s30"></a>

- [x] **S30 — Use the agreed shared encoding.** Supported source values remain exact; unsupported values are refused with evidence. DocSpec adoption remains separate. [Guide](decisions.md).

## Work owned by other repositories

These links require optional sibling checkouts. Follow the destination's current
acceptance criteria; updating this ledger does not complete receiving work.

<a id="s02"></a>

- **S02 → [DocSpec D08](../../DocSpec/docs/dataset-experiments-todo.md#d08):** consume source outcomes and choose partial-input policy.

<a id="s18"></a>

- **S18 → [DocSpec D52](../../DocSpec/docs/dataset-experiments-todo.md#d52):** build the captured-comment catalog adapter and example. [SpicyRegs SR02](../../spicy-regs/PLAN.md#sr02) owns the input facts and API; local source coverage remains [S09](#s09)–[S10](#s10).

<a id="s20"></a>

- **S20 → [DocSpec D20–D23](../../DocSpec/docs/dataset-experiments-todo.md#d20):** qualify execution, interruption, bounded retry and accounting.

<a id="s27"></a>

- **S27 → [DocSpec D13–D19](../../DocSpec/docs/dataset-experiments-todo.md#d13), [D38](../../DocSpec/docs/dataset-experiments-todo.md#d38):** processing/resource injection, later processing, reuse, growth and comparison.

<a id="s28"></a>

- **S28 → [DocSpec D02–D04](../../DocSpec/docs/dataset-experiments-todo.md#d02), [D19–D21](../../DocSpec/docs/dataset-experiments-todo.md#d19), [D32](../../DocSpec/docs/dataset-experiments-todo.md#d32):** configuration, stage references and local/Dagster composition.

<a id="s29"></a>

- **S29 → [DocSpec D19](../../DocSpec/docs/dataset-experiments-todo.md#d19), [D24–D29](../../DocSpec/docs/dataset-experiments-todo.md#d24):** usable retained stages, comparison, optional export and admission.

Other handoffs: [DocSpec D41–D46](../../DocSpec/docs/dataset-experiments-todo.md#d41)
for provider reuse; [SpicyRegs SR01/SR03](../../spicy-regs/PLAN.md#sr01) for selected
upstream source reuse; [Rulespec RS01–RS03](../../rulespec/TODO.md#rs01) for shared
encoding/artifact/storage operations. DocSpec D28/D31 own encoder/writer adoption.

<a id="product-ownership-to-preserve"></a>

The [ownership page](source-ownership.md) governs product boundaries. No package
merger, legacy layer or search consumer is required. Keep independent source use,
injected fetchers/processors, exact evidence and meaningful failure distinctions.

## Merged baseline and evidence

[PR #1](https://github.com/mikewolfd/spicy-docs/pull/1) merged as `3ff8011`.
Its final source qualification used `296f20d`: 802 local tests passed, two opt-in
checks were deselected; CI passed with one unavailable saved sample skipped.
The exact installed wheel passed 64 focused tests and 44 canonical cases in both
core/extras environments. Reviews and contributor simulations establish their
stated scope, not human usability, live coverage or deployment.

Retained candidate: `spicy_docs-0.2.0-py3-none-any.whl`, SHA-256
`ecaa5ebc15df7cad12952e5fdeb8e1cef71614471dfb81b5f43316049d246c4e`.
Rulespec Artifacts `1.0.12`, from `bf59d63`, SHA-256
`3f6c946c60ff2ddbe854fce7f74f4358ddb21e3ba3f6ad10caa8a0d8d59fd0a5`.
These identify the merged baseline, not a newly rebuilt wheel after later edits.

The [merged execution record](https://github.com/mikewolfd/spicy-docs/blob/3ff8011b221d4508778996c4a479c54a038f406c/docs/simplification-todo.md#execution-record)
retains per-item criteria, decisions and commit evidence. Local command receipts
remain in the originating Codex task's `validation/s19-s22-s26-s30/` directory.
That record also documents the qualified Rulespec probe and local DocSpec receiving
commit `bf38ef1`; it does not establish their later upstream state.
