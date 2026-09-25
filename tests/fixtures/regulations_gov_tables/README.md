# Regulations.gov published-table rows

`published-rows.json` holds seven rows read back from the SpicyRegs fork host's
public `dockets`, `documents` and `comments` objects on 2026-09-25
(`https://pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev/<object>`). Each row is
complete and unchanged: every column, in the Parquet footer's order, with the
publisher's spelling, including the trailing space in one `reason_withdrawn`.
The tests hold the `dockets`, `documents` and `comments` contracts to these rows.

| Object | Last-Modified | ETag | SHA-256 |
| --- | --- | --- | --- |
| `dockets.parquet` | 2026-09-25 19:54:22 GMT | `635df1608fae442726e36a573ea074aa-2` | `07bf427e689a19267d5585754fb8a3bc95e7b91d78f1e4d9ea4163eb3fbc38cd` |
| `documents.parquet` | 2026-09-25 19:54:25 GMT | `079cdbaf15234ef3f0d3589c83d61623-10` | `ffa2da6cd4a3ed399ee755a66fca6ffe272d01f2b2d859ea71adebb40c76be52` |
| `comments.parquet` | 2026-09-25 18:15:38 GMT | `731e88e8d2ee0be0532e7461a355494a-508` | `bf81f764598eaab75eb1667b40e5a9dd5b384d35b6bc8cbad58a10d44fd9c15e` |

The local copies were bound to the public objects by recomputing each
multipart ETag over 8 MiB parts.

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

The comment predicates exclude personal names and phone numbers so that no
submitter's contact details are copied here. Comments are public records.

## What the rows establish

- the published column set and order of each table on that day;
- which column holds the identity each contract declares;
- one cross-check: the captured detail of `FAA-2016-6907-0001` (2026-09-14),
  through `DOCUMENT.extract`, equals the published row on every column the
  extract fills.

They do not establish coverage, and they do not establish that a key is unique.
Uniqueness was measured over the whole generation; see
[table contracts](../../../docs/tables.md#the-regulationsgov-tables-are-keyed-on-the-publishers-id).
