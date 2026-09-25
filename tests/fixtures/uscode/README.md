# OLRC U.S. Code fixtures

Publisher files from `uscode.house.gov`, pinned on 2026-09-14 unless stated (the two classification fixtures on 2026-09-19, the three Table III chain pages on 2026-09-24).
These U.S. government documents are public domain. Offline tests establish
behavior for these shapes; they do not establish coverage or continuing live
availability.

| Fixture | Publisher object | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `xml_usc01@119-103.zip` | complete: [`xml_usc01@119-103.zip`](https://uscode.house.gov/download/releasepoints/us/pl/119/103/xml_usc01@119-103.zip), carrying `usc01.xml` at 284,795 bytes | 42,242 | `57b78a959a4cb8c07e31bc12af9682a81b03f4277e1f09a6cf131eb887859c9d` |
| `usc50A.xml` | complete: `usc50A.xml` inside `xml_uscAll@119-102.zip`, retained by RefSpec on 2026-08-24 | 1,627 | `eae46adb4ae592098604fec660f8ae20ffece7b94dbbe6976e422fe215a375a6` |
| `annual-2024usc01-head.htm` | reduced: the first 4,096 bytes of `2024/2024usc01.htm` (201,571 bytes) inside [`2024.zip`](https://uscode.house.gov/download/annualhistoricalarchives/XHTML/2024.zip), plus `\n</body>\n</html>\n` | 4,113 | `3944e008d1443825bbae484982538ed7e113af8368a88da193b8e5c722384c13` |
| `popularnames-head.htm` | reduced: [`popularnames.htm`](https://uscode.house.gov/popularnames/popularnames.htm) (11,106,277 bytes) through its first 9 entries, closed | 9,260 | `6c715b1dab0ae63d21a46ee50bc75b993d4bb102ad7cb9e9aaf1185581498259` |
| `table3-1955_360-head.htm` | reduced: [`1955_360.htm`](https://uscode.house.gov/table3/1955_360.htm) (117,524 bytes, 186 rows) through its first 4 rows, closed | 6,245 | `9fa0a4014cebc9e12f5497508557676d95fde44bc40ff092b8610b3ccd42569f` |
| `table3-111_226-head.htm` | reduced: [`111_226.htm`](https://uscode.house.gov/table3/111_226.htm) (53,528 bytes, 32 rows) through its first 4 rows, closed | 6,199 | `943c62a36a58f7f0a94da6276ba073e44cd3af439656be32abbaa9143740a301` |
| `table3-100_234-truncated.htm` | complete: every byte the publisher sent for [`100_234.htm`](https://uscode.house.gov/table3/100_234.htm), an act Table III has no page for, before it dropped the connection | 15,881 | `dc126dffdbde367d40149b96e5da70ca0d71dd9a3c95535d1d25a095ee66912e` |
| `table3-119_69-head.htm` | reduced: [`119_69.htm`](https://uscode.house.gov/table3/119_69.htm) (41,145 bytes, 5 rows) through its first 2 rows, closed; names 119-72 next | 5,386 | `bfdfbedc105307290d363f910e045815503d008bd26e7997177ed48600f66e0b` |
| `table3-119_72-head.htm` | reduced: [`119_72.htm`](https://uscode.house.gov/table3/119_72.htm) (39,853 bytes, 2 rows), closed; names 119-69 before and 119-73 next | 5,381 | `70f18081114a3847fb3b59f820f90c06a205f0854ce65c02ee651f22ce9e05fe` |
| `table3-119_73-head.htm` | reduced: [`119_73.htm`](https://uscode.house.gov/table3/119_73.htm) (42,398 bytes, 8 rows) through its first 2 rows, closed; current through 119-73, names 119-74 next | 5,383 | `8255a24c50e3f8b570570c76a493597818dc9588cde2a66aa69b84a171ee6872` |
| `table3-119_37.htm` | complete and unchanged, its per-request `jsessionid` included: every byte of [`119_37.htm`](https://uscode.house.gov/table3/119_37.htm) as retained by the 2026-09-25 rollup audit (`corpora/fork-execution-2026-09-21/parallel-rollup-audit-2026-09-25/congress-documents/raw/table3-119-37.htm`); 110 data rows, four of them with a blank act-section cell | 87,292 | `1e3fcbc7dbe87541c2183a50286567e2416074c4454c7ab707ce576f8b2e087d` |
| `table3-fulldump-head.xml` | reduced: the first 3 `<act>` elements of `fulldump@119-73.xml` (126,260,704 bytes) inside [`table3-xml-bulk.zip`](https://uscode.house.gov/table3/table3-xml-bulk.zip) | 4,948 | `158d910a5d76fd9cf954a382061e600ff3121af9651a41d3f4b983a33a9d1c1a` |
| `classification-tables-index.shtml` | reduced: [`classification/tables.shtml`](https://uscode.house.gov/classification/tables.shtml) (39,140 bytes) minus its 27 KB navigation menu, everything else kept | 13,285 | `6a4fbfe2c5834745dfbaabd4418549e25bf3dca3b2ac25a63e3e7fc241cfcba0` |
| `classification-tbl119pl_2nd-head.htm` | reduced: [`classification/tbl119pl_2nd.htm`](https://uscode.house.gov/classification/tbl119pl_2nd.htm) (115,140 bytes, 583 rows) through its column header plus 10 of the 583 data lines, closed | 14,073 | `2eb046d9bab9bce8a04606d23cff48b51b4ac942f653e3e0e6bb747b73e2fda6` |

## Reductions, stated exactly

Every reduction is a byte prefix of the publisher's file with closing tags
appended; no byte inside a kept region was rewritten except as noted here.

- **The JSF session id.** Every page stamps an anonymous `jsessionid=` into each
  menu link. In the five `.htm` fixtures it is replaced with the constant
  `jsessionid=SESSIONID`. The originals, session ids and all, are in the port
  receipt; `table3-100_234-truncated.htm` is 16,134 bytes there, SHA-256
  `d10dea18868af541a42aeb309e592a2340e83217106376e76c0f73a6cb5ee4a5`.
- **The site menu.** `popularnames-head.htm` and the `table3-*-head.htm`
  fixtures drop the 27 KB navigation menu every page on the site repeats,
  between `<div id="menu">` and the page's own content div, replaced by
  `<!-- site menu removed -->`. Nothing the readers look at lives there.
- **The classification table head keeps ten of 583 data lines**: the first six in page order, plus four
  chosen from deeper in the same block and copied verbatim -- a row whose act section quotes a new section
  (`113(a) "[12]"`), a row printing a page span (`637, 638`) with no statviewer link, a bare-`nt` row, and
  the first row whose section prints a capital (`26 4980D`, the section-key fold's case). The menu and
  session-id reductions are the ones above. The full page and its code-order twin are in the
  receipt; the two orders were parsed there to the same 583-row multiset. The tenth line was added on
  2026-09-23 by `cut_fixture.py` in `corpora/supply-2026-09-02/receipts/usc-section-key-2026-09-23/`,
  which keeps every earlier byte and inserts that line before `</pre>`.
- The truncated Table III fixture is **not** reduced beyond the session id: its
  point is that the publisher's answer stops mid-menu, and shortening it would
  remove the evidence. The publisher drops the connection there, and the tests
  replay it that way. The bytes are also the first 16 KB of every served page,
  which is why they are evidence of a failed request and never of absence.
- **The chain pages** were captured on 2026-09-24 by the drift audit's probe,
  which kept its session cookie, so they carry no session id. They keep their
  caption whole: the act, its prior and next acts, and the table's currency.

The build script is `build_fixtures.py` in
`corpora/supply-2026-09-02/receipts/port-P01-uscode-2026-09-14/`, beside the
original captures and the pin log. The chain pages' script is
`build_chain_fixtures.py` in
`corpora/fork-execution-2026-09-21/table3-walk-2026-09-24/spicy-docs/`; the
originals are in `drift-audit-2026-09-24/laws/raw/table3/` beside it.

## Observed shapes across every retained file

Qualified offline against RefSpec's retained publisher zips: the whole-corpus
`xml_uscAll@119-102.zip` (108,610,077 bytes, 58 titles, 697,301,368 bytes of
XML) and all 31 annual archives, 1994 through 2024 (1,835 members, 2.3 GB).

- **The namespace is the publisher's own, not GovInfo's.** All 58 titles and
  both live 119-103 captures are `uscDoc` in
  `http://xml.house.gov/schemas/uslm/1.0`, schema `USLM-1.0.15.xsd`. GovInfo's
  USLM 2.x namespace appears nowhere here.
- **Identity is in `<meta>`, not in the file name.** `docNumber` states `1` and
  `5a`; `docPublicationName` states `Online@119-102`. The publisher's own names
  disagree with each other: the URL spells `xml_usc05a@…zip` while the member
  inside is `usc05A.xml`, and `11a`, `18a`, `28a` stay lower case while `05A`
  and `50A` are upper.
- **One document carries no root `identifier`:** `usc50A.xml`, the eliminated
  Title 50 Appendix, converted by `USCConverter 1.1` in 2015 and reissued
  unchanged at every release point since. The other 57 carry `/us/usc/tN`.
- Titles carry `<main>`; the five appendix titles carry `<appendix>`.
- **Annual members state their own edition.** All 1,781 title members state all
  ten `AUTHORITIES-*` and `CONVERSION-*` comments, within the first 842 bytes.
  `AUTHORITIES-PUBLICATION-NAME` names the edition and supplement (31 distinct
  values, `1994 Edition` through `2024 Main Edition`);
  `AUTHORITIES-USC-TITLE-STATUS` is `positive-law` (781), `editorial` (974) or
  `repealed` (26).
- **Two members state another year:** `2016usc50a.htm` and `2017usc50a.htm` both
  state 2015, the last year the eliminated appendix changed. They are reported
  as carried forward, never refused.
- **The 54 non-title members are real:** `usc.css` (25 years), `index.html` (13),
  and the extra tables 2010 through 2013 ship (`2012uscTable3.htm`,
  `tbl112cd_2nd.htm` and others). They are kept by name, size and digest.
- **The 1994 edition is not UTF-8** (`0xFF` at offset 14,644,597 in
  `1994usc42.htm`), which is why only the ASCII identity header is decoded.
- **Table III lags the Code.** On 2026-09-14 the Code stood at release point
  119-103 and Table III at 119-73, which the bulk member's own name states.
- **The bulk member's vocabulary is closed and known.** Across all 48,973 acts
  and 317,590 records of `fulldump@119-73.xml`, `<act>` states exactly ten
  attributes and three child elements (`num`, `record`, and `public-law` on
  10,406 acts), and `<record>` states four attributes and five child elements.
  81,283 records state a Code status instead of a title and section; 15,434
  state no act section; 32,749 state `print-in-supplement`. Exactly one record
  states an empty `id` and one an empty `usckey`. `usckey` is not fixed width
  (31 and 34 characters both occur) and is never parsed.
