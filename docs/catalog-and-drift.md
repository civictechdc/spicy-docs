# Source catalogs and documented-value drift

Source catalogs describe published tables and their available source evidence.
The drift check compares selected exact table values with pinned publisher
documentation. These are separate maintenance tasks: neither builds a
source-native release nor assigns downstream search meaning.

## Update a source catalog

[`catalog/profiles.py`](../src/spicy_docs/catalog/profiles.py) declares table
identities, fields, processing modes, access rules, and active profiles.
[`catalog/artifacts.py`](../src/spicy_docs/catalog/artifacts.py) builds two
deterministic artifacts from these declarations and reviewed inputs:

- `source-profile-catalog` describes each declared profile and its access scope.
- `profile-resource-applicability` relates preserved source evidence to resources
  in a supplied, digest-pinned RefSpec catalog.

The checked inputs and outputs live in [`policies/`](../policies/). Relationship
types describe a native code, identifier, structure, or source-assigned
vocabulary. They do not select concepts, tags, facets, or ranking policy.
Formats retain their literal `spicyregs-.../experimental-v0` identifiers.

The builder checks closed input shapes, exact profile coverage, unique resource
references, and the supplied catalog's content seal. `recordedAt` comes from
the reviewed input and contributes to artifact identity; it is not replaced with
the current time. A valid seal establishes content consistency, not the source
or authenticity of the catalog.

From the repository root:

```sh
uv run --frozen python scripts/generate_source_profile_artifacts.py --check
```

The default uses the checked RefSpec fixture and its
[provenance](../tests/fixtures/refspec-resource-catalog-v0.provenance.json).
For a reviewed catalog change, pass `--refspec-catalog /path/to/resource-catalog.json`.
After reviewing declarations and applicability, use `--write` with that same
input and inspect both output diffs. The check compares regenerated text byte
for byte. `validate_source_profile_artifacts()` provides the in-process check
against current declarations; a standalone applicability build checks the
supplied catalog's seal and coverage but does not compare every row with those
declarations.

The installed `build-source-profile-artifacts` command accepts explicit inputs
and an output directory:

```sh
uv run --frozen build-source-profile-artifacts \
  --applicability-input policies/profile-resource-applicability-input-v0.json \
  --refspec-catalog tests/fixtures/refspec-resource-catalog-v0.json \
  --output /path/to/generated-directory
```

Both write paths write files sequentially and can leave a partial result on
failure. Use a private output directory for an independent build; the repository
`--write` mode intentionally updates checked outputs. Focused checks:
`uv run --frozen pytest -q tests/test_source_profile_artifacts.py`.

## Review documented-value drift

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
written before the finding check returns its exit status:** a failing gate can
still change the checked snapshot. Inspect that diff and update the ledger only
for reviewed source conditions. Refresh publisher captures with their manifest
when the documented source changes; do not hand-edit extracted value lists.

Run `uv run --frozen pytest -q tests/test_source_domain_drift.py` for capture,
parser, observation, comparison, and accepted-finding changes. See the
[repository script index](../scripts/README.md) for command ownership.
