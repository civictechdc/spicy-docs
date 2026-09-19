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

`TABLE_CONTRACTS` holds all twenty-two by name. Each carries its columns in
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
| `roll_call_votes` | One row per roll call: the publisher's own tally, and the bill it refers to. | `congress`, `chamber`, `session`, `roll_number` | `vote_date` | 19 | `sources.congress.votes` |
| `member_votes` | One row per member's position on one roll call. | `congress`, `chamber`, `session`, `roll_number`, `member_key` | `vote_date` | 14 | `sources.congress.votes` |
| `members` | One row per legislator in one capture of the community crosswalk. | `bioguide_id` | `observed_at` | 18 | `sources.legislators` |
| `member_terms` | One row per term a legislator served, in the crosswalk's own order. | `bioguide_id`, `term_index` | `observed_at` | 9 | `sources.legislators` |
| `committee_reports` | One row per captured GovInfo committee report package. | `package_id` | `last_modified` | 19 | `sources.govinfo.body_acquisition` |
| `report_sections` | One row per agency block parsed out of one committee report's text. | `package_id`, `seq` | `last_modified` | 12 | `sources.agency_reports.report_blocks` |
| `hearing_transcripts` | One row per captured GovInfo hearing transcript package. | `package_id` | `last_modified` | 19 | `sources.govinfo.body_acquisition` |

Four hundred and six columns in all, each with its own sentence.

`congress_bills`'s first ten columns keep the exact order and spelling of the
live `build_congress_bills.COLUMNS` a host already publishes: other repositories
pin that prefix by digest, so it is frozen on purpose and every new column is
appended.

## The bill family is one pass

Twelve of the twenty-two tables come out of a single call to
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

## What is still a preserved NULL

| Column | Why | What would fill it |
| --- | --- | --- |
| `congress_bills.statutes_at_large_cite` | The citation lives in the PLAW package's GovInfo MODS, which this repository does not acquire. | A PLAW MODS reader. |
| `committee_reports.bill_id`, `hearing_transcripts.bill_id` | A package-keyed report is fillable today; the bill linkage is not. | A report-to-bill join. |

## Decision

Recorded in [decisions.md](decisions.md#row-shaping-lives-in-spicy-docs-spicy-regs-converts-and-publishes):
row shaping lives in spicy-docs beside the logic that fills each column, the
consuming repository converts, merges and publishes without re-deriving any
rule, and the bill family is one pass so no hosted rollup reads another's
output.
