# Budget volume fixtures

Two of the eight volumes of the President's budget the
[PDF-family rollup](../../../docs/research/pdf-family-rollup-yield-2026-09-20.md)
retained on 2026-09-20, plus the keyed GovInfo records the
[MODS re-check](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
compared them against. These U.S. government documents are public domain.

**Nothing here was re-fetched from the publisher's document route.** The text
is rebuilt from the PDF bytes that measurement retained, through the same
extractor and normalizer the re-check's `uncapped` phase used, imported from
the tool rather than restated. The two package summaries are the only new
acquisition — the re-check fetched MODS only — two keyed requests inside a
four-request bound, receipt
`corpora/supply-2026-09-02/receipts/budget-volumes-2026-09-20/`.

Offline tests establish behavior for these two volumes on the day they were
captured; they establish neither family coverage nor continuing live
availability.

| Fixture | What it is | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `BUDGET-2026-MSR.txt` | The normalized text of the FY2026 Mid-Session Review, **16 pages of 16** — `DocumentExtractor(NativeText())` then `normalize_gpo_pages`, pages joined with one `\n`. Byte-identical to the rollup receipt's own `extract/budget-BUDGET-2026-MSR.txt`, which is the same read because the volume is shorter than that measurement's 60-page cap. | 27,235 | `c5cb60c3e33ea5a2893abaaed48b6b5e8a9a844242182beeeb200f469e43dca4` |
| `BUDGET-2026-MSR.json` | Provenance: the source PDF's URL, digest and size, the text digest, the per-page character lengths that rejoin to the text, the page range, the GPO cleanup counts, both records' digests and all three receipts. | 1,489 | `8c03fac8ae2db5b9c493a1cc9211b196fd0b16c5e504de0e6bf4db73252b2dab` |
| `summary-BUDGET-2026-MSR.json` | verbatim: `api.govinfo.gov/packages/BUDGET-2026-MSR/summary` | 2,354 | `c28161989a2a2833c36c32a80eb24bd8114e554298252b956d572feeaf050c5c` |
| `mods-BUDGET-2026-MSR.xml` | **reduced** (see below): `api.govinfo.gov/packages/BUDGET-2026-MSR/mods`, 7,403 bytes, `sha256:26673c13d09ca221740a0a8630a01f73d14e21f05e38da9b9bbabb2abf98fd07` | 6,072 | `05e2eb1ce0ae5d67dbad04c8ac2b53ba7c4feb294f71ab728473e995463f6c2e` |
| `BUDGET-2027-BUD.txt` | The FY2027 *Budget of the U.S. Government*, **92 pages of 92** — longer than the re-check's cap, which is what makes it the second fixture. | 214,775 | `28f6ac286e541a83a1d17a2d1ec97252313912f872de2dfc5face22772e3f4d0` |
| `BUDGET-2027-BUD.json` | As above. | 2,210 | `f3f6e9373bace11260bd49b4e205df6197c79dc4b117fcc6b2cd7322e794dfa7` |
| `summary-BUDGET-2027-BUD.json` | verbatim: `api.govinfo.gov/packages/BUDGET-2027-BUD/summary` | 1,748 | `7f7685aa803dfb90edaa09deb0c334acb6ae824e5d80756c257c89744ed31afd` |
| `mods-BUDGET-2027-BUD.xml` | **reduced**: `api.govinfo.gov/packages/BUDGET-2027-BUD/mods`, 36,851 bytes, `sha256:41c456be3fc5c034c15aee49482c3024a03cd0b2218c1152d18fe721d3d2d11e` | 5,509 | `683867d906f11cd2d8f9b272e1a9ce664a5777e223df88068a005eed91a37017` |

## Why each volume is read whole

The brief asked for bounded excerpts, and both of these come in under the
400 KB bound *whole*. That is better than a cut, and for one reason: a
page-range excerpt would reproduce no published number, while each of these
reproduces a real per-document row of the re-check, so the fixture counts can
be held against a measurement instead of against themselves.

`BUDGET-2026-MSR` is 16 pages, so the re-check's 60-page cap never bit and its
`recheck.json` and `uncapped.json` rows are the same row: 1 printed public law
and 1 printed U.S. Code section, **neither of them print-only**, because its
MODS states both. That is the `stated_by_index = true` side, and
`tests/test_budget_volumes.py` reproduces all four numbers.

`BUDGET-2027-BUD` is 92 pages, so the cap **did** bite, and the two published
rows disagree — `recheck.json` states 2 printed public laws and `uncapped.json`
states 3. The uncapped row is the right one for this text, and not as a
judgement call: the capped row is a 60-page read of a 92-page volume, a capped
read can only understate what a print names, and the third law
(`Public Law 119-21`) is printed past page 60. The test asserts both numbers so
the difference is a stated fact. This volume's MODS states **no `<law>` at
all**, so all three printed laws are print-only and every row carries `false`
— "compared, and the index does not state it" — which is the yield the revised
build order leads with.

## The MODS reduction, stated exactly

Everything before the first `<relatedItem>`, then `</mods>` — the same
reduction the [activity-report fixtures](../document_citations/README.md) use,
and for the same reason: `validate_package_mods` reads only the **root's own**
`extension` and `location` children, so a constituent's record is bytes the
reader under test never looks at. What is dropped is 2 constituent records for
-2026-MSR and 24 for -2027-BUD. The builder does not assume that: it validates
the full and the reduced bytes and compares the access ids, collection code,
offered formats, other renditions, fiscal year, bills, laws, Code sections,
CFR parts and Statutes, and refuses if any of them moved.

## What these fixtures cannot show

- **Neither exercises a capped read.** Both are read whole, so `pages_capped`
  is `false` on both rows; the capped path is exercised by
  `house_activity_reports`' CRPT-118hrpt965 fixture (60 pages of 282).
- **Neither reaches a `<cfr>` part or a `<statuteAtLarge>`.** The volumes that
  do are `BUDGET-2027-APP` (39 `<cfr>` blocks, 182 Statutes pages, a 2.8 MB
  MODS and 1,340 pages) and `BUDGET-2027-PER`; both are too large to commit.
  Those readers are exercised on inline markup in `tests/test_citations.py`,
  with the element shapes taken from the collections that do carry them.
- **Neither prints a bill.** The bill kind's whole point on this family is that
  it is *not comparable* — a budget volume states no Congress — and
  `tests/test_budget_volumes.py` asserts that on a one-line text rather than
  on a volume that happens to print one.

## Rebuild

`build-fixtures.py` in the receipt directory, from retained bytes only:

```sh
PYTHONPATH=. uv run --frozen --extra pdf python \
    ~/Work/corpora/supply-2026-09-02/receipts/budget-volumes-2026-09-20/build-fixtures.py
```
