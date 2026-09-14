# Supreme Court slip opinion fixtures

Captured 2026-09-14 from `https://www.supremecourt.gov/opinions/slipopinion/{code}`
and the PDF links those pages stated, with a `spicy-docs-supreme-court/1.0`
user agent and no credential; the route takes none. Opinions of the Supreme
Court of the United States are U.S. government works in the public domain.
Offline tests establish behavior for these shapes; they do not establish
coverage or continuing live availability.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `term-index-2025.html` | [/opinions/slipopinion/25](https://www.supremecourt.gov/opinions/slipopinion/25) | 4,918 | `027fb2feea2617912a22cfad728157e16112a12d70603226fc698259abc9d7f7` | The `<div id="list">` header through the table's header row, then 5 of 72 data rows (R- `71`, `66`, `55`, `54`, `D1`) verbatim, then a closing `</table></div></div></div>`. Page chrome, scripts, ASP.NET tokens and the other 67 rows removed. Complete response 108,678 bytes, SHA-256 `30c0e67f759f7af00ca3da7abde780d67369f7871e6c23684e45a27bdb4d9d09`. |
| `term-index-2020.html` | [/opinions/slipopinion/20](https://www.supremecourt.gov/opinions/slipopinion/20) | 3,244 | `23298588b22f42ee87cfaaa821a0257917e712fddc65958994f0cbef83429703` | Same reduction; 2 of 68 data rows (R- `68` and `1`). Complete response 107,445 bytes, SHA-256 `683c8a9713e8845d880d9a9b62f8e65dc611963eb26b021dd7de47e5112a921d`. |
| `opinion-26a274_l537.head.pdf` | [/opinions/25pdf/26a274_l537.pdf](https://www.supremecourt.gov/opinions/25pdf/26a274_l537.pdf) | 1,024 | `df5e5216a0ab79123505589ec67f528f33c579957cb10aece0fc34739d9ff12e` | **First 1,024 bytes only**, so an incomplete capture is what this file is. Complete response 66,165 bytes, SHA-256 `7c14a9d1e945641c23b82a8838f94d4af5113ef51424d21bd1d623bffbdf2e60`, `content-type: application/pdf`, no redirect. |

The five OT2025 rows are the five row shapes the term states, so a parser that
reads only the common one fails here rather than in production:

- `71` — a slip opinion with a holding in the anchor's `title`.
- `66` — a revised opinion (`25-365_new_5if6.pdf`) plus a `Revisions:` link to
  the diff. Both are links in one cell; only the first is the opinion.
- `55` — a case name in plain text whose **only** link is a revision diff.
  Taking the first anchor in the cell makes the case name `6/28/26`.
- `54` — a listed case with no link at all.
- `D1` — release number `D1`, docket `141, Orig.`, and `title=""`: a stated but
  empty holding, which is absent rather than the empty string.

`term-index-2020.html` holds the older layout: row `68` links a slip PDF, row
`1` links `/opinions/preliminaryprint/592US1PP_web.pdf#page=41`. The fragment
says where in the volume the opinion begins and is not part of the resource.
Fifteen OT2020 rows point into that one volume file.

The PDF prefix keeps the parts a reader checks: the `%PDF-1.6` magic and the
linearization dictionary `<</Linearized 1/L 66165/O 101/E 46378/N 5/T 65805…>>`,
whose `/L` is the complete file's length. So the fixture is both a real header
to read and a real truncated capture to refuse; the test reconstructs a
complete body from it by padding to 66,165 bytes.

Two renders of the OT2025 index 2.5 minutes apart disagreed about 24 of 72
rows' links while stating the same `Last-Modified`. `term-index-2025.html` comes
from the earlier render. A term index capture is one render at one instant, and
a link is only what a retained index stated.

Complete pages and PDFs, response headers, the render-drift and
revision-token experiments, and the term-code confirmation are in
`corpora/supply-2026-09-02/receipts/port-P02-supreme-court-2026-09-14/`.
