# Documentation maintenance and provenance

The [documentation index](README.md) is the starting point for maintained
guides. Update them with the code they describe:

| Change | Update |
| --- | --- |
| Implementation ownership or import paths | [Architecture](architecture.md), affected guide links, and contributor entry points |
| Command arguments, outputs, or failure behavior | [Operator guide](cli.md), [script index](../scripts/README.md), or [analysis-tool index](../tools/README.md) |
| Source scope, evidence, identity, or selection | The source guide under `sources/`, [acquisition decisions](decisions.md), and affected specification requirements |
| Release format or consumer assumptions | [Release lifecycle](releases.md), the [specification](superpowers/specs/2026-08-25-source-native-release-spec.md), and [maintenance decisions](maintenance-decisions.md) |
| Declared tables, applicability, or publisher domains | [Catalog and drift guide](catalog-and-drift.md) and the affected checked inputs |

Read the implementation, its callers, and relevant tests before stating a
guarantee. Explain scope and limits beside the behavior. Keep commands runnable
from the repository root with `uv run --frozen`; identify required inputs,
credentials, and effects. Link the owning module instead of copying its symbol
inventory. Check relative links and moved paths before submitting.

Keep a short rule and reason beside unusual code. Put architecture-wide reasons
in decision notes and current behavior in the task guide. The adopted release
specification remains the source for format requirements; historical amendments
must remain distinguishable from the current implementation. Measurements in
prose need their input pins, command, and retained receipt. Campaign findings
belong with corpus receipts outside the repository.

## Former generated wiki

The wiki was consolidated into these guides on 2026-09-11. Its metadata recorded
source commit `78b8565b936981308e8816821aefc59fab13635b`, generation timestamp
`2026-09-03T00:14:12.339168+00:00`, model `gpt-5.6-sol`, and generator version
`1.0.1`. The command and configuration were not retained, so exact regeneration
was never reproducible. Subsequent manual corrections appeared in those pages.

The complete tracked wiki and its original metadata remain in Git at
`720fabd6c2aae4e1a692ff721cbaca5e55f70256`. For example:

```sh
git show 720fabd6c2aae4e1a692ff721cbaca5e55f70256:wiki/metadata.json
git show 720fabd6c2aae4e1a692ff721cbaca5e55f70256:wiki/federal_register_source_native.md
```

The consolidation retained source-specific operating rules and proof limits,
checked them against the implementation, and removed duplicate generated
descriptions. In particular, the old Federal Register page described number-only
identity; the current guide describes the implemented compound identity.

| Former wiki topic or file | Current home and disposition |
| --- | --- |
| `overview`, connector ingestion, acquisition profiles, release lifecycle, source-definition governance | [Index](README.md), [architecture](architecture.md), and the relevant task guides; duplicate diagrams and logical-module hierarchies removed |
| `source_connector_contracts_and_projections`, `mirrulations_connector`, `courtlistener_bulk_connector` | [Raw readers](sources/raw-readers.md); preserve explicit projection, key accounting, bounded/exact reader differences, resume, and coverage limits |
| `federal_register_source_native` | [Federal Register](sources/federal-register.md); preserve splitting, crawl acceptance, diagnostics, and renditions; correct superseded identity and selection |
| `regulations_gov_source_native` | [Regulations.gov](sources/regulations-gov.md); preserve scope dates, exact object packs, inclusion replay, and collection-specific ties |
| `gao_product_page_source_native` | [GAO](sources/gao.md); preserve exact product scope, literal topic-field boundaries, ZIP evidence, and bounds |
| `spicy_regs_public_table_source_native` | [Public comments](sources/public-comments.md); preserve whole-partition proof, Hive agency insertion, upstream selection, and attachment diagnostics |
| `source_native_profile_api`, `source_native_release_engine`, `source_native_storage_and_publication` | [Releases](releases.md), [architecture](architecture.md), and the specification; preserve callback responsibilities, deterministic storage, immutable publication, and verification distinctions |
| `source_native_operator_cli` | [Operator guide](cli.md); replace the old pointer page |
| `source_profile_catalog_artifacts`, `source_domain_drift_gate` | [Catalog and drift](catalog-and-drift.md); preserve deterministic regeneration, provenance, bidirectional findings, and snapshot write behavior |
| `metadata.json` | Provenance above; exact file remains in the pinned Git revision |
| `module_tree.json`, `first_module_tree.json` | Removed generated symbol inventories; current ownership map and live code replace stale counts and graphs |

An ignored local `wiki/temp/dependency_graphs/spicy_docs_dependency_graph.json`
was also removed. It was generated scratch data and was not part of the tracked
Git snapshot.

These guides are maintained prose. Adding a second generated documentation tree
would restore the same navigation and drift problem; any future generator should
serve these task guides and record its reproducible inputs and command.
