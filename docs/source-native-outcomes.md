# Understand a collection outcome

A valid source release can contain accepted records, rejected records, or no
records. `SourceNativeReleaseReader.collection_outcome` exposes that distinction
using the release's existing scope and publication receipt. `publish`, `verify`,
and `inspect` return the same mapping as `collectionOutcome` in their JSON output.
No new status file or release format is involved.

## What the outcome establishes

`requestedScope` contains the exact selectors recorded for this collection, such
as dates, agencies, or GAO product IDs. `sourceStateScope` names the source
profile's coverage claim. For example, `observed-crawl` records an observed crawl;
it does not promise a frozen snapshot of every publisher document.

`recordOutcome` describes records from the accepted traversal:

| Value | Meaning |
| --- | --- |
| `empty` | The accepted traversal supplied no record observations from its included pages. |
| `no-record-rejections` | Records were observed and none failed source-record validation. |
| `partial-rejection` | Some records were published and some were rejected. |
| `total-rejection` | Records were observed, but all failed source-record validation. |

**Empty input does not prove source absence.** The outcome concerns the recorded
request and observed response. It says nothing about an unrequested collection.
An acquisition or transport failure that prevents publication produces a command
error, not an `empty` release. A deterministic record rejection concerns that
acquisition attempt; a later request may succeed.

For all three commands, `ok: true` means the command completed its admission or
verification checks. Read `collectionOutcome` to determine what happened to the
records. A release with total record rejection can still pass those checks.

## Read the counts

The main counts describe the **accepted traversal**, not the sum of discovery
passes. They use these exact receipt names:

| Field | Unit |
| --- | --- |
| `discoveredRecordCount` | Record observations from included acquisition pages, including rejections with invalid or unestablished scope. It is not a count of unique published records. |
| `inputObservationCount` | Valid observations considered for selection, including multiple observations of one source identity. |
| `publishedRecordCount` | Selected source records. |
| `failedRecordCount` | Rejected record observations retained as failure ledger entries. |
| `discardedObservationCount` | Valid observations superseded during selection, such as older observations of the same identity. These are not validation failures. |

The counts reconcile as follows:

```text
discoveredRecordCount = inputObservationCount + failedRecordCount
inputObservationCount = publishedRecordCount + discardedObservationCount
```

The outcome also includes the receipt's `deterministicFailureCount`,
`transientFailureCount`, `unclassedFailureCount`, `acquisitionEvidenceCount`,
`reconciliationPassCount`, `renditionIndexCount`, and `warnings`. Evidence and
reconciliation counts describe retained acquisition evidence and passes;
renditions are listed document formats, not additional source records. These
counts do not add to the equations above. Current publication permits recorded
deterministic record failures; transient or unclassified acquisition failures
prevent an accepted release.

Each property access returns a fresh mapping, including fresh selectors and
warnings, so changing the returned value does not change later reads.

## Inspect failures

Use the release pin and the verifier implementation you already accept:

```sh
uv run spicy-docs-source-native inspect \
  --source federal-register \
  --release /data/releases/federal-register \
  --blob-store /data/blobs \
  --logical-id "$LOGICAL_ID" \
  --artifact-digest "$ARTIFACT_DIGEST" \
  --accepted-verifier-implementation-id "$IMPLEMENTATION_ID" \
  --failure-limit 20
```

The JSON output contains `collectionOutcome`, `failureLimit`, `failures`, and
`failuresTruncated`. The default limit is 20. Set `--failure-limit 0` to report
the outcome alone. `failuresTruncated: true` means more failures are recorded
than are included in the response.

For Python callers, `reader.iter_failures(limit=100)` streams existing failure
ledger rows in `sourceRecordId` order. Each row retains `sourceRecordId`,
`observationRef`, `evidenceBlobRef`, and the nested `failure` with its `class`,
`reasonCode`, and `evidenceDigest`. Use the references to inspect retained source
evidence. Failure entries do not invent a valid publisher identity when the
source record could not be classified.

```python
from contextlib import closing

print(reader.collection_outcome)
with closing(reader.iter_failures(limit=10)) as failures:
    for failure in failures:
        print(failure)
```

The reader admits the pinned artifact under the supplied source profile and
accepted verifier implementation. Admission hashes all retained payload members;
it uses bounded memory, but its I/O grows with release size. `inspect` does not
repeat source interpretation. Use `verify` for independent source replay.

Reading the outcome after admission reopens no payloads. Failure iteration uses
the existing merge of at most 64 partition streams and bounded rows. It stops at
the requested number of failures and closes its streams; a zero limit or a
sealed zero failure count skips the ledger. Finding a late failure can still
require scanning the whole ledger. Callers that stop iteration early should
close the iterator, as the example does.
