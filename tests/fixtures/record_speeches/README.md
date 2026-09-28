# Congressional Record speech-turn fixtures

Whole GovInfo CREC granule bodies, granules' own MODS, and bounded excerpts of
two issue package MODS, all retrieved **2026-09-28**. The September 2026 bodies and
package MODS come from the @unitedstates reuse review (receipt
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-legal-record-2026-09-28/record-inputs/`;
URLs and full-file digests in the workspace's
`docs/unitedstates-review-2026-09-28/validation/legal-record/current-record-sources.json`);
the granule MODS and the suffixed issue's granule from their own retrieval,
below.
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

**A granule of a suffixed issue, whole.** GovInfo addresses the Record's split
days as separate packages with a `-v{N}` or `-i{N}` suffix, and spells their
granule ids without it: package `CREC-2025-03-11-i46` holds
`CREC-2025-03-11-pt1-PgS1677-4`. Both files were retrieved 2026-09-28 by
`retrieve.py` through `GovInfoBodyAcquirer.acquire_granule` (keyed summary and
MODS, the key in the `X-Api-Key` header only; keyless body), in
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/review-fixes/suffixed-fixture/`
beside its `receipt.json`, and are committed unedited:

| Fixture | Route | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `CREC-2025-03-11-pt1-PgS1677-4.htm` | keyless `content/pkg/CREC-2025-03-11-i46/html/CREC-2025-03-11-pt1-PgS1677-4.htm` | 632 | `7f068d44…8ab` |
| `CREC-2025-03-11-pt1-PgS1677-4.granule-mods-api.xml` | keyed `packages/CREC-2025-03-11-i46/granules/CREC-2025-03-11-pt1-PgS1677-4/mods` | 7,440 | `05687877…795` |

It pins Mr. THUNE with the MODS-stated bioguide `T000250`, the Acting
President pro tempore with none, a closing rule, and `package_id`
`CREC-2025-03-11-i46`, the id its host `relatedItem` states.

**A 1994 granule, whole.** In 1994 GovInfo states no page number: the body's
header reads `[Page H]`, the MODS `<start>H</start>`, and the number in an id
such as `-PgH10` orders the section's granules. Both files were retrieved
2026-09-28 by `retrieve.py` through `GovInfoBodyAcquirer.acquire_granule`
(keyed summary and MODS, the key in the `X-Api-Key` header only; keyless body),
in
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/rereview-fixes/fixture-1994/`
beside its `receipt.json`, and are committed unedited:

| Fixture | Route | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `CREC-1994-03-25-pt1-PgH10.htm` | keyless `content/pkg/CREC-1994-03-25/html/CREC-1994-03-25-pt1-PgH10.htm` | 36,431 | `5f423341…5d3` |
| `CREC-1994-03-25-pt1-PgH10.granule-mods-api.xml` | keyed `packages/CREC-1994-03-25/granules/CREC-1994-03-25-pt1-PgH10/mods` | 7,688 | `3f5049b1…a46` |

It pins that a header with no page number is held to its section only, Mr.
NICKLES and Mrs. KASSEBAUM with their MODS-stated bioguide ids, and a presiding
officer's turn with none. Its volume 140, No. 36 is also what tells it from a
body of another issue filed under a 2026 id.

**A 1995 granule, whole.** GovInfo's 1995 text opens some lines of prose with a
page marker: `[[Page S573]] not have, he said: ...`. Both files were retrieved
2026-09-28 by `retrieve.py` through `GovInfoBodyAcquirer.acquire_granule`
(keyed summary and MODS, the key in the `X-Api-Key` header only; keyless body),
in
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/rereview-fixes/fixture-1995/`
beside its `receipt.json`, and are committed unedited; the body equals the
re-review's separate keyless GET of the same URL:

| Fixture | Route | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `CREC-1995-01-06-pt1-PgS572-2.htm` | keyless `content/pkg/CREC-1995-01-06/html/CREC-1995-01-06-pt1-PgS572-2.htm` | 2,043 | `36aab96a…3c8` |
| `CREC-1995-01-06-pt1-PgS572-2.granule-mods-api.xml` | keyed `packages/CREC-1995-01-06/granules/CREC-1995-01-06-pt1-PgS572-2/mods` | 7,647 | `de8e2968…fc6` |

It pins that the prose after the marker is text of Mr. SIMON's speech
(bioguide `S000423`), located on the marker's line, with nothing unaccounted,
and a line-leading `<bullet>`.

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

**Why the excerpt is enough.** Upstream finds the `accessId` equal to the
granule's id (by an index of the MODS's accessIds, built once); everything else
it reads is inside that element's parent. Run against the full MODS and against
the excerpt, upstream's document, speaker table and completion flag were equal
for all three granules, and the adapter's documents differed only in
`mods_sha256`, at the first pin and again at the current one. The cutting and
comparison scripts and their output are retained under
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/record-speeches/excerpt/`
and, for `3715651` and the current pin, `review-fixes/repin-3715651a/excerpt-check/` and
`rereview-fixes/repin-ee5ba237/excerpt-check/` beside it.

**Expectations are the parser's at `PARSER_PIN`.** The tests' readings were
re-derived from the pinned parser each time the pin moved. Moving it to
`3715651` (#94 and #90) changed one field of the adapter's output on these
fixtures: `speaker` on rules and titles, and in `source_item`, is `None` where
it was the string `"None"`; items, kinds, texts, spans, `unaccounted_lines` and
every other field are unchanged (`review-fixes/repin-3715651a/fixture-compare/`).
Moving it to `ee5ba237` changed only the 1995 fixture: its recovered line joins
Mr. SIMON's `text` and `source_item`, and its `unaccounted_lines` goes from one
line to none (`rereview-fixes/repin-ee5ba237/fixture-compare/`).

Offline fixtures establish behavior for these shapes. They establish neither
coverage of other eras nor the parser's accuracy across the Record.
