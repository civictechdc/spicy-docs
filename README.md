# spicy-docs

Collect government-source records, preserve their fields and evidence, and
publish immutable releases that can be checked offline. Use the records directly
or supply them to a dataset application such as DocSpec.

<a id="start-here"></a>

## Try it offline

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). From this checkout:

```sh
uv sync --frozen --all-extras
uv run --frozen python examples/offline_release.py
./scripts/check
```

The example publishes, verifies and reads one synthetic GAO page. It needs no
credentials or network access. The JSON output contains the source record,
literal publisher topic, evidence references and retained file paths.

Try `--case unexpected` to preserve a different topic, or `--case missing` to
inspect an expected refusal and its retained bytes. Use
`--directory /path/to/example` to choose an output parent; its `gao/` child must
be new. The example's fixed implementation ID is for demonstration only.

## Choose your next step

- **Make a change:** [Contributing](CONTRIBUTING.md).
- **Find the code:** [Architecture](docs/architecture.md).
- **Choose an output:** [Source workflows](docs/source-workflows.md).
- **Run a command:** [Operator guide](docs/cli.md).
- **Install a smaller reader:** [Installation](docs/installation.md).
- **Find a source rule:** [Documentation](docs/README.md).

## Sources and supply

Source releases support Federal Register, Regulations.gov through Mirrulations,
captured spicy-regs public comments, and named GAO product pages. Raw
Mirrulations and CourtListener readers are also available.

The [bill API](docs/sources/congress-bills.md) separately captures BILLSTATUS XML
and a selected bill-text version, preserving identity, source fields and bytes.
The [CFR/eCFR API](docs/sources/cfr.md) captures explicitly selected regulation
XML, retaining printed dates separately from requested dates and editions.

Prefer community spicy-regs tables where they carry the required data; use
origin acquisition for missing coverage. Capture and pin whole named agency
partitions before classifying rows. Source choice is explicit: the CLI does
not perform automatic fallback. See [supply policy](docs/decisions.md#community-supply-precedes-origin-acquisition).

Live GAO capture needs `ZYTE_TOKEN`. Keep credentials out of locators, artifacts,
logs and errors; follow [the acquisition rules](AGENTS.md).

## Provenance

Extracted from spicy-regs branch `integrate/payload-prereqs`, commit `ff8d202`
and neighboring changes. Earlier history remains there. Some format identifiers
retain the `spicy-regs` name; current releases require producer `spicy-docs` and
[current formats](docs/decisions.md#current-source-release-format-and-retained-evidence).
