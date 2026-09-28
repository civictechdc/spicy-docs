# Native legal-reference published-table rows

`published-rows.json` holds rows read back on 2026-09-28 from the SpicyRegs fork
host's public `native_legal_references` and `native_legal_reference_reads`
objects, generation `sha256:53755e3e…` of the `native-legal-references` family
(`https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/generations/native-legal-references/53755e3e0076dfa5bacc5681c4316f4806bf23694693d1e8bbe551a70b1a711c/<object>`,
named by `publication.v2.json`). Each row is complete and unchanged: every
column, in the Parquet footer's order, with the host's spelling. The tests hold
both contracts to these rows, column order included.

| Object | Last-Modified | ETag | SHA-256 | Rows |
| --- | --- | --- | --- | --- |
| `native_legal_references.parquet` | 2026-09-27 22:19:04 GMT | `21049d032aa5e1092c6b53fe6caad987` | `cb6b341615c4deba73e93e0fe814b237e89856babad31d28db1e3c2abe81e4b9` | 881 |
| `native_legal_reference_reads.parquet` | 2026-09-27 22:19:04 GMT | `64ff2db53ce176dd7974c87947900e6e` | `26b102153a7b0628122890ed30bd2889032e79c37ec855552b491758d4e2ef5f` | 2 |

Both SHA-256s equal the ones the publication index states, and each ETag is the
MD5 of the local copy (receipt `fork-execution-2026-09-21/native-refs-contract/`
under `~/Work/corpora`).

## Selection

| Table | Rows | Predicate |
| --- | --- | --- |
| `native_legal_references` | nine | For each `(observation_kind, element_tag, interpretation_status)`, the row with the lowest `occurrence_index` read as an integer. |
| `native_legal_references` | U.S. Code `71` | The lowest-index `native_reference` whose `href` is NULL. |
| `native_legal_reference_reads` | both | Every row. |

The U.S. Code rows were read from `usc01.xml` inside
`../uscode/xml_usc01@119-103.zip`, the same bytes (`sha256:d3228083…`), so the
tests re-shape those rows from the archive and compare every column a shaper
fills. The eCFR rows were read from the complete eCFR Title 1 XML
(`sha256:fe18aad1…`, 477,387 bytes), which is not retained here;
`../cfr/ecfr-authority-title1-part18.xml` is a fragment of it with its own digest
and paths.

## What the rows establish

- the published column set and order of each table on that day;
- which columns hold the identity each contract declares, and that the
  published scopes are `native_reference_scope_id` of their family, record key
  and edition;
- that each value a contract names in backticks occurs in a published row or in
  the code that fills the table;
- for the U.S. Code rows, that the shapers reproduce every column they fill.

They do not establish that a key is unique or that every live row fits; those
were checked over both whole objects (see
[table contracts](../../../docs/tables.md#the-native-legal-reference-tables-are-a-scanners-observations-and-its-reads)).
