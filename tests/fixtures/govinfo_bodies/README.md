# GovInfo package body fixtures

Complete, unchanged publisher responses for one small package, captured on
2026-09-19 with `Accept-Encoding: identity`. These U.S. government documents
are public domain. Offline tests establish behavior for these shapes; they do
not establish coverage or continuing live availability.

`CRPT-119hrpt1` is a four-page House Rules Committee report, the smallest
complete package across the collections measured, so all three of its
responses fit well inside the fixture bound.

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `summary-CRPT-119hrpt1.json` | [`packages/CRPT-119hrpt1/summary`](https://api.govinfo.gov/packages/CRPT-119hrpt1/summary), keyed with `X-Api-Key` | 1,800 | `818d6a4dc8678a6b2972eb2f0e4596be2c576087508bb49caeb5d8be588e5bc1` |
| `mods-CRPT-119hrpt1.xml` | [`packages/CRPT-119hrpt1/mods`](https://api.govinfo.gov/packages/CRPT-119hrpt1/mods), keyed with `X-Api-Key` | 9,787 | `d73ea7b12140ca7e1ad08649092a9e14a432a9fce8948d8a4975e4f3cd43f9d2` |
| `body-CRPT-119hrpt1.htm` | [HTML rendition](https://www.govinfo.gov/content/pkg/CRPT-119hrpt1/html/CRPT-119hrpt1.htm), keyless | 13,953 | `d2575146c81d989831fd08e8f424eddb048346bfe78670db994c0a107b584ad9` |
| `body-CRPT-119hrpt105.htm` | [HTML rendition](https://www.govinfo.gov/content/pkg/CRPT-119hrpt105/html/CRPT-119hrpt105.htm), keyless | 8,504 | `903f3aadd805b3ed85066bef29fa4d3f236501b6e94cb531168ed189362eca19` |
| `body-CRPT-119hrpt796.htm` | [HTML rendition](https://www.govinfo.gov/content/pkg/CRPT-119hrpt796/html/CRPT-119hrpt796.htm), captured 2026-09-21 | 81,335 | `43eb74dac1580417ebb6f61bbc4b65b0c7eb0582d3057690fdd30140856ab971` |
| `summary-CPRT-118HPRT57104.json` | [`packages/CPRT-118HPRT57104/summary`](https://api.govinfo.gov/packages/CPRT-118HPRT57104/summary), keyed with `X-Api-Key` | 1,220 | `b3fedfb456de587366b84087248f7a075fc22567fc3c814b580ae87ef5ce2547` |
| `mods-CPRT-118HPRT57104.xml` | [`packages/CPRT-118HPRT57104/mods`](https://api.govinfo.gov/packages/CPRT-118HPRT57104/mods), keyed with `X-Api-Key` | 6,221 | `7d30cbee9e219929472608daf15871c46f3c5ade926d698f48485c2ef798fe19` |

No fixture above was reduced or reformatted. The credential travels only in the
request header, and the capture script refused to write any file whose bytes
contained the key or an `api_key=` parameter; none did. The keyless body route
takes no credential at all.

`body-CRPT-119hrpt796.htm` was retained during the 2026-09-21 data validation
sprint. Its bytes match the earlier hosted report capture's digest. It keeps
all eight heading/body blocks, including generic headings that the old table
shaper mislabeled as agencies. The receipt is
`receipts/data-validation-sprint-2026-09-21/legislative/fresh-package-bodies/`
under the supply corpus; the remediation replay is beside it under
`receipts/remediation-sprint-2026-09-21/report-headings/`.

## The committee-print collection (CPRT)

`CPRT-118HPRT57104` was found through a keyed `published` walk scoped to the
`CPRT` collection (2020-01-01 through 2024-12-31, 1,118 packages) and chosen
for its `"pages": "1"` summary field, the smallest found. Its summary states
`"documentType": "HPRT"` and `"docClass": "HPRT"` -- the chamber-plus-doctype
token is spelled **upper-case** here, unlike `CRPT`'s own lower-case
`hrpt`/`srpt`/`erpt` -- so `bodies.py`'s `CPRT` grammar
(`{congress}{HPRT|SPRT|JPRT}{number}`) is measured, not inferred from `CRPT`'s
shape. A wider walk (2018-2024, 100 packages) also turned up real `SPRT` ids
(`CPRT-113SPRT52146` and others) and `JPRT` ids (`CPRT-116JPRT41347` and
others), confirming all three chambers' tokens without needing to fetch any of
them. The MODS states HTML, PDF and XML renditions, all at the standard
`content/pkg/{id}/{folder}/{id}.{extension}` addresses `package_body_locator`
already derives, so no new locator code was needed for this collection --
only the grammar entry.

## Multi-part committee reports

Captured 2026-09-23. `CRPT-119hrpt811` was the one report the spicy-regs
committee-reports rollup refused that day. `CRPT-112hrpt38` shows the same shape
in the 112th Congress, `CRPT-119hrpt455` the shape whose parts are all
constituents, and `CRPT-119hrpt494` the unsuffixed Part 1 beside a `-pt2`.

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `summary-CRPT-119hrpt811.json` | [`packages/CRPT-119hrpt811/summary`](https://api.govinfo.gov/packages/CRPT-119hrpt811/summary), keyed with `X-Api-Key` | 1,293 | `e2c404c897f6c98b43308c462094c7d6e255e37eaee364fd256a84bc23cec34f` |
| `mods-CRPT-119hrpt811.xml` | [`packages/CRPT-119hrpt811/mods`](https://api.govinfo.gov/packages/CRPT-119hrpt811/mods), keyed with `X-Api-Key` | 26,279 | `aba0227068f60977bb1ee98d58add159064bb2b38e7b235e70b8673de7b3e125` |
| `mods-CRPT-112hrpt38.xml` | [`packages/CRPT-112hrpt38/mods`](https://api.govinfo.gov/packages/CRPT-112hrpt38/mods), keyed with `X-Api-Key` | 13,932 | `ddc18b4eef1895e89576f623def42712f91e24a0d00f9b4f971a8bf6d88f6fc0` |
| `mods-CRPT-119hrpt455.xml` | [`packages/CRPT-119hrpt455/mods`](https://api.govinfo.gov/packages/CRPT-119hrpt455/mods), keyed with `X-Api-Key` | 24,549 | `290e09efb3f28d77e3e23cd379d8e826e8894ef444aea0fd383377a210d86c59` |
| `summary-CRPT-119hrpt455.json` | [`packages/CRPT-119hrpt455/summary`](https://api.govinfo.gov/packages/CRPT-119hrpt455/summary), keyed with `X-Api-Key` | 1,399 | `1d483854f59a0c6d3c4bf521c4b2a6ec44391d16391faf3271a8b1884ecaceb0` |
| `summary-CRPT-119hrpt494.json` | [`packages/CRPT-119hrpt494/summary`](https://api.govinfo.gov/packages/CRPT-119hrpt494/summary), keyed with `X-Api-Key` | 1,381 | `6d1e7dbda2f69f71bd7cb626025cb8378ea90e457731e3e2bc20deed0ae0fe66` |
| `mods-CRPT-119hrpt494.xml` | [`packages/CRPT-119hrpt494/mods`](https://api.govinfo.gov/packages/CRPT-119hrpt494/mods), keyed with `X-Api-Key` | 20,579 | `8ba1ed0f6e11569f78130f71a6390abd34f424ccac3bb684a48e14c39cd70b68` |
| `body-CRPT-119hrpt494-pt2.htm` | [Part 2's HTML rendition](https://www.govinfo.gov/content/pkg/CRPT-119hrpt494/html/CRPT-119hrpt494-pt2.htm), keyless | 1,490 | `c988d374420e3dd010d4980118d94404d99e4dbed423f936d98ef29aaf97717c` |

The `CRPT-119hrpt811` summary came from the rollup's own requalification
capture; its MODS, `CRPT-112hrpt38`'s and `CRPT-119hrpt455`'s came from a probe
of 21 bounded GETs. The `CRPT-119hrpt494` summary and MODS are the rollup's
captures of 2026-09-22 (`fork-execution-2026-09-21/report-family/acquisition/raw/`),
byte-identical to its 2026-09-23 captures and to a live `acquire_parts` run the
same afternoon, which also served the `CRPT-119hrpt455` summary and the
`CRPT-119hrpt494` Part 2 body (8 GETs; `receipts/multipart-reports-2026-09-23/parts/`).
The receipts are under the supply corpus:
`receipts/multipart-reports-2026-09-23/` (`ledger.jsonl`, `raw/`, `parts/`) and
`fork-execution-2026-09-21/reports-requalification-2026-09-23/`. The same probe
measured the other routes:

- `packages/CRPT-119hrpt811/granules` lists one granule, `CRPT-119hrpt811-pt1`,
  class `FIRSTPART`. Its granule summary states `packageId` `CRPT-119hrpt811`.
- `content/pkg/CRPT-119hrpt811/pdf/CRPT-119hrpt811.pdf` (the package stem)
  answers `302` to `/error`. `html/CRPT-119hrpt811-pt1.htm` (the part's stem)
  answers `200` `text/html`, 215,968 bytes.
- The granule MODS route for `CRPT-119hrpt811-pt1` returns the package's record
  again, identical element for element. So does the route for
  `CRPT-119hrpt455-pt1`. Neither states a host.
- `CRPT-119hrpt468`, `-483`, `-577`, `-621`, `CRPT-112hrpt141` and
  `CRPT-112hrpt11` are shaped like `CRPT-119hrpt811`. `CRPT-119hrpt620` and
  `CRPT-108hrpt24` are shaped like `CRPT-119hrpt455`. The package stem of
  `CRPT-119hrpt455` also redirects.
- `collections/CRPT` walks of the 116th and 113th Congress House reports listed
  722 and 734 package ids, and none carried a `-pt` suffix.

## Granule bodies for the daily Record (B2)

`CREC-2026-09-18` is a three-page issue (the day this fixture set was
captured) with 11 granules, walked through the keyed
`packages/CREC-2026-09-18/granules` route. `CREC-2026-09-18-pt1-PgS4837-4`
("APPOINTMENT OF ACTING PRESIDENT PRO TEMPORE") was chosen as the smallest.

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `granule-summary-CREC-2026-09-18-pt1-PgS4837-4.json` | [`packages/CREC-2026-09-18/granules/CREC-2026-09-18-pt1-PgS4837-4/summary`](https://api.govinfo.gov/packages/CREC-2026-09-18/granules/CREC-2026-09-18-pt1-PgS4837-4/summary), keyed with `X-Api-Key` | 1,448 | `6fffa582c4382db83fffdb8134ba1440ab28a68a67713e884beafe833ce69b7b` |
| `granule-mods-CREC-2026-09-18-pt1-PgS4837-4.xml` | [`packages/CREC-2026-09-18/granules/CREC-2026-09-18-pt1-PgS4837-4/mods`](https://api.govinfo.gov/packages/CREC-2026-09-18/granules/CREC-2026-09-18-pt1-PgS4837-4/mods), keyed with `X-Api-Key` | 6,658 | `2e436a5449935b90e7bd6076b659c94d6c69f5cb09d885260729454afbe3459a` |
| `granule-body-CREC-2026-09-18-pt1-PgS4837-4.htm` | [HTML rendition](https://www.govinfo.gov/content/pkg/CREC-2026-09-18/html/CREC-2026-09-18-pt1-PgS4837-4.htm), keyless | 1,333 | `e52adaf8783f047024f762eff21cf33f626efb018a29c8ac56b08d3d7ae82c31` |

The measured shape: the granule summary states both `packageId` and
`granuleId` directly, so membership is a field check, not a second route. The
granule MODS states its own `accessId` the same way a package MODS states its
own (a direct-child `extension`), and states its host package's `accessId`
nested inside a `relatedItem type="host"` -- GovInfo's own proof of
membership. Its own `location` (also a direct child, not nested) states HTML
and PDF renditions, both raw-object, both addressed at
`content/pkg/{packageId}/{folder}/{granuleId}.{extension}` -- the package's
folder, the granule's own file stem.

**A granule that does not belong to the requested package answers HTTP 400,
not 404.** Measured 2026-09-19, two ways: a wrong-day granule id
(`CREC-2026-09-17-pt1-PgS4800`, not a real id) requested under
`CREC-2026-09-18`, and this fixture's own real granule id requested under
`CREC-2026-09-17` (a real, different day) instead of its actual package. Both
answered `400 {"message":"invalid granuleId"}`, no `packageId` or `granuleId`
field at all -- unlike a missing *package*, which answers 404 on `/summary`.
`GovInfoBodyAcquirer.acquire_granule` reads this the same way it reads a
package's own 404/410: `_unavailable`, typed `GovInfoPackageUnavailableError`.
That response body is small and carries no credential, so
`tests/test_govinfo_granule_body_acquisition.py` inlines it rather than
keeping a fourth fixture file for 32 bytes.

`body-CRPT-119hrpt105.htm` is the one package this repository holds in **two**
renditions: its PyMuPDF page text is `tests/fixtures/gpo_pdf_text/CRPT-119hrpt105.json`
and its complete PDF-derived text is `tests/fixtures/agency_reports/crpt-119hrpt105.txt`,
both from the identical PDF (`sourcePdfSha256`
`0b8f5c52ce09396f40c400ed23d2d52ec8cb638e5b2227d5592656557fce9911`). That is
what makes the rendition comparison in `tests/test_body_text.py` a comparison
of one document rather than of two.

## The one measured `txt` rendition

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `body-CDIR-2026-02-20.excerpt.txt` | first 5,981 bytes (cut at a CRLF boundary) of the [text rendition](https://www.govinfo.gov/content/pkg/CDIR-2026-02-20/text/CDIR-2026-02-20.txt), keyless | 5,981 | `fbd6e70a40d657f214ad697b9f325d4d16eaae4a0935dbaffd9d5f440cf76b76` |

This one *is* an excerpt, and it is here because it is the only `txt` rendition
in reach: of the six collections measured, **only CDIR offers one**, and its
full response is 1,155,810 bytes (`7757cde4dc6cde3e7dc697bd12d841f6d9a159050769105b650e03f8c777d3e5`,
27,717 CRLF pairs), well past what belongs in this repository. The excerpt
carries 111 of those CRLF pairs and 52 trailing-space lines, which is enough
to measure both rules the `txt` branch of `extraction/body_text.py` applies.
Re-derive the whole file from the URL above; nothing here depends on more of it.

**There is no `txt` rendition for a committee report.** Measured 2026-09-19
through `GovInfoBodyAcquirer`: `CRPT-119hrpt1`, `CRPT-119hrpt105` and
`CRPT-113srpt77` each state `htm, pdf` and nothing else, and
`acquire(..., prefer=("txt",))` refuses with `GovInfoFormatNotOfferedError`
before any body request. `text/{id}.txt` and `xml/{id}.xml` for those packages
answer `200` from `https://www.govinfo.gov/error` with the 44,165-byte "Page
Not Found" page. So a committee report's text-bearing rendition is its `htm`,
which is GPO's plain text inside `<html><title>…</title><body><pre>`.

## What each text-bearing rendition carries

Counted on the bytes as the publisher served them (`tests/test_body_text.py`
asserts the per-rendition numbers `extraction/body_text.py` derives from them):

| Artifact | `htm` (4 CRPT bodies) | `txt` (CDIR) | `xml` (3 BILLS bodies) | PDF page text |
| --- | --- | --- | --- | --- |
| CRLF line endings | 0 | 27,717 | 0 | 0 |
| `\x1a` end-of-text marker | 0, 0, 1, 1 | 0 | 0 | 0 |
| ` `` `/`''` GPO quote pairs | 6, 2, 54, 119 | 0 | 0 | 0 |
| Curly quotes | 0 | 0 | 0, 2, 0 | 8, 99, 242 |
| Trailing-space lines | 96, 53, 6,259, 6,344 | 19,077 | 0, 11, 0 | — |
| `<title>` wrapper | 4 of 4 | — | — | — |
| `<all>` / `<graphic(s)>` locator markers | 0, 0, 10, 1 | — | — | — |
| `[[Page N]]` markers | 0 | 0 | 0 | 0 |
| Form feeds | 0 | 0 | 0 | 0 |
| `VerDate` print footers | 0 | 0 | 0 | 229 on CRPT-113hrpt135 |

The four `htm` bodies are CRPT-119hrpt1, -119hrpt105, -113hrpt135 and
-113srpt77 (in that column order); the three `xml` bodies are the BILLS
fixtures under `tests/fixtures/govinfo_bills/`. The last four rows are why
`body_text` writes no rule for page markers, form feeds or `VerDate` footers
outside the PDF branch: nothing measured carries one.

## What the same run measured elsewhere

Routes were probed with GET and an early stream abort, because a publisher can
refuse HEAD while serving GET. "Offered" is the set of `location/url` elements
with `access="raw object"` in the package MODS.

| Package | MODS says offered | Keyless routes answering 200 | Summary `download` body links |
| --- | --- | --- | --- |
| `CRPT-119hrpt1` | HTML, PDF | `html/…htm`, `pdf/…pdf` | none |
| `CHRG-119hhrg64242` | HTML, PDF | `html/…htm`, `pdf/…pdf` (46.6 MB) | none |
| `CDOC-119tdoc2` | HTML, PDF | `html/…htm`, `pdf/…pdf` | none |
| `CREC-2026-01-02` | PDF | `pdf/…pdf` | `pdfLink` plus house, senate and daily-digest PDFs |
| `CDIR-2026-02-20` | PDF, Text | `pdf/…pdf` (18.3 MB), `text/…txt` | `txtLink` (pointing at `/txt`), `pdfLink` |
| `BILLS-119hr1enr` | HTML, PDF, XML, USLM | `html/…htm`, `xml/…xml`, `pdf/…pdf` | `xmlLink`, `txtLink` (pointing at `/htm`), `xhtmlLink`, `uslmLink`, `pdfLink` |

Every format the MODS did not state answered `302` to `https://www.govinfo.gov/error`,
which answers `200` with a 44,165-byte "Page Not Found" page; every format it
did state answered `200`. A missing package answers `404` on `/summary`, `400`
on `/mods`, and `302` on the body routes.

Package-id shapes came from `published` walks on 2026-09-19: 3,000 CREC ids
(2,968 plain, 16 `-v{n}`, 16 `-i{n}`), 3,000 CRPT (`hrpt` 2,234, `srpt` 751,
`erpt` 12), 3,000 CHRG (`hhrg` 1,728, `shrg` 1,203, `jhrg` 69), 1,681 CDOC
(`hdoc` 1,409, `sdoc` 142, `tdoc` 51) and all 27 CDIR ids (`CDIR-YYYY-MM-DD`).

A collection-scoped walk also returns ids from neighboring collections: 79 of
the CDOC-scoped ids and 3 of the CRPT-scoped ones are `ERP-…` or `GPO-…`
packages, and their own `collectionCode` says so (`ERP-2009` states `ERP`,
`GPO-J6-REPORT` and `GPO-CRPT-116hrpt562` state `GPO`). They are real packages
with different addresses, and this module refuses them by name.

## The rendition comparison that ordered `BODY_PREFERENCE`

`sources/govinfo/bodies.py::BODY_PREFERENCE` puts PDF last on a measurement no
fixture here is large enough to hold. It ran on 2026-09-19 over two
appropriations reports in both renditions, fetched keyless through
`GovInfoBodyAcquirer`:

| Package | `htm` bytes | `htm` SHA-256 | PDF bytes | PDF SHA-256 |
| --- | ---: | --- | ---: | --- |
| `CRPT-113srpt77` | 677,525 | `60b0d418ca8b80b3db3e27b294d652dcf72e81eba9de2343434a24c15b56c120` | 531,055 | `d533775b53de0ba1fd4d35d9d4345727a87979aa578d18db778e917be4b7f76a` |
| `CRPT-113hrpt135` | 488,738 | `4c0e2ec9b38d02a9546ed88aa78005ed302b263332935ee95551816b6d107301` | 3,233,438 | `cb6a9d0aa131f60be5c1635cd044ff06dcdb1a7da0db9789c3bd1e3bdd087af7` |

Both PDF digests equal the `sourcePdfSha256` already recorded in
`tests/fixtures/agency_reports/sources.json`, so the PDFs measured are
byte-identical to the ones those text fixtures were extracted from — an
independent re-fetch agreeing with a prior run, not a restatement of it. The
four bodies themselves are session receipts and are not kept here; the numbers
they produced are in `docs/sources/govinfo-bodies.md`, "Why PDF is last".

Full probe output and the capture scripts are session receipts; they are not
kept in this repository. Re-derive them with the routes named above.

## The Senate Secretary reprint, for the widened grammar (2026-09-20)

`GPO-CDOC-119sdoc3` is the second id shape
`sources/govinfo/bodies.py`'s package-id grammar was widened to
([decision record](../../../docs/decisions.md#budget-and-the-gpo-prefixed-cdoc-reprints-join-the-package-id-grammar)).
Records only, no body: the Senate Secretary's expenditure tables are another
contract's subject and this pair is here to exercise the grammar and the two
sealed validators.

| Fixture | What it is | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `summary-GPO-CDOC-119sdoc3.json` | verbatim: `api.govinfo.gov/packages/GPO-CDOC-119sdoc3/summary`, one keyed request 2026-09-20, receipt `corpora/supply-2026-09-02/receipts/budget-volumes-2026-09-20/` | 2,677 | `0361cfeb5274685036089948422c6088b62cb2bc2dae3823efa814e60c226d9d` |
| `mods-GPO-CDOC-119sdoc3.xml` | **reduced** (everything before the first `<relatedItem>`, then `</mods>`; 9 constituent records dropped): `api.govinfo.gov/packages/GPO-CDOC-119sdoc3/mods`, 15,797 bytes, `sha256:31e229e8fbba75cddeb0d90c89c7c3f6509131c49495f215f65f50b6842d92fb`, retained by the MODS re-check | 4,809 | `8aba15aaf7ac5ec1cd5cb81328d73c436adf6f830081e8a2a972b2cea2eab9be` |

Both records state `collectionCode` **`GPO`**, which is neither the package-id
prefix nor a collection this module addresses on its own — the same code
`GPO-J6-REPORT` states, which is still refused because the registered
collection is the whole `GPO-CDOC` prefix. That pair of facts is what the
grammar's `collection_code` field exists for, and why the check compares
against the code a collection's records state rather than against its prefix.
The budget volume this widening was built for keeps its own records beside its
text in `tests/fixtures/budget_volumes/`.
