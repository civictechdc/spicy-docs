# Publish, verify, and inspect

Run `uv run --frozen spicy-docs-source-native --help` from a developer checkout.
Each command also accepts `--help`. The commands below write a JSON success
object to stdout (exit 0), or a handled operational error to stderr (exit 1).
Argument syntax errors use argparse's ordinary usage output and exit 2.

For an installed package, `spicy-docs-source-native` is the same entry point.
Public-table commands require the `public-table` extra (PyArrow); `uv sync --frozen`
includes it through the development dependencies. Other commands load it lazily.
The [offline example](../examples/offline_release.py) needs no credentials.
Library and module ownership are in the [architecture map](architecture.md).
The module form of this command is `python -m spicy_docs.cli.source_native`.

## publish

Acquire one source, retain exact evidence in the persistent blob store, stage
and producer-verify a release, and publish its directory once.

```sh
uv run --frozen spicy-docs-source-native publish \
  --source federal-register --since 2026-04-13 --until 2026-04-13 \
  --destination /new/release --blob-store /persistent/blobs \
  --implementation-id 'git+https://example.test/spicy-docs@<full-commit>'
```

Use the actual producer revision in place of the example implementation ID.
`--source`, `--destination`, `--blob-store`, and `--implementation-id` are
required. The destination must be new; destination and blob store must be
separate, with neither nested inside the other.

The success result includes `byteMeasurements` for this invocation: payload
bytes read, reused, and written to storage staging, plus the resulting local
metadata size. Staging writes include a discarded write that lost a concurrent
publication race.
These operational measurements are outside the sealed release and are not
returned by later verification or inspection. See [storage reporting](releases.md#storage-and-recovery)
for their units and limits. Publication uses the current source-native format
2.0; historical release formats and producer identities are refused on opening.

| Source | Required selectors | Meaning and live access |
| --- | --- | --- |
| `federal-register` | `--since`, `--until` | Closed publication-date window, Federal Register HTTPS API; no agency or product selector |
| `regulations-documents` | Dates and one or more `--agency` | Publication-date window, anonymous Mirrulations S3 |
| `regulations-dockets` | Dates and agencies | Modified-date window, anonymous Mirrulations S3 |
| `regulations-comments` | Dates and agencies | Posted-date window, anonymous Mirrulations S3 |
| `spicy-regs-public-comments` | Agencies | Whole named community-table partitions over HTTPS; dates are invalid |
| `gao-product-pages` | One or more `--product-id` | Closed set of exact product pages through Zyte; dates and agencies are invalid |

Dates use `YYYY-MM-DD`. Repeat `--agency` or `--product-id` for multiple values.
Agencies are sorted and deduplicated; duplicate GAO product IDs are refused.
GAO requires `ZYTE_TOKEN` in the process environment. It preserves literal
publisher topic information and covers only the named products. Bounds and
supply precedence are explained in [decisions](decisions.md).

Federal Register and public-table HTTP requests retry transient request errors,
429s, and server failures with bounded jittered delays. Most other 4xx responses
abort. Mirrulations retains its source-specific retry and ordered enumeration
rules. Credential refusals stop the run; follow [AGENTS.md](../AGENTS.md) for
error scrubbing and resumable operational tools.

## verify

Replay retained evidence without source requests. Require the expected artifact
pin and an explicitly accepted producer-verifier implementation identity.

```sh
uv run --frozen spicy-docs-source-native verify \
  --source federal-register --release /existing/release \
  --blob-store /persistent/blobs \
  --logical-id '<logicalId from publication>' \
  --artifact-digest '<artifactDigest from publication>' \
  --accepted-verifier-implementation-id '<trusted implementation ID>'
```

Every shown option is required. Repeat the accepted-ID option for an explicit
set of trusted implementations. Choose that set according to your deployment;
reading a value from an untrusted artifact does not establish trust in it.
Verification checks scope, schemas, evidence, reconstruction, ordering,
selection, failure accounting, and the published source-state digest.


## inspect

Open a retained release, check its pin and trusted producer-verifier identity,
and show collection outcomes and a bounded sample of recorded failures.
Use the same required `--source`, `--release`, `--blob-store`, `--logical-id`,
`--artifact-digest`, and repeatable `--accepted-verifier-implementation-id`
options as [verify](#verify), with `inspect` as the subcommand.

`--failure-limit 20` is the default sample size. Set `--failure-limit 0` for
outcomes only. Admission hashes retained payloads without reconstructing source
records; `verify` performs the full replay. The [source outcomes guide](source-native-outcomes.md)
explains each count, scope, and failure field.

## publish-public-table

Project an admitted source-native release into an immutable flat Parquet table.
The publisher checks every output row before publication. It retains a pin to
its source release; preserve that release and its evidence separately.

```sh
uv run --frozen spicy-docs-source-native publish-public-table \
  --table federal-register --source-release /existing/release \
  --source-blob-store /persistent/blobs \
  --source-accepted-verifier-implementation-id '<trusted source implementation ID>' \
  --destination /new/public-table \
  --implementation-id 'git+https://example.test/spicy-docs@<full-commit>'
```

Every shown option is required. Repeat `--source-accepted-verifier-implementation-id`
for multiple accepted IDs. Tables are `federal-register`, `regulations-documents`,
`regulations-dockets`, and `regulations-comments`. GAO and captured community
comments have no output-table profile. The destination must be new and separate
from the source release. The source release and source blob store must also be
separate.

Federal Register now publishes projection `1.1`, keyed by the existing
`document_number` and `publication_date` columns. Reused numbers on different
dates remain separate rows. This corrects the former projection's mismatch
with current source-native identity; it changes the table's projection version
and logical identity while preserving the columns.

## verify-public-table

Check the artifact pin, structure, declared table profile, member layout, and
accepted producer-verifier identity. This command performs table admission;
it does not independently reproject source records or run the publisher's
full Parquet-row gate. `verify_public_table_release()` provides the full row
gate to library callers.

```sh
uv run --frozen spicy-docs-source-native verify-public-table \
  --table federal-register --release /existing/public-table \
  --logical-id '<logicalId from publication>' \
  --artifact-digest '<artifactDigest from publication>' \
  --accepted-verifier-implementation-id '<trusted table implementation ID>'
```

Every shown option is required. Table choices match `publish-public-table`;
repeat the accepted-ID option as needed.

For Federal Register this command selects the supported `1.1` profile.
The old `1.0` table projection is no longer supported. See the
[compatibility decision](decisions.md#federal-register-public-tables-preserve-composite-identity).

## Campaigns, replay, and source tools

Reusable operations live beside their owning source or CLI package. Their
`--help` output lists explicit paths and required inputs:

```sh
uv run --frozen python -m spicy_docs.cli.campaign --help
uv run --frozen python -m spicy_docs.sources.federal_register.replay --help
uv run --frozen python -m spicy_docs.sources.congress.crs_summaries --help
```

Use the [operation index](../tools/README.md#related-operations) for each
command's purpose, output, and prerequisites. Campaigns publish agency-scoped
releases with attempt logs and receipts; start with their `--dry-run`.

```sh
uv run --frozen python -m spicy_docs.cli.campaign \
  --agency EPA --window-since 2021-01-01 --window-until 2025-12-31 \
  --destination-root /campaign/releases --blob-store /persistent/blobs \
  --implementation-id '<current producer implementation ID>' \
  --accepted-verifier-implementation-id '<trusted producer-verifier ID>' \
  --dry-run
```

Remove `--dry-run` to publish. Each publisher performs one mandatory full replay
before making its release visible. The campaign then checks its expected pin,
publication metadata, requested agency and window, and trusted verifier identity
without reconstructing source records again. Admission uses bounded memory but
still hashes all retained payload bytes to detect corruption. Resume repeats
this admission check in an interruptible `inspect --failure-limit 0` child; it
does not launch another publisher or semantic replay for a matching release.
Inspection writes to the attempt log and creates no separate success receipt. Repeat
`--accepted-verifier-implementation-id` to explicitly trust several producer
builds. These IDs come from your deployment policy, independently of release
contents; `--implementation-id` alone does not grant trust.

Keep the campaign's external `receipts/*.json` files with their release pins and
collection outcomes. See [source outcomes](source-native-outcomes.md) for counts,
requested scope, and inspection of retained failures. Missing, malformed, or
misdirected receipts cause the campaign to rename old evidence aside before
retrying. A valid receipt with a
mismatched pin, requested scope, damaged metadata, or unaccepted verifier fails
closed and preserves the release and receipt for inspection. Choose a new
campaign root when changing an agency's window. Full source reconstruction
remains available through the explicit [verify command](#verify) using the
retained external pin and an independently accepted verifier ID. The campaign's
former `--verify` and `--no-verify` switches and separate verify receipts are
removed; current resume requires a publish receipt with `collectionOutcome`.

Federal Register replay publishes saved responses under the current profile
without a source request. CRS acquisition writes resumable Congress.gov summary
records and requires an explicit credential file.

[Corpus diagnostics](../tools/README.md) remain checkout tools under
`tools/analysis/`, where each report states the bounded question it answers.
[Repository maintenance](../scripts/README.md) lives under `scripts/`.
The installed catalog builder is described in the
[catalog guide](catalog-and-drift.md#update-a-source-catalog).

## Output and failures

Success includes `ok`, `command`, absolute `release`, `logicalId`,
`artifactDigest`, `sourceStateDigest`, `sourceStateScope`, and `sourceSystemId`.
Source-native results also include `source`, `sourceSystemVersion`,
`sourceNativeSchemaSetDigest`, and `collectionOutcome`. Inspection adds its
failure sample and limit; see [inspect](#inspect). Public-table results instead include `table`,
`tableName`, and `maxRowsPerMember`. Keep these values with the run's receipt.

Handled failures have `ok: false`, `command`, and `error` containing `code` and
`message`. Codes distinguish `destination-exists`, `acquisition-failed`,
`release-invalid`, `transport-failed`, `dependency-missing`, and
`operation-failed`. Keep the actual message; a failed acquisition is not a claim
that the publisher has no records. Missing optional dependencies identify setup
work; an existing immutable destination requires choosing a new destination.
