# spicy-docs

Faithful acquisition from government sources and immutable publication of
source-native records. spicy-docs preserves what a publisher supplied and the
evidence needed to check it. DocSpec, the downstream product, interprets it.

## Start here

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). From this checkout:

```sh
uv sync --frozen
uv run --frozen python examples/offline_release.py
./scripts/check
```

The example publishes and independently verifies one synthetic GAO page. It
makes no network requests and needs no credentials. Its JSON output includes
the preserved source record under `records`, including the publisher's topic
and capture details, read through `SourceNativeReleaseReader` after verification.
It also prints paths to retained artifacts; the evidence ZIP holds the exact
synthetic HTML. Use `--directory /path/to/example` to choose the output parent;
its `gao/` child must be new. The fixed implementation ID identifies the
example, not a production build. See [the example](examples/offline_release.py).

- [Contribute a fix, a source, or a fixture](CONTRIBUTING.md)
- [Find the component that owns a change](docs/architecture.md)
- [Publish and verify releases or public tables](docs/cli.md)
- [Understand the acquisition decisions](docs/decisions.md)
- [Read the adopted release specification](docs/superpowers/specs/2026-08-25-source-native-release-spec.md)
- [Use the dated source references](wiki/overview.md) and [maintain documentation](docs/documentation.md)

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
history remains in that repository. Historical `spicy-regs` schema identifiers
and supported producer identities remain intentional compatibility boundaries.
