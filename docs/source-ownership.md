# Who owns what

The cross-repository goal is one maintained implementation per shared behavior.
Consolidate duplicate code in the package that owns its responsibility and have
consumers use its wheel. SpicyDocs remains an independent source provider.

SpicyDocs fetches source files and turns their content and metadata into reusable
parsed data, linked to the original bytes. Supported source publishers save those
results directly. Library readers can also return the same parsed values for a
DocSpec caller to retain. Fetching a file does not replace parsing it, and callers
should reuse saved parsed results when they already exist.

DocSpec can also start with an existing catalog and call SpicyDocs fetchers and
parsers for selected entries. DocSpec manages the run and retains the downloaded
files and parsed results with their catalog associations. It can therefore drive
acquisition as well as reuse data already captured by SpicyDocs.

## Product responsibilities

| Component | Responsibility |
| --- | --- |
| SpicyDocs | Shared source acquisition, document parsing and metadata capture; faithful fields, structure, identity, coverage, evidence and immutable source publication; optional reusable PDF/image extraction adapters. |
| SpicyRegs | Its independently useful regulatory-data pipeline and mutable public tables. |
| DocSpec | Dataset catalogs, selection, catalog-driven acquisition through injected fetchers such as SpicyDocs, processing runs, retained results, experiments, reuse and comparison. |
| SpicySearch | Catalog enrichment, query interpretation and reranking; reusable search policies. |
| SpicyEngine | Native index construction, index replacement and query execution over retained inputs; a small local search/inspection client. |
| Rulespec Artifacts | Shared canonical encoding, artifact admission/publication and bounded physical blob writes. |

DocSpec owns dataset semantics; Dagster or another executor schedules and runs
its work. RefSpec and other supplied processors/resources own their domain meaning.
A source release, catalog or retained capture can each be a useful stopping point.

Reuse retained data as well as code. Engine should read existing DocSpec catalogs
and selected processing results without requiring another complete catalog export.
Its index may store the fields needed for fast retrieval and display; full source
records remain addressable through DocSpec. Search enrichment adds results linked
to the original inputs and uses DocSpec's existing run and reuse facilities. A
separate materialized dataset needs a demonstrated consumer or performance benefit.
The direct Engine reader is qualified locally against bounded retained JSON
states through DocSpec 0.4.0. Optional enrichment reuse and wider measurements
remain open in [PAR18](simplification-todo.md#shared-parsing-and-metadata-capture).

Apply this goal to parsers, metadata models, validation, transport, format readers,
hashing, serialization, evidence handling, processing helpers and maintenance tools.
Inspect behavior and callers as well as matching code: differently written functions
can implement the same rule. Existing shared packages take precedence over creating
another helper library. Interpretation can also be shared through its owning product;
keeping it downstream does not justify separate copies in every consumer.

Consolidation should remove more maintenance than it introduces. Prefer a small
shared implementation with explicit inputs over copied variants. Keep a separate
implementation only for a demonstrated difference in behavior or dependency needs,
with tests and a recorded reason. Track copies and dead support code removed,
consumers migrated, and adapters added; fewer lines alone do not prove success.

Parsing [GovInfo MODS metadata](sources/govinfo-metadata.md), including its nested
records and source links, is core source work. DocSpec chooses which records
become catalog items and manages their runs. RefSpec interprets citations and
document text; SpicyDocs preserves the publisher's reference hints.

The [extraction API](pdf-extraction-api.md) accepts retained bytes and injected
readers, strategies and recognition backends. It returns derived page observations
without assuming source authority. DocSpec owns selection, retained processing
stages, reuse, comparison and run completion; SpicyDocs does not import that lifecycle.

## Consolidate parsing across consumers

SpicyDocs is the shared home for reusable source parsing and metadata capture
currently spread across SpicySearch, RefSpec and Rulespec. This includes reading
retained files, document structure, literal reference occurrences, and publisher
code tables, labels and rosters. Ownership follows what a function does, including
when it currently lives inside a vocabulary builder or an interpretation pipeline.

Source readers preserve the publisher's text, structure, repeated fields and
source locations. Split mixed functions so consumers can use those observations
without inheriting a particular search or legal policy. Vocabulary reconciliation,
citation resolution, applicability, ranking and quality scoring remain downstream.
For example, retain every source-credit observation and its enclosing section;
the policy choosing which citation counts as enactment belongs to its consumer.

A source may publish derived text. A reader can retain that exact output with
its supplier, tool and source associations; choosing it over the original document
is a consumer decision. Publisher dictionaries likewise describe observed codes
and labels; they do not make an explicitly open list exhaustive.

Choose the best evidenced implementation, reuse existing bounded readers, and
organize public APIs by source family. Keep source spellings and unresolved cases
available. Use publisher guides and dictionaries to explain mappings. Shared
canonical encoding and artifact storage remain in Rulespec Artifacts; inspect
package dependencies before moving Rulespec code to avoid an import or wheel cycle.

A consolidation is complete when the named consumers use a qualified SpicyDocs
wheel and delete their replaced parsers and support code. Check source fidelity
against retained inputs and receiver behavior, documenting any intentional fixes.
Keep only adapters that translate between different product data types; remove
compatibility wrappers and unused helpers. A provider port alone is partial work.
Track the work in the [parsing checklist](simplification-todo.md#shared-parsing-and-metadata-capture).

## Keep, share or retire

- **Keep native releases and immutable Parquet tables:** source users need both
  without DocSpec. SpicyRegs' mutable publication remains separate.
- **Keep source diagnostics:** they explain retained source observations; they
  do not become acquisition gates or evidence of current live coverage.
- **Share CourtListener parsing:** the strict parser is public in SpicyDocs.
  Consumer adoption and removal of their copies belong to the receiving projects.
  Dataset selection and catalog-item mapping remain DocSpec work.
- **Use Rulespec's blob writer:** SpicyDocs maps its result to source references.
  Known-digest reuse, hard byte bounds, directory pinning, corruption refusal,
  cleanup and durability remain required. Dataset transactions stay in DocSpec.
- **Retire unused catalogs, policy declarations and Iceberg attachment:** no
  required current consumer earned their maintenance cost. [Source references](source-reference.md)
  retain useful source knowledge; an actual new consumer can justify reconsideration.

Keep dependency direction acyclic: SpicyDocs uses shared primitives, never
DocSpec's lifecycle. An experiment caller may use both public packages. Check
package requirements as well as imports; moving code between modules cannot fix
a package cycle.

## Current campaign and dataset callers

**S21 and S31 are conditionally deferred.** The current agency campaign publishes
and admits source releases. The caller audit found no remaining local catalog,
selected-document capture, processor or dataset-resume loop to replace.

Retain the source campaign until a named workflow demonstrates a better replacement:

- **S21:** DocSpec D22 must prove source ordering, interruption, root ownership,
  resource bounds, retained pin checks and stale-resume refusal.
- **S31:** identify a concrete local dataset caller that can use qualified public
  DocSpec wheel APIs. Replace its loops only after proving parity.

DocSpec D51/D52 own the planned GAO/comment dataset examples. Do not create a
source-side experiment merely to have something to migrate.

<a id="e-documented-value-drift"></a>

## Documented-value drift

Keep the [comparison tool](source-domain-drift.md) with source maintenance.
It distinguishes undocumented observations from documented values absent in a
bounded snapshot. New observations and publisher captures must be supplied;
the tool does not monitor live drift automatically. Its nonzero status reports
an unexplained comparison, not an invalid publisher record.

## Handoffs and evidence

[Task status](simplification-todo.md) links the receiving backlogs in optional
sibling checkouts. A provider implementation, a receiving patch, a qualified
wheel and an upstream release are distinct milestones. Do not mark adoption
complete because a local provider test passed.

The September 2026 inventory inspected code and documented uses in SpicyDocs,
SpicyRegs, DocSpec, Rulespec, SpicySearch and RefSpec. A missing local caller was
evidence within that search, not proof that no external user exists. The merged
[inventory and traces](https://github.com/mikewolfd/spicy-docs/blob/3ff8011b221d4508778996c4a479c54a038f406c/docs/source-ownership.md)
remain in Git; current decisions are summarized here.
