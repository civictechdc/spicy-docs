# spicy-docs

The acquisition layer of a regulatory-search platform: faithful acquisition
from government sources (the Federal Register, regulations.gov via the
Mirrulations S3 mirror, GAO product pages, and CourtListener's bulk-data dumps)
and immutable source-native release publication.

spicy-docs *gets*; it does not interpret. Its sibling **DocSpec** is the
*processing* product — catalogs and document interpretation live there.
spicy-docs acquires and publishes raw, source-native records; DocSpec
consumes and interprets them.

## What's here

- `federal_register_source_native.py`, `regulations_gov_source_native.py` —
  paginate and normalize each source's native API/mirror into source-native
  records.
- `gao_product_pages_source_native.py`, `sources/zyte.py` — capture a closed set
  of exact GAO product-page bytes and preserve its one literal publisher topic.
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

## GAO product pages

The migrated capture campaign observed HTTP 403 from GAO for its ordinary
direct client, so live acquisition reads `ZYTE_TOKEN` from the process
environment and uses SpicyDocs' bounded raw-HTTP Zyte adapter. The credential
never enters a locator, artifact, log, or error. The earlier SpicySearch runner
imported this transport from RefSpec because it was already available there;
that placement was implementation momentum, not a product boundary. Exact page
capture belongs here.

The useful source fact was different: each product page carries exactly one
publisher topic anchor with a literal `/topics/<slug>` and label. SpicyDocs
preserves that fact and the page's URL, byte length, and SHA-256 digest. It does
not resolve the slug to a RefSpec concept or create a search tag.

```sh
spicy-docs-source-native publish \
  --source gao-product-pages \
  --product-id gao-26-107693 \
  --destination /new/immutable/release \
  --blob-store /persistent/source-native-blobs \
  --implementation-id 'git+https://example/spicy-docs@<commit>'
```

The release is complete only for the explicit, sorted, distinct product IDs in
its scope; it makes no claim about the complete GAO catalog. Each page is one
deterministic ZIP containing canonical capture metadata followed by the exact
HTML. For `N` products, `H` total HTML bytes, and largest page `B`, acquisition
takes `O(N log N + H)` work including canonical CLI ordering, makes `N`
sequential bounded requests, and uses
`O(N + B)` working space. `N <= 1,000`, `B <= 8 MiB`, and `H <= 1 GiB`.

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
