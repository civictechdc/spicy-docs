# Repository maintenance

These commands operate on the checkout's checked inputs or development tools.
They do not ship in the installed Python package. Run these examples from the
repository root after [contributor setup](../CONTRIBUTING.md).

| Command | Input, result, and reason |
| --- | --- |
| `./scripts/check` | Installs the locked contributor environment, then runs lint, formatting, and the default offline test suite. CI uses this same command. |
| `uv run --frozen python scripts/check_source_domain_drift.py` | Compares documented publisher values with the checked observation snapshot. Fails on an unrecorded finding or a stale accepted finding. No network access. |

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

Use [corpus diagnostics](../tools/README.md) for measurements against releases or
live publisher metadata. Keep their output receipts outside the repository.
