# Capture Supreme Court slip opinions

Give SpicyDocs a term year such as `2025`. It returns the exact
supremecourt.gov term index for that term, proves from the page itself that it
is the term you asked for, and lists every row the page states. Then hand that
retained index back, with one of the PDF links it stated, to capture the
document. No key is required, and the site served a plain non-browser client on
2026-09-14.

| Selection | What it supplies |
| --- | --- |
| A term year, 2000 to 2099 | One `/opinions/slipopinion/{code}` render: the page's `Term Year` label and one row per listed opinion -- release number, decision date, docket number, case name, holding, authoring Justice, citation, and the PDF link if the row states one. |
| A retained index and one URL it stated | The exact PDF bytes, with the file's own `%PDF-` version and the length its linearization dictionary states. |

The term code is the year's last two digits: `2025` is `/25`. That is the
publisher's own rule, not an inference -- the OT2025 index links `24` to 2024,
`23` to 2023 and so on, and states `Term Year: 2025` for `/25`.

```python
from spicy_docs.sources.supreme_court import SupremeCourtAcquirer, SupremeCourtBudget

budget = SupremeCourtBudget(
    max_requests=4,
    max_index_bytes=4 * 1024**2,
    max_document_bytes=16 * 1024**2,
    timeout_seconds=60,
    min_request_interval_seconds=2,
)
with SupremeCourtAcquirer(budget=budget) as source:
    term = source.acquire_term_index(2025)
    opinion = term.index.opinions[0]
    document = source.acquire_document(term.index, opinion.pdf_url)

print(term.index.stated_term, len(term.index.opinions), term.capture.sha256)
pdf_bytes = document.capture.body  # retain in caller-owned storage
```

## Read the result correctly

- **An index capture is one render, not the term.** Two captures of
  `/opinions/slipopinion/25` 2.5 minutes apart on 2026-09-14 disagreed about 24
  of 72 rows' links, while both were CDN hits stating the same `Last-Modified`.
  Neither header nor byte length distinguishes the renders. Keep the bytes; do
  not treat a later capture as confirmation of an earlier one.
- **A PDF link is only what a retained index stated.** `acquire_document`
  refuses a URL the index it was handed does not state, before any request.
  Four filename families occur (`26a274_l537.pdf`, `608us1r36_n758.pdf`,
  `25-365_new_5if6.pdf`, `23-1197diff2_j4ek.pdf`), so a URL can never be built
  from a docket number. The trailing token identifies a revision: two tokens on
  one base name both served, with different lengths and digests.
- **A row can state no opinion link.** Ten of 72 OT2025 rows did on the first
  capture; `pdf_url` and `pdf_kind` are then absent and the row is still the
  publisher's statement of a decided case. A row can also carry `Revisions:`
  links; they are kept in `revisions` and are never read as the opinion.
- **An older term links into a volume.** OT2020 pointed 15 of 68 rows into one
  `/opinions/preliminaryprint/` PDF with a `#page=N` fragment. The fragment is
  where in the volume the opinion begins, so it is reported as `page_start` and
  the resource fetched is the volume. The opinion's end page is not inferred
  here; that is interpretation and belongs downstream.
- `holding` is the anchor's `title` and is absent when the publisher states it
  empty, as OT2025's decree row does.

## What is refused

A 200 that is not this term's index is refused with its bytes retained. Three
independent statements must agree: the page's own `Term Year: {year}` label,
the `/opinions/{code}pdf/` directory every slip link sits in, and a decision
date inside the term's window (its September through the end of the following
calendar year). Parsed against every other term retained on 2026-09-14, all 12
wrong-term pairings were refused.

A document must be `application/pdf`, must begin `%PDF-`, must end in a
trailer, and -- when it is linearized, as every opinion captured was -- must be
exactly the length its `/L` states. The length comes from the file being
checked, so it catches a truncated capture, not a substituted one. The trailer
check alone cannot catch truncation here: a linearized PDF carries an early
`%%EOF` inside its first kilobyte.

`min_request_interval_seconds=2` is what the salvaged SpicyRegs fetcher settled
on after the site answered `403 Access Denied` to everything from one address
following roughly 80 requests in 25 minutes (2026-08-22). Eleven requests 1.6 s
apart on 2026-09-14 were all served, which establishes nothing about that
threshold. The acquirer keeps one HTTP client, and it does not clear the site's
session cookie between operations -- the condition under which the wrong term
was once served. The term assertion is what defends against it.

## Evidence

The reduced fixtures, the full page and PDF hashes, and the five OT2025 row
shapes are in
[`tests/fixtures/supreme_court/README.md`](../../tests/fixtures/supreme_court/README.md).
Complete pages and PDFs, response headers, the render-drift and revision-token
experiments, and the term-code confirmation are in
`corpora/supply-2026-09-02/receipts/port-P02-supreme-court-2026-09-14/`.
