# Documented column domains

These publisher captures and one dated table snapshot let the
[source-domain check](../../docs/source-domain-drift.md) compare documented values
with observed values, offline.

## Publisher captures

The [capture manifest](documented-enumeration-capture-manifest-v1.json) records each
file's URL, timestamp, SHA-256, and byte length. RefSpec fetched and verified these
same bytes. `spicy_docs.sources.source_domains.read_capture` rechecks digest and
length on every read; parsers extract values directly from those pinned bytes.

- [regulations.gov OpenAPI](regulations-gov-openapi-v4-2026-08-03.yaml): three enums —
  `DocumentType`, `DocketType`, and `SubmitterType`. Other categories (`subtype`,
  `category`, `organizationType`) are agency-configurable, so they have no closed
  list to check. Tests preserve YAML's trimming of `Nonrulemaking ` and the literal
  ampersand in `Supporting & Related Material`.
- [RegInfo XSD](reginfo-rin-data-ver10262011.xsd): controlled values appear in
  documentation prose, not `xs:enumeration`. The parser reads `RULE_STAGE`,
  `PRIORITY_CATEGORY`, `RIN_STATUS`, and `MAJOR`. It collapses the duplicated
  `Not Major` value while retaining both raw and distinct counts.

`TTBL_ACTION` is deliberately excluded: its documentation lists 34 actions, but
its snapshot contains 1,139 distinct actions across 10,533 timetable entries.
Observed use is free text; treating the list as exhaustive would misreport it.

## Observed table values

The [2026-08-03 snapshot](observed-domain-snapshot-2026-08-03.json) records distinct
values with row support, null counts, and table row counts. It also pins the
publisher URLs, producer revision, digests, and lengths of the tables scanned.
It summarizes those tables; the full Parquet files are not checked in.

Use the [refresh command](../../scripts/README.md) to regenerate it from locally
downloaded tables. `scripts/check_source_domain_drift.py` both writes and checks
the snapshot, so observation and comparison use the same implementation.
