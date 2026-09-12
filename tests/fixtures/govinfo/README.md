# GovInfo metadata fixture

`cfr-mods-excerpt.xml` is a reserialized excerpt of
[2025 Title 1 package MODS](https://www.govinfo.gov/metadata/pkg/CFR-2025-title1-vol1/mods.xml).
It retains all package fields, the host relationship and three constituents:
Part 1, section 1.1 and Chapter VI. Other constituents were removed, so some
parent identifiers deliberately do not resolve within this excerpt.

The fixture contains 203 elements and 15,418 bytes. It preserves literal notes,
repeated references, rendition links and the publisher's `part number="VI"`
reference hint. That hint is not repaired to match the chapter label.

Full input: 1,342,199 bytes, SHA-256
`6ae66a2ba6939c1c0c307199dcab3ba69aa1e607f3a4640dc58ba17b2aa4ceed`.
The September 12 capture is retained under
`~/Work/corpora/supply-2026-09-02/receipts/cfr-edition-type-2026-09-12/annual-title1-mods.xml`.
This excerpt is not an exact HTTP capture. Synthetic cases in the test module
exercise repeated dates, unknown fields, mixed content and namespace rebinding.
