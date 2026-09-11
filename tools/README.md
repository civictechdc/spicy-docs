# Corpus diagnostics

These tools answer a specific question about retained releases or publisher
metadata and produce a reproducible measurement. They live outside the installed
package because their reports support corpus investigations, rather than the
normal acquire, publish, and read workflow.

Run them from the repository after the [contributor setup](../CONTRIBUTING.md):

```sh
uv run --frozen python -m tools.analysis.observation_census --help
```

Keep generated reports beside their inputs and command receipts, outside this
repository. A successful diagnostic is evidence for its stated question; it does
not establish the integrity or completeness of an entire release.

| Diagnostic | Inputs and output | Why it exists and what it cannot prove |
| --- | --- | --- |
| [compare_source_native_releases](analysis/compare_source_native_releases.py) | Baseline and candidate release roots, shared blob store, explicit identity fields; JSON to stdout. | Compares emitted records before and after a producer change. Reports added, removed, and changed records without guessing the identity policy. Reads blob bytes with digest verification; it does not perform full release admission. |
| [cross_filing_census](analysis/cross_filing_census.py) | JSON list of `[root, artifactDigest, profile]` triples and a blob store; JSON to stdout. | Measures regulations.gov document or docket identities across releases in one pass. Each count names its population; source records differ from downstream catalog items. |
| [observation_census](analysis/observation_census.py) | Release root, blob store, artifact pin, verifier id, and source profile; JSON to stdout. | Reads retained acquisition evidence to include observations that publication did not select. Distinguishes record identity from observation counts. |
| [fr_discarded_distinctness](analysis/fr_discarded_distinctness.py) | Federal Register release root and blob store; JSON to stdout. | Compares source content fields across observations sharing a document number. Retains a way to reproduce the evidence behind compound identity; it does not infer meaning from the number's year. |
| [govinfo_granule_census](analysis/govinfo_granule_census.py) | Federal Register release root, blob store, upper date bound, and output path; append-only JSONL. | Compares exact document numbers against keyless issue MODS granule ids in both directions. Missing or failed listings are missing evidence. A mismatch alone is not a missing-document finding. |
| [govinfo_resolve_unmatched](analysis/govinfo_resolve_unmatched.py) | Prior MODS census, explicit credential file, and output path; append-only JSONL. | Checks the keyed endpoint for fused identifiers that MODS left unmatched. Only a complete populated listing supports `fused-match` or `not-listed`; `not-listed` describes that endpoint, not all GovInfo holdings. |

The GovInfo commands use the network. The other four operate on local evidence.
Both GovInfo outputs record `sourceReleaseDigest` and resume only against the
same source release. Rows lacking that digest require a fresh output file.
The resolver also retries when an issue's requested unmatched-number set changes.

Both commands stop on HTTP 401/403. The resolver retries recorded request errors,
empty listings, invalid listings, and incomplete listings. Empty remains
indeterminate. It requests one page per issue and explicitly refuses a truncated
listing (`nextPage`, count mismatch, or a full 1,000-row page); it does not silently
treat the first page as a complete enumeration. A full page remains indeterminate
even if its declared count is 1,000: this diagnostic has not established whether
that count describes the page or the issue. A run with unresolved listings exits
with status 1.

## Related operations

Reusable operations ship with `spicy_docs` and accept caller-selected paths:

| Operation | Command | Output |
| --- | --- | --- |
| [Replay Federal Register evidence](../src/spicy_docs/sources/federal_register/replay.py) | `uv run --frozen python -m spicy_docs.sources.federal_register.replay --help` | A new release from the original release's retained responses and scope; no network requests. |
| [Run an agency campaign](../src/spicy_docs/cli/campaign.py) | `uv run --frozen python -m spicy_docs.cli.campaign --help` | Regulations.gov docket/document releases, per-attempt logs, and receipts under one locked destination root. Start with `--dry-run`. |
| [Fetch CRS summaries](../src/spicy_docs/sources/congress/crs_summaries.py) | `uv run --frozen python -m spicy_docs.sources.congress.crs_summaries --help` | Resumable Congress.gov summary JSONL from a Parquet list of report ids. Requires PyArrow (the `public-table` extra outside contributor setup) and an explicit credential file. |

[Repository checks and artifact maintenance](../scripts/README.md) live in
`scripts/`. Existing script paths were replaced by these task-specific homes;
there are no compatibility wrappers.
