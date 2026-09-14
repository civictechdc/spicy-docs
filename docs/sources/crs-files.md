# Capture a CRS report file

Give SpicyDocs one CRS report id, one version and the family segment the
publisher files it under. It returns the exact PDF congress.gov served, the
identity it proved and bounded HTTP evidence. The route is keyless: the
api.data.gov key names and describes reports, but the file itself needs no
credential.

| Step | Route | Credential |
| --- | --- | --- |
| Name the reports | `api.congress.gov/v3/crsreport` ([list pages](listings.md)), rows with `id`, `version`, `contentType` | api.data.gov key |
| Read one report's metadata | `api.congress.gov/v3/crsreport/{id}`, whose `formats` states the PDF URL | api.data.gov key |
| **Capture the file** | `www.congress.gov/crs_external_products/{family}/PDF/{id}/{id}.{version}.pdf` | **none** |

`crs_summaries.py` fetches the middle step and says PDFs are fetched
separately. This is that fetch.

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
    crs_file_locator,
    crs_file_selection,
)

# From the report's stated PDF URL (exact):
selection = crs_file_selection("https://www.congress.gov/crs_external_products/RA/PDF/RL31312/RL31312.6.pdf")

# From a list row's id and version, with the family inferred (fails as a 404 when wrong):
selection = CrsFileSelection("LSB", "LSB11481", 1)
print(crs_file_locator(selection))

budget = CrsFileBudget(max_requests=2, max_bytes=8 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.5)
with CrsFileAcquirer(budget=budget) as source:
    result = source.acquire_report_pdf(selection)

print(result.file.pdf_version, result.file.byte_size, result.capture.sha256)
pdf = result.capture.body  # retain these exact bytes in caller-owned storage
```

Offline, `read_crs_pdf(body, selection, final_url=..., max_bytes=...)` applies
the same checks to retained bytes. Install the `acquisition` extra for the
acquirer; selection, locator and reader need only the core package.

## Read the result correctly

- **A version selects a file, not the current state.** Superseded versions stay
  available: `IF11830.4.pdf` and `IF11830.5.pdf` both served, with different
  bytes. The version need not be the one the CRS list states today. A version
  the publisher never issued is a 404.
- **A 404 is about the locator, not the report.** A missing id, a missing
  version, a wrong family and a lowercase family all return the same 341,423-byte
  Congress.gov HTML error page with status 404, raising
  `CrsFileUnavailableError` with the capture attached. It never establishes that
  a report has no PDF.
- **GET only.** `HEAD` on the same URL answered 403. Under the shared client a
  403 aborts the acquisition as a credential refusal, so never probe with `HEAD`.
- **Identity is the request plus the shape.** A CRS PDF names no report inside
  its bytes. The capture must be `application/pdf`, must begin `%PDF-`, and its
  final URL must equal the locator; the shared client follows no redirect. A 200
  that is not a PDF is refused with its bytes retained.
- **Completeness is checked twice.** Every CRS PDF ends `%%EOF`, and each is
  digitally signed with a `/ByteRange` in its first 4 KiB whose last two numbers
  sum to the whole file's length; where that appears it must equal the bytes
  captured. Both statements come from the file, so they prove the capture is
  whole, not that it is authentic. `signed_byte_range_total` is reported as the
  publisher stated it.
- **No credential belongs on this route.** The acquirer sends none, and a key in
  a locator would be evidence of a mistake.

## Evidence

The pinned header and hashes are in
[`tests/fixtures/crs_files/README.md`](../../tests/fixtures/crs_files/README.md).
Complete PDFs from five families, response headers, the 404 answers, the `HEAD`
refusal and the family and id measurements over the retained stated URLs are in
`corpora/supply-2026-09-02/receipts/port-P03-crs-files-2026-09-14/`. Two
captures of `IF11830.5.pdf` three weeks apart are byte-identical, which pins the
route but does not promise the publisher keeps any version forever.
