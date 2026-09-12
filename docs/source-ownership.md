# Who owns what

SpicyDocs remains an independent source provider. Reuse through installed wheels
reduces duplicate implementation without forcing source users into a dataset platform.

## Product responsibilities

| Component | Responsibility |
| --- | --- |
| SpicyDocs | Source acquisition, faithful fields, identity, coverage, evidence and immutable source publication. |
| SpicyRegs | Its independently useful regulatory-data pipeline and mutable public tables. |
| DocSpec | Dataset catalogs, selection, injected fetchers/processors, capture, experiments, reuse and comparison. |
| Rulespec Artifacts | Shared canonical encoding, artifact admission/publication and bounded physical blob writes. |

DocSpec owns dataset semantics; Dagster or another executor schedules and runs
its work. RefSpec and other supplied processors/resources own their domain meaning.
A source release, catalog or retained capture can each be a useful stopping point.

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
