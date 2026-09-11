> Generated reference snapshot; see [current architecture](../docs/architecture.md),
> [operator commands](../docs/cli.md), and [reference maintenance](../docs/documentation.md).

# Source definition governance and validation

## Purpose

The `source_definition_governance_and_validation` module governs how SpicyDocs describes published SpicyRegs source tables and detects changes in selected source-defined values.

It has two independent parts:

- The source-profile catalog publishes deterministic, digest-pinned descriptions of table identities, processing modes, access rules, evidence fields, and relationships to RefSpec resources.
- The source-domain drift gate compares selected table values with pinned government documentation and requires a written acceptance for every difference.

The module does not acquire records, build tables, validate complete table schemas, interpret source values, define search policy, or publish source-native releases.

| Question | Answer |
| --- | --- |
| What goes in? | Source-profile declarations, reviewed applicability data, a pinned RefSpec catalog, pinned publisher documents, observed table-value snapshots, and accepted drift findings. |
| What happens? | The catalog branch validates and seals source definitions. The drift branch compares documented and observed values in both directions. |
| What comes out? | Digest-pinned catalog artifacts and a pass-or-fail drift report with traceable findings. |
| How do we check it? | Regenerate catalog artifacts byte for byte, run the offline drift gate, and run each component’s focused tests. |

## Architecture

```mermaid
flowchart LR
    Producers["Source-table producers"]
    Tables[("Published SpicyRegs tables")]
    Publishers["Government publishers"]
    Captures[("Pinned OpenAPI and XSD captures")]
    RefSpec[("Pinned RefSpec catalog")]

    subgraph Governance["source_definition_governance_and_validation"]
        Catalog["Source-profile catalog<br/>and applicability builder"]
        Observation["Checked snapshot or<br/>explicit Parquet observation"]
        Drift["Bidirectional source-domain<br/>drift gate"]
    end

    CatalogArtifacts[("Digest-pinned profile<br/>and applicability artifacts")]
    GateResult["Findings report<br/>and pass/fail status"]

    Producers --> Tables
    Tables -. "described by declarations" .-> Catalog
    RefSpec --> Catalog
    Catalog --> CatalogArtifacts

    Publishers --> Captures --> Drift
    Tables --> Observation --> Drift
    Drift --> GateResult
```

The catalog branch describes tables without opening them. The drift branch inspects only declared closed-value domains, either through a checked snapshot or an explicit local Parquet observation. Neither branch imports source connectors, source-native profiles, release machinery, or sibling-product runtimes.

### Validation paths

```mermaid
flowchart TB
    Profiles["SOURCE_PROFILES"]
    Policy["Reviewed applicability input"]
    Resources["Digest-pinned RefSpec catalog"]
    CatalogValidation["Validate formats, seals,<br/>coverage, and references"]
    Artifacts["Build, sort, hash,<br/>and seal artifacts"]
    ArtifactCheck{"Matches checked files<br/>byte for byte?"}

    PublisherCaptures["Verified publisher captures"]
    DomainDeclarations["Declared table domains"]
    ObservedValues["Observed-domain snapshot<br/>or local Parquet values"]
    Compare["Compare exact strings<br/>in both directions"]
    Ledger["Accepted-findings ledger"]
    DriftCheck{"Ledger exactly matches<br/>current findings?"}

    Profiles --> CatalogValidation
    Policy --> CatalogValidation
    Resources --> CatalogValidation
    CatalogValidation --> Artifacts --> ArtifactCheck

    PublisherCaptures --> Compare
    DomainDeclarations --> Compare
    ObservedValues --> Compare
    Compare --> DriftCheck
    Ledger --> DriftCheck
```

Catalog validation proves deterministic content, complete profile coverage, and valid RefSpec references. Drift validation proves that every current documented-versus-observed difference has an active explanation and that no obsolete exception remains. These checks do not prove publisher authenticity, semantic correctness, deployment, or publication.

## Core component documentation

- [Source-profile catalog artifacts](source_profile_catalog_artifacts.md) — source declarations, applicability policy, RefSpec validation, canonical JSON, content identities, artifact generation, and deterministic regeneration checks.
- [Source-domain drift gate](source_domain_drift_gate.md) — publisher-capture verification, domain parsing, Parquet observation, bidirectional comparison, accepted-findings governance, and command-line verification.