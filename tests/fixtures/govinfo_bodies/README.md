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

No fixture was reduced or reformatted. The credential travels only in the
request header, and the capture script refused to write any file whose bytes
contained the key or an `api_key=` parameter; none did. The keyless body route
takes no credential at all.

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

Full probe output and the capture scripts are session receipts; they are not
kept in this repository. Re-derive them with the routes named above.
