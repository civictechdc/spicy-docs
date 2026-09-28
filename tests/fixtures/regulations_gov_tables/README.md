# Regulations.gov published-table rows

`published-rows.json` holds twelve rows read back from the SpicyRegs fork host's
public `dockets`, `documents` and `comments` objects
(`https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/<object>`). Each row is
complete and unchanged: every column, in the Parquet footer's order, with the
publisher's spelling, including the trailing space in one `reason_withdrawn`.
The tests hold the `dockets`, `documents` and `comments` contracts to these rows,
column order included.

The rows were selected on 2026-09-25 by the predicates below and re-read by id
on 2026-09-28, after the host rewrote `comments` and `documents` with the
0.50.0 columns in the contract's order. Every value the 2026-09-25 rows held
is unchanged; the re-read adds `attachment_records_json` to each document and
the four comment-reference columns to each comment. Only FAA-2016-6907-0001's
`attachment_records_json` is non-NULL: the host read that document's attachment
relationship.

| Object | Last-Modified | ETag | SHA-256 |
| --- | --- | --- | --- |
| `dockets.parquet` | 2026-09-28 07:40:25 GMT | `9f13d49e9b953c212b7841301c2afea3-2` | `3a31edc95c735f96ac84d6bd1a2a06344beff54d7568063f44fc6533ea0924e9` |
| `documents.parquet` | 2026-09-28 07:34:24 GMT | `17b61f496f3812be6ff94178026f7fb6-10` | `fe9eb3628f22c97aabbe1eed7626727ef13f0416bd5f9de69fdc9eabca3f6fe5` |
| `comments.parquet` | 2026-09-28 08:19:12 GMT | `3f0770d0d4e0f4bb929c5958fd145f44-510` | `d876bc8dea207e406110b11dc34fd8b380059bc685ab3c81db4211204404a05a` |

The local copies were bound to the public objects by recomputing each
multipart ETag over 8 MiB parts (receipt
`fork-execution-2026-09-21/spicy-docs-0501/published-rows/` under
`~/Work/corpora`). The 2026-09-25 objects were `308b35c6…`, `d7487819…` and
`bf81f764…`.

## Selection

Each row is the one row a stated predicate selects. `min` is over the id column.

| Table | Row | Predicate |
| --- | --- | --- |
| `dockets` | `FAA-2016-6907` | The docket of `../listings/regulations-gov-document-detail.json`. |
| `dockets` | `ACF-2007-0125` | `min(docket_id)` where `docket_type = 'Rulemaking'`, `rin` is stated and `abstract` is under 240 characters. |
| `documents` | `FAA-2016-6907-0001` | The document `../listings/regulations-gov-document-detail.json` captured. |
| `documents` | `ACF-2015-0002-0331` | `min(document_id)` where `withdrawn = 'true'` and a reason is stated, title and reason each under 100 characters. |
| `documents` | `DOE-HQ-2010-0016-0001` | `min(document_id)` stating `additional_rins` and `comment_end_date`, title under 120 characters. |
| `comments` | `AHRQ-2025-0001-0411` | `min(comment_id)` with `derived` text from an organization and no personal name: text under 400 characters, no phone-number shape, `comment` under 120. |
| `comments` | `APHIS-2004-0018-0031` | `min(comment_id)` titled `Anonymous public comment`, no personal name, `comment` under 160 characters, no text extraction. |
| `dockets` | `ACF-2008-0001` | `min(docket_id)` where `rin = 'Not Assigned'`. |
| `documents` | `ABMC-2017-0001-0001`, `ABMC-2005-0001-0001`, `ACF-2023-0002-0002`, `BIS-2018-0002-4451` | For each `document_type` the rows above lack (`Proposed Rule`, `Notice`, `Supporting & Related Material`, `Public Submission`), `min(document_id)` with a title under 100 characters. |

The comment predicates exclude personal names and phone numbers so that no
submitter's contact details are copied here. The `Public Submission` document is
a company's filing. Comments are public records.

## What the rows establish

- the published column set and order of each table on that day;
- which column holds the identity each contract declares;
- that each value a contract names in backticks occurs in a published row of
  that table or in the extract that fills it;
- one cross-check: the captured detail of `FAA-2016-6907-0001` (2026-09-14),
  through `DOCUMENT.extract`, equals the published row on every column the
  extract fills from the detail (`attachment_records_json` comes from the
  separately read attachment relationship).

They do not establish coverage, and they do not establish that a key is unique.
The keys were checked over whole objects; see
[table contracts](../../../docs/tables.md#what-the-key-measurement-can-and-cannot-see).
