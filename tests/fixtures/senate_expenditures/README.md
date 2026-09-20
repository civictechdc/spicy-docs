# Secretary of the Senate expenditure-table fixtures

Two real page ranges, not byte-range excerpts: each is cut out of a retained
volume with `document.insert_pdf(...)`, `subset_fonts()` and
`tobytes(garbage=4, deflate=True)` into its own small, openable PDF that
PyMuPDF's `find_tables()` reads exactly as it reads the full volume — the same
way `tests/fixtures/gpo_pdf_tables` was cut. These U.S. government documents
are public domain.

**Nothing here was re-fetched from the publisher.** Both cuts come from the
bytes the
[PDF-family rollup](../../../docs/research/pdf-family-rollup-yield-2026-09-20.md)
retained on 2026-09-20, content-addressed by SHA-256 in that receipt's
`blobs/`, and `build-fixtures.py` asserts — page for page, cell for cell — that
the cut's text and table cells equal the volume's before it accepts them.

Offline tests establish behavior for these two page ranges on the day they were
captured; they establish neither family coverage nor continuing live
availability.

| Fixture | What it is | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `GPO-CDOC-119sdoc3-1.pages11-17.pdf` | Pages 11–17 of 1,335 of Part I of the report for October 1, 2024 – March 31, 2025: the **whole** `SUMMARY OF TRANSACTIONS BY APPROPRIATIONS` section, printed pages A-1 to A-7, ending on the print's own `Totals` row. Seven tables, 43 ruled rows. | 87,002 | `180f1b97a60a20ba356bcfd73c81787096ad50c26567485b2b5073e4f9ed3175` |
| `GPO-CDOC-119sdoc6-2.pages11-22.pdf` | Pages 11–22 of 1,264 of Part II of the report for October 1, 2025 – March 31, 2026: a second whole summary section (A-1 to A-6, `Totals` on A-6) plus the first six pages of the detailed statement, printed pages B-1243 to B-1248. Twelve tables, 71 ruled rows. | 138,247 | `32834f1078045ef2d298cfbe664db9527d0eb39e1557fe9eb656e2ba38e1f7b6` |

`sources.json` carries each cut's own digest beside its source file's digest,
byte size, page count, package id and the publisher URL it was fetched from.
The source PDFs (5,657,813 and 5,192,693 bytes, SHA-256
`2248097b…` and `8c0198e5…`) are not committed; their digests agree with the
rollup receipt's `requests.jsonl`.

## Why these two ranges

**A totals check needs a whole section.** Each fixture carries one complete
`SUMMARY OF TRANSACTIONS BY APPROPRIATIONS` section, so
`summary_totals` can sum 28 account rows across seven printed pages and compare
them against the `Totals` row the print states — to the cent, on seven money
columns. A partial range would disagree, and should.

**All three grids, and the two that are not tables of amounts.** The second
fixture is the only one carrying `organization_detail` and `payee_detail`, the
grids whose body is one ruled cell holding a whole payee block. They are what
`cells_ruled` and the two-header-band rule are tested against, and what shows
why the contract carries no `payee_name` column
([the measurement](../../../docs/research/senate-expenditure-tables-2026-09-20.md)).

**Both sides of the page context.** B-1243 states an office, a funding year and
an appropriation title; B-1244 is a continuation page that states none, so the
NULL path is real rather than constructed. A-1 states a section heading and no
office at all.

**Two reporting periods and two spellings.** One fixture's headers read
`FUNDS AVAILABLE AS OF October 1, 2024`, the other's
`PERIOD OF 10/01/2025 THRU 03/31/2026`, so both date spellings the period rule
handles are exercised on real print.

## What they cannot show

Neither reaches the `C-` compensation-of-members or `D-` mail-allocation
sections the volumes' contents pages name, both of which are past page 2,000;
nothing here says what grids those carry. Neither exercises a page with two
ruled tables, because none of the 139 measured table pages had one.

## Rebuild

`build-fixtures.py` in the receipt directory, from retained bytes only:

```sh
uv run --frozen --all-extras python \
  ~/Work/corpora/supply-2026-09-02/receipts/senate-expenditure-tables-2026-09-20/build-fixtures.py
```

It keeps an existing fixture and re-checks it rather than rewriting it: PyMuPDF
writes a fresh document `/ID` on every save, so two cuts of the same pages
differ in bytes for no difference in content. The guarantee it enforces is the
stronger one — text and cells equal to the retained volume's, page for page.
