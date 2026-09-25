# Regulations.gov published-table rows

`published-rows.json` holds twelve rows read back from the SpicyRegs fork host's
public `dockets`, `documents` and `comments` objects on 2026-09-25
(`https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/<object>`). Each row is
complete and unchanged: every column, in the Parquet footer's order, with the
publisher's spelling, including the trailing space in one `reason_withdrawn`.
The tests hold the `dockets`, `documents` and `comments` contracts to these rows.

| Object | Last-Modified | ETag | SHA-256 |
| --- | --- | --- | --- |
| `dockets.parquet` | 2026-09-25 20:51:53 GMT | `50d8cfba5aa312c5fe19d67418f41c5d-2` | `308b35c66f8f3694c8048f166dcdf4e3282256c6aeed4974d21e799c3c4580df` |
| `documents.parquet` | 2026-09-25 20:51:57 GMT | `f3324286311a483b463f92a16b6f3baf-10` | `d7487819971c84ba184853ed09be6bb1df7490eaecc3054487dcd467a4303801` |
| `comments.parquet` | 2026-09-25 18:15:38 GMT | `731e88e8d2ee0be0532e7461a355494a-508` | `bf81f764598eaab75eb1667b40e5a9dd5b384d35b6bc8cbad58a10d44fd9c15e` |

The local copies were bound to the public objects by recomputing each
multipart ETag over 8 MiB parts. The first five rows below were first read from
the 19:54 `dockets` and `documents` objects and are byte-identical in the 20:51
ones.

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
  extract fills.

They do not establish coverage, and they do not establish that a key is unique.
The keys were checked over whole objects; see
[table contracts](../../../docs/tables.md#what-the-key-measurement-can-and-cannot-see).
