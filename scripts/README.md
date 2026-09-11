# Repository maintenance

These commands operate on the checkout's checked inputs or development tools.
They do not ship in the installed Python package. Run these examples from the
repository root after [contributor setup](../CONTRIBUTING.md).

| Command | Input, result, and reason |
| --- | --- |
| `./scripts/check` | Installs the locked contributor environment, then runs lint, formatting, and the default offline test suite. CI uses this same command. |
| `uv run --frozen python scripts/check_source_domain_drift.py` | Compares documented publisher values with the checked observation snapshot. Fails on an unrecorded finding or a stale accepted finding. No network access. |
| `uv run --frozen python scripts/generate_source_profile_artifacts.py --check` | Deterministically regenerates source-profile policy artifacts in memory and compares them with `policies/`. Defaults to the committed, digest-checked RefSpec catalog fixture used by tests. |

To refresh a source-domain snapshot from locally downloaded publisher tables:

```sh
uv run --frozen python scripts/check_source_domain_drift.py \
  --observe --data-dir /path/to/tables \
  --observed-at 2026-09-11T00:00:00Z --producer-revision PRODUCER_COMMIT \
  --write-snapshot
```

`--data-dir` holds the table-named Parquet files. `--producer-revision` identifies
the revision that produced those tables. Snapshot observation needs DuckDB,
which contributor setup installs. Review both new findings and accepted findings
that disappeared; record source evidence before changing the accepted ledger.

To rewrite the checked source-profile artifacts after a deliberate declaration
or applicability change:

```sh
uv run --frozen python scripts/generate_source_profile_artifacts.py --write
uv run --frozen python scripts/generate_source_profile_artifacts.py --check
```

Pass `--refspec-catalog /path/to/catalog.json` only when intentionally checking a
different catalog. The generator verifies the catalog's own digest, resolves
the applicability input's resource ids, and records the catalog pin in its output.
The fixture's adjacent provenance file records its source. This maintenance
command preserves the versioned filenames in `policies/`; the installed
`build-source-profile-artifacts` command instead writes artifacts to a selected
output directory for consumers.

Use [corpus diagnostics](../tools/README.md) for measurements against releases or
live publisher metadata. Keep their output receipts outside the repository.
