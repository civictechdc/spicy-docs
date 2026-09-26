# Table contracts

`spicy_docs.schemas` states every row shape this repository offers a host, and
one pure `shape_*` function per table that turns a record into that row, except
for the [host-shaped Regulations.gov tables](#the-regulationsgov-tables-are-keyed-on-the-publishers-id).
The build brief is
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

`TABLE_CONTRACTS` holds every contract by name. Each carries its columns in
publish order, its identity, its source or processing version column, a
one-sentence grain, and one sentence per column for the host's data dictionary.
The version column's meaning determines whether its values can be ordered;
the column name alone does not establish freshness.

This page states no counts, which went stale here before: ask
`len(TABLE_CONTRACTS)` for the tables and `len(contract.columns)` for a
table's columns.

| Table | Grain | Identity | Version column | Supplier |
| --- | --- | --- | --- | --- |
| `congress_bills` | One row per bill or resolution, as one BILLSTATUS document states it. | `bill_id` | `update_date` | `interpretation.bill_family` |
| `bill_actions` | One row per action entry in a bill's BILLSTATUS document, in publisher order. | `bill_id`, `action_index` | `action_date` | `interpretation.bill_family` |
| `bill_committees` | One row per committee or subcommittee a bill reached, as its BILLSTATUS document names it. | `bill_id`, `system_code` | `snapshot_update_date` | `interpretation.bill_family` |
| `bill_publisher_summaries` | One row per CRS summary the publisher states on a bill, at the version and action it describes. | `bill_id`, `summary_version_code`, `action_date` | `update_date` | `interpretation.bill_family` |
| `cbo_cost_estimates` | One row per bill and CBO publication the bill's BILLSTATUS document names as a cost estimate of it. | `bill_id`, `publication_id` | `pub_date` | `interpretation.bill_family` |
| `bill_versions` | One row per printing of a bill, per source that supplied it. | `bill_id`, `version_code`, `source` | `version_date` | `interpretation.bill_family` |
| `bill_sections` | One row per content-bearing node of one bill version, in document order. | `bill_id`, `version_code`, `source`, `seq` | `version_date` | `interpretation.bill_family` |
| `section_diffs` | One row per compared pair of consecutive printings of one bill. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source` | `to_version_date` | `interpretation.bill_family` |
| `section_diff_items` | One row per settled correspondence in one version-pair comparison. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source`, `seq` | none | `interpretation.bill_family` |
| `financial_changes` | One row per aligned pair of dollar figures in a section whose amounts changed. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source`, `seq`, `amount_index` | none | `interpretation.bill_family` |
| `section_classifications` | One row per label a model assigned to one section of one printing. | `bill_id`, `version_code`, `source`, `seq`, `label` | `completed_at` | `interpretation.bill_family` |
| `bill_summaries` | One row per plain-language summary of one printing of a bill. | `bill_id`, `version_code`, `source` | `completed_at` | `interpretation.bill_family` |
| `diff_summaries` | One row per model-written summary of the change between two printings of a bill. | `bill_id`, `from_version_code`, `from_source`, `to_version_code`, `to_source` | `completed_at` | `interpretation.bill_family` |
| `public_activity_events` | One row per change detected between two runs of the bill family. | `bill_id`, `event_type`, `subject_id`, `occurred_at` | `detected_at` | `schemas.activity_events` |
| `amendments` | One row per amendment, as the Congress.gov amendment list route states it. | `congress`, `amendment_type`, `amendment_number` | `update_date` | `sources.congress.listing` (`amendment`) |
| `press_releases` | One row per item in one appropriations committee press-release feed capture. | `release_id` | `observed_at` | `sources.congress.press_releases` |
| `roll_call_votes` | One row per roll call: the publisher's own tally, and the bill it refers to. | `congress`, `chamber`, `session`, `roll_number` | `vote_date` | `sources.congress.votes` |
| `member_votes` | One row per member's position on one roll call. | `congress`, `chamber`, `session`, `roll_number`, `member_key` | `vote_date` | `sources.congress.votes` |
| `members` | One row per legislator in one capture of the community crosswalk. | `bioguide_id` | `observed_at` | `sources.legislators` |
| `member_terms` | One row per term a legislator served, in the crosswalk's own order. | `bioguide_id`, `term_index` | `observed_at` | `sources.legislators` |
| `committee_reports` | One row per published part of a captured GovInfo committee report package, with the CBO estimate it reprints or refuses. | `package_id`, `part_id` | `last_modified` | `sources.govinfo.body_acquisition`, `interpretation.cbo_estimates` |
| `report_sections` | One row per heading block parsed out of one committee report part's text. | `package_id`, `part_id`, `seq` | `last_modified` | `sources.agency_reports.report_blocks` |
| `hearing_transcripts` | One row per captured GovInfo hearing transcript package. | `package_id` | `last_modified` | `sources.govinfo.body_acquisition`, `sources.congress.listing` (`hearing-detail`) |
| `house_communications` | One row per House executive communication: the Congress.gov house-communication routes where the publisher decomposes it, the Congressional Record entry it printed where the publisher does not. | `congress`, `communication_type`, `number` | `update_date` | `sources.congress.listing` (`house-communication`, `house-communication-detail`), `sources.congress.record_communications`, `interpretation.communication_rin` |
| `committee_meetings` | One row per scheduled committee meeting, as the Congress.gov committee-meeting routes state it. | `congress`, `chamber`, `event_id` | `update_date` | `sources.congress.listing` (`committee-meeting`, `committee-meeting-detail`) |
| `record_issues` | One row per daily Congressional Record issue, which is also one legislative day per chamber named. | `volume`, `issue` | `update_date` | `sources.congress.listing` (`daily-congressional-record`, `daily-congressional-record-detail`) |
| `treaties` | One row per treaty document, as the Congress.gov treaty routes state it. | `congress_received`, `number`, `suffix` | `update_date` | `sources.congress.listing` (`treaty`, `treaty-detail`) |
| `nominations` | One row per nomination or part, as the Congress.gov nomination list route states it. | `congress`, `citation` | `update_date` | `sources.congress.listing` (`nomination`) |
| `laws` | One row per enacted law the Congress.gov law list route states, with its PLAW USLM citation where captured. | `congress`, `law_type`, `number` | `update_date` | `schemas.law_tables` |
| `law_code_sections` | One row per line of one OLRC per-Congress classification table: a Code place one public law section touched. | `congress`, `session`, `seq` | `observed_at` | `schemas.law_tables` |
| `table3_records` | One row per classification record of one act in OLRC's Table III, read from its page or the bulk file. | `act_key`, `seq` | `observed_at` | `schemas.law_tables` |
| `committees` | One row per committee or subcommittee the Congress.gov committee list route states, with its detail record where captured. | `system_code` | `update_date` | `schemas.roster_tables` |
| `committee_assignments` | One row per member per committee or subcommittee seat a chamber roster file lists today. | `congress`, `system_code`, `bioguide_id` | `observed_at` | `schemas.roster_tables` |
| `document_citations` | One row per occurrence of one cited key in one document's text: the key, the exact text that named it, and the character span it was read at. | `document_key`, `text_sha256`, `cite_kind`, `target_key`, `span_start` | `rule_version` | `schemas.document_citation_tables`, `interpretation.citations` |
| `house_activity_reports` | One row per end-of-Congress committee activity report package, House or Senate, with what its print adds; the table's name predates its Senate rows. | `package_id` | `last_modified` | `schemas.document_citation_tables`, `sources.govinfo.bodies` |
| `budget_volumes` | One row per published volume of the President's budget, with what its print adds to its own index. | `package_id` | `last_modified` | `schemas.budget_volume_tables`, `sources.govinfo.bodies` |
| `senate_expenditures` | One row per ruled row of one ruled table on one page of a Report of the Secretary of the Senate, with the cells exactly as the print states them and the roles its own header band names. | `package_id`, `file_name`, `page`, `table_ordinal`, `row_ordinal`, `text_sha256` | `extraction_rule_version` | `schemas.senate_expenditure_tables` |
| `bill_committee_actions` | One row per action phrase a committee print states about one bill it names in the same sentence: the print's own phrasing, what it maps to, and how reliable the pairing is. | `document_key`, `text_sha256`, `bill_id`, `print_phrasing`, `span_start` | `rule_set_version` | `schemas.bill_action_tables`, `interpretation.bill_actions` |
| `hearing_bill_links` | One row per bill one source states a hearing was held on or noticed for: the pair, the source that stated it, and the committee-and-date key the statement was checked against. | `package_id`, `bill_id`, `link_source` | `link_rule_version` | `schemas.hearing_bill_link_tables`, `interpretation.hearing_bill_links`, `sources.congress.house_committee_repository` |
| `dockets` | One row per Regulations.gov docket, the folder an agency opens for one rulemaking or other action. | `docket_id` | `modify_date` | the host, through its copy of `schemas.regulations`' extract |
| `documents` | One row per document an agency posted on Regulations.gov: a rule, notice or supporting material. | `document_id` | `modify_date` | the host, through its copy of `schemas.regulations`' extract |
| `comments` | One row per public comment posted on Regulations.gov. | `comment_id` | `modify_date` | the host, through its copy of `schemas.regulations`' extract |

Every column carries its own sentence.

### Version equality and replacement

A publisher date or an explicitly ordered revision can order comparable rows.
A rule digest cannot: `bill_committee_actions.rule_set_version` and
`hearing_bill_links.link_rule_version` establish equality of the recorded rule
sets, not which set is newer. A correction can produce a lexically smaller
digest. Select the intended input generation before merging; a successful
correction supersedes its prior regardless of digest spelling. Conflicting
same-key rows from different rule generations in one input require an explicit
generation choice or refusal, not a maximum digest.

A publisher date orders rows only in a sortable spelling.
`roll_call_votes.vote_date` and `member_votes.vote_date` keep each chamber's
literal (`8-Sep-2025`), which sorts lexicographically, not by time; the
appended `roll_call_votes.vote_day` is its ISO reading
([vote day](sources/congress-votes.md#vote-day)). Rows published before the
column existed carry NULL until a host backfills them, so until then neither a
merge ordered on `vote_day` nor a join from `bill_vote_references` through
`vote_id` to `vote_day` is complete; the version column stays `vote_date`.

The current SpicyRegs `transforms.table_merge.merge_table` already ranks fresh
rows before prior rows (`_src DESC` before the version). Its same-input
tie-break still orders the version string, so it cannot establish chronology
between two different rule digests. This source definition does not change that
host behavior or make a mixed-generation input safe. The print and hearing
hosts instead replace the scopes they successfully reevaluate and checkpoint
the processing identity.

### What shared checks establish

`TableContract.checked` checks the declared column set and string-or-NULL
storage; `key` separately checks identity presence and non-NULL components.
These definitions contain no per-column logical-type declarations. Dates,
numbers, booleans and JSON are not inferred from names or prose, and passing
`checked` is not semantic validation of those values. Adding such declarations
requires a source/host ownership decision and evidence for each declared type.

The explicit `json_column` helper produces compact, sorted JSON. It refuses
non-finite numbers at any nesting depth and circular containers with
`TableContractError`; unsupported object types still raise `TypeError`.
The bill-family admission path records these as named row refusals. Other
callers retain their existing refusal or abort behavior. Finite JSON bytes,
including Unicode escaping, floating-point spelling and key order, are unchanged.
`read_json_column` remains a convenience decoder, not strict row validation.

`congress_bills`'s first ten columns keep the exact order and spelling of the
live `build_congress_bills.COLUMNS` a host already publishes: other repositories
pin that prefix by digest, so it is frozen on purpose and every new column is
appended.

`law_code_sections` and `table3_records` append `usc_section_key`: the
printed `usc_section` lower-cased, with every dash spelling an ASCII hyphen
(`schemas.tables.usc_section_key`), the spelling RefSpec's section oracle keys
on. Join on it, never on the printed column, and fold the other side the same
way. **The citation side is already folded by the same function:**
`document_citations`' `usc_section` (rule 002) keys through the citation
grammar, which folds each section through `usc_section_key`, so
`{usc_title}-{usc_section_key}` joins its `target_key` as published. Only rows
published under rule 001 keep the printed case (`26-199A`) and need the fold
first. Rows published before the column carry NULL until their scope is
captured again
([decision](decisions.md#us-code-section-join-keys-are-lower-cased-on-both-sides)).

`laws` appends `uslm_citable_as_json`, `uslm_reason` and
`uslm_reader_version`. Every attempted PLAW read states its outcome:
`captured_partial` is a validated file that names no Statutes at Large
citation (a private law, whose own `citableAs` is kept), `captured_refused` a
`200` body the reader refused (another law's file, or not native USLM), and
`request_failed` a read that established nothing. `not_requested` means no
request was made. `table3_records.act_section` is NULL when a meaningful source
row leaves its label blank; the `table3-native-rows-v2` reader keeps such rows
instead of dropping them.

`report_sections` preserves the source heading in its appended `heading`
column. The older `agency_label` and `agency_key` columns remain in place but
are NULL: the heading splitter does not resolve agency identities. Actual
agency names survive as literal headings alongside generic section titles.
`preamble` and `full_report` blocks have no source heading; the legacy parser's
`Full Report` sentinel is not copied into the new column. Body text, patterns,
spans and row identity are unchanged. Hosts must include
`REPORT_SECTION_READER_VERSION` from `schemas.committee_report_tables` in
their processing checkpoint and regenerate old rows; publisher modification
timestamps cannot establish that this correction has run.

## The Regulations.gov tables are keyed on the publisher's id

`dockets`, `documents` and `comments` are shaped by the host, from Mirrulations
records through its copy of the extract in `schemas.regulations`, so they have
no `shape_*` here. Each contract lists the extract's columns in its order, then,
on documents and comments, the host's `pdf_extraction_results_json`. The record
types here, and the `public_tables` and public-comment profiles built on them,
still lack that column; the contracts state what is published.

Each identity is the publisher's own id, because a document filed under two
agencies is still one document (DocSpec decision 0004).

### Every one-column identity declares its member-key spelling

DocSpec admits a generation by reference only on a member-key spelling this
package declares (its decision 0007, ruling R6). `TableContract.key_spelling`
names an entry of `schemas.tables.KEY_SPELLINGS`, and `spelled_key(row)` is the
Python reference DocSpec tests its compiled SQL against. Every contract with a
one-column identity declares `value/1`, the value itself; a composite declares
none until its spelling is decided. An entry never changes: a new rule gets a
new `name/version`, and adopting it is an explicit re-key.

### What the key measurement can and cannot see

The ids were checked on 2026-09-25 over the fork host's public objects, each
local copy bound to its object by recomputing the multipart ETag.

| Table | Objects (SHA-256, Last-Modified) | Rows | NULL, empty or duplicate ids |
| --- | --- | --- | --- |
| `dockets` | `308b35c6…` 20:51Z, `07bf427e…` 19:54Z, `680b86ad…` 10:11Z | 279,380; 279,351; 279,336 | 0 |
| `documents` | `d7487819…` 20:51Z, `ffa2da6c…` 19:54Z, `ff502e4b…` 10:11Z | 2,002,831; 2,002,688; 2,002,562 | 0 |
| `comments` | `bf81f764…` 18:15Z, `b90e1105…` 10:11Z | 26,303,691; 26,303,691 | 0 |

DuckDB 1.5.5 counted NULL and empty ids and grouped the id column
(`GROUP BY id HAVING count(*) > 1`) under a 2 GB memory limit. On the 19:54 and
18:15 objects Polars, a different reader, counted distinct ids per hash bucket
against the footer's row count, and agreed. Both caught a planted duplicate and
a planted NULL.

- **Duplicates in `dockets` and `documents` could not have been found.** The
  host's merge (`merge_staging_files`) keeps one row per id, the newest by
  `modify_date`, so those zeros hold by construction. `comments` is exported
  from the host's Iceberg catalog with no such step, and that catalog can hold
  physical duplicates (spicy-regs `sources/iceberg.py`, `merge_comments`), so
  its zero is a measurement that could have failed.
- **What every table's check does establish:** every id matches
  `^[A-Za-z0-9_.-]+$`, so none needs escaping in JSON framing, and none differs
  from another only by case.

### `modify_date` versions only the publisher's fields

`modify_date` is an ISO 8601 `Z` instant on every row of each table's newest
object above, so it orders chronologically as text. It is the publisher's
instant. The host fills `text_content`, `text_extraction_status` and
`pdf_extraction_results_json` in its own PDF and derived-text steps without
changing it, so a row's value can change while its version does not. For
DocSpec that is ruling R5's churn, and a declared projection without those
columns is the candidate remedy. In the 19:54 and 20:51 `documents` objects all
three columns are NULL on every row.

The fixture rows and their selection are in
`tests/fixtures/regulations_gov_tables/README.md`.

## The bill family is one pass

Every table `BillFamilyTables` carries comes out of a single call to
`build_bill_family`, in an order where no step reads a table an earlier step
published:

1. referral signals from the committee system codes;
2. the stage, signing and money-bill findings;
3. `congress_bills`, `bill_actions`, `bill_committees`, `bill_publisher_summaries`,
   and `cbo_cost_estimates` off the same document;
4. `bill_versions`, with the version-kind finding;
5. `bill_sections`, one row per flattened node;
6. `section_diffs`, `section_diff_items`, `financial_changes`, over consecutive
   pairs only, in `sources.congress.bill_versions.printing_order`: publisher
   date, with a dateless enrolled printing placed by its stage;
7. `section_classifications` and `bill_summaries`, where a printing carries bill
   text;
8. `diff_summaries`, from the comparisons step 6 already has in hand.

Per bill with A actions, C committees, V versions and S sections per version,
steps 1 to 5 are O(A + C + V + ΣS) with no re-parsing. Step 6 diffs V−1 pairs,
not V², each bounded by the engine's own retrieval gate. Consecutive pairs is
deliberate: the diff is the only superlinear operation in the family.

`build_bill_printings` runs steps 4 to 8 alone, for a caller that reads bodies
apart from the status (the [BILLS bulk zips](sources/congress-bulk-bills.md)):
it takes every listed printing of one bill and a `context` set of
`(version_code, source)` printings that emit no rows of their own -- placeholders,
and held printings whose documents are there only to be compared with a newly
read neighbour. Its rows equal `build_bill_family`'s for the same printings; the
plain-language summary, which needs the status's stage and money-bill finding,
stays with the family.

The three model calls are injected at this boundary rather than as a
`ModelCall`: a caller binds `functools.partial(classify_sections, call=…,
model=…)`, and passing `None` skips the model tables entirely, which is what a
keyless CI run and every hermetic test do.

Nothing is dropped silently. A pair that cannot be compared or whose order no
date or stage establishes, a row whose identity has a null part or repeats one
already admitted, a printing whose identity repeats an earlier printing's
(refused whole, never mixed into it), a version the summarizer declined — each
becomes a `FamilyRefusal` naming the table, the identity and the reason. A
numbered reprint carries its own package suffix as its `version_code`
([decision](decisions.md#a-numbered-reprint-is-its-own-printing)). A section is
keyed on its `seq` within its printing, because `match_path` is a
cross-version key that repeats inside one printing
([decision](decisions.md#a-bill-section-is-keyed-on-its-position-and-a-dateless-enrolled-printing-is-paired-by-its-stage)).

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

  **It carries two eras under one identity.** Congress.gov decomposes a House
  executive communication only from the 114th Congress. For the ten before it
  the Congressional Record printed the same sentence — the publisher's
  `abstract` *equals* the printed entry under four named normalizations — and
  `sources/congress/record_communications.py` reads it back into the same
  columns ([research](research/executive-communications-backfill-2026-09-20.md)
  §5, [score](research/record-communications-overlap-2026-09-20.md)).
  `source_route` says which produced a row (`congress-gov-detail` or
  `congressional-record-granule`), `record_package_id` and `record_granule_id`
  name the CREC granule that printed it, `record_entry_text` keeps the exact
  sentence, and `reconstruction_rule_version` names the rule. Three rules hold
  across the two eras:

  1. a reconstructed row's `url` is **NULL** — the detail route 404s for every
     pre-114th communication, so writing one would assert a route that refuses;
  2. the merge prefers **provenance over `update_date`**: for one identity a
     `congress-gov-detail` row wins over a `congressional-record-granule` row
     whatever `update_date` says, so a later publisher backfill overwrites the
     reconstruction and never the reverse; within one `source_route` the larger
     `update_date` still wins;
  3. an **unresolved field is NULL beside the retained sentence**, never a
     guess. `submitting_official` and `submitting_agency` are the measured
     case. They are one boundary decision, scored on one declared denominator —
     the rows the split rule answered and the publisher decomposed — and on it
     the pair fails on **both** sides (agency 88.4%, official 85.3% held out,
     against a 90% threshold declared before the run). Neither publishes, and
     the whole from-clause survives inside `record_entry_text`.
     `is_rulemaking`, `matching_requirement_number` and `session` are NULL for
     the plainer reason that the Record states none of them.
     `referral_system_code` is NULL because the resolver from a printed
     committee name to a `committees.system_code` is **not built**.

  The referral's *names* are published: `referral_committee_name` and
  `committees_json` carry the Record's own words, which are the committee's
  name on the day. They are not the publisher's spelling of the same committee
  — 71.5% agreement under a normalized comparison, because the 116th Record
  prints *Oversight and Reform* where Congress.gov states *Oversight and
  Government Reform Committee* — so nothing joins on them.

  Scored against the publisher on 256 rows of the overlap era, 144 of them
  held out: `abstract` 97.9%, `legal_authority` 99.1%, `rin` 100%,
  `report_nature` 95.8%, `referral_count` 95.1%.
- **`committee_meetings`** is keyed on the publisher's own address
  `(congress, chamber, event_id)`, with `hearing_jacket` (the first jacket)
  beside `hearing_jackets_json` (every one: the captured hearing's meeting
  names two), `bill_ids_json` from `relatedItems.bills`, and
  `document_urls_json` over witness then meeting documents.
  `hearing_transcripts` gained `event_id`, appended last, filled from the
  `hearing-detail` route's `associatedMeeting.eventId`.
  `committee_reports` and `hearing_transcripts` then append
  `body_completeness` (`publisher_placeholder` when the native text is the
  publisher's notice that the document is only in the PDF, `pdf_extracted` for
  text from a PDF, `not_flagged` otherwise; no value asserts completeness) and
  `text_derivation`, the named derivation behind `text_sha256`.
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

**Which CRPT packages are activity reports is a title rule, and the package
owns it.** Nothing in a package id, its `docClass` or its MODS separates an
end-of-Congress activity report from any other committee report in the same
collection walk; only the title does.
[`sources/govinfo/activity_reports.py`](../src/spicy_docs/sources/govinfo/activity_reports.py)
holds it, so a host publishing this table imports the rule instead of
restating it — and the analysis tools select with the same object, the
arrangement the citation rules already have. It matches a *phrase* and never
the bare word `activit`: on the 71 CRPT packages of the measured window, 20
titles carry the word and the rule matches 15, rejecting two
`DIRECTING THE SECRETARY … ACTIVITIES` resolutions and one
`PROVIDING FOR CONSIDERATION … FOREST MANAGEMENT ACTIVITIES`. **Read 15 as a
floor**: it also misses two real activity reports that name a Congress and no
committee (`SUMMARY OF ACTIVITIES ONE HUNDRED EIGHTEENTH CONGRESS`,
`REVIEW OF LEGISLATIVE ACTIVITY DURING THE 118TH CONGRESS`), and the rule is
not widened to reach them because dropping the committee requirement readmits
the three above (receipt `activity-report-title-rule-2026-09-20/`).

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
- **`bill_committee_actions`** distinguishes single-bill and multi-bill
  sentences. `WHERE attachment_confidence = 'single'` selects the class with
  the higher measured precision; it does not certify an individual finding.
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
  was capped. A print writes `H.R. 7806` and never a Congress beside it, so
  every bare designator is stamped with `covered_congress` -- the Congress the
  report states it covers, from its title, cover or front matter
  (`covered_congress_source`), kept beside the summary's filing `congress`
  because a Senate report is filed in the next Congress -- except where the
  print states a bill's own: set right after it (`H.R. 6752, 115th Cong.`),
  else a Congress subheading over it (`116th Congress` over a predecessor
  bill's history, until the next entry). No statement, no bill key. `bills_congress_mismatch` runs the index comparison a second time on
  `(bill_type, number)` alone, so a bill the MODS keys under another Congress
  shows as a discrepancy -- on a Senate report, the MODS's own filing-Congress
  stamp. Zero on both House fixture packages.

  It overlaps `committee_reports` on seven columns under the same
  `package_id` — `package_id`, `congress`, `title`, `date_issued`,
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

## A hearing is held on a list, so the linkage is a table and not a column

`schemas/hearing_bill_link_tables.py` hosts what the
[hearing-to-bill measurement](research/hearing-bill-linkage-2026-09-20.md)
found (198 requests, receipt `hearing-bill-linkage-2026-09-20/`). It reopened
gap [A2](research/closing-the-gaps-2026-09-19.md) without contradicting it: no
hearing states a `PRIMARY` bill, and a `BODY` mention is confirmed by nothing —
both re-measured and both still true. What was wrong was the conclusion. Those
two findings answer the question a committee *report* answers; a hearing is not
filed against one bill, it is convened on a **list**, and four publishers state
that list. **`hearing_transcripts.bill_id` stays NULL for a new reason**: not
"no source states it" but "a scalar column is the wrong shape", with twelve
bills on `CHRG-118hhrg56198`.

- **`hearing_bill_links`** is keyed `(package_id, bill_id, link_source)`, and
  the **source is in the identity on purpose**. Two publishers naming the same
  pair is the strongest evidence in the measurement — where the MODS cover and
  the House agenda agree the bill's own action list confirms **18 of 18** — so
  one row per pair would delete exactly the agreement worth keeping. On the one
  hearing this repository holds both records for, 8 cover bills and 8 agenda
  bills are **16 rows over 9 distinct bills**.
  `committee_system_code` and `held_date` are the MODS's own
  `congCommittee` authority id and its one stated `heldDate` (NULL when a
  compiled volume states several; `held_dates_json`, appended last, keeps every
  native date in source order), which are the join key a
  bill-side confirmation needs and the pair an agenda row had to match before
  it was written. `event_id` is the `associatedMeeting.eventId` the row was
  reached through, NULL on a cover row whose caller read no hearing detail.
  `evidence_rule` and `evidence_text` are the statement the rule actually read,
  so a wrong row is readable without the record in hand.
- **`link_source` is sealed and additions-only**, and names all five measured
  sources from the start so taking one later is an addition rather than a
  rename: `mods_cover` and `docs_house_br` are implemented;
  `daily_digest_entry`, `congress_related_items` and `front_matter_designator`
  are measured, ranked and not yet filled.
- **`relation` separates what happened from what was scheduled.** A
  `mods_cover` row is `held_on`: the bill's own *Hearings Held* action by that
  committee on that date confirms **19 of 20** pairs, the one exception being a
  bill with three actions in total, and six set-comparisons against an
  independently produced list are **6 of 6 set-equal over 55 bills**. A
  `docs_house_br` row is `noticed`, because the agenda states intent: an
  agenda-only bill is confirmed 1 of 18, **contradicted 1** (`118-hr-2997`,
  noticed for 2023-05-23 and heard 2023-06-22) and unverifiable 16. Publishing
  both as `held_on` would publish a calendar as a record of events.
- **Precision is not recall, and recall is unmeasured.** 2 of 20 sampled House
  hearings of the 118th carry a `COVER` bill at all, and no probe classified
  hearing type, so that is a floor over all hearings and not a rate over
  legislative ones. **0 of 3 sampled Senate hearings** carry one — those MODS
  state no bill in any context while Congress.gov states one to two for each —
  so a missing row for a Senate hearing is indistinguishable from a correct
  silence on an oversight hearing. The per-chamber, per-Congress census is the
  open measurement; `daily_digest_entry` is the route that would close it.

**The two readers cost one request between them.**
`interpretation/hearing_bill_links.py` holds both rules and the derived
`link_rule_version` digest.

- `mods_cover` costs **nothing**: `GovInfoBodyAcquirer` already fetches the
  package MODS for every body it reads, and `PackageModsIdentity` gained
  `held_date` so the join key comes off the same record.
- `docs_house_br` costs **one keyless GET per event**, at the static address
  `sources/congress/house_committee_repository.py` builds:
  `docs.house.gov/meetings/{CMTE}/{SUBCMTE}/{yyyymmdd}/{EventID}/{TYPE}-{congress}-{SUBCMTE}-{yyyymmdd}.xml`.
  The event page offers the same XML only as an ASP.NET `__doPostBack`, and the
  two are **byte-identical, 2 of 2 by SHA-256** — checked by digest rather than
  by status, because this publisher serves its own pages at 200. The
  `EventID`/`eventId` equality that makes the address reachable from
  `hearing_transcripts.event_id` is a measured regularity neither publisher
  documents, so the **committee-and-date identity check runs per row** and
  refuses rather than linking.
- **A type-less `<legis-num>` is refused, not guessed.** Some committees post
  `226` beside `BILLS-118226ih.pdf`, neither of which states whether the
  measure is a House or a Senate one; the long-standing community scraper
  defaults that to `hr`. Here the rule falls through to the `<description>`,
  which usually spells the designator in full, and refuses with a stated reason
  when nothing does. **36 of 46** retained `BR` documents resolve; the 10 that
  do not are the `BILLS-118Xih.pdf` discussion drafts, which name a measure
  with no number at all.

Both figures are reproduced from the receipt's retained bytes through this
product code by `tools/analysis/hearing_bill_links_recompute.py`, which makes
no request.

## The budget volumes are the family whose print outruns its index

`schemas/budget_volume_tables.py` is what the
[MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)'s revised build
order puts first, and it is the mirror image of the activity reports. Read at
full page depth, the eight retained volumes name **504 public laws of 518, 97
U.S. Code sections of 922 and 13 CFR parts of 18 that their own MODS does not
state** — the largest real citation yield in the corpus, where the activity
reports' is zero for the same kinds.

`budget_volumes` is the document row and `document_citations` is still the only
link table: a budget citation is a `document_citations` row with
`document_kind` `budget_volume`, not a second table. The document row takes
every descriptive field from the keyed records — the summary's title, issue
date and **page count**, and the MODS's `<law>`, `<USCode>` section, `<cfr>`
part, `<statuteAtLarge>` and `<bill>` lists — and the print contributes counts
only.

Three things about this family are not true of the others.

- **There is no Congress anywhere.** A BUDGET package id carries a fiscal year
  and a part, and a BUDGET summary states no `congress` field at all. So the
  print's bill key is the congress-free `HR7806` and the MODS's is
  `119-hr-7806`, and those are not comparable. `budget_index_stated_keys`
  drops `bill_number` from the comparison rather than publishing a `false`
  no comparison earned, so those rows carry NULL and the MODS's own bill list
  is published whole in `associated_bills_json`. The weaker comparison that
  *is* possible is published as a count and labelled as one:
  `distinct_bills` and `distinct_bills_beyond_index_congress_blind` reduce both
  sides to `{bill_type}-{number}`, which is how 6 of the 8 distinct printed
  bills across the eight volumes are print-only. Neither column is a join key —
  `congress_bills.bill_id` cannot be built from either side — and saying so in
  the column name is what stops the family's own headline from being read as
  one.
- **The volumes are long, so the read depth is the finding.** `BUDGET-2027-APP`
  is 1,340 pages; read to 60 it names 29 public laws and read whole it names
  490. `pages_read`, `stated_page_count` and `pages_capped` are what keep a
  count from being read as the volume's when it is a window's. The fixture
  `BUDGET-2027-BUD` is the small version of the same fact: 2 print-only laws
  at 60 pages, 3 across all 92.
- **The fiscal year is stated twice and held equal.** The package id carries
  it and the MODS states it as `<field name="Fiscal Year">`; the column
  publishes the MODS's and a test asserts the two agree on both fixtures,
  because a single source would agree with itself whatever it said. It is not
  the issue year: `BUDGET-2026-MSR` was issued 2025-09-05.

Reaching these packages at all needed the package-id grammar widened to
`BUDGET-*` and `GPO-CDOC-*`, which is [its own decision
record](decisions.md#budget-and-the-gpo-prefixed-cdoc-reprints-join-the-package-id-grammar):
before it, `GovInfoBodyAcquirer` refused both collections and the measurement
proved their identity by a fallback weaker than the sealed validators.

## The Senate expenditure table carries the cells, not a guess about them

`senate_expenditures` is step 4 of the same build order and the one PDF-only
family whose value is a **table**: its citation yield against the package MODS
is zero, and a full read of the eight sampled volumes carries 65,261 distinct
dollar figures over 161,536 rows against a publisher listing that states two
fields. The source is the
[Report of the Secretary of the Senate](sources/senate-secretary-report.md);
what its ruled tables are was
[measured first](research/senate-expenditure-tables-2026-09-20.md), and the
measurement changed the design.

**The print draws three grids and rules only one of them into cells.** Of 227
ruled body rows across 160 measured pages, the 56 in the
`appropriation_summary` grid carry all nine cells — account title, account
number and six money columns, each stacking one amount per fiscal year — while
every one of the other 171 carries exactly **one** cell of ten or of seven. A
payment is a line inside that cell, not a ruled row, even though the print's
own header band above it names `DOCUMENT NO.`, `DATE POSTED`, `PAYEE NAME`,
`DESCRIPTION` and `AMOUNT ($)`.

So the table has **no `payee_name`, `document_number`, `date_posted` or
singular `amount` column**. Filling them would mean splitting a blob on an
unmeasured guess, and a column NULL on every row of every fixture is the defect
the design brief names for `hearing_transcripts`. What lands instead:
`cells_json` holds the row exactly as the print states it, newlines and all;
`column_headers_json` holds the role the print's own header band gives each
column; `cells_ruled` is the consumer's predicate for the rows whose cells are
separate facts. Splitting the payee block is a text rule for `interpretation/`
and it is unmeasured.

- **The governing header band is the nearest one, not the table's first.** An
  `organization_detail` table carries two bands: column 0 goes from the office
  block to `DOCUMENT NO.` and `DESCRIPTION` moves from column 3 to column 7
  inside one table. That is also why there is no separate
  `senate_expenditure_tables` companion — there is no one header row for it to
  hold.
- **`file_name` is in the identity.** One package publishes the whole report
  and each of its parts as separate PDFs, and `GPO-CDOC-119sdoc3.pdf` and
  `GPO-CDOC-119sdoc3-1.pdf` extract byte-identical text over their first sixty
  pages. Keying on `(package_id, page, table_ordinal, row_ordinal)` alone would
  have collided them silently.
- **`text_sha256` is in the identity for the same reason it is in
  `document_citations`**: a re-extraction that finds one more ruled band moves
  every ordinal after it, and two extractions of one page must not merge.
- **The office, the funding year and the printed page come from the page text,
  not the table.** The page states the printed page label on 139 of 139 table
  pages and the office block on 83; the table's own first cell states the office
  on 21, all of which the page text also states. On the other 56 — continuation
  pages — the print states no office and the column is NULL, and a consumer
  forward-fills in `printed_page` order. This is why the shapers take a
  `TableObservation` **plus the page text**.
- **Five of those 83 pages state a funding-year *span*** (`Funding Year
  2021-2023`, the Chaplain's blocks at B-48 to B-55), so `funding_year` carries
  the first year either way and `funding_year_end` the second, NULL for a single
  year. This is load-bearing rather than cosmetic: a rule matching one year left
  those five pages with no office, and the documented forward-fill then charged
  their rows to the *preceding* office — a wrong attribution, which is less
  visible than a missing value.
- **The amounts are decimal strings and never a canonical key.** The
  `dollar_amount` canonical the rollup used erases the decimal separator and was
  measured colliding, so a dollar figure is not a join key until that is fixed.
- **Acquisition is wired up.** `GovInfoBodyAcquirer` supports the measured
  `BUDGET-*` and `GPO-CDOC-*` package-id forms with summary and MODS identity
  checks. See the [integration decision](decisions.md#budget-and-the-gpo-prefixed-cdoc-reprints-join-the-package-id-grammar)
  and [supported identifiers and renditions](sources/govinfo-bodies.md).
  The shapers still take table observations and page text.

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

The check that a value a description names in backticks appears in the code
that fills its table reads, for a table shaped here, the module that also holds
that table's sentences, so it cannot catch a value named only in prose. With the
prose removed some contracts fail it, on backticked references to tables,
columns, modules and templates that are not values; applying
`_without_contract_prose` to every table lists them. Only the three
Regulations.gov tables are held without their prose, to their extract and to
the rows the host published.

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
  documents name no measure from another Congress — not that none ever does.
  The Senate report fixture (CRPT-118srpt99) is where it is nonzero;
- **the MODS comparison here is two packages**; the eight-report, full-depth
  figures quoted above are the [MODS re-check](research/pdf-yield-mods-recheck-2026-09-20.md)'s,
  not this branch's. The request budget for this build was four keyed records
  and all four were spent on these two packages.

`hearing_bill_links` is built from **four retained publisher records**, three
reduced MODS and one whole meeting XML, and what they establish is bounded the
same way:

- **Two hearings and one agenda.** The 12-bill and 8-bill cover lists and the
  9-document agenda are those records' numbers, not a family rate. The
  18-of-18, 19-of-20 and 1-of-18 confirmation figures are the receipt's, from
  60 bill-action requests this repository holds no fixture for; nothing offline
  can re-derive them.
- **The identity check is exercised both ways** — a passing pair, a wrong date
  and a wrong committee — but on one pair. That it held 9 of 9 is the receipt's
  measurement.
- **`36 of 46` is not asserted from the fixtures.** The one retained agenda
  gives 8 of 9; the family figure is reproduced from the receipt's bytes by
  `tools/analysis/hearing_bill_links_recompute.py`, which is not part of the
  offline suite because those bytes are not in this repository.
- **No Senate row exists anywhere.** The Senate fixture is here to prove the
  rule yields nothing, which is the honest answer and not a filled column.

`senate_expenditures` is built from **two bounded page ranges of two of the
eight** retained volumes — 19 pages of 2,599 — cut from the rollup's own bytes
and never re-fetched. All 114 ruled rows run through the generic loop, not a
selection, because the identity's whole job is to stay unique across two
volumes carrying the same printed grid. What that does and does not establish:

- **The totals check is real and it is one grid's.** Each fixture holds a
  *complete* `SUMMARY OF TRANSACTIONS BY APPROPRIATIONS` section, so the parsed
  amounts of 28 account rows are summed across seven printed pages against the
  `Totals` row the print states, on seven money columns, and agree to the cent
  on both. A companion test deletes one entry row and asserts the check then
  fails, so it is proved to bite. `organization_detail` states
  `ORGANIZATION TOTALS` inside its one body cell rather than as a row, so
  there is no cell-level arithmetic to check there and none is claimed.
- **The check cannot see column 0**, because the `Totals` row states no amount
  there — and that is exactly where the one defect this build found was
  hiding: an amount rule that accepted a bare integer read the fiscal years
  stacked in the title cell as money, passed the totals check, and failed only
  a test that asserted the title cell states none. The rule now requires a
  decimal point, which is a measurement: of 1,316 amount-shaped lines every one
  carries a `.dd` tail, and the 143 that do not are all account numbers or
  fiscal years.
- **Nineteen pages establish no family coverage.** Neither fixture reaches the
  `C-` compensation or `D-` mail-allocation sections the volumes' contents name,
  both past page 2,000, and nothing here says what grids those carry. No
  measured page carried two ruled tables, so `table_ordinal` is `0` throughout
  and the column exists because nothing in the print guarantees it.
- **No request was made for this table at all**, so nothing here speaks to the
  route's availability; the rollup's receipt is the only evidence of it.

## The CBO cost estimate is an index here and a span there

CBO's own site is behind a bot wall whose proxy error names a website ban, so
no document route to an estimate exists at all
([routes](research/cbo-cost-estimate-routes-2026-09-20.md)). Two tables carry
what is reachable without it, and the boundary between them is measured
([the build](research/cbo-cost-estimates-build-2026-09-20.md)).

**`cbo_cost_estimates` is the index, keyless.** GovInfo's BILLSTATUS bulk zips
carry `<cboCostEstimates>` per bill: two requests give the whole 118th — 1,368
bills, 1,468 stated items, 1,431 distinct publication ids, identical to the
keyed Congress.gov API on all 33 overlapping bills. Step zero of this build
checked whether the family already published any of it and found none, so this
is a new table rather than columns appended to `congress_bills`.

- **The identity folds, and the fold keeps what it folds.** 1,468 items become
  1,431 rows because the publisher states one publication twice on some bills.
  Nine of those 37 restatements *disagree*, every one in `title` alone, so
  `restatements_json` carries each differing later item with only its differing
  fields. `[]` on the other 1,459 rows.
- **`publication_id` is parsed, never guessed.** The rule takes only the
  `https://www.cbo.gov/publication/{id}` page all 1,468 measured urls are; a
  url outside that shape is a named `FamilyRefusal`, not a row keyed on a
  coerced id.
- **`congress_bills.cbo_cost_estimates_outcome` records every bill's answer.**
  The appended, nullable column is NULL for unread data, `populated` for read
  items, `requested-empty:absent` for a missing element,
  `requested-empty:present-and-empty` for an empty element, and
  `requested-empty:unexpected-shape:<shape>` for an unsupported shape (for
  example `non-item-child` or `empty-item`). An estimate table cannot publish
  this marker when it has no rows. The re-measurement found 1,368 populated
  blocks, 14,845 absent, zero empty and zero unexpected; none establishes
  whether an unlisted estimate exists. Unkeyable populated items still produce
  family refusals naming the rule, host and path shape, without the URL.
- **`report_citation_count` is the text route's reachability, per row.** 883 of
  the 1,368 scored bills (64.5%) have a committee report at all; the Senate
  shortfall is structural, since 155 of 395 scored Senate bills were reported
  without a written report. `WHERE report_citation_count = 0` selects bills for which this
  BILLSTATUS capture names no report; it does not prove no CRPT package exists.

**`committee_reports` carries the letter.** A report reprints the CBO letter
verbatim when its cover carries the statutory recital, and thirteen appended
columns hold what the rule found: the recital's answer, the print's own bill
key, the heading, the span, its digest, the end rule, the signatory, and the
publisher's own reason where there is no letter.

- **The gate is the recital and never a heading**, in both directions: three
  retained reports print a CBO heading over a section saying the estimate was
  not received, and one prints the estimate under a heading no pattern set had.
  A signature or dateline gate fails too — `CRPT-118srpt99` states `Director,
  Congressional Budget Office.` in a witness list.
- **`report_states_estimate = false` is requested-empty with a reason**, not a
  NULL: four of the seventeen retained bodies say why in their own words, and
  `estimate_absence_reason` carries the paragraph whole.
- **NULL throughout means no rule was run**, which is a different answer from
  `false`.
- **The heading vocabulary is a floor** and is used only to locate a span the
  recital has already declared. A declared letter the vocabulary misses
  publishes a NULL span, which reads as a shortfall rather than as an absence.
- **HTM and PDF text are supported.** Four retained PDFs now yield exact
  pinned spans after `rendition_text`; uppercase whole-line headings handle
  lost indentation, while dot leaders, prose and missing recitals still fail.
  All 17 retained HTM findings stay unchanged except for the rule version.
  The caller selects the rendition; PDF is preferred by the research plan.
  `format` and `text_sha256` identify the text these spans address.
- **`estimate_rule_version` digests every rule input.** Named and auxiliary
  patterns, flags, rejects, heading thresholds, punctuation and a control-flow
  revision are pinned together; mutation tests prove each moves the version.
- **No letter date is published.** No retained body states a CBO letterhead
  dateline; the estimate's date is CBO's own `pubDate` on the index row, and
  re-deriving it from prose would recreate what the index states.
- **No cost figures are published by either table.** The summary card is a
  raster in every rendition and no extraction was attempted over it.

**Why no `document_citations` row, and why the letter is not on the estimate
row.** Across all 17 retained bodies there is exactly one `cbo.gov` locator — a
footnote to an unrelated study — no `/publication/{id}` page, and none inside
any located letter, so a citation row's `target_key` would have to be invented.
And the estimate row is shaped from one BILLSTATUS document in one pass while
the report is a different package: 61 of the 1,368 scored bills carry more than
one estimate and 28 of those also carry a report, so one reprinted letter could
not be attributed to one of them without guessing. The relation is therefore a
join on the bill, which both sides state.

## A multi-part committee report is one row per part

A report filed in parts is one GovInfo package whose parts are granules, each
with its own body ([multi-part reports](sources/govinfo-bodies.md#multi-part-committee-reports)).
`committee_reports` publishes **one row per published part**, keyed
`(package_id, part_id)`, and `report_sections` keys its blocks
`(package_id, part_id, seq)`, with `seq` counting within the part. Both
columns are appended; `part_number` is appended beside `part_id` on the report
row only, since a block reaches it through its parent. This is an owner-ruled
identity move (decision 29, delegated 2026-09-23 and confirmed 2026-09-24;
shipped in 0.32.0).

- **`part_id` is the publisher's granule id, never a marker.** It is the
  `accessId` the record states for the part and the file stem its body was
  read at, so `requested_url` ends in `/{part_id}.{extension}` on every row. A
  report published in one part states its granule id as the package id
  (`CRPT-119hrpt1`), and `CRPT-119hrpt494` states its unsuffixed Part 1 the
  same way, so on those rows `part_id` equals `package_id`. A blank marker, the
  way `treaties.suffix` spells an unpartitioned treaty, was rejected: it would
  be a value no record states, and it could not be checked against the URL the
  body came from.
- **`part_number` is what the record numbers.** 1 and 2 on `CRPT-119hrpt455`,
  1 on `CRPT-119hrpt811`'s lone `-pt1`, and NULL on a report published in one
  part, whose record states no number. It is not identity: NULL there is a fact,
  not a gap. Neither column says how many parts a package has:
  `(CRPT-119hrpt811-pt1, 1)` has the shape of `CRPT-119hrpt455`'s Part 1, so a
  reader counts a package's rows to tell a lone part from Part 1 of two.
- **A package's part rows are replaced as a set.** The acquisition checkpoint
  stays keyed by package: one read yields every part
  (`GovInfoBodyAcquirer.acquire_parts`, all or nothing), and a host removes
  the package's prior part rows before merging the fresh ones, the scope
  `report_sections` already replaces by package. A package gains a part without
  changing identity: `CRPT-119hrpt494`'s Part 2 was printed 2026-09-08 and the
  package's `last_modified` moved to 2026-09-11, so discovery re-reads it.
- **Summary facts repeat on each part row.** `title`, `date_issued` and
  `last_modified` are the package's; `format` through `text_sha256` and the
  estimate columns are the part's own. The bill a host passes should be the
  part's (`part.primary_bill`): a multi-part package's root states no `<bill>`
  (`CRPT-119hrpt455`, `-119hrpt494`), so the package-level `primary_bill` is
  `None` there.
- **`REPORT_SECTION_READER_VERSION` is `report-headings-002`.** Hosts carry it
  in their read checkpoint, so every report is re-read into part rows.
- **A host adopts all of it in the release that vendors it.** The shapers no
  longer take the old call: `shape_report_section` requires `part_id`, and
  `shape_committee_report` raises `ValueError` for a body that names no part
  rather than emit a NULL `part_id`. A merge that keeps only rows whose
  identity is wholly non-null would drop that row without a word, and it drops
  every prior row too, since rows published before the column existed read
  `part_id` as NULL. So in the same release a host:
  1. passes each `acquire_parts` result's `part.part_id` to both shapers;
  2. backfills the prior rows of both tables with
     `part_id = COALESCE(part_id, package_id)`, which is right for every report
     published in one part and for `CRPT-119hrpt494`'s Part 1;
  3. merges `committee_reports`, like `report_sections`, with
     `replace_parents=("package_id", <evaluated packages>)`. The one prior row
     the backfill spells wrong, a lone `-pt1` part read before this move, is
     then replaced when the reader-version bump re-reads its package, rather
     than kept beside the corrected row.

  The move shipped in 0.32.0 after the owner confirmed decision 29; a consumer
  adopts it in the release it vendors.

Over every retained CRPT package MODS (148 distinct records, 145 packages, all
read, none refused; receipt
`receipts/multipart-reports-2026-09-23/parts/population.json`), 141 packages
publish one row and 4 publish two (`CRPT-108hrpt24`, `-119hrpt455`,
`-119hrpt494`, `-119hrpt620`). Of the 141, 133 have `part_id` equal to
`package_id` and 8 have a `-pt1` part (`CRPT-112hrpt11`, `-112hrpt38`,
`-112hrpt141`, `-119hrpt468`, `-119hrpt483`, `-119hrpt577`, `-119hrpt621`,
`-119hrpt811`).

## What is still a preserved NULL

| Column | Why | What would fill it |
| --- | --- | --- |
| `congress_bills.statutes_at_large_cite` | The family build sees one BILLSTATUS document and its printings; the citation lives in the PLAW package's USLM `meta`, which the laws rollup acquires once per law — filling it here would fetch every PLAW twice or read another table's output. | The merge joins `laws` on `bill_id` (`statutes_at_large_cite` is published there). |
| `committee_reports.bill_id` | A package-keyed report is fillable today; the *index's* report-to-bill linkage is not. | A report-to-bill join from an index record. The **print's** answer now lands beside it on `committee_reports.recital_bill_id`, read off the cover recital; the two are kept apart because what a print says and what an index says are different claims. |
| `hearing_transcripts.bill_id` | Not for want of a source: four publishers state a hearing's bills. The relationship is one-to-many — twelve bills on `CHRG-118hhrg56198` — so a scalar column would pick one of twelve. | Nothing. `hearing_bill_links` is the answer, and this column stays NULL by design. |

## Decision

Recorded in [decisions.md](decisions.md#row-shaping-lives-in-spicy-docs-spicy-regs-converts-and-publishes):
row shaping lives in spicy-docs beside the logic that fills each column, the
consuming repository converts, merges and publishes without re-deriving any
rule, and the bill family is one pass so no hosted rollup reads another's
output.
