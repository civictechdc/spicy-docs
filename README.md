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
- `source_native.py` — the shared publish/verify/replay path for a
  source-native release (an immutable, digest-pinned artifact).
- `sources/mirrulations.py`, `sources/courtlistener_bulk.py` — the two
  bulk/mirror readers this product owns.
- `source_profiles.py`, `source_profile_artifacts.py`, `sources/source_domains.py`
  — profile declarations and the documented-vs-observed drift gate.

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
