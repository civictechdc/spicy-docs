# USITC EDIS fixtures

Reduced captures of the USITC EDIS `/data` web service and its RSS
notification feed. Every byte in a row kept here is the publisher's own,
served over HTTPS, either archived by the Wayback Machine or captured live
as named below; trims remove whole rows and keep the rest byte-exact, so no field was
edited, reordered or re-encoded. Provenance and the live re-verification of
the routes (2026-09-24, real-browser transport; plain clients are refused by
the host's Akamai edge on every path) are in
[`docs/sources/usitc-edis.md`](../../../docs/sources/usitc-edis.md).

| Fixture | Route captured | Wayback timestamp | Trim |
| --- | --- | --- | --- |
| `investigation-731-1103.xml` | `/data/investigation/731-1103` | 2021-05-19 03:06:55 UTC | none (4 investigation rows, whole) |
| `investigation-731-1103-final.xml` | `/data/investigation/731-1103/final` | 2021-05-19 02:50:20 UTC | none (1 row, whole) |
| `investigations-active-2019.xml` | `/data/investigation?investigationstatus=Active` | 2019-07-19 06:00:58 UTC | first 6 of 100 investigation rows |
| `documents-337-1145-violation.xml` | `/data/document?investigationNumber=337-1145&investigationPhase=Violation` | 2020-07-13 08:36:15 UTC | first 6 of 100 document rows |
| `documents-337-3673-2023.xml` | `/data/document` | 2023-04-03 23:03:46 UTC | first 3 of 20 document rows |
| `attachment-111112.xml` | `/data/attachment/111112` | 2023-04-03 15:02:58 UTC | none (1 row, whole) |
| `feed-2022-05-27.xml` | `/external/rss/render.rss/?criteria=CRITERIONINVDEL:5193:PHASE:Violation:CRITERIONINVDEL:8018:PHASE:Violation:CRITERIONANOTIFY:true` | 2022-05-27 20:24:51 UTC | first 4 of 37 items |

The two document fixtures pin the two document-date spellings observed
across captures (`2020/07/09 00:00:00` and `2023/04/03 00:00:00`; the 2010
guide's example shows a third, `2005-01-25 00:00:00.0`), so the parser keeps
dates verbatim rather than reading them. `attachment-111112.xml` states an
empty `<pageCount/>`, and both investigation fixtures state empty
`<docketNumber/>` elements, pinning empty-element handling. The 2023 capture
arrived `application/xml`, the 2019-2021 captures `text/xml`; both media
types are accepted.

`document-894762.xml` is the complete, unmodified response from
`https://edis.usitc.gov/data/document/894762`, captured through Zyte's raw HTTP
transport on 2026-09-25 at 14:06:27 UTC without an EDIS credential. The response
was 1,079 bytes with SHA-256
`48b08fbca085e60451a4b6e4fa48b22ab36669e162f2d4012759f2d5b7b1a813`.
It proves the guide's single-document route answers one public document without
pagination. The request receipt is `edis-guide-review-2026-09-25/probe-result.json`
in the campaign receipts.

`bulk-index-894762.html` is the complete, unmodified `index.html` member from
the browser bulk job for public document 894762, downloaded on 2026-09-25 at
14:52:35 UTC. The index is 2,371 bytes with SHA-256
`887d2184b9c27872d32df49ab4b3ea0ce4d4a9eb77279fe9697fbdf57bd3e8ca`.
Its link hrefs include a middle sequence number that the displayed filenames
omit. Each row identifies one attachment and preserves its document metadata.
The archive and transfer receipt remain in `edis-browser-recovery-2026-09-25`;
archive SHA-256 is
`b20239265c6e5faa394f91afd54cfdcc57c3ccb75d4ac4ac215b8c6646dc34a7`.
Offline archive tests combine this exact index with explicitly synthetic tiny
PDFs; no synthetic PDF is presented as a publisher capture.

`documents-337-145-prefix.xml` keeps three whole rows of the live answer to
`https://edis.usitc.gov/data/document?investigationNumber=337-145&pageNumber=1`,
captured through Zyte's raw HTTP transport on 2026-09-25 at 20:48:57 UTC without
an EDIS credential. The exact response was 19,723 bytes with SHA-256
`5be12c6adaebf6bd6dcdad3f6fe1dccc531db6afbe66db15f4b91083a08c516d` and held
20 rows, every one for 337-1451, 337-1453 or 337-1454 and none for 337-145:
the publisher matches a partial investigation number. The trim keeps rows 1,
4 and 20 (one per investigation) and the wrappers byte-exact. Requests,
responses and the replay scripts are in the campaign receipt
`edis-partial-number-probe-2026-09-25`.

`attachment-880936-empty-download.xml` retains the first attachment row from
`https://edis.usitc.gov/data/attachment/880936`, captured live on
2026-09-24 at 23:08:03 UTC. The exact response was 10,358 bytes with SHA-256
`ee651b1a45ac6bdf96cfb399e51b914ddfdc1cae559e9aab974badc07b5c649b`.
The trim removes the remaining whole attachment rows without changing the
retained row or XML wrappers. The publisher states `<downloadUri/>`: metadata
is available, but no download URL is offered. The document listing marks
this document `Confidential`; its file body was not requested. Exact responses
and replay commands are retained in the campaign receipt directory
`scraper-review-live-2026-09-24T225923Z`.

`investigations-active-2019.xml` carries the filter in its URL's own 2019
spelling, `?investigationstatus=Active` (all lowercase), and its rows all
state `Active` — that spelling filtered in 2019. Measured live 2026-09-24
(receipt `usitc-edis-filters-2026-09-24`), the lowercase spelling is ignored
(the same unfiltered first page answers Active, Inactive and nonsense
values alike), while the guide's parameter-table spelling
`investigationStatus` (camelCase) still filters; the URL builder now writes
the camelCase spelling.

Publisher PDF bytes remain outside the fixtures. Historical anonymous
downloads on 2026-09-24 returned HTTP 401, and an early credentialed attempt
failed at the proxy before reaching EDIS (receipts
`usitc-edis-download-ladder-2026-09-24` and
`usitc-edis-credentialed-2026-09-24`). The later EDIS-token qualification
downloaded both public PDFs for document 894762, and the browser bulk job
returned byte-identical PDFs. Those originals and their checks are retained in
`edis-token-qualification-2026-09-25` and `edis-browser-recovery-2026-09-25`.
