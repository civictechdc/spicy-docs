# CFR source fixtures

These fixtures check source identity and response shape. XML excerpts are
reserialized, deliberately incomplete test inputs; they establish no collection
coverage. Full captures and acquisition receipts stay outside the repository.

| Fixture | Source and selection | Transformation |
| --- | --- | --- |
| `ecfr-titles.json` | eCFR titles API; retained 2026-08-24, response date 2026-08-20 | Exact response, including reserved Title 35. |
| `ecfr-api-title1.xml` | eCFR full Title 1, requested 2026-08-10 | First section and its original ancestry; selected header fields retained. |
| `ecfr-api-title14-numbering.xml` | eCFR full Title 14, requested 2026-08-19 | Section `19-8.1` under its original Part `241` ancestry. Source numbering disproves deriving the part from the section prefix. |
| `ecfr-api-part18.xml` | eCFR Title 1, Part 18, requested 2026-07-31 | First two sections under the source PART root, with a shortened first section. |
| `ecfr-api-section18-1.xml` | Same retained Part 18 response | First section under its source PART root, with authority/source metadata. This is an authored subset fixture, not a captured section response. |
| `ecfr-bulk-title1.xml` | GPO `usgpo/bulk-data` commit `83a85170ce0bdd0cf218f6290bd739df8748e2ea`, `ndash-changes-March2024/updated/ECFR-title1.xml` | First section and ancestry; complete original header. |
| `annual-title1-vol1.xml` | [2025 Title 1 volume 1 bulk XML](https://www.govinfo.gov/bulkdata/CFR/2025/title-1/CFR-2025-title1-vol1.xml), captured 2026-09-12 | Front identity fields and first section with ancestry. |
| `annual-title30-vol3-sec716-2.xml` | SpicyRegs commit `a6ab98aa35825ce993023ad9b237a28d04bb153e`, `sample-data/document-files/cfr-xml-short.xml` | Unchanged archived GovInfo section fixture; this archive does not establish current route availability. |
| `annual-title1-edition.xml` | GovInfo 2025 Title 1 volume 1 package MODS, captured 2026-09-12 | Root extension, originInfo and titleInfo elements; nested constituents omitted. |
| `annual-title1-2023-edition.xml` | GovInfo 2023 Title 1 volume 1 package MODS, captured 2026-09-12 | Same extraction; explicitly states `isCoverOnly=false`. |
| `annual-title34-vol4-combined.xml` | GovInfo 2025 Title 34 volume 4 XML, fetched 2026-09-23 (digest in `cfr-ancestry-2026-09-23/fetch.json`) | Title page, both CFRTITLE headings (Title 35 reserved) and the first section with its ancestry, one paragraph kept. |
| `annual-title40-vol9-appendices.xml` | GovInfo 2025 Title 40 volume 9 XML, same fetch | Title page (`Part 60 (Appendices)`), title heading and the first APPENDIX with its ancestry, keeping the first EAR, HD, FP and P. |
| `ancestry/CFR-2025-*.xml` | GovInfo 2025 annual volume XML named by package, fetched 2026-09-23; byte counts and SHA-256 in `corpora/fork-execution-2026-09-21/cfr-ancestry-2026-09-23/fetch.json` | The element path to each selected PART and SECTION only: PARTs keep EAR, HD and RESERVED, SUBPARTs HD, SECTIONs SECTNO, SUBJECT and RESERVED; whitespace-only text is re-indented. |

The API title and roster source receipts are in RefSpec's
`research/evidence/ecfr-authority-notes-2026-08-24/manifest.json`.
The retained Part 18 input is
`corpora/_salvage-2026-08-28/refspec-output/registry-real-data-sources/ecfr-title-1-part-18-full-2026-07-31.xml`.
Its `hierarchy_metadata` retains the publisher's `_SUBSTITUTE_DATE_` placeholder
and differing quote escapes.

The annual volume capture is 814,725 bytes, SHA-256
`443032797d95acd1d1f338e5f6252544b97ec35bd12e6fc0979d3773f9913595`.
The requested 2025 URL returned front matter revised **January 1, 2023**.
The separately captured 2023 bulk URL returned identical bytes. These are
observed source facts. GovInfo's separately captured MODS explicitly identifies
2025 as cover-only, issued 2025-01-01 with original issue date 2023-01-01.
Tests retain the literal body dates without generating a warning or inferring
the edition type from their difference.
Receipts are under `corpora/supply-2026-09-02/receipts/cfr-parser-probe-2026-09-12/`.

MODS receipts are under `corpora/supply-2026-09-02/receipts/cfr-edition-type-2026-09-12/`.

The two `annual-title*-vol*-*.xml` excerpts are cut by `cut_fixtures.py` in
`corpora/supply-2026-09-02/receipts/cfr-annual-validation-2026-09-23/`, beside
the whole-population validation (`validate_population.py`, before and after).
The `ancestry/` excerpts are cut by `cut_fixtures.py` in
`corpora/supply-2026-09-02/receipts/cfr-section-ancestry-2026-09-23/`, which
also retains the whole-population check of `scan_annual_cfr_sections` over the
262 volumes (`population.py`, output `population.json`).
The complete 2025 MODS is 1,342,199 bytes, SHA-256
`6ae66a2ba6939c1c0c307199dcab3ba69aa1e607f3a4640dc58ba17b2aa4ceed`;
the 2023 MODS is 1,342,245 bytes, SHA-256
`0f31dab2324e889e78ae3b8780fe330d4d92ebd2c6fe2001f6a395527a2e3118`.
Both were fetched from `https://www.govinfo.gov/metadata/pkg/CFR-{year}-title1-vol1/mods.xml`.

Source shapes: [GPO annual CFR XML guide](https://github.com/usgpo/bulk-data/blob/main/CFR-XML_User-Guide.md),
[GPO bulk eCFR XML guide](https://github.com/usgpo/bulk-data/blob/main/ECFR-XML-User-Guide.md),
and the retained eCFR API OpenAPI response. Bulk `DLPSTEXTCLASS` and API `ECFR`
are distinct formats. Bulk title identity comes from header `IDNO`; its `DIV1 N`
identifies a volume. API subset dates remain request facts, not inferred XML dates.
