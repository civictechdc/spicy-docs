# Release lifecycle and extension

A source-native release binds selected records to exact acquisition evidence.
Keep its metadata directory, separate content-addressed blob store, artifact pin,
and accepted producer identity for later reading or verification.

Use the [CLI](cli.md) for commands, the
[specification](superpowers/specs/2026-08-25-source-native-release-spec.md) for
formats/digests/bounds, and the [architecture map](architecture.md) for owners.

## What happens during publication

1. The source validates explicit scope and yields ordered pages with request
   identity, traversal/window/page positions, exact bytes, and media type.
2. The publisher stores evidence, checks chains/completeness, classifies records,
   and indexes observations in temporary SQLite.
3. Source policy selects traversal and observations. Shared code derives records,
   renditions, schemas, partitions, and digests using Rulespec Artifacts' canonical
   byte rules.
4. The publisher writes a receipt and stages members. Full verification replays
   evidence and checks the result before immutable publication exposes the directory.

Current format **2.0** requires failure-summary counts and exact current schemas,
policies, producer, and verifier version. Historical formats are refused with
retained files left intact. Format changes can change logical artifact identity
because its schema contributes to that identity, even with unchanged source facts.

Sources own classification, identity, dates, ties, and completeness. Shared code
owns indexing, partitioning, manifests, artifact identity, and publication.
Evidence remains available for excluded probes and discarded observations.

## Choose the right check

| Check | Establishes | Limit |
| --- | --- | --- |
| `verify_source_native_admission()` | Bounded agreement among receipt, release root, and profile on a structurally admitted artifact | No caller pin/allowlist check or full replay |
| `SourceNativeReleaseReader` and CLI admission | Structure, source profile, supplied pin, explicit implementation allowlist, and row checks during reading | Unread rows remain unchecked |
| `verify_source_native_release()` | Offline reconstruction of observations, failures/evidence links, selected records, renditions, ordering, digests, and counts | Agreement with retained evidence, not publisher authenticity or broader coverage |
| Public-table reader and CLI admission | Table pin, profile, layout, and accepted verifier | No source reprojection or full Parquet-row check |
| `verify_public_table_release()` | Table admission plus full Parquet-row checks | Source evidence remains a separate input |

The publisher writes the verification receipt before staging verification;
the verifier checks it. Choose accepted implementation IDs from trusted
deployment policy, independently of artifact claims. Passing checks does not
authenticate the publisher.

## Storage and recovery

[`SourceNativeBlobStore`](../src/spicy_docs/storage/blobs.py) supplies reads/writes.
Its local implementation delegates physical writes to
`rulespec_artifacts.LocalBlobWriter`:

- Declared size is a hard limit checked before each write.
- Writes verify size/SHA-256, pin directories, and install digest-named blobs
  without replacement.
- Reuse still checks existing bytes and durable directory state. Known reuse
  consumes none of the supplied iterator; the caller owns its lifetime.
- Write receipts distinguish reuse from staging writes. Storage has no DocSpec
  dataset-lifecycle dependency.

`PublishedSourceNativeRelease.byte_measurements` and CLI `byteMeasurements`
describe **this publication invocation**, outside the sealed receipt:

| Measurement | Meaning |
| --- | --- |
| Payload bytes read/reused/written | Unique evidence and staged partitions presented to storage; excludes total network traffic and verification reads |
| Written bytes | Includes a losing concurrent staging write discarded after checking the winner; reused + written can exceed read |
| `publicationBytesWritten` | Size of the six local metadata files after writing |

Metadata is built once without encoding its own measured size. With identical
sealed inputs, empty and populated blob stores produce the same artifact pin;
only reported reuse differs. Keep measurements in operator records: later
verification/inspection cannot reconstruct storage work.

[`storage/publication.py`](../src/spicy_docs/storage/publication.py) requires a
new destination separate from the blob store, with neither containing the other.
Failure may leave exact unreferenced blobs. They are not a release or permission
to delete shared storage.

Failed publication can attach `failed_acquisition` to the original exception:

- GAO and Federal Register attach bounded response context for checks before
  page yield. Regulations.gov does so for current-object metadata, JSON, or
  identity failures before pack yield.
- A later enumeration failure never inherits an earlier object's bytes.
  Shared indexing stores bounded page evidence before semantic checks.
- `retainedPageEvidence` lists at most eight distinct previously written blobs,
  with total count and truncation flag. These are context, not necessarily refused
  responses; iterator/final checks may fail without a new body.

See [CLI recovery](cli.md#output-and-failures) for report retention, body limits,
and offline retrieval. Refusals create neither admitted records nor partial releases.

Changing evidence ZIP metadata, schema bytes, digest domains, ordering, or format
IDs may change published identity despite unchanged decoded records. Preserve
exact source evidence and make format decisions explicit.

## Add or change a source profile

Compose a [`SourceNativeProfile`](../src/spicy_docs/releases/profile.py) in one
source-owned package's `profile.py`:

| Callback group | Required decisions |
| --- | --- |
| Scope/acquisition | Canonical selectors, source/policy identity, bounds, ordered evidence |
| Replay/completeness | Exact-byte parsing, cursors/windows, inventory, excluded evidence, scope membership |
| Record meaning | Closed shape, identity/digest, schema, renditions, versions, ties |
| Release claim | `observed-crawl` or justified `complete-snapshot`, plus traversal acceptance |

Keep network access outside deterministic parsing and profile imports.
`complete-snapshot` requires `source-enumeration` acceptance and proof of the named
scope. Matching crawls establish observed stability, not authoritative enumeration.
Reuse source rules only when actual behavior matches.

Register scope, acquisition, source errors, and optional table support in
[`cli/sources.py`](../src/spicy_docs/cli/sources.py). Reuse the publisher. Add a
`PublicTableProfile` only for needed flat output; catalog declarations are separate.

Test a small complete release, malformed success, incomplete enumeration, duplicates,
ties, source drift, and tampered replay. Sources own fixtures; shared checks live
in `tests/releases/`. Build adversarial artifacts independently of the publisher.
For import/schema moves, also check the wheel and downstream imports. See
[contributing](../CONTRIBUTING.md).
