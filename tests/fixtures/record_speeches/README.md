# Congressional Record speech-turn fixtures

Three whole GovInfo CREC granule bodies, one granule's own MODS from two routes,
and bounded excerpts of the two issue package MODS, all retrieved
**2026-09-28**. The bodies and package MODS come from the @unitedstates reuse
review (receipt
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-legal-record-2026-09-28/record-inputs/`;
URLs and full-file digests in the workspace's
`docs/unitedstates-review-2026-09-28/validation/legal-record/current-record-sources.json`);
the granule MODS from their own retrieval, below.
These U.S. government documents are public domain. `provenance.json` records
every fixture's source URL, bytes and SHA-256, and each excerpt's method, kept
byte ranges and their digests; a test re-checks all of it.

**Bodies are whole and unedited.** Each `.htm` is the granule exactly as
`content/pkg/{package}/html/{granule}.htm` served it.

| Fixture | Bytes | SHA-256 | What it pins |
| --- | --- | --- | --- |
| `CREC-2026-09-16-pt1-PgH5835-8.htm` | 2,304 | `40bbfd5f…3b7` | A House one-minute: an item upstream leaves `Unknown`, one speech by Mrs. KIGGANS of Virginia with the MODS-stated bioguide `K000399`, a closing rule |
| `CREC-2026-09-17-pt1-PgH5987-5.htm` | 819 | `b53d3466…eb7` | A procedural granule: the Speaker pro tempore's speech carries no person id |
| `CREC-2026-09-17-pt1-PgS4765-6.htm` | 71,137 | `c7040cde…ff1` | A Senate granule: 56 speech turns, presiding-officer turns with no id, and line spans that step over `[[Page]]` markers and whitespace-only lines |

**The Kiggans granule's own MODS, twice, whole.** Retrieved 2026-09-28 by
`retrieve.py` in
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/granule-mods/`,
beside its `receipt.json`:

| Fixture | Route | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `CREC-2026-09-16-pt1-PgH5835-8.granule-mods.xml` | keyless, [`metadata/granule/CREC-2026-09-16/CREC-2026-09-16-pt1-PgH5835-8/mods.xml`](https://www.govinfo.gov/metadata/granule/CREC-2026-09-16/CREC-2026-09-16-pt1-PgH5835-8/mods.xml), through `BoundedHttpCapture` configured as `GovInfoBodyAcquirer`'s keyless client | 6,432 | `45e6c589…bee` |
| `CREC-2026-09-16-pt1-PgH5835-8.granule-mods-api.xml` | keyed `packages/CREC-2026-09-16/granules/CREC-2026-09-16-pt1-PgH5835-8/mods`, the capture `GovInfoBodyAcquirer.acquire_granule` retains; the key travelled in the `X-Api-Key` header only | 7,833 | `9a087936…323` |

The two differ only in whitespace and namespace-declaration order. The keyless
response passes `validate_granule_mods`, and the body `acquire_granule` fetched
in the same run is byte-identical to `CREC-2026-09-16-pt1-PgH5835-8.htm`. Read
against either, the Kiggans granule gives the adapter's package-MODS document
apart from `mods_sha256`.

**The package MODS are excerpts, not captures.** The originals are 3,645,061 bytes
(`CREC-2026-09-16`, SHA-256 `1aea2f0c…c1b`) and 993,858 bytes
(`CREC-2026-09-17`, `257ff371…ecb`), too large to commit. Each excerpt keeps:

- the original bytes up to the first top-level `<relatedItem>`: the `<mods>`
  start tag and all top-level metadata, including the package `accessId` the
  adapter reads (in both originals every metadata element precedes the
  relatedItems);
- only the top-level `<relatedItem>` whose `accessId` is a fixture granule,
  whole and byte-identical;
- the original's tail after its last top-level element (`\n</mods>`).

Kept relatedItems are joined by the whitespace the original puts between two
of them. Nothing inside a kept span is edited, so some identifiers in the
package metadata name constituents the excerpt no longer carries.

**Why the excerpt is enough.** Upstream reads the MODS root once, to find the
`accessId` equal to the granule's id; everything else it reads is inside that
element's parent. Run at the pin against the full MODS and against the excerpt,
upstream's document, speaker table and completion flag were equal for all
three granules, and the adapter's documents differed only in `mods_sha256`.
The cutting and comparison scripts and their output are retained under
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/excerpt/`.

Offline fixtures establish behavior for these shapes. They establish neither
coverage of other eras nor the parser's accuracy across the Record.
