# Compiled and historical hearing fixtures

Verbatim GovInfo responses, keyed with `X-Api-Key` as a request header; nothing
here was re-fetched or edited. Every file's SHA-256 equals the digest its
capture recorded. Paths are under `~/Work/corpora/fork-execution-2026-09-21/`.
These U.S. government documents are public domain.

| Fixture | Publisher URL | Captured | Retained capture | SHA-256 |
| --- | --- | --- | --- | --- |
| `CHRG-117shrg56721.mods.xml` | `https://api.govinfo.gov/packages/CHRG-117shrg56721/mods` | 2026-09-24T17:16:19Z | `report-hearing-qualification-2026-09-24/evidence/live/blobs/sha256/d70e6c24…` (capture event in that directory's `journal.jsonl`) | `d70e6c245219100909a81d62958f9836c497a09bd023d4844be9c236e15b57a7` |
| `CHRG-79jhrg79716p11.summary.json` | `https://api.govinfo.gov/packages/CHRG-79jhrg79716p11/summary` | 2026-09-25 | `repair-execution-2026-09-25/hearings/raw/CHRG-79jhrg79716p11.summary.json` (listed in `hearings/source-http.json`) | `0a6132ecd83157817e5dd057ef406cc3df28fb45ad819e8d286fcef815aa2529` |
| `CHRG-79jhrg79716p11.mods.xml` | `https://api.govinfo.gov/packages/CHRG-79jhrg79716p11/mods` | 2026-09-25 | `repair-execution-2026-09-25/hearings/raw/CHRG-79jhrg79716p11.mods.xml` | `09b2ff255032c2e6bd4d1a94ec4c3896fa98c957e60e4f3db367b9536f0b1a5b` |
| `CHRG-79jhrg79716p19.summary.json` | `https://api.govinfo.gov/packages/CHRG-79jhrg79716p19/summary` | 2026-09-25 | `repair-execution-2026-09-25/hearings/raw/CHRG-79jhrg79716p19.summary.json` | `f36f72f1477f01c17587715829a3860823b6f8d8b49fdc70db79e8080efcb429` |
| `CHRG-79jhrg79716p19.mods.xml` | `https://api.govinfo.gov/packages/CHRG-79jhrg79716p19/mods` | 2026-09-25 | `repair-execution-2026-09-25/hearings/raw/CHRG-79jhrg79716p19.mods.xml` | `6aa38685f1d907a833e3e4c85f6268dca076487d097d512a1b7e6f0b65196db9` |

`CHRG-117shrg56721` is a compiled volume: its MODS states eleven distinct
`heldDate`s and one `COVER` bill. The two `CHRG-79jhrg79716` volumes are Pearl
Harbor attack hearings the retained CHRG listing of the 2026-09-24 report
qualification named (`report-hearing-qualification-2026-09-24/README.md`); each
summary's `packageId` and MODS `accessId` state the suffixed id, and each MODS
offers only a PDF. No body of either was fetched.

Offline tests establish behavior for these records as captured, not coverage
or continuing availability.
