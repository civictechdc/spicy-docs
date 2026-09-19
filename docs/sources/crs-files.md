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
separately. This is that fetch. `acquire_report` reads one `CrsReportSelection`
— built from that one `formats[]` response by `crs_report_selection` — and
tries HTML first for the version that response called current, falling back
to PDF on any refusal or for any other requested version; use
`acquire_report_pdf` directly for finer control over one specific,
possibly superseded version (below).

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
    crs_report_selection,
)

# The report's own formats[] array (from api.congress.gov/v3/crsreport/{id}), unmodified:
formats = [
    {"format": "PDF", "url": "https://www.congress.gov/crs_external_products/RA/PDF/RL31312/RL31312.6.pdf"},
    {"format": "HTML", "url": "https://www.congress.gov/crs_external_products/RA/HTML/RL31312.html"},
]
# One read of that one array: the PDF's version and the paired HTML can never
# come apart into naming different reports or different versions.
selection = crs_report_selection(formats)

# From a list row's id and version alone, with the family inferred (fails as a 404 when wrong):
pdf_selection = CrsFileSelection("LSB", "LSB11481", 1)
print(crs_file_locator(pdf_selection))

# max_requests covers HTML and, only on a refusal, the PDF fallback under one budget.
budget = CrsFileBudget(max_requests=2, max_bytes=8 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.5)
with CrsFileAcquirer(budget=budget) as source:
    result = source.acquire_report(selection)  # version defaults to selection.pdf.version, the current one

body = result.capture.body  # retain these exact bytes in caller-owned storage
if result.rendition == "html":
    print("html", result.html.byte_size, result.capture.sha256)
else:
    print("pdf", result.pdf.pdf_version, result.pdf.byte_size, result.capture.sha256)
    print("why not html:", result.html_skipped_reason or f"refused: {result.html_refusal}")
```

A caller who wants a specific, possibly superseded version passes it explicitly
— `source.acquire_report(selection, version=4)` — which is routed straight to
the PDF route without ever touching HTML, since HTML can only stand in for the
version `formats[]` called current; `result.html_skipped_reason` says why HTML
was skipped. `acquire_report_pdf(CrsFileSelection(...))` remains available
directly for the same effect without building a `CrsReportSelection` at all.

Offline, `read_crs_html(body, selection, final_url=..., max_bytes=...)` and
`read_crs_pdf(body, selection, final_url=..., max_bytes=...)` apply the same
checks to retained bytes. Install the `acquisition` extra for the acquirer;
selection, locator and reader need only the core package.

## Read the result correctly

- **HTML is preferred but not reliable; a refusal falls back, it never raises
  by itself.** Measured 2026-09-19 across two reports and three keyless header
  variants each, then a repeat of all six (report, header) pairs: it is
  genuine request-to-request flakiness, not just report-or-header variance —
  three of the six repeated pairs flipped status between passes, including
  this module's own exact headers (table below). `acquire_report` therefore
  tries HTML once and, on any refusal — the bot wall, a wrong media type, a
  missing identity marker — falls back to the versioned PDF route under the
  same request budget, keeping the refused capture on the result as
  `html_refusal`. Call `acquire_report_html` directly only when a refusal
  should propagate instead.
- **HTML has no version; it is always the current file — and `acquire_report`
  cannot be fooled into pairing it with a different one.** The route carries
  no version segment (`.../{family}/HTML/{id}.html`, unlike the PDF's
  `.../{id}.{version}.pdf`), and the bytes state none either. `crs_report_selection`
  reads both the PDF's current version and the paired HTML URL from one
  `formats[]` array, so they cannot independently drift; `acquire_report`
  compares the requested `version` against that pairing's own current
  version and only ever tries HTML when they match. A request for any other
  version — `source.acquire_report(selection, version=4)` — is routed
  straight to the PDF route, and `result.html_skipped_reason` says why. This
  is a structural guarantee, not a rule a caller has to remember: there is no
  argument combination that answers a historical request with today's HTML.
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
- **A keyless 401/403 is this family's own error, not a credential refusal.**
  `named_challenge` recasts the HTML route's 401/403 as `CrsHtmlRefusedError`
  — catchable as a `CrsFileSourceError` alongside every other refusal, its
  body retained as evidence on `refused_response` — the same pattern
  `cbo.py`, `votes.py`, `legislators.py` and `bulk_status.py` use for their
  own keyless routes. The PDF route's error handling is unchanged: `GET` has
  never yet answered 401/403 there, only `HEAD` has.
- **Identity is the request plus the shape.** A CRS PDF names no report inside
  its bytes: identity is `application/pdf`, the `%PDF-` magic, and a final URL
  equal to the locator. A CRS HTML page does name its report, twice
  independently — read through `reading/markup.py`'s parsed events, not a
  substring search over the whole page: the `class="CoverDate"` element's own
  text states the id in parentheses, and a `data-prod-type` attribute states
  the family. Scoping to that one element matters — another report's page can
  cite this id in its prose (`... see CRS Report (IF12853) ...`), and an
  unscoped search would accept that citation as the page's own identity.
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

The pinned header and hashes, and the fourteen-request HTML measurement (the
first eight plus a six-request repeat of every pair), are in
[`tests/fixtures/crs_files/README.md`](../../tests/fixtures/crs_files/README.md).
Complete PDFs from five families, response headers, the 404 answers, the `HEAD`
refusal and the family and id measurements over the retained stated URLs are in
`corpora/supply-2026-09-02/receipts/port-P03-crs-files-2026-09-14/`. Two
captures of `IF11830.5.pdf` three weeks apart are byte-identical, which pins the
route but does not promise the publisher keeps any version forever.
