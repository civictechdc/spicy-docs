# Decisions behind the rules

Use [source guides](README.md#work-on-a-source) for current procedures and the
[release specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
for exact requirements. This page keeps the reasons that future changes must preserve.

## Community supply precedes origin acquisition

Prefer spicy-regs public tables where they carry the required data; origin
acquisition fills gaps. Capture and pin whole named agency Parquet objects
before classifying rows, including locator, fetch time, stated freshness, size
and SHA-256. A live query result cannot replace pinned input.

Sources are explicit CLI choices; fallback is not automatic. The original
“Supply-precedence ruling” cited a platform `PLAN.md` that is not retained here.
Commits `48dac81` and `b25a3e9`, the captured-comment adapter and its tests retain
the implemented decision; they do not reconstruct the missing plan.

<a id="federal-register-identity-and-fields-version-separately"></a>

## Federal Register identity changes preserve the current fields

A document number can name different documents on different dates. Identity
therefore uses `(document_number, publication_date)`; conflicting observations
of the same pair refuse publication. Policy `1.1` introduced that identity;
current policy `1.2` also describes the limits of stable observed crawls.

Both use the same 22 `DOCUMENT_FIELDS`. Requests and replay require that set and
the exact canonical URL. The proposed `correction_of` field was deferred and
never accepted; adding it needs a new policy decision.

Historical rationale: SD-24 / DocSpec decision 0003,
`docs/decisions/0003-federal-register-record-identity.md` in that repository.
It contains superseded proposals; the current source profile, fields and tests
remain the implementation evidence.

## Federal Register public tables preserve composite identity

Projection `1.1` uses `primaryKey: ["document_number", "publication_date"]`.
A number-only key would reject valid reused numbers. Both columns, their types
and literal values remain unchanged, so the Parquet schema ID stays `1.0`.

Compound-key duplicate checks use Rulespec canonical JSON and the source identity
function. Other profiles keep scalar keys. Readers require the exact current
projection version and key; the earlier number-only projection is unsupported.

## Similar sources can need different rules

Regulations.gov documents and dockets select the newest observation and may
collapse identical same-instant records. Document ties changing only
`openForComment` or `withinCommentPeriod` use a narrower comparison while keeping
the full observation digest. Equal-version comment ambiguity is refused.

Regulations.gov and captured comments share integer-only JSON decoding, with
source-specific exceptions. Federal Register retains its finite/non-finite float
diagnostics and response checks; GAO requires canonical capture manifests.
Share mechanics without erasing those distinctions.

## GAO evidence is bounded and literal

The profile covers only the named product IDs. Exact HTML and the literal
publisher topic survive; interpreting that topic belongs downstream. The
[GAO guide](sources/gao.md) owns capture limits and refusal rules.

## Supported entry points

The package root keeps five public export modules for current consumers:

- `spicy_docs.source_native`: release publishing, reading, schemas and verification.
- `spicy_docs.source_native_profiles`: source profile exports.
- `spicy_docs.federal_register_source_native`: Federal Register source operations.
- `spicy_docs.regulations_gov_source_native`: Regulations.gov source operations.
- `spicy_docs.source_native_store`: source blob-store API.

Implementations live under their [owning packages](architecture.md). Public
tables use `spicy_docs.public_tables.api` and `.profiles`; raw readers stay under
`sources/`. The installed command is `spicy-docs-source-native`.

Reader imports must avoid eager HTTP/S3, logging/progress, Parquet and DuckDB
imports. Federal Register profile/replay imports also avoid GAO, Zyte and live
transports. `tests/test_reader_closure.py` guards these boundaries. Existing
`source_native.schema_bundle_digest` remains available; new code uses Rulespec.
Patch implementation owners in tests; private forwarding wrappers are not supported.

## Current source-release format and retained evidence

- Source-native format/schema/verifier: **2.0**; public-table format/verifier: **1.0**.
- Producer: **`spicy-docs`**. Require the current schema bundle and profile policy.
  Older `spicy-regs` names in format identifiers remain data identifiers.
- Historical inputs are retained but refused by current readers/replay. There is
  no automatic conversion or legacy reader. Historical test schemas are not packaged.
- All three nonnegative failure counts are required and must sum to
  `failedRecordCount`, even at zero. Transient and unclassed failures cannot publish.
- Storage byte accounting lives in the run result, outside sealed receipts.
  Fixed sealed inputs retain the same artifact pin regardless of store reuse.
  Changing the release schema can still change logical identity.

## Share work without sharing mistakes

Keep source callbacks and scope registration in `cli/sources.py`; the generic
release engine needs no source-specific branch. Close partially consumed source
iterators before their transports. Cache digests of immutable schemas instead
of recomputing them for each record.

Share routine test encoding and inspection. Keep malformed artifacts and semantic
replay independent of the writer they check. Preserve coupled traversal, selection
and accounting state in cohesive functions; file length is a review prompt, not a quota.
