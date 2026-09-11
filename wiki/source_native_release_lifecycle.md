> Generated reference snapshot; see [current architecture](../docs/architecture.md),
> [operator commands](../docs/cli.md), and [reference maintenance](../docs/documentation.md).

# Source-native release lifecycle

## Purpose

The `source_native_release_lifecycle` module turns preserved source pages into immutable, digest-pinned releases and verifies those releases from saved evidence.

It coordinates three responsibilities:

- The operator CLI selects a source profile, normalizes its scope, and routes publication or verification.
- The release engine validates pages, selects records, builds deterministic partitions and digests, and replays the evidence.
- The storage layer preserves content-addressed blobs and publishes the verified release directory without replacing existing content.

Source profiles define source-specific meaning and completeness rules. This module owns the shared release lifecycle.

## Architecture

```mermaid
flowchart LR
    Operator[Operator or scheduler]
    Sources[Live source adapters]
    Profiles[Source-native profiles]

    subgraph Lifecycle[source_native_release_lifecycle]
        CLI[source_native_cli.py]
        Engine[source_native.py]
        Storage[source_native_store.py]
        Publication[publication.py]
        Zip[source_native_zip.py]
    end

    Blobs[(Content-addressed blobs)]
    Release[(Immutable release directory)]
    Consumer[Verified consumer]

    Operator --> CLI
    CLI --> Sources
    Sources -->|Ordered SourceNativePage values| Engine
    Profiles -->|Parsing and validation rules| Engine
    Zip --> Sources
    Engine <--> Storage
    Storage <--> Blobs
    Engine --> Publication --> Release
    CLI -->|Independent verification| Engine
    Release --> Engine
    Blobs --> Engine
    Engine --> Consumer
```

```mermaid
sequenceDiagram
    actor Operator
    participant CLI as Operator CLI
    participant Adapter as Source adapter
    participant Profile as Source profile
    participant Engine as Release engine
    participant Store as Blob store
    participant Release as Release directory

    alt Publish
        Operator->>CLI: publish with source, scope, and paths
        CLI->>Adapter: acquire the canonical source scope
        Adapter-->>Engine: ordered pages and exact evidence bytes
        Engine->>Profile: parse, validate, and classify
        Engine->>Store: store evidence and payload partitions
        Engine->>Engine: select records and compute digests
        Engine->>Profile: replay all preserved evidence
        Engine->>Release: publish verified directory once
        CLI-->>Operator: artifact pin and source-state digests
    else Verify
        Operator->>CLI: verify with artifact pin and allowlist
        CLI->>Engine: selected profile and existing paths
        Engine->>Release: admit release members
        Engine->>Store: hash and read referenced blobs
        Engine->>Profile: replay preserved evidence
        CLI-->>Operator: verified artifact details
    end
```

Publication contacts live sources; verification does not. Verification reads the release and blob store, checks the expected artifact pin and verifier identity, and rebuilds the published result from preserved evidence.

## Core component documentation

- [Source-native release engine](source_native_release_engine.md) — record selection, deterministic partitions, artifact construction, admission, replay, and streaming reads.
- [Source-native storage and publication](source_native_storage_and_publication.md) — content-addressed blobs, create-once writes, deterministic ZIP metadata, and no-replace directory publication.
- [Source-native operator CLI](source_native_operator_cli.md) — source routing, scope arguments, acquisition adapters, retries, publication, verification, and machine-readable results.