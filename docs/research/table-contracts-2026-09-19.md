# The table-contract layer: spicy-docs records to spicy-regs rows

Status: design, 2026-09-19, written read-only against spicy-docs `main` after
the press-release, report-block, bill-version, interpretation and GPO branches
merged, and against the DeltaTrack adapter branch before it merged. It is the
build brief for the layer that turns this repository's records into the rows
spicy-regs hosts ([placement study](billtrax-regs-placement-2026-09-19.md) §3
and §6, [value inventory](billtrax-value-inventory-2026-09-19.md) §3 and §6).

## 0. Three facts that shape everything

1. **The interpretation package already carries provenance.** Every rule in
   `src/spicy_docs/interpretation/` returns a frozen finding naming its rule,
   matcher and input indices, and the two model-backed modules already carry
   `model`, `prompt_version`, `prompt_hash`, `requested_at`, `completed_at`.
   The contract layer flattens findings; it does not invent provenance.
2. **`schemas/` is a leaf.** `schemas/spicy_regs_public_tables.py` and
   `schemas/federal_register.py` import nothing from this repository;
   `public_tables/profiles.py` imports them. Keeping that direction lets
   spicy-regs import a column tuple without pulling DeltaTrack, pyarrow or an
   HTTP client.
3. **DeltaTrack is a git dependency, not a registry package** (the `bill-diff`
   extra pins `git+https://github.com/civictechdc/DeltaTrack?rev=c636448…`).
   spicy-regs vendors its source readers as wheels with recorded SHA-256, so
   the diff tables have a release blocker (§5.4).

## 1. Where the contract lives

One module per table family under `src/spicy_docs/schemas/`: column tuples,
identity, version column, and one pure `shape_*` function per table, stdlib
only (`dataclasses`, `json`, `typing`, `collections.abc`, `hashlib`). No
pyarrow, no DeltaTrack, no `sources.*` or `interpretation.*` imports from
`schemas/`.

### A `TableContract` record, not loose tuples

`spicy_regs_public_tables.py`'s four module constants work for one table; for
twenty, iterating every table (identity uniqueness, description coverage,
generating spicy-regs's schema dict) needs one record type. A frozen dataclass
of tuples and strings is still data and pure functions.

New file `src/spicy_docs/schemas/tables.py`:

```python
Row = dict[str, str | None]


@dataclass(frozen=True, slots=True)
class TableContract:
    name: str  # R2 key = MCP view = dict key, snake_case
    columns: tuple[str, ...]  # publish order
    identity: tuple[str, ...]  # dedup / primary key columns
    version_column: str | None  # freshness / merge-preference column
    descriptions: Mapping[str, str]  # one per column; feeds spicy-regs-dict
    grain: str  # one sentence, for the data-dictionary summary

    def __post_init__(self) -> None: ...  # refuses identity not in columns, version not in

    # columns, duplicate columns, descriptions keys != columns

    def key(self, row: Row) -> tuple[str, ...]: ...  # identity tuple; refuses a null part

    def checked(self, row: Row) -> Row: ...  # refuses a row whose keys != columns


def text(value: object) -> str | None: ...  # None|str|int|float|bool -> str|None
def flag(value: bool | None) -> str | None: ...  # "true"/"false"/None
def json_column(value: object) -> str: ...  # json.dumps(sort_keys=True, separators=(",", ":"))
def joined(parts: Iterable[str]) -> str: ...  # "\x1f".join, the separator-collision fix
def digest(text: str | None) -> str | None: ...  # "sha256:" + hexdigest, or None


TABLE_CONTRACTS: Mapping[str, TableContract]  # every contract by name
```

`TableContract.checked()` is the one place a `shape_*` output is proved to
match its column tuple, so the round-trip test (§6) is one loop. `text()` is
lifted from `federal_register.py:_text` rather than copied.

### The family builder does not live in `schemas/`

`build_bill_family` composes interpretation findings with parsed documents; in
`schemas/` it would make the leaf import `sources/` and `interpretation/`. It
lives at `src/spicy_docs/interpretation/bill_family.py`, where
`interpretation/` already imports `sources.congress.bill_status`.

Net effect: spicy-regs's transform imports `spicy_docs.schemas.*` only, with no
extras; its rollup is the only thing importing
`spicy_docs.interpretation.bill_family` and so the only thing needing
`bill-diff`.

### Files to create in `schemas/`

| File | Tables |
|---|---|
| `tables.py` | shared contract machinery |
| `bill_tables.py` | `congress_bills`, `bill_actions`, `bill_committees`, `bill_publisher_summaries` |
| `bill_version_tables.py` | `bill_versions`, `bill_sections` |
| `bill_diff_tables.py` | `section_diffs`, `section_diff_items`, `financial_changes` |
| `bill_model_tables.py` | `section_classifications`, `bill_summaries` |
| `congress_activity_tables.py` | `amendments`, `press_releases`, `roll_call_votes`, `member_votes` |
| `legislator_tables.py` | `members`, `member_terms` |
| `committee_report_tables.py` | `committee_reports`, `report_sections`, `hearing_transcripts` |
| `activity_events.py` | `public_activity_events` and the snapshot comparison (§4) |

`schemas/__init__.py` re-exports `TableContract`, `TABLE_CONTRACTS`, `Row`.

## 2. The table list and columns

### 2.0 Changes to the placement study's table set, with reasons

| # | Change | Reason |
|---|---|---|
| C1 | Split `bills` into `congress_bills` + `bill_actions` + `bill_committees` + `bill_publisher_summaries`. | Inventory §6.1: the entire action history and the committee list are discarded, and `summaries` is never declared. All three are typed on `BillStatus` now (actions with `action_code`, `action_time`, `source_system_code`, `recorded_votes`; committees with `system_code`, `chamber`, subcommittees; summaries). The largest single "data on the table" item in the inventory. |
| C2 | Drop `text` and `xml` from `bill_versions`; publish `sha256`, `byte_size`, `resolved_url`, `content_type`, `observed_at`, `package_id`, and let `bill_sections.body` carry text at the grain people query. | spicy-regs publishes one Parquet object per table read through a DuckDB view; a full-text column per version is a multi-GB object fighting the shrink guard. BillTrax itself listed both in `METADATA_STRIP_COLUMNS`. Nothing is lost: the body is recomposable from sections and re-fetchable by package id and digest. |
| C3 | Reverse the study on `word_segments_json`: publish `text_diff_json`, byte-capped, with `text_diff_truncated`. | Once C2 drops `bill_versions.text`, the word diff is no longer recomputable from published rows. |
| C4 | `bill_sections` identity gains `source` and `body_index`: `(bill_id, version_code, source, match_path, body_index)`. | A reported bill carries two `legis-body` elements and DeltaTrack's `BillNode` exposes `body_index` because paths repeat across them; `source` is part of the parent version's key. |
| C5 | `section_classifications` and `bill_summaries` identities gain `source`. | `bill_versions` is keyed `(bill_id, version_code, source)`, the key BillTrax widened in migration 020; a child cannot name which of an XML row and its PDF twin it classified without it. |
| C6 | `amendments` identity is `(congress, amendment_type, amendment_number)`. | The study's key is the amended bill's. An amendment has its own publisher identity and can amend another amendment; `amended_bill_id` and `amended_amendment_id` stay as foreign-key columns. |
| C7 | `press_releases` identity is `release_id = sha256(chamber \x1f link)`. | BillTrax's unique key is a 255-byte prefix of `source_url`; the study names the collision. The full `link` stays its own column. |
| C8 | `public_activity_events` identity is `(bill_id, event_type, subject_id, occurred_at)`. | `(bill_id, event_type, occurred_at)` collides whenever two versions of one bill share a date, which an introduced version and its reprint routinely do. |
| C9 | Split `members` into `members` + `member_terms`. | Inventory §6.7: every term but the last is discarded; `Legislator.terms` carries all of them and one row cannot hold a chamber switch. |
| C10 | `diff_summaries` ships only if BillTrax has a diff-summary generator to port; otherwise it is left out with the reason. | `interpretation/` has `bill_summaries.py` and no diff-summary module today; a contract nothing fills is the defect the study names for `hearing_transcripts`. The implementer checks BillTrax for a generator and ports it, prompt sealed, if one exists. |
| C11 | `hearing_transcripts` keyed on the CHRG package id with `bill_id` nullable; `member_votes` contract written and registered once a vote reader lands. | A package-keyed hearing table is fillable today by `GovInfoBodyAcquirer`; the bill linkage is not. `member_votes` needs the House Clerk and Senate LIS readers. |
| C12 | `bill_summaries` stays the model-backed table; the publisher's CRS summaries get `bill_publisher_summaries`. | `BillStatus.summaries` and BillTrax's `bill_summaries` are two different things under one name. |

### 2.1 Prerequisites this uncovered

| Gap | Blocks | Fix |
|---|---|---|
| `BillStatus` does not parse `titles[]` | `congress_bills.short_title` | add `titles: tuple[BillTitle, ...]` to `sources/congress/bill_status.py` |
| `BillStatus` does not parse `relatedBills` | replacing BillTrax's hand-set `related_bill_id` with the publisher's fact (§6.2) | same file |
| `Term` carries type, start, end, state only, no `party`, no `district` | `members.current_term_party`, `current_term_district` | `sources/legislators.py::_read_term` |
| `LIST_ROUTES` has no `house-vote` route | `roll_call_votes` tallies and `vote_matching.house_vote_references`'s input | add `CongressListRoute("house-vote", "house-vote/{congress}/{session}", "houseRollCallVotes", …)` to `sources/congress/listing.py` |
| No House Clerk or Senate LIS reader | `roll_call_votes.{yea,nay,present,not_voting}`, all of `member_votes` | a new `sources/congress/votes.py`; until then publish linkage columns with NULL tallies and say so in the coverage statement |
| `version_kind()` returns a bare string with no finding record | the package's own contract ("outputs that are frozen records carrying the rule that fired") | add `version_kind_finding(...) -> VersionKindFinding(kind, rule, section_count, body_bytes)`; keep `version_kind()` as a wrapper |
| `statutes_at_large_cite` needs GovInfo MODS for the PLAW package | the column the study says to fill | publish a preserved NULL with the reason in the description, as `federal_register.py` does for `modify_date` |

### 2.2 The tables

Notation: fact = publisher field; interp = rule output; prov = provenance
beside an interpreted column; ✚ = a field inventory §6 says BillTrax discards.

**`congress_bills`** (extend the live table). Identity `bill_id`. Version
`update_date`.
`shape_bill(status: BillStatus, *, referrals: frozenset[str], stage: StageFinding, signing: SignedDateFinding, money: MoneyBillFinding) -> Row`

Frozen prefix: columns 1 to 10 keep the exact order and spelling of
spicy-regs's live `build_congress_bills.COLUMNS`, which other repos pin by
digest through `catalog.json`.

| # | Column | Source | Kind |
|---|---|---|---|
| 1 | `bill_id` | `f"{c}-{t}-{n}"` from `status.identity` | fact |
| 2-4 | `congress`, `bill_type`, `bill_number` | `status.identity.*` | fact |
| 5 | `title` | `status.title` | fact |
| 6 | `origin_chamber` | `status.origin_chamber` ✚ | fact |
| 7-8 | `latest_action_date`, `latest_action_text` | `status.latest_action` | fact |
| 9 | `update_date` | `status.update_date` | fact |
| 10 | `url` | `status.legislation_url` | fact |
| 11 | `schema_version` | `status.schema_version` ✚ | fact |
| 12 | `update_date_including_text` | ✚ | fact |
| 13 | `introduced_date` | | fact |
| 14 | `policy_area` | ✚ | fact |
| 15-16 | `subjects_json`, `subject_count` | `status.subjects` ✚ | fact |
| 17-18 | `sponsor_bioguide_id`, `sponsor_full_name` | `status.sponsors[0]` ✚ | fact |
| 19 | `cosponsor_count` | `max(len(status.sponsors) - 1, 0)` ✚ | fact |
| 20-23 | `latest_action_code`, `latest_action_time`, `latest_action_source_system_code`, `latest_action_source_system_name` | ✚ | fact |
| 24-26 | `action_count`, `committee_count`, `version_count` | lengths | fact |
| 27 | `public_law_number` | `signing.public_law_number` | fact |
| 28 | `law_type` | `status.laws[0].type` ✚ | fact |
| 29 | `statutes_at_large_cite` | preserved NULL, reason in description | fact |
| 30 | `stage` | `stage.stage` | interp |
| 31-35 | `stage_rule`, `stage_matcher`, `stage_action_index`, `stage_action_date`, `stage_source_text` | `StageFinding` | prov |
| 36 | `signed_date` | `signing.signed_date` | interp |
| 37-39 | `signed_date_rule`, `signed_date_action_index`, `signed_date_action_code` | `SignedDateFinding` | prov |
| 40 | `money_bill_kind` | `money.kind` | interp |
| 41-42 | `money_bill_rule`, `money_bill_reason_codes` | `money.rule`, joined reason codes | prov |
| 43-44 | `fiscal_year`, `appropriations_subcommittee` | `money` | interp |
| 45 | `referral_signals` | sorted, joined; what the classifier was given | prov |

Dropped with reason: `id` (UUID, natural key instead), `summary` (never
written; C12), `chamber` (redundant with 6), `classified_by` and
`classified_at` (replaced by the `*_rule` columns and the run manifest),
`related_bill_id` and `prev_year_bill_id` (UI-set; the publisher's
`relatedBills` waits on §2.1).

**`bill_actions`** (C1). Identity `(bill_id, action_index)`. Version
`action_date`.
`shape_bill_action(identity, action: BillAction, *, action_index, is_latest, stage: StageFinding) -> Row`:
`bill_id`, `action_index`, `action_date`, `action_time` ✚, `action_text`,
`action_code` ✚, `action_type` ✚, `source_system_code` ✚,
`source_system_name` ✚, `recorded_vote_count`, `is_latest_action`; interp and
prov: `stage`, `stage_rule`, `stage_matcher` from `infer_stage_from_text` on
the action, which makes `congress_bills.stage` auditable action by action.

**`bill_committees`** (C1). Identity `(bill_id, system_code)`. Version
`snapshot_update_date`.
`shape_bill_committee(identity, committee: BillCommittee, *, parent_system_code, update_date) -> Row`:
`bill_id`, `system_code` ✚, `name`, `chamber`, `committee_type`,
`parent_system_code`, `is_subcommittee`, `snapshot_update_date`; interp and
prov: `referral_signal` (`money_bills.COMMITTEE_CODES` lookup, NULL outside the
six), `referral_rule = "committee_system_code"`.

**`bill_publisher_summaries`** (C1, C12). Identity
`(bill_id, summary_version_code, action_date)`. Version `update_date`.
`shape_bill_publisher_summary(identity, summary: BillSummary) -> Row`:
`bill_id`, `summary_version_code`, `action_date`, `action_desc`, `update_date`,
`summary_html` (as the publisher escaped it), `summary_chars`. All fact ✚.

**`bill_versions`**. Identity `(bill_id, version_code, source)`. Version
`version_date`.
`shape_bill_version(capture: BillVersionCapture, *, identity, kind: VersionKindFinding) -> Row`.
Fact: `bill_id`, `version_code` (`bill_versions.version_slug`), `source`,
`label` (the type verbatim), `version_date`, `package_id` ✚, `format_name`,
`format_type`, `requested_url`, `resolved_url`, `content_type`, `byte_size`,
`sha256`, `observed_at` (from `transport/captured.py`'s
`CapturedBodyResponse`, exactly the columns inventory §3.2 lists as missing),
`offered_formats_json` ✚, `version_code_is_reprint_ambiguous`
(`len(version_slug_reprints(type)) > 1`), `root_tag`, `body_tags`,
`publisher_stage` (`BillDocument.stage`), `section_count`,
`discarded_elements_json`, `equivalent_xml_version_code`. Processing
provenance, not data: `cleanup_line_numbers`, `cleanup_gpo_footers`,
`cleanup_spacing_normalized`, `cleanup_small_caps_merges`,
`cleanup_hyphen_rejoins`, `cleanup_json` from `GpoCleanupRecord`, modelled on
spicy-regs's `pdf_extraction_results_json`. Interp and prov: `kind`,
`kind_rule`, `kind_label`, `kind_warning`, `kind_section_count`,
`kind_body_bytes`. Dropped: `text`, `xml` (C2), `is_base`,
`uploaded_by_user_id`, `aligned_to_congress_bill_id`, `id`.

**`bill_sections`**. Identity
`(bill_id, version_code, source, match_path, body_index)` (C4). Version is the
parent `version_date`.
`shape_bill_section(node: BillNode, *, bill_id, version_code, source, seq, version_date) -> Row`:
`bill_id`, `version_code`, `source`, `match_path` (unit-separator joined, the
study's separator collision fixed), `match_path_json`, `display_path_json`,
`element_id`, `section_number`, `heading`, `body`, `display_text`,
`division_label`, `division_key`, `body_index`, `seq`, `body_chars`,
`body_sha256`, `version_date`.

**`section_diffs`**. Identity
`(bill_id, from_version_code, from_source, to_version_code, to_source)`.
Version `to_version_date`.
`shape_section_diff(diff: SectionDiff, *, bill_id, from_ref, to_ref, from_version_date, to_version_date, pair_type, engine: EngineStamp, computed_at) -> Row`:
the key, `from_version_date`, `to_version_date`, `pair_type`, `pair_rule`
(`"consecutive_by_date"`), `added_count`, `removed_count`, `modified_count`,
`unchanged_count`, `moved_count`, `item_count`, and the engine provenance that
stands in for a rule name: `engine_name`, `engine_version`, `engine_revision`
(the pinned commit), `computed_at`.

**`section_diff_items`**. Identity the diff key plus `seq`.
`shape_section_diff_item(item: SectionDiffItem, *, bill_id, from_ref, to_ref, text_diff_cap) -> Row`:
the diff key, `seq`, `op`, `similarity`, `moved`, `pairing_rule`
(`path-round`, `move-round`, `unpaired`), `evidence_json` (upstream's named
signals), `match_path`, `match_path_json`, `display_path_old_json`,
`display_path_new_json`, `section_number`, `heading`, `from_element_id`,
`to_element_id`, `from_text_sha256`, `to_text_sha256`, `from_text_chars`,
`to_text_chars`, `text_diff_json`, `text_diff_truncated` (C3), and the
per-item money facts `financial_from_amounts_json`,
`financial_to_amounts_json`, `financial_amounts_changed`,
`financial_has_amendment_annotations`.

**`financial_changes`**. Identity the item key plus `amount_index`.
`shape_financial_change(pair: AmountPair, *, item_key, amount_index) -> Row`:
the item key, `amount_index`, `label` (the section heading, the study's
always-empty label fixed), `from_amount`, `to_amount`, `delta`,
`pairing_claim = "word_alignment"` (the name upstream insisted on when it
removed paired amounts from its published contract; rows exist only where
`amounts_changed` and the caller asked for pairs).

**`section_classifications`**. Identity
`(bill_id, version_code, source, match_path, body_index, label)` (C5). Version
`completed_at`.
`shape_section_classification(result, *, section_key, vocabulary_hash) -> Row`:
the section key, `label`, `confidence`, `model`, `prompt_version`,
`prompt_hash`, `batch_index`, `requested_at`, `completed_at`,
`vocabulary_hash` (sha256 over `CLASSIFICATION_LABELS`, so a vocabulary change
is visible in the data).

**`bill_summaries`**. Identity `(bill_id, version_code, source)` (C5). Version
`completed_at`.
`shape_bill_summary(result: BillSummaryResult, *, source, money_bill_kind) -> Row`:
`bill_id`, `version_code`, `source`, `summary`, `audience`,
`top_provisions_json`, `model`, `prompt_version`, `content_hash`,
`input_tokens`, `output_tokens`, `requested_at`, `completed_at`,
`money_bill_kind`, `frame` (without the frame the summary is not reproducible
from the row).

**`public_activity_events`**: §4.

**`amendments`** (C6). Identity `(congress, amendment_type, amendment_number)`.
Version `update_date`.
`shape_amendment(record: Mapping[str, Any]) -> Row` from the `amendment` list
route's exact publisher dict: `amendment_id`, `congress`, `amendment_type` ✚,
`amendment_number`, `purpose` ✚, `description` ✚, `proposed_date` ✚,
`submitted_date` ✚, `chamber` ✚, `update_date` ✚, `latest_action_date` ✚,
`latest_action_text`, `sponsor_bioguide_id`, `sponsor_full_name`,
`sponsor_party` (the full string), `amended_bill_id` ✚,
`amended_amendment_id` ✚, `url`. `status` is dropped: it was hardcoded
`"Proposed"` (fix ledger item 7).

**`press_releases`** (C7). Identity `release_id`. Version `observed_at`.
`shape_press_release(release, channel, *, feed, observed_at, match: ReleaseMatch | None) -> Row`.
Fact: `release_id`, `chamber`, `feed_url`, `channel_title` ✚, `channel_link` ✚,
`channel_description` ✚, `channel_language` ✚, `channel_copyright` ✚,
`channel_docs` ✚, `channel_last_build_date` ✚, `channel_ttl` ✚,
`channel_skip_days` ✚, `channel_skip_hours` ✚, `item_index`, `title`
(untruncated), `link`, `guid`, `guid_is_permalink`, `description` (the full
body ✚), `description_text`, `description_chars`, `pub_date`,
`pub_date_instant`, `author` ✚, `creator` ✚, `categories_json` ✚,
`enclosure_url` ✚, `enclosure_length` ✚, `enclosure_type` ✚, `observed_at`.
Interp and prov: `bill_id`, `match_rule`, `matched_field`, `matched_text`.

**`roll_call_votes`**. Identity `(congress, chamber, session, roll_number)`.
Version `vote_date`.
`shape_roll_call_vote(vote: VoteKey, *, match: VoteMatch, tally: VoteTally | None, source_url, question, result, vote_date) -> Row`:
`vote_id`, `congress`, `chamber`, `session`, `roll_number`, `vote_date`,
`source_url`, `question` ✚, `result` ✚, `yea`, `nay`, `present` ✚,
`not_voting` ✚ (all four real, §6.5); interp and prov: `bill_id`,
`match_rule`, `match_action_index`, `match_url`, `conflict_count`.

**`member_votes`** (C11). Identity
`(congress, chamber, session, roll_number, bioguide_id)`; contract written,
registered when the vote readers land.

**`members`** and **`member_terms`** (C9). Identities `bioguide_id` and
`(bioguide_id, term_index)`. Version `observed_at`.
`shape_member(legislator: Legislator, *, roster, observed_at) -> Row`,
`shape_member_term(term: Term, *, bioguide_id, term_index) -> Row`.
`members`: `bioguide_id`, `lis_id` ✚, `fec_ids_json` ✚, `icpsr_id` ✚,
`govtrack_id` ✚, `opensecrets_id` ✚, `wikidata_id` ✚, `name_first`,
`name_last`, `term_count`, `first_term_start`, `last_term_end`,
`current_term_type`, `current_term_state`, `current_term_party`,
`current_term_district` (the last two after §2.1), `roster`, `observed_at`.
`photo_url` dropped (constructed, not fetched). `member_terms`:
`bioguide_id`, `term_index`, `term_type`, `term_start`, `term_end`,
`term_state`, `term_party`, `term_district`.

**`committee_reports`**, **`report_sections`**, **`hearing_transcripts`**
(C11). Identities `package_id`, `(package_id, seq)`, `package_id`. Version
`last_modified`.
`shape_committee_report(body: GovInfoPackageBody, *, bill_id, page_count, text_sha256) -> Row`:
`package_id`, `collection`, `congress`, `report_type`, `report_number`,
`chamber`, `title`, `date_issued`, `last_modified`, `bill_id`, `format`,
`media_type`, `requested_url`, `resolved_url`, `byte_size`, `sha256`,
`observed_at`, `page_count`, `text_sha256`.
`shape_report_section(block: AgencyBlock, *, package_id, seq) -> Row`:
`package_id`, `seq`, `agency_label`, `agency_key`, `body`, `pattern` (the
header pattern that fired, this table's provenance column), `char_start`,
`char_end`, `page_start`, `page_end`, `body_chars`.

## 3. The bill-family build

New file `src/spicy_docs/interpretation/bill_family.py`:

```python
@dataclass(frozen=True, slots=True)
class BillVersionCapture:
    version: BillTextVersion
    version_code: str  # bill_versions.version_slug(version.type)
    source: str  # "govinfo" | "congress" | "govinfo-pdf" | "upload"
    package_id: str | None  # bill_status.bill_package_id_from_url, preferred
    chosen_format: BillTextFormat | None  # bill_versions.choose_format(version.formats)
    body: CapturedBodyResponse | None  # sha256, urls, observed_at, size
    document: BillDocument | None  # sources.congress.bill_tree.parse_bill_tree
    cleanup: GpoCleanupRecord | None  # extraction.gpo_normalize, PDF path only
    equivalent_xml_version_code: str | None


@dataclass(frozen=True, slots=True)
class BillFamilyCapture:
    status: BillStatus
    versions: tuple[BillVersionCapture, ...]
    observed_at: str


class SectionClassifier(Protocol):
    def __call__(self, sections: Sequence[ClassifiableSection]) -> tuple[SectionClassification, ...]: ...


class BillSummarizer(Protocol):
    def __call__(self, version: BillVersionText) -> BillSummaryResult | None: ...


@dataclass(frozen=True, slots=True)
class EngineStamp:
    name: str
    version: str
    revision: str


@dataclass(frozen=True, slots=True)
class FamilyRefusal:
    table: str
    identity: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class BillFamilyTables:
    bills: tuple[Row, ...]
    bill_actions: tuple[Row, ...]
    bill_committees: tuple[Row, ...]
    bill_publisher_summaries: tuple[Row, ...]
    bill_versions: tuple[Row, ...]
    bill_sections: tuple[Row, ...]
    section_diffs: tuple[Row, ...]
    section_diff_items: tuple[Row, ...]
    financial_changes: tuple[Row, ...]
    section_classifications: tuple[Row, ...]
    bill_summaries: tuple[Row, ...]
    refusals: tuple[FamilyRefusal, ...]

    def merged(self, other: BillFamilyTables) -> BillFamilyTables: ...


def build_bill_family(
    capture: BillFamilyCapture,
    *,
    engine: EngineStamp,
    classify: SectionClassifier | None = None,
    summarize: BillSummarizer | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BillFamilyTables: ...
```

The model call is injected at this boundary, not as a `ModelCall`:
`classify_sections` and `summarize_bill` already take the call and choose the
model, and the family builder must not pick a model or batch size. A caller
binds `functools.partial(classify_sections, call=client, model=...)`. `None`
skips the model tables entirely, which is what a keyless CI run and every
hermetic test do.

Internal order, one pass, no table reads another's published output:

1. `referrals = money_bills.referrals_from_committee_codes(...)` over
   committees and subcommittees.
2. `stage = bill_stage.infer_stage(status.actions)`,
   `signing = bill_stage.signed_date(status)`,
   `money = money_bills.classify_money_bill(...)`.
3. `bills`, `bill_actions` (each action through `infer_stage_from_text`),
   `bill_committees`, `bill_publisher_summaries`.
4. `bill_versions`, using `version_kind_finding`.
5. `bill_sections`, one row per `BillNode`.
6. Pairing: order versions by `(version.date, VERSION_CODES index)`; diff
   consecutive pairs only. `pair_type` then `diff_sections` produce
   `section_diffs`, `section_diff_items`, `financial_changes`. A pair with a
   missing `BillDocument` yields a `FamilyRefusal`, never a silent gap.
7. If `classify` is given: `section_classifications` for versions whose
   `kind == "full_text"`.
8. If `summarize` is given: `bill_summaries` for the same set, with
   `money_bill_kind` threaded so the frame is recorded.
9. Every row passes `TableContract.checked()`.

Big O per bill with A actions, C committees, V versions, S sections per
version, W words per section: steps 1 to 5 are O(A + C + V + ΣS), linear in
rows produced, with no re-parsing. Step 6 diffs V-1 pairs, not V², each bounded
by DeltaTrack's own retrieval gate; the builder adds one linear pass per pair.
Steps 7 and 8 cost ceil(S/30) model calls per classified version and one per
summarized version. Consecutive pairs is deliberate: the diff is the only
superlinear operation in the family.

spicy-regs's rollup drives it: `BulkStatusAcquirer` → `BulkStatusArchive.members`
→ acquire versions → `build_bill_family(...)` → `.merged(...)`. Members with a
refusal become `FamilyRefusal` rows, not dropped bills.

## 4. Activity events

New file `src/spicy_docs/schemas/activity_events.py`:

```python
EVENT_TYPES = ("bill_added", "version_added", "stage_changed", "summary_generated")


@dataclass(frozen=True, slots=True)
class BillFamilySnapshot:
    bills: Mapping[tuple[str, ...], Row]
    bill_versions: Mapping[tuple[str, ...], Row]
    bill_summaries: Mapping[tuple[str, ...], Row]


def snapshot_from_rows(*, bills, bill_versions, bill_summaries) -> BillFamilySnapshot: ...


# keys each row with its own contract's .key(row), never hand-written


def activity_events(prior: BillFamilySnapshot, current: BillFamilySnapshot, *, detected_at: str) -> tuple[Row, ...]: ...
```

| Event | Condition | `subject_id` | `occurred_at` | `event_data_json` |
|---|---|---|---|---|
| `bill_added` | bill key in current, not in prior | `""` | `introduced_date`, else `update_date`, else `detected_at` | title, stage, sponsor bioguide |
| `version_added` | version key in current, not in prior | joined version key | `version_date`, else `detected_at` | version_code, source, kind, kind_rule |
| `stage_changed` | bill key in both and `stage` differs | `""` | `update_date`, else `detected_at` | from, to, rule, matcher |
| `summary_generated` | summary key in current and not in prior, or `content_hash` differs | joined summary key | `completed_at`, else `detected_at` | model, prompt_version, content_hash, regenerated |

Identity `(bill_id, event_type, subject_id, occurred_at)` (C8); version column
`detected_at`. Two instants, because the publisher instant serves a feed and
the run instant serves "what changed tonight". Deletions are not events: the
four-type vocabulary is sealed, and a row leaving a table is a withdrawn record
or a truncated snapshot, stated in the coverage statement. O(|prior| +
|current|): one pass builds each keyed mapping, one pass over each current
mapping with constant-time lookups.

## 5. What spicy-regs then needs

### 5.1 Per table

| Piece | File | Shape |
|---|---|---|
| Merge helper, once | `src/spicy_regs/transforms/table_merge.py` | `merge_table(output_dir, *, contract_name, columns, identity, version_column, rows, remote_key) -> Path`: prior from R2 best-effort, new rows through an all-VARCHAR Arrow schema from the column tuple, DuckDB row-number over the identity preferring fresh, ordered by the version column. Lifted from `build_congress_bills.py:135-210` and parameterised, so twenty tables do not copy that SQL. |
| Transform | `transforms/build_bill_family.py`, `build_press_releases.py`, `build_amendments.py`, `build_roll_call_votes.py`, `build_members.py`, `build_committee_reports.py` | import the contract from `spicy_docs.schemas.*`, build rows, call `merge_table` per output |
| Rollup | `pipelines/rollups/bill_family.py` and five siblings | `inputs = ()` everywhere |
| CLI | `pyproject.toml` scripts | `run-rollup-bill-family` and five siblings |
| Cron | `.github/workflows/rollup-bill-family.yml` and five | delegating to `_rollup.yml` |
| Dictionary | `data_dictionary/descriptions.yaml`, `src/spicy_regs/data_dictionary.py` | §5.3 |
| MCP | `src/spicy_regs/mcp_server.py` `TABLES` | one line per table |

### 5.2 The one base-class change

`RollupPipeline` declares a single `output` and uploads one file through the
shrink guard. The bill family produces eleven tables from one expensive pass;
eleven rollups re-running the family would cost eleven times the acquisition
and model calls. Add `outputs: ClassVar[tuple[str, ...]] = ()`, keep `output`
as a property returning `outputs[0]` when set, let `build()` return one path
or a tuple, and have `run()` upload each through the same guard. Every existing
rollup keeps working. `_rollup.yml` gains `bill_family_congresses`,
`bill_family_bill_types` inputs and the model API key secret.

### 5.3 One source for column prose

`spicy-regs-dict check` reconciles `descriptions.yaml` against a hand-typed
`DERIVED_SCHEMAS`. Generate the new tables' entries from `TABLE_CONTRACTS`
(`[(c, "VARCHAR") for c in contract.columns]`) merged into the hand-typed
dict, so a column added in spicy-docs fails the check until the prose catches
up; and let `descriptions.yaml` declare `columns_from: spicy_docs` for these
tables, reading per-column strings from `TableContract.descriptions`. `label`,
`coverage`, `measured_on` and `summary` stay hand-written in spicy-regs,
because a coverage statement is a spicy-regs measurement.

### 5.4 Release mechanics

spicy-docs has no changelog file; the release note is the commit body
(`b96e083`, "chore: release 0.20.0", touched `pyproject.toml` and `uv.lock`).

spicy-docs 0.21.0 (cut 2026-09-19: commit ff92406, local tag v0.21.0,
`dist/spicy_docs-0.21.0-py3-none-any.whl` 1,009,120 bytes, sha256
`ca3f26c5361f26bd3d38d7789277bff2a72ebfd224a65e65e0f24ec4ed241705`; commit and
tag pushed to origin): land the DeltaTrack adapter branch and the contract layer;
add `docs/tables.md` and index it; `./scripts/check` green; bump the version,
`uv lock`, commit both files as `chore: release 0.21.0` with a body naming what
it carries; `uv build`; tag `v0.21.0`; record the wheel's SHA-256.

spicy-docs 0.21.1 (cut 2026-09-19: commit 6f8d20e, tag v0.21.1 pushed,
`dist/spicy_docs-0.21.1-py3-none-any.whl` 1,025,308 bytes, sha256
`c519e231b44a639c342fa857802869eca258bb4a7051a84b983956a2706e68a6`) carries the
sealed body preference and `body_text`, the bulk listing skip and the
normalization fixes; its adoption on the fork branch follows the same steps.

spicy-regs adoption (done 2026-09-19 on the fork branch `billtrax-hosting-prep`;
no push to origin unless the user names the branch): copy the wheel into `vendor/` and delete the 0.20.0 wheel; point
`[tool.uv.sources] spicy-docs` at it; set both `source-readers` pins to
`spicy-docs[acquisition,pdf-pypdf,bill-diff]==0.21.0`; `vendor/README.md`
gains the spicy-docs bullet with commit, tag and digest. Blocker: the
`bill-diff` extra resolves to a git source, and spicy-regs's vendor discipline
is "wheels supplied explicitly until published in a registry". Build
`deltatrack-0.1.0-py3-none-any.whl` from the pinned commit, vendor it with its
SHA-256, and add a `[tool.uv.sources] deltatrack` path entry. Measured 2026-09-19:
`uv build --wheel` at c636448 builds it cleanly, 206,461 bytes, 29 files, sha256
`7f060e30af9702f4e45c305fa93c53d1e3e59bd70858d3c6717f6fc9cf825197`. Fallback if a
second vendored wheel is refused: the family rollup runs with `diff=False`,
shipping the other eight family tables. Sequencing: the study's `SR01`
(spicy-regs adopting `listing.py`) shares only the frozen ten-column
`congress_bills` prefix with this work, which is why that prefix is frozen.

## 6. Tests the contract layer needs

`tests/test_table_contracts.py`, one loop over `TABLE_CONTRACTS` each:

- every contract is internally consistent (identity within columns, version
  column present or None, no duplicates, descriptions keyed exactly by columns,
  no empty description, snake_case name);
- every shaped row from a real fixture record round-trips through its column
  tuple: same order and set, every value None or str, `contract.key(row)`
  equals the identity rebuilt from the record, every `*_json` column parses
  back to the record's own tuple or mapping, `checked()` accepts it and refuses
  it with one column removed;
- identity is unique over the fixtures;
- every column has a description string.

Fixtures already in the repo: `tests/fixtures/govinfo_bills/status-119hr6028.xml`,
`status-119s5.xml`, `status-119hres1376.xml` (bills, actions, committees,
publisher summaries, versions); `text-119hr6028ih.xml` and `text-119hr6028eh.xml`
(a real consecutive pair for sections and diffs, skipped without the
`bill-diff` extra); `tests/fixtures/press_releases/*.xml` (the Senate feed has
no description, the right stress for a nullable column);
`tests/fixtures/legislators/*.json`; `tests/fixtures/agency_reports/crpt-119hrpt105.txt`.

`tests/test_bill_family.py`: one pass over one fixture bill with both model
seams stubbed; every output row passes its contract; every `bill_sections`
parent exists in `bill_versions`; diff rows exist only for consecutive pairs;
`classify=None, summarize=None` yields empty model tables and no refusals; a
version with `document=None` yields a named `FamilyRefusal`.

`tests/test_activity_events.py`: two snapshots built from the contracts' own
`shape_*` output covering each event type, a changed content hash marking
`regenerated`, a row only in prior producing no event, two versions of one
bill on one date producing two events, and identical snapshots producing
nothing.

spicy-regs side, thin: the Arrow schema equals the column tuple as VARCHAR, the
merge prefers the fresh row on a repeated identity, `spicy-regs-dict check`
passes. The rule cases are not re-asserted there; that coverage belongs where
the logic lives.
