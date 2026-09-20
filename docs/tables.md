# Table contracts

`spicy_docs.schemas` states every row shape this repository offers a host, and
one pure `shape_*` function per table that turns a record into that row. The
build brief is
[the table-contract design](research/table-contracts-2026-09-19.md); this page
is what landed.

Everything under `schemas/` is a stdlib-only leaf: no pyarrow, no DeltaTrack, no
`sources.*` or `interpretation.*` imports. A host can therefore import a column
tuple without pulling an HTTP client, a model client or a git dependency. The
one piece that cannot be a leaf — `build_bill_family`, which composes parsed
documents with interpretation findings — lives at
`interpretation/bill_family.py`, where `interpretation` already imports
`sources.congress`.

Every value in a row is a string or NULL: a host publishes these as all-VARCHAR
Parquet read through a DuckDB view, so a typed value is spelled exactly once, in
`schemas/tables.py`'s `text`, `flag`, `json_column`, `joined` and `digest`.

## The tables

`TABLE_CONTRACTS` holds all thirty-four by name. Each carries its columns in
publish order, its identity, its version column — the column a merge prefers the
larger value of when two rows share an identity — a one-sentence grain, and one
sentence per column for the host's data dictionary.

| Table | Grain | Identity | Version column | Columns | Supplier |
| --- | --- | --- | --- | --- | --- |
| `congress_bills` | One row per bill or resolution, as one BILLSTATUS document states it. | `bill_id` | `update_date` | 48 | `interpretation.bill_family` |
| `bill_actions` | One row per action entry in a bill's BILLSTATUS document, in publisher order. | `bill_id`, `action_index` | `action_date` | 14 | `interpretation.bill_family` |
| `bill_committees` | One row per committee or subcommittee a bill reached, as its BILLSTATUS document names it. | `bill_id`, `system_code` | `snapshot_update_date` | 10 | `interpretation.bill_family` |
| `bill_publisher_summaries` | One row per CRS summary the publisher states on a bill, at the version and action it describes. | `bill_id`, `summary_version_code`, `action_date` | `update_date` | 7 | `interpretation.bill_family` |
| `bill_versions` | One row per printing of a bill, per source that supplied it. | `bill_id`, `version_code`, `source` | `version_date` | 35 | `interpretation.bill_family` |
| `bill_sections` | One row per content-bearing node of one bill version, in document order. | `bill_id`, `version_code`, `source`, `match_path`, `body_index` | `version_date` | 18 | `interpretation.bill_family` |
| `section_diffs` | One row per compared pair of consecutive printings of one bill. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source` | `to_version_date` | 19 | `interpretation.bill_family` |
| `section_diff_items` | One row per settled correspondence in one version-pair comparison. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source`, `seq` | none | 29 | `interpretation.bill_family` |
| `financial_changes` | One row per aligned pair of dollar figures in a section whose amounts changed. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source`, `seq`, `amount_index` | none | 12 | `interpretation.bill_family` |
| `section_classifications` | One row per label a model assigned to one section of one printing. | `bill_id`, `version_code`, `source`, `match_path`, `body_index`, `label` | `completed_at` | 14 | `interpretation.bill_family` |
| `bill_summaries` | One row per plain-language summary of one printing of a bill. | `bill_id`, `version_code`, `source` | `completed_at` | 15 | `interpretation.bill_family` |
| `diff_summaries` | One row per model-written summary of the change between two printings of a bill. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source` | `completed_at` | 17 | `interpretation.bill_family` |
| `public_activity_events` | One row per change detected between two runs of the bill family. | `bill_id`, `event_type`, `subject_id`, `occurred_at` | `detected_at` | 6 | `schemas.activity_events` |
| `amendments` | One row per amendment, as the Congress.gov amendment list route states it. | `congress`, `amendment_type`, `amendment_number` | `update_date` | 18 | `sources.congress.listing` (`amendment`) |
| `press_releases` | One row per item in one appropriations committee press-release feed capture. | `release_id` | `observed_at` | 34 | `sources.congress.press_releases` |
| `roll_call_votes` | One row per roll call: the publisher's own tally, and the bill it refers to. | `congress`, `chamber`, `session`, `roll_number` | `vote_date` | 20 | `sources.congress.votes` |
| `member_votes` | One row per member's position on one roll call. | `congress`, `chamber`, `session`, `roll_number`, `member_key` | `vote_date` | 14 | `sources.congress.votes` |
| `members` | One row per legislator in one capture of the community crosswalk. | `bioguide_id` | `observed_at` | 18 | `sources.legislators` |
| `member_terms` | One row per term a legislator served, in the crosswalk's own order. | `bioguide_id`, `term_index` | `observed_at` | 9 | `sources.legislators` |
| `committee_reports` | One row per captured GovInfo committee report package. | `package_id` | `last_modified` | 19 | `sources.govinfo.body_acquisition` |
| `report_sections` | One row per agency block parsed out of one committee report's text. | `package_id`, `seq` | `last_modified` | 12 | `sources.agency_reports.report_blocks` |
| `hearing_transcripts` | One row per captured GovInfo hearing transcript package. | `package_id` | `last_modified` | 20 | `sources.govinfo.body_acquisition`, `sources.congress.listing` (`hearing-detail`) |
| `house_communications` | One row per House executive communication, as the Congress.gov house-communication routes state it. | `congress`, `communication_type`, `number` | `update_date` | 27 | `sources.congress.listing` (`house-communication`, `house-communication-detail`), `interpretation.communication_rin` |
| `committee_meetings` | One row per scheduled committee meeting, as the Congress.gov committee-meeting routes state it. | `congress`, `chamber`, `event_id` | `update_date` | 27 | `sources.congress.listing` (`committee-meeting`, `committee-meeting-detail`) |
| `record_issues` | One row per daily Congressional Record issue, which is also one legislative day per chamber named. | `volume`, `issue` | `update_date` | 17 | `sources.congress.listing` (`daily-congressional-record`, `daily-congressional-record-detail`) |
| `treaties` | One row per treaty document, as the Congress.gov treaty routes state it. | `congress_received`, `number`, `suffix` | `update_date` | 24 | `sources.congress.listing` (`treaty`, `treaty-detail`) |
| `nominations` | One row per nomination or part, as the Congress.gov nomination list route states it. | `congress`, `citation` | `update_date` | 13 | `sources.congress.listing` (`nomination`) |
| `laws` | One row per enacted law the Congress.gov law list route states, with its PLAW USLM citation where captured. | `congress`, `law_type`, `number` | `update_date` | 27 | `schemas.law_tables` |
| `law_code_sections` | One row per line of one OLRC per-Congress classification table: a Code place one public law section touched. | `congress`, `session`, `seq` | `observed_at` | 19 | `schemas.law_tables` |
| `table3_records` | One row per classification record on one act's OLRC Table III page. | `act_key`, `seq` | `observed_at` | 14 | `schemas.law_tables` |
| `committees` | One row per committee or subcommittee the Congress.gov committee list route states, with its detail record where captured. | `system_code` | `update_date` | 21 | `schemas.roster_tables` |
| `committee_assignments` | One row per member per committee or subcommittee seat a chamber roster file lists today. | `congress`, `system_code`, `bioguide_id` | `observed_at` | 20 | `schemas.roster_tables` |
| `document_citations` | One row per occurrence of one cited key in one document's text: the key, the exact text that named it, and the character span it was read at. | `document_key`, `text_sha256`, `cite_kind`, `target_key`, `span_start` | `rule_version` | 17 | `schemas.document_citation_tables`, `interpretation.citations` |
| `house_activity_reports` | One row per end-of-Congress House committee activity report package, with what its print adds. | `package_id` | `last_modified` | 36 | `schemas.document_citation_tables`, `sources.govinfo.bodies` |
| `bill_committee_actions` | One row per action phrase a committee print states about one bill it names in the same sentence: the print's own phrasing, what it maps to, and how reliable the pairing is. | `document_key`, `text_sha256`, `bill_id`, `print_phrasing`, `span_start` | `rule_set_version` | 27 | `schemas.bill_action_tables`, `interpretation.bill_actions` |

Six hundred and seventy columns in all, each with its own sentence.

`congress_bills`'s first ten columns keep the exact order and spelling of the
live `build_congress_bills.COLUMNS` a host already publishes: other repositories
pin that prefix by digest, so it is frozen on purpose and every new column is
appended.

## The bill family is one pass

Twelve of the thirty-four tables come out of a single call to
`build_bill_family`, in an order where no step reads a table an earlier step
published:

1. referral signals from the committee system codes;
2. the stage, signing and money-bill findings;
3. `congress_bills`, `bill_actions`, `bill_committees`, `bill_publisher_summaries`;
4. `bill_versions`, with the version-kind finding;
5. `bill_sections`, one row per flattened node;
6. `section_diffs`, `section_diff_items`, `financial_changes`, over consecutive
   pairs only;
7. `section_classifications` and `bill_summaries`, where a printing carries bill
   text;
8. `diff_summaries`, from the comparisons step 6 already has in hand.

Per bill with A actions, C committees, V versions and S sections per version,
steps 1 to 5 are O(A + C + V + ΣS) with no re-parsing. Step 6 diffs V−1 pairs,
not V², each bounded by the engine's own retrieval gate. Consecutive pairs is
deliberate: the diff is the only superlinear operation in the family.

The three model calls are injected at this boundary rather than as a
`ModelCall`: a caller binds `functools.partial(classify_sections, call=…,
model=…)`, and passing `None` skips the model tables entirely, which is what a
keyless CI run and every hermetic test do.

Nothing is dropped silently. A pair that cannot be compared, a row whose
identity has a null part, a version the summarizer declined — each becomes a
`FamilyRefusal` naming the table, the identity and the reason.

## The Congress.gov index tables are read from a list row and its detail

`schemas/congress_index_tables.py` holds the five tables wave 2 of the
[gap register](research/closing-the-gaps-2026-09-19.md) asked for (A5, A7,
A10). Each is one row per record of one Congress.gov route in
`sources/congress/listing.py`, and four of them take two records at once: the
list row, the only place the publisher states `url`, and the detail record,
which carries everything else. A shaper reads the detail's fields over the
list row's; a list-valued column comes from the detail alone and is NULL when
no detail was read, `[]` when the detail was read and states none. Nothing is
invented for either.

- **`house_communications`** is the regulatory bridge: every typed detail
  field, the referral's system code and date, `is_rulemaking` (the publisher's
  `"True"`/`"False"` strings folded, any other spelling refused), the cited
  `legal_authority`, the matching requirement number, and the RIN as three
  columns (`rin`, `rin_rule`, `rin_matched_text`) from
  `interpretation/communication_rin.py`, whose rule is the data map's own
  measured `RIN: nnnn-XXnn` pattern. Re-measured 2026-09-19 on 18 of the 25
  newest communications inside the day's request budget: 18 carry a dated
  referral, 12 are rulemakings and the same 12 carry a RIN under the measured
  rule and under a relaxed one shaped like the Federal Register validator, 15
  name a requirement (receipt
  `corpora/supply-2026-09-02/receipts/house-communications-rin-2026-09-19/`).
  The Federal Register side needs no change: the source record already carries
  `regulation_id_numbers` and `schemas/federal_register.py` publishes it as
  `regulation_id_numbers_json`, so `communication ↔ rule` is a host-side join
  on `rin`. There is no `senate_communications` table: the Senate detail
  carries the abstract, the referral and the Record date and none of the
  bridge's fields, so it could not fill the same columns without invention.
- **`committee_meetings`** is keyed on the publisher's own address
  `(congress, chamber, event_id)`, with `hearing_jacket` (the first jacket)
  beside `hearing_jackets_json` (every one: the captured hearing's meeting
  names two), `bill_ids_json` from `relatedItems.bills`, and
  `document_urls_json` over witness then meeting documents.
  `hearing_transcripts` gained `event_id`, appended last, filled from the
  `hearing-detail` route's `associatedMeeting.eventId`.
- **`record_issues`** is keyed `(volume, issue)` and doubles as the
  legislative-day calendar: `chambers` is derived from the detail's section
  names by the map's rule (`House Section`, `Senate Section`), and
  `package_id` from the whole-issue link's file stem.
- **`treaties`** carries `package_id` by the map's `CDOC-{c}tdoc{n}` rule on an
  unpartitioned treaty; **`nominations`** is keyed `(congress, citation)`.

## The citation link table stores the span, not the key

`schemas/document_citation_tables.py` is step 1 of the
[PDF-family build order](research/pdf-family-rollup-yield-2026-09-20.md#recommended-build-order):
one shared link table, built first on the House committee activity reports.
The rules are
[`interpretation/citations.py`](../src/spicy_docs/interpretation/citations.py)'s
— thirteen stored kinds out of the sixteen the rollup measured, lifted from that
measurement unchanged, with `tools/analysis/pdf_family_rollup.py` now importing
them so the measurement and the contract cannot disagree about what a bill
number looks like. Re-running `analyze` over the same retained bytes after the
lift reproduces every count, distinct set and resolved system code in the
sidecar; the only differences are per-page timings and the rules' own prose
(`document-citations-2026-09-20/diff-sidecar.txt`).

**Building it corrected the measurement's headline.** The rollup reported 883
distinct bills "beyond the index" for this family, because the index it
compared against was the `published` listing row — seven fields and no
citation among them. The **package MODS** states them, and `GovInfoBodyAcquirer`
already fetches it for every body it reads.

The [MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md) then
measured it properly: all eight sampled activity reports at **full page
depth**, 1,249 pages against the rollup's capped 476.

| Kind | Print-only, eight reports, every page |
| --- | --- |
| `bill_number` | **0 of 1,406** |
| `public_law` | **0 of 174** (the one apparent survivor, `188-11`, is the print's own misprint of 118-11) |
| `usc_section` | **0 of 37** |
| `statutes_at_large` | **0 of 7** |
| `committee_name` | **27 resolved codes**, 71 of 79 rows |
| `rin` | **87** |
| `docket_number` | **38** |
| `gao_product_id` | 5 |
| `cfr_section` | 1 of 1 |
| `federal_register_cite` | 1 |
| `us_reports_cite` | 2 |

**For bills, laws, U.S. Code sections and Statutes pages the MODS is the
authoritative source.** `house_activity_reports.associated_bills_json` and
`.associated_laws_json` are the document-to-target join for those kinds: the
MODS's list is complete, while the print's is a floor bounded by `pages_read`
(39 against 380 on CRPT-118hrpt965). What a citation row adds for them is the
*evidence span* — where in a 282-page print a measure is discussed — which no
GovInfo record states, and which is why `span_start` is part of the identity.

**What the print adds outright** is the committees beyond the one that
submitted the report, the RINs, the agency dockets and the GAO ids. **No
sampled MODS in any collection states a Federal Register cite, a GAO product
id, a CRS report id, an agency docket, a case docket, a U.S. Reports cite or a
dollar figure.** `WHERE stated_by_index IS NOT TRUE` is the consumer's
predicate for those kinds; `stated_by_index` is NULL rather than `false` where
the MODS vocabulary has no element of that shape at all, because "compared and
absent" and "no comparison was possible" are different answers.

The re-check also moves this family out of first place in the build order — the
budget volumes carry 504 print-only public laws against these eight reports'
one — and narrows the activity-report print contract to what the MODS lacks.
It is still worth building, and it is an order of magnitude smaller than the
rollup estimated.

- **`document_citations`** is keyed `(document_key, text_sha256, cite_kind,
  target_key, span_start)`. `target_key` is the hosted target's own spelling —
  `118-hr-1093`, `117-public-263`, `hsfa00` — and where nothing settled it (a
  bill with no stated Congress, a committee name no supplied roster reaches)
  the rule's canonical printed form stands and `target_resolved` is `false`.
  An unsettled key is kept rather than dropped: it is evidence only the print
  holds. `target_rule` says *how* a key was reached, which matters for
  committees: `exact` and `roster_prefix` are roster lookups, `name_prefix`
  and `sibling_prefix` are inferences from this one document's printed text,
  and a consumer wanting only lookups filters on that column.
  **The table is append-only per text digest.** `text_sha256` is in the
  identity because a re-extraction that moves one character moves every offset
  after it, and two extractions must not collide on one identity and silently
  merge; superseded rows are not retired, and a consumer filters to the digest
  `house_activity_reports.text_sha256` states for that document.
  **The aggregate shape is derivable from this one and not the reverse**: one
  row per (document, key) is `GROUP BY document_key, cite_kind, target_key`
  with `COUNT(*)` and `MIN(span_start)`. Storing that instead would make the
  table a lossy copy of the MODS, which is exactly what it must not be.
- **`bill_committee_actions`** is the one table here whose rows carry their
  own measured error rate, and **a consumer must filter on it**:
  `WHERE attachment_confidence = 'single'` is the hosted-quality subset.
  Measured on 60 hand-checked mentions
  (`docs/research/bill-action-relationship-2026-09-20.md`): a `single` row is
  both the right kind and the right bill **83.3%** of the time (30 of 36), a
  `multi` row **50%** (2 of 4). **4,089 of 4,456 rows (91.8%) are `single`**,
  so the restriction costs 8% of the volume. `multi` rows are kept in the
  table as evidence to verify rather than dropped, because a coin-flip row a
  reader can check beats a fact nobody can. `bills_in_sentence` is the raw
  predicate behind the label, published so a consumer can set its own
  threshold.
  **Precision is not recall.** 83.3% is a statement about *what is published*.
  Against what a reader sees stated in the entry, these rules capture
  **59.6%**: the print writes "the bill" after naming it once, sets an en-bloc
  disposition as a sentence about "the measures", and states a committee
  consideration date in a ruled table's column header. A consumer counting
  hearings from these rows is counting a floor, and
  `document_citations.span_start` on the same document and digest is where the
  rest of the evidence is.
  **What this table is for: a subcommittee hearing on a bill is often recorded
  nowhere else.** Asked for 20 sampled bills' whole action lists, the publisher
  has **no counterpart at all** to 10 of the 15 subcommittee hearings these
  prints state — no action, no code, no wording. Markups are stated in full and
  coded (`H15000-B`, `H15001`, `H22000`), so there the print is a second,
  coded source rather than the only one.
  **`billstatus_action_code` carries codes the retained guide does not list.**
  `H21000` for a hearing and the three markup codes appear nowhere in the
  guide's section 3, which says in its own first paragraph that it is
  representational and that no authoritative list exists; 13 of the 35 distinct
  codes in the retained responses are absent from it. They were read off the
  publisher's responses, and `GuideCode.source` records which codes a committed
  fixture can check and which only the receipt can.
- **`house_activity_reports`** takes every descriptive field from the keyed
  GovInfo records and none from the print: the summary's title, Congress,
  session, issue date and **page count**, and the MODS's authoring committee
  `systemCode`, the submitting member's bioguide id, the `<bill>` list with
  each bill's context, the `<law>` list, the `<USCode>` sections and the
  `<congReport>` sibling reports. What the PDF adds is counts — distinct
  bills, laws and Code sections, how many of each the MODS does not already
  state, committees resolved and unresolved, pages read and whether the read
  was capped. `bills_congress_mismatch` is the check on the one assumption the
  rules make: a print writes `H.R. 7806` and never a Congress, so every bare
  designator is stamped with the document's own, and the index comparison runs
  a second time on `(bill_type, number)` alone so a measure from another
  Congress shows as a discrepancy rather than a confidently wrong `bill_id`.
  Measured zero on both packages.

  It overlaps `committee_reports` on seven columns under the same `package_id`
  identity — `package_id`, `congress`, `title`, `date_issued`,
  `last_modified`, `text_sha256` and, but for a rename, the page count — and
  spells the first six identically so a host can join the two.
  `committee_reports` is the generic captured-package row; this is the
  activity report's own. The page count is deliberately **not** spelled the
  same: `committee_reports.page_count` is how many pages *that extraction*
  read, and this table's `stated_page_count` is how many the publisher says
  the document has. On CRPT-118hrpt965 those are 60 and 282, so one name for
  both would have been a silent collision.

`sources/govinfo/bodies.py` grew the index facts those columns need:
`PackageSummary.session` and `.pages`, and `PackageModsIdentity.committees`,
`.laws`, `.usc_sections`, `.reports`, `.members` and `.session` from the MODS
root extension. A chapter-only `<USCode>` block contributes nothing: a chapter
is not a section and has no hosted key.

## What the tests do not establish

Every contract has at least one shaped row built from a fixture in this
repository, and `tests/test_table_contracts.py` proves each of those rows
against its own column tuple. Two of them are not built from a captured
response, and neither says anything about what the publisher serves:

- the diff of three printings uses the constructed division fixtures, because
  they are the only files here that differ in an amount, an addition and a
  move;
- **`hearing_transcripts` is exercised only by a synthetic record**: this
  repository holds no captured CHRG body, so the case reads a captured CRPT
  response under a CHRG package identity. It establishes the two columns that
  differ from `committee_reports` and the chamber lookup, and nothing about
  GovInfo's hearing packages. The table is registered because
  `GovInfoBodyAcquirer` can fill it today, not because it has been filled.
  Its identity is now the package the captured hearing detail (jacket 64431)
  names in its own `formats[].url`, so the `event_id` on that row is the real
  linkage the publisher stated, on a body that is still synthetic.

The five index tables are built from captured list pages (three rows each,
`limit=3`) and the captured details for the rows that have one; where a list
row has no detail the case shapes it list-only, and meeting 119003 shapes from
its detail alone. Those establish the shapes on the day they were captured,
not coverage: `record_issues.chambers` has been exercised on one issue that
names one chamber, and `treaties.package_id` on one unpartitioned treaty.

The two citation tables are built from **two of the eight** activity reports
the rollup read, rebuilt from its retained bytes and never re-fetched, and
that bounds what they establish:

- the normalized text is the rollup's own extract, held to the digest its
  sidecar states, so the counts are measured over the same characters the
  report was — but 179 distinct bills is CRPT-118hrpt968's number, not the
  family's;
- **`CRPT-118hrpt965` is a 60-page read of a 282-page print**, so its counts
  are a floor and `pages_capped` says so. Nothing here establishes what the
  other 222 pages name;
- the committee vocabulary is the two pinned roster excerpts. The Senate `cvc`
  excerpt reaches only the committees its sampled senators sit on, so
  `committees_unresolved` is a floor on what a full roster would settle, not a
  defect count. Two of the four resolution routes — `name_prefix` and
  `sibling_prefix` — are inferences from one document's printed text rather
  than roster lookups, and `target_rule` is what lets a consumer decline them;
- **the two fixtures reach no RIN and no agency docket**, which are the
  family's largest genuinely-new kinds (87 and 38 across the eight reports).
  Both sit in oversight chapters past the rollup's 60-page cap, so these
  fixtures exercise the contract's shape for those kinds and nothing about
  its content. The re-check measured them; this repository holds no fixture
  that does;
- **`bills_congress_mismatch` is zero on both**, which says those two
  documents name no measure from another Congress — not that none ever does;
- **the MODS comparison here is two packages**; the eight-report, full-depth
  figures quoted above are the [MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)'s,
  not this branch's. The request budget for this build was four keyed records
  and all four were spent on these two packages.

## What is still a preserved NULL

| Column | Why | What would fill it |
| --- | --- | --- |
| `congress_bills.statutes_at_large_cite` | The family build sees one BILLSTATUS document and its printings; the citation lives in the PLAW package's USLM `meta`, which the laws rollup acquires once per law — filling it here would fetch every PLAW twice or read another table's output. | The merge joins `laws` on `bill_id` (`statutes_at_large_cite` is published there). |
| `committee_reports.bill_id`, `hearing_transcripts.bill_id` | A package-keyed report is fillable today; the bill linkage is not. | A report-to-bill join. |

## Decision

Recorded in [decisions.md](decisions.md#row-shaping-lives-in-spicy-docs-spicy-regs-converts-and-publishes):
row shaping lives in spicy-docs beside the logic that fills each column, the
consuming repository converts, merges and publishes without re-deriving any
rule, and the bill family is one pass so no hosted rollup reads another's
output.
