# What the PDF-only families would add as hosted tables

Status: measured 2026-09-20. Read-only, ten families, 118 logged requests;
nothing published, no contract built. Sidecar:
[`pdf-family-rollup-yield-2026-09-20.json`](pdf-family-rollup-yield-2026-09-20.json).
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20/`.
Tool: `tools/analysis/pdf_family_rollup.py`, two phases, both through
`uv run --frozen`.

The [PDF-only census](pdf-only-corpus-2026-09-19.md) named which families have
no rendition but a PDF. This measures what hosting them would be *worth*, under
the two rules the owner set:

1. **Data that already exists is not recreated from the PDF.** So each family is
   measured twice — once against its index or API record, once against its
   documents — and only the difference counts. "Already exists" is measured, not
   assumed: the same extraction rule is read off the index record and both sides
   are reduced to one canonical key before comparison, so Congress.gov's
   `{"type": "HR", "number": 7806}` and the print's `H.R. 7806` are one fact.
2. **Nothing of value that only the PDF holds may be left uncaptured**, where
   value means join keys to the [hosted tables](../tables.md) and structured
   content a consumer would otherwise re-read the PDF for.

## Correction, 2026-09-20 (same day, while building step 1)

**This measurement compared against the wrong index record for the GovInfo
families.** It is superseded for those families by
[the MODS re-check](pdf-yield-mods-recheck-2026-09-20.md), which measured the
same question properly: every GovInfo family against its own package MODS, at
full page depth rather than the 60-page cap. Read that document for the
verdict and the revised build order; this section records what the error was
and what remains true here.

"Beyond the index" was measured against the `published` listing row — seven
fields, no citation among them. GovInfo offers a second index record for the
same package, the **package MODS**, which
[`GovInfoBodyAcquirer`](../sources/govinfo-bodies.md) fetches for every body it
reads, and which states bills, laws, U.S. Code sections, Statutes pages, CFR
parts, RINs, committees and the submitting member as named elements.

For the House committee activity reports, all eight, every page:

| Kind | Printed | Print-only |
| --- | --- | --- |
| `bill_number` | 1,406 | **0** |
| `public_law` | 174 | **1** |
| `usc_section` | 37 | **0** |
| `statutes_at_large` | 7 | **0** |

So this document's "883 distinct bill numbers ... none of them stated by the
index" is wrong, and so is the verdict built on it: **the citation yield this
report put first does not exist.**

This is the failure this repository's own rule warns about: a check that could
only look one way. The index side was rendered generously on purpose so it
could only overstate what the publisher states, and that guard worked as
designed — but it was pointed at one of the two index records, and the wrong
one. The 60-page cap compounded it: read to all 1,340 pages, `BUDGET-2027-APP`
names 490 public laws of which 488 are **not** in its MODS, so the budget
volumes' figures here were a 4-percent sample reported as the volume.

**What survives for the activity reports**, and it is what the print contract
is now scoped to: committees beyond the one that submitted the report (27
resolved `system_code`s over 71 rows), **87 RINs**, **38 agency dockets**, 5
GAO product ids, 1 CFR part, 1 Federal Register cite and 2 U.S. Reports cites.
No sampled MODS in any collection states a Federal Register cite, a GAO
product id, a CRS report id, an agency docket, a case docket, a U.S. Reports
cite or a dollar figure. The RINs and dockets are zero in the table below only
because a 60-page read never reached the oversight chapters.

**The rules were not the problem and did not change** — but the committee
resolver did, in review, and it changed this report's numbers. Every pattern
here now lives in `src/spicy_docs/interpretation/citations.py`, which
`tools/analysis/pdf_family_rollup.py` imports. Re-running `analyze` over the
same retained bytes reproduced every join-key count, distinct set and presence
figure unchanged (`document-citations-2026-09-20/diff-sidecar.txt`; the
differing-value total is run-dependent, because per-page timings are). Two
resolution guards were then added, and both remove wrong answers:

- **A run-on candidate whose remainder begins `AND` is refused.** The Senate's
  *Committee on Homeland Security and Governmental Affairs* begins with the
  House's *Committee on Homeland Security*, and the run-on route read it as
  the House committee with prose after it — publishing `hshm00`, a plausible,
  wrong, unflagged join. Same for the Senate's *Small Business and
  Entrepreneurship* against the House's *Small Business*, and for
  `Committee on the Judiciary and Committee ...` in an activity report.
- **A sibling fragment shorter than `Committee on` plus four characters is
  refused**, because below that it takes whichever single sibling happens to
  share its prefix (`Committee on A` → Appropriations).

Effect: the budget family loses `hshm00` (10 distinct `system_code`s to 9, and
it was the Senate committee misread as a House one); GAO's unresolved rises
1 → 2 with its code set unchanged; the activity reports' unresolved candidates
rise 20 → 26 with **the 20 distinct `system_code`s unchanged**, because every
refused fragment's committee is also spelled out in full somewhere in the same
print. Each finding's route is now reported (`resolved_by_route` in the
sidecar): `exact` and `roster_prefix` are roster lookups, `name_prefix` and
`sibling_prefix` are inferences from one document's own text.

The committed sidecar was deliberately **not** regenerated: it is the
measurement as run, and a re-run's timings would contradict the prose this
report quotes from it. `rollup-relift.json` in
`document-citations-2026-09-20/` is the re-run.

## The verdict, per family

| Family | Documents read | Verdict | What only the PDF supplies | What the index already supplies |
| --- | --- | --- | --- | --- |
| **House committee activity reports** (GovInfo `CRPT`) | 8/8 | ~~the highest-yield family in the corpus~~ — **superseded**, see the correction above and the [MODS re-check](pdf-yield-mods-recheck-2026-09-20.md) | ~~883 distinct bill numbers, 75 public laws, 15 U.S. Code cites~~ (the package MODS states all of them: 0 of 1,406 bills, 1 of 174 laws and 0 of 37 Code cites are print-only at full page depth). What survives: **27 committees** resolved to a `system_code`, **87 RINs**, **38 agency dockets**, 5 GAO ids, and the evidence span for every cite | The `published` row states `packageId`, `title`, `dateIssued`, `lastModified`, `congress`. **The package MODS states far more**: session, the authoring committee's `systemCode`, the submitting member's bioguide id, every `<bill>` with its context, every `<law>`, every `<USCode>` section and every sibling `<congReport>` — and 380 bills for a print whose capped read saw 39 |
| **Report of the Secretary of the Senate** (GovInfo `CDOC`) | 8/8 | **Host as a contract** — a cost/expenditure table, not prose | 396 ruled tables in 480 sampled pages (median 5 rows × 10 columns); 1,687 distinct dollar figures over 2,004 link rows; 5 distinct public laws | The senate.gov page states a link and a label (`Full Report`, `Part I`, `Part II`) — two fields |
| **GAO reports** | 8/8 | **Host as a contract** — recommendations and cross-product citations | Recommendation sections in 5/8, *Matters for Congressional Consideration* in 1/8, 44 of the 45 distinct GAO product ids cited are other products, 25 ruled tables | `product_id`, `title`, `link`, `guid`, `pub_date`, and a `description` that is the "What GAO Found" abstract |
| **Agency uploaded-report PDFs** (measured on Oversight.gov) | 8/8 | **Host as a contract**, but a narrow one | Recommendation sections in 6/8, 57 ruled tables, 11 distinct fiscal years, 4 distinct CFR cites | An unusually rich record: agency reviewed, components, report number, report type, date issued, external entity, **number of recommendations**, questioned costs, funds for better use |
| **Budget justifications** (GovInfo `BUDGET`) | 8/8 | **Host as a contract** — account tables, with a caveat | 658 distinct dollar figures (727 link rows), 90 distinct U.S. Code cites, 69 distinct public laws, 71 ruled tables, appropriation-account headings in 4/8 | `packageId`, `title` (`Appendix`, `Analytical Perspectives`, …), `dateIssued` — nothing below volume level |
| **House Clerk disclosures** | 7/8 | **Host as a contract** — but a form-extraction one, not a citation one | 56 ruled tables in 45 pages (asset/transaction grids), 44 distinct dollar figures over 102 link rows | The yearly index states `DocID`, `Year`, `FilingType`, `FilingDate`, `Prefix`, `First`, `Last`, `Suffix`, `StateDst` — the filer and the filing, none of the content |
| **Supreme Court slip opinions** | 8/8 | **Evidence-only for citations; host the body** | 192 distinct U.S. Reports cites over 209 link rows, 22 U.S. Code cites, 14 Statutes at Large cites, syllabus/held markers in 8/8 | The term index already states release number, date, docket, case name, **holding**, authoring Justice and citation |
| **CourtListener opinions** | 8/8 | **Evidence-only** | Nothing of its own. Every one of its 8 `download_url`s is a supremecourt.gov slip PDF, and 7 of the 8 are the same files the row above sampled; the two that differ are not the same case — CourtListener's extra is a second revision of 25-365, the Court's index's extra is a different case, 24-1260 | 33 fields including `citation`, `docketNumber`, `dateFiled`, `judge`, `panel_names`, `syllabus`, `posture`, `procedural_history`, `scdb_id`, `lexisCite`, `neutralCite` |
| **CRS report files** | 8/8 | **Evidence-only for join keys; host the body** | 44 of the 52 distinct CRS report ids cited (report→report, which the index never states); 177 distinct dollar figures; 22 U.S. Code cites | **Every bill the print discusses.** 0 of 36 distinct bills and 1 of 33 distinct public laws across the eight reports are absent from `relatedMaterials` |
| **CBO cost estimates** | **0/8** | **Blocked** — not obtainable, even through a paid proxy | Unknown, and it stays unknown | `Title`, `Date`, `Link` (a publication *page*), `Description`, `Bill_Number` |

## The three the owner named

### CBO's cost table: blocked, and the proxy does not change that

The census recorded CBO's documents as DataDome-walled with no keyless route.
Measured again today with a `ZYTE_TOKEN`: **nine walled URLs, eleven attempts,
two modes, and not one document obtained.** Eight of those nine were
`/publication/{id}` pages the feed itself stated; the ninth was a
`/system/files/*.pdf` the earlier probe had named.

**What those eleven refusals are, exactly**, because the distinction matters
under this repository's own rule that a transport failure is not a record: 3 of
the 11 carry Zyte's `/download/temporary-error` slug, which is the provider
saying it could not download the target; the other 8 are a bare HTTP 520 from
the provider with no slug at all. A 520 is Zyte's own transport failing. **So
none of the eleven is CBO refusing Zyte** — what is established is that *this
proxy could not fetch these paths*, which is a weaker and different statement
than the census's direct 403s, and those direct 403s remain the evidence that
CBO itself refuses. Neither says the wall is permanent.

The control is what makes that a finding rather than a broken run: the same
proxy, the same session, fetched CBO's *unwalled* `/rss/119congress-cost-estimates.xml`
and returned 432,572 bytes with digest `910aab10…` — byte-identical to the
keyless capture taken minutes earlier. The transport works and the wiring is
right, so the eleven failures are about those paths and not about this client —
but they are the provider's failure to fetch, not the publisher's answer.

So the highest-value candidate in the corpus cannot be built at all. What
survives is what the feed already gives, and that is not nothing: today's
capture of the 119th Congress holds 1,196 items, **1,140 of them naming a bill**
in `Bill_Number`, which resolves to a `congress_bills` row by the map's own
measured `cbo→bill` edge. A
`bill ↔ cost-estimate` link table is buildable today from the feed alone, with
no estimate document and no cost figures in it. Everything past that waits on a
route.

### CRS's bills-discussed: already exists — do not recreate it

This is the clearest application of rule 1 in the corpus, and it goes the other
way from what the census implied. Across the eight sampled reports the prints
name 36 distinct bills; `api.congress.gov/v3/crsreport/{id}`'s
`relatedMaterials[]` already states **every one of them**. Public laws: 33
distinct in the prints, 32 already stated, 1 new.

| Report | Bills in the PDF | Stated by the index | New | Laws in the PDF | New |
| --- | --- | --- | --- | --- | --- |
| IN12709 | 0 | 0 | 0 | 0 | 0 |
| IF12853 | 0 | 0 | 0 | 9 | 1 |
| IF13314 | 2 | 2 | 0 | 3 | 0 |
| R49351 | 5 | 5 | 0 | 2 | 0 |
| IN12576 | 1 | 1 | 0 | 1 | 0 |
| IN12418 | 3 | 3 | 0 | 4 | 0 |
| R49355 | 23 | 23 | 0 | 14 | 0 |
| IF12760 | 2 | 2 | 0 | 1 | 0 |

This result is the one the build order turns on, so it was re-derived with the
constraint relaxed and a different method: `crs-overlap-cross-check.py` in the
receipt reads `relatedMaterials[].type` and `.number` as **named fields**
rather than by pattern over rendered text, and agrees exactly. Extracting bills
from CRS PDF prose would be a keyed-route re-derivation of a keyed route's own
field, and it would be worse — a regex over print can drop a line-wrapped
`H.R.\n5509`, which `relatedMaterials` cannot.

What CRS PDFs *do* hold that nothing else does is the **report→report graph**:
52 distinct CRS report ids cited across the eight prints, 44 of them absent
from the citing report's index record. That is a real edge and it has no other
source; `relatedMaterials` covers laws and bills, never sibling reports.

### Opinions: CourtListener already carries the citations

Say it plainly, because it decides two families at once. CourtListener's own
record carries what a citation contract would be built to produce — `citation`,
`lexisCite`, `neutralCite`, `docketNumber`, `dateFiled`, `judge`, `panel_names`,
`syllabus`, `posture`, `procedural_history`, `scdb_id`, `sibling_ids` — and its
`download_url` for a Supreme Court opinion is the supremecourt.gov slip PDF
itself. There is no second acquisition to do and no metadata to re-derive.

What the slip PDF supplies that no index does is therefore exactly two things.

**The slip-opinion window before ingestion.** All eight sampled clusters carry
`citation: []`; the Court's own index gives `609/2` for all eight, which is a
preliminary-print volume placeholder, not a citation. Between a decision and its
ingestion — which for the newest of these is days and for the oldest in the
sample is months — the PDF is the only complete record of the opinion that
exists, and the Court's index is a *live render*: two captures 2.5 minutes apart
disagreed about 24 of 72 rows' links, and a link's trailing token is a revision
id. Capturing the PDF in that window is worth doing for the bytes, not for
fields.

**The body text**, and the citations inside it — 192 distinct U.S. Reports
cites over 209 link rows, 22 U.S. Code cites and 14 Statutes at Large cites
across eight opinions, none of them in either index. CourtListener's `citation` field names how this
opinion is cited; it never names what this opinion cites. That opinion-to-
opinion edge is real yield, and it belongs in the shared
`document_citations` table rather than in an opinion-specific contract.

Everything else about an opinion is already hosted somewhere. A slip opinion
carries **no ruled table at all** (0 across 335 sampled pages), so there is no
table contract here, and the structure that does exist — syllabus, per curiam,
concurrence, dissent, found in 8 of 8 — is what the
[slip-opinion capture profile](document-capture-schema-2026-09-19.md) already
reads.

## Join-key yield

Each cell is `documents stating the key / documents read` · **distinct
values the index does not state** · link rows the index does not state. Blank
means zero.

The last two are different numbers and conflating them overstates the yield.
**Link rows** is what a `document_citations` table would hold — one document
citing one key is one row, and eight opinions citing *Detroit Timber* is eight
rows. **Distinct values** is how many separate keys the family reaches — that
same boilerplate cite is one key. Where the two differ, the gap is repetition
across documents: the slip opinions cite 209 rows against 192 distinct U.S.
Reports cites, and the activity reports 940 rows against 883 distinct bills.
The bolded number is the yield over the publisher's own record.

The whole `Activity` column is **superseded** by the
[MODS re-check](pdf-yield-mods-recheck-2026-09-20.md), which read every page
rather than sixty: `bill_number`, `public_law`, `usc_section` and
`statutes_at_large` are 0, 1, 0 and 0 print-only there, and `rin` and
`docket_number` — zero here only because the cap never reached the oversight
chapters — are 87 and 38. The `committee_name` row's 87 candidates now settle
with two guards that refuse wrong answers, leaving the same 20 distinct
`system_code`s at this read depth and 26 rather than 20 unresolved candidates;
the re-check's full read reaches 27. The Secretary of the Senate and budget
columns are superseded there too, the budget one in the *other* direction: 504
of 518 public laws print-only on a full read.

| Key | Join target | CRS | GAO | SCOTUS | CourtL. | Activity | SecSen | Clerk | Budget | Upload |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bill_number` | `congress_bills.bill_id` | 6/8 · **0** · 0 | 1/8 · **1** · 1 | 2/8 · **4** · 4 | 2/8 · **2** · 4 | 8/8 · **883** · 940 |  |  | 2/8 · **4** · 4 |  |
| `public_law` | `laws (congress, law_type, number)` | 7/8 · **1** · 1 | 5/8 · **7** · 7 | 2/8 · **2** · 2 | 2/8 · **2** · 2 | 8/8 · **75** · 85 | 8/8 · **5** · 30 |  | 4/8 · **69** · 77 |  |
| `statutes_at_large` | `laws.statutes_at_large_cite` |  | 7/8 · **11** · 11 | 5/8 · **14** · 14 | 5/8 · **8** · 13 | 1/8 · **2** · 2 |  |  | 1/8 · **6** · 6 |  |
| `usc_section` | `law_code_sections` | 3/8 · **22** · 22 | 5/8 · **27** · 27 | 6/8 · **19** · 19 | 6/8 · **13** · 14 | 6/8 · **15** · 15 | 8/8 · **2** · 16 |  | 4/8 · **90** · 91 | 4/8 · **4** · 5 |
| `cfr_section` | CFR sections (host-side) | 3/8 · **17** · 17 | 4/8 · **9** · 9 | 2/8 · **4** · 4 | 2/8 · **4** · 4 |  |  |  | 1/8 · **3** · 3 | 5/8 · **4** · 6 |
| `federal_register_cite` | `federal_register.document_number` |  | 2/8 · **7** · 7 | 4/8 · **7** · 7 | 5/8 · **7** · 8 | 1/8 · **1** · 1 |  |  |  |  |
| `rin` | `federal_register.regulation_id_numbers_json` |  |  |  |  | 1/8 · **1** · 1 |  |  |  |  |
| `gao_product_id` | GAO product id (`gao/files.py` key) | 1/8 · **3** · 3 | 8/8 · **44** · 44 |  |  | 1/8 · **2** · 2 |  |  |  | 2/8 · **4** · 4 |
| `crs_report_id` | Congress.gov `crsreport` id | 8/8 · **44** · 44 |  |  |  |  |  |  | 1/8 · **1** · 1 |  |
| `bioguide_id` | `members.bioguide_id` |  |  |  |  |  |  |  |  |  |
| `docket_number` | `dockets.docket_id` |  |  |  |  | 1/8 · **1** · 1 |  |  |  |  |
| `case_docket_number` | CourtListener docket |  | 3/8 · **7** · 7 | 6/8 · **9** · 9 | 6/8 · **7** · 8 |  |  |  |  |  |
| `us_reports_cite` | CourtListener opinion citation |  |  | 8/8 · **192** · 209 | 8/8 · **178** · 222 |  |  |  |  |  |
| `committee_name` | `committees.system_code`, resolved | 2/8 · **8** · 8 | 6/8 · **7** · 8 |  |  | 8/8 · **87** · 120 |  | 7/7 · **1** · 7 | 2/8 · **14** · 14 |  |
| `dollar_amount` | no hosted target yet | 8/8 · **177** · 183 | 6/8 · **264** · 265 | 3/8 · **25** · 25 | 3/8 · **25** · 25 | 6/8 · **46** · 46 | 8/8 · **1687** · 2004 | 7/7 · **44** · 102 | 6/8 · **658** · 727 | 4/8 · **55** · 57 |
| `fiscal_year` | no hosted target yet | 7/8 · **10** · 14 | 5/8 · **15** · 23 |  |  | 8/8 · **7** · 15 | 8/8 · **5** · 35 |  | 6/8 · **49** · 58 | 6/8 · **11** · 17 |

Two results stand out and neither is where the census pointed.

**`bioguide_id` is zero everywhere, and that was a foregone conclusion.** A
bioguide id is an identifier the publishers assign and do not print; no
congressional document was ever going to contain one, so this row measures
nothing and is kept only to say plainly that it does. What these prints *do*
carry is names — an honorific-plus-name rule run over the activity reports finds
3 to 347 distinct hits per report — and turning those into bioguide ids is a
name-to-member crosswalk that **this measurement did not attempt**. So nothing
here says whether a `document → member` contract is feasible; it says only that
it cannot be built from a printed identifier, and that the crosswalk it would
need has not been measured.

**The House committee activity reports are the corpus's densest citation
surface**: 940 bill mentions and 85 law mentions across eight prints, over 883
and 75 distinct keys. ~~against a publisher index that states seven fields and
none of that~~ — the correction above: the package MODS states those keys, and
for -118hrpt965 it states 380 bills where the capped read saw 39. One report is
a whole Congress of one committee's legislative activity, and what only the
print holds is *where in it* each measure is discussed.

**Committee names are a resolution problem, not a count.** The rule that finds
them is a *candidate* finder: a committee report wraps the name across lines and
runs it into the following prose, so an early version of this measurement
reported 125 "committee names" for the activity reports when the eight prints
name about twenty committees. Of the 90 distinct candidates that rule produced,
five were dates (`Committee on June`), 46 were line-wrap prefixes of each other
(`Committee on Ag` / `Committee on Agri` / `Committee on Agriculture`) and
several ran into a chairman's name. The rule now rejects a month, and every
candidate is settled against the chamber rosters this repository already pins —
27 House committees from the Clerk's `MemberData.xml` and 12 more Senate
committees from the `cvc` file, read through
`sources/congress/committee_rosters.py`, with `comcode AG00 → hsag00` by the
data map's own measured rule. **20 distinct `system_code`s resolve across the
eight activity reports** (16 House, 4 Senate), from 87 candidates, leaving 20
unresolved. Only a resolved code is reported as a committee anywhere in this
document; an unresolved candidate is counted as a candidate.

The unresolved 20 are mostly Senate committees the pinned `cvc` excerpt does not
reach and fragments too short to settle (`Committee on E`), so 20 is a floor on
what a full roster would resolve — which is the shape the contract should take
anyway: extract the candidate, resolve against the hosted `committees` table at
build time, and store the `system_code`, never the printed string.

## Structured content

| Family | Ruled tables observed | Documents with one | Geometry (rows × cols, min/median/max) | Other structure |
| --- | --- | --- | --- | --- |
| Secretary of the Senate | 396 | 8/8 | 3/5/11 × 7/10/10 | — |
| Budget | 71 | 6/8 | 1/3/52 × 2/10/15 | appropriation-account headings 4/8, cost-table markers 2/8 |
| Agency upload (Oversight) | 57 | 7/8 | 1/4/53 × 2/4/18 | recommendation sections 6/8 |
| House Clerk | 56 | 7/8 | 2/10/23 × 2/6/8 | — |
| GAO | 25 | 8/8 | 1/8/18 × 2/3/6 | recommendations 5/8, Matters for Congress 1/8 |
| CRS | 11 | 2/8 | 2/14/59 × 3/3/3 | recommendations 2/8 |
| Slip opinions / CourtListener | 0 | 0/8 | — | syllabus or "Held" 8/8 |
| House activity reports | 0 | 0/8 | — | — |
| CBO | not measurable | — | — | — |

Two of these are negative results worth as much as the positive ones. **A slip
opinion has no ruled table at all** — its structure is the opinion division the
[slip-opinion profile](document-capture-schema-2026-09-19.md) already reads, not
a grid. And **a committee activity report has none either**: it is a long
bill-by-bill list in prose, so the contract for it is a citation contract, never
a table contract.

Table geometry is PyMuPDF's `find_tables()` through
`DocumentExtractor(..., tables=True)`, so it finds a table only where the print
carries a ruled grid, and reports one row per ruled band. The Senate's
expenditure volumes are the best case in the corpus: consistently 5–6 rows of
9–10 columns, which is a printed account block with its own ruling.

## The extraction rule per join key

Each rule below is what a `document_citations` builder would run. Every one was
measured on the sample and each carries the lookalikes it must reject; the
measurement asserts the rejection, so a rule that widened into prose shows up as
a failing check rather than as a high presence rate. All 16 rules pass; the full
patterns are in the sidecar's `join_key_rules`.

| Key | Rule, in words | Rejects (checked) |
| --- | --- | --- |
| `bill_number` | chamber designator, a `.` or space, then 1–5 digits, not preceded by `U.` or a letter | `HR974` (a GPO running head), `S4601` (a Record locator), `600 U. S. 183`, `ANALYSIS. 12` |
| `public_law` | `Public Law`, `P.L.`, `PL` or the Bluebook `Pub. L. No.`, then `congress-number` | `Public Lands`, `P.L. Smith`, `Pub L`, `Republic Law 5`, `Pub. L. Rev.` |
| `statutes_at_large` | `N Stat. N` | `Stat. of the Union`, `12 State 45` |
| `usc_section` | title, `U.S.C.`, optional `§`, then a section | `U.S. Code of conduct`, `42 USC for` |
| `cfr_section` | title, `C.F.R.`, optional `part`/`§`, then a part | `CFR is the`, `40 CRF 60` |
| `federal_register_cite` | volume, `Fed. Reg.`, page | `Fed. Reg. of the`, `88 Federal agencies` |
| `rin` | `RIN nnnn-XXnn`, the data map's own measured shape | `RIN of the`, `RIN 1234` |
| `gao_product_id` | `GAO-YY-NNNNN` with an optional suffix | `GAO reported`, `GAO-2026` |
| `crs_report_id` | a CRS series prefix and 4–6 digits, no separator | `R 1234`, `RL-31312` |
| `bioguide_id` | letter and six digits | `A 000375`, `AB000375` |
| `docket_number` | agency acronym, year, sequence | `FAA 2016 6907`, `ABC-16-0001` |
| `case_docket_number` | `No. YY-NNNN` not preceded by `L.` — any federal case, not only a Supreme Court one | `No. 25`, `Number 24-1001`, `Pub. L. No. 89-136` |
| `us_reports_cite` | volume, `U. S.`, page | `U.S. Government`, `600 US 1` |
| `committee_name` | `Committee on [the] <Title Case>`, no month; then resolved against the pinned chamber rosters | `committee on the matter`, `Committee of the Whole`, `Committee on June 5` |

**Four of these rules were wrong until the sample corrected them, and that is
the argument for measuring before building.** The first `bill_number` rule
scored the slip-opinion sample at a 100% bill rate — because `600 U. S. 183`
contains `S. 183`. The same rule read the GPO running head `HR974` as a bill, which is
why GPO print artifacts now come off through
[`extraction/gpo_normalize.py`](../extraction-gpo.md) before any text rule runs.
Its own evidence gate is worth reporting: it stripped GPO footers from 8 of the
71 documents read — all eight committee activity reports — and fired on none of
the other 63, including the eight Secretary of the Senate volumes, which are
GovInfo prints from the same collection family. The gate is reading the page,
not the host. A `recommendation_list` marker built
from `We recommend that` alone found GAO recommendations in 1 of 8 reports; the
publisher's actual heading is *Recommendations for Executive Action*, and with
it the rate is 5 of 8.

The other two were found in review. The `public_law` rule could read
`Public Law 98-369` and `P.L. 98-369` but not the Bluebook `Pub. L. No. 89-136`,
which is the spelling a court or an auditor writes in: adding it recovered 35
occurrences the first pass missed, 18 in the activity reports and 11 in GAO, and
moved GAO's public-law row from **no documents** to 5 of 8. And
`case_docket_number` was reading the `No. 89-136` inside those same Bluebook
cites as a circuit docket; it now refuses a `No.` preceded by `L.`

## The contract shape this points at

One link table in the `fr_docket_links` shape — one row per (document, cited
key), sorted by target so a `WHERE target_key = ?` prunes row groups:

| Column | Meaning |
| --- | --- |
| `document_key` | The family's own natural key: `packageId` for GovInfo, `product_id` for GAO, CRS `id` + version, the Clerk's `DocID`, the slip opinion's file stem |
| `document_family` | Which of the families above, so one table serves all of them |
| `cite_kind` | The rule name above: `bill_number`, `public_law`, `usc_section`, … |
| `target_key` | The canonical key, in the hosted table's own spelling: `hr3633`, `119-21`, `26 U.S.C. 1` |
| `target_table` | `congress_bills`, `laws`, `law_code_sections`, `federal_register`, … |
| `evidence_page`, `evidence_line`, `evidence_text` | Where in the print it was read, from the same evidence blocks the capture profiles are built on |
| `rule_version` | So a re-extraction under a corrected rule is attributable, the way `prompt_version` is |

Every document in every family partitions cleanly into those evidence blocks:
the line assembly `reconstruction.evidence.evidence_from_pages` — the half that
every PDF capture profile shares — ran over one document per family, producing
55 to 3,008 blocks, and in all nine the concatenated blocks reproduce the page
text under whitespace normalization. That comparison is the witness; an earlier
version of this measurement instead checked the evidence document's
`source_sha256` against the digest it had just been handed, which is a
tautology and would have passed on any input at all.

**No seventh capture profile was written.** What a family-specific profile adds
over the shared line assembly is a *grammar* — which lines are a heading, a
recommendation, a cost row — and choosing that grammar is the contract build
this measurement is meant to inform, not part of measuring it. The slip-opinion
profile remains the PDF-text worked example, and today's independent capture of
`25pdf/26a274_l537.pdf` is byte-identical to the one pinned there on 2026-09-19
(`7c14a9d1…`, 66,165 bytes), which is a route-stability result in its own right.

## What Zyte answered and what it did not

| Route | Census said | Direct, today | Through Zyte, today |
| --- | --- | --- | --- |
| CRS HTML (`congress.gov/crs_external_products/*/HTML/*.html`) | 403 to a plain client, corrected 2026-09-19 to flaky | `200 text/html`, 2 of 2 reports | `200 text/html`, 2 of 2, **byte-identical to the direct capture** (`5e20a65f…`, `154a5492…`) |
| CBO `/publication/{id}` | 403 DataDome | not attempted (the census established it twice) | **no document**, 8 URLs + 2 repeats in `browserHtml`; 2 answered with the provider's `/download/temporary-error`, 8 with a bare 520 |
| CBO `/system/files/*.pdf` | 403 DataDome | not attempted | **no document**, 1 attempt, the provider's `/download/temporary-error` |
| CBO `/rss/{c}congress-cost-estimates.xml` (control) | 200 keyless | `200`, 432,572 B | `200`, 432,572 B, **same digest** `910aab10…` |

The controls are the point. Two byte-identical pairs, on two publishers, say the
proxy returns the publisher's own bytes rather than a rendering, so the CBO
failures are about those paths and not about this client. They do **not** say
CBO refused the proxy: 8 of the 11 are a bare provider 520, which is Zyte's
transport failing, and a transport failure establishes nothing about a
publisher. The CRS "wall" did
not reproduce on either route; two successes do not establish a reliable route
any more than one does, and `crs_files.py`'s existing HTML-then-PDF fallback
stays the right shape.

The transport that made this possible is new:
[`transport/zyte.py`](../../src/spicy_docs/transport/zyte.py), an
`httpx.BaseTransport` over the existing `sources/zyte.py` fetcher, so any
acquirer that already takes an injected transport can be pointed through the
proxy without a second HTTP client. Its rules — one provider call per request,
no credential to the publisher, a `ZyteProxyRecord` on every response naming the
request id, the mode and the proxy — are recorded in
[decisions.md](../decisions.md#the-shared-zyte-transport-lives-in-spicy-docs-and-records-that-a-capture-was-proxied).

## Request counts

| Class | Requests | Bound | Notes |
| --- | --- | --- | --- |
| Keyless | 91 | none set | Ten hosts: `files.gao.gov`, `www.gao.gov`, `www.congress.gov`, `www.govinfo.gov`, `www.supremecourt.gov`, `www.courtlistener.com`, `www.senate.gov`, `disclosures-clerk.house.gov`, `www.oversight.gov`, `www.cbo.gov` |
| Keyed (`API_GOV`, header only) | 13 | 20 | Two hosts: 9 `api.congress.gov` `crsreport`, 4 `api.govinfo.gov` `published` |
| Zyte | 14 logged rows; **at least 17** provider calls | 30 | Three provider calls predate the probe's failure logging and were re-run identically, so every row the report cites is in `requests.jsonl`. The exact total is *not* derivable from this receipt: the shared client may retry within one logged row, and the run recorded no per-row call count. The transport now reports `provider_calls` on every row and `acquire` writes the budget's spend to `acquire-summary.jsonl`, so the next run states it exactly. |
| **Total** | **118 logged** | | |

## Complexity

Linear per document in its pages. Extraction yields one page at a time and each
rule scans each page's text once, so a family of `D` documents with `P` pages
costs `O(D·P·C·K)` for `K` fixed rules. Measured with `tables=True` on all 71
documents, per family as whole-document seconds divided by pages read: **24 to
84 ms per page**, and the spread is content, not size — the budget volumes cost
84 ms/page against 24 ms/page for the slip opinions. The slowest *single* page
in the corpus is timed around the generator's own `next()` and is 275 ms, in the
Budget Appendix; the first version of this tool started that timer after the
page was already produced and published a column of zeros. `find_tables()` is
the only superlinear step and it is per page and bounded there; nothing in this
measurement is superlinear in the corpus.

The one quadratic step is in the measurement's own index rendering, not in any
proposed contract: every ordered pair of a record's values is offered so a
two-field key is readable whatever order it was serialized in, which is O(k²) in
one record's field count — a handful, bounded by the publisher's schema.

## What this measurement cannot see

- **It reads at most 60 pages of a document.** That truncates the Secretary of
  the Senate volumes (1,259–3,018 pages), the Budget Appendix (1,340), seven of
  eight activity reports and four slip opinions. Every count above is therefore
  a floor on the document, not a total.
- **The "beyond the index" counts are a floor** for a second reason: the index
  side is rendered generously on purpose, so it can only look like the publisher
  states *more* than it does.
- **Eight documents per family is a sample, not coverage**, and every family's
  eight are the newest available, which biases toward current formatting.
- **One capture does not establish a route.** The CBO refusals are one day.
- **The agency-upload family has no publisher at all.** Its index record is
  Oversight.gov's, the nearest public analogue with one; a BillTrax upload has
  no index record, so for that channel *every* column in the table above is
  yield, and the Oversight numbers are the conservative reading.

## Recommended build order

1. ~~**`document_citations`, built first on the House committee activity
   reports.**~~ **Superseded** by the
   [MODS re-check](pdf-yield-mods-recheck-2026-09-20.md#revised-build-order),
   which puts the budget volumes first (504 print-only public laws against
   these reports' one) and narrows the activity-report print contract to what
   the MODS lacks: committees beyond the submitting one, 87 RINs, 38 agency
   dockets, 5 GAO ids. The shared contract itself **landed 2026-09-20** on the
   activity reports — `document_citations` and `house_activity_reports` in
   `schemas/document_citation_tables.py` — which was the right piece of work
   in the wrong order of priority; it is an order of magnitude smaller than
   this report estimated, and still worth having.
2. **Extend `document_citations` to GAO and the slip opinions**, which add the
   `gao_product_id` report→report edge (44 of 45 cites are other products) and
   the `us_reports_cite` opinion→opinion edge (192 distinct cites over 209
   rows, and CourtListener's `citation` field covers the *cited* opinion, never
   the citing one's references).
3. **`crs_report_citations`, and nothing else from CRS.** The bills and laws are
   already in `relatedMaterials`; the report→report graph is not, and has no
   other source.
4. **`senate_expenditures`, a real table contract**, off the Secretary of the
   Senate volumes: 396 ruled tables in 480 sampled pages, a consistent 5–6 × 9–10
   geometry, and a two-field index record that states nothing about the content.
   This is the best ruled-table target in the corpus and it is keyless. Note
   what the join-key table says about it: 1,687 distinct dollar figures but only
   5 distinct public laws and 2 U.S. Code cites — this family is a *table*
   contract, not a citation one, and `document_citations` would add almost
   nothing here.
5. **`gao_recommendations`** — a list contract, not a citation one, over the
   *Recommendations for Executive Action* and *Matters for Congressional
   Consideration* sections. Worth doing after (2) because it needs a section
   grammar, which means the first family-specific capture profile.
6. **Budget account tables and House Clerk disclosure grids**, in that order.
   Both are real table yield; both need a page-level section grammar before the
   rows mean anything, and the Clerk's grids are a form-extraction problem
   rather than a citation one.
7. **CBO: build the feed-only `bill ↔ cost_estimate` link table now, and stop
   there.** The document has no route this measurement could reach. Re-probe
   when CBO changes hosts or when a route other than `www.cbo.gov` appears. Do
   not spend on the proxy again without new evidence — but record why: 8 of the
   11 attempts were the provider's own transport failing, so what was measured
   is that *this proxy could not fetch these paths*, not that CBO refused it.
   The feed control is what makes even that worth acting on.
8. **Do not build**: a CRS bills-discussed extractor (rule 1). A
   `document → member` contract is **not** ruled out here — it is unmeasured:
   no print states a bioguide id, which was always going to be true, and the
   name-to-member crosswalk that would be needed instead was not attempted.
