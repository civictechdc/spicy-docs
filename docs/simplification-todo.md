# SpicyDocs, SpicyRegs, and DocSpec simplification to-do list

Created September 11, 2026 from the blind product-boundary review (`blind-product-boundary-review.md`), its post-review ownership discussion, the blind simplification review (`blind-simplification-review.md`), and the consolidated recommendations in this conversation. The reviewed SpicyDocs revision is `605acb4199d0b5d13cb9ec0b544ddcbb99d09873`. Recheck current sibling repositories before changing their interfaces; the reviews inspected work in progress there.

**Updated September 11, 2026 following the owner's product clarification and checklist sync.** DocSpec is an iterative dataset and catalog platform: accept sources, select documents, use injected fetchers, process now or later, reuse previous work, and compare results. SpicyRegs remains an independently usable source-data product. SpicyDocs may remain separate; share source improvements where they remove duplicate effort or improve a supported workflow. Package placement remains open and is not a prerequisite for useful integration. The prior blanket recommendation to merge SpicyDocs into DocSpec is withdrawn. The additional duplication review (`docspec-spicy-docs-duplication-review.md`) and coordination review (`docspec-spicy-docs-coordination-review.md`) supply useful findings, but their merger addenda do not define this plan.

**Progress: 6 of 25 local implementation items complete.** S02, S18, S20, and S27–S29 are moved-task references with no checkbox. All S IDs remain stable; moving a task does not complete its implementation. The completed 51-item maintainability checklist (`spicy-docs-maintainability-todo.md`) remains the record of the earlier refactor. Updating this list completes no implementation.

The intended result is reusable upstream source data and an approachable platform for dataset experiments. A user can build a catalog, fetch selected documents once, process them inline or later, change processors or reference resources, add documents, and compare reproducible results. Every useful stopping point exposes what was requested, received, accepted, rejected, and unresolved. Search is one consumer; catalog-only, acquisition-only, and later-processing workflows have independent value.

Review filenames identify artifacts retained with the original local planning session. This repository checklist includes their actionable findings and acceptance criteria; DocSpec paths identify files in that separate repository.

## Product ownership to preserve

| Component | Responsibility and user value |
| --- | --- |
| SpicyRegs | Collect and publish useful regulatory data for its own users. Adopt suitable source connectors, parsing fixes, and public-data publication improvements without depending on DocSpec's experiment lifecycle. |
| SpicyDocs | Current home of acquisition and source-release implementations under review. S25 assigns each component to SpicyRegs, a retained source package, DocSpec, or existing shared machinery based on its responsibility. A wholesale package merger is not assumed. |
| DocSpec | Build explicit catalogs from supplied sources, select and capture documents through injected fetchers, plan and track dataset work, run supplied processors, reuse valid results, compare revisions, and publish the selected stage's usable output. SpicyRegs is one input among others. |
| Dagster or another supported executor | Schedule and execute work, manage workers and execution events, and apply the agreed execution retry policy. DocSpec supplies dataset semantics, valid-reuse rules, cumulative work accounting, and completion checks. |
| Supplied processors and reference resources | Implement the experiment's analysis. A processor can use pinned RefSpec resources or another provider; DocSpec records implementation, configuration, input, and resource identities without taking ownership of their domain meaning. |

This direction matches DocSpec's recorded experimental-runner intent (DocSpec `docs/decisions/0002-shared-execution-and-the-acquisition-gap-ledger.md:28`), its fetcher interface (DocSpec `src/docspec/ports/content_fetcher.py:79`), processor interface (DocSpec `src/docspec/ports/processor.py:14`), processor-only reprocessing checks (DocSpec `tests/test_processor_reprocessing.py:114`), and Dagster adapter (DocSpec `src/docspec/adapters/dagster.py:1`). Those paths are existing implementation evidence, not proof that all experiment workflows are currently complete or qualified at scale.

## Reuse capabilities through installed wheels

Reuse works in both directions at the application boundary: DocSpec consumes source-provider APIs, while experiment callers consume DocSpec's dataset APIs. Separate repositories can share these implementations. This does not require a wholesale merger or require source users to run an experiment platform to read or publish public data. The table identifies dataset capabilities to reuse; S31 establishes which APIs already work and which need a supported package surface. DocSpec D41–D46 cover provider-wheel reuse.

| Capability owned by DocSpec | Local work to replace or avoid | Wheel-based use and acceptance | Items |
| --- | --- | --- | --- |
| Catalog building, selection, and reading | Dataset-specific catalog construction in source tools; manual transfer of profile/root/digest lists; source-side processor selection | Supply a source adapter and catalog policy to the installed builder; receive an explicit catalog reference and read it through the public API. Literal publisher fields remain source-owned. | S02, S12, S18, S26, S28, S31 |
| Generic selected-document capture and verified reuse | Bespoke download/store/resume loops in experiment tools | Inject a fetcher into DocSpec's capture operation. The fetcher supplies publisher-specific routes and checks; DocSpec retains bounded captured bytes, references, and valid reuse. | S19, S22, S26, S31 |
| Dataset planning, work accounting, and run/resume/completion operations | The applicable SpicyDocs experiment campaign driver and duplicate checkpoint/run receipts | A thin caller uses installed DocSpec operations and its supported executor adapter. Dagster handles its execution responsibilities; the caller supplies source scope and experiment configuration. | S20, S21, S28, S29, S31 |
| Processing, dependency invalidation, incremental datasets, and comparison | Per-experiment processor loops, stale-result cache logic, and ad hoc result comparisons | Supply processor implementations and pinned resources through the wheel's extension API. Retain valid captured data and unaffected results; expose comparable result revisions. | S27, S29, S31 |

DocSpec owns dataset capture and transactions. S22/D31 choose the owner of any shared physical blob writer based on independent source callers as well as dataset callers. Reuse suitable existing primitives where possible; provider storage must not acquire a DocSpec lifecycle dependency solely to remove a writer copy.

Rulespec supplies the existing shared encoding and generic artifact/atomic-publication primitives; Rulespec RS01 owns the remaining encoding decision; S30/D28 own producer/consumer adoption. Publisher parsers, source identities, and public-data transforms remain with their source owner. Keep the dependency direction explicit:

- The independent provider package uses shared primitives and remains usable without DocSpec.
- An optional DocSpec integration or a separate experiment caller uses both packages' public APIs and injects source operations and fetchers. Dataset-specific source-tool loops can move to that caller and use DocSpec's wheel.
- Check declared package dependencies as well as imports before choosing where the caller lives. Separate modules alone do not remove a circular package dependency. Resolve this in S25/S31 and D45–D46 before changing dependencies.

## How to use this list

**Tasks live where their implementation changes.** This list owns SpicyDocs
work; each affected sibling owns its own code, packaging, documentation, and
validation tasks. A dependency link or moved ID is not a second checkbox. Update
status and evidence at the destination. If ownership changes, place the task in
the selected destination before implementation.

Items have stable IDs, an owner, a beneficiary, dependencies, and completion criteria. **Change** means implementation is required. **Decision** means inspect the stated evidence, record the choice and reason, and distinguish any resulting implementation from the decision itself. **Conditional change** remains open until implemented; if its prerequisite establishes no present need, mark it deferred explicitly and report it separately from completed work.

Open checkboxes describe local work only. S25 records SpicyDocs ownership and handoffs; it does not require source code to move or make source improvements depend on the experiment platform.

Use a solutions architect subagent for ownership, format, and scope judgments. Record the agreed approach before implementing those decisions. Use independent semi-formal code reviews for the resulting changes. Commit coherent changes and update the affected checklist entries with commit IDs and validation evidence as work proceeds. Keep local validation, CI, push, and release state distinct.

Organize delivery around three user workflows, with the numbered items serving as coverage and acceptance details:

1. **Reusable source data and clear catalog inputs:** establish responsibility and interface decisions in S25 alongside S01–S04/S11, then qualify SpicyRegs and independent source inputs through S18/S26. Package moves are optional and do not gate source improvements or integration. Establish reusable public APIs and both wheel directions in S31 alongside DocSpec D41–D46. Coordinate source-format changes in S05–S10 and encoding in S30 with those owners.
2. **An iterative dataset experiment:** Follow the destination tasks linked from S02/S18/S20/S27–S29 for fetcher/processor injection, later processing, reuse, comparison, configuration, and useful stopping points; S26 supplies the independent provider API. Preserve existing working mechanisms and simplify their public use.
3. **A recoverable run with less duplicated machinery:** S20–S22 use the existing Dagster/execution boundary and consolidate only replaced mechanics. S12–S16 remove or relocate obligations after checking both upstream users and the owner's experiment requirements. S23–S24 validate the resulting workflows.

An absent current search caller does not invalidate an intended experiment capability or an upstream SpicyRegs use. Avoid speculative framework expansion, while preserving source/fetcher/processor injection, dependency tracking, selective reprocessing, and incremental datasets as core capabilities.

## Preserve the parts with demonstrated value

| Keep | Beneficiary and reason |
| --- | --- |
| Source-specific identity, scope, pagination, observation selection, and tie rules | Dataset users need the correct documents and an honest account of coverage. These rules address actual publisher behavior. |
| Exact captured evidence, member hashes and sizes, immutable publication, and logical source-state identity | Dataset builders can inspect original inputs, detect changed bytes, and distinguish changed source records from packaging changes. |
| One full producer replay and bounded consumer opening | Publication checks reconstructed output; DocSpec can then open an accepted release without replaying the whole acquisition. Preserve the distinction between integrity and publisher authenticity. |
| Source-native profiles and one shared publisher | Contributors add source knowledge without copying the release engine. A large callback list or file is not by itself a reason to replace this structure. |
| Credential scrubbing, bounded requests and memory, source refusals, and explicit failure outcomes | Operators can run acquisition without turning outages, challenge pages, or credential errors into source facts. |
| Mirrulations download and exact-object enumeration used by Regulations.gov | The current native acquisition path depends on these mechanics. Raw reading and verified publication provide different guarantees. |
| Capturing the exact public-comment table bytes used as input | Community tables can change; the native release must remain traceable to the table it actually read. This input path is distinct from optional public-table output. |
| Source adapters and injected fetchers/processors | Experiment authors can use SpicyRegs, other providers, and supplied document references without modifying DocSpec's core for each experiment. |
| Processor identities, resource/configuration pins, dependency tracking, checkpoints, and selective reuse | Users can change an experiment, rerun affected work, retain unaffected results, and explain differences without reacquiring unchanged bytes. |
| Catalog-only, acquisition-only, inline-processing, and later-processing workflows | Users can inspect a population before spending acquisition or processing resources and return to the same retained dataset later. |
| The thin Dagster integration and scheduler-neutral dataset operations | Dataset work can run with maintained execution infrastructure while DocSpec retains its domain-specific correctness rules. |

No legacy support is required. S05 removes historical acceptance behavior; active public entry points can remain useful. Retiring support does not require deleting retained datasets or adding automatic migration adapters. Additional file splits must remove a concrete maintenance burden, rather than satisfy a line-count quota.

## First: make ordinary collection understandable and remove repeated work

<a id="s01"></a>

- [x] **S01 — Expose collection outcomes through the reader and CLI.** **Change; owner: SpicyDocs; beneficiary: acquisition operators and catalog builders.** Reuse existing receipt and ledger data to expose requested scope, discovered/published/failed/discarded counts, and a bounded way to inspect failures. Explain the units and relationships between counts; discovered observations, selected records, and rejected records are not interchangeable. **Done when:** valid empty input, partial rejection, total record rejection, and ordinary success are distinguishable through supported interfaces, without inspecting internal files or building a second status store. Failure iteration and ordinary opening remain bounded. **Evidence:** product review finding 1; `releases/reader.py`, `cli/source_native.py`, `releases/publish.py`.

<a id="s02"></a>

- **S02 — Moved to [DocSpec D08](../../DocSpec/docs/dataset-experiments-todo.md#d08).**
  Carrying source outcomes and choosing partial-input policy is DocSpec work.
  SpicyDocs implements the supplying reader in S01/S26 and coverage facts in S09.
  This ID remains a dependency reference; it is not completed implementation.

<a id="s03"></a>

- [x] **S03 — Remove the default second full campaign verification.** **Change; owner: SpicyDocs; beneficiary: acquisition operators.** Keep the full staged-publication verifier mandatory. Use the existing bounded opening and expected artifact pin where a visible-destination or resume check is needed. Retain full replay as an explicit audit operation, with an independently supplied expected pin and accepted verifier identity. Simplify the extra verification subprocess, receipts, and resume states that become unnecessary. **Done when:** ordinary publication runs full replay once; interrupted runs, stale receipts, mismatched pins, and tampered destinations cannot be mistaken for completed work. Explicit audit still works. Record pass counts and any measured cost reduction without claiming unmeasured speedups. **Evidence:** simplification recommendation 1; `cli/campaign.py:252`, `releases/publish.py:328`.

<a id="s04"></a>

- [ ] **S04 — Correct SpicyDocs' product promises and workflow map.**
  **Owner: SpicyDocs; beneficiary: source users and contributors.** Explain source
  inputs, acquisition, outputs, and checks; distinguish accepted evidence from
  every response, links from captured bodies, raw/table outputs from verified
  releases, and declarations from working adapters. Preserve community-first
  supply precedence and GAO topics as literal publisher labels. **Done when:**
  source guides show actual coverage and useful source-only stopping points,
  and link to dataset workflows owned by
  [DocSpec D01/D36](../../DocSpec/docs/dataset-experiments-todo.md#d01). S25 governs
  selected local ownership; neither a merger nor a search destination is required.

## Second: simplify the current format and close evidence gaps

<a id="s05"></a>

- [ ] **S05 — Require current schemas, policies, and source receipt shapes.**
  **Owner: SpicyDocs; beneficiary: source-package maintainers.** Remove local
  historical allowlists, absent-count defaults, optional fields required only
  for legacy inputs, and obsolete producer acceptance. Agree intentional source
  format changes alongside S06–S10/S30 and qualify this repository's candidate
  wheel. **Done when:** current source writers, readers, schemas, and fixtures
  agree; required counts are present; historical inputs receive clear refusals;
  no fallback restores retired behavior. Consumer acceptance belongs to
  [DocSpec D10](../../DocSpec/docs/dataset-experiments-todo.md#d10); common encoding
  belongs to [Rulespec RS01](../../rulespec/TODO.md#rs01). Depends on S25's relevant
  interface decision, never a mandatory package move.

<a id="s06"></a>

- [ ] **S06 — Move operational byte accounting into run reporting.** **Change; owner: SpicyDocs, coordinated with DocSpec; beneficiary: operators and format maintainers. Depends on the S05 format decision.** Move read/reused/written-byte measurements and publication-size telemetry out of the source release into the existing operator result or run receipt where useful. Calculate publication size after writing. Remove the loop that rebuilds metadata until its self-reported size stabilizes and the associated admission obligations. Keep exact member sizes/hashes, source counts, scope, and evidence links. **Done when:** equivalent source content remains correctly identifiable under the declared format, storage reuse is still observable where required, and metadata construction has no self-size fixed point. Updated format documentation and focused fixtures explain the intentional change. **Evidence:** simplification recommendation 4; `releases/publish.py:396`, `releases/admission.py:241`.

<a id="s07"></a>

- [x] **S07 — Reconstruct deterministic failure provenance during full replay.** **Change; owner: SpicyDocs release verification; beneficiary: users investigating omitted records.** During the existing evidence pass, independently reconstruct rejected-record positions, identifiers, reason/class, and evidence references, then compare the failure ledger. Keep transport failures separate where retained response bytes cannot reproduce them. Avoid sharing the writer's failure-ledger construction in a way that makes the check circular. **Done when:** omitted, injected, duplicated, misclassified, or relinked failures are rejected even in an otherwise consistently resealed artifact. Genuine deterministic failures replay successfully. Ordinary reader admission gains no whole-corpus scan. **Evidence:** product review finding 2; `releases/replay.py:183`, `releases/verify.py:213`.

<a id="s08"></a>

- [ ] **S08 — Retain bounded evidence for refused responses.** **Change; owner: SpicyDocs acquisition and release code; beneficiary: operators repairing source drift.** Cover GAO identity/topic/markup failures and shared page parsing or inventory failures that currently occur before evidence persistence. Reuse the blob store and failed-run outcome to reference captured bytes; keep them separate from admitted records. Agree the smallest retention/reference design with the architect. Apply existing credential safeguards and byte bounds, and record when a bound or transport failure prevents capture. **Done when:** an operator can inspect the original refused response and diagnose these cases offline; failed runs retain discoverable evidence references; malformed pages remain refused; no second acquisition framework or valid-looking partial release is introduced. **Evidence:** product review finding 3; `sources/gao/native.py:623`, `releases/indexing.py:92`.

<a id="s09"></a>

- [ ] **S09 — Expose what each coverage claim actually establishes.** **Change; owner: SpicyDocs; beneficiary: dataset users assessing omissions. Depends on S01 and the relevant S25 interface decision.** Carry exact selectors, discovery rules, and material assumptions alongside broad scope labels. Distinguish Federal Register's stable observed crawls, GAO's explicit requested IDs, and Mirrulations' live listing with individually pinned objects. Identify requested, unrequested, observed-empty, rejected, and unresolved outcomes where evidence supports those distinctions. **Done when:** supported source APIs and examples explain each source's coverage without implying one frozen publisher-wide instant or treating a transport error as source absence. Reuse existing scope/policy declarations where possible. [DocSpec D08](../../DocSpec/docs/dataset-experiments-todo.md#d08) consumes these facts; implementing the provider does not depend on its consumer. **Evidence:** product review finding 4.

<a id="s10"></a>

- [ ] **S10 — Make public-comment completeness match its discovery evidence.** **Change with architecture decision; owner: SpicyDocs; beneficiary: public-comment dataset users. Depends on S09 and the S05 format decision.** The current first-missing-part rule establishes discovery under a contiguous-name assumption. Prefer an observation-level claim unless a named consumer needs complete membership and a publisher inventory/version can establish it. Do not invent an endless search for later part numbers to preserve the old label. **Done when:** the profile, executable checks, downstream description, and guide agree; retained cases cover the first missing part, gaps, empty input, and request failures. If authoritative inventory is adopted, membership is checked against that inventory. **Evidence:** product review finding 4; `sources/public_comments/profile.py:20`, `sources/public_comments/native.py:785`.

## Third: place source capabilities with their users and remove unused obligations

<a id="s11"></a>

- [x] **S11 — Inventory SpicyDocs users and repeated source work.**
  **Decision; owner: SpicyDocs; beneficiary: source contributors and experiment authors.**
  Inspect local auxiliary catalogs, tables/Iceberg, CourtListener, drift tools,
  imports, and extension points against actual sibling callers and intended
  workflows. Distinguish runtime, operational, test, and stated product use.
  **Done when:** each local candidate has evidence, a beneficiary, removal
  consequence, and KEEP/MOVE/DELETE/DEFER disposition. Any destination change
  has its own local task before implementation. Counterpart inventories are
  [DocSpec D41](../../DocSpec/docs/dataset-experiments-todo.md#d41) and
  [SpicyRegs SR01](../../spicy-regs/PLAN.md#sr01). Missing search callers alone do
  not justify removing useful source capabilities or intended injection/reuse.

<a id="s12"></a>

- [ ] **S12 — Remove unused local catalogs and misplaced policy declarations.**
  **Owner: SpicyDocs; beneficiary: source contributors and experiment authors.**
  After S11/S25's relevant decisions, retire unused `allowed_schemes`, processor/
  region selections, stage flags, generators, commands, custom seals, outputs,
  and maintenance gates together. Preserve faithful fields, identities, access
  evidence, and native vocabulary relationships. **Done when:** each retained
  local declaration has a source responsibility and supported use; selected
  removals leave source publication usable. Active experiment configuration is
  owned by [DocSpec D32/D34](../../DocSpec/docs/dataset-experiments-todo.md#d32);
  any selected Search recipe policy belongs to [SC04](../../spicysearch/PLAN.md#sc04).
  Add a destination task before moving a rule to any other processor. Source
  removal alone does not complete that consumer's adoption.

<a id="s13"></a>

- [x] **S13 — Resolve SpicyDocs' public-table and Iceberg surfaces.**
  **Decision and selected local changes; owner: SpicyDocs; beneficiary: source-data users.**
  Compare local outputs with SpicyRegs' actual publishing workflow before
  retaining, sharing, or retiring them. Keep public-table output distinct from
  consuming captured table bytes as input. **Done when:** each local surface has
  a supported use and disposition, and selected local changes include package
  dependencies, tests, and accurate data guarantees. SpicyRegs assessment and
  adoption live in [SR01](../../spicy-regs/PLAN.md#sr01) and
  [SR03](../../spicy-regs/PLAN.md#sr03). Retire local copies only after selected
  consumers switch; retaining SpicyDocs separately is valid. Depends on S11/S25's
  relevant decisions; DocSpec use is not required to justify source publication.

<a id="s14"></a>

- [ ] **S14 — Expose one retained CourtListener publisher parser.**
  **Decision and selected local changes; owner: SpicyDocs; beneficiary: bulk-data users.**
  Check local and upstream use against S11/S25. If retained, expose strict pure
  listing/filename parsing with source-owned live acquisition. Preserve ETags,
  required size/date fields, bounds, duplicate-key checks, and refusal of truncated
  pages without continuation. **Done when:** the public parser represents publisher
  facts faithfully and replaced local grammar/tests/dependencies are removed.
  Captured-input admission and selection stay in
  [DocSpec D31/D42](../../DocSpec/docs/dataset-experiments-todo.md#d31); selected
  SpicyRegs adoption is [SR03](../../spicy-regs/PLAN.md#sr03). If no supported use
  remains, document and implement local retirement. Preserve Mirrulations mechanics
  used by Regulations.gov.

<a id="s15"></a>

- [x] **S15 — Keep local documented-value diagnostics proportionate to use.**
  **Decision and selected local changes; owner: SpicyDocs; beneficiary: source maintainers.**
  Identify who uses the diagnostic to compare observed values with publisher
  documentation, including SpicyRegs maintenance. Keep exact strings, pinned
  inputs, and undocumented/unobserved distinctions where useful. **Done when:**
  the local command, owner, refresh process, and KEEP/SHARE/REMOVE/DEFER decision
  are explicit; selected changes reduce unused obligations without claiming
  complete publisher coverage or runtime enforcement. SpicyRegs adoption, if
  selected, lives in [SR03](../../spicy-regs/PLAN.md#sr03). Missing DocSpec runtime
  calls do not invalidate a useful source-quality tool. Depends on S11.

<a id="s16"></a>

- [ ] **S16 — Remove superseded SpicyDocs code and dependencies.**
  **Owner: SpicyDocs; beneficiary: contributors and package consumers.** After
  S12–S15/S25 decisions and selected replacements, recheck callers and delete
  local dead helpers, old commands, replaced parsers/encoders, unused extras,
  and stale links. Preserve required source-only APIs and injection points.
  **Done when:** local retained APIs have clear responsibilities, optional
  dependencies load only when needed, and clean installs cover supported source
  users. File length prompts an ownership review rather than a quota. Counterpart
  removal lives in [DocSpec D34](../../DocSpec/docs/dataset-experiments-todo.md#d34)
  and [SpicyRegs SR03](../../spicy-regs/PLAN.md#sr03).

## Fourth: connect source and experiment workflows and consolidate repeated mechanics

<a id="s17"></a>

- [ ] **S17 — Supply faithful GAO topics and retained example evidence.**
  **Owner: SpicyDocs; beneficiary: dataset users selecting GAO material.** Expose
  the literal publisher topic and required byte/evidence references through the
  supported source API. Keep a small retained fixture with matching, missing,
  and unexpected topic cases. **Done when:** fields preserve exact publisher
  values and provenance, missing topics remain explicit, and no inferred
  requirements are introduced. Add only source fields/byte access required by
  [DocSpec D51](../../DocSpec/docs/dataset-experiments-todo.md#d51), which owns the
  catalog/filter/processor example. Depends on S01/S09/S26; search is optional.

<a id="s18"></a>

- **S18 — Moved to [DocSpec D52](../../DocSpec/docs/dataset-experiments-todo.md#d52).**
  The retained public-comment catalog adapter and example belong to DocSpec.
  Public table facts/API work belongs to [SpicyRegs SR02](../../spicy-regs/PLAN.md#sr02);
  applicable SpicyDocs coverage work remains S09–S10. This is a dependency reference.

<a id="s19"></a>

- [ ] **S19 — Package publisher-specific acquisition and identity checks.**
  **Owner: SpicyDocs; beneficiary: consumers fetching the intended document.**
  Expose existing Federal Register locators, soft-404/printed-marker checks, and
  MODS resolution through a bounded public provider API where the selected route
  needs them. **Done when:** explicit request/retry/byte bounds, wrong-document
  refusal, and original/resolved identities are preserved in the installed wheel;
  standalone source use remains possible. Reuse generic HTTP/storage mechanics
  and avoid a mandatory second download. DocSpec owns candidate preference and
  the injected adapter in [D11/D12](../../DocSpec/docs/dataset-experiments-todo.md#d11)
  and [D44](../../DocSpec/docs/dataset-experiments-todo.md#d44). Depends on S25/S26's
  relevant interface decisions, not relocation to SpicyRegs.

<a id="s20"></a>

- **S20 — Moved to [DocSpec D21](../../DocSpec/docs/dataset-experiments-todo.md#d21).**
  DocSpec owns the representative Dagster integration, with interruption in
  [D20](../../DocSpec/docs/dataset-experiments-todo.md#d20), bounded retry/accounting
  in [D23](../../DocSpec/docs/dataset-experiments-todo.md#d23), and any minimal
  acquisition task adaptation in [D22](../../DocSpec/docs/dataset-experiments-todo.md#d22).
  SpicyDocs supplies bounded source operations; S21 owns its local caller retirement.

<a id="s21"></a>

- [ ] **S21 — Retire the SpicyDocs experiment campaign after replacement.**
  **Conditional change; owner: SpicyDocs; beneficiary: operators and maintainers.**
  Once [DocSpec D22](../../DocSpec/docs/dataset-experiments-todo.md#d22) qualifies
  the selected workflow, switch this repository's caller and remove replaced
  pools, retry/run policy, receipts, locking, and recovery branches. Keep useful
  diagnostics and source acquisition functions. **Done when:** the local caller
  has one execution owner, recovery works, and removed code has no required users.
  Assess independent source publishing separately; it remains usable without
  DocSpec. Depends on S25's relevant decision and the accepted destination
  evidence; if replacement adds no value, defer with the reason.

<a id="s22"></a>

- [ ] **S22 — Adopt the chosen shared physical writer in SpicyDocs.**
  **Conditional change; owner: SpicyDocs; beneficiary: source operators and maintainers.**
  Supply known-digest, early reuse, directory pinning, no-follow, cleanup, and
  durability requirements to [Rulespec RS03](../../rulespec/TODO.md#rs03)'s
  suitability/ownership review. Compare them with DocSpec's unknown-digest and
  hard streaming-bound needs. **Done when:** this repository uses the agreed
  bounded operation, local race/corruption/bound checks pass, and its replaced
  physical writer is removed. Keep source references and result meaning here;
  provider storage must not depend on DocSpec's lifecycle. DocSpec's caller and
  transactions belong to [D31](../../DocSpec/docs/dataset-experiments-todo.md#d31).
  Record any differently selected implementation in that destination's backlog
  before work starts. If sharing adds no value, defer explicitly; no storage
  platform or package move is required.

## Finish: prove the simpler product and make its status reviewable

<a id="s23"></a>

- [ ] **S23 — Qualify SpicyDocs' documentation and installed package.**
  **Owner: SpicyDocs; beneficiary: source contributors and consumers.** Update
  local specs, source guides, public API docs, CLI help, ownership maps, and
  examples as local changes land. Build the current candidate wheel and check
  its exact bytes outside source checkouts. **Done when:** clean source-only
  setup, publication/reading, and selected public capabilities work as documented;
  schemas/resources are packaged; useful regression/refusal checks remain.
  Coordinate consumer requirements without maintaining their test suites here:
  [DocSpec D10/D46](../../DocSpec/docs/dataset-experiments-todo.md#d10),
  [SpicyRegs SR03](../../spicy-regs/PLAN.md#sr03). Existing green checks do not
  qualify changed producer bytes. Report local validation, CI, and release separately.

<a id="s24"></a>

- [ ] **S24 — Independently review SpicyDocs changes and source-user value.**
  **Owner: SpicyDocs; beneficiary: source users and contributors.** Obtain
  independent semi-formal code review and architecture advice for local judgment
  calls. Give a fresh source-contributor persona the supported instructions and
  verify that an acquisition/publication change is understandable without running
  DocSpec. **Done when:** findings have explicit resolutions and selected source
  workflows retain evidence with fewer steps or duplicate implementations.
  Record commits, checks, deferred work, and publication state separately.
  DocSpec's experiment demonstration/reviews live in
  [D38–D39](../../DocSpec/docs/dataset-experiments-todo.md#d38); simulated personas
  do not complete [D40](../../DocSpec/docs/dataset-experiments-todo.md#d40)'s human exercise.
  Depends on applicable S23 checks.

## Additional ownership and experiment requirements

S25–S31 retain their original IDs. Open checkboxes now cover SpicyDocs implementation; moved items point to their destination. The delivery order places relevant ownership and interface decisions early.

<a id="s25"></a>

- [ ] **S25 — Assign SpicyDocs responsibilities and implement local handoffs.**
  **Decision and selected changes; owner: SpicyDocs; beneficiary: source users and contributors.**
  Use S11's inventory to identify repeated source rules, table publication,
  evidence, diagnostics, storage, and experiment loops. **Done when:** the local
  component map records selected implementations, public capabilities, and copies
  to remove, and selected SpicyDocs handoffs are validated. Keep SpicyDocs
  independently usable; retaining this package is valid and a SpicyRegs move is
  optional. Receiver work belongs to [SpicyRegs SR01/SR03](../../spicy-regs/PLAN.md#sr01),
  [DocSpec D41–D46](../../DocSpec/docs/dataset-experiments-todo.md#d41), or
  [Rulespec RS02–RS03](../../rulespec/TODO.md#rs02), as selected. Remove local
  copies after their consumers switch. Dependencies require the relevant decision,
  not every handoff. Deferred moves are not completed changes; keep prepared,
  committed, and accepted-upstream status separate.

<a id="s26"></a>

- [ ] **S26 — Publish the independent source-provider API through its wheel.**
  **Owner: SpicyDocs; beneficiary: catalog builders and source users.** Expose
  profiles, stable source descriptions, faithful fields, provenance, records,
  candidate renditions, scope/outcomes, and bounded evidence/failure inspection
  through the existing public source API. Combine S01/S19 capabilities without
  inventing a second reader. Keep full replay with the producer and ordinary
  opening bounded. **Done when:** the exact candidate wheel includes required
  schemas/resources and supports these imports without sibling paths or DocSpec;
  optional acquisition/analytics dependencies are proportionate. Record version,
  revision, and wheel digest separately from dataset pins. Source choice and
  fetcher choice remain independent. DocSpec implements intake/injection in
  [D06/D11](../../DocSpec/docs/dataset-experiments-todo.md#d06) and provider
  integration in [D43–D46](../../DocSpec/docs/dataset-experiments-todo.md#d43);
  supplied local records need not become SpicyDocs bundles.

<a id="s27"></a>

- **S27 — Moved to [DocSpec D13–D19](../../DocSpec/docs/dataset-experiments-todo.md#d13)
  and [D38](../../DocSpec/docs/dataset-experiments-todo.md#d38).** Processor/resource
  injection, inline/later processing, selective dependent reuse, dataset growth,
  and revision comparison are owned and qualified in DocSpec. No source-package
  processing loop is assigned here.

<a id="s28"></a>

- **S28 — Moved to [DocSpec D02–D04](../../DocSpec/docs/dataset-experiments-todo.md#d02),
  [D19–D21](../../DocSpec/docs/dataset-experiments-todo.md#d19), and
  [D32](../../DocSpec/docs/dataset-experiments-todo.md#d32).** Simple experiment
  configuration, supported stage references, and local/Dagster composition belong
  to DocSpec. This is a dependency reference.

<a id="s29"></a>

- **S29 — Moved to [DocSpec D19](../../DocSpec/docs/dataset-experiments-todo.md#d19)
  and [D24–D29](../../DocSpec/docs/dataset-experiments-todo.md#d24).** Usable retained
  stages, revision comparison, optional portable export, and consumer admission
  are DocSpec work. Catalog-only and acquisition-only use retain independent value;
  a retained attempt may include failures that prevent serving admission.

<a id="s30"></a>

- [ ] **S30 — Adopt the agreed shared encoding in source production.**
  **Owner: SpicyDocs; beneficiary: consumers relying on exact stable source identities.**
  Supply required source-value cases to [Rulespec RS01](../../rulespec/TODO.md#rs01),
  which owns the supported-value decision and shared emitter. **Done when:** local
  producers/readers use the agreed shared implementation, exact values survive,
  and relevant Unicode/duplicate-key/number-boundary cases pass through the
  current candidate wheel. Update source format identities and S05 checks only
  where the agreed behavior changes; remove any replaced local emission code
  without a compatibility mode. DocSpec adoption lives in
  [D28](../../DocSpec/docs/dataset-experiments-todo.md#d28). Unresolved convergence
  remains an explicit deferral; do not round or indiscriminately stringify values.

<a id="s31"></a>

- [ ] **S31 — Replace SpicyDocs' selected dataset loops with DocSpec wheel calls.**
  **Conditional change; owner: SpicyDocs; beneficiary: experiment-tool maintainers.**
  Identify local callers using dataset capabilities and replace their catalog,
  capture/reuse, processing, or run/resume loops with public operations published
  by [DocSpec D04/D45](../../DocSpec/docs/dataset-experiments-todo.md#d04). Keep
  composition separate from the independent provider package; check declared
  dependencies as well as imports. **Done when:** the selected local caller uses
  exact installed wheel bytes, preserves source/fetcher/processor injection, and
  removes its obsolete loops after relevant parity checks. No private imports,
  sibling paths, vendored source copies, or package cycle remain. If composition
  moves to DocSpec instead, link its destination task and retire only replaced
  local code here. Source-only users remain independent. Record package versions,
  wheel/revision pins, local checks, and deferred capabilities; provider packaging
  is S26, and DocSpec's public API/qualification work is D45–D46.

## Destination-owned implementation tasks

The former reciprocal mapping table is replaced by destination links. Splitting
an effort gives each repository a concrete local obligation; it does not create
another copy of the whole feature or imply any implementation is complete.

| Destination | Authoritative work referenced by this checklist |
| --- | --- |
| [DocSpec checklist](../../DocSpec/docs/dataset-experiments-todo.md) | D08 owns source-outcome consumption (S02); D21 owns Dagster (S20); D13–D19/D38 own iterative processing (S27); D02–D04 own configuration (S28); D24–D29 own retained stages/export (S29); D45 owns public wheel packaging; D51–D52 own GAO/comment examples (S17–S18). |
| [SpicyRegs plan](../../spicy-regs/PLAN.md#sr01) | SR01 reviews local source overlap; SR02 supplies retained public-comment input facts/APIs; SR03 implements only selected local improvements and handoffs. A repository move stays optional. |
| [Rulespec backlog](../../rulespec/TODO.md#rs01) | RS01 owns shared encoding; RS02 assesses needed generic artifact capabilities; RS03 assesses physical writer suitability. S30/S22 own SpicyDocs adoption. |
| [SpicySearch plan](../../spicysearch/PLAN.md#sc01) | SC01–SC05 own Search reader adoption, schema-helper reuse, shared definitions, optional recipe composition, and Search parity/removal. |
| [SpicyEngine plan](../../spicyengine/PLAN.md#ec01) | EC01–EC03 own Engine definition adoption, output admission, and native-only rebuilding. |

Search retains its transformations and semantic producer identity. DocSpec's
D48–D50 provide generic dataset execution and its qualification; Engine retains
native indexing and serving. Optional search integration does not gate source-only
use, ordinary document experiments, or DocSpec's Dagster example. Consuming an
unchanged RefSpec resource package assigns no implementation work to RefSpec.

## Finding coverage

| Review finding or recommendation | Addressed by |
| --- | --- |
| Outcomes absent from normal reader/CLI and DocSpec handoff | S01, S02 |
| Failure provenance receives weaker verification than successful records | S07 |
| Page/GAO rejection can precede evidence retention | S08 |
| Coverage labels hide different proof and discovery assumptions | S09, S10 |
| GAO and captured-comment dataset use needs a supported example | S17, S18, S26 |
| Product promise overstates preservation, document capture, interpretation, or readiness | S04, S23 |
| Repeated full campaign verification and self-derived verifier acceptance | S03 |
| Historical schema, policy, receipt, and producer acceptance | S05 |
| Self-referential sealed storage telemetry | S06 |
| Unconsumed catalog artifacts, bespoke sealing, and downstream policy in source declarations | S11, S12, S16 |
| Public-table/Iceberg and CourtListener value must include upstream SpicyRegs use | S11, S13, S14, S25 |
| Drift diagnostics and extra maintenance obligations need a real use | S11, S15 |
| Supported imports, optional dependencies, long files, and source-profile complexity | Preserve table, S16, S23 |
| Selected body acquisition has an unclear current/proposed owner | S19 |
| Duplicate campaign execution and the unfinished DocSpec replacement | S20, S21 |
| Duplicate physical writers need a bounded design with the correct source/platform owner | S22, S25 |
| Keep evidence/identity/source rules, distinct raw/native/table guarantees, and bounded operation | Preserve table, acceptance criteria throughout, S23, S24 |
| Claimed simplification and integration value needs evidence for both source users and experiments | S11, S17–S29 |
| Blanket package-merger recommendation conflicts with intended upstream ownership | Product ownership table, S11, S25 |
| Source products should share useful improvements without a required repository move | S13–S16, S25 |
| Catalog inputs and fetchers must be supplied independently of SpicyRegs | S02, S19, S26 |
| Inline/later processing, changing processors/resources, and incremental growth are core capabilities | Preserve table, S27 |
| Dagster should own execution machinery while DocSpec owns dataset meaning and reuse | S20, S21, S28 |
| Catalog-only and retained-document workflows need useful completion, comparison, and later reuse | S04, S18, S28, S29 |
| Fixed setup ceremony and manually transferred stage references obscure the experiment workflow | S28 |
| Distinct document-release representations need one supported completion path | S23, S29 |
| Canonical encoders differ, and admitted large-integer behavior is not itself a product requirement | S05, S30 |
| Current package interoperability must use current candidate bytes | S23 |
| DocSpec-owned capabilities should replace local copies through an installed wheel | Wheel ownership map, S22, S25, S31 |
| Wheel reuse must preserve public APIs, lightweight composition, and acyclic dependencies | Product ownership and wheel maps, S16, S23, S31 |

## Execution record

**September 11, 2026 — planning revision only.** Updated S01–S24's governing scope and 17 individual items after the owner clarified DocSpec's experiment-platform purpose and SpicyRegs' independent role. Added S25–S30 for component destinations/upstream work, source/fetcher injection, iterative processing and dataset growth, configuration, stage completion/comparison, and shared encoding. Added S31 and a capability map for moving DocSpec-owned work behind supported wheel APIs and removing local copies. Rejected the blanket package-merger assumption and strengthened Dagster, processor/reuse, source-only, and package-dependency acceptance. All implementation items remain open.

**September 11, 2026 — reciprocal checklist sync, planning only.** Aligned this canonical repository checklist with DocSpec's 50-item plan. Added shared ID mappings and reconciled open package placement, both wheel directions, independent source storage, the encoding decision, optional export, and conditional search integration. S25 no longer requires a SpicyRegs move or patch as a prerequisite for unrelated work. No implementation checkbox changed; source-side acceptance remains here and DocSpec implementation detail remains in its checklist.

**September 11, 2026 — destination ownership correction, planning only.** Split shared work into local tasks in DocSpec, SpicyDocs, SpicyRegs, Rulespec, SpicySearch, and SpicyEngine. Replaced six source-side descriptions of DocSpec work with moved-ID links; narrowed remaining checkboxes to this repository's work. DocSpec D51–D52 now own the named GAO/comment examples. The 25 remaining local checkboxes are open; no implementation was completed or dropped by this routing change.

Append concise implementation entries as work proceeds: item IDs, agreed decision, changed repositories, commit IDs, focused validation, upstream status, and remaining dependencies. Decisions to defer optional features need a beneficiary and revisit condition; they do not count as delivered implementation. The owner's stated experiment capabilities and SpicyRegs uses are requirements, not speculative features to remove solely because today's search pipeline does not exercise them.


**September 11, 2026 — S07 complete; S11 inventory agreed.** Commit `1e661ed`
reconstructs rejected record positions and exact failure/evidence references during
producer replay. It removes the weaker shape-only ledger path while preserving
bounded-memory admission and full producer verification. The focused failure and
publication checks passed (43 tests); the broader source/release checks passed
before redundant fixture-test removal (169 tests, one excluded live case).
Nine adversarial cases fail against the original `c9da196` verifier and pass
against the changed implementation. Focused Ruff and type checks passed.
Independent semi-formal review found no blocking issue.

The [source ownership inventory](source-ownership.md) completes S11's decision
work: keep independent source publication, remove unused generated policy and
Iceberg attachment machinery, share the strict source parser through its wheel,
and qualify shared storage before replacing callers. S25 handoffs and every
selected removal remain open; this decision does not claim consumer adoption.


**September 11, 2026 — S01 and S13 complete.** Commit `6341d04` adds the
collection outcome API and `inspect`, with bounded failure iteration and the same
scope/count mapping on publish/verify. The local source/CLI checks passed
(58 tests); Ruff and formatting checks passed. Independent review corrected the
count wording: included-page observations can fail scope validation, so
`discoveredRecordCount` must not claim every observation was in scope.

Commit `5f09f1b` removes the unused Iceberg attachment helper, public exports,
and URI plumbing while retaining immutable Parquet publication and DuckDB reads.
The table input protocol now accepts read-only source facts. The retained local
table checks passed (22 tests; one environment-sensitive HTTP range case excluded);
focused types, Ruff, and formatting passed. Independent review approved both
changes after the documentation fixes. Architecture/inventory commit `fe541c9`
records the S11 decision. Review reports are retained in the local planning
session as `s01-outcomes-review.md`, `s13-iceberg-retirement-review.md`, and
`s07-failure-provenance-review.md`. No consumer adoption or remote publication is
claimed by these local changes.

**September 11, 2026 — S03 and S15 complete.** Commit `ee991d7` removes
the campaign's automatic second full replay and separate verification receipts.
New and resumed releases use interruptible inspection with independently supplied
verifier acceptance, the retained expected pin, requested scope, and exact
collection outcomes. Tests count one mandatory replay per publication and check
explicit audit, corruption, stale receipts, retries, and interruption, including
the gap between launching a child and registering it. The 43 campaign tests,
focused Ruff, formatting, and type checks passed. Independent review approved
the final patch after cancellation, outcome matching, and malformed-log fixes.
Admission still hashes all retained payloads; no runtime speedup is claimed.

Commit `aba1031` keeps documented-value drift as an optional offline diagnostic
owned by source maintainers, documents its refresh process and limits, and
removes an empty skipped test. Both local Parquet queries bind paths as data;
the connection closes on errors as well as success. The 30 diagnostic tests and
focused Ruff, formatting, and type checks passed. Independent review approved
the changes. SpicyRegs adoption remains conditional on a named maintenance user.

The combined repository check, `./scripts/check`, passed after both changes:
locked dependency sync, Ruff, formatting, and **559 tests passed; two integration
cases deselected by the default configuration**. This is local validation;
remote CI, pushing these commits, and wheel qualification are not claimed.
The independent reports remain in the local planning session as
`implementation-review-s03.md` and `s15-drift-diagnostic-review.md`.
