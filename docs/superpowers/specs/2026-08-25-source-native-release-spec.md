# SpicyDocs source-native release 2.0

**Status: normative target.** The shared local release path and source profiles
are implemented. Local wheel checks do not establish external object-store
publication, consumer cutover or scale conformance; those require their own evidence.

**Current versions:** source-native format/schema/verifier `2.0`; public-table
format/verifier `1.0`; producer `spicy-docs`. Require the installed current schema
bundle and selected profile policy. Existing `spicyregs` / `urn:spicy-regs:...`
format identifiers remain. Retain historical artifacts, but current readers
neither accept nor automatically convert them.

For ordinary use, start with the [release guide](../../releases.md) or
[commands](../../cli.md). This document defines the exact requirements:

1. [Purpose](#1-purpose-and-boundary)
2. [Artifact, identity and schema](#2-artifact-identity-and-schema)
3. [Acquisition completeness](#3-acquisition-completeness)
4. [Source state and selection](#4-source-state-and-profile-owned-collapse)
5. [Receipt and verification](#5-receipt-and-semantic-verification)
6. [Reader and dependencies](#6-bounded-reader-and-dependency-inversion)
7. [Public tables](#7-public-publication-profile)
8. [Federal Register baseline](#8-federal-register-profile)
9. [Conformance](#9-conformance)

## 1. Purpose and boundary

SpicyDocs owns source-specific acquisition, faithful source-native records,
immutable source-data publication, and thin raw-data readers. This specification
defines its one retained artifact, `spicyregs-source-native-release`. It uses
the Rulespec platform container and does not define another root, canonical
encoder, structural verifier, or framed digest implementation.

The release preserves source observations and the evidence needed to verify
them. It performs no DocSpec normalization, cross-source join, catalog
selection, disposition, capture, or document processing; no search or RefSpec
meaning enters this artifact.

## 2. Artifact, identity, and schema

The current receipt declares `formatVersion: "2.0"`,
`releaseSchemaId: "urn:spicy-regs:schema:source-native-release:2.0"`, and
`verifierVersion: "2.0"`. Its release-schema member is
`schemas/source-native-release-2.0.json`. Admission compares the embedded schema
with the sole current installed bundle, with no historical allowlist.
Logical digest framing is unchanged. Because the logical identity includes
`releaseSchemaDigest`, equivalent source data can have different logical IDs
across the `1.0` to `2.0` boundary. Within `2.0`, fixed sealed inputs produce the
same exact artifact pin regardless of payload-store reuse.

The artifact kind is `spicyregs-source-native-release`. Its closed product `spec` has exactly
`releaseSchemaDigest`, `sourceSystemId`,
`sourceSystemVersion`, `acquisitionPolicyId`, `acquisitionPolicyVersion`,
`acquisitionPolicyDigest`, `sourceStateScope`,
`sourceNativeSchemaSetDigest`, and
`sourceStateDigest`. Source-native releases have no Rulespec logical inputs.
A successor records the exact superseded logical ID and artifact digest only
as publication evidence in the Rulespec root `supersedes` record. Lineage therefore changes
`artifactDigest`, not logical identity: a correction or repack with identical
logical state preserves `logicalId`, while a changed source state moves it. A
rebuild with identical logical state may still change `artifactDigest` when
sealed timestamps or publication evidence change. Storage accounting alone
changes only the run result. Publication never replaces an existing artifact
destination.

The release carries one generated `release-schema` bundle, canonical
`source-native-scopes`, their closed `source-native-schema` members, one
`source-publication-receipt`, and fixed-partition external payload members. The
external payloads are `source-native-records`, the complete `rendition-index`
of source-stated locators plus nullable source-stated digests and sizes,
`source-acquisition-ledger`, and the immutable source response, page, object,
or source-issued enumeration bytes under `source-acquisition-evidence`. Every
external payload uses a Rulespec `blobRef` in one explicitly injected shared
content-addressed store; the artifact contains no hidden sibling store.

### Payload partitions

The partition policy has exactly 64 buckets, numbered `00` through `63`, and
assigns each UTF-8 identity to the integer value of its SHA-256 digest modulo
64. Record and acquisition-record identities are `sourceRecordId`; rendition
identities use their `sourceRecordId` bucket and sort by
`(sourceRecordId, renditionId)`; acquisition-page identities are
`traversalIndex:pageIndex`. Empty buckets have no member. Members sort by
`(partitionKind, partitionId)`, and rows merge into the source profile's stable
global order. Unchanged buckets therefore retain their exact `blobRef`; a
changed row writes only payload buckets whose canonical bytes changed. Exact
evidence bytes are deduplicated by `blobRef` and form the observation history:
the verifier replays every parsed pre-collapse row from them, so the release
does not duplicate the same bytes in an observation-log member. The release
performs no DocSpec normalization, join, sampling, rendition choice,
disposition, capture, or document processing.
Its complete product-role vocabulary is `source-native-scopes`,
`source-native-schema`, `source-native-records`, `rendition-index`,
`release-schema`, `source-publication-receipt`, `source-acquisition-ledger`,
and `source-acquisition-evidence`. This is the complete required product-role
set; any other role fails. `source-native-records` and `rendition-index` are
absent only when their corresponding receipt counts are zero.
### Schema bundle

The installed spicy-docs package generates and ships the closed bundle at
`spicy_docs/schemas/source_native_release/2.0/` from the same typed records
used by its serializers and parsers. It contains the release, scope,
source-schema-declaration, rendition-index, acquisition-ledger, failure, and
publication-receipt schemas. `releaseSchemaDigest` calls the
installed `rulespec-artifacts` `schemaBundleDigest` over the complete normalized
product-relative path-to-schema map. The same helper computes every
source-native `schemaDigest`; SpicyDocs defines no second `$id` omission,
reference rewriting, bundle ordering, or digest preimage. Duplicate paths,
path escape, unresolved targets, and external references fail. The carried
`release-schema` member contains those exact generated bytes. Declared IDs
and exact file digests remain artifact evidence; an unresolved or external
schema reference fails.

## 3. Acquisition completeness

`sourceStateScope` is `complete-snapshot` or `observed-crawl` and is fixed by
the injected source profile. The build caller cannot supply or override it.
Each profile defines one closed acquisition strategy and its executable
evidence check. Caller-authored snapshot tokens do not exist in this API and
can never prove completeness.

### Enumerated source membership

A source enumeration may claim `complete-snapshot` only when the source reader
enumerates the exact requested membership and pins every member with
source-issued identity evidence. The current Mirrulations proof carries every
sorted object key, listing ETag, nullable source version ID, byte size, and the
exact object bytes fetched with the listed ETag as a precondition. It refuses
a changed ETag, missing or duplicate key, omitted object, mismatched size,
unsupported key, incomplete agency set, or unclassified raw field. The
enumeration evidence is preserved independently from the records selected by
the release's bounded date scope, so an out-of-scope source object remains
evidence but contributes no record. A Regulations.gov document `postedDate`
that is null or present but not canonical-date text is outside every date scope.
Retain it in evidence without a published record, as for other out-of-scope objects.

Each Regulations.gov query covers at most 14,640 inclusive calendar days
(~40 years). The adapter rejects a reversed or wider range before it opens the
source reader.

The range supports source history beginning in the 1990s without scanning the
same objects in many short windows. Changing the allowed range changes
`acquisitionPolicyDigest`; widening the actual scope also changes
`sourceStateDigest`, `logicalId` and `artifactDigest`, because state includes scope.

SpicyDocs stores that proof in deterministic, bounded ZIP members. Each member
contains one canonical manifest followed by the listed object bytes in the same
order. A member carries at most 1,000 objects and 16 MiB of uncompressed object
bytes; a single object may not exceed 16 MiB. Pack indexes start at zero for
each agency, increase without gaps, and end with one terminal pack, including
an empty terminal pack when an agency has no objects. Admission checks the
closed manifest, exact ZIP membership and order, sizes, source identity facts,
object bytes, pack sequence, globally sorted distinct keys, and exact requested
agency set before the release may claim `complete-snapshot`.

### Paginated observations

A paginated strategy starts at the profile's declared initial request, carries
every exact response, and records request key, response digest, source cursor,
next cursor or terminal marker, explicit window indexes, whether its records
are included, and ordered discovered record identities and record digests.
Repeated, missing, forked, or cyclic cursors fail. Bounded stable
reconciliation may compare at most three full traversals and accept only two
consecutive traversals with identical ordered record identities and record
digests. That proves a repeatable observation, not source completeness, so
such a profile is always `observed-crawl`. The release carries every attempted
chain. No matching pair fails publication. An `observed-crawl` exposes its
exact time and query scope and cannot support a downstream completeness claim.

### Federal Register windows

The Federal Register strategy partitions each traversal into ordered date
windows of at most 90 days. A response whose declared `count` is at least
10,000 is ambiguous because the API caps both pagination and that count; the
adapter bisects the window and retries both halves recursively. An ambiguous
single day fails instead of publishing a truncated state. Every capped probe
response remains acquisition evidence with `recordsIncluded = false`;
semantic verification replays the same pre-order split tree from those bytes.
Only uncapped leaf windows contribute records; their explicit window and page
indexes, canonical initial requests, cursor chains, and exact response bytes
are carried as evidence. In each traversal those leaf windows MUST cover the requested date
interval once, in order, with no gap or overlap, and every returned record's
`publication_date` MUST fall inside its leaf. Stable reconciliation compares
the complete ordered union across all leaves, not each leaf independently.

### GAO named products

The GAO product-page profile enumerates one explicit, closed set of sorted,
distinct product IDs. Its `complete-snapshot` claim covers exactly that named
set, not the complete GAO catalog. The migrated campaign observed GAO refusing
its ordinary direct client, so the profile uses a SpicyDocs-owned,
environment-credentialed Zyte raw-HTTP adapter; no credential or provider
request metadata enters release evidence. Each product contributes one
deterministic, bounded ZIP whose first member is a canonical capture manifest
and whose second member is the exact HTML. The
manifest pins the requested and resolved GAO URL, target status, content type,
HTML byte length, and SHA-256 digest. Replay requires one source canonical URL
matching the requested product and exactly one literal `/topics/<slug>` anchor
inside `views-field-field-topic`; missing, duplicate, redirected, oversized, or
changed fields fail the release rather than dropping a product. SpicyDocs
preserves the publisher slug and label but does not map either to RefSpec or
mint a search tag. For `N` product IDs, `H` total HTML bytes, and largest page
`B`, the CLI publication path is `O(N log N + H)` time and `O(N + B)` working
space (the source iterator itself is linear after canonical ordering), with closed
bounds of 1,000 IDs, 8 MiB per page, and 1 GiB total HTML.

### Regulations.gov collections

Regulations.gov documents and dockets are separate source profiles and separate
releases. Each uses one exact Mirrulations enumeration traversal for its own
collection and agency set. Document records preserve their raw
`data.attributes.docketId` and `frDocNum`, withdrawal and withdrawal-reason
fields, topics, file formats, attachments, relationships, and source locators.
Docket records preserve their raw `data.id` and complete docket attributes.
SpicyDocs performs no document-to-docket or Federal Register join; DocSpec owns
those joins using the preserved exact source keys.

The ledger maps every published current record in the accepted traversal
exactly once to its source evidence. Acquisition pages list every discovered
record, including observations discarded by a source-owned current-state
rule. The independent verifier replays the profile parser over all carried
evidence, reconstructs the complete traversal, and recomputes the selection,
ledger, and counts. Ambient network state is never proof of completeness.

## 4. Source state and profile-owned collapse

### Federal Register identity

Federal Register groups by `document_number@publication_date`: the source reuses
numbers across unrelated documents. For example, `00-111` names both a 2000-01-14
rule and a 2000-01-18 notice; both remain distinct records.

Repeated observations of the same pair collapse only when their canonical record
digests agree; differing digests refuse publication. Policies `1.1` (identity)
and `1.2` (crawl limits) retained the same 22 `DOCUMENT_FIELDS`. Current policy
`1.3` adds `full_text_xml_url` and pins all 23 fields and the rendition mappings;
source schema `1.1` admits the optional, nullable XML locator.
`correction_of` was deferred and never added. Requests and replay require the
current field set and exact canonical URL, with no historical field-set map or
separate field-policy selector. See the
[identity decision](../../decisions.md#federal-register-identity-and-fields-version-separately)
for the superseded number-only behavior and SD-24 / DocSpec 0003 provenance.

### Regulations.gov observations

Source-specific observation collapse is acquisition meaning, not a catalog
derivation: every Regulations.gov profile — comments, dockets, and documents —
selects the newest observed row per `/data/id` by `modifyDate DESC NULLS LAST`,
documents falling back to `postedDate` when `modifyDate` is null. Each
preserves the exact source-issued instant in the raw record and normalizes that
instant to UTC only for comparison. The canonical observation sequence sorts by
strict-ASCII record identity, non-null before null, and normalized UTC instant
descending. A repeated `(record identity, normalized UTC instant)` pair
with differing records, including two nulls, fails instead of inventing a
tie-breaker.

For dockets, documents and comments, a repeated pair with an identical canonical
record digest selects one record; raw bytes need not match. Comments joined this
rule on 2026-09-23: a census of every ACF comment (129,052 objects) found 23
repeated pairs, all byte-identical Mirrulations `<id>(1).json` refetch files and
none differing. Count every redundant input
as discarded and retain it in evidence. Differing digests fail as a tie, except
for documents differing only in `openForComment` or `withinCommentPeriod` at one
instant. Those fields are derived at read time, so that difference represents
one observation; any other difference refuses publication.
`inputObservationDigest` consumes that sequence through the installed shared
framed-section digester. Every older observation counts as discarded and stays
in the acquisition evidence; the profile records that count and owns the
executable equivalence test for its public current view.
The thin reader contains none of this policy.

### Digest inputs and ordering

These source digests call the installed `rulespec-artifacts` streaming
framed-section digester; SpicyDocs does not implement or restate its byte
framing.
`inputObservationDigest` declares domain
`spicyregs-input-observations/1`, one `observations` section, and the exact
order above. `sourceNativeSchemaSetDigest` uses domain
`spicyregs-source-schema-set/1` and one `schemas` section.
`sourceStateDigest` declares domain `spicyregs-source-state/1` and the exact
section order `scopes`, `schemas`, `records`, `renditions`. Scopes are closed
records with exactly `scopeId`, `scopeKind`, `sourceSystemId`, and `fields`,
and sort by `scopeId`. Schemas are complete canonical closed schema documents
with exactly one product-relative `schemaName`, one `schemaVersion`, and one
semantic `schemaDigest`; their validation bytes omit any artifact-authored
`$id`, include the source-profile order declaration below, and sort by
`(schemaName, schemaVersion, schemaDigest)`. Current records reference exactly
one admitted `scopeId`, `schemaName`, `schemaVersion`, and `schemaDigest`, and
sort by the complete
source-profile `recordOrderKey`; and rendition rows by
`(sourceRecordId, renditionId)`. Every versioned source schema declares and
digest-binds the record-order field paths, value types, null order, and tuple
comparison. The implemented profiles require strict ASCII record identities,
so SQLite's binary order and the declared UTF-16 code-unit order are identical
for every accepted key. Duplicate order keys fail. The digest covers the complete
canonical item in each section, preserving explicit nulls.
`sourceStateDigest` is therefore recomputed from the complete canonical
source scopes, schemas, current records, and rendition index. The schema-set
digest recomputed from the same `schemas` section MUST equal the product
`spec`; every record and rendition reference must resolve within those closed
sets before either state digest is accepted.
`acquisitionLedgerDigest` uses domain `spicyregs-acquisition-ledger/1`, one
`entries` section, and the complete closed acquisition-ledger records from the
generated release schema, sorted by unique source record identity. Each record
contains the accepted evidence reference and exactly one canonical observation
reference or closed failure. `reconciliationDigest` uses domain
`spicyregs-source-reconciliation/1`, one `pages` section, and the complete
accepted traversal/page records in `(traversalIndex, pageIndex)` order. That
projection includes the request key, response digest, source and next cursors or
terminal marker, explicit window indexes, `recordsIncluded`, and ordered
discovered record identities and record digests. Duplicate keys, a missing
page, or a different declared and observed count fails. Both call the same installed
`framedSectionDigest`; source profiles only supply their closed values and
declared counts.
Historical pre-collapse observations, physical partitioning, compression,
timestamps, and the publication receipt are excluded from logical state but
remain integrity-bound by `artifactDigest`. Each source adapter must classify
every observed upstream column and nested field into its closed versioned
source schema, validate its declared shape, and preserve the exact classified
value including explicit nulls. A new name or incompatible type is refused.
Failures raised by the shared record-classification or scope-validation step
are recorded as deterministic under section 5; source acquisition and
evidence-parser errors still abort. A future schema may preserve new names only
through an explicitly
classified, closed extension map; an open catch-all is not allowed.

## 5. Receipt and semantic verification

Its one `source-publication-receipt` is a closed evidence member containing
exactly `format`, `formatVersion`, `releaseSchemaId`,
`releaseSchemaDigest`, `sourceSystemId`,
`acquisitionPolicyDigest`, `sourceStateScope`, `reconciliationPassCount`,
`reconciliationDigest`, `inputObservationDigest`,
`inputObservationCount`, `publishedRecordCount`,
`discardedObservationCount`, `renditionIndexCount`, `failedRecordCount`,
`deterministicFailureCount`, `transientFailureCount`, `unclassedFailureCount`,
`acquisitionLedgerDigest`, `acquisitionEvidenceCount`,
`discoveredRecordCount`,
`sourceNativeSchemaSetDigest`, `sourceStateDigest`, `verifierId`,
`verifierVersion`, `verifierImplementationId`, `semanticVerdict`, `warnings`,
`partitionPolicy`, `payloadPartitions`, `startedAt`, and
`completedAt`. `partitionPolicy` fixes the algorithm, bucket count, and UTF-8
identity encoding. `payloadPartitions` is bounded to the four partition kinds
times 64 buckets and records each nonempty member's kind, bucket, `blobRef`,
byte size, and record count in strict order.

### Operational byte measurements

Operational byte measurements are returned as
`PublishedSourceNativeRelease.byte_measurements` and as `byteMeasurements` in
the publish CLI result. They are not sealed receipt fields and cannot be
reconstructed by admission. The result contains exactly `payloadBytesRead`,
`payloadBytesReused`, `payloadBytesWritten`, and `publicationBytesWritten`.
`payloadBytesRead` is the sum of distinct external payload bytes presented to
the store by this build. `payloadBytesReused` counts payload bytes whose exact
digest already existed or won a concurrent no-replace race.
`payloadBytesWritten` counts bytes this build actually wrote to store staging,
including a losing concurrent write discarded after verifying the winner.
Consequently reused and written bytes are each bounded by read bytes, but their
sum may exceed read bytes during a race. Existing verified content is reused
without first writing another pending copy.
`publicationBytesWritten` is the exact sum of local scopes, source schema,
release schema, receipt, manifest, and root bytes, calculated after writing.
Metadata construction has no self-size fixed point. Member sizes and hashes
remain sealed evidence, and admission retains its root size limit.

### Verification and failure accounting

Root `supersedes` carries the one
platform succession record when this release replaces the current generation;
the receipt does not repeat it. All listed counts are required and nonnegative,
`semanticVerdict` is exactly `pass` for a publishable release; `warnings` is
a sorted array of closed code/message objects; and the times are canonical
UTC instants with completion not before start. The publisher creates the
receipt in staging. Before publication, an independent product semantic
verifier recomputes the release schema bundle and compares its digest with the
product `spec`, carried member, and receipt. It recomputes the observation
digest and count by parsing retained acquisition evidence and rebuilding the
complete pre-collapse observation sequence. It replays the profile's exact
collapse over that ordered input, compares every current row, proves
`inputObservationCount = publishedRecordCount + discardedObservationCount`,
proves `discoveredRecordCount = inputObservationCount + failedRecordCount`,
recomputes the acquisition-ledger digest and evidence count,
recomputes the rendition and published-record counts, and checks them against
the product state and applicable root aggregates. `failedRecordCount` covers
records that never became canonical observations. Deterministic classification or record-scope
failures remain in the acquisition ledger and retained source evidence; they
contribute no published record. A release may publish with these failures when
the per-class counts reconcile with `failedRecordCount` and both transient and
unclassed counts are zero. Admission applies this equation even when
`failedRecordCount` is zero; missing class counts are refused. Transport, page parsing, and other acquisition errors
still abort; a credential refusal never becomes a deterministic source record.

Full verification independently reclassifies retained records and compares
both successful and rejected rows. A rejected record is identified by its
zero-based traversal, page, and position in that page's results. Replay derives
that position from retained bytes and compares the exact ledger identity,
observation reference, deterministic class, `source.record-unclassifiable`
reason, and page evidence references. Omitted, added, duplicated, or relinked
failures are refused even when their member hashes and receipt counts agree.
Transport outcomes cannot be established by reclassifying retained pages and
remain outside an accepted release. This check deliberately does not reuse the
writer's failure-ledger construction.
Bounded consumer admission checks the sealed counts and accepted verifier pins
without semantically replaying the ledger. Structural admission still reads and
hashes payload bytes, so bounded memory does not imply fixed total I/O. Only the
current installed schema bundle and current profile policy version are accepted.
The verifier refuses an unsupported release format or role, unknown release
field, missing required evidence, or inconsistent page, ledger, schema, receipt,
or state data. It recomputes and checks the exact schema-set and source-state
digests, and the receipt pins its verifier identity, version, and
implementation pin. Rulespec's root `producer` identifies the released
publisher implementation and verifier. The producer gate resolves those pins
before running the verifier; consumer admission compares them with the
receipt and installed or explicitly allowed verifier. An unresolved pin,
non-pass verdict, or mismatched receipt, root, policy, schema-set, or state
pin blocks publication.

The verifier checks the profile-fixed `sourceStateScope`, pass count, and
reconciliation digest against the carried acquisition evidence. A
`complete-snapshot` without the injected profile's complete source-enumeration
proof fails. Identical consecutive paginated traversals remain
`observed-crawl`; they never upgrade themselves to complete. An
`observed-crawl` may feed a DocSpec catalog, but its reader exposes that scope
and the catalog's requested universe is only the exact carried policy row
family. DocSpec preserves `observed-crawl` and cannot claim source-wide
completeness or source-wide omissions.

Generator tests compare typed records, serializers, parsers, generated
schemas, and installed bytes exactly. A namespace-only `$id` change preserves
`releaseSchemaDigest` while moving artifact evidence; a changed validation
rule moves the digest and logical ID. Consumer fixtures reject a missing
schema member or any receipt/root/schema mismatch.

## 6. Bounded reader and dependency inversion

SpicyDocs exposes a separate bounded `SourceNativeReleaseReader`. It performs
Rulespec structural admission, compares the sealed receipt and verifier pins
with the root, requires an injected Rulespec `BlobSource` for every external
member, and then streams closed-schema rows in stable order with at most 64
payload streams open for a row family. It does not replay observation collapse
or recompute the corpus-wide semantic state on consumer open. DocSpec's
source-native adapter receives that reader
through its `SourceNativeRecordSource` port; the DocSpec core imports neither
SpicyDocs nor a concrete store. Tests prove a changed member or receipt fails
before the first row and a valid consumer starts after bounded structural and
receipt checks without a second semantic pass.

The reader is the only SpicyDocs integration surface required by DocSpec.
DocSpec owns its optional outer adapter and receives the reader through its
`SourceNativeRecordSource` port. Neither product imports the other's core.

### Command and storage boundary

The `spicy-docs-source-native` operator command is a thin outer adapter. Its
`publish` command selects one source and its explicit selectors: inclusive
`--since` and `--until` dates for date-scoped collections, repeated `--agency`
values where required, or exact `--product-id` values for GAO. The
[operator guide](../../cli.md#publish) lists the supported source names and
selector combinations. Publication requires an immutable destination, an
explicit persistent `--blob-store`, and an implementation identity, and runs
the same injected publisher and producer verifier. Release and store paths must be distinct and neither may contain the
other. The store atomically creates digest-addressed files without replacement,
verifies an existing digest on reuse or `EEXIST`, and retains verified orphan
blobs after a failed root publication so a later build can recover them. A
failure exposes no artifact root. Source-name dispatch exists only at this
command's composition edge. Its `verify` command requires the explicit blob
store, both expected artifact pins, and an accepted verifier implementation,
then replays the full product verifier with the exact selected profile. Each
command writes one canonical JSON result to standard output, or one canonical
JSON error to standard error, so automation does not scrape log text. The
command defines no catalog, selection, join, or document-processing behavior.

**Current implementation gap:** handled failures end stderr with a JSON error,
but diagnostic or retry lines may precede it. Argument errors and unexpected
exceptions are not structured-error results. See [command output](../../cli.md)
for the current behavior; the single-result requirement above remains the target.

## 7. Public publication profile

The public profile preserves bulk-data access without creating another logical
record model. One `spicyregs-public-table` Rulespec artifact pins exactly one
admitted source-native release and faithfully projects its current rows into
bounded Parquet members. Rulespec supplies root identity, manifests, member
digests, and admission. SpicyDocs supplies only the source-specific columns,
primary key, total order, and physical partition choice.

The implemented profiles preserve the existing Federal Register, Regulations.gov
document, docket, and comment column sets. Comments use the Hive partition
`agency_code=<value>` and retain the source release's one-current-row-per-comment
semantics: newest `modifyDate`, null last, with an equal-version conflict refused
before this projection. Documents and comments retain their established
`text_content` and `text_extraction_status` columns, but a faithful source view
sets them to null because source acquisition does not create derived text.
DocSpec must own any future body-text result and the catalog row that selects it.

Federal Register public projection `1.1` declares
the compound primary key `["document_number", "publication_date"]`, preserving
the existing columns and their types. It checks native identity using the
Federal Register identity function and keeps both rows when a document number
occurs on different dates. Compound-key uniqueness uses canonical JSON values,
not delimiter concatenation. All key columns participate in the declared total
order. Other profiles keep scalar `primaryKey` metadata. Federal Register
projection `1.1` is the single supported table profile; the former `1.0`
projection is no longer supported. See the
[current projection decision](../../decisions.md#federal-register-public-tables-preserve-composite-identity).

### Publish and read tables

Publication uses a disk-backed sort and duplicate-key check, bounded Arrow
batches, a configured maximum row count per member, Parquet 2.6 with Zstandard,
and an atomic no-replacement directory publish. One self-describing zero-row
member represents an empty table. The producer gate reads every member and
checks its exact Arrow schema, row count, global primary-key uniqueness, Hive
partition, declared order, and root accounting. Consumer open performs
Rulespec admission plus closed product-shape checks; it does not rerun the
producer's corpus-wide semantic pass.

Given an admitted artifact, the reader hands its exact member locations to
DuckDB's native Parquet reader. An injected locator may use local paths or
anonymous immutable HTTPS URLs, so DuckDB performs its standard range reads and
Hive pruning without a query service. SpicyDocs publishes immutable Parquet
generations; consumers own any catalog registration or mutable table updates.
The former first-snapshot Iceberg attachment helper is retired because it had
no operational caller and did not implement SpicyRegs' mutable publishing flow.

This public-table format defines no registry, mutable merge/upsert path,
row-hash index, latest-pointer algorithm, compatibility command, or object-store
replacement protocol. Callers select an exact immutable generation through its
artifact pin and address. SpicyRegs owns its mutable public-data pipeline
independently; these source-table changes do not replace that pipeline or its
public URLs. A selected future handoff needs retained-data comparison,
dependent-reader checks, and explicit cutover evidence.

## 8. Federal Register profile

The Federal Register profile preserves the predecessor's measured ingest value
without carrying forward its catalog implementation. Its Git-pinned baseline
covers 1,004,233 distinct document numbers from 1994-01-03 through 2026-07-23,
448 observed agency slugs, 5,871 rows with no agency, every raw RIN value, all
three source-stated rendition locator fields, native titles, and raw
`topics_json`. The current release may grow beyond that baseline, but it MUST
NOT silently lose a baseline row or field.

Every record requires the source's `document_number` and canonical
`publication_date`; together they form `document_number@publication_date`, as
amended in section 4. A missing or malformed value at the shared classification
or record-scope boundary becomes a retained deterministic failure under section
5, with no published record. The date remains in the native record; SpicyDocs
does not copy it into a second generic version field.

The profile preserves agency names and slugs exactly and reports absence. It
does not require or invent an agency crosswalk. It preserves malformed RIN text
only as a source-native fact plus a field diagnostic. Its rendition index
records every stated `html_url`, `pdf_url`, `body_html_url`, and
`full_text_xml_url`, including null locators, without choosing a DocSpec
candidate. Missing and explicit null fields remain distinct in source records;
both emit null rendition locators. A constructed body URL cannot replace a
publisher-stated field.

The predecessor found `topics_json = []` on 890,013 rows. SpicyDocs preserves
those arrays exactly and makes no claim that the publisher declared no topics.
DocSpec alone owns any catalog interpretation and the corresponding live-source
measurement.

## 9. Conformance

The current phase gate builds and independently verifies fixture releases for
Federal Register records and separate Regulations.gov document, docket, and
comment collections. It also builds all four public profiles, opens local and
anonymous HTTP-range members through DuckDB, checks comment Hive pruning and
newest-comment behavior. Its live source check is deliberately
bounded to one Federal Register day. These checks do not prove corpus-wide
completeness, historical baseline parity, a live HTTPS/object-store deployment,
or production cadence.

The final migration gate uses a clean installed SpicyDocs wheel to build and
independently verify fixture and exact real-data releases for the retained
mirror index, Regulations.gov documents, dockets, and comments, Federal
Register records, and every other published source table retained by the
platform value inventory. A deferred source still needs an explicit release
profile, owner, user-access disposition, and no-loss test before its predecessor
publisher can stop.

A release copies or immutably snapshots every metadata input required to verify
its source state. Rendition bodies may remain external when the source publishes
only a locator. A source-stated digest or size is preserved and enforced when
present. New source columns fail until the versioned source schema classifies
them. Repeating identical logical records preserves logical identity; any byte
change remains visible in exact artifact identity.

Public-profile tests MUST open an immutable generation through Rulespec
admission, read its exact local and anonymous range-served Parquet members with
DuckDB, preserve all declared columns, and reproduce comments partition pruning
and newest-comment collapse. They refuse tamper, repeated primary keys,
out-of-partition rows, unbounded rows or members, schema and row-count drift,
replacement of an immutable destination. External cutover adds a live immutable
HTTPS range test and smoke tests for each retained anonymous consumer. Catalog
integration, if selected by a consumer, needs its own snapshot/update checks.

### Refusal and determinism checks

Role-closure tests reject an extra role. Comment fixtures cover equal and null
timestamp conflicts, multiple source versions, shuffled enumeration order,
digest/count replay, deterministic output order, schema drift, and a one-row
mutation that changes the digest. Document and docket fixtures extend that
executable coverage to the document `postedDate` fallback, offset-equivalent
instants that tie, a repeated docket instant, and a repeated pair with an
identical canonical record digest but differing raw bytes (key order alone)
at one instant selecting one published record instead of tying,
with every redundant input counted as a discarded observation and retained
in acquisition evidence.
Generation tests refuse broken superseded identities, an empty successor reason,
unrelated pointer replacement, and a byte-for-byte no-op successor. A
physical-only correction preserves logical identity and moves exact artifact
identity.

Source-native storage tests prove exact unchanged-bucket `blobRef` reuse,
changed-bucket-only writes, zero payload writes for a physical rebuild,
truthful byte accounting, corrupt-`EEXIST` refusal, safe concurrent publication,
recoverable orphan content, path-containment refusal, no root after failure,
and the fixed 64-stream reader bound.

### Scale and baseline gates

A sealed scale run publishes and verifies the accepted 3.9 GB input with peak
resident memory at most 8 GiB and temporary disk at most 16 GiB. It records
wall time, output bytes, member count, and rows per member without requiring a
custom changed-file or row-hash mechanism. Any later incremental optimization
must preserve the standard Rulespec `blobRef`, artifact-store, or Iceberg
identities and reproduce the same admitted rows; it cannot introduce a
SpicyRegs registry or mutable merge.

Federal Register tests replay the pinned baseline and prove row and primary-key
completeness, native-title placement, exact agency and malformed-RIN source
values, nonfatal per-field diagnostics, rendition-locator completeness, the
5,871-row missing-agency count, and preservation of the 890,013 unresolved empty
topic arrays. A current corpus may change measured counts only through a newly
pinned input and dated difference receipt. One malformed RIN, absent agency,
missing rendition, or empty topic array MUST NOT abort or silently remove an
unrelated record.

## Current wheel acceptance boundary

Qualify the exact producer wheel after changing source format or admission.
DocSpec owns its receiving integration and partial-input policy in D10; a passing
SpicyDocs build does not establish consumer adoption. The
[task ledger](../../simplification-todo.md#merged-baseline-and-evidence) records
qualified baseline wheels and local receiving evidence separately from release
and deployment status.
