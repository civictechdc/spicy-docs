# Legislative data validation — 2026-09-21

## Decision

The inspected literal legislative metadata generally preserves its sources.
The next work should repair demonstrated omissions and misleading derived
fields, then publish a coherent generation of the existing families. More
source families or more model output would not resolve those defects.

This review accounts for all **45 assigned output tables**: the 39 SpicyDocs
legislative table definitions, five additional processing/link tables, and the
emitted `bill_subjects` table. It also covers the Congress, GovInfo, U.S. Code
and legislators source families, including routes without hosted outputs.
Each table has conversion, completeness, shape and usefulness verdicts, an
explicit source/output scope and a next action in the detailed assessment.

The strongest positive evidence consists of native input/output censuses:
2,966 committee assignments, 2,204 nominations, 583 selected classification
lines, all 65 retained Table III records and all 881 retained bill vote
references. These checks do not qualify other Congresses, source releases,
unread bodies or inferred fields.

The strongest new counterexamples concern six generic report headings labeled
as agencies, committee actions attached to the wrong text block, a missing
meeting address, nested committees missing from the identity table, and two
missed citation spellings in one budget document. No product code, vendor pin,
release or public artifact was changed by this work stream.

## Evidence and scope

The predeclared protocol is
[data-validation-sprint-2026-09-21.md](data-validation-sprint-2026-09-21.md).
The receipt root for this review is:

`~/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/`

The detailed machine-readable results are
[table-assessments.json](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/table-assessments.json) and
[source-assessments.json](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/source-assessments.json).
They name each actual output path, raw evidence receipt, sample denominator,
limitations and next action. `native-input-pins.json`,
`extended-input-pins.json`, `final-witness-pins-v2.json`,
`supplementary-pins.json` and `visual/source-pins.json` retain byte counts and
SHA-256 input identities. Parent-level `artifact-selection.json` and
`table-profiles-final.json` supply the common selected-output inventory.

The primary profile is an inventory, **not one coherent release**. In
particular, the actual public `congress_bills` object has 419,571 rows and ten
columns. It is distinct from the broad local D1 generation with 419,621 rows
and 48 columns, the adoption generation with 16,213 rows and 49 columns, and
the corrected local 118th-Congress HR/S candidate. The last two share a narrow
scope; the broad old generation still carries known old cosponsor values.
The five corrected candidate tables must not supply parents for unrelated
119th-Congress child rows.

The previous independent 118 HR/S census was reused, not repeated. It covered
16,213 native BILLSTATUS XML documents, 1,189,950 field comparisons, 75,239
actions, 26,029 bill/committee rows, 10,806 publisher summaries and 1,431 CBO
publication entries, including restatement fields. Its demonstrated cosponsor
error was fixed earlier in this session. The corrected count includes every
listed cosponsor entry, including withdrawn entries; it is not a count of
currently active cosponsors.

New comparisons used native XML/JSON/HTML, independent field selection and
actual Parquet rows. They did not invoke the product parser as a correctness
oracle. Selected PDFs were rendered and viewed. Every semantic sample is
named and purposive; none is claimed to be a statistical estimate of overall
accuracy. Repository test fixtures are identified as either complete native
captures or genuine reserialized excerpts, rather than all being treated as
full publisher responses.

There were **ten successful fresh HTTP requests**: one bill status plus three
bill XML bodies, and two packages each requiring summary, MODS and HTML body.
One additional requested bill rendition was refused before an HTTP body
request because the source status did not offer it. The ledgers are
`fresh-bill-1009/ledger.json` and `fresh-package-bodies/ledger.json`. Each of the
five fetched document bodies matched a digest already retained in an output
generation. No new population acquisition, model call or upload occurred.

## Findings that change the work

### Report headings are not agency identities

`CRPT-119hrpt796` is a report on H.R. 5634, the Veterans Flight Training
Responsibility Act of 2026. Its complete 81,335-byte native HTML exactly
matches the retained report digest. All eight output block bodies occur in
the native text after whitespace and paired-quote normalization.

The text is present, but six headings become `agency_label` and `agency_key`
values although they name no agency: `R E P O R T`, `CONTENTS`, two spending
table headings, and two statutory part/subchapter headings. Grouping these
rows by agency would create invented agency entities. Preserve the literal
heading separately and leave unresolved agency identity null. An actual
agency resolver needs its own declared evaluation.

Evidence: `final-witness-results-v2.json`, `supplementary-witnesses.json`,
`fresh-package-bodies/CRPT-119hrpt796-body`, and the actual `report_sections`
rows named by the table assessment. The conversion defect concerns the
meaning assigned to headings, not loss of the sampled body text.

### Activity rules miss bills and attach evidence across hearing blocks

The rendered activity report `CRPT-118hrpt977`, physical page 42 / printed page
32, lists five explicitly numbered H.R. bills and H.Con.Res. 34 under dated
hearing headings. It also contains three H.R. entries with blank numbers. Two
blanks have superscript footnote 1; neither is evidence of H.R. 1.

The output produces eight `held_hearing` rows for four distinct numbered
measures, twice each, and omits H.R. 209 and H.R. 3883. A `HEARING` match in the
closing `PRINTED HEARING 118–5` locator of the February 28 block is associated
with H.Con.Res. 34 in the following May 11 block. The May 11 heading separately
supports the real event; the extra locator match supplies the wrong evidence.
Counting these rows as distinct actions would be misleading.

The bounded repair should respect list and date-block boundaries and avoid
treating printed-hearing identifiers as action assertions. Qualification must
then use a predeclared contextual gold set; `attachment_confidence=single`
is a heuristic label, not measured accuracy.

Evidence: [rendered page 42](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/visual/activity-page42.png),
`final-witness-results-v2.json` and `supplementary-witnesses.json`. This is one
inspected page of one of 41 selected activity reports, not a population recall
estimate.

### Source shape loses locations and committee identities

The native detail for House meeting `119569` supplies an off-site address:
Old Parkland, 3819 Maple Avenue, Dallas, Texas 75219. Its output has null
`location_building` and `location_room`, and no full address/location value.
Preserve the source location object or its address variant. Null here does
not mean the publisher supplied no location.

The retained committee response has 236 top-level rows but 240 unique system
codes when nested subcommittee arrays are included. Four codes appear only
inside parent rows: `sscm39`, `ssju27`, `ssga19`, `ssap07`. They have no rows in
`committees`. Known names and codes match, but the output cannot provide a
complete tree traversal. Either emit only minimally evidenced child identities
or make unresolved child references explicit; do not invent absent detail.

Evidence: `native-audit-results.json` and `final-witness-results-v2.json`.
Meeting detail is partial: 993 of 2,754 selected rows have detail enrichment.
The 2,979 list/detail differences in the independent comparison are exactly
three fields across those 993 rows and were adjudicated as enrichment, not
source contradictions.

### Citation findings are useful but incomplete; budget amounts are not hosted

The 12-page `BUDGET-2027-MSR` PDF contains five printed references to 31 USC
1106. The output has three citation rows on physical pages 9, 10 and 11. It
misses the reverse wording on page 5, “Section 1106 of Title 31, United States
Code,” and a second reverse-worded occurrence on page 9. This gives a concrete
three-of-five witness, not a general recall score.

The same PDF contains Table S-1 with units of billions of dollars: Medicare is
1,209 for 2027 and 7,006 for 2027–2031. The `budget_volumes` table is an index
and citation/read record; those amounts are not numeric hosted facts. Budget
analysis would require a separately qualified extraction that preserves row,
column, period, unit and footnote context.

Evidence: rendered [page 5](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/visual/budget-page5.png),
[page 9](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/visual/budget-page9.png),
[page 10](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/visual/budget-page10.png), and
[page 11](/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/legislative/visual/budget-page11.png), together with
`final-witness-results-v2.json`. All four images were inspected.

### Bodies and joins are materially narrower than their inventories

The primary `bill_versions` output lists 19,687 versions but captures only
four bodies, yielding 66 section nodes. D1 separately captures 600 of 22,064
listed versions and has 6,301 nodes. Three D1 printings of 119-HR-1009 were
checked against fresh, byte-identical native XML. Six substantive subsection
`display_text` values match. The canonical `body` intentionally changes
spacing and should not be shown as a source-faithful display string.

The enacting clause in those trees is reconstructed from publisher stylesheet
boilerplate rather than a literal XML element. That is a documented upstream
choice, not a demonstrated false statement, but the row should distinguish
reconstructed text from source-node text. Complex amendments, tables, bill
HTML/PDF and USLM alternatives remain unqualified by this sample.

The 13-row `hearing_transcripts` output contains capture metadata, not speaker
turns, witnesses, exhibits or complete transcript text. The inspected
`CHRG-119hhrg64242` body contains four named witnesses. A different retained
hearing cover, `CHRG-118hhrg56198`, names twelve distinct H.R. measures, while
`hearing_bill_links` is empty. Scalar null `bill_id` avoids inventing one
primary bill, but the plural join still needs production.

All 881 recorded-vote references in the 118 HR/S native archives exactly match
the output tuples. The selected vote tables are 119th-Congress House only, so
a zero join here cannot establish that the source references are wrong. A
coherent vote/reference generation is necessary before that analytic use.

## Positive checks and explicit limits

| Native source / actual output | Inspected scope and result | What it does not establish |
| --- | --- | --- |
| Nominations list | All 2,204 rows, 24,244 literal comparisons; no mismatch | Nominee-level or full action-history coverage |
| Official committee rosters | All 2,966 assignments, 31,726 comparisons; no mismatch | Historical service or Senate subcommittee seats |
| House communications | 4,956 overlapping native identities, 24,780 comparisons; no mismatch; three detail records also match | Four retained raw identities are absent in a later generation; the original same-run output contains them, so parser deletion is not demonstrated |
| Committee meetings | All 2,754 list identities plus three detailed examples; stated values agree after enrichment adjudication | Complete details, off-site address preservation or complete hearing/bill links |
| Record issues | All 363 list rows, 2,541 comparisons; three nested detail collections also match | Article bodies, speaker turns or daily-digest events |
| Treaties | Both selected detail records, 26 comparisons; no mismatch | Older/suffixed treaties, bodies or legal effect |
| Laws | All 108 native list records, 648 comparisons; one complete PLAW USLM identity/digest witness | Complete law-body semantics or historical laws |
| OLRC classification | All 583 retained second-session lines, 3,498 comparisons; no mismatch | The other session or all current Code text |
| Table III | All 65 output records for two acts, 325 comparisons with native bulk fragments; no mismatch | The full large native bulk population |
| Press releases | All 25 items in two native RSS bodies, 175 comparisons; 11 differences are only edge whitespace | Other committees, full release pages or attachments |
| House roll 119/1/240 | All 430 member positions and vote metadata, 2,156 comparisons; no mismatch | All 577 selected votes or any Senate vote population |
| Legislator crosswalk | 25 genuine source people and 119 terms, 814 comparisons; no mismatch | Full 12,770-person / 45,535-term semantic accuracy |
| Amendments | Three native list records, 24 comparisons; no mismatch | Sponsor, target bill, purpose and other missing detail fields |
| Bill subject reuse | 5,624 overlapping rows match the prior native-censused 118 HR/S values | New raw evidence for the 116th/117th-Congress subject rows |

The prior direct Senate expenditure check inspected nine printed amounts in
three account rows. The later 357-row replay validates correction
reproducibility, not all monetary meaning. The selected 3,272-row output is
bounded by page caps and must not be presented as complete expenditure volumes.

Earlier reviewer errors remain visible in receipts and are explicitly
superseded: the first Table III comparison kept only one native fragment per
act, and the first bill display assembly inserted spaces before punctuation.
The corrected v2 results aggregate all fragments and concatenate inline text
correctly. Report-body differences disappear after documented quote and
whitespace normalization. These are audit corrections, not product defects.

## All 45 output dispositions

The four columns below are **conversion / completeness / shape / usefulness**.
**S** means supported in inspected scope, **D** defect demonstrated, **L**
limited usefulness, and **U** unvalidated. Counts describe the common primary
profile, not a single published release. A conversion S never covers unnamed
fields or uninspected source populations. The row's detailed JSON entry is the
source of its exact evidence scope, practical use and next action.

| Table | Primary rows | Conversion | Completeness | Shape | Usefulness |
| --- | ---: | :---: | :---: | :---: | :---: |
| `congress_bills` | 419,571 | S | L | L | L |
| `bill_actions` | 75,239 | S | L | L | S |
| `bill_committees` | 26,029 | S | L | S | S |
| `bill_publisher_summaries` | 10,806 | S | L | S | S |
| `cbo_cost_estimates` | 1,431 | S | L | S | S |
| `bill_versions` | 19,687 | S | L | L | S |
| `bill_sections` | 66 | S | L | L | S |
| `section_diffs` | 0 | U | L | L | L |
| `section_diff_items` | 0 | U | L | L | L |
| `financial_changes` | 0 | U | L | U | U |
| `section_classifications` | 0 | U | L | L | U |
| `bill_summaries` | 0 | U | L | U | U |
| `diff_summaries` | 0 | U | L | U | U |
| `public_activity_events` | 35,900 | U | L | L | L |
| `amendments` | 7,016 | S | L | L | L |
| `press_releases` | 25 | S | L | L | S |
| `roll_call_votes` | 577 | S | L | S | S |
| `member_votes` | 249,099 | S | L | S | S |
| `members` | 12,770 | S | L | S | S |
| `member_terms` | 45,535 | S | L | S | S |
| `committee_reports` | 105 | S | L | L | S |
| `report_sections` | 1,246 | D | L | D | L |
| `hearing_transcripts` | 13 | S | L | L | L |
| `hearing_bill_links` | 0 | U | L | U | U |
| `laws` | 108 | S | L | S | S |
| `law_code_sections` | 3,632 | S | L | S | S |
| `table3_records` | 65 | S | L | L | S |
| `committees` | 236 | S | L | L | S |
| `committee_assignments` | 2,966 | S | L | S | S |
| `house_communications` | 4,969 | S | L | L | S |
| `committee_meetings` | 2,754 | S | L | L | S |
| `record_issues` | 363 | S | L | S | S |
| `treaties` | 2 | S | L | S | S |
| `nominations` | 2,204 | S | L | S | S |
| `house_activity_reports` | 41 | S | L | L | S |
| `budget_volumes` | 29 | S | L | S | L |
| `document_citations` | 49,935 | S | D | L | S |
| `senate_expenditures` | 3,272 | S | L | S | S |
| `bill_committee_actions` | 12,700 | D | D | L | L |
| `bill_family_archives` | 2 | U | L | L | S |
| `bill_vote_references` | 881 | S | L | S | S |
| `bill_family_backfills` | 0 | U | L | U | L |
| `bill_family_backfill_walks` | 0 | U | L | U | L |
| `committee_report_reads` | 118 | S | L | S | S |
| `bill_subjects` | 20,013 | S | L | L | S |

Empty outputs remain explicit evidence gaps: `section_diffs`,
`section_diff_items`, `financial_changes`, `section_classifications`,
`bill_summaries`, `diff_summaries`, `hearing_bill_links`,
`bill_family_backfills` and `bill_family_backfill_walks`. Secondary D1 diff
rows support only the named uncomplicated sample. Two repeated model calls on
the same three-node fixture do not provide independent classification
qualification; confidence 1.0 does not establish accuracy. No threshold was
invented after observing those results.

## Source routes beyond hosted tables

**Congress.** Native BILLSTATUS, list/detail metadata, publisher summaries,
rosters, selected votes and RSS have scoped direct support. Bill PDF/HTML/USLM
alternatives, Record communication reconstruction and full House repository
XML conversion have no new independent raw/output qualification in this
review. The corresponding readers are not evidence that a hosted dataset was
produced. Standalone CRS files are covered by the other-source work stream;
BILLSTATUS CBO publication entries do not qualify standalone CBO file readers.

**GovInfo.** Two package summaries/MODS/body captures and one PLAW USLM example
provide metadata and byte-preservation support. Raw transcript/report bodies
carry information absent from the hosted metadata. The complete native
PREMIS preservation-metadata example has 46 objects but only three SHA-256
statements; this sprint inspected those bytes, but there is no hosted PREMIS
output table to compare. Missing fixity must remain missing, rather than
becoming an invented hash. Broader MODS, granule, native capture and error-page
routes require route-specific evidence. The print/action defects above concern
interpretation after successful capture.

**U.S. Code.** Classification and selected Table III outputs are directly
supported. Title 1 and Title 5 appendix native XML were inspected, including
transferred-section notes. Their 53 and 19 section elements include source
notes/stubs and do not count operative provisions. A retained Title 53 body is
zero bytes and not a ZIP; it is an unsuccessful capture, not an empty title.
Annual 2024 Title 1 and 2012 Title 40 HTML excerpts were inspected, but no
matching hosted Code-text output exists. Annual edition, appendix, bracketed
labels, status notes and literal ranges must survive. Popular Names and
reference-observation routes remain unvalidated here and have no dedicated
hosted tables.

**Legislators.** The sampled community crosswalk preserves identity and term
values and supports joins. Its selected native excerpts contain genuine
values but are reserialized subsets; they are not complete official historical
membership captures. Complete source revision pins, term overlap checks and
party-transition handling are needed before wide historical attribution.

## Recommended completion sequence

1. Repair the demonstrated agency-label, hearing-block, location and nested
   committee defects with source-native fixtures. Extend citation patterns
   using the observed reverse wording, then measure on held-out material.
2. Adopt the corrected bill reader and build one named generation with a
   manifest of raw inputs, scopes, refusals, parent/child keys and outputs.
   Preserve the existing broad public coverage only when its facts can be
   regenerated or explicitly distinguished from unread values.
3. Complete the useful existing joins: matching vote/reference scopes,
   plural hearing/bill links, date-aware member terms, and release-aware
   law/Code crosswalks. Do not use current committee assignments as historical
   membership evidence.
4. Qualify inferred stages, financial changes, agency resolution, action
   attachment and models against declared criteria before presenting them as
   facts or totals. Empty model tables provide no empirical qualification.
5. Acquire additional bodies or source families only for a named question
   that the existing scope cannot answer. Numeric budget analysis, transcript
   retrieval and current Code text each need explicit output shape and
   acceptance evidence.

This is a completed inventory and evidence review within its declared scope.
It does not certify every source fact, provide complete legislative coverage,
or authorize publication. Software gates and reproducible replays remain
useful implementation checks; neither replaces the native source comparisons.
