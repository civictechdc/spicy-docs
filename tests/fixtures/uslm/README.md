# GovInfo USLM fixtures

Complete, unchanged publisher files from the keyless GovInfo bulkdata zips
pinned on 2026-09-14, unless the table states another capture. These U.S. government documents are public domain.
Offline tests establish behavior for these shapes; they do not establish
coverage or continuing live availability.

| Fixture | Publisher object | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `plaw-119publ1.xml` | `PLAW-119publ1.xml` inside [`PLAW-119-public.zip`](https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119-public.zip), publisher Last-Modified 2026-09-09 15:30:21 GMT | 23,379 | `ee0e7a5d534411f78dd325405c42d386a1cfcf14f3870c93f5488874bb7acb54` |
| `plaw-119pvtl1.xml` | [`PLAW-119pvtl1.xml`](https://www.govinfo.gov/bulkdata/PLAW/119/private/PLAW-119pvtl1.xml), captured 2026-09-24 and retained in `corpora/fork-execution-2026-09-21/rollup-success-log-audit-2026-09-24/private-law-check/`; a private law, whose meta states no Statutes at Large citation | 4,597 | `501bd73c995747f6f7d849d2b1cb2e4a80136da1b093b098982e43627ec7cfb1` |
| `plaw-119pvtl2.xml` | [`PLAW-119pvtl2.xml`](https://www.govinfo.gov/bulkdata/PLAW/119/private/PLAW-119pvtl2.xml), captured 2026-09-24 and retained in `corpora/fork-execution-2026-09-21/rollup-success-log-audit-2026-09-24/private-law-check/`; a private law, whose meta states no Statutes at Large citation | 5,391 | `45a3807cb2da2331952582fbf63e90e200fd155a215992ec9275b48db43f3dbf` |
| `comps-10542.xml` | `COMPS-10542.xml` inside [`COMPS.zip`](https://www.govinfo.gov/bulkdata/COMPS/COMPS.zip), publisher Last-Modified 2026-09-11 12:19:04 GMT | 33,745 | `d26f3f8266e613158309e807f6503ce51c78e2afc3989638f730f41eb1204602` |

The zips themselves are 3,221,106 bytes, SHA-256
`5694c34db729f07246208a8226abb8744dd79a509e8ee8068282681f1d03cfbf`, and
85,064,598 bytes, SHA-256
`cd831e267c1719fb5001a14e37a144e28a177126d01de36a891a36c2bb4e42c7`. Both zips,
every folder listing, both-direction listing checks and the pin script are in
`corpora/supply-2026-09-02/receipts/comps-plaw-pin-2026-09-14/`.

Observed shapes across every pinned file (2,155 laws, 2,681 compilations):
every root is in `http://schemas.gpo.gov/xml/uslm` (`pLaw` or
`statuteCompilation`) with one `meta` block; `citableAs` and `dc:creator`
repeat within a file; `currentThroughPublicLaw` is absent in 75 compilations
and repeated in 3; one compilation (`COMPS-3101`) has an empty `main` and
points to the U.S. Code from its preface; the largest file is the Social
Security Act at 20,419,115 bytes under the placeholder identifier
`COMPS-88888888`. The publisher's readme calls the XML schema beta and points
to the `proposed` branch of `usgpo/uslm`.
