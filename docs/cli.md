# Publish and verify

Run `uv run --frozen spicy-docs-source-native --help` from a developer checkout.
Each command also accepts `--help`. The four commands below write a JSON success
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
Source-native results also include `source`, `sourceSystemVersion`, and
`sourceNativeSchemaSetDigest`. Public-table results instead include `table`,
`tableName`, and `maxRowsPerMember`. Keep these values with the run's receipt.

Handled failures have `ok: false`, `command`, and `error` containing `code` and
`message`. Codes distinguish `destination-exists`, `acquisition-failed`,
`release-invalid`, `transport-failed`, `dependency-missing`, and
`operation-failed`. Keep the actual message; a failed acquisition is not a claim
that the publisher has no records. Missing optional dependencies identify setup
work; an existing immutable destination requires choosing a new destination.
