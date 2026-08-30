# spicy-docs

The acquisition layer of a regulatory-search platform: faithful acquisition
from government sources (the Federal Register, regulations.gov via the
Mirrulations S3 mirror, and CourtListener's bulk-data dumps) and immutable
source-native release publication.

spicy-docs *gets*; it does not interpret. Its sibling **DocSpec** is the
*processing* product — catalogs and document interpretation live there.
spicy-docs acquires and publishes raw, source-native records; DocSpec
consumes and interprets them.

## What's here

- `federal_register_source_native.py`, `regulations_gov_source_native.py` —
  paginate and normalize each source's native API/mirror into source-native
  records.
- `spicy_regs_public_tables_source_native.py` — the community tables, the
  first rung of supply (see below).
- `source_native.py` — the shared publish/verify/replay path for a
  source-native release (an immutable, digest-pinned artifact).
- `sources/mirrulations.py`, `sources/courtlistener_bulk.py` — the two
  bulk/mirror readers this product owns.
- `source_profiles.py`, `source_profile_artifacts.py`, `sources/source_domains.py`
  — profile declarations and the documented-vs-observed drift gate.

## Supply precedence

Acquisition begins at the spicy-regs public tables — the community's already
collected data — captured and digest-pinned like any other source; an origin
API is the fallback rung, for what those tables cannot carry (PLAN.md,
"Supply-precedence ruling", accepted 2026-08-31). `spicy-docs-source-native
publish --source spicy-regs-public-comments --agency EPA` is that first rung:
it captures whole `comments/agency/agency_code={X}/part-{n}.parquet` objects,
pins each by SHA-256 with its size, fetch instant, locator, and stated
freshness, and classifies rows from those pinned bytes — never a live query.
The named agencies are the whole scope, so no row is filtered and any column
drift fails closed.

## Provenance

Extracted from `spicy-regs` branch `integrate/payload-prereqs`, commit
`ff8d202` and neighbors (the Mirrulations and CourtListener bulk readers,
their fixtures, and the vendored `rulespec-artifacts` wheel). Full history for
this code lives in that repository, not here.

## Running the tests

```
uv sync
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
