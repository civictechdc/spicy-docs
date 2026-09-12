# Understand a collection outcome

**A valid release can contain accepted records, rejected records, or no records.**
`SourceNativeReleaseReader.collection_outcome` reads that distinction from the
existing scope, policy, and receipt. `publish`, `verify`, and `inspect` expose the
same mapping as `collectionOutcome`; there is no separate status format.

## What the outcome establishes

| Field | Read it as |
| --- | --- |
| `requestedScope` | Exact recorded selectors: dates, agencies, or product IDs |
| `sourceStateScope` | The profile's coverage claim, qualified by its policy |
| `acquisitionPolicy` | `initialQueryScope`, discovery `strategy`, bounds, selection, and `coverageLimits` |
| `acquisitionPolicyId`, `acquisitionPolicyVersion` | Identity of that policy |
| `traversalAcceptance` | Rule used to accept the collected passes |

The reader regenerates policy values from the supplied profile and checks their
digest against `acquisitionPolicyDigest`. Changed code cannot silently describe
an old release with different policy values.

| Source | Coverage limit |
| --- | --- |
| Federal Register | Two consecutive crawls agree within exact date selectors; capped windows split. This is stable observation, not a frozen publisher version. |
| GAO | `complete-snapshot` covers exactly the requested IDs, each captured separately. Other IDs are unrequested. |
| Mirrulations | `complete-snapshot` covers the observed agency/collection enumeration. Dates are selected afterward. Each GET uses the listed ETag as `IfMatch`; the listing is not frozen at one upstream instant. |
| Community comments | One `observed-crawl` probes contiguous parts from zero and stops at the first missing part. Later parts are unrequested. Terminal markers are retained; missing-part HTTP responses are not. |

`recordOutcome` describes only the accepted traversal:

| Value | Meaning |
| --- | --- |
| `empty` | Included pages supplied no record observations |
| `no-record-rejections` | Records were observed; none failed source-record validation |
| `partial-rejection` | Some observed records were published and some rejected |
| `total-rejection` | All observed records failed source-record validation |

Keep these distinctions:

- **Empty accepted input does not prove source absence.** It describes the
  recorded request and response, saying nothing about unrequested collections.
- An acquisition/transport refusal leaves the request unresolved and supplies
  no accepted outcome or partial release.
- A deterministic record rejection concerns this attempt; a later request may
  succeed. A failure does not invent a valid publisher ID when identity failed.
- `ok: true` means the command passed its admission or verification checks.
  Read the outcome for record results; even total record rejection may pass.

The API reports collection facts, not a result for every possible document ID.

## Read the counts

Counts describe the **accepted traversal**, not the sum of discovery passes:

| Receipt field | Unit |
| --- | --- |
| `discoveredRecordCount` | Included-page record observations, including rejections with invalid/unestablished scope; not unique published records |
| `inputObservationCount` | Valid observations considered for selection, including repeated source identities |
| `publishedRecordCount` | Selected source records |
| `failedRecordCount` | Rejected observations retained in the failure ledger |
| `discardedObservationCount` | Valid observations superseded during selection; not validation failures |

```text
discoveredRecordCount = inputObservationCount + failedRecordCount
inputObservationCount = publishedRecordCount + discardedObservationCount
```

The receipt also supplies `deterministicFailureCount`, `transientFailureCount`,
`unclassedFailureCount`, `acquisitionEvidenceCount`, `reconciliationPassCount`,
`renditionIndexCount`, and `warnings`. Evidence/pass counts describe retained
acquisition work; renditions list formats, not additional records. They do not
add to those equations. Publication permits deterministic record failures;
transient or unclassified acquisition failures prevent acceptance.

Each property read returns a fresh mapping, including selectors, policy values,
and warnings. Editing it does not change later reads.

## Inspect failures

Use the retained pin and an independently accepted verifier implementation:

```sh
uv run --frozen spicy-docs-source-native inspect \
  --source federal-register \
  --release /data/releases/federal-register \
  --blob-store /data/blobs \
  --logical-id "$LOGICAL_ID" \
  --artifact-digest "$ARTIFACT_DIGEST" \
  --accepted-verifier-implementation-id "$IMPLEMENTATION_ID" \
  --failure-limit 20
```

JSON contains `collectionOutcome`, `failureLimit`, `failures`, and
`failuresTruncated`. The default limit is 20; zero returns only the outcome.
`failuresTruncated: true` means the ledger contains additional failures.

Python `iter_failures(limit=100)` streams rows in `sourceRecordId` order. Each
retains `sourceRecordId`, `observationRef`, `evidenceBlobRef`, and nested `failure`
fields `class`, `reasonCode`, and `evidenceDigest`:

```python
from contextlib import closing

print(reader.collection_outcome)
with closing(reader.iter_failures(limit=10)) as failures:
    for failure in failures:
        print(failure)
```

Admission checks the pin, profile, accepted verifier, and hashes of all payload
members. Memory is bounded; I/O grows with release size. `inspect` performs no
source replay; use `verify` for that check. Reading the admitted outcome reopens
no payloads.

Failure iteration merges at most 64 partition streams with bounded rows. It stops
and closes at the limit; zero limits or sealed zero counts skip the ledger.
Finding a late failure may scan the whole ledger. Close an iterator you stop early.

## Inspect record evidence

`record_evidence(source_record_id)` returns the selected successful observation's
`sourceRecordId`, `observationRef`, `evidenceBlobRef`, and `failure: None`.
`None` means no published success for that identity in this release, not source
absence. Use `iter_failures()` for failure-only identities. This lookup excludes
discarded observations and earlier passes.

For a bulk join, use `iter_record_evidence()` alongside `iter_records()`. Both
streams use source-record identity order. The evidence iterator reads each ledger
partition once and excludes failure rows; compare identities while joining and
fully exhaust both streams to check membership and partition counts. Close either
iterator when stopping early. Repeating `record_evidence()` for every row rescans
partitions and should remain a single-record inspection path.

```python
evidence = reader.record_evidence(source_record_id)
if evidence is not None:
    exact_bytes = reader.read_evidence(evidence["evidenceBlobRef"], max_bytes=8 * 1024 * 1024)
```

Lookup scans at most one identity-bucket ledger partition, checks rows/order/bucket,
and closes before returning. Memory is row-bounded, but the partition may be large.
It relies on the admitted immutable ledger, producer, and profile; it neither
replays acquisition nor rechecks all bytes after storage changes.

`read_evidence()`:

- Accepts only evidence references declared by this admitted release. Unknown,
  record, table, and ledger references are refused.
- Refuses declared sizes above `max_bytes` before opening storage, then checks
  returned size and digest. Storage closes on success or failure.
- Defaults to the 24 MiB release evidence bound. `max_bytes` must be an integer
  from zero through that bound; zero permits only admitted zero-byte evidence.
- Accumulates at most the requested limit plus one detection byte. Oversize
  evidence is refused, never truncated. Injected storage may do integrity reads
  of its own on opening.

Evidence may be JSON or a source ZIP, not the body named in a rendition.
Use the source parser; see the [GAO example](sources/gao.md#read-a-topic-and-its-evidence).
Refused acquisitions have no admitted reader. Their `failedAcquisition` references
belong to the [failed-run report and blob store](cli.md#output-and-failures).
