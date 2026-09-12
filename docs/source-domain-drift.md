# Documented-value drift

## Review documented-value drift

SpicyDocs source maintainers own this optional offline diagnostic. Use it when
publisher documentation or a retained SpicyRegs table observation changes. It is
not a live-source monitor, a publication prerequisite, or a DocSpec execution
gate. Its fixture checks protect this diagnostic's evidence, not the current
publisher population. The [ownership decision](source-ownership.md#e-documented-value-drift)
keeps it here; upstream adoption remains conditional on a named maintenance user.

[`sources/source_domains.py`](../src/spicy_docs/sources/source_domains.py)
parses selected closed-value domains from pinned publisher captures in
[`sample-data/source-domains/`](../sample-data/source-domains/). The manifest
binds each document to its source URL, capture metadata, size, and digest.
Regulations.gov values come from OpenAPI declarations; Unified Agenda values
come from checked XSD documentation prose, not XSD enumeration elements.

The comparison preserves exact strings and checks both directions:

| Finding | Meaning to investigate |
| --- | --- |
| `undocumented-value` | The observed table contains a value absent from the pinned publisher list. |
| `unobserved-value` | The pinned list contains a value absent from this bounded observation. |

Every current difference needs a reason in `ACCEPTED_DOMAIN_FINDINGS`.
A ledger entry that no longer matches a finding also fails. Acceptance records
the source condition; it neither normalizes values nor proves that missing
values are absent from the publisher's wider population. Read counts from the
checked snapshot and its input pins rather than copying them into prose.

The default check reads the pinned captures and checked observation without
network or Parquet access:

```sh
uv run --frozen python scripts/check_source_domain_drift.py
```

To preview separately retained local tables, supply `<table>.parquet` files in
one directory. DuckDB is supplied by the development environment:

```sh
uv run --frozen python scripts/check_source_domain_drift.py \
  --observe --data-dir /path/to/published-tables \
  --observed-at 2026-09-02T12:00:00Z \
  --producer-revision <full-producing-commit>
```

After reviewing the pins and findings, add `--write-snapshot` to retain the new
observation. Writing requires both provenance options. **The snapshot is
written before the finding check returns its exit status:** a failing diagnostic can
still change the checked snapshot. Inspect that diff and update the ledger only
for reviewed source conditions. Refresh publisher captures with their manifest
when the documented source changes; do not hand-edit extracted value lists.
Preserve the original response and capture URL/time, recompute its size and digest,
then inspect parser changes and the resulting value diff together. Keep observation
time and producing revision tied to the local files actually supplied. Local table
paths may contain spaces or apostrophes; they are passed as data to DuckDB.
A finding explains a difference between those two retained inputs, not a verdict
about the completeness or health of the public service.

Run `uv run --frozen pytest -q tests/test_source_domain_drift.py` for capture,
parser, observation, comparison, and accepted-finding changes. See the
[repository script index](../scripts/README.md) for command ownership.
