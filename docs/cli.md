# Publish, verify, and inspect

Run `uv run --frozen spicy-docs-source-native --help` in a checkout; each
subcommand accepts `--help`. Installed packages use `spicy-docs-source-native`
or `python -m spicy_docs.cli.source_native`.

| Result | Stream | Exit |
| --- | --- | --- |
| Success JSON | stdout | 0 |
| Handled operational error JSON, after any retry logs | stderr | 1 |
| Argument usage error | stderr | 2 |

Default HTTPX/S3 operations need `acquisition`; GAO's standard-library Zyte
transport needs its credential only. Parquet parsing/full replay and public-table
commands need `public-table`, even with injected acquisition. Core inspection,
JSON/HTML replay, and injected JSON/HTML acquisition need neither extra.
`uv sync --frozen --all-extras` installs both for development. See
[installation](installation.md) or try the credential-free
[offline example](../examples/offline_release.py).

## publish

Acquire evidence, stage and fully verify a release, then publish its directory once:

```sh
uv run --frozen spicy-docs-source-native publish \
  --source federal-register --since 2026-04-13 --until 2026-04-13 \
  --destination /new/release --blob-store /persistent/blobs \
  --implementation-id 'git+https://example.test/spicy-docs@<full-commit>'
```

`--source`, `--destination`, `--blob-store`, and `--implementation-id` are required.
Use the actual producer revision. The destination must be new and separate from
the blob store, with neither nested inside the other.

| Source | Required selectors | Live access and scope |
| --- | --- | --- |
| `federal-register` | `--since`, `--until` | Inclusive publication dates; Federal Register HTTPS API; no agencies/products |
| `regulations-documents` | Dates and repeated `--agency` | Posted dates; anonymous Mirrulations S3 |
| `regulations-dockets` | Dates and agencies | Modified dates; anonymous Mirrulations S3 |
| `regulations-comments` | Dates and agencies | Posted dates; anonymous Mirrulations S3 |
| `spicy-regs-public-comments` | Agencies | Whole community-table partitions over HTTPS; dates invalid |
| `gao-product-pages` | Repeated `--product-id` | Exact products through Zyte; dates/agencies invalid |

Dates use `YYYY-MM-DD`. Agencies are sorted/deduplicated; duplicate GAO IDs are
refused. GAO requires environment variable `ZYTE_TOKEN` and preserves literal
topics for named products. See [source scope and supply rules](source-workflows.md#know-what-each-source-supplies).

Federal Register and public-table HTTP retry transient errors, 429s, and server
failures with bounded jittered delays; most other 4xx abort. Mirrulations uses
its own retry/enumeration rules. Credential refusals stop the run. Follow
[credential and resume rules](../AGENTS.md).

Publication uses source-native format 2.0; opening historical formats or unsupported
producer identities is refused. Success includes invocation-only `byteMeasurements`,
outside the sealed release. Later inspection/verification cannot reconstruct
these storage counters; see [units and limits](releases.md#storage-and-recovery).

## verify

Replay retained evidence without source requests, using the expected artifact
pin and an independently accepted producer-verifier identity:

```sh
uv run --frozen spicy-docs-source-native verify \
  --source federal-register --release /existing/release \
  --blob-store /persistent/blobs \
  --logical-id '<logicalId from publication>' \
  --artifact-digest '<artifactDigest from publication>' \
  --accepted-verifier-implementation-id '<trusted implementation ID>'
```

Every shown option is required. Repeat the accepted-ID option to trust multiple
implementations. Choose IDs through deployment policy, independently of artifact
claims. Verification checks scope, schemas, evidence, reconstruction, ordering,
selection, failure accounting, and source-state digest.

## inspect

Check a retained release's pin and accepted verifier, then report its outcome
and a bounded failure sample. Use [verify](#verify)'s required options with
`inspect` as the subcommand.

`--failure-limit` defaults to 20; zero reports outcomes only. Admission hashes
payloads without reconstructing source records. See the
[inspection example and field definitions](source-native-outcomes.md#inspect-failures).

## publish-public-table

Export an admitted source release to immutable flat Parquet. Publication checks
every output row and retains the input release pin; preserve source evidence
separately.

```sh
uv run --frozen spicy-docs-source-native publish-public-table \
  --table federal-register --source-release /existing/release \
  --source-blob-store /persistent/blobs \
  --source-accepted-verifier-implementation-id '<trusted source implementation ID>' \
  --destination /new/public-table \
  --implementation-id 'git+https://example.test/spicy-docs@<full-commit>'
```

Every shown option is required. Repeat the source accepted-ID option as needed.
Tables: `federal-register`, `regulations-documents`, `regulations-dockets`,
`regulations-comments`. GAO and captured community comments have no table output
profile. The destination must be new and separate from the source release; the
source release and blob store must also be separate.

Federal Register table version `1.1` uses existing `document_number` and
`publication_date` columns as compound identity. Reused numbers on different dates
stay separate. Columns are unchanged; projection version and logical identity changed.

## verify-public-table

Check table admission: pin, structure, profile, member layout, and accepted verifier.
This command neither reprojects source records nor runs the full Parquet-row gate;
library `verify_public_table_release()` adds the full row check.

```sh
uv run --frozen spicy-docs-source-native verify-public-table \
  --table federal-register --release /existing/public-table \
  --logical-id '<logicalId from publication>' \
  --artifact-digest '<artifactDigest from publication>' \
  --accepted-verifier-implementation-id '<trusted table implementation ID>'
```

Every shown option is required. Table choices match publication; repeat accepted
IDs as needed. Federal Register selects `1.1`; `1.0` is unsupported. See the
[compatibility decision](decisions.md#federal-register-public-tables-preserve-composite-identity).

## Campaigns, replay, and source tools

Start with module help and the [operation index](../tools/README.md#related-operations):

```sh
uv run --frozen python -m spicy_docs.cli.campaign --help
uv run --frozen python -m spicy_docs.sources.federal_register.replay --help
uv run --frozen python -m spicy_docs.sources.congress.crs_summaries --help
```

Campaigns publish agency-scoped releases with attempt logs and external receipts.
Preview first:

```sh
uv run --frozen python -m spicy_docs.cli.campaign \
  --agency EPA --window-since 2021-01-01 --window-until 2025-12-31 \
  --destination-root /campaign/releases --blob-store /persistent/blobs \
  --implementation-id '<current producer implementation ID>' \
  --accepted-verifier-implementation-id '<trusted producer-verifier ID>' \
  --dry-run
```

Remove `--dry-run` to publish. Each publisher runs mandatory full replay before
publication. The campaign then checks expected pin, metadata, agency/window,
and trusted verifier through admission, hashing all payloads with bounded memory.

Resume uses an interruptible `inspect --failure-limit 0` child for that admission.
A matching release triggers neither republication nor replay. Inspection writes
the attempt log without a separate success receipt. Accepted IDs may repeat;
`--implementation-id` alone grants no trust.

Keep `receipts/*.json` with pins and `collectionOutcome`:

| Resume condition | Action |
| --- | --- |
| Missing, malformed, or misdirected receipt | Rename old evidence aside, then retry |
| Valid receipt with mismatched pin/scope, damaged metadata, or unaccepted verifier | Fail closed; preserve release and receipt for inspection |
| Changed agency window | Choose a new campaign root |

Explicit [verify](#verify) still performs full reconstruction with the external
pin and trusted ID. Former `--verify`/`--no-verify` switches and separate verify
receipts are removed; resume requires a publish receipt with `collectionOutcome`.

Federal Register replay publishes saved responses under the current profile
without source requests. CRS acquisition writes resumable Congress.gov summaries
and requires an explicit credential file. [Corpus diagnostics](../tools/README.md)
live under `tools/analysis/`; [maintenance](../scripts/README.md) lives under
`scripts/`. The retired catalog has no generation command; use
[source references](source-reference.md).

## Output and failures

Keep success fields with the run receipt:

| Result | Fields |
| --- | --- |
| All | `ok`, `command`, absolute `release`, `logicalId`, `artifactDigest`, `sourceStateDigest`, `sourceStateScope`, `sourceSystemId` |
| Source release | `source`, `sourceSystemVersion`, `sourceNativeSchemaSetDigest`, `collectionOutcome` |
| Inspection | Failure sample and limit |
| Public table | `table`, `tableName`, `maxRowsPerMember` |

Handled failures contain `ok: false`, `command`, and `error` (`code`, `message`).
Codes: `destination-exists`, `acquisition-failed`, `release-invalid`,
`transport-failed`, `dependency-missing`, `operation-failed`. Preserve the message.
Missing dependencies need setup; an existing immutable destination needs a new
path. Acquisition failure does not establish source absence.

After acquisition starts, errors may include `failedAcquisition`. Append
`2> /path/to/run-error.log` to publication to retain stderr. For a handled error
(exit 1), **only the final stderr line is the JSON report**; retry logs may precede it:

```sh
tail -n 1 /path/to/run-error.log > /path/to/run-error.json
```

Argument errors, interruption, and unhandled tracebacks lack this structured
report. `response.status: retained` means `blobRef` names exact stored bytes.
The report and blob remain separate from the source error and are not a release.
Read retained bytes offline:

```python
import json
from pathlib import Path
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

failure = json.loads(Path("/path/to/run-error.json").read_text())
response = failure["failedAcquisition"]["response"]
if response["status"] == "retained":
    store = LocalSourceNativeBlobStore(Path("/path/to/blobs"), create=False)
    with store.open(response["blobRef"]) as source, open("refused-response.bin", "xb") as output:
        output.write(source.read())
else:
    print(response["reason"])
```

| Evidence condition | Report behavior |
| --- | --- |
| Fully received empty bytes | Retainable exact evidence |
| Oversize | `response-byte-limit` or `acquisition-byte-limit`, observed size when known; never a truncated capture |
| No target body reached the adapter | May report `transport-unavailable` |
| Zyte target reflects known credentials | `credential-suppressed`; provider JSON/auth headers are never retained |
| Diagnostic storage fails | `storage-failed`; original acquisition error preserved |

Shared pages are bounded to 24 MiB; GAO HTML to 8 MiB/page and 1 GiB/acquisition.
`retainedPageEvidence` lists bounded previously written context with total count
and truncation flag. Earlier responses do not become evidence of a later failed request.
