# The GovInfo families were measured against the wrong index

Status: measured 2026-09-20. Read-only, 24 keyed requests, nothing published.
Sidecar: [`pdf-yield-mods-recheck-2026-09-20.json`](pdf-yield-mods-recheck-2026-09-20.json).
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/pdf-yield-mods-recheck-2026-09-20/`.
Tool: [`tools/analysis/pdf_yield_mods_recheck.py`](../../tools/analysis/pdf_yield_mods_recheck.py),
three phases, all through `uv run --frozen`.

**This supersedes the GovInfo-served rows of
[the yield measurement](pdf-family-rollup-yield-2026-09-20.md)** (merge
6cea782) and the build order it recommended. Its rules, its sample and its
retained bytes all stand; what was wrong is the record it called "the index".

The rollup compared each print's citations against the row GovInfo's
`published` walk returns — `packageId`, `title`, `dateIssued`, `lastModified`,
`congress`, `docClass`, `packageLink`. Seven fields, no citation among them, so
everything the print named counted as yield. But that listing row is not the
index a GovInfo body has. `GovInfoBodyAcquirer` fetches the **package MODS**
for every body it reads — it is the record that decides which rendition to
fetch, so no caller ever has the body without it — and the MODS states bills,
laws, U.S. Code sections, CFR parts, Statutes at Large pages, RINs, committees
and the submitting member as *named elements*. The owner's rule is never to
recreate data an index already states. Applied against the listing row, that
rule was answered with the wrong record.

## The verdict, restated

| Family | The rollup's headline | Against the MODS, same sample | Against the MODS, every page |
| --- | --- | --- | --- |
| **House committee activity reports** (`CRPT`) | "the highest-yield family in the corpus": **883** distinct bills, **75** public laws, 20 resolved committees, none of it stated by the index | bills **0**, laws **0**, U.S. Code **0**, Statutes **0**. Committees survive: 20 resolved codes, 38 of 46 rows | bills **0 of 1,406**, laws **1 of 174**, U.S. Code **0 of 37**, Statutes **0 of 7**. Committees 27 codes, 71 of 79 rows |
| **Budget justifications** (`BUDGET`) | 69 public laws, 90 U.S. Code cites, 658 dollar figures | laws 43 of 69, U.S. Code **7 of 90**, Statutes **1 of 6**, CFR 3 of 3 | laws **504 of 518**, U.S. Code 97 of 922, Statutes **1 of 81**, CFR 13 of 18 |
| **Report of the Secretary of the Senate** (`GPO-CDOC`) | 5 public laws, 2 U.S. Code cites, 1,687 dollar figures | laws **0**, U.S. Code **0**. Dollar figures untouched | laws **0 of 7**, U.S. Code **0 of 2**. 65,261 distinct dollar figures over 161,536 rows |
| GAO, Supreme Court, CourtListener, CRS, House Clerk, agency uploads, CBO | — | Not GovInfo. No MODS exists; those rows are unchanged by this recheck | — |

The one-line version: **the citation yield the rollup put first does not
exist.** A House committee activity report names no bill, no public law, no
U.S. Code section and no Statutes at Large page that its own package MODS does
not already state — not on the rollup's 60-page sample and not on a complete
read of all 1,249 pages. The MODS states *more* than the print: 1,500 bill
entries against the print's 1,494, 219 law entries against 202.

## How the 883 became 0

The rollup's `bill_number` figures for the activity reports, per document,
beside what each package's own MODS states. "Print" is the rollup's own
retained key set; "MODS" is `extension/bill`, read as named attributes.

| Report | Print (60 pages) | MODS | Print-only | Print (all pages) | Pages | Print-only |
| --- | --- | --- | --- | --- | --- | --- |
| CRPT-118hrpt965 | 39 | 380 | **0** | 379 | 282 | **0** |
| CRPT-118hrpt968 | 179 | 179 | **0** | 179 | 56 | **0** |
| CRPT-118hrpt970 | 71 | 111 | **0** | 110 | 127 | **0** |
| CRPT-118hrpt972 | 124 | 217 | **0** | 217 | 119 | **0** |
| CRPT-118hrpt974 | 169 | 194 | **0** | 193 | 296 | **0** |
| CRPT-118hrpt975 | 86 | 90 | **0** | 89 | 103 | **0** |
| CRPT-118hrpt976 | 45 | 48 | **0** | 46 | 99 | **0** |
| CRPT-118hrpt977 | 227 | 281 | **0** | 281 | 167 | **0** |

Bills compare on `natural_key` where both sides state a Congress, and on
`type+number` otherwise: the print rule reads `H.R. 1093` and captures no
Congress, so a congress-blind key is the only honest comparison the print side
supports, and it is also the generous one — it can only make the MODS look like
it states more, never less. Laws compare on `(congress, number)` with the
MODS's `isPrivate` giving the type; committees compare on the resolved
`system_code`, the MODS's `congCommittee/@authorityId` against the same pinned
chamber rosters the rollup resolves printed candidates with.

## The check the result turns on

Zero is the kind of number that deserves suspicion, and there was one obvious
way it could have been an artifact: the rollup reads at most 60 pages of a
document, and **seven of the eight activity reports are longer than that**. A
capped read can only understate what a print names, so "print-only is zero"
might have been a statement about the cap rather than about the document.

So the cap was removed and the measurement re-run — same rules, imported not
restated, same MODS, **every page of all 24 retained PDFs**, no request at all,
since the bodies are already in the rollup's own `blobs/`. That is 18,119 pages
against the 1,271 the rollup read from these three families: 1,249 for the
activity reports (9.5 s, against 476 read), 1,785 for the budget volumes
(40.5 s, against 315) and 15,085 for the Senate volumes (125.6 s, against 480).

It did not move the result for the activity reports. The print's bill count
rose from 883 distinct to 1,406, and **every one of the 1,406 is in the MODS**,
which states 1,410. Laws rose from 75 to 174 and exactly one — in
CRPT-118hrpt977 — is not in that report's MODS.

It moved the budget result hard, in the other direction, and that is worth as
much. Read to 60 pages, `BUDGET-2027-APP` names 29 public laws; read to all
1,340, it names 490, of which **488 are not in its MODS**. The rollup's budget
figures were not wrong about the index — they were a 4-percent sample of a
1,340-page volume reported as the volume.

## What the MODS states, per collection

Measured by walking the retained bytes, not assumed: `element_census` reports
every path each record carries, and only what it found is compared. Counts are
records out of the 8 sampled per collection that state the kind at all.

| Kind | `CRPT` (activity reports) | `BUDGET` | `GPO-CDOC` (Senate Secretary) |
| --- | --- | --- | --- |
| `bill` | **8/8** | 1/8 | 0/8 |
| `law` | **8/8** | 3/8 | **8/8** |
| `USCode` (section, chapter, appendix) | **8/8** | 4/8 | **8/8** |
| `cfr` | 0/8 | 2/8 | 0/8 |
| `statuteAtLarge` | 1/8 | 2/8 | 0/8 |
| `rin` | 0/8 | 1/8 | 0/8 |
| `congCommittee` with an `authorityId` | **8/8** | 0/8 | 0/8 |
| `congMember` with a `bioGuideId` | **7/8** | 0/8 | 0/8 |
| `congReport` / `congDoc` / `congHearing` / `congSerial` | **7/8**, 374 entries | 0/8 | 0/8 |
| `field name="Fiscal Year"` | 0/8 | **8/8** | 0/8 |

Three of those rows are findings in their own right.

**The MODS names the submitting member by bioguide id.** The rollup reported
`bioguide_id` as zero in every family and called that "a foregone conclusion —
no congressional document was ever going to contain one", and said a
`document → member` contract would need an unattempted name-to-member
crosswalk. For CRPT it needs neither: `<congMember role="SUBMITTEDBY"
bioGuideId="M001157">` is a `members.bioguide_id` already. **Seven of the
eight**, not eight — CRPT-118hrpt965's `congMember` carries a chamber, a state
and the parsed name `Mrs. Rodgers of Washington` and no `bioGuideId` at all, so
this is a per-record statement and not a property of the collection. It is also
only the *submitting* member; every other name in the print stays uncrosswalked
and unmeasured.

**The MODS names 374 other congressional documents.** 347 `congReport`, 25
`congSerial`, one `congDoc`, one `congHearing`, across seven of the eight
activity reports — the report-to-report edge, stated by the publisher in
`(congress, type, number)`. No rollup rule looks for it and no print was read
for it.

**No MODS in any sampled collection states a Federal Register cite, a GAO
product id, a CRS report id, an agency docket, a case docket, a U.S. Reports
cite or a dollar figure.** No element of any such kind appears anywhere in the
three collections' vocabularies — the census lists every root-level `extension`
child of all 24 records, and there is no `fr`, no `gaoId`, no `crsId`, no
`docketNumber` and no `courtCase` among them. Those are the kinds where a print
read is the only source.

Per collection, the kinds a MODS **never** states, which is the surviving
PDF-only yield for each:

- **`CRPT`**: CFR parts, RINs, fiscal years, Federal Register cites, agency
  dockets, case dockets, U.S. Reports cites, GAO product ids, CRS report ids,
  dollar figures.
- **`BUDGET`**: committees, members, report-to-report references, Federal
  Register cites, dockets of either kind, U.S. Reports cites, GAO and CRS ids,
  dollar figures.
- **`GPO-CDOC`**: everything except public laws and U.S. Code sections. No
  bill, no committee, no member, no CFR, no Statutes, no RIN, no fiscal year —
  and the granule MODS states no more than its package's.

## The surviving yield

Per family and per kind, on the uncapped read, after the MODS is subtracted.
"Print-only" is the union of each document's own print-only set — the right
number for a `document_citations` row, since a row is worth building only where
*that* document's index does not state the key.

| Kind | Activity reports | Budget | Senate Secretary |
| --- | --- | --- | --- |
| `bill_number` | — (0 of 1,406) | 6 of 8 | 1 of 1 |
| `public_law` | 1 of 174 | **504 of 518** | — (0 of 7) |
| `usc_section` | — (0 of 37) | 97 of 922 | — (0 of 2) |
| `statutes_at_large` | — (0 of 7) | 1 of 81 | — |
| `cfr_section` | 1 of 1 | 13 of 18 | — |
| `federal_register_cite` | 1 | 9 | — |
| `rin` | **87** | — | — |
| `gao_product_id` | 5 | — | — |
| `crs_report_id` | — | 1 | — |
| `docket_number` | **38** | — | — |
| `case_docket_number` | — | 2 | — |
| `us_reports_cite` | 2 | — | — |
| `committee_name` (resolved codes) | **27**, 71 of 79 rows | **20**, all of them | — |
| `bioguide_id` | 0 printed; MODS states 7 | — | — |
| `dollar_amount` | 157 | **2,838** | **65,261** over 161,536 rows |
| `fiscal_year` | 16 | 47 of 48 | 5 |

Committees are the one citation kind that survives on the activity reports, and
the reason is structural rather than accidental: a package MODS states the
committee that *submitted* the report — one per report, eight across the sample
— while the print names every committee the report's business touched. All
eight MODS committees are in their own report's resolved print set, so the
index adds nothing there; the print adds 19 more codes the family's MODS never
name between them.

`rin` and `docket_number` on the activity reports are new — both are zero in
the rollup's table because its 60-page read never reached the oversight
chapters, and the CRPT MODS states neither. 87 distinct RINs and 38 dockets
across eight reports is a real `federal_register` edge with no other source.

## The non-GovInfo publishers

The same question, asked of every family with no MODS: is there a field in the
publisher's own record that already states what the print was going to be read
for? Answered from retained bytes with no new request
(`non-govinfo-index-recheck.py` in the receipt).

**CourtListener: yes, and the rollup narrowed the record before reading it.**
The search result carries 33 fields; the rollup retained 10 of them as the
document's `index` and compared against those. Among the 23 it dropped is
`opinions[].cites` — **the outbound opinion-to-opinion edge, in CourtListener
opinion ids**: 4, 12, 27, 152 and 61 ids on five of the eight sampled clusters,
none on the other three. The rollup's build order says CourtListener's
`citation` field "covers the *cited* opinion, never the citing one's
references" and puts `us_reports_cite` second on the strength of it. That claim
was read off a record that had already been cut down. What the print still adds
is the *reporter spelling* — `opinions[].cites` gives CourtListener ids, and
turning one into `192 U. S. 1` is another request per id — and the three
clusters where CourtListener states no outbound cite at all. That is a smaller
and differently shaped claim than the one the rollup made.

**GAO: the retained record is the richest one measured, and it is thin.** The
RSS item's `description` is the whole "What GAO Found" text, 3,252 to 7,323
characters, and the rollup did compare against it. Only one of the eight
descriptions states a law (`Pub. L. No. 119-60 … 139 Stat. 718`, which the
rollup counted as already-stated) and none states a bill. **Whether GAO's
product page states more is unmeasured**: the rollup fetched the feed and the
PDF and never fetched a product page, so nothing here licenses a claim either
way.

**The Court's term index, CRS, the Clerk, agency uploads and CBO: unchanged.**
The Court's index has nine fields, the rollup read eight of them and the ninth
is the PDF URL; it states no citation beyond the `609/2` preliminary-print
placeholder. CRS's `relatedMaterials` — up to 58 entries on one report — is a
named-field list of bills and laws, and the rollup read it and reached the
right conclusion. The Clerk's, Oversight's and CBO's records were flattened
whole into the comparison; the apparent gaps between their `index_fields` and
their retained records are two spellings of the same fields, not dropped ones.

## Revised build order

The rollup's order was led by the activity reports on the strength of the 883
bills and 75 laws. Both are zero. What replaces it:

1. **`document_citations`, built first on the budget volumes, not the activity
   reports.** 504 distinct public laws, 97 U.S. Code sections and 13 CFR parts
   across eight volumes that no MODS states — the largest real citation yield
   in the corpus, and the only GovInfo family whose print substantially
   outruns its own index. It exercises `public_law`, `usc_section` and
   `cfr_section` together. Two costs the rollup did not price: the volumes are
   long (1,340 pages for the Appendix, 1,785 across the sample) so a page-level
   read is the contract, not a 60-page probe; and `bodies.py`'s package-id
   grammar does not cover `BUDGET-*`, so `GovInfoBodyAcquirer` cannot reach
   these packages at all until it does.
2. **Ingest what the CRPT MODS already states, and build no citation
   extractor for it.** Bills, laws, U.S. Code cites, Statutes pages, the
   submitting member's bioguide id and the 374 report-to-report references are
   all in a record this repository already fetches for every body it reads. A
   `document_citations` loader over `PackageModsIdentity` costs no new request
   and no extraction rule. `ModsBill` is already read; `law`, `USCode`,
   `congCommittee`, `congMember` and `congReport` are not, and adding them to
   `validate_package_mods` is the smallest piece of work in this document.
3. **The activity-report *print* contract narrows to what the MODS lacks**:
   committees beyond the submitting one (27 resolved codes, 71 rows), 87 RINs,
   38 agency dockets, 5 GAO product ids. Worth building, an order of magnitude
   smaller than the rollup's estimate, and no longer the family to build first.
4. **`senate_expenditures`, the ruled-table contract, unchanged and now clearly
   second overall.** Its citation yield is zero against the MODS, which only
   confirms the rollup's own reading that this family is a table contract and
   never a citation one. 65,261 distinct dollar figures over 161,536 rows on a
   full read, against a two-field publisher listing and a MODS that states
   laws, U.S. Code sections and nothing about the content. Same grammar caveat:
   `GPO-CDOC-*` is outside `bodies.py`'s package-id grammar.
5. **GAO and the slip opinions**, as before, with the `us_reports_cite`
   rationale rewritten: CourtListener *does* state the outbound edge in its own
   opinion ids, so what the slip PDF adds is the reporter spelling and the
   clusters where CourtListener states nothing. Re-measure that before
   committing to it.
6. **`gao_recommendations`**, then **Clerk disclosure grids**, unchanged.
7. **CBO**, unchanged: feed-only `bill ↔ cost_estimate`, and do not spend on
   the proxy again without new evidence.
8. **Do not build**: a CRS bills-discussed extractor (unchanged — that one the
   rollup got right); a CRPT bill, law, U.S. Code or Statutes extractor
   (new — the MODS states all four); a name-to-member crosswalk for a CRPT
   report's submitting member (new — the MODS states the bioguide id).

## Complexity

One keyed request per distinct MODS, 24 for this sample, bounded at 40 in the
tool. Analysis is linear in retained MODS bytes plus the rollup's own key sets,
`O(Σ M + D·K)` for `D` documents and `K` fixed rules; the MODS total is 4.1 MB,
of which `BUDGET-2027-APP` alone is 2.8 MB. The uncapped re-read is linear in
pages, measured with table detection off at 7.6 ms/page for the activity
reports, 8.3 ms/page for the Senate volumes and 22.7 ms/page for the budget
volumes — against the rollup's 24–84 ms/page, and the difference is what
`find_tables()` costs. That is the whole argument for reading every page: 18,119
of them took 176 seconds and reversed the measurement's headline.

## What this measurement cannot see

- **Eight documents per family, and three collections.** CRPT, BUDGET and the
  GPO-prefixed CDOC reprints are what the rollup's sample reaches. CHRG, CPRT,
  CREC, CDIR and BILLS MODS are not measured here, and what one collection's
  MODS states says nothing about another's — this document's own per-collection
  table is the evidence for that.
- **A MODS is a claim, not a proof of completeness.** That the MODS states
  every bill these eight prints name does not establish that it always will.
  What is established is that on 24 records and 18,119 pages, the print added
  nothing to it — twice, at two different read depths.
- **The comparison is key-for-key, not context-for-context.** The MODS states
  that a report names H.R. 1093; the print states *what it says about it* —
  reported, amended, passed. Nothing here measures that, and a contract that
  wants the relationship rather than the edge still has to read the print.
- **The print side is still the rollup's rules.** They were measured and
  corrected on this sample, but a rule that misses a spelling makes the print
  side look smaller, which here makes the MODS look more complete. The one
  place that matters is `public_law` on the budget volumes, and there the print
  runs far ahead of the MODS anyway.
- **GAO's product page was never fetched**, by the rollup or by this recheck,
  so "no richer GAO index exists" is not claimed.
- **CourtListener's `opinions[].cites` was not resolved.** Whether those ids
  cover the print's 178 distinct U.S. Reports cites is a per-id lookup this
  measurement did not make.
