# Documented-value drift

## Review documented-value drift

Compare pinned publisher value lists with a retained SpicyRegs table observation.
SpicyDocs maintainers own this optional offline diagnostic; it is no live monitor,
publication prerequisite, or DocSpec gate. Upstream adoption requires a named
maintenance user. See [ownership](source-ownership.md#e-documented-value-drift).

[`source_domains.py`](../src/spicy_docs/sources/source_domains.py) parses
[pinned captures](../sample-data/source-domains/). Their manifest binds source
URL, capture metadata, size, and digest. Regulations.gov values come from OpenAPI;
Unified Agenda values come from checked XSD documentation prose, not enumeration
elements. Exact strings are compared in both directions:

| Finding | Meaning |
| --- | --- |
| `undocumented-value` | Observed in the table, absent from the pinned list |
| `unobserved-value` | In the pinned list, absent from this bounded observation |

Every difference needs a reason in `ACCEPTED_DOMAIN_FINDINGS`; stale ledger
entries also fail. Acceptance records a source condition without normalizing
values or proving absence from the wider publisher population. Keep counts with
the checked snapshot and input pins.

Check the pinned inputs without network or Parquet access:

```sh
uv run --frozen python scripts/check_source_domain_drift.py
```

Preview local `<table>.parquet` files in one directory, using development DuckDB:

```sh
uv run --frozen python scripts/check_source_domain_drift.py \
  --observe --data-dir /path/to/published-tables \
  --observed-at 2026-09-02T12:00:00Z \
  --producer-revision '<full-producing-commit>'
```

After reviewing pins and findings, add `--write-snapshot` to retain the observation.
Both provenance options are required. **The snapshot is written before the finding
check exits, even when that check fails.** Inspect the diff and accept only
reviewed source conditions. Tie observation time and producer revision to the
supplied files; paths with spaces or apostrophes are passed as data to DuckDB.

When publisher documentation changes, preserve the new response and capture
URL/time, recompute manifest size/digest, then review parser and value changes
together. Do not hand-edit extracted lists. Findings compare two retained inputs;
fixture checks do not establish current service health or population coverage.

For capture, parser, observation, comparison, or ledger changes, run:

```sh
uv run --frozen pytest -q tests/test_source_domain_drift.py
```

See the [script index](../scripts/README.md) for command ownership.
