# Maintainability decisions and compatibility boundary

This refactor preserves source evidence, published identities, observation
selection, immutable publication, and bounded consumer opening. The
[architecture map](architecture.md) identifies the implementation owners.

## Supported entry points

| Surface | Compatibility decision |
| --- | --- |
| `spicy_docs.source_native` | Preserve public build, publisher, reader, error, schema-bundle, admission, and verification imports, format constants, and declared public exports. Implementations live in `releases/`. |
| `spicy_docs.regulations_gov_source_native` | Preserve collection constants, data types, scope, classification, evidence parsing, iteration, digest functions, and declared public exports. Implementations live in `sources/regulations_gov/`. |
| `spicy_docs.source_native_profiles` | Preserve profile exports. A caller needing one source can import its source-owned `profile.py` without loading unrelated sources. |
| `spicy_docs.federal_register_source_native` | Preserve the Federal Register imports used by current reader probes. Source acquisition and classification live in `sources/federal_register/native.py`. |
| `spicy_docs.source_native_store` | Preserve the current consumer's blob-store imports. Their implementation lives in `storage/blobs.py`. |
| Newly organized library APIs | Public tables use `spicy_docs.public_tables.api`; table profiles use `spicy_docs.public_tables.profiles`; the unused `spicy_docs.catalog` package and its artifact builders are retired. [Source-reference notes](source-reference.md) preserve useful knowledge; current native profiles own executable source descriptions. No forwarding wrappers remain. |
| Raw reader modules | Mirrulations and CourtListener remain under `sources/`. |
| Operator commands | `spicy-docs-source-native` is the installed entry point in `pyproject.toml`; its implementation lives in `cli/`. The retired catalog builder has no replacement command. Current subcommands, injected operations, exit codes, and `python -m` paths are documented in the [operator guide](cli.md). |
| Private test hooks | Tests now patch the implementation owner, such as Regulations.gov acquisition's pack limit. Private imports are not retained as forwarding wrappers. |

The five modules in `tests/test_reader_closure.py` match DocSpec's installed-wheel
probe. Each is imported in isolation. They must not eagerly load HTTP clients,
S3 clients, logging/progress libraries, Polars, PyArrow, or DuckDB. Federal
Register profile and replay imports additionally exclude GAO, Zyte, and live
transport modules. The old `schema_bundle_digest` convenience import from
`source_native` remains available; new code should import it from Rulespec.

The caller inventory covered this repository and the local DocSpec, spicy-regs,
spicysearch, RefSpec, and rulespec checkouts. DocSpec's installed-wheel probe
imports spicy-docs through these entry modules. They remain discoverable public
APIs with one implementation behind each exported operation. Current callers
and documented use define the supported entry points. The organization follow-up
keeps only those five export modules at the package root; it adds no wrappers
for moved internal modules. The current code and guides use the owning packages.

## Unused-code dispositions

| Candidate | Decision and reason |
| --- | --- |
| `_descriptor_rows()` | Removed. No repository or searched downstream caller; the underlying descriptor and JSON-lines readers remain in use. |
| `_policy()` | Removed after the release split. Its only use forwarded a build's scope to the actual policy validator. |
| `Writer` | Removed under the decision that legacy support is not required. No implementation or current caller was found in this repository or the five related checkouts. A source uses `Reader` or `SourceNativeProfile`; publication uses the shared publisher. |
| `declared_profile_for_table()` | Retired with the unused table registry in S12. Existing native release profiles describe working source operations; [source-reference notes](source-reference.md) preserve reviewed relationships and correct unsupported table-field claims. |
| `discover_agencies()` | Retain as the documented library convenience for listing agencies with the built-in anonymous Mirrulations connection. Same-named sibling functions are separate APIs. |

A final static scan found no private top-level function without a name or
attribute read across source, tools, and tests. This is a candidate-finding
check, not proof that every branch is reachable or every external API is used.

## Shared mechanics and preserved differences

Federal Register production and offline replay use one profile and scope
validator. HTTP retry lives in `transport/retry.py`; CLI adapters live in
`transport/acquisition.py`. Publisher media-type inference and compatible
integer-only JSON decoding have one implementation each. CLI and replay share
path-separation preflight in `releases/paths.py`.

CLI scope, acquisition, source error type, and optional public-table support are
registered together in `cli/sources.py`. A source using an existing scope pattern
adds one registration entry plus its source implementation/profile, tests, and
documentation. A new flat projection also needs its own `PublicTableProfile`.
The generic release engine does not need another source branch.

Publication consumes the source iterator inside its transport context and closes
partial iteration before closing transport. Counted digest streams still use
Rulespec's canonical encoding and hashing. Tests share routine response encoding,
payload inspection, and report traversal; malformed expected artifacts remain
independently constructed.

[Acquisition decisions](decisions.md) preserve source-specific JSON diagnostics,
observation ties, composite identity, and the deferred `correction_of` field.
Regulations.gov schema digests remain cached: schemas are immutable constants,
and recomputing their digests inside both publication and replay repeated costly
work per record. The original profiling narrative remains in Git history;
this refactor preserves the cache and its purpose.

## Long-code review

| Code | Disposition |
| --- | --- |
| Release publication | `_publish_indexed` went from 311 to 187 lines. It computes the result, stages indexed partitions, writes metadata, verifies, and publishes. The extracted steps perform substantive operations. |
| Acquisition indexing | The 225-line method became a 197-line function with a separate stateless page-chain check. Index updates and source callback state remain together. |
| Full verification | The 274-line verifier is now 246 lines after sharing counted digest construction and correcting stale commentary. Keep the ordered comparisons and failure-ledger accounting visible in one function. |
| Acquisition replay | Keep the 239-line loop together. Traversal/window/page state, evidence pins, terminal markers, and discovered-record accounting are coupled. Replay remains independent of the publisher's indexer. |
| Federal Register module | Retain the cohesive source adapter and its field/schema declarations. The single current `DOCUMENT_FIELDS` set replaces the unused historical field-policy map; request construction and replay require the same current fields and canonical URL. The independently importable profile already has its own home. |
| Captured public-comment module | Retain the single captured-table adapter after sharing JSON and media-type mechanics. Its largest function is 51 lines; source column declarations, evidence format, and small callbacks make the file long. Split another responsibility when a concrete change needs it. |
| Mirrulations reader | Retain distinct incremental and complete-enumeration paths sharing download primitives. Their failure and coverage promises differ. The largest function is 80 lines. |

The module split increases physical Python lines through explicit imports and
public API exports; it does not establish a net line-count reduction.
Repeated implementation was removed, and changes can now be reviewed within
bounded responsibilities. File size remains a review prompt, not a quota.

## Current source-release format and retained evidence

Source-native format and verifier `2.0` accept only the installed current
schema bundle, the selected profile's current acquisition-policy version,
and producer `spicy-docs`. The format name, artifact kind, verifier ID,
and digest framing keep their existing identifiers; the schema ID, member
key, and packaged schema directory explicitly name `2.0`. Every receipt
requires all three nonnegative failure counts. Their sum must equal
`failedRecordCount`, including when that total is zero; transient and unclassed
failures remain unpublishable.

Historical schema and policy allowlists, missing-count defaults, and acceptance
of the former `spicy-regs` producer have been removed. Public-table format and
verifier remain `1.0`; their current producer is also `spicy-docs`. Retained
artifacts remain on disk, but current readers and the
[offline replay tool](../src/spicy_docs/sources/federal_register/replay.py)
refuse unsupported inputs. This change provides no conversion or historical
reader. Independently sealed refusal fixtures protect that boundary; the
historical schema copy is test evidence and is not packaged.

Storage read, reuse, write, and publication-size measurements now belong to
`PublishedSourceNativeRelease.byte_measurements` and the publish CLI result.
They are absent from sealed receipts. Metadata is written once; publication
size is measured afterward. Exact member sizes and hashes, source counts,
requested scope, evidence references, and the root size limit remain checked.
For fixed sealed inputs, format `2.0` produces the same exact artifact pin
whether the store starts empty or already contains the payloads. Logical
identity still includes `releaseSchemaDigest`, so the schema change can alter
the logical ID between versions `1.0` and `2.0` despite unchanged digest framing.

This is an intentional consumer boundary. The current DocSpec acceptance probe
requires the removed producer allowlist to include both `spicy-regs` and
`spicy-docs`; it will refuse this candidate until DocSpec implements its D10
acceptance update. Building and qualifying the SpicyDocs wheel does not establish
DocSpec adoption. No sibling repository is changed by this decision.

## Remaining observations

The former generated wiki has been consolidated into maintained task guides.
[Documentation provenance](documentation.md#former-generated-wiki) records the
original generator metadata, the recoverable Git snapshot, and each topic's
current home. Reproducing the missing generator is no longer a prerequisite for
maintaining the documentation.

At the user's request, the contributor exercise used fresh blind subagents
assigned Python-developer and government-records-analyst personas. Both followed
the repository guidance and produced useful regression tests. Their shared
record-inspection detour prompted a preserved-record preview in the offline
example; finding Federal Register tests prompted explicit source test paths in
the contributor guide. These are simulated contributor observations on a
prepared host. First-time human contribution times remain unmeasured.

Independent review also exposed a pre-existing Federal Register public-table
identity mismatch. Its separately versioned
[projection repair](decisions.md#federal-register-public-tables-preserve-composite-identity)
preserves columns while using both identity fields. Legacy table support is not
required. This changes that table's output identity and is separate
from the behavior-preserving module extraction. Current native-to-public CLI
tests cover the boundary that the former number-only test stub missed.
