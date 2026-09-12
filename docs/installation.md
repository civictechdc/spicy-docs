# Installation choices

Use Python 3.12. The core SpicyDocs wheel requires Rulespec Artifacts and
`jsonschema`; it does not require DocSpec, SpicyRegs, or a sibling checkout.
Optional dependencies follow two kinds of work:

| Install | What it enables | Additional packages |
| --- | --- | --- |
| Core `spicy-docs` | Profiles; admitted records, renditions, outcomes, failures, and bounded evidence; JSON/HTML source parsing and replay; injected acquisition; pure CourtListener listing parsing | None beyond the core requirements |
| `spicy-docs[acquisition]` | Default HTTP and S3 acquisition; Mirrulations and CourtListener raw readers | HTTPX, Boto3, Loguru, tqdm |
| `spicy-docs[public-table]` | Captured comment Parquet parsing and full replay; public-table publication and checking | Polars, PyArrow |
| `spicy-docs[acquisition,public-table]` | Live capture of community comment partitions; CRS summaries fetched from a Parquet input; all package operations | Both groups above |

GAO's default Zyte transport uses the Python standard library, so it needs no
extra, but live capture requires `ZYTE_TOKEN`. An injected fetcher may have its
own dependencies. Install only what that fetcher uses.

Reading admitted public-comment records does not parse the retained Parquet
again. Full source verification does, so it requires `public-table` even when
the release and evidence are local. These are different checks; see
[collection outcomes and evidence access](source-native-outcomes.md).

## From this checkout

Contributors install all operations and the development tools:

```sh
uv sync --frozen --all-extras
./scripts/check
```

The check script performs this same sync. Subsequent `uv run --frozen` commands
retain installed extras. Running `uv sync --frozen` without `--all-extras`
removes the optional packages; rerun the contributor setup before the full suite.
Development tools are declared once, separately from runtime extras.

To try only the core in the checkout, use `uv sync --frozen --no-dev`, then
`uv run --frozen --no-dev python examples/offline_release.py`. This publishes,
verifies, and reads synthetic GAO evidence without optional packages or network
access. Restore the contributor setup before working on the full package.

## From a built wheel

Use a fresh virtual environment and the exact candidate wheel and Rulespec
Artifacts wheel selected for your application. For example, replacing the paths
with your retained wheel files:

```sh
uv venv --python 3.12 /path/to/source-reader-env
uv pip install --python /path/to/source-reader-env/bin/python \
  /path/to/rulespec_artifacts-1.0.11-py3-none-any.whl \
  /path/to/spicy_docs-0.2.0-py3-none-any.whl
```

For both optional groups, replace the last argument with
`'/path/to/spicy_docs-0.2.0-py3-none-any.whl[acquisition,public-table]'`.
Ordinary dependency resolution is sufficient; `--no-deps` is unnecessary.
Record package version, source revision, and wheel digest separately from data
release pins. Building a local wheel does not establish package publication or
downstream adoption.

The CLI reports `dependency-missing` when an operation needs an unavailable
package. That is an installation issue; it does not report an empty source or
create a successful release. Use the table above to choose the required extra.
