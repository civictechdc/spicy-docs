# CRS report file fixtures

Captured 2026-09-14 from the keyless congress.gov route
`https://www.congress.gov/crs_external_products/{family}/PDF/{id}/{id}.{version}.pdf`
with a `spicy-docs-crs-files/1.0` user agent and no credential. Congressional
Research Service reports are U.S. government works in the public domain.
Offline tests establish behavior for this shape; they do not establish coverage
or continuing live availability.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `IF11830.5.prefix.pdf` | [.../IF/PDF/IF11830/IF11830.5.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF11830/IF11830.5.pdf) | 2,048 | `c01d719ff762b076ee12177b278fdb9b87740d1a8deed6b67e0029a8d2a4c0fa` | **First 2,048 bytes only**, so an incomplete capture is what this file is. Complete response 406,818 bytes, SHA-256 `452298978fa1b75a96373219f76403cc0b9362e52ef75c6725bdb2d3e006822c`, `content-type: application/pdf`, no redirect. |

The prefix keeps the parts a reader checks: the `%PDF-1.7` magic and the
signature's `/ByteRange [0 142 244094 162724]`, whose last two numbers sum to
406,818 — the complete file's length. So the fixture is both a real header to
read and a real truncated capture to refuse.

Two captures of this locator three weeks apart are byte-identical: the copy
cached 2026-08-22 in
`corpora/_preserved-2026-08-27/spicy-regs-output-complete/segmentation-source-cache-v2/crs-pdf-short.pdf`
has the same SHA-256 as the 2026-09-14 fetch. A pinned `(id, version)` is
stable; it is not a claim that the publisher keeps it forever.

Complete PDFs, response headers, the 404 answers for a missing id, a missing
version and a wrong family, and the family measurements over 13,970
publisher-stated URLs are in
`corpora/supply-2026-09-02/receipts/port-P03-crs-files-2026-09-14/`.
