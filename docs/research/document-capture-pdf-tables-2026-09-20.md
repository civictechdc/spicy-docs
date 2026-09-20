# PDF table observations now enter DocumentCapture

**G2's dropped-input gap is closed for the measured Senate sample.** Fresh
captures retain **2,267/2,267 observed cells** from **673/673 ruled rows** on
pages 1–80 of each of two retained PDFs. Both directional differences are zero.
The run made **zero network requests**. This establishes preservation of the
extractor's observations; it does not establish complete table detection or
coverage of every PDF family.

The [sidecar](document-capture-pdf-tables-2026-09-20.json) records input and
implementation digests, counts, validations and full receipt paths. The
[receipt README](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/document-capture-pdf-tables-2026-09-20/README.md)
names the retained captures, extractor evidence and per-cell differences.

## Inputs and preservation comparison

Both inputs are read-only blobs under
`/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20/blobs/<sha256>`.
The [PDF-family MODS recheck](pdf-yield-mods-recheck-2026-09-20.md) supplies the
family context; the page scope comes from the existing
[Senate table reading](senate-expenditure-tables-2026-09-20.md).

| File | SHA-256 | Bytes | Pages read / total |
| --- | --- | ---: | ---: |
| `GPO-CDOC-119sdoc3-1.pdf` | `2248097b0c5106889d8882a979a0488a49f283b29e28289d2778864c40b7b13e` | 5,657,813 | 80 / 1,335 |
| `GPO-CDOC-119sdoc6-2.pdf` | `8c0198e57f3f4a3bba56939e3972c7c2d3ef55f4d01aa0addd2457ff98158e47` | 5,192,693 | 80 / 1,264 |

The reference passes the independently retained `sdoc3-1.p1-80.json` and
`sdoc6-2.p1-80.json` readings through `shape_senate_expenditure_rows`. The
capture side freshly runs `DocumentExtractor(NativeText(), tables=True)` on
the pinned PDF bytes and the new adapter. It never consumes reference cells.
Both readings go through PyMuPDF 1.28.2. A shared extraction defect is invisible
to this comparison, and detector-level agreement is near-identity. The
2,267-of-2,267 agreement establishes preservation: the adapter neither changes,
drops, duplicates, moves nor misidentifies an observation relative to the
reference reading. It does not independently establish that PyMuPDF read the
printed table correctly.

A stronger publication check was not done: re-reading the analytical Parquet
rows the contract published, or previously retained shaper output. Instead,
this measurement recomputes the reference with the shaper in the same pass.

Row identity is `(package_id, file_name, page, table_ordinal, row_ordinal,
text_sha256)`. That last digest describes **raw page text**, not a cell or the
capture stream; the comparison removes only the contract's `sha256:` prefix.
Cell comparison uses multisets of `(package, file, page, table ordinal, row
ordinal, SHA-256 of verbatim cell text)`, preserving repeated identical cells.
A second comparison also requires the column to agree. Mutation tests prove
each of the five preservation failures makes the comparison fail: changed
text, dropped cells, duplicate cells, moved columns, and misidentified
package/file/page/table/row or page-text digest.

| Reading | Table pages / read | Ruled rows matched / contract | Cells matched / contract | Capture-only / capture | Contract-only / contract |
| --- | ---: | ---: | ---: | ---: | ---: |
| Part I, sdoc3 | 69 / 80 | 357 / 357 | 1,202 / 1,202 | 0 / 1,202 | 0 / 1,202 |
| Part II, sdoc6 | 70 / 80 | 316 / 316 | 1,065 / 1,065 | 0 / 1,065 | 0 / 1,065 |
| **Total** | **139 / 160** | **673 / 673** | **2,267 / 2,267** | **0 / 2,267** | **0 / 2,267** |

All 139 table pages carry one table. The column-sensitive comparison also
matches 2,267/2,267 cells. The adapter emits 139 tables and 673 row nodes;
these are all ruled rows, including headers and totals, not individual payments.

## Text reconciliation and geometry

The reusable adapter is
[`tables_to_nodes`](../../tools/analysis/document_capture_pdf_tables.py),
composed with the existing line builder by `pdf_pages_to_nodes`. The
`senate-expenditures-pdf` profile is new because none of the six existing
profiles describes Senate reports or permits these observation fields. It
adds no node kinds: `table`, `row`, `cell`, decisions, issues and source boxes
already belong to the unchanged pinned parent. The profile passes its pinned
meta-schema and binding checks.

Every present cell keeps verbatim `ext.observedText`. An empty string produces
an empty cell node; a position with neither text nor geometry produces no cell
node. Table dimensions preserve the missing positions. Cell and table boxes
are retained in the parent's integer permille; row boxes unite observed cell
boxes. The run retains **87/87 empty cells**, omits **3,905/3,905 missing
positions**, and flags **505/2,267 cells without boxes**. Those missing boxes
already exist in the retained rotated-page observations; the adapter does not
repair geometry or infer `rowSpan`, `columnSpan` or `header`.

The capture stream stays assembled lines joined by newline, and page changes
by form feed. `BodyText` applies GPO cleanup and joins pages with newline;
its offsets must never be copied into capture spans. A whole cell must match
verbatim on its own page, outside another word or number. Repeated text needs
one match whose contributing line boxes fit inside the cell. Remaining
ambiguity and overlapping claims are refused. Matches split and transfer
existing spans from line nodes, preserving the stream and its single-owner rule.

Of **2,180 nonempty cells**, **1,505/2,180** receive exact spans and
**675/2,180** remain unresolved: **289/675** have text absent from the stream,
**326/675** have repeated text without a cell-local match, and **60/675** remain
ambiguous. Each unresolved cell retains its observed text, location,
`reviewStatus: needs_review` and `pdf-cell-text-unresolved` reason, with no
invented span. These are node issues, not entries in `unresolved`: the parent
requires each such region to own an existing span. Full per-cell reasons are
retained in the receipt, with the text in the captures.

## Bounded adapter timing after review

The adapter now indexes nodes and spans by page once, searches only that
page's text, and rebuilds document spans once after collecting all claims.
It clears owner lists once and detects overlapping interval groups without
comparing every pair. Permille conversion uses `block_source`; row and
assembled-line boxes share `Box.union`.

For 20/40/80/160 repeated fixture pages, the review reported
0.032/0.113/0.428/1.751 seconds. A matched local rerun measured
**0.025/0.084/0.326/1.297 seconds before** and
**0.009/0.018/0.037/0.088 seconds after** (median of five runs of
`pdf_pages_to_nodes`, excluding PDF extraction). This bounded probe now grows
roughly with page count; it does not measure whole-volume extraction or dense
single-page search costs. The pinned fixture, original adapter, command and
raw samples are retained in
[`document-capture-pdf-tables-review-2026-09-20`](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/document-capture-pdf-tables-review-2026-09-20/).
The original sidecar and receipts remain the baseline; review reruns use a
separate output directory. Capture byte digests also cover converter source,
Git revision, capture time and the retained-evidence path. Any changed digest
must be reported rather than substituted into that baseline.

## Reproduce and check

From this worktree, using cached dependencies and retained inputs only:

```sh
UV_OFFLINE=1 uv run --frozen python -m tools.analysis.measure_document_capture_pdf_tables \
  --output /tmp/document-capture-pdf-tables-rerun \
  --sidecar /tmp/document-capture-pdf-tables-rerun.json
UV_OFFLINE=1 uv run --frozen pytest -q tests/test_document_capture_pdf_tables.py tests/test_document_capture.py
UV_OFFLINE=1 ./scripts/check
```

The measurement exits 1 on disagreement, invalid captures or a changed line
stream. Both captures pass the parent, profile and invariant checks, and their
streams match independent rejoins of the retained line evidence. The bounded
fixture is full-PDF page 17 of sdoc3 Part I, with its own digest and cut
provenance; it includes empty, missing, matched and unresolved cells.

G1 (reversible capture XML) and G3 (required shared provenance) remain separate
open gaps. This run does not split payments inside unruled cells, fix extractor
geometry, cover the unread pages, or establish captures for every PDF family.
