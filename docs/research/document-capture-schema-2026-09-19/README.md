# Document capture conversions

The six worked conversions behind
[`../document-capture-schema-2026-09-19.md`](../document-capture-schema-2026-09-19.md),
produced by `tools/analysis/document_capture.py` and re-checked offline by
`tests/test_document_capture.py`. Regenerate from the repository root:

```sh
uv run --frozen python -m tools.analysis.document_capture --output docs/research/document-capture-schema-2026-09-19
```

That command makes no request. It reads four committed fixtures and the
retained inputs below, writes one `<name>.capture.json` and one
`<name>.fragments.json` per document, and `measurement.json`. Pass
`--scotus-pdf <file>` to re-extract the slip opinion from the fetched PDF
instead of reading the retained evidence document; the PDF must match the
receipt's digest.

| Output | Input | Input receipt |
| --- | --- | --- |
| `plaw-119publ1.*` | `tests/fixtures/uslm/plaw-119publ1.xml` | `tests/fixtures/uslm/README.md` |
| `bills-119hjres25enr.*` | `tests/fixtures/govinfo_bills/text-119hjres25enr.xml` | `tests/fixtures/govinfo_bills/README.md` |
| `crpt-119hrpt1.*` | `tests/fixtures/govinfo_bodies/body-CRPT-119hrpt1.htm` | `tests/fixtures/govinfo_bodies/README.md` |
| `fr-2026-19200.*` | `inputs/fr-2026-19200.xml` (10,224 bytes, sha256 `0f0653b6ea1063944e444893cb385f24a3cfe635088683465d6a9ce3e903c3e2`) and `inputs/fr-2026-19200.json` | `inputs/requests.jsonl`, lines 4 and 5 |
| `cfr-2025-title30-vol3-sec716-2.*` | `tests/fixtures/reconstruction/cfr/CFR-2025-title30-vol3-sec716-2.evidence.json` | `tests/fixtures/reconstruction/cfr/README.md` |
| `scotus-26a274_l537.*` | `inputs/26a274_l537.evidence.json`, extracted from the 66,165-byte PDF (sha256 `7c14a9d1e945641c23b82a8838f94d4af5113ef51424d21bd1d623bffbdf2e60`) by `extraction.DocumentExtractor(NativeText())` and `reconstruction.evidence.evidence_from_pages` | `inputs/requests.jsonl`, line 1 |

`inputs/<name>.pages.json` retains each PDF's page sizes in points, pinned to
the PDF's digest, because `evidence_from_pages` keeps line boxes in permille
of the displayed page and drops the size that produced them. Without them a
`page` node cannot state `pageSize` and a page region cannot be cited in the
unit RFC 8118 names.

`inputs/requests.jsonl` is a copy of the request log in
`~/Work/corpora/supply-2026-09-02/receipts/document-capture-schema-2026-09-19/`,
which also holds the fetch commands and this run's `summary.json`. Five keyless
requests were made; the third, a guessed govtrack address, answered 404 and
retained nothing. The fetched documents are public-domain U.S. government
documents. The slip opinion PDF itself is not committed, following the
`tests/fixtures/supreme_court/` policy.

Each `*.fragments.json` renders two leaves of its capture as
`rkaf:SourceFragment`s: one into the capture's text stream (with the
carrier-local URN where the leaf is one contiguous run) and one into the
publisher's artifact in its own coordinates. `tests/test_document_capture.py`
resolves every selector of both against the bytes it names.

`visual-review.md` and `png/` are the 2026-09-19 visual review of the six
profiles against the print rendition of each family's document, retained as
received with the fourteen pages it viewed. The design record says what each
finding changed.
