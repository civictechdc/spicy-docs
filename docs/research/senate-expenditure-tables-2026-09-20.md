# What the Secretary of the Senate's ruled tables actually are

Status: measured 2026-09-20, read-only over bytes the
[PDF-family rollup](pdf-family-rollup-yield-2026-09-20.md) already retained.
**No request was made.** Input pins, the commands and the retained output are
in `~/Work/corpora/supply-2026-09-02/receipts/senate-expenditure-tables-2026-09-20/`.
Tool: [`tools/analysis/senate_expenditure_tables.py`](../../tools/analysis/senate_expenditure_tables.py),
two phases, both through `uv run --frozen --all-extras`.

This is the measurement that had to come before
[`senate_expenditures`](../tables.md), item 4 of the
[revised build order](pdf-yield-mods-recheck-2026-09-20.md#revised-build-order).
The rollup established that the family is worth a table contract — 396 ruled
tables in 480 sampled pages, 65,261 distinct dollar figures over 161,536 rows
at full length, a citation yield of zero. It did not establish **what one
ruled row is**, and that turns out to be the whole design.

## Input pins

| Volume | File | Bytes | SHA-256 | Pages | Read |
| --- | --- | ---: | --- | ---: | --- |
| Report of the Secretary of the Senate, 119th Congress, Oct 1 2024 – Mar 31 2025, Part I | `GPO-CDOC-119sdoc3-1.pdf` | 5,657,813 | `2248097b0c5106889d8882a979a0488a49f283b29e28289d2778864c40b7b13e` | 1,335 | 1–80 |
| Same report, Oct 1 2025 – Mar 31 2026, Part II | `GPO-CDOC-119sdoc6-2.pdf` | 5,192,693 | `8c0198e57f3f4a3bba56939e3972c7c2d3ef55f4d01aa0addd2457ff98158e47` | 1,264 | 1–80 |

Both digests are the rollup receipt's own `requests.jsonl` entries, and the
bytes are its content-addressed blobs. Extraction is
`DocumentExtractor(NativeText(), tables=True)`, the same call the rollup made.

## The shape of the print

160 pages read, **139 carry exactly one ruled table** and 21 carry none — the
front matter and the contents. Never two tables on a page, never one table
spanning two. 673 ruled rows over 6,172 cell positions.

The print draws **three** grids, and they are not interchangeable. Each one is
identified by the label its own first row states, never by its column count:

| Grid | First row states | Tables | Columns | What one ruled row is |
| --- | --- | ---: | ---: | --- |
| `appropriation_summary` | `APPROPRIATION TITLE` | 13 | 9 | One appropriation account. All nine cells ruled. |
| `organization_detail` | `TOTAL FUNDING YTD ($)` | 83 | 10 | One office's funding block. **One** ruled cell in the body. |
| `payee_detail` | `DOCUMENT NO.` | 43 | 7 | A continuation page of the same block. **One** ruled cell. |

Geometry: 3 to 11 rows, 7/9/10 columns, 13 distinct shapes. That reproduces
the rollup's pinned rows 3/5/11 and columns 7/…/10 over a different and
smaller sample, which is the check that the two reads agree.

## The decisive finding: the print does not rule the payee lines

**3,905 of 6,172 cell positions — 63% — are positions the extraction finds no
cell region at all.** Split by grid, over the 227 rows the contract classifies
as `entry`:

| Grid | Entry rows | Cells the print rules per row |
| --- | ---: | --- |
| `appropriation_summary` | 56 | **9 of 9**, every row |
| `organization_detail` | 99 | **1 of 10**, every row |
| `payee_detail` | 72 | **1 of 7**, every row |

So only **56 of 227 entry rows (25%) are cell-separated at all**, and all of
them are in the one grid that tabulates accounts rather than payments.

The other two grids *do* carry a header band naming `DOCUMENT NO.`,
`DATE POSTED`, `PAYEE NAME`, `START`, `END`, `DESCRIPTION` and `AMOUNT ($)` —
and the print rules that band, which is why the band is found. It does not rule
what sits under it. A payment arrives as a line inside one cell:

```
00646684 02/19/2025 PATTY MURRAY 02/19/2025 02/19/2025 SENATOR TRANSPORTATION $19.96
INTERDEPARTMENTAL TRANSPORTATION
```

**This is why `senate_expenditures` carries no `payee_name`, `document_number`,
`date_posted` or singular `amount` column**, although the brief that scoped it
named all four and although the print's own header names them. Filling them
would mean splitting a blob on an unmeasured guess — the failure the rollup
made four separate times before its sample corrected it — and a column NULL on
every row of every fixture is the defect the
[design brief](table-contracts-2026-09-19.md) already names for
`hearing_transcripts`. What lands instead is the blob **whole** in
`cells_json`, the print's own role for every column in `column_headers_json`,
and `cells_ruled` so `WHERE cells_ruled` is exactly the rows whose cells are
separate facts. **Splitting the payee block is a text rule for
`interpretation/`, it is measurable against these same retained bytes, and it
is not measured here.**

## What one `appropriation_summary` row holds

Nine ruled cells, and both the title cell and every money cell stack one line
per fiscal year, in the same order:

| Cell | Content |
| --- | --- |
| `APPROPRIATION TITLE` | `COMPENSATION OF\nMEMBERS\n2023\n2024\n2025` |
| `NO.` | `0100` |
| `FUNDS AVAILABLE AS OF October 1, 2024` | `798,584.35\n687,246.58\n24,949,150.00` |
| `SUPPLEMENTALS`, `TRANSFERS`, `RESCISSIONS/ WITHDRAWALS` | `0.00\n0.00\n0.00` each |
| `NET EXPENDITURES` | `0.00\n-27.75\n-12,161,280.90` |
| `REVOLVING FUND RECEIPTS` | `0.00\n0.00\n0.00` |
| `UNEXPENDED BALANCE AS OF March 31, 2025` | `798,584.35\n687,218.83\n12,787,869.10` |

So the unit of an amount is the **line**, not the cell. A revolving-fund row
states one line per cell instead of three, and the print says which by stacking
`X (REVOLVING)` in the title cell rather than years.

## The roles come from the print's header, and the band moves

`organization_detail` carries **two** header bands in one table: rows 0–1 name
the organization-summary columns and rows 2–3 name the payee columns. Column 0
goes from the office block to `DOCUMENT NO.` and `DESCRIPTION` moves from
column 3 to column 7 *inside one table*. A single per-table header would be
wrong for half the rows, so `column_headers_json` is per row and reads the
**nearest** band above it. That is also the reason a separate
`senate_expenditure_tables` companion was not built: there is no one header row
for it to hold.

A row is a header row when **two** of its cells are header labels. One is not
enough: the blob cells contain `DESCRIPTION` and `END` inside sentences, and no
measured body row states two header labels as whole cells. Of 673 rows, 361 are
header, 85 are `total` and 227 are `entry`.

## Where the office and the page label are stated

| Fact | Stated on | Of 139 table pages |
| --- | --- | ---: |
| Printed page label (`A-7`, `B-1243`) | last non-empty line of the page text | **139** |
| Office / `Funding Year` / appropriation title | page text | 78 |
| The same block, in the table's own first cell | table | 21 |

Every one of the 21 table-cell occurrences is also in the page text, so the
page text is a strict superset and is the source the contract reads. The other
61 table pages are continuation pages, on which the print states no office at
all; `office` is NULL there and a consumer forward-fills in `printed_page`
order. That is also why the shapers take `TableObservation` **plus the page
text**: the table alone would lose the office on three pages in four.

`printed_page` is the locator that matters: the volume's own table of contents
indexes by `B-1 – B-36`, not by PDF page.

## The check that can fail

The `appropriation_summary` section ends on a row the print labels `Totals`,
and each of its money columns should be the sum of every amount line in that
column over every entry row of the section — across the seven pages the section
runs. Run over both volumes' whole sections:

| Volume | Section | Entry rows | Amount lines summed | Money columns | Result |
| --- | --- | ---: | ---: | ---: | --- |
| `GPO-CDOC-119sdoc3-1.pdf` | A-1 – A-7 | 28 | 93 per column | 7 | **agrees to the cent** |
| `GPO-CDOC-119sdoc6-2.pdf` | A-1 – A-6 | 28 | 93 per column | 7 | **agrees to the cent** |

Stated against summed, `FUNDS AVAILABLE`: `1,771,557,289.86` and
`2,055,856,462.50`. `NET EXPENDITURES`: `-649,330,011.60` and
`-627,015,388.75`. `UNEXPENDED BALANCE`: `1,124,171,630.54` and
`1,430,534,226.97`.

This is a real check: a dropped cell, a column read one place over, or an
amount parsed loosely all move a sum, and none of them would look like an error
anywhere else. `tests/test_senate_expenditures.py` runs it on both fixtures and
also runs it on a section with one entry row deleted, so the check is proved to
bite rather than to agree with itself.

**What it cannot see** is column 0, because the `Totals` row states no amount
there. That is exactly where the one defect this measurement found was hiding.

## The defect the totals check missed

The first amount rule accepted a bare integer, so it read the fiscal years
`2023`, `2024`, `2025` stacked in the title cell as money. The totals check
passed anyway — it never reaches column 0 — and the error surfaced only in a
test that asserted the title cell states no amount.

Re-measured across both volumes: **1,316 printed lines are amount-shaped and
every one carries a `.dd` tail.** The 143 that do not are 32 distinct strings,
and all 32 are appropriation account numbers (`0100` through `4326`) or fiscal
years (`2023` through `2026`). So the decimal point is required, and that is
the print's own spelling rather than a convention.

## Two files of one package carry the same pages

`GPO-CDOC-119sdoc3.pdf` (`Full Report`) and `GPO-CDOC-119sdoc3-1.pdf`
(`Part I`) are two files in package `GPO-CDOC-119sdoc3` with different digests
and sizes whose first 60 pages extract to **byte-identical text** — measured on
the rollup receipt's own retained extracts, MD5 `518477a5…` for both. Keying
the contract on `(package_id, page, table_ordinal, row_ordinal)` would have
collided them silently, so `file_name` is in the identity.

## Acquisition is not wired up yet

`sources/govinfo/bodies.py`'s package-id grammar reaches neither `BUDGET-*` nor
`GPO-CDOC-*`, so `GovInfoBodyAcquirer` cannot fetch these packages in product
code. The register's B4 row carries that as an open decision record. Until it
lands, the contract is filled from retained bytes, and it is built so that the
grammar is the only thing missing: the shapers are pure over one
`TableObservation` and the page text, so a caller that reaches the package by
any route can fill the table without this module changing.

## Complexity

Per page of `N` characters holding a table of `R` rows and `C` columns, shaping
is `O(N + R·C)`: the page scan and digest are paid once per page rather than
once per row, which is the difference between `O(N)` and `O(R·N)` on a page
with eleven ruled rows. The census is linear in dumped cells. Nothing here is
superlinear, and nothing re-reads a page.

The cost that *is* superlinear in practice is the read itself:
`find_tables()` cost the rollup 26.5–84.6 ms/page against a few ms without it,
and these volumes run 1,264 to 3,018 pages. A full-volume build is a detached
run, resumable from its own output, not a foreground call.

## What this measurement cannot see

- **160 pages of two volumes, of eight volumes running 1,259 to 3,018 pages.**
  Every count here is a floor, and `pages_capped` carries that per row. The
  later pages of these volumes hold sections this read never reached — the
  `C-` compensation and `D-` mail-allocation sections the contents page names —
  and nothing here says what grids those carry.
- **Two of the eight retained volumes.** The other six were not re-read with
  `tables=True` for this note; the rollup's own capped read of all eight is the
  evidence that the geometry generalises, and it is a 60-page read.
- **Whether the payee blob is splittable.** Not attempted, not measured. The
  header band names the fields, which is a strong prior and not a measurement.
- **The totals check covers one grid.** `organization_detail` states
  `ORGANIZATION TOTALS` inside its one body cell rather than as a row, so there
  is no cell-level arithmetic to check there, and this note claims none.
- **Nothing about live availability.** No request was made; these are retained
  bytes from 2026-09-20.
