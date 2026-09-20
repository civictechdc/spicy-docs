# Report of the Secretary of the Senate

The Senate's semiannual statement of its own expenditures, filed under
[2 U.S.C. 104a](https://www.govinfo.gov/link/uscode/2/104a) and printed as a
Senate document. Each report covers one half-year — October 1 to March 31, or
April 1 to September 30 — and runs 1,259 to 3,018 pages across two or three
PDFs.

This is the one PDF-only family in the
[rollup census](../research/pdf-family-rollup-yield-2026-09-20.md) whose value
is a **table** rather than a citation, and it is step 4 of the
[revised build order](../research/pdf-yield-mods-recheck-2026-09-20.md#revised-build-order).
The contract it fills is [`senate_expenditures`](../tables.md).

For a structural capture of retained pages, the bounded
[`senate-expenditures-pdf` adapter](../../tools/analysis/document_capture_pdf_tables.py)
preserves table, row and cell observations beside the PDF line stream. The
[offline comparison](../research/document-capture-pdf-tables-2026-09-20.md)
retains 2,267/2,267 observed cells across the same 160-page sample. Unmatched
cell text remains in the capture with a reason; analytical rows continue to
come directly from the independent `senate_expenditures` shaper.

## The index

**GovInfo's `CDOC` collection listing**, under package ids of the form
`GPO-CDOC-119sdoc3` — the `GPO-` prefixed reprint form, not the bare
`CDOC-119sdoc3`. One package publishes several PDFs:

| Link text | Locator |
| --- | --- |
| `Full Report` | `content/pkg/GPO-CDOC-119sdoc3/pdf/GPO-CDOC-119sdoc3.pdf` |
| `Part I` | `content/pkg/GPO-CDOC-119sdoc3/pdf/GPO-CDOC-119sdoc3-1.pdf` |
| `Part II` | `content/pkg/GPO-CDOC-119sdoc3/pdf/GPO-CDOC-119sdoc3-2.pdf` |

senate.gov links the same files and states **two fields** — the href and that
link text. That is the whole of the non-GovInfo index, which is why the rollup
counted this family's index as the thinnest in the census.

**The package id is not a unique key for a page.** `Full Report` and `Part I`
are separate objects with separate digests whose first sixty pages extract to
byte-identical text (measured; see
[the table measurement](../research/senate-expenditure-tables-2026-09-20.md#two-files-of-one-package-carry-the-same-pages)).
Anything keyed on a page must key on the file as well, and
`senate_expenditures` does.

## What the MODS states

The package MODS is the index `GovInfoBodyAcquirer` fetches for every body it
reads, and the [MODS re-check](../research/pdf-yield-mods-recheck-2026-09-20.md)
read all eight sampled volumes against theirs at full page depth:

| Kind | Print-only, against the MODS |
| --- | --- |
| `public_law` | **0** |
| `usc_section` | **0** |
| `bill_number` | **0** (the one apparent survivor, `S08`, is a print-side false positive) |
| dollar figures | 65,261 distinct over 161,536 rows — **no MODS states one** |

So the MODS is authoritative for this family's citations and the print adds
none. It states the document's bibliographic identity, its Congress and session,
its issue date and the laws and Code sections the document is filed under; it
states nothing about the content. **A citation extractor for this family would
recreate what the index already has, which is the owner's first rule, and it is
not built.**

## What only the PDF holds: the tables

Everything the report is for. Measured 2026-09-20 over 160 pages of two
volumes, 139 of which carry exactly one ruled table:

- the **summary of transactions by appropriation** — one row per Senate
  appropriation account, with the account number, the funds available, the
  supplementals, transfers and rescissions, the net expenditures, the revolving
  fund receipts and the unexpended balance, each stacked one line per fiscal
  year, and a `Totals` row that agrees with them to the cent;
- the **detailed and summary statement of expenditures** — per office, per
  funding year, per appropriation: an organization funding block and then the
  payments, document number, date posted, payee, service dates, description and
  amount.

**The print rules the first and not the second.** Of 227 ruled body rows, the
56 in the summary grid carry all nine cells and the other 171 carry exactly
one: a payment is a *line inside one cell*, not a ruled row. The full finding,
with counts, is in
[the table measurement](../research/senate-expenditure-tables-2026-09-20.md);
the contract carries the blob whole and names the print's own column roles
beside it rather than splitting it on a guess.

Two facts the page text holds and the table does not: the **printed page label**
(`A-7`, `B-1243`), present on 139 of 139 table pages and the locator the
volume's own contents index by; and the **office, funding year and appropriation
title**, stated on 83 of them — the first page of each office block — and on no
continuation page.

The funding year is sometimes a **span**. A two-year appropriation prints as
`Funding Year 2021-2023` and the contents index the same block as
`FY 21/23 – FY 25/27`; five of the 83 measured office pages are spans, all of
them the Chaplain's. A reader that expects a single year loses the office on
those pages entirely, which is worse than it sounds, because the office is
carried only on the first page of a block and a consumer fills the rest
forward.

## Acquisition

**Not wired up.** `sources/govinfo/bodies.py`'s package-id grammar covers
neither `BUDGET-*` nor `GPO-CDOC-*`, so `GovInfoBodyAcquirer` cannot reach
these packages in product code; widening it is an open decision record on the
[gap register](../research/closing-the-gaps-2026-09-19.md)'s B4 row. Until it
lands the contract is filled from the bytes the rollup retained, and it is
built so the grammar is the only thing missing: the shapers are pure over one
`TableObservation` and the page text, so any caller that reaches the package
can fill the table without the schema module changing.

Two costs to price before a full-volume run. The bodies are 5 to 12 MB each,
and `tables=True` cost the rollup **26.5–84.6 ms per page** against a few
milliseconds without it — over 3,018 pages that is minutes per volume, so this
is a detached run resumable from its own output, per
[the source workflow](../source-workflows.md). And every count taken from a
capped read is a floor; `pages_capped` says so per row.

## Reading the publisher's answer

The eight sampled PDFs were fetched keyless from `www.govinfo.gov` and all
eight returned `200` with `application/pdf`. Nothing here establishes that the
route is reliable: one success does not establish a route, and the rollup's own
receipt is the only evidence of this family's availability.
