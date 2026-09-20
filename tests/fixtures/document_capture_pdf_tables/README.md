# One retained Senate table page

`GPO-CDOC-119sdoc3-1.page17.pdf` is PDF page 17 (printed A-7) of
`GPO-CDOC-119sdoc3-1.pdf`, cut offline from the PDF-family rollup's retained
content-addressed blob. `source.json` pins the full input path, full PDF digest,
cut digest, page, package and extraction version. No request was made.

The cut contains one 3-by-9 table: 19 observed cells, including one empty
cell, and eight missing positions. Some nonempty cells have no box in the
extractor observation. Both the full PDF's page and this cut were independently
extracted with `DocumentExtractor(NativeText(), tables=True)`; page text,
table text and normalized boxes agreed exactly after allowing for the page
number changing from 17 to 1.

To reproduce the cut, use `UV_OFFLINE=1 uv run --frozen python` with PyMuPDF:
open `source.json`'s `source_path`, verify `source_sha256`, insert page index 16
into an empty document using `insert_pdf(from_page=16, to_page=16)`, and save
with `garbage=4, deflate=True`. The fixture is derived bytes and is never
represented as the original publisher PDF.

`tests/test_document_capture_pdf_tables.py` re-extracts this page and checks
cell presence, geometry, unresolved observations, exact span ownership, the
pinned parent and the Senate profile. Its explicitly synthetic cases exercise
ambiguity, overlapping claims, missing text and cross-page refusal. Mutations
of the real-page capture prove the agreement measurement can fail.
