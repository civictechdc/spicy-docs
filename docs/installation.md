# Install what you need

Use Python 3.12. Core SpicyDocs requires Rulespec Artifacts and `jsonschema`,
with no DocSpec, SpicyRegs or sibling checkout dependency.

| Install | Use it for |
| --- | --- |
| Core | Profiles, admitted records/renditions/outcomes, bounded evidence, JSON/HTML parsing, injected acquisition and pure CourtListener listing parsing. |
| `[acquisition]` | Default HTTP/S3 capture and raw Mirrulations/CourtListener readers; adds HTTPX, Boto3, Loguru and tqdm. |
| `[public-table]` | Captured-comment Parquet parsing/replay and public-table operations; adds Polars and PyArrow. |
| Both extras | Live community-comment capture or CRS summaries read from Parquet. |

Live GAO uses the standard-library Zyte transport: no extra, but `ZYTE_TOKEN`
is required. Injected fetchers need their own dependencies.

Reading admitted comment records needs no Parquet parser. Full verification
replays their retained Parquet and therefore needs `public-table`.

## From this checkout

```sh
uv sync --frozen --all-extras
./scripts/check
```

The check script installs all extras too. `uv run --frozen` retains them;
`uv sync --frozen` without extras removes them.

To try core only:

```sh
uv sync --frozen --no-dev
uv run --frozen --no-dev python examples/offline_release.py
```

This runs offline without optional packages. Restore all extras before the full suite.

### macOS: install succeeds but import fails

Python skips an editable-path file carrying the `hidden` flag. Check:

```sh
ls -lO .venv/lib/python3.12/site-packages/spicy_docs.pth
```

If that exact file is hidden, clear the flag and retry:

```sh
chflags nohidden .venv/lib/python3.12/site-packages/spicy_docs.pth
```

This local condition was observed during contributor checks; its cause is unknown.

## From a built wheel

Replace these paths with the exact wheel files selected for your application:

```sh
uv venv --python 3.12 /path/to/source-reader-env
uv pip install --python /path/to/source-reader-env/bin/python \
  /path/to/rulespec_artifacts-1.0.12-py3-none-any.whl \
  /path/to/spicy_docs-0.3.0-py3-none-any.whl
```

For both extras, use
`'/path/to/spicy_docs-0.3.0-py3-none-any.whl[acquisition,public-table]'` as the last
argument. Use ordinary dependency resolution. Record version, source revision
and wheel digest separately from data pins; a local build is not a published release.

A CLI `dependency-missing` error means an extra is needed. It never means an empty source.
