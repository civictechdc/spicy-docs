# Release lifecycle and extension

A source-native release binds selected source records to the exact evidence
used to derive them. Its directory contains deterministic metadata and payload
descriptors; a separate content-addressed store holds referenced evidence and
payload blobs. Keep both, along with the artifact pin and accepted producer
identity, to verify or consume the release later.

The [operator guide](cli.md) gives commands. The
[adopted specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
defines member names, schemas, digest inputs, ordering, and bounds. The
[architecture map](architecture.md) names the implementation owners.

## What happens during publication

1. The source validates a closed query scope and yields ordered pages with
   request identity, traversal/window/page positions, exact response bytes,
   and media type.
2. The publisher stores evidence, checks page chains and source completeness,
   classifies records, and indexes observations in temporary SQLite storage.
3. Source policy chooses the accepted traversal and observations. The publisher
   derives source records, renditions, schemas, deterministic partitions, and
   digests using Rulespec Artifacts' canonical byte rules.
4. The publisher writes a receipt and stages release members. Full verification
   replays saved evidence and checks the staged result. Only then does immutable
   publication make the destination directory visible.

The source owns classification, identity, dates, tie rules, and what
completeness means. Shared release code owns indexing, partitioning, manifests,
artifact identity, and publication. Exact evidence remains available even for
excluded probes or discarded observations.

## Choose the right check

| Check | What it establishes | Limit |
| --- | --- | --- |
| `verify_source_native_admission()` | Bounded agreement among the receipt, release root, and profile on an already structurally admitted artifact | Does not check a caller's expected pin or implementation allowlist, or replay every source observation. |
| `SourceNativeReleaseReader` and CLI admission workflow | Structural and source-native admission, supplied artifact-pin checks, an explicit implementation allowlist, and member/row checks during reading | A partially consumed reader has not checked unread rows. |
| `verify_source_native_release()` | Offline reconstruction of successful observations, selected output, renditions, ordering, digests, and receipt counts | Failure-ledger entries receive shape and class-count checks; their individual failure provenance is not reconstructed. |
| Public-table reader and CLI admission workflow | Supplied table-pin checks, profile, layout, and accepted verifier identity | Does not reproject source records or run the full Parquet-row check. |
| `verify_public_table_release()` | Full Parquet-row checks in addition to table admission | Operates on the table; source evidence remains a separate retained input. |

The source publisher creates the verification receipt before staging verification;
the verifier checks it. A successful admission or internally consistent digest
does not establish publisher authenticity. Choose accepted implementation IDs
from a trusted deployment decision, not from an untrusted artifact's own claim.

## Storage and recovery

[`storage/blobs.py`](../src/spicy_docs/storage/blobs.py) defines the
`SourceNativeBlobStore` read/write boundary and local implementation. Conditional
writes stream into a temporary file, verify the expected size and SHA-256, and
install a digest-named blob without replacement. Reusing an existing blob still
checks its bytes. Write receipts distinguish reused content from new bytes.

[`storage/publication.py`](../src/spicy_docs/storage/publication.py) owns
create-once publication. The release destination and blob store must be separate
and must not contain one another. A destination is never overwritten. A failed
publication may have already stored valid, unreferenced blobs; those are not a
published release or permission to delete shared storage.

Source evidence ZIP helpers use deterministic member metadata. Changing those
bytes, source schema bytes, digest domains, ordering, or literal format IDs can
change published identity even if the decoded records appear unchanged. Keep
format decisions explicit and preserve the source bytes needed to inspect them.

## Add or change a source profile

Implement one source-owned package and compose a
[`SourceNativeProfile`](../src/spicy_docs/releases/profile.py) in its `profile.py`.
The callbacks define these four groups:

| Group | Required decisions |
| --- | --- |
| Scope and acquisition | Canonical selectors, source identity, acquisition-policy identity, bounds, and ordered page evidence |
| Replay and completeness | Exact-byte parser, cursor/window validation, inventory checks, excluded evidence, and scope membership |
| Record meaning | Closed source shape, record identity and digest, schema, renditions, versions, and tie disposition |
| Release claim | `observed-crawl` or a justified `complete-snapshot`, plus the traversal acceptance rule |

Keep network access outside deterministic parsing and profile imports. A
`complete-snapshot` profile must use `source-enumeration` acceptance and prove
the named scope. Matching repeated crawls establish stability of an observation,
not an authoritative enumeration. Use an existing source only when its rules
match the new source's actual behavior.

Register CLI scope, acquisition, source errors, and optional table support
together in [`cli/sources.py`](../src/spicy_docs/cli/sources.py). Reuse the shared
publisher. Add a `PublicTableProfile` only when a flat output is needed; source
declarations for the catalog are a separate responsibility.

Test a complete small release, malformed success, incomplete enumeration,
duplicate or tied observations, source drift, and tampered replay evidence.
Shared checks live in `tests/releases/`; each source owns its meaningful fixtures.
Keep adversarial artifacts independent of the publisher being checked. When
moving imports or bundled schemas, also check the built wheel and current
downstream reader imports. See [contributing](../CONTRIBUTING.md).
