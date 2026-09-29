# GAO open-recommendations export excerpt

`open-recs-2026-09-28-excerpt.csv` is GAO's open-recommendations CSV
(`https://www.gao.gov/open-recs2-csv?q=`, `text/csv; charset=UTF-8`, fetched
through Zyte on 2026-09-28) cut to its preamble, its header and 35 of its 5,379
data records. Every record is the export's own bytes, terminator included, in
the export's order, so the CRLF preamble, the LF records and the missing final
terminator all survive. Directors' phones are kept as GAO prints them (owner
decision, 2026-09-29); the reader never reads them and the table never
publishes them. U.S. government work, public domain.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| Full export, "status as of Sep 28, 2026 at 7:05 PM EST" | 6,771,912 | `0bca0a8d9c463d9b0010fbe807ab5950dab33775b474d5ad03ba4fe6cab15fee` |
| `open-recs-2026-09-28-excerpt.csv` | 41,835 | `fb6f8a6b1fa91fc258b23032f08b58cbb65d168fb41abcd49d3fad5f3ba8fee2` |

Two captures twenty minutes apart returned the same bytes. The full export, its
capture receipts and the cutting script (`cut_fixture.py`, over `records.py`'s
quote-aware record split) are in
`corpora/supply-2026-09-02/receipts/gao-recommendations-20260928/`.

The kept data records, by zero-based position in the export, and why:

| Positions | Case |
| --- | --- |
| 0, 1, 2 | The first records: `Open`, "(Recommendation N)", no director phone |
| 11 | "(Matter for Consideration 1)", to Congress |
| 37 | A recommendation holding doubled quotes |
| 99 | A one-digit issue day (`Sep 8, 2026`) |
| 164 | An agency spelled with `&amp;` (Centers for Medicare &amp; Medicaid Services) |
| 172 | A publication name spelled with `&amp;` |
| 249 | Comments spelled with `&amp;` |
| 255 | "(recommendation 1)", lower case |
| 284 | `Open--Partially Addressed` |
| 393 | Priority `Yes` |
| 479 | "(Recommendation 9", never closed |
| 540 | A director phone written without a space, `(202)512-7952` |
| 652 | Comments holding doubled quotes |
| 767 | "(Recommendations 5)" |
| 990 | "[Recommendation 1]" |
| 1099, 1344, 1345 | A publication name holding a line break inside its quotes |
| 1444 | A narrow no-break space (U+202F) |
| 1534 | Two director phones in one field |
| 1742 | "(Matter for Congressional Consideration)", no number |
| 2149 | "(Matter 4)" |
| 2600 | A zero-width space (U+200B) |
| 3012, 3365 | Comments with outer whitespace; 3365 also names no director |
| 3288 | No director name |
| 3366 | "(Recommendation 1.)" |
| 3732, 3733, 3734 | One recommendation made to three agencies: three rows |
| 4253 | No topic |
| 4663 | "(Recommendation 19-01)" |
| 5378 | The last record, with no number stated and no terminator |
