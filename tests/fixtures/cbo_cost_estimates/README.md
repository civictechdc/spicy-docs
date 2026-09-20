# CBO cost-estimate index fixtures

Four bounded excerpts of real BILLSTATUS records, cut from the two bulk zips
the [CBO routes measurement](../../../docs/research/cbo-cost-estimate-routes-2026-09-20.md)
retained on 2026-09-20 (receipt
`~/Work/corpora/supply-2026-09-02/receipts/cbo-routes-2026-09-20/`, blobs
`8e7ca7da…` for `118/hr` and `269261c0…` for `118/s`). Each file's own XML
comment states its source zip, the whole record's byte count and SHA-256, what
was kept and what was dropped, and why that record is here. These are U.S.
government documents in the public domain.

| Fixture | What it is here for |
| --- | --- |
| `BILLSTATUS-118hr801.excerpt.xml` | The ordinary shape: one estimate, one House report. Its report, `CRPT-118hrpt53`, is the recital fixture on the text side. |
| `BILLSTATUS-118hr3091.excerpt.xml` | The publisher states one publication twice, field for field — two items, one estimate. |
| `BILLSTATUS-118hr589.excerpt.xml` | One publication stated twice with a re-spelled title, which is the only field that ever differed across the 37 restated rows measured. |
| `BILLSTATUS-118s3139.excerpt.xml` | The Senate shape, whose report `CRPT-118srpt289` ends its letter at the `Estimate approved by` attribution. |

Only the identity block `parse_bill_status` validates, `<committeeReports>` and
`<cboCostEstimates>` are kept; every kept element is whole and verbatim.
Offline tests establish behavior for these shapes. They establish nothing about
coverage or continuing live availability — the corpus-wide counts live in
[the build measurement](../../../docs/research/cbo-cost-estimates-build-2026-09-20.md),
which reads the retained zips rather than these excerpts.
