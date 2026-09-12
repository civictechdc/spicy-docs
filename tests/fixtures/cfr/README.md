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
observed source facts; their cause is unverified. Tests retain the literal dates
and report the difference without equating a URL year to a verified body edition.
Receipts are under `corpora/supply-2026-09-02/receipts/cfr-parser-probe-2026-09-12/`.

Source shapes: [GPO annual CFR XML guide](https://github.com/usgpo/bulk-data/blob/main/CFR-XML_User-Guide.md),
[GPO bulk eCFR XML guide](https://github.com/usgpo/bulk-data/blob/main/ECFR-XML-User-Guide.md),
and the retained eCFR API OpenAPI response. Bulk `DLPSTEXTCLASS` and API `ECFR`
are distinct formats. Bulk title identity comes from header `IDNO`; its `DIV1 N`
identifies a volume. API subset dates remain request facts, not inferred XML dates.
