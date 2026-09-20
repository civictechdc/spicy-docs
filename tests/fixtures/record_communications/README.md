# Congressional Record executive-communications fixtures

Bounded excerpts of GovInfo CREC granule bodies, cut from the retained bytes of
the [executive-communications backfill
research](../../../docs/research/executive-communications-backfill-2026-09-20.md)
(receipt `~/Work/corpora/supply-2026-09-02/receipts/executive-communications-backfill-2026-09-20/`,
retrieved **2026-09-20** through `GovInfoBodyAcquirer.acquire_granule`). These
U.S. government documents are public domain.

**Excerpts, not bodies.** Each file keeps the granule's real HTML frame — the
`<pre>` block GovInfo serves, its `[Congressional Record Volume …]` header, the
`EXECUTIVE COMMUNICATIONS, ETC.` heading and the introductory clause — and a
few whole printed entries out of the dozens the granule carries. Entries were
selected for the behaviour each one pins, never edited: every entry below is
byte-identical to the granule's own bytes, and the only removal inside a kept
span is the section's closing rule line, which is re-added once at the end.

| Fixture | Granule | Entries kept | What each pins |
| --- | --- | --- | --- |
| `CREC-2016-02-12-pt1-PgH815-4.excerpt.htm` | `CREC-2016-02-12-pt1-PgH815-4` | 4329, 4335, 4340, 4350 | The two publisher ground truths (4329, 4350), GPO's mid-sentence `[[Page H816]]` marker (4335), and a from-clause the split rule refuses (4340, *General Counsel, Peace Corps*) |
| `CREC-2008-06-11-pt1-PgH5326-4.excerpt.htm` | `CREC-2008-06-11-pt1-PgH5326-4` | 7093, 7094 | An entry citing **no** authority (7093) beside one that does, and an `Office of …` from-clause the split rule refuses (7094) |
| `CREC-2004-06-16-pt1-PgH4278.excerpt.htm` | `CREC-2004-06-16-pt1-PgH4278` | 8566, 8569 | An entry with no official before the agency (8566) and a joint referral to two committees whose names contain `and` (8569) |
| `CREC-2004-06-16-granules.excerpt.json` | `packages/CREC-2004-06-16/granules` | 13 of 228 | The day that prints the House section **twice** (`pt1-PgH4278` and `pt2-PgH4285`), beside the Senate granules whose titles also say "executive" and must not be taken |

The two publisher decompositions these are scored against are whole, unedited
responses and live with the other Congress.gov captures:
`tests/fixtures/listings/congress-house-communication-detail-114-ec-4329.json`
and `…-4350.json` (`house-communication/114/EC/{number}`, keyed with
`X-Api-Key`, retrieved 2026-09-20). No credential appears in any file here; the
keyless body route takes none and the keyed detail route carries it in a header.

Offline fixtures establish behaviour for these shapes. They establish neither
coverage of the era nor continuing live availability.
