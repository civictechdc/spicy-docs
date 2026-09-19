# CFR reconstruction fixtures

Four real annual CFR sections, each as the **evidence document** the PDF
extractor produced for it: `extraction.DocumentExtractor(NativeText())` over
the keyless GovInfo section PDF, through
`reconstruction.evidence.evidence_from_pages`, written by that model's own
`dumps()` (one JSON document, one block per line). No PDF is decoded at test
time and no PDF is committed: these are the same shape as
`tests/fixtures/gpo_pdf_text/`, one step further along, and they carry the
per-span style observations — font, size, bold, italic — that the parser's
typography rules read.

**Each file is every block of every page the section touches, not a selection
of lines.** The parser measures the body face, the line pitch and each
column's left edge over the whole document it is given, so dropping lines out
of a page would move those measurements and the fixture would exercise a
geometry GPO never printed. That was tried and it did exactly that: a
line-level reduction of `sec46-1` moved the measured body size onto the
table's own face and the table stopped reading as a table. These four PDFs are
one to three pages each, so whole pages are cheap.

| Fixture | Section | What it exercises | PDF bytes | PDF SHA-256 | Blocks |
| --- | --- | --- | ---: | --- | ---: |
| `CFR-2024-title12-vol1-sec1-1.evidence.json` | 12 CFR 1.1 | A plain section: no designated paragraph at all, so no ladder to get wrong | 139,133 | `fb5a50999c9483316b4233b726c8b99db32e13f80482180e30a77034fab11f9d` | 117 |
| `CFR-2025-title30-vol3-sec716-2.evidence.json` | 30 CFR 716.2 | Nested paragraphs `(a)`/`(1)`/`(i)`/`(A)` four levels deep, an italic run-in heading whose `(1)` never begins a line, a page break inside a paragraph, a source citation, and three neighbouring sections in the same page range | 157,908 | `508548281c0ab7fc68b7d4a4765b3972cbbca9dc72043861fbe696f07ef08162` | 355 |
| `CFR-2024-title12-vol1-sec46-1.evidence.json` | 12 CFR 46.1 | Two table regions in the page range, which survive as `UnresolvedRegion`s rather than being serialized wrongly, plus two appendix division headings | 149,357 | `1be0e803c7dbb8e2cfddf4fb533df015a35268e6de0c939250bf3d6927a8eade` | 193 |
| `CFR-2024-title12-vol1-sec21-1.evidence.json` | 12 CFR 21.1 | Four small-face runs no rule can place, which is the case the `classify_and_attach` seam exists for | 139,024 | `f7d95df44cc10977c9dda1d49fb0f47da8a258d71c899bf9d80444364ae5ab0e` | 107 |

`provenance.json` holds the same facts machine-readably and
`tests/test_reconstruction.py` reads it rather than repeating them.

**Every unresolved region in these four files belongs to a neighbouring part,
not to the section the granule names.** That is not an accident of the
fixtures: across the whole forty-section benchmark corpus, after the
`print_shop_footer` rule landed, no section had an unresolved region inside
the section its own granule names. It is the boundary the proposal's §3.1
describes — a section PDF is a page range of the printed volume — showing up
as evidence rather than as loss.

The PDFs were fetched keyless on 2026-09-19 from
`https://www.govinfo.gov/content/pkg/{package}/pdf/{granule}.pdf` by
`tools/analysis/reconstruction_benchmark.py`. The corpus manifest behind that
run, with all forty pairs and their digests, is at
`~/Work/corpora/supply-2026-09-02/receipts/reconstruction-benchmark-2026-09-19/`.
These are public-domain U.S. government documents.

**The paired reference for 30 CFR 716.2 is already in this repository**:
`tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml` is GovInfo's own XML
granule for the same section, which is what makes the round-trip test in
`tests/test_reconstruction.py` a comparison of one document with itself
rather than of two documents with each other. The other three sections have no
committed reference; the benchmark scores those against the publisher's XML at
run time.

These fixtures establish behavior for these four sections' shapes. They
establish no coverage of the CFR, and no continuing availability of the
addresses above.
