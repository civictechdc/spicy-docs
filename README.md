# spicy-docs

Collect government-source records with enough retained evidence to check what
was received. SpicyDocs acquires named sources, preserves their fields and
provenance, and publishes immutable source releases that can be checked offline.
It also provides raw readers and optional flat-table output.

Use the source records directly, or supply them to another application. DocSpec
owns dataset catalogs, document-fetcher and processor selection, experiment
runs, and reuse across runs. A source release is a useful stopping point on its
own. [Choose a source workflow](docs/source-workflows.md).

## Start here

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). From this checkout:

```sh
uv sync --frozen --all-extras
uv run --frozen python examples/offline_release.py
./scripts/check
```

This contributor setup installs the live-acquisition and Parquet tools used by
the full test suite. An application can install the smaller core wheel for
source records, profiles, evidence, and JSON/HTML parsing. See
[installation choices](docs/installation.md).

The example publishes and independently verifies one synthetic GAO page. It
makes no network requests and needs no credentials. Its JSON output includes
the preserved source record under `records`, including the publisher's topic
and capture details, read through `SourceNativeReleaseReader` after verification.
It also prints paths to retained artifacts; the evidence ZIP holds the exact
synthetic HTML. `recordEvidence` links that record to its admitted evidence blob.
Use `--case unexpected` to preserve a different literal topic, or `--case missing`
to inspect an expected missing-topic refusal with retained diagnostic bytes.
These cases demonstrate source behavior; they do not filter a catalog or infer
requirements from a topic. Use `--directory /path/to/example` to choose the output parent;
its `gao/` child must be new. The fixed implementation ID identifies the
example, not a production build. See [the example](examples/offline_release.py).

- [Contribute a fix, a source, or a fixture](CONTRIBUTING.md)
- [Find the component that owns a change](docs/architecture.md)
- [Publish and verify releases or public tables](docs/cli.md)
- [Understand the acquisition decisions](docs/decisions.md)
- [Read the adopted release specification](docs/superpowers/specs/2026-08-25-source-native-release-spec.md)
- [Browse source behavior, raw readers, and maintenance workflows](docs/README.md)

## Sources and supply

Source-native publishing supports Federal Register documents, Regulations.gov
records from Mirrulations, captured spicy-regs public comment tables, and a
named set of GAO product pages. Raw Mirrulations and CourtListener bulk readers
are also available; a raw reader does not itself publish a verifiable release.

Prefer the community's spicy-regs public tables where they carry the required
data, then use origin acquisition for missing coverage. Capture and digest-pin
whole named agency partitions before classifying rows. This precedence is a
supply policy; the CLI requires an explicit source and has no automatic fallback.
[The decision note](docs/decisions.md) explains its scope.

Live GAO capture uses `ZYTE_TOKEN` from the process environment. Credentials
must never enter a locator, artifact, log, or error. Source-specific limits and
failure handling are in [the operator guide](docs/cli.md) and [AGENTS.md](AGENTS.md).

## Provenance

The initial extraction came from `spicy-regs` branch
`integrate/payload-prereqs`, commit `ff8d202` and neighboring changes, including
the bulk readers, fixtures, and vendored `rulespec-artifacts` wheel. Earlier
history remains in that repository. Some current schema and artifact identifiers
retain the `spicy-regs` name. They identify the data format; current releases
require the `spicy-docs` producer and supported current format and policy
versions. Historical producer or format acceptance is not retained.
