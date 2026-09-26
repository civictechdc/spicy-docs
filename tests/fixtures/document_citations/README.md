# Committee activity report fixtures

`a10-regressions.json` retains source snippets and expected keys from the
September 24 print-citations audit. Each example names its GovInfo package.
The full texts, source digests and original span observations are under
`~/Work/corpora/fork-execution-2026-09-21/drift-audit-2026-09-24/print-citations/`;
the extraction is recorded in `spot-check.json`. These snippets also
participate in the per-kind grammar digest in `tests/test_citations.py`.

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

## `grammar-specimens.jsonl` (frozen)

266 Federal Register titles and abstracts, one JSON object per line
(`{"id": "<document_number>@<publication_date>", "text": ...}`), copied
unchanged from the parsing survey's retained input
`corpora/fork-execution-2026-09-21/parsing-survey-2026-09-23/citations/in/fr_text.jsonl.gz`
(`sha256:1ee21de8bf2ab6ced188bd5bea953790a39e68026cda50da66d848bd65912cb2`).
Public-domain government text; nothing was fetched.

**Frozen.** The file is chosen without the grammar it pins, so rebuilding it
with any version of the grammar builds these same bytes, and a rule that
starts or stops reading text shows as a moved digest rather than as a moved
sample. It is not rebuilt to follow the code. The rule: for each of twenty
shapes the grammar kinds were changed for, found by plain regular
expressions in the builder (a CFR part or section before its heading, a
space after a part's inner hyphen, every case of "Part", a `through` range,
a reversed "part N of title N", a doubled or one-sided dash between Code
sections, a Code range, appendix and trailing period, a zero-padded law
number, a spaced law separator, an unspaced Statutes cite, `FR` and
comma-paged `Fed. Reg.` cites, RIN lists and unlabelled RINs, long dockets
and ITC investigation numbers), the first eight texts carrying it in corpus
order; then 120 more drawn with seed 20260923 from every other retained id.
Builder, command and output: receipt
`corpora/supply-2026-09-02/receipts/b4-citation-grammar-2026-09-23/`
(`uv run --frozen python build_grammar_specimens.py <out>`).

`tests/test_citations.py` pins what each grammar-read kind reads over this
file, both activity reports and both budget volumes, at that kind's rule
version: a change inside `citation_grammar` or `identifier_shapes` shows there
and names the version to move.

| Fixture | Bytes | SHA-256 |
| --- | --- | --- |
| `grammar-specimens.jsonl` | 298,203 | `7fbfd98619e2b6c1190ea1cf70aaf7a4e0fdcdbde0f77ca0f7ce23e431b6c6ed` |

## The 2026-09-26 print-citations audit (`print-citations-2026-09-26.json`, `mods-CRPT-118srpt99.xml`)

The drift audit in
`corpora/fork-execution-2026-09-21/drift-qualification-2026-09-26/bills-citations/`
found Senate activity reports -- filed in the Congress after the one they
cover -- publishing their bills in the filing Congress, and two bill misreads.
Receipt: `corpora/supply-2026-09-02/receipts/fix-print-citations-2026-09-26/`
(`build_fixtures.py` writes both files from retained bytes only; nothing was
re-fetched for them). Public-domain government text.

- **`covered`**: four of the 40 reports in the print-citations window, one per
  path through `activity_reports.covered_congress` -- CRPT-118srpt99 and
  CRPT-118srpt3 (title), CRPT-118srpt1 (cover), CRPT-118hrpt941 (front matter)
  -- each with its published index title and its first five pages of
  normalized text, cut from the full text whose digest (`text_sha256`) equals
  the published `house_activity_reports.text_sha256`. `pdf_sha256` names the
  PDF it was derived from: the audit's own native read for -118srpt99 and
  -118srpt3, this receipt's keyless fetch (`fetch-ledger.json`) for the others.
  `expected` is the Congress each report covers, checked two ways over all 40
  (`check_covered.py`): the reader's answer, and the chamber rule that a House
  report is filed in the Congress it covers and a Senate report in the next.
- **`bill_snippets`**: the two misreads (`CLAUSE S 2(N)` in CRPT-117hrpt702 and
  `S. Con. Res.\n2022:` in CRPT-117hrpt708) and the true readings nearest each
  refusal -- year-shaped numbers wrapped under their designator, a colon after
  an unwrapped number, and CRPT-118srpt99's `H.R. 5376`. Each is a whole-line
  slice `[span_start, span_end)` of the text its `text_sha256` names; `keys`
  lists every bill the slice names, stated by reading it.
- **`committee_snippets`**: four lines naming a committee with its chamber
  (`Senate Committee on Armed Services` in CRPT-118hrpt961, beside the House
  one; `the Senate Committee on Appropriations` in -117hrpt702; `The Senate
  Committee on Homeland Security` in -117hrpt705; `U.S. House Committee on
  Transportation` in the Senate report -119srpt29), each a whole-line slice of
  the text its `text_sha256` names, with the report's chamber. `keys` are the
  `committee_name` findings in order, stated by reading them against the
  pinned roster excerpts in `../congress_rosters/` -- which reach no Senate
  Homeland Security and Governmental Affairs, so that line is unresolved here
  and `ssga00` with the full roster.
- **`mods-CRPT-118srpt99.xml`**: **reduced** exactly as the two MODS above --
  everything before the first `<relatedItem>`, then `</mods>`, 62 constituent
  records dropped -- from
  `https://www.govinfo.gov/metadata/pkg/CRPT-118srpt99/mods.xml` (32,601 bytes,
  `sha256:775f4aac44924271b8d284cfb40372008cb942e5e5503ec60746d90c9f0002a9`).
  Its 34 root `<bill>` elements, H.R. 5376 among them, all state
  `congress="118"` for a report on the 117th.

| Fixture | Bytes | SHA-256 |
| --- | --- | --- |
| `print-citations-2026-09-26.json` | 34,622 | `6bb85994ce3e78e5406796ae9f1d61c99bc1742cda93bff5aaad7d356bca6748` |
| `mods-CRPT-118srpt99.xml` | 11,679 | `824fe705c4ab450ca53f98ad4a53682daeb0a4d59c5b1a22835ae9493bfd481f` |

## Congress subheadings (`print-subheadings-2026-09-26.json`)

`bill_number` 004 keys a bill printed under a Congress subheading (`116th
Congress` over a predecessor bill's history) in that Congress, until the next
bill entry. Receipt:
`corpora/fork-execution-2026-09-21/print-subheading-2026-09-26/`
(`build_fixtures.py` writes this file from the retained texts of
`supply-2026-09-02/receipts/fix-print-citations-2026-09-26/texts.pkl`, whose
digests equal the published `text_sha256`; nothing was fetched). Public-domain
government text.

`subheading_snippets` are whole-line slices `[span_start, span_end)` of the
text their `text_sha256` names, each with the report's covered Congress and a
`why`: a subheading ended by another and then by an entry heading naming a
law (CRPT-117hrpt705), the join-gaps orphan `117-hr-5119` between its entry and
the next (-117hrpt705), two earlier bills restated as their paragraphs'
subjects under one subheading (-118hrpt974), two committee-history sections
with their law tables (-118hrpt967), `Prior Congresses` (-117hrpt705) and a
wrapped heading's tail that is no subheading (-117hrpt709). `keys` lists every
bill each slice names, in order, read from the slice rather than by running the
rule. `bill_number` 005 re-read the `Prior Congresses` snippet (which no longer
ends the scope, and whose bills state their Congress inline) and dropped its
`floor`: receipt `print-inline-congress-2026-09-26/build_fixtures.py`.

| Fixture | Bytes | SHA-256 |
| --- | --- | --- |
| `print-subheadings-2026-09-26.json` | 19,298 | `09585abcdb1f6877c4953250bb5ca900a9f647139a2ce94f98b310eaa8e76c3c` |

## A Congress set beside a bill (`print-inline-congress-2026-09-26.json`)

`bill_number` 005 keys a bill the print qualifies with its own Congress (`H.R.
6752, 115th Cong.`, `S. Res. 400 of the 94th Congress`, `H.R. 8528 (117th
Congress)`) in that Congress, ahead of any subheading over it. Receipt:
`corpora/fork-execution-2026-09-21/print-inline-congress-2026-09-26/`
(`build_fixtures.py`, from the same retained texts; nothing was fetched).
Public-domain government text.

`inline_snippets` are whole-line slices as above, one per measured shape:
`of the` (CRPT-118srpt11), `, 112th Congress` wrapped across a line
(-119srpt6), `(117th Congress)` and `, 117th Cong.` (-118hrpt964), GPO's `93d`
wrapped (-117hrpt707), a slash-joined list one qualifier closes and `(114th
Cong.)` beside the public law that confirms it (-119srpt8), and `in the 117th
Congress` naming the report's own (-117hrpt702). `keys` were read from each
slice.

| Fixture | Bytes | SHA-256 |
| --- | --- | --- |
| `print-inline-congress-2026-09-26.json` | 4,308 | `454cb876f4dd5b99e64b675a9ab683c993affc5e8b9e4a2f51e7cb746610bfd7` |
