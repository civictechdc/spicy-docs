# FERC eLibrary WebAPI fixtures

Captured and derived on 2026-09-24 by probing `https://elibrary.ferc.gov`
through its own Angular bundles (`/eLibrary/assets/config/app-settings.json`
names the API base `/eLibraryWebAPI/api/`; the lazy chunks `913`, `common` and
`103` name the routes and the request bodies). Two probe sessions ran that
day: the original one (24 GETs and 5 POSTs, paced at 1-3 s) and a second,
bounded session that replicated the SPA's login handshake, retried the search
in seven body spellings (10 requests), captured the two bundle-derived routes
live, and made one DownloadPDF attempt (17 requests total, plus bundle
fetches). The second session's receipts — headers and bodies verbatim — are
retained under `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-24/`.

## Live captures (real publisher bytes)

| Fixture | Route | Provenance |
| --- | --- | --- |
| `elibrary-app-settings.json` | `GET /eLibrary/assets/config/app-settings.json` | 200, 206 bytes, 2026-09-24; the SPA's own API-base and application-id statement |
| `docket-description-rm24-5.json` | `GET /eLibraryWebAPI/api/Docket/getDocketDescription/RM24-5` | 200, 67 bytes, 2026-09-24 |
| `sub-dockets-rm24-5.json` | `GET /eLibraryWebAPI/api/Docket/getSubDocketSearch/RM24-5` | 200, 20 bytes, 2026-09-24; live answer `{"DataList":["000"]}` — note the live envelope carries no `ErrorList` key |
| `file-list-p8-20251125-3057.json` | `GET /eLibraryWebAPI/api/File/GetFileListFromP8/20251125-3057` | 200, 2,362 bytes, 2026-09-24; the accession is a public letter order accepting a MISO filing under ER25-3543 (one row: GUID `ID`, `Orig_File_Name` `ER25-3543-000.docx`, `File_Type_Code` `DOCX`) |
| `advanced-search-empty-rm24-5.json` | `POST /eLibraryWebAPI/api/Search/AdvancedSearch` | 200, 100 bytes, 2026-09-24; request body: `searchText:"*"`, `docketSearches:[{"docketNumber":"RM24-5","subDocketNumbers":[]}]`, `allDates:true`, `availability:null`, no class/category filter, `resultsPerPage:3` |
| `docket-atmsdocs-empty.json` | `GET /eLibraryWebAPI/api/Docket/GetATMSdocs/RM24-5/01-01-2024/12-31-2024/DocketFullNumber` | 200, 30 bytes, 2026-09-24; a requested-empty observation of a real docket |
| `new-dockets-rbcreatedate-2026-09-23-2026-09-25.json` | `GET /eLibraryWebAPI/api/Docket/GetATMSdocs/rbCreateDate/09-23-2026/09-25-2026/DocketFullNumber` | 200, trimmed to four rows of a 203-row answer, 2026-09-25; `DocketSheetlink` verbatim; the full envelope and the two preceding zero answers of the identical URL are retained under `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/` |
| `new-dockets-rbfilingdate-2026-09-20-2026-09-25.json` | `GET /eLibraryWebAPI/api/Docket/GetATMSdocs/rbFilingDate/09-20-2026/09-25-2026/DocketFullNumber` | 200, trimmed to five rows of a 283-row answer, 2026-09-25, each identical to its receipt row and kept in receipt order: receipt rows 1-3 and 14, and row 130, `ID-10800-000`, added 2026-09-25 to pin the serial-numbered `ID-` docket spelling the docket grammar admits (the answer holds three `ID-` dockets); full envelope retained in the receipt directory above |
| `docket-sheet-er11-4046-001.json` | `POST /eLibraryWebAPI/api/Docket/GetSingleDocketSheet` | 200, 2,388 bytes, 2026-09-25 (SHA-256 `9312ea67…`); body `{"dockets":"er11-4046","subdockets":"001","filed_date_beg":"01-01-1960","filed_date_end":"09-25-2026","complete_flag":0,"numHits":100,"pageNumber":0}`; three documents (accessions `20110714-5024`, `20110715-3051`, `20110816-3002`), one `DocumentsItem` entry per row, `AuthorsItem`/`FedCitesItem` empty lists, `document_id` 0 on every row, `Page.totalHits` 3; the raw response is retained at `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/docket-sheet-er11-4046-001.json` and the module-path verification receipt at `.../docket-sheet-2026-09-25.jsonl` |
| `class-types-trimmed.json` | `GET /eLibraryWebAPI/api/Search/GetClassTypes` | 200, 36,297 bytes, 2026-09-24 (SHA-256 `1f6d84a27baf34e878556ed62d560f62c199adc945ab6f45affd68d6e1a90a6c`); trimmed to the five comment-class rows and the one `Uncertain` row |

The DownloadPDF live capture (POST `File/DownloadPDF?accesssionNumber=20251125-3057`,
`200 application/pdf`, 1,972,667 bytes) is not committed: it is whole-publisher
bytes too large for a fixture and is retained in the receipt directory above.

## Synthetic (row shapes derived from the bundles; not publisher bytes)

These earlier fixtures spell search-row shapes read from the bundles. The
later live fixtures below qualify the actual wire fields and pagination;
the synthetic ones remain useful for malformed and duplicate-row cases: `searchHits` rows from the results table in chunk `913`
(`reference`, the publisher's own misspelling `acesssionNumber`, `filedDate`,
`docDate`, `postedDate`, `category`, `classTypes`, `description`,
`affiliations`, `availCode`, `fileName`, `fileSize`, `transmittals`,
`documentId`, `docketNumber`, `parentAccessionNumber`).

| Fixture | Route | Note |
| --- | --- | --- |
| `advanced-search-rm24-5-comments-p1.json` | `POST Search/AdvancedSearch` | page 1 of a 2-page walk (page size 2, declared 3) |
| `advanced-search-rm24-5-comments-p2.json` | `POST Search/AdvancedSearch` | terminal short page of the same walk |
| `docket-sheet-er11-4046-001-p1.json` | `POST Docket/GetSingleDocketSheet` | synthetic page 1 of a 2-page walk: the live sheet's first two rows, `Page.numHits` 2, `totalHits` 3, `pageNumber` 0 |
| `docket-sheet-er11-4046-001-p2.json` | `POST Docket/GetSingleDocketSheet` | synthetic terminal page: the live sheet's third row, `pageNumber` 1 |

`AuthorsItem`/`FedCitesItem` entry shapes are unmeasured (the live lists are
empty); the flatten tests' `{"FullName": ...}`/`{"Citation": ...}` entries
are invented placeholders proving verbatim retention only.

## What live probing established and what it could not (2026-09-24)

- **The original zero-hit finding was transient and unexplained.** An early
  probe recorded zero hits from every off-network body it tried. A 2026-09-24
  re-probe from a plain shell did not reproduce it: the operator-verified
  full wire body, the module's then-minimal body, and empty-date and
  `idolResultID:""` variants all answered docket RM24-5's eleven records
  across six rapid same-session requests. The original empty responses
  remain fixtures for requested-empty handling; the zero itself is treated
  as transient, not a property of the route. Receipts:
  `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-24/` and
  `.../ferc-elibrary-2026-09-25/search-page-convention.jsonl` (the 2026-09-25
  page-convention walk: RM24, `totalHits: 207`; `curPage` 0 and 1 the
  identical first page, 2 the second, 3 the 7-row terminal page).
- **`File/GetFileListByAccession` is not deployed.** It answered the IIS 404
  "File or directory not found" live; the deployed SPA's file-list page
  (chunk `103`) calls `File/GetFileListFromP8/{accession}` instead, which
  answered with the real row captured above.
- **`POST Search/GeneralSearch` answered the framework's 404 "No HTTP
  resource"** although chunk `913` calls it; the deployed API keeps only
  `AdvancedSearch`.
- **`www.ferc.gov/ferc-online/ecomment` answered 403 (Akamai)** to a scripted
  browser-profiled GET, so the eComment portal itself was not probed.
- **A new-docket window answering zero is a publisher-side bug (2026-09-25).**
  The identical URL
  `Docket/GetATMSdocs/rbCreateDate/09-23-2026/09-25-2026/DocketFullNumber`
  answered 200 with an empty `DataList` twice within a second, then 203 rows
  on the third request; `rbFilingDate` 09-20→09-25 answered 283 rows,
  agreeing with the operator's earlier measurements of the same windows.
  The empty answers are retained as receipts, never read as "no new
  dockets"; the reader records an empty answer with its timestamp and the
  window is re-asked, a non-empty later answer replacing the empty
  observation. Receipts:
  `~/Work/corpora/supply-2026-09-02/receipts/ferc-elibrary-2026-09-25/`.
- **The docket-sheet route answers the SPA's own body (2026-09-25).**
  `POST Docket/GetSingleDocketSheet` with the SPA's wire body (dockets
  lowercased, dates `MM-dd-yyyy`, zero-based `pageNumber`) answered ER11-4046
  sub-docket 001's three documents, one `DocumentsItem` entry per `DataList`
  row, `Page.totalHits: 3`; the module-path verification fetch agreed
  byte-for-byte with the earlier plain-shell probe (SHA-256 `9312ea67…`).
  `document_id` measured 0 on every row and is not read; each document's
  identity is its `accession_no`, the join value into the file-list route.
  Receipts: `.../docket-sheet-er11-4046-001.json` and
  `.../docket-sheet-2026-09-25.jsonl`.

## Pinned vocabularies (from RefSpec's digest-pinned PDFs)

`advanced-search-all-dockets-request.json` is the operator's browser request
for filed dates 2026-07-27 through 2026-09-25, no docket restriction, and
`All` types under `Approved Designation` and `Application/Petition/Request`.
The initial `curPage:0` is retained verbatim; the production walk starts at
one under the measured paginator convention.

`class-types-discovery.json` selects complete rows from the 2026-09-25
`GetClassTypes` capture: a rulemaking comment, a legacy conversion value,
the category variants of `Agenda Materials`, and an API-only application
type. Whitespace is reformatted; field values and row order are preserved.
Full request/response bytes and SHA-256 receipts are outside the repository
at `~/Work/corpora/supply-2026-09-02/receipts/ferc-reference-class-search-20260925T144857Z/`.
The vocabulary response digest is
`sha256:1f6d84a27baf34e878556ed62d560f62c199adc945ab6f45affd68d6e1a90a6c`.

`src/spicy_docs/sources/ferc/vocabulary.py` pins FERC's June 2025 docket-prefix
PDF (`sha256:c32efae9…`, 95 prefixes) and January 2025 class/type PDF
(`sha256:af632c9c…`, 235 rows collapsing to 230 unique class/type pairs).
The bytes are RefSpec's pinned acquisitions (captured 2026-08-03,
`RefSpec/output/registry-real-data-sources/`); the parsed rosters were
re-derived 2026-09-24 with RefSpec's own parsers and verified against this
module's literals.

## Successful browser and paged discovery (2026-09-24/25 UTC)

The sanitized browser HAR and each exact direct POST response are retained at
`~/Work/corpora/supply-2026-09-02/receipts/scraper-completion-2026-09-24T235248Z/ferc/`.
The qualification scripts there pin request bodies, URLs, methods, timestamps,
byte counts and SHA-256 values. No cookies or credentials are in these fixtures.

| Fixture | Origin and observation |
| --- | --- |
| `advanced-search-browser-request.json` | Exact browser POST payload for RM24-5, all dates; responded with eleven records. This proves `classTypes` on the wire and omission of unused selectors. |
| `advanced-search-rm24-5-live-comments-p1.json` | Exact production direct POST answer, page one, page size two, declared total five. |
| `advanced-search-rm24-5-live-comments-p2.json` | Exact page two answer, two further distinct source references, declared total five. |
| `advanced-search-rm24-5-live-comments-p3.json` | Exact terminal page three answer, one source reference, declared total five. |
| `advanced-search-rm24-5-live-terminal.json` | Exact empty page after a full final page of five comment rows; declared total stays five. |

The live walk selected `classTypes:[{"documentClass":"Comments/Protest","documentType":"Rulemaking Comment"}]`
and `docketSearches:[{"docketNumber":"RM24-5","subDocketNumbers":[]}]`.
Its five distinct source references match the corresponding records in the
browser's all-class result. The unfiltered direct walk independently returned
the browser's entire identity set in pages of five, five, one. The raw
responses retain the publisher's null `searchResultId`; synthetic fixtures
continue to cover forwarding a non-null token.

## Original-file download (2026-09-25 UTC)

The real browser's **Download File** action for `20240807-5052` sent
`POST /eLibraryWebAPI/api/File/DownloadP8File`. Its exact body is
`original-download-browser-request.json`. The direct production acquirer
uses the same body, with the file-list GUID in `fileidLst` and `Islegacy:false`.

| Fixture | Origin and pin |
| --- | --- |
| `file-list-p8-20240807-5052.json` | Exact `GET File/GetFileListFromP8/20240807-5052` answer at `2026-09-25T00:42:12.452322Z`: 2,345 bytes, SHA-256 `c77d447d73c7d53695cbdecbe461f4755c85a179a633378b194e41d2cbf72cfc`. |
| `original-20240807-5052.pdf` | Exact original POST answer at `2026-09-25T00:42:12.882242Z`: 241,123 bytes, SHA-256 `c7ef927914a7a53d17ed0f3ddf4fc67143bfb91ccbd401bab162929510fc818f`; identical to the browser download and the preceding direct control. |

The complete five-comment original-file walk, browser network trace and
generated-PDF control are retained outside the repository at
`~/Work/corpora/supply-2026-09-02/receipts/scraper-delivery-2026-09-25T003133Z/ferc/`.
The generated PDF for this accession was 318,445 bytes with a different
digest; it is not substituted for the original fixture. Metadata mutations
in the tests are synthetic and do not replace these exact source bytes.
