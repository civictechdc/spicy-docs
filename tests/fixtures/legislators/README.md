# Community legislators fixtures

Excerpts of `unitedstates/congress-legislators`, captured keyless 2026-09-19.
These are real records taken verbatim from the publisher's JSON (re-serialized
with `json.dump(..., indent=2)`, so bytes differ from the original file;
values do not) -- a subset, never a capture of a full response.

| Fixture | Source | Full file | Full bytes | Full SHA-256 |
| --- | --- | --- | --- | --- |
| `legislators-current-excerpt.json` | [legislators-current.json](https://unitedstates.github.io/congress-legislators/legislators-current.json) | 2026-09-19 | 1,468,926 | `19b49014bfbfb0defd3bc7b6ba8e279a63931427af9464b0f014a9bfb541ec5d` |
| `legislators-historical-excerpt.json` | [legislators-historical.json](https://unitedstates.github.io/congress-legislators/legislators-historical.json) | 2026-09-19 | 13,483,039 | `25187633f3215a096fe9d14d8a40db1fb0841ab1d24c6da52da3a80c93698cbc` |

The historical full-file byte count and SHA-256 match the 2026-09-18
measurement in `docs/research/legislative-data-map-2026-09-18.md` exactly
(13,483,039 bytes, 12,231 records): the file had not changed between the two
observations.

## What each excerpt keeps and why

`legislators-current-excerpt.json` -- 5 of 539 current records:

| bioguide | Kept for |
| --- | --- |
| `C000127` (Cantwell) | Senator with both `id.lis` and `id.fec`, the ordinary shape. |
| `S000033` (Sanders) | Senator whose `id.fec` holds two congressional ids (House, then Senate), list order preserved. |
| `W000805` (Warner) | Senator whose `id.fec` holds a **presidential** candidate id, `P80003023` -- the shape that has no state letters. This is the record that proves the presidential FEC id shape is not a hypothetical: it is in the *current* file, today. |
| `A000055` (Aderholt) | Ordinary House member: `id.fec` present, no `id.lis` (never a senator). |
| `G000607` (Gallagher) | Freshly seated House member missing `id.wikidata` -- proof that field is genuinely optional, not always present. |

`legislators-historical-excerpt.json` -- 20 of 12,231 historical records:

| bioguide | Kept for |
| --- | --- |
| `B000226` (Bassett) | 1st-Congress senator: no `id.lis`/`id.fec` (predates both), a term with no `district`. |
| `B000546` (Bland) | 1st-Congress representative whose only term has **no `party`** -- parties did not exist yet; a real absence, not a gap. |
| `C000370` (Chipman) | Reconstruction-era D.C. delegate, `type: "rep"`, territory `state: "DC"`. |
| `H000168` (Hanrahan) | Plain modern House member with neither `id.lis` nor `id.fec`. |
| `R000417` (Romero-Barceló) | Puerto Rico resident commissioner, `id.fec` present, no `id.lis`. |
| `M000303` (McCain) | **Former senator** with `id.lis` and `id.fec`, including a presidential id `P80002801`. |
| `B000711` (Boxer) | **Former senator** with `id.lis` and `id.fec` across three offices (Senate, House, President). |
| `M001054` (Moynihan) | Former senator, ordinary `id.lis` + single congressional `id.fec`. |
| `T000254` (Thurmond) | Former senator with the longest `terms` list in the excerpt (decades of service). |
| `H000463` (Helms) | Former senator, ordinary shape. |
| `W000288` (Wellstone) | Former senator, ordinary shape. |
| `M001170` (McCaskill) | Former senator with a presidential `id.fec`, `P80005721`. |
| `G000365` (Gramm) | Former senator whose `id.fec` spans House and Senate ids. |
| `G000333` (Gorton) | Former senator, ordinary shape. |
| `G000367` (Grams) | Former senator with three `id.fec` entries across two chambers. |
| `G000359` (Graham) | **Left office 2026-07-11** -- captured today, 2026-09-19, this is the record the whole crosswalk exists for: a senator whose seat has already turned over, so no publisher file states his `id.lis` (`S293`) any more, only this one. |
| `S001193` (Swalwell) | Recently departed (2026-04-14) House member, single `id.fec`, no `id.lis`. |
| `G000594` (Gonzales) | Recently departed (2026-04-14) House member, single `id.fec`, no `id.lis`. |
| `L000550` (Landrieu) | Former senator with a presidential `id.fec`, `P00003483`. |
| `A000360` (Alexander) | Former senator with a presidential `id.fec`, `P60003225`, and three consecutive Senate terms. |

Between them the two excerpts exercise every shape rule `parse_legislators`
enforces on real data: both `id.fec` shapes, missing `id.lis`, missing
`id.wikidata`, a term with no `party`, and a chamber roster spanning the 1st
Congress to a seat that turned over three months ago.

## Refusal fixtures

Refusal tests in `tests/test_legislators.py` mutate these real records in
memory (drop a field, corrupt an id, duplicate an entry) rather than shipping
separate malformed fixture files; the starting point stays real data.
