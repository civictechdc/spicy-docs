# House committee activity report fixtures

Two of the eight House committee activity reports the
[PDF-family rollup](../../../docs/research/pdf-family-rollup-yield-2026-09-20.md)
read on 2026-09-20, plus the keyed GovInfo records that state what its
`published` listing row does not. These U.S. government documents are public
domain.

**Nothing here was re-fetched from the publisher's document route.** The text
is rebuilt from the PDF bytes that measurement retained, and
`build-fixtures.py` asserts the rebuilt text is byte-identical to the extract
it retained beside them. The summary and MODS are the only new acquisition:
four keyed requests, receipt
`corpora/supply-2026-09-02/receipts/document-citations-2026-09-20/`.

Offline tests establish behavior for these two documents on the day they were
captured; they establish neither family coverage nor continuing live
availability.

| Fixture | What it is | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `CRPT-118hrpt968.txt` | The normalized text of the Foreign Affairs activity report, 56 pages of 56 — `DocumentExtractor(NativeText())` then `normalize_gpo_pages`, pages joined with one `\n`. Byte-identical to the rollup receipt's own `extract/house_activity-CRPT-118hrpt968.txt`, and its digest is the `text_sha256` that measurement's sidecar states. | 141,125 | `f2c52f60c527c27c0ef6389cf4f2fbb94c5cedd7ba5cfe3632d459dd7ad915f7` |
| `CRPT-118hrpt968.json` | Provenance: the `published` index row, the source PDF's digest and size, the text digest, the per-page character lengths that rejoin to the text, the GPO cleanup counts, and both receipts. | 2,154 | `2cbb66afae510974f4c3baaf630890288333136f4946fbe824a6bbec46195329` |
| `summary-CRPT-118hrpt968.json` | verbatim: `api.govinfo.gov/packages/CRPT-118hrpt968/summary` | 6,360 | `115cd1bb1029f661e8dc3be172de9cb2e825306e69b36e9cf076a878b0e51ada` |
| `mods-CRPT-118hrpt968.xml` | **reduced** (see below): `api.govinfo.gov/packages/CRPT-118hrpt968/mods`, 100,652 bytes, `sha256:40990b6a7275d2ae3c760ad57e9ee2154a03bab6835f385f8b599022303f1210` | 27,382 | `7e543d6ec56eb255660410a44fc34f3f120623fa400212ac0dae44d8500b125d` |
| `CRPT-118hrpt965.txt` | The Energy and Commerce activity report, **60 pages of 282** — a capped read, which is what makes it the second fixture. | 124,467 | `3878beee22ee5e2a84a728c4fd2ccc401649fd11852e62659a4143ea066dd723` |
| `CRPT-118hrpt965.json` | As above. | 2,229 | `27e8b845a3be145831bbca83d1433be4a42ae603c677a70ca5241ad4da027dd4` |
| `summary-CRPT-118hrpt965.json` | verbatim: `api.govinfo.gov/packages/CRPT-118hrpt965/summary` | 1,357 | `8c83a72f4c6116b51aeccfe4a39f178414c41dbfcc3db4f474f8a2e37be216c8` |
| `mods-CRPT-118hrpt965.xml` | **reduced**: `api.govinfo.gov/packages/CRPT-118hrpt965/mods`, 191,584 bytes, `sha256:fddafcb80e56c487a12beaddf2f261435c949fc507aa3879a25c1cb7ee8506c8` | 38,690 | `41b83999b850c0ae083c8c2715498aa9d3f5f54f2565f7e820fcfa842da1fcd7` |

## The MODS reduction, stated exactly

Everything before the first `<relatedItem>`, then `</mods>`. Nothing inside
the kept span was rewritten. What is dropped is the per-granule constituent
records — 198 for -118hrpt968, 413 for -118hrpt965 — which
`validate_package_mods` does not read: it reads only the **root's own**
`extension` children, the same boundary `_mods_bills` draws. The kept span is
therefore everything the reader under test looks at, and it still carries all
179 (resp. 380) root-level `<bill>` elements, all 6 (resp. 16) `<law>`
elements, both `<USCode>` blocks (one section, one chapter-only), the 11
(resp. 15) `<congReport>` elements, the `<congMember role="SUBMITTEDBY">`, the
`<congCommittee>` and the `<session>`. Both full digests and the dropped
counts are in each `.json` sidecar.

## Why these two

`CRPT-118hrpt968` is the report the 2026-09-20 rollup sidecar's own per-document
numbers are quoted against: 179 distinct bills, 3 public laws, 9 printed
committee candidates of which 8 occurrences settle to a `system_code`.
`tests/test_citations.py` reproduces all of them from this text.

`CRPT-118hrpt965` is a 60-page read of a 282-page print, so it is what
exercises `pages_capped` and what shows a MODS naming 380 bills and
`15 U.S.C. 57a` where the capped read sees 39 bills and no Code section. It is
also the package whose `<congMember role="SUBMITTEDBY">` carries **no**
`bioGuideId`, which is what stops the contract from assuming the role implies
one; -118hrpt968's states `M001157`.

Between them the two cover both sides of every MODS reader: a `<USCode>`
section and a chapter-only block, a submitter with and without an id, a
complete read and a capped one.

**What they cannot show.** Neither reaches a RIN or an agency docket, which
the [MODS re-check](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
found to be this family's two largest genuinely-new kinds (87 and 38 across
the eight reports). Both sit in oversight chapters past the 60-page cap the
rollup read to, so these fixtures exercise the contract's shape for those
kinds and nothing about their content. Neither states a `<cfr>`, a
`<statuteAtLarge>` or a `<rin>` element either; those readers are exercised on
inline markup in `tests/test_citations.py`, with the element shapes taken from
the collections that do carry them.

## Rebuild

`build-fixtures.py` in the receipt directory, from retained bytes only:

```sh
uv run --frozen python ~/Work/corpora/supply-2026-09-02/receipts/document-citations-2026-09-20/build-fixtures.py
```

## `grammar-specimens.jsonl`

266 Federal Register titles and abstracts, one JSON object per line
(`{"id": "<document_number>@<publication_date>", "text": ...}`), copied
unchanged from the parsing survey's retained input
`corpora/fork-execution-2026-09-21/parsing-survey-2026-09-23/citations/in/fr_text.jsonl.gz`
(`sha256:1ee21de8bf2ab6ced188bd5bea953790a39e68026cda50da66d848bd65912cb2`).
Public-domain government text; nothing was fetched.

Chosen by a fixed rule, so the file is rebuilt rather than hand-edited: for
each of twenty shapes the grammar kinds were changed for (a CFR part or
section before its heading, a space after a part's inner hyphen, every case of
"Part", a `through` range, a reversed "part N of title N", a doubled or
one-sided dash between Code sections, a Code range, appendix and trailing
period, a zero-padded law number, a spaced law separator, an unspaced
Statutes cite, `FR` and comma-paged `Fed. Reg.` cites, RIN lists and
unlabelled RINs, long dockets and ITC investigation numbers), the first eight
texts carrying it in corpus order; then 120 more, sampled with seed 20260923
from the texts in which the grammar kinds read anything. Builder, command and
output: receipt `corpora/supply-2026-09-02/receipts/b4-citation-grammar-2026-09-23/`.

`tests/test_citations.py` pins what each grammar-read kind reads over this
file, both activity reports and both budget volumes, at that kind's rule
version: a change inside `citation_grammar` or `identifier_shapes` shows there
and names the version to move.

| Fixture | Bytes | SHA-256 |
| --- | --- | --- |
| `grammar-specimens.jsonl` | 310,429 | `cee8ddc31d8206b298366282dff4ce8811f61d60ef7667f9e0cac2f5a474b73e` |
