# CBO cost-estimate letter fixtures

Seven bounded excerpts of the normalized text of real GovInfo `CRPT` bodies,
derived from the bytes the
[CBO routes measurement](../../../docs/research/cbo-cost-estimate-routes-2026-09-20.md)
retained keyless on 2026-09-20 (receipt
`~/Work/corpora/supply-2026-09-02/receipts/cbo-routes-2026-09-20/`). Each file
is `extraction.body_text.rendition_text(rendition="htm")`'s own output, cut to
the regions the rule reads and joined by a column-zero line naming the omitted
character range — column zero because a centered line could otherwise be read
as a heading. These are U.S. government documents in the public domain.

`sources.json` pins, per package: the URL, the retained response's SHA-256 and
byte count, the derivation, the **full** extracted text's character count and
SHA-256, the kept ranges, and the excerpt's own digest — so an excerpt can be
checked against a source it does not contain.
`tests/test_cbo_estimates.py::test_retained_fixture_pins` reads it.

| Fixture | Branch it establishes |
| --- | --- |
| `CRPT-118hrpt53.txt` | Recital present, House style; the span ends at the Director's signature block and the cover names the bill. |
| `CRPT-118hrpt780.txt` | Recital present; the attribution is parenthesised, `(For Phillip L. Swagel, Director, …)`. |
| `CRPT-118hrpt951.txt` | Recital present; GPO wrapped the heading across two centered lines, so a line-at-a-time matcher sees neither half. |
| `CRPT-118srpt298.txt` | Recital present and **no attribution at all** — a summary table rather than a letter — so the span ends at the next heading in the same numbering series (`VI.` to `VII.`). |
| `CRPT-118hrpt18.txt` | No recital, a CBO heading, and the publisher's own reason: the estimate was not available. A heading gate would publish this as an estimate. |
| `CRPT-118hrpt111.txt` | No recital; the reason sits under `C. Cost Estimate Prepared by the Congressional Budget Office`, a heading the routes measurement's five patterns missed. |
| `CRPT-118srpt99.txt` | No recital, and two markers that look like a letter outside the gate: a `Washington, DC, March 1, 2023.` dateline on the committee's own transmittal, and `Director, Congressional Budget Office.` in a witness list. |

Each excerpt reproduces the whole body's finding exactly — same heading rule,
same end rule, same span length, same signatory — which is checked against the
full bodies in
[the build measurement](../../../docs/research/cbo-cost-estimates-build-2026-09-20.md),
not here. Offline tests establish behavior for these shapes; they establish
nothing about coverage or continuing live availability.
