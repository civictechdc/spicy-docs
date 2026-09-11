# Contributing

Start with the [offline example](README.md#start-here), then choose the smallest
change that demonstrates the source behavior you want to improve. Python 3.12,
uv, and the checked-in wheel under `vendor/` are sufficient for the default
checks. You do not need a sibling checkout or source credentials.

## Choose a job

| Job | Start with | Evidence and focused checks |
| --- | --- | --- |
| Correct a source behavior | The source's acquisition module and `sources/<source>/profile.py`; see the [module map](docs/architecture.md) | Add a small response fixture demonstrating the difference. Run `tests/regulations_gov/` for Regulations.gov, or the corresponding `test_*source_native*` source tests. Add `tests/releases/` when selection or identity changes. |
| Add a source | `source_native_profile.py`, an existing source profile, and `cli/sources.py` registration | Define scope, exact evidence, classification, identities, and completeness. Test success, malformed success, incomplete enumeration, duplicate observations, and offline replay. Reuse the release engine. |
| Change shared release behavior | `source_native.py`, the [release specification](docs/superpowers/specs/2026-08-25-source-native-release-spec.md), and reader tests | Preserve output identities, schema bytes, bounded reading, immutable publication, and independent replay. Run `tests/releases/`, `test_source_native_failure_shape.py`, CLI, and reader-closure tests. Test the built wheel when imports or bundled schemas move. |

Public-table changes also need `test_public_table.py` and its CLI tests. Raw
reader changes belong with the Mirrulations or CourtListener tests. Find exact
test names with `uv run --frozen pytest --collect-only -q`.

## Bring a domain finding without writing an adapter

Open an issue with the source URL or object key, retrieval time, request method
and selectors, the smallest response demonstrating the issue, and your expected
outcome. State whether bytes are original, reduced, or synthetic. Preserve
source text and distinguish missing fields from explicit nulls. Remove
credentials before attaching anything; identify any redactions.

Explain whether the source gave a complete empty result, an incomplete answer,
or a failed request. A `200` with an empty list alone does not establish absence.
A challenge page or `502` is transport evidence, not a source record. Follow
[the acquisition rules](AGENTS.md). Keep large captures and campaign measurements
in their corpus receipts; commit only bounded test fixtures.

## Check and submit

```sh
./scripts/check
# Equivalent individual checks after uv sync --frozen:
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -q
```

Run `uv run --frozen ruff format .` to format a change. Keep mechanical formatting
separate from behavior changes. Prefer cohesive files around 200–500 lines, but
use length as a review prompt: schemas and independent adversarial fixtures may
need more space. Split by responsibility. Share matching mechanics while
preserving source-specific acceptance and diagnostics.

The default suite excludes two opt-in checks:

| Command | Prerequisite and interpretation |
| --- | --- |
| `uv run --frozen pytest -q -m integration` | Calls Federal Register over HTTPS for one fixed day. Needs network access; publisher changes can invalidate its pinned expectation. The test currently records a stale identity-era digest; inspect captured differences before updating a pin. |
| `uv run --frozen pytest -q -m httpfs` | Needs DuckDB's `httpfs` extension and local loopback networking. Install the extension with `uv run --frozen python -c 'import duckdb; duckdb.connect().install_extension("httpfs")'`. The test documents a platform-specific stall that can last about two minutes. |

Describe the trigger, resulting behavior, relevant source evidence, checks run,
and compatibility effects in the change description. Explain deliberate
exceptions and preserved historical rules. Follow [documentation maintenance](docs/documentation.md).
Package publication, downstream pin changes, and deployment are separate actions.

Repository owner [@mikewolfd](https://github.com/mikewolfd) is the initial review-routing
contact. Source, release-format, and operations reviewer assignments still need
maintainer confirmation; do not infer ownership from who last edited a file.
