# Maintainability decisions and compatibility boundary

This refactor preserves source evidence, published identities, observation
selection, immutable publication, and bounded consumer opening. The
[architecture map](architecture.md) identifies the implementation owners.

## Supported entry points

| Surface | Compatibility decision |
| --- | --- |
| `spicy_docs.source_native` | Preserve public build, publisher, reader, error, schema-bundle, admission, and verification imports, format constants, and historical `__all__`. Implementations live in `releases/`. |
| `spicy_docs.regulations_gov_source_native` | Preserve collection constants, data types, scope, classification, evidence parsing, iteration, digest functions, and historical `__all__`. Implementations live in `sources/regulations_gov/`. |
| `spicy_docs.source_native_profiles` | Preserve profile exports. A caller needing one source can import its source-owned `profile.py` without loading unrelated sources. |
| `spicy_docs.public_table` | Preserve table build, publisher, reader, location, verifier, and injected Iceberg APIs. Implementations live in `public_tables/`. |
| Other public reader modules | Keep Federal Register, source profiles, blob stores, Mirrulations, and CourtListener imports stable. |
| Operator commands | Keep both installed entry points in `pyproject.toml`. The source-native command retains its four subcommands, injected operations, exit codes, and result shapes. |
| Private test hooks | Tests now patch the implementation owner, such as Regulations.gov acquisition's pack limit. Private imports are not retained as forwarding wrappers. |

The five modules in `tests/test_reader_closure.py` match DocSpec's installed-wheel
probe. Each is imported in isolation. They must not eagerly load HTTP clients,
S3 clients, logging/progress libraries, Polars, PyArrow, or DuckDB. Federal
Register profile and replay imports additionally exclude GAO, Zyte, and live
transport modules. The old `schema_bundle_digest` convenience import from
`source_native` remains available; new code should import it from Rulespec.

The caller inventory covered this repository and the local DocSpec, spicy-regs,
spicysearch, RefSpec, and rulespec checkouts. DocSpec's installed-wheel probe and
a historical spicysearch investigation script import spicy-docs. Installed
consumers outside those checkouts are unknown. The refactor preserves public
names rather than treating missing local callers as proof of no consumers.

## Unused-code dispositions

| Candidate | Decision and reason |
| --- | --- |
| `_descriptor_rows()` | Removed. No repository or searched downstream caller; the underlying descriptor and JSON-lines readers remain in use. |
| `_policy()` | Removed after the release split. Its only use forwarded a build's scope to the actual policy validator. |
| `Writer` | Retain the documented, exported legacy extension interface. Core publication does not implement it. A new source uses `Reader` or `SourceNativeProfile`; removing `Writer` needs an explicit public deprecation decision. No external implementation was verified. |
| `declared_profile_for_table()` | Retain as a supported, lightweight lookup of declared source capabilities. It raises `KeyError` for an undeclared table without loading a processing runtime. |
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
| Release publication | `_publish_indexed` went from 311 to 187 lines. It computes the result, stages indexed partitions, writes self-accounting metadata, verifies, and publishes. The extracted steps perform substantive operations. |
| Acquisition indexing | The 225-line method became a 197-line function with a separate stateless page-chain check. Index updates and source callback state remain together. |
| Full verification | The 274-line verifier became 252 lines after sharing counted digest construction. Keep the ordered comparisons and failure-ledger accounting visible in one function. |
| Acquisition replay | Keep the 239-line loop together. Traversal/window/page state, evidence pins, terminal markers, and discovered-record accounting are coupled. Replay remains independent of the publisher's indexer. |
| Federal Register module | Retain the cohesive source adapter; its largest function is 105 lines. Field/schema declarations and historical field policies account for substantial file length. The independently importable profile already has its own home. |
| Captured public-comment module | Retain the single captured-table adapter after sharing JSON and media-type mechanics. Its largest function is 51 lines; source column declarations, evidence format, and small callbacks make the file long. Split another responsibility when a concrete change needs it. |
| Mirrulations reader | Retain distinct incremental and complete-enumeration paths sharing download primitives. Their failure and coverage promises differ. The largest function is 80 lines. |

The module split increases physical Python lines through explicit imports and
compatibility exports; it does not establish a net line-count reduction.
Repeated implementation was removed, and changes can now be reviewed within
bounded responsibilities. File size remains a review prompt, not a quota.

## Historical format rules

Known schema digests and accepted acquisition-policy versions are literal
history. Add an entry for a newly accepted format; do not compute old entries
from today's schema or profile. The failure-ledger shape widened after existing
releases had been published, so accepting only today's bundle would reject
valid older artifacts. Historical schema and acquisition-policy tests protect
these rules.

`sourceSystemId` and `acquisitionPolicyId` identify what an artifact is and still
require exact matches. `sourceSystemVersion` and `sourceStateScope` also currently
match the live profile. Changing either needs an explicit compatibility design;
the earlier decision to defer that work is preserved, not silently resolved by
this cleanup. See `releases/format.py` and the admission tests.

## Remaining observations

Exact regeneration of the original wiki generator remains unavailable because
its command and configuration were not retained. The documented manual refresh
procedure preserves original provenance and separates current task guides from
the dated reference snapshot.

A first-time human contribution exercise remains unobserved. The automated
example, tests, and clean installation establish that the path runs; they do
not measure whether a new contributor can follow it within the proposed times.
