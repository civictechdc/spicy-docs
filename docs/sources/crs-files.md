# Capture a CRS report file

Give SpicyDocs one CRS report id, one version and the family segment the
publisher files it under. It returns the exact rendition congress.gov served,
the identity it proved and bounded HTTP evidence. Both routes are keyless: the
api.data.gov key names and describes reports, but the file itself needs no
credential.

| Step | Route | Credential |
| --- | --- | --- |
| Name the reports | `api.congress.gov/v3/crsreport` ([list pages](listings.md)), rows with `id`, `version`, `contentType` | api.data.gov key |
| Read one report's metadata | `api.congress.gov/v3/crsreport/{id}`, whose `formats` states the PDF and HTML URLs | api.data.gov key |
| **Capture the file — HTML, preferred** | `www.congress.gov/crs_external_products/{family}/HTML/{id}.html` | **none** |
| **Capture the file — PDF, the fallback** | `www.congress.gov/crs_external_products/{family}/PDF/{id}/{id}.{version}.pdf` | **none** |

`crs_summaries.py` fetches the middle step and says the file is fetched
separately. This is that fetch. `acquire_report` tries HTML first and falls
back to PDF on any refusal; use `acquire_report_pdf` alone for a specific,
possibly superseded version, which HTML cannot express (below).

## Take the family from the publisher, not from the id

The family is a path segment, not a property of the id, and it is
case-sensitive (`if` answered 404 where `IF` served). Over the 13,970
publisher-stated PDF URLs retained on 2026-09-07 it equals the id's prefix for
all but two groups: 80 `RL` reports are filed under **`RA`**, and 224 legacy
ids such as `98-807` have no alphabetic prefix at all. Live on 2026-09-14,
`RA/PDF/RL31312/RL31312.6.pdf` served 200 while the inferred
`RL/PDF/RL31312/RL31312.6.pdf` answered 404.

So prefer `crs_file_selection(stated_url)`, which reads the publisher's own
`formats[].url`. `family_from_report_id` is the inference for when that URL is
not at hand; it refuses legacy ids outright, and where it is wrong the route
answers 404 rather than another report's bytes.

```python
from spicy_docs.sources.congress.crs_files import (
    CrsFileAcquirer,
    CrsFileBudget,
    CrsFileSelection,
    CrsHtmlAcquisition,
    crs_file_locator,
    crs_file_selection,
    crs_html_selection,
)

# From the report's stated URLs (exact), both taken from the same formats[] response:
pdf_selection = crs_file_selection("https://www.congress.gov/crs_external_products/RA/PDF/RL31312/RL31312.6.pdf")
html_selection = crs_html_selection("https://www.congress.gov/crs_external_products/RA/HTML/RL31312.html")

# From a list row's id and version, with the family inferred (fails as a 404 when wrong):
pdf_selection = CrsFileSelection("LSB", "LSB11481", 1)
print(crs_file_locator(pdf_selection))

# max_requests covers HTML and, only on a refusal, the PDF fallback under one budget.
budget = CrsFileBudget(max_requests=2, max_bytes=8 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.5)
with CrsFileAcquirer(budget=budget) as source:
    result = source.acquire_report(pdf_selection, html_selection=html_selection)

body = result.capture.body  # retain these exact bytes in caller-owned storage
if isinstance(result, CrsHtmlAcquisition):
    print("html", result.html.byte_size, result.capture.sha256)
else:
    print("pdf", result.file.pdf_version, result.file.byte_size, result.capture.sha256)
```

Offline, `read_crs_html(body, selection, final_url=..., max_bytes=...)` and
`read_crs_pdf(body, selection, final_url=..., max_bytes=...)` apply the same
checks to retained bytes. Install the `acquisition` extra for the acquirer;
selection, locator and reader need only the core package.

## Read the result correctly

- **HTML is preferred but not reliable; a refusal falls back, it never raises
  by itself.** Measured 2026-09-19 across two reports and three keyless header
  variants each (bounded to eight requests total, table below), the same
  report answered 200 to one header combination and 403 (a bot-wall page) to
  another. `acquire_report` therefore tries HTML once and, on any refusal —
  the bot wall, a wrong media type, a missing identity marker — falls back to
  the versioned PDF route under the same request budget. Call
  `acquire_report_html` directly only when a refusal should propagate instead.
- **HTML has no version; it is always the current file.** The route carries no
  version segment (`.../{family}/HTML/{id}.html`, unlike the PDF's
  `.../{id}.{version}.pdf`), and the bytes state none either. `html_selection`
  should always come from the same `formats[]` response as the paired
  `pdf_selection` — for a caller-pinned historical version, omit
  `html_selection` (or call `acquire_report_pdf` directly) so a superseded
  request is never silently answered with today's HTML.
- **A version selects a PDF file, not the current state.** Superseded versions
  stay available: `IF11830.4.pdf` and `IF11830.5.pdf` both served, with
  different bytes. The version need not be the one the CRS list states today.
  A version the publisher never issued is a 404.
- **A 404 is about the locator, not the report.** A missing id, a missing
  version, a wrong family and a lowercase family all return the same 341,423-byte
  Congress.gov HTML error page with status 404, raising
  `CrsFileUnavailableError` with the capture attached. It never establishes that
  a report has no PDF.
- **GET only.** `HEAD` on the PDF URL answered 403. Under the shared client a
  403 aborts that request as a credential refusal, so never probe with `HEAD`.
- **Identity is the request plus the shape.** A CRS PDF names no report inside
  its bytes: identity is `application/pdf`, the `%PDF-` magic, and a final URL
  equal to the locator. A CRS HTML page does name its report, twice
  independently — the cover line's parenthesized id and a `data-prod-type`
  attribute stating the family — checked alongside the same final-URL equality.
  Either way the shared client follows no redirect, and a 200 that is not the
  expected shape is refused with its bytes retained.
- **PDF completeness is checked twice.** Every CRS PDF ends `%%EOF`, and each is
  digitally signed with a `/ByteRange` in its first 4 KiB whose last two numbers
  sum to the whole file's length; where that appears it must equal the bytes
  captured. Both statements come from the file, so they prove the capture is
  whole, not that it is authentic. `signed_byte_range_total` is reported as the
  publisher stated it.
- **No credential belongs on either route.** The acquirer sends none, and a key
  in a locator would be evidence of a mistake.

## Evidence

The pinned header and hashes, and the eight-request HTML measurement, are in
[`tests/fixtures/crs_files/README.md`](../../tests/fixtures/crs_files/README.md).
Complete PDFs from five families, response headers, the 404 answers, the `HEAD`
refusal and the family and id measurements over the retained stated URLs are in
`corpora/supply-2026-09-02/receipts/port-P03-crs-files-2026-09-14/`. Two
captures of `IF11830.5.pdf` three weeks apart are byte-identical, which pins the
route but does not promise the publisher keeps any version forever.
