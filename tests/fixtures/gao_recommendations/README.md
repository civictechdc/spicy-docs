# GAO open-recommendations export excerpt

`open-recs-2026-09-28-excerpt.csv` is GAO's open-recommendations CSV
(`https://www.gao.gov/open-recs2-csv?q=`, `text/csv; charset=UTF-8`, fetched
through Zyte on 2026-09-28) cut to its preamble, its header and 26 of its 5,379
data records. Every record is the export's own bytes, terminator included, in
the export's order, so the CRLF preamble, the LF records and the missing final
terminator all survive. U.S. government work, public domain.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| Full export, "status as of Sep 28, 2026 at 7:05 PM EST" | 6,771,912 | `0bca0a8d9c463d9b0010fbe807ab5950dab33775b474d5ad03ba4fe6cab15fee` |
| `open-recs-2026-09-28-excerpt.csv` | 32,751 | `d6c0fc5bff6b17638ad9cd13015cbd714d3cc6131507aa636041985bf8eef4da` |

Two captures twenty minutes apart returned the same bytes. The full export, its
capture receipts and the cutting script (`cut_fixture.py`, over
`records.py`'s quote-aware record split) are in
`corpora/supply-2026-09-02/receipts/gao-recommendations-20260928/`.

The kept data records, by zero-based position in the export, and why:

| Positions | Case |
| --- | --- |
| 0, 1, 2 | The first records: `Open`, no director phone |
| 37 | A recommendation holding doubled quotes |
| 99 | A one-digit issue day (`Sep 8, 2026`) |
| 164 | An agency spelled with `&amp;` (Centers for Medicare &amp; Medicaid Services) |
| 172 | A publication name spelled with `&amp;` |
| 249 | Comments spelled with `&amp;` |
| 284 | `Open--Partially Addressed` |
| 393 | Priority `Yes` |
| 540 | A director phone, which the reader does not read |
| 652 | Comments holding doubled quotes |
| 1099, 1344, 1345 | A publication name holding a line break inside its quotes |
| 1444 | A narrow no-break space (U+202F) |
| 1534 | Two director phones in one field |
| 2600 | A zero-width space (U+200B) |
| 3012, 3365 | Comments with outer whitespace; 3365 also names no director |
| 3288 | No director name |
| 3732, 3733, 3734 | One recommendation made to three agencies: three rows |
| 4253 | No topic |
| 5378 | The last record, with no terminator |
