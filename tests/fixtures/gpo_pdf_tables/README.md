# GPO PDF table-geometry fixture

One real page, not a byte-range excerpt: page 11 of the Senate Department of
Homeland Security Appropriations Committee report, extracted with PyMuPDF
(`document.insert_pdf(source, from_page=10, to_page=10)`, then
`subset_fonts()` and `tobytes(garbage=4, deflate=True)`) into its own
single-page PDF so the fixture stays small while remaining a real, openable
document PyMuPDF's `find_tables()` reads the same way it reads the full
report. This is what B5 of
`docs/research/closing-the-gaps-2026-09-19.md` measures against: the report
whose HTML rendition the govinfo-bodies "Why PDF is last" measurement already
uses for the 841-row reference count.

| Fixture | Source | Page | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `CRPT-113srpt77.page11.pdf` | [full-report PDF](https://www.govinfo.gov/content/pkg/CRPT-113srpt77/pdf/CRPT-113srpt77.pdf), keyless, fetched 2026-09-19 | 11 of 190 | 66,708 | `54264b3e646aaf814f99e2d768975609bcfc9fd4fb7e61ec6efab1571bb31dfc` |

The full source PDF (531,055 bytes, SHA-256
`d533775b53de0ba1fd4d35d9d4345727a87979aa578d18db778e917be4b7f76a`) is not
committed -- it agrees with the digest already recorded in
`docs/sources/govinfo-bodies.md`'s "The rendition comparison that ordered
`BODY_PREFERENCE`" table and in `tests/fixtures/agency_reports/sources.json`,
an independent re-fetch on the same date agreeing with the prior one rather
than restating it.

This page carries an "Office of the Secretary and Executive Management"
account table: a real ruled grid (GPO drew horizontal and vertical rules
around the header, the fifteen-account body block and the total), which is
why PyMuPDF's default line-based `find_tables()` finds it at all -- most of
this report's comparative-statement rows use leader-dot or whitespace
alignment with no ruling, and the default strategy finds nothing there (see
`docs/sources/govinfo-bodies.md`, "Table geometry recovered from the PDF").
PyMuPDF reports this table as three ruled rows (header, one multi-line body
cell per column -- the label column carries the fifteen accounts plus its
own trailing "Total," label line, each amount column carries the matching
fifteen figures -- and a separately-ruled total row), not fifteen separate
rows: there is no rule between individual accounts, only around the block.
`tests/extraction/test_api.py`'s pinned test asserts that shape and the
account lines' exact `\n`-joined text, not fifteen `TableObservation` rows.

Re-derive with `spicy_docs.sources.govinfo.bodies.package_body_locator
("CRPT-113srpt77", "pdf")`; U.S. government committee reports are public
domain.
