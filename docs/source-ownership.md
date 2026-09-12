# Source ownership and reuse decisions

Keep SpicyDocs as an independent source provider. The unused catalog machinery
and Iceberg attachment helper are retired; source parsing is available through its wheel.
DocSpec owns dataset selection, capture, processing, reuse, and experiment runs.
SpicyRegs owns its independently useful public-data pipeline. Rulespec is the
selected candidate for shared physical storage operations, subject to its writer
qualification.

This is the [S11 inventory](simplification-todo.md#s11) and the decision input for
[S25 handoffs](simplification-todo.md#s25). **The inventory is complete; this
record does not complete any adoption, retirement, package qualification, or
upstream submission.** The coordinating agent and architecture reviewer agreed
on these dispositions on September 11, 2026. Package moves are optional; no
legacy compatibility layer or repository merger is required.

## Evidence and decision frame

The review inspected local code, documentation, package declarations, tests,
commands, and workflows in SpicyDocs, DocSpec, SpicyRegs, Rulespec, SpicySearch,
and RefSpec. It searched exact module/API names and generated artifact names
across those checkouts. A missing reference means none was found in that scope;
it does not prove that no external user exists. Documented source use and the
owner's intended experiment capabilities count independently of current search
consumption.

Baseline revisions were SpicyDocs `c9da196a85969345d45cf0c0bacaf4466b8ed669`,
DocSpec `41a6b144c06c08ebaf8f57e9c7fe4c6927dff11f`, SpicyRegs
`1880517202ccc80e31bc8072dd21965e90253646`, and Rulespec
`25ea30056f1a20bff893738d8a297420a05cdf2e`. SpicyDocs implementation and DocSpec
configuration work were changing during review. Citations identify the inspected
implementation, not a claim that those entire working trees were committed or
qualified. No live publisher or deployed service was tested.

| Prior decision or interface | Relationship to this decision |
| --- | --- |
| [SpicyDocs acquisition rules](../AGENTS.md) and [product ownership](simplification-todo.md#product-ownership-to-preserve) | Source refusals, evidence, independent source users, and the owner's clarified responsibilities govern simplification. |
| [DocSpec decision 0002:28](../../DocSpec/docs/decisions/0002-shared-execution-and-the-acquisition-gap-ledger.md#what-docspec-is-for) | Dataset experiments require injected sources, later processing, incremental growth, and reuse. These are requirements, not disposable complexity. |
| [SpicyRegs plan: source-provider work](../../spicy-regs/PLAN.md#source-provider-work-for-dataset-experiments) | Source publication remains independent. SR01/SR03 own selected upstream reuse; a local decision is not upstream acceptance. |
| [Existing maintenance decisions](maintenance-decisions.md#supported-entry-points) | Public entry points remain discoverable with one implementation. This review refines the earlier blanket retention of auxiliary source-profile declarations. |
| [Rulespec RS03](../../rulespec/TODO.md#rs03) | Shared storage must satisfy both independent source and dataset callers before either writer is replaced. |

## Component inventory and selected dispositions

“Runtime” means executable application calls; “operational” means a documented
operator command or workflow; “test” and “research” do not establish deployment.
The detailed traces below distinguish existing callers from proposed consumers.

| Component | Actual or required user and present callers | Decision, owner, and removal consequence |
| --- | --- | --- |
| Native release profiles, publisher, reader, evidence and failure APIs | Source operators use `cli/source_native.py`; DocSpec uses `SpicyDocsSourceNativeAdapter`. Injected source profiles and bounded readers support both source-only and dataset work. [Trace A](#a-source-operations-and-public-interfaces) | **KEEP**, SpicyDocs. Removing them breaks native publication and DocSpec source intake. Extend the existing API in S01/S19/S26 instead of creating another reader. |
| Auxiliary generated profile/applicability catalogs | The retired repository generator, installed builder, and fixture tests regenerated the outputs. No production reader was found in the checked siblings. [Trace B](#b-auxiliary-catalogs-and-misplaced-policy) | **RETIRED in S12** with the entire unused catalog package. [Source-reference notes](source-reference.md) preserve reviewed relationships and limitations; current native profiles retain executable source descriptions. |
| Source table declarations mixed with processing policy | The retired builder read `allowed_schemes`, processing mode, region adapter, and step flags. The historical Rulespec probe read `declared_profile_for_table`; source acquisition uses native profiles. [Trace B](#b-auxiliary-catalogs-and-misplaced-policy) | **RETIRED in S12**: no shadow table dictionary replaces it. Existing native profiles and SpicyRegs producers describe actual data. A current Rulespec probe replaces the lookup without rewriting historical evidence. DocSpec D32/D34 and optional Search SC04 own experiment/recipe policy. |
| Immutable public Parquet output | Documented publish/verify commands and public library API; tests exercise native-to-table conversion. No sibling runtime import found. Source users can inspect a bounded immutable generation without DocSpec. [Trace C](#c-public-tables-and-iceberg) | **KEEP**, SpicyDocs S13. Removal would delete a supported source output. SpicyRegs may reuse suitable source transforms under SR03, but its mutable ETL is not replaced by this publisher. |
| First-snapshot Iceberg attachment helper | Public export and one fake-table test; no operational caller or distinct required current workflow found. [Trace C](#c-public-tables-and-iceberg) | **DELETE**, SpicyDocs S13/S16. Remove the helper/export and now-unused location plumbing after checking the retained Parquet reader. No real integration is qualified by its protocol test. Reintroduce only for a concrete immutable-generation consumer. |
| CourtListener listing, filename grammar, and raw streaming reader | SpicyDocs documented library use and tests; SpicyRegs independently calls its copied reader from court-scope, opinion-cluster and opinion-body builders. DocSpec's captured-listing tool owns a stricter duplicate parser. [Trace D](#d-courtlistener) | **KEEP/SHARE**, SpicyDocs S14/S26 owns the strict public source parser and live reader. DocSpec D42 and selected SpicyRegs SR03 callers consume its wheel before removing replaced copies. Domain transforms and dataset admission stay with their present owners. |
| Documented-value drift diagnostic | Repository command and fixture tests compare retained SpicyRegs table observations with retained publisher documentation. No live-source or sibling runtime caller found. [Trace E](#e-documented-value-drift) | **KEEP**, SpicyDocs S15 as explicit source-maintainer tooling. Removing it loses a checked explanation of documented/observed differences. **DEFER** upstream adoption until SR01/SR03 selects a maintenance caller; do not make it a DocSpec or publication gate. |
| Agency campaign driver | Documented `python -m spicy_docs.cli.campaign` publishes source releases with subprocesses, receipts, locking and recovery. DocSpec's task runner is a sibling capability, not a qualified replacement for this workflow. [Trace F](#f-campaigns-and-experiment-execution) | **KEEP pending replacement**; S03 removes repeated verification now. **DEFER retirement**, S21/S31, until DocSpec D22 qualifies the selected workflow. Then remove only replaced execution machinery. Independent source publication remains supported. |
| Local physical blob writer | Native CLI/replay use `LocalSourceNativeBlobStore`; publication calls `put_blob`. DocSpec request composition creates its separate `LocalContentAddressedBlobStore`. [Trace G](#g-physical-storage-and-shared-primitives) | **SHARE after qualification**, candidate owner Rulespec RS03, adopters S22/DocSpec D31. Retain both working writers until the common operation preserves their different requirements. Moving provider storage into DocSpec would add the wrong lifecycle dependency. |
| Dataset catalog/capture/processing/run APIs | DocSpec source intake, fetcher and processor interfaces, execution services and optional Dagster adapter implement these concerns. Required future callers include independent source inputs and iterative experiments. [Trace F](#f-campaigns-and-experiment-execution) | **KEEP**, DocSpec; **MOVE selected composition** from SpicyDocs only when D45/D46 provides supported wheel APIs and S31 identifies the replaced local loop. Do not move publisher identity or source-data transforms with it. |

## Traces and repeated work

### A. Source operations and public interfaces

The native CLI composes source registrations with one publisher
([`cli/source_native.py:126`](../src/spicy_docs/cli/source_native.py#L126),
[`cli/sources.py:117`](../src/spicy_docs/cli/sources.py#L117)). DocSpec resolves
SpicyDocs modules lazily, opens the public reader, and streams records/renditions
([`spicy_docs_source_native.py:31`](../../DocSpec/src/docspec/adapters/spicy_docs_source_native.py#L31),
[`:71`](../../DocSpec/src/docspec/adapters/spicy_docs_source_native.py#L71)).
That adapter is a current runtime caller; package interoperability still needs
current-wheel qualification in S23/S26 and D46.

Source transport and source identity have distinct responsibilities. Regulations.gov
captures source objects into bounded evidence pages
([`acquisition.py:42`](../src/spicy_docs/sources/regulations_gov/acquisition.py#L42));
public-comment input captures exact upstream Parquet bytes before interpretation
([`public_comments/native.py:1`](../src/spicy_docs/sources/public_comments/native.py#L1)).
Neither is the optional public-table output described below. Federal Register
body helpers preserve printed-marker and MODS identity checks but currently make
no requests ([`body_sources.py:1`](../src/spicy_docs/sources/federal_register/body_sources.py#L1));
S19/D44 must join those checks to selected bounded acquisition without a second
unnecessary download.

Reader imports are deliberately tested without eager HTTP/S3/analytics imports
([`test_reader_closure.py`](../tests/test_reader_closure.py)). Version `0.2.0`
also separates installation: Rulespec Artifacts and jsonschema form the core,
`acquisition` supplies HTTP/S3 clients, and `public-table` supplies Parquet
parsing and publication. See [installation choices](installation.md). The
intermediate core and extras wheels passed isolated installation checks; S26
still requires qualification of the final combined candidate.

### Current campaign and dataset callers

The September 11 caller audit at SpicyDocs `49c1eec` and committed DocSpec
`99849b2` found no local dataset loop to replace with DocSpec's wheel. The agency
campaign publishes docket/document source releases, checks admitted releases,
and retains external attempt receipts. CRS summaries and the GovInfo/source
census tools perform source acquisition or diagnostics. The offline GAO example
demonstrates source publication and evidence access. None constructs a dataset
catalog or runs selected-document processors. The obsolete table-profile
catalog was already removed in S12.

DocSpec exposes a catalog builder and a prepared document-store runtime with
fetcher/processor injection, recovery, and a Dagster adapter. Its inspected
runtime expects dataset plans and document stores; it is not a qualified
replacement for independent source-publication subprocesses. Adding that
lifecycle would increase the source operator's work without replacing the
campaign's actual behavior.

**S21 and S31 are conditionally deferred, not completed.** Keep the current
source campaign. Reopen S21 when a named dataset workflow and DocSpec D22
demonstrate source ordering, interruption, root ownership, resource bounds,
retained pin checks, and stale-resume refusal. Reopen S31 for a concrete local
dataset caller that can use qualified public wheel APIs. DocSpec D51/D52 already
own the named GAO/comment dataset examples; no source-package dependency or
example is needed merely to have a loop to migrate. The independent reviewer
and coordinating agent agreed on these dispositions.

### B. Auxiliary catalogs and misplaced policy

S12 retires the entire `catalog` package and its declared `SourceProfile` table
registry. At baseline `04ade52`, `catalog/profiles.py` mixed identity/text/access
notes with `allowed_schemes`, processing `mode`, `region_adapter_id`, and a
`STEP4_ACTIVE_SOURCE_TABLES` flag. `catalog/artifacts.py` copied those choices,
joined reviewed relationships to a pinned RefSpec catalog, and computed custom
seals. Its only located executable consumers were the repository generator,
installed builder, and maintenance tests. Those commands, tests, input/output
JSONs, vendored RefSpec fixture, and package entry point are retired together.

The [source-reference notes](source-reference.md) retain useful relationship
knowledge as maintained prose. There is no replacement registry or seal.
Supported executable descriptions remain in existing native release profiles;
SpicyRegs' [dictionary](../../spicy-regs/src/spicy_regs/data_dictionary.py) and
producing transforms own its table columns. The review corrected claims about
CFR/Federal Register body columns, GAO RSS empty topic placeholders, FCC proceeding
identity, and non-native Federal Register topic relationships. Real CourtListener
cluster/body producers remain recognized; the unsupported old generic opinion
declaration is not treated as a working adapter. Blanket public-record access
was also a declaration, not evidence of every record's access conditions.

Rulespec's earlier `spicydocs_probe.py` and its result remain historical evidence.
Its new current-provider probe uses the installed public native profiles and
records that the tested wheel has no CFR release adapter, with a separate
SpicyRegs CFR metadata citation. No historical capture is rewritten and no
compatibility wrapper keeps the retired lookup alive. The S12 execution record
identifies the exact receiving probe and wheel qualification.

DocSpec D32/D34 and optional Search SC04 remain owners of actual experiment and
recipe choices. No removed processing flags are automatically copied there,
and their adoption is not completed by source-side deletion.

### C. Public tables and Iceberg

The supported command converts an admitted source release into an immutable
Parquet generation with a source pin
([`docs/cli.md:73`](cli.md#publish-public-table),
[`public_tables/publish.py:262`](../src/spicy_docs/public_tables/publish.py#L262)).
The source-specific profile checks columns and identity
([`public_tables/profiles.py:43`](../src/spicy_docs/public_tables/profiles.py#L43));
the publisher verifies output rows before publication. Its PyArrow extra and
source pin serve people who need a stable flat source dataset.

SpicyRegs instead updates public tables: its Regulations pipeline calls
`merge_comments`/`merge_and_export`
([`pipelines/regulations.py:392`](../../spicy-regs/src/spicy_regs/pipelines/regulations.py#L392)),
and its Iceberg implementation performs delete/insert updates and public export
([`sources/iceberg.py:135`](../../spicy-regs/src/spicy_regs/sources/iceberg.py#L135),
[`:506`](../../spicy-regs/src/spicy_regs/sources/iceberg.py#L506)). The
[scheduled ETL definition](../../spicy-regs/.github/workflows/etl-new-pipeline.yml#L43)
and [MCP reader](../../spicy-regs/src/spicy_regs/mcp_server.py#L286) establish
operational producers and consumers in code; this review does not assert live health.

SpicyDocs' `IcebergPublicTableSink` (baseline `c9da196`, `public_tables/iceberg.py:29`)
only accepts a new empty table and calls injected `add_files`; its located caller
is `tests/test_public_table.py:618` at baseline `c9da196`, using a test
table. It supplies neither upstream incremental updates nor a qualified production
attachment workflow. Retiring that helper removes an unsupported integration
obligation while preserving the documented Parquet outcome.

### D. CourtListener

SpicyDocs' [bulk listing:164](../src/spicy_docs/sources/courtlistener_bulk.py#L164)
and [SpicyRegs' listing:165](../../spicy-regs/src/spicy_regs/sources/courtlistener_bulk.py#L165)
repeat the same loop: missing size/date becomes a default, ETags are discarded,
and a truncated page without a continuation token silently ends discovery.
DocSpec's [`parse_listing_page:163`](../../DocSpec/tools/courtlistener_bulk_source.py#L163)
requires size, ETag and last-modified fields, enforces a page byte bound, and
refuses missing continuation. Its [`parse_capture:203`](../../DocSpec/tools/courtlistener_bulk_source.py#L203)
adds duplicate-key and completed-population checks. Filename/date/media-type
parsing is also duplicated. Preserve these stronger checks when sharing; an ETag
is a publisher revision marker, not a substitute for a whole-object SHA-256.

The exact upstream callers are
[`build_court_opinion_clusters.py:292`](../../spicy-regs/src/spicy_regs/transforms/build_court_opinion_clusters.py#L292),
[`build_court_opinion_bodies.py:248`](../../spicy-regs/src/spicy_regs/transforms/build_court_opinion_bodies.py#L248),
and [`court_scope.py:88`](../../spicy-regs/src/spicy_regs/transforms/court_scope.py#L88).
They consume their own `spicy_regs` copy today; they do not yet import SpicyDocs.
The [cluster](../../spicy-regs/.github/workflows/rollup-court-opinion-clusters.yml#L19)
and [body](../../spicy-regs/.github/workflows/rollup-court-opinion-bodies.yml#L21)
workflows invoke those transforms. DocSpec's capture tool is exercised by
[`test_courtlistener_bulk_source.py`](../../DocSpec/tests/test_courtlistener_bulk_source.py),
including source-item construction. The source grammar belongs in the provider;
retained-capture identity, selection, withdrawal handling and catalog-item mapping
remain DocSpec concerns.

The [raw-reader guide](sources/raw-readers.md#courtlistener) records streaming CSV,
concatenated bzip2, reconnect and bound behavior. Preserve those signals during
parser sharing. Consolidating listing grammar does not prove a full raw stream is
complete or eliminate the guide's distinct CSV/decompression limitations.

### E. Documented-value drift

The purpose is grounded in observed differences, not a generic quality framework:
[`source_domains.py:8`](../src/spicy_docs/sources/source_domains.py#L8) explains
pass-through publisher strings; [comparison:492](../src/spicy_docs/sources/source_domains.py#L492)
separates undocumented observations from documented values absent in the bounded
snapshot. The operational caller is
[`scripts/check_source_domain_drift.py:155`](../scripts/check_source_domain_drift.py#L155);
[`test_source_domain_drift.py`](../tests/test_source_domain_drift.py) protects exact
captures, provenance, parsing, comparison and accepted explanations. No counterpart
module or executable caller was found in current SpicyRegs.

Keep this as an explicitly owned source-maintainer diagnostic, with the existing
[refresh instructions](source-domain-drift.md#review-documented-value-drift): observe
retained tables with time/revision pins, review both directions, and refresh
publisher captures and their manifest together. It does not discover live drift
until someone supplies new observations. Its nonzero status reports an unexplained
comparison; it must not reject valid publisher values during acquisition. Upstream
adoption is deferred until a maintainer selects it for SR03, with those boundaries.

### F. Campaigns and experiment execution

The [campaign guide](cli.md#campaigns-replay-and-source-tools) names an operational
source command. [`cli/campaign.py`](../src/spicy_docs/cli/campaign.py) owns a thread
pool of subprocesses, run locks, receipts and interruption recovery. Removing it
now loses an existing source-operation path. Its later experiment replacement is
conditional on DocSpec D22 and S21; a similar function name or green dataset test
is insufficient parity evidence.

DocSpec's [fetcher](../../DocSpec/src/docspec/ports/content_fetcher.py#L77) and
[processor](../../DocSpec/src/docspec/ports/processor.py#L15) interfaces preserve
injection; [`adapters/dagster.py:116`](../../DocSpec/src/docspec/adapters/dagster.py#L116)
maps bounded task messages onto a real dynamic Dagster job with injected workers
and retry policy. Dataset reuse, processing and completion remain DocSpec's work.
Use those public wheel APIs for selected experiment composition, without requiring
SpicyRegs' [independent ETL](../../spicy-regs/src/spicy_regs/pipelines/regulations.py)
or source-only publication to adopt an experiment lifecycle.

### G. Physical storage and shared primitives

SpicyDocs' [writer:242](../src/spicy_docs/storage/blobs.py#L242) takes a known digest
and size, verifies early reuse without consuming new chunks, pins directory
identities, uses no-follow operations and syncs published directories. Its native
[partition publisher:176](../src/spicy_docs/releases/partitions.py#L176) calls that
API. DocSpec's [writer:43](../../DocSpec/src/docspec/adapters/storage/blobs.py#L43)
accepts an unknown digest, enforces a hard streaming limit before writing each
chunk, validates expected identity and conditionally links the result. Its
[CLI composition:289](../../DocSpec/src/docspec/cli/requests.py#L289) constructs it.
Both hash, stage, sync, conditionally publish, verify existing bytes and clean up;
neither implementation currently subsumes every useful property of the other.

Rulespec already supplies [atomic directory publication:1691](../../rulespec/packages/rulespec-artifacts/src/rulespec_artifacts/_artifact.py#L1691),
[blob reading:2061](../../rulespec/packages/rulespec-artifacts/src/rulespec_artifacts/_artifact.py#L2061),
and [canonical encoding:318](../../rulespec/packages/rulespec-artifacts/src/rulespec_artifacts/_artifact.py#L318).
The local [publication wrapper](../src/spicy_docs/storage/publication.py#L41) calls
that implementation; it is not a second rename engine. RS03 must qualify the
smallest shared writer before S22/D31 remove their physical copies. Keep media
types, source receipts, DocSpec references and dataset transactions with callers.
No new storage framework is selected.

## Invariants, value and counterfactual checks

| Commitment | Status in this decision | Failure if violated |
| --- | --- | --- |
| Source-only publication and public-data use remain independent of DocSpec | Preserved by provider ownership and optional composition | A source fix forces users to configure an experiment platform. |
| Exact source identities, values, refused evidence and coverage distinctions survive simplification | Required by AGENTS and S01/S07–S10/S19 | Outages, partial pages or changed source bytes become false data claims. |
| One implementation owns each shared source rule | Selected, not yet implemented for CourtListener | Three parsers continue disagreeing about complete listings and revision markers. |
| Dataset selection, processors, resources and reuse remain injectable | Preserved in DocSpec | Removing “unused” extensions makes the owner's iterative workflow impossible. |
| No circular package dependency | Required by S25/S31 and DocSpec D45–D46 | Optional module boundaries disguise an un-installable package graph. |
| Wheel and upstream status reflect observed acceptance | Required, still open | A local source edit is misreported as deployed consumer interoperability. |

The user value is fewer places to change one publisher rule, fewer generated files
to keep in sync, and simpler experiment setup without losing independent source
outputs. The smaller alternative is to delete every test-only or currently
unconsumed surface. That would wrongly erase intended experiments and upstream
CourtListener use. Keeping everything would preserve unused catalog and Iceberg
maintenance obligations. The selected distinction follows responsibility and an
identified user outcome.

Revisit a deletion if a concrete consumer demonstrates an unmet source fact or
immutable Iceberg workflow. Reject a proposed shared writer if satisfying both
callers requires a broad new storage platform or weakens bounds and durability.
The decision has failed if a source contributor still fixes the same grammar in
three places, or if an ordinary source user must install and configure DocSpec.
Those are observable outcomes; line-count reductions alone are not proof of value.

## Validation and implementation status

The following historical S11 maintenance commands ran against the inspected baseline inputs. The catalog generator was later retired by S12; this is an evidence record, not a current command list:

- `uv run --frozen python scripts/generate_source_profile_artifacts.py --check`
  reported 19 profiles and 18 active. This proves the present maintenance cycle
  works, not that the generated policy has a production consumer.
- `uv run --frozen python scripts/check_source_domain_drift.py` compared six
  documented domains with the pinned `2026-08-03T22:35:00Z` observation and reported
  seven explained findings. These are historical snapshot results, not current
  publisher coverage or a live data-quality verdict.

**Architecture verdict: approve these dispositions.** Ownership follows the
owner's intent, preserves useful existing differences, and selects concrete
removals and reuse. Confidence is high for local caller evidence and medium for
future adoption value. S12–S16, S21–S22, S25–S26 and S31 remain implementation work;
DocSpec D41–D46, SpicyRegs SR01/SR03 and Rulespec RS03 own their corresponding
changes. Keep selected deferrals separate from delivered changes. No adoption,
retirement, wheel release, production run, push, or upstream acceptance is claimed
by this inventory.
