# Corpus diagnostics

Use these tools to investigate retained releases or publisher metadata. They
produce measurements and do not ship in the installed package.

Run them from the repository after [contributor setup](../CONTRIBUTING.md):

```sh
uv run --frozen python -m tools.analysis.observation_census --help
```

Keep reports with their inputs and command receipts outside the repository.
Each diagnostic answers one question; it does not verify a whole release.

## Compare local evidence

These four commands write JSON to stdout:

- [compare_source_native_releases](analysis/compare_source_native_releases.py):
  compare added, removed, and changed records. Supply two release roots, a shared
  blob store, and explicit identity fields. Verifies blob digests, not full release
  admission.
- [cross_filing_census](analysis/cross_filing_census.py): count regulations.gov
  document or docket identities across releases. Supply `[root, artifactDigest,
  profile]` triples and a blob store. Counts name their populations; source records
  and downstream catalog items differ.
- [observation_census](analysis/observation_census.py): count retained observations,
  including those publication discarded. Supply a release root, blob store,
  artifact pin, verifier id, and source profile. Record and observation counts differ.
- [fr_discarded_distinctness](analysis/fr_discarded_distinctness.py): compare content
  across Federal Register observations sharing a document number. Supply a release
  root and blob store. Reproduces evidence for compound identity without interpreting
  the number's year.

## Check GovInfo metadata

These commands use the network and write append-only JSONL:

- [govinfo_granule_census](analysis/govinfo_granule_census.py): compare exact document
  numbers with keyless issue MODS granule ids in both directions. Supply a Federal
  Register release root, blob store, upper date bound, and output path. Missing or
  failed listings leave missing evidence; a mismatch alone does not prove a missing
  document.
- [govinfo_resolve_unmatched](analysis/govinfo_resolve_unmatched.py): check fused
  identifiers left unmatched by MODS. Supply the prior census, an explicit credential
  file, and output path. Only complete, populated listings support `fused-match` or
  `not-listed`; the latter describes this endpoint, not all GovInfo holdings.

Both outputs record `sourceReleaseDigest` and resume only against the same source
release. Rows lacking that digest require a fresh output file. The resolver also
retries when an issue's requested unmatched-number set changes.

- [legislative_data_map](analysis/legislative_data_map.py): measure what each
  Congress.gov and GovInfo collection route lists and from when, sample the
  publisher XML candidates, and rewrite the generated tables in
  `docs/research/legislative-data-map-2026-09-18.md` from those measurements
  and the judgments held in the tool. Supply an explicit credential file, the
  JSON output path and the map path; `--offline` rewrites from a prior output.
  Coverage is a lower bound from a capped walk, never proof of absence.

Both stop on HTTP 401/403. The resolver retries request errors, empty, invalid,
and incomplete listings. It requests one page per issue and refuses `nextPage`,
count mismatches, or a full 1,000-row page. A full page is indeterminate even when
its declared count is 1,000: that may describe the page, not the issue. Empty
listings are also indeterminate. Unresolved listings cause exit status 1.

## Related operations

These operations ship with `spicy_docs` and accept caller-selected paths. Use
`uv run --frozen python -m MODULE --help` with:

- [`spicy_docs.sources.federal_register.replay`](../src/spicy_docs/sources/federal_register/replay.py):
  build a new release from retained responses and scope, offline.
- [`spicy_docs.cli.campaign`](../src/spicy_docs/cli/campaign.py): publish regulations.gov
  docket/document releases with attempt logs and receipts under one locked root.
  Start with `--dry-run`.
- [`spicy_docs.sources.congress.crs_summaries`](../src/spicy_docs/sources/congress/crs_summaries.py):
  fetch resumable summary JSONL from a Parquet list of report ids. Requires an
  explicit credential file and PyArrow (`public-table` extra).

[Repository checks and artifact maintenance](../scripts/README.md) live in
`scripts/`.

The offline [FEC layout generator](build_fec_layouts.py) rebuilds packaged field
definitions from pinned workbook fixtures. Its OpenPyXL dependency is used only
for generation; the [runtime API](../docs/sources/fec-filing-fields.md) uses core JSON.
