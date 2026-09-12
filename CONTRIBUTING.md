# Contributing

Start with the [offline example](README.md#try-it-offline). Python 3.12, uv and
this checkout are enough; no sibling repository or source credentials are needed.

## Find the owner

- **Source fix:** change its acquisition module or `sources/<source>/profile.py`.
  Add a small fixture that demonstrates the publisher's behavior.
- **New source:** follow the [profile extension guide](docs/releases.md#add-or-change-a-source-profile).
  Define scope, evidence, identity, classification and completeness. Register it
  in `cli/sources.py`; reuse the release engine.
- **Shared release change:** read the [specification](docs/superpowers/specs/2026-08-25-source-native-release-spec.md).
  Preserve identities, exact schema bytes, bounded reading, immutable publication
  and independent replay. Qualify the built wheel when imports or resources move.

The [architecture map](docs/architecture.md) identifies the implementation files.
Split by responsibility, not a line-count quota. Keep coupled state transitions
and independent adversarial fixtures understandable.

## Run focused checks

```sh
uv sync --frozen --all-extras
uv run --frozen pytest -q tests/releases/test_acquisition.py
# Add --collect-only to list test names.
```

| Change | Tests under `tests/` |
| --- | --- |
| Federal Register | `releases/test_acquisition.py`, `test_federal_register_request_window.py` |
| Regulations.gov | `regulations_gov/` |
| GAO | `test_gao_product_pages_source_native.py`, `test_gao_source_native_cli.py` |
| Public comments | `test_spicy_regs_public_tables_source_native.py` |
| Public tables | `test_public_table.py`, `test_federal_register_public_table.py` |
| Raw readers | `test_mirrulations_reader.py`, `test_courtlistener_bulk.py`, `test_courtlistener_listing.py` |
| Shared release behavior | `releases/`, `test_source_native_failure_shape.py`, CLI and reader-closure tests |

For source changes, cover success, malformed success, incomplete enumeration,
duplicate observations and offline replay. Add release tests when selection or
identity changes. Keep deliberately malformed artifacts independent of the writer.

## Report a source problem

Include the URL/object key, retrieval time, request method, selectors, smallest
useful response and expected outcome. Label bytes as original, reduced or
synthetic; identify redactions and remove credentials.

Preserve source text, nulls and missing fields. An empty `200` response does not
establish absence; a challenge page or `502` is transport evidence. Follow
[AGENTS.md](AGENTS.md). Keep large captures and measurements with corpus receipts;
commit only bounded fixtures.

## Before submitting

```sh
uv run --frozen ruff format .
./scripts/check
```

The check script installs all extras and runs lint, formatting and the default
suite. Describe the trigger, resulting behavior, source evidence, checks and
compatibility effects. Update the [owning guide](docs/documentation.md).
Keep mechanical formatting separate from behavior changes.

Two checks are opt-in:

- `uv run --frozen pytest -q -m integration`: live Federal Register, one fixed
  day. Inspect source changes before updating its expected pin.
- `uv run --frozen pytest -q -m httpfs`: local loopback and DuckDB's `httpfs`
  extension. Install it with
  `uv run --frozen python -c 'import duckdb; duckdb.connect().install_extension("httpfs")'`.
  An extension/network stall can take about two minutes.

Review contact: [@mikewolfd](https://github.com/mikewolfd). Package publication,
downstream pin changes and deployment are separate from a code review.
