# Source-native operator CLI

Command behavior reviewed against refactor `a8f0da9`.

The maintained [operator guide](../docs/cli.md) now covers all four commands:
`publish`, `verify`, `publish-public-table`, and `verify-public-table`. It includes
source selectors, dependency requirements, examples, output, errors, and the
distinction between full source replay and public-table admission.

This page replaces the generated 2026-09-03 command inventory, which described
only the first two commands. Its original generation provenance remains in
[metadata.json](metadata.json) and its text remains in Git history.

For implementation ownership, see [architecture](../docs/architecture.md).
For contributor checks and injected input, see [CONTRIBUTING.md](../CONTRIBUTING.md)
and the [offline example](../examples/offline_release.py).
