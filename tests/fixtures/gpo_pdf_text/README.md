# GPO PDF text fixtures

Extracted text (not the PDF) of three real GPO legislative documents, captured
to re-derive `extraction/gpo_normalize.py` against this repo's own PDF
extraction instead of BillTrax's pdf-parse. Each file is a JSON array of
per-page strings: `extraction.DocumentExtractor(extraction.NativeText())`'s
`PageResult.text`, one entry per page, in reading order. No page's text is
truncated or reformatted.

Package identity, PDF byte size and PDF sha256 for two of the three come
straight from `docs/research/billtrax-raw-data-2026-09-19.json`
(`sources.billPdfTextArtifacts`), which recorded them from the same keyless
GovInfo URLs on 2026-09-19; refetching each reproduced the identical byte
size and sha256 stated there. The committee report was not itself captured in
that sidecar (only its line-count statistics were, under
`sources.committeeReportTextArtifacts["CRPT-119hrpt105"]`); its PDF was
fetched keyless from the address `spicy_docs.sources.govinfo.bodies.
package_body_locator("CRPT-119hrpt105", "pdf")` derives, the same GovInfo
package-body address family `docs/sources/govinfo-bodies.md` documents and
`docs/research/billtrax-raw-data-2026-09-19.md` §6 used for this exact
package. All three PDFs are public-domain U.S. government documents, under
the 24 MiB evidence bound documented in that same section, and well under it.

| Fixture | Version | Publisher URL | PDF bytes | PDF sha256 | Pages | Extracted chars |
| --- | --- | --- | ---: | --- | ---: | ---: |
| `BILLS-119hr4727ih.json` | Introduced in House (IH) | <https://www.govinfo.gov/content/pkg/BILLS-119hr4727ih/pdf/BILLS-119hr4727ih.pdf> | 223,439 | `3f3620d2c4f597a0a04a930e79977f5fec6a37a3ecc9e0765c40aa994a209a3d` | 1 | 854 |
| `BILLS-119sconres1enr.json` | Enrolled (ENR) | <https://www.govinfo.gov/content/pkg/BILLS-119sconres1enr/pdf/BILLS-119sconres1enr.pdf> | 196,785 | `bed258a4cdbf876b099d49554cadfe3a641c9d785e61662f4076bf74ba635924` | 1 | 1,291 |
| `CRPT-119hrpt105.json` | Committee report (House Rules) | <https://www.govinfo.gov/content/pkg/CRPT-119hrpt105/pdf/CRPT-119hrpt105.pdf> | 199,803 | `0b8f5c52ce09396f40c400ed23d2d52ec8cb638e5b2227d5592656557fce9911` | 3 | 7,111 |

Extracted 2026-09-19 with PyMuPDF 1.28.2 via
`extraction.DocumentExtractor(extraction.NativeText()).extract(source,
media_type="application/pdf")`, one `PageResult.text` per page, joined into
this file as a JSON list. No normalization has been applied to these files;
`tests/extraction/test_gpo_normalize.py` normalizes them at test time and
asserts the measured `GpoCleanupRecord` counts (`docs/extraction-gpo.md` has
the same table with the after-normalization reduction).

These fixtures establish behavior for these three documents' shapes; they do
not establish coverage of every GPO PDF layout GovInfo has ever produced.
