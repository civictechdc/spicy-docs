# Parsing survey: what moves into spicy-docs

Status: evidence for the [consolidation path](consolidation-path-2026-09-22.md),
2026-09-23. Six read-only scouts surveyed every parser in the stack by area:
CFR, Congress, regulatory sources, other sources and walk mechanics, citation
and identifier grammars, and document text. Each ran the competing
implementations through their own `uv` projects over the same retained inputs.
Their scripts and outputs are retained in
`~/Work/corpora/fork-execution-2026-09-21/parsing-survey-2026-09-23/`. Claims
marked **re-derived** were checked again by a second method before being
written here. The rest are single measurements. File and line cites were read
on spicy-docs `5d8c396`, spicy-regs `5780702`, RefSpec `f83c0d7a`, DocSpec
`2cdde74`, spicyengine `31f7959`, spicysearch `b150fdd` and rulespec
`23d5f2d9`; re-read them before acting.

Validated the same evening by seven independent scouts; corrected counts and
wording are folded in below, and the receipts for that validation are in
`~/Work/corpora/fork-execution-2026-09-21/survey-validation-2026-09-23/`.

The survey adds items A5–A12, B6–B12, B18–B19, C4 and D6 to the plan, runs
B4's bakeoff and adds rulings 5–7. The fork's output ledger and backlog (spicy-regs
`docs/research/fork-output-ledger-2026-09-21.md` and `docs/fork-generation.md`)
record which published tables each item touches.

## 1. Where shared parsing can live

- spicy-docs' only Spicy-stack dependency is `rulespec-artifacts` (besides
  `jsonschema` and the optional `deltatrack` extra); it is the root of the
  stack's graph.
- DocSpec, RefSpec, spicyengine and spicysearch pin `spicy-docs==0.26.6`
  exactly. spicy-regs pins 0.29.0 in its default `source-readers` group and
  imports neither RefSpec nor DocSpec.
- spicy-docs cannot import RefSpec (a cycle). spicy-regs could, but uv cannot
  resolve RefSpec's 0.26.6 pin against spicy-regs' 0.29.0.
- RefSpec's `citation_grammar.py` and `identifier_shapes.py` import only the
  standard library, so they can move down.

So shared source parsing belongs in spicy-docs. It reaches spicy-regs at the
next wheel and the other repositories when they repin. Anything touching R2,
DuckDB merges or prior-table policy stays in spicy-regs.

## 2. Quiet bugs, including published values

| Item | Finding | Measured impact | Evidence |
| --- | --- | --- | --- |
| A5 | `bill_subjects` sends the Congress.gov key as a query parameter; on a 4xx, httpx's error text carries the full URL and is logged; 401/403 are retried, not fatal. **Re-derived** from the code; no retained log contains a key. GitHub Actions masks it in CI output; local logs do not. | Every 4xx other than 404 and 429, locally | `spicy-regs/src/spicy_regs/sources/bill_subjects.py:238-244,338,347,350` |
| A6 | Comment attachment text is joined in string order (`attachment_10` before `attachment_2`), and a second extraction tool's text for the same attachment is concatenated too. `text_extraction_status = 'ok'` is written with no extraction record. **Re-derived** from the code. | Up to 656 published comments whose attachment numbers sort differently as strings (597 with 10+ attachments); 70,845 texts without provenance | `spicy-regs/src/spicy_regs/sources/derived_text.py:82` (`keys.sort()`), prefix at `:44-46` |
| A7 | `rule_targets`, `proceedings` and `comment_periods` read FR docket values with a syntax-only normalizer that refuses labelled values ("Docket No. SSA-2010-0037"). **Re-derived:** of 899,227 FR→docket link rows, 48,169 join through the code's normalizer; spicy-regs' own unused `normalize_docket_reference` (`ontology/citations.py:532`) joins 96,803 more, and RefSpec's `normalize_docket_reference` 106,771 more. | 96,803–106,771 Federal Register–docket links unpublished | `spicy-regs/.../build_rule_targets.py:222`, `build_proceedings.py:196`, `build_comment_periods.py:360` |
| A7 | Zero-padded FR numbers from Regulations.gov (`2010-02394`, `E9-09366`) are matched literally against the unpadded FR API form. **Re-derived:** 40,340 of the 49,403 `missing` FR references in the published `rule_targets` exist once leading zeros after the hyphen are removed. | 82% of `missing` references | `build_rule_targets.py:204` |
| A8 | CFR part ancestry is wrong in three shapes (§4). | 9,250 part changes against the live table | §4 |
| A9 | Two of spicy-docs' three bill-number readers over-match: "CR S4530", "paragraph S9", "U.S.C. S300f" read as Senate bills; `bill_signals` keeps the possessive-year error fixed only in `release_matching`. A catalog-existence check cannot see this. | 2,477 extra keys over the 78k actions of the pre-reconciliation generation, all Congressional Record pages ("CR S4557"); 3,765 over the live 153k. `release_matching` adds none on the 28 retained press rows; `bill_signals` reads "President's 2027" as S. 2027 on one live press row. | `src/spicy_docs/interpretation/release_matching.py:23-53`, `interpretation/bill_signals.py:57-63` |
| A10 | `document_citations` target keys keep trailing `.`/`-` and en-dashes, publish U.S.C. ranges as one token, and read only singular lower-case "part" (plural and capitalized forms are missed). | At least 301 of 2,741 `usc_section` citation rows (304 counting unsplit hyphen ranges such as `2-661-661f`) and 4 of 41 `cfr_section` rows carry malformed keys, all published with `target_resolved = true`; that they join nothing is inferred from their shape, since no complete U.S.C. table exists to test against. 4,145 Part/Parts/parts/PART citations are missed in 3,431 of 60k FR titles and abstracts. | `src/spicy_docs/interpretation/citations.py:287,446,455` |
| A11 | Vote days: `bill_vote_references.date` holds the UTC instant; its day is not the publisher's local vote day. `roll_call_votes.vote_date` is the merge's version column but holds literal text that sorts lexicographically (`'1-Apr-2025'` … `'9-Sep-2025'`). `vote_day` refuses a missing House `action-date` that `votes.py:696` allows. | 91 of the 847 vote–date pairs that join `roll_call_votes` (145 of 1,347 joined rows) fall on a different day; 511 of the 1,356 referenced votes are not in `roll_call_votes`; the Eastern day agrees on every joined row. | `spicy-regs/.../build_member_vote_terms.py:57-69`, `build_bill_family.py:832-880` |
| A12 | Day rules for instants differ: `comment_periods` uses the Eastern day, `proceedings` and the agenda truncate to the UTC day, and `rule_targets.first_seen`/`last_seen` mix instants and dates in one column. The bill walk checks only that rows equal the declared count, the check that let the amendments table fall 52 short. | 443,959 of 2,001,531 `documents.modify_date` instants fall on a different day under `comment_periods`' Eastern rule than under UTC truncation | `build_proceedings.py:277`, `build_regulatory_agenda.py:74,174`, `build_rule_targets.py:61-63`; the count check lives in spicy-docs `reading/paged_json.py:486,499`, to which `sources/congress_bills.py:256-291` only hands the walk |

## 3. Second copies to remove

| Item | Copy | Owner it should use | Size |
| --- | --- | --- | --- |
| B6 | `pool_passes` (`spicy-regs/.../sources/pooled_walk.py`) and the pass closures in CRS, amendments, FCC; `walk_route` matching spicy-docs error text with `endswith`; `_fetch_bills` re-walking on drift | A pooled enumeration and a typed `DeclaredCountMismatch(declared, observed)` in `spicy_docs/reading/paged_json.py`; spicy-docs chooses sorts only where the route honours them. When moving, pool by set, not count: a stale record can fill a skipped record's slot, and ECFS proceedings use the whole JSON as identity. | ~150 lines each way; 0.30.0 |
| B7 | ECFS `_COUNTED_BY`, `_window_count`, the 10,000 ceiling and bisection (`build_fcc_ecfs.py:197-395`) | `spicy_docs/sources/fcc_ecfs.py`, deciding on page 1 instead of after 40 pages; fix `fcc_ecfs.py:3-8` and `docs/sources/listings.md:358`, which say ECFS states no count | medium |
| B8 | Response-envelope checks: USAspending `hasNext`/page skips, CourtListener count and empty page, FEC whole-walk count, GAO `_report_id` (spicy-docs' `product_id` already gives it), LDA pacing constants | The owning spicy-docs readers; add `Retry-After` in `transport/retry.py` | small–medium |
| B9 | `spicy-regs/src/spicy_regs/schemas/regulations.py` and `base.py`: a fork of spicy-docs' regulations extractors, differing only in polars types and `pdf_extraction_results_json` | spicy-docs `schemas/regulations.py` plus the enrichment columns; `repair_regulations.py:18` already uses it | ~220 lines deleted |
| B10 | Congress shapers in spicy-regs: `bill_detail` (no spicy-docs route), CRS `_shape` (no contract), hearing `_event_id` and its chamber map (spicy-docs has `CHAMBER_BY_DOCUMENT_TYPE`), the vote-reference round trip (no contract), `_ordered_printings` (restates spicy-docs' private `_sorted_versions` without its tie-break), congress scope constants, `_resolve_api_key`, copied in five spicy-regs modules (`sources/congress_bills.py:220`, `sources/crs_reports.py:36`, `sources/cfr_sections.py:44`, `transforms/build_fcc_ecfs.py:214`, `transforms/build_fec_committees.py:67`) | A `bill-detail` route beside `amendment-detail`, a `CRS_REPORTS` contract, a `BILL_VOTE_REFERENCES` contract with `parse_bill_id`, exported printing order and scope constants | medium |
| B11 | Unified Agenda field navigation in spicy-regs (`sources/unified_agenda.py:73-131`) and RefSpec (`unified_agenda_editions.py:678-688,821-861`) disagree on whitespace (`strip()` versus collapsing internal runs) and on reading every `TIMETABLE_LIST`, `CFR_LIST` and `LEGAL_AUTHORITY_LIST` versus the first | One field-path projection in `spicy_docs/sources/unified_agenda/records.py` | small |
| B12 | Document text (§6) | spicy-docs `reading/` and `extraction/` | large |

B2 (Federal Register `_shape`) and B5 (`backfill_status`, Senate report
selection) are confirmed still open. A3's two bill-key rules were run on the
same MODS inputs: `0053` gives `119-hres-0053` in spicy-docs and `119-hres-53`
in spicy-regs, and an HDOC bill gets a key in spicy-docs where spicy-regs
refuses it. No padded key occurs in the retained generation, so it is latent.

## 4. CFR section ancestry (T11)

`cfr_sections` takes part and section from GovInfo granule ids. The id cannot
distinguish `sec100-1` (§ 100.1, part 100) from title 14 vol 4's `sec19-8-1`
(`19-8.1`, part 241). One streaming pass over the 262 annual volume XMLs
(255,562 sections, 10,855 parts, 13.9 s) through spicy-docs' `scan_xml`
compared each section's printed number with its enclosing `PART` heading:

- **Title 43, 3,018 sections.** Sections are numbered by subpart: § 1601.0-1
  sits in part 1600. The live table says 1601, a part that does not exist.
  **Re-derived** with eCFR's ancestry API: part 1600, subpart 1601. RefSpec's
  grammar and the scratch rule from the same day agree with the live table
  because all three read the leading number, so their agreement is no evidence.
- **Title 41, 4,732 live rows.** Compound parts are truncated at the first
  hyphen (part `50` for `50-201`). Every GovInfo-derived field splits there
  too: granule tokens, MODS `partRange` and granule ancestry. Only the volume's
  `PART` heading and eCFR keep `50-201`. **Re-derived** with eCFR: part
  `50-201`.
- **Title 14 vol 4, 1,492 NULL rows.** The bounded correction nulled 1,444
  parts; 1,434 of them matched the heading, and only the ten `19-8.x` sections
  (part 19 → 241) were wrong. The other 48 (`Sec. 1-N` granules) were NULL
  before the correction. MODS agrees with the heading on 1,484 of 1,484.
- **Eight other rows:** six publisher typos (`§ 206.253` under `PART 1206`),
  each confirmed by GovInfo's granule ancestry, and two ranges ending in the
  heading's part (`§§ 1509.203-1519.204` under `PART 1519`).
  3,018 + 4,732 + 1,492 + 8 = 9,250.

The part number exists only as text: `PART` elements carry no attributes. Read
the heading, not the running head (8 running heads are wrong, e.g. `Pt. 1208`
over `PART 1209`), with an anchored pattern that stops at the dash:
`^\s*PART\s+(\d+[A-Za-z]?(?:-\d+[A-Za-z]?)*)(?=[—–\s]|-(?=[A-Za-z])|$)`,
case-insensitive. A version without the leading `\s*` misses 21 headings that
begin with a newline (994 sections, e.g. 12 CFR 326) and
`PART 1-POSTAL POLICY` (39 CFR part 1); this one gives the 9,250 from the
heading alone, with no running-head fallback. Patterns that fold dashes before matching misread
`PART 8—4-H CLUB` and `PART 124—8(a)`. The scan must take the innermost
`PART`, keep nested sections (4,351, mostly revised text under effective-date
notes, and one wrapper holding 1,032 sections in title 41 vol 4) and prefer the
un-nested copy where a number recurs in nested text (250 numbers); 11 numbers
repeat outside nesting, and both copies of each share one heading part.

Of the 1,734 granules the scratch scan did not match, 1,498 have parenthesized
numbers that GovInfo drops (`sec1-1h-1`) and 164 have dashes GovInfo folds (3
have both and are counted as dashes). Normalizing those leaves 72: 50 appendix
and 18 TOC granules, which are not sections, and 4 content granules (three
GovInfo `-id` duplicates and `title26-vol17-sec37`).

**Design.**

1. spicy-docs `sources/cfr/annual.py`: a streaming section-ancestry scan on the
   existing `_AnnualScan`, returning each section's printed number, heading
   part and flags (nested, revised text, reserved). One granule-token helper,
   shared with `annual_cfr_xml_locator`: strip `§` and whitespace, drop
   parentheses, fold dashes, `.` → `-`. Merge `_ANNUAL_SECTION` and
   `reconstruction/parse.py`'s `_NUMBER` into one pattern (`_ANNUAL_SECTION`
   rejects 6,389 printed section numbers in the 262 volumes, 3,184 of them
   single sections) and allow `vol0`.
2. spicy-regs `build_cfr_sections`: one download and scan per volume, then a
   lookup per granule: O(bytes + granules) against about 255k requests for
   per-granule summaries. `part` is the heading part; `section` is the number
   less its `{part}.` prefix; ranges, typos and title 14 Part 241's
   `Section 01` forms get a NULL `cfr_ref`.
3. Delete the scratch parser, `_PART_RE`/`_SECTION_RE` for section granules,
   `cac7615`'s null rule (keep its refusal of incomplete walks) and the title 14
   nulls.
4. Reuse spicy-docs' `tests/fixtures/cfr/annual-*.xml` and
   `test_native_part_is_not_inferred_from_section_number`, and add excerpts
   for 43/1600, 41/50-201, the title 41 vol 4 wrapper, `PART 8—4-H` and 12
   vol 10's running head. MODS and eCFR are the independent checks.

Point-in-time eCFR is a good check but the wrong source: it is a different
publication and costs one request per title and date. TOC and node rows in
title 41 keep truncated parts from the id; a section scan does not reach them.
RefSpec's `registry/ecfr.py:59` `section_addresses` raises `ValueError` on
full-title eCFR 43 CFR Part 1600 (on a bare part file it fails earlier, for
want of title context).

## 5. Citation and identifier grammars (B4)

There are five prose grammars, not three: RefSpec `citation_grammar.py`,
spicy-regs `ontology/citations.py`, rulespec-projection `citations.py` (a copy
of spicy-regs'), spicysearch `identifiers.py` and spicy-docs
`interpretation/citations.py`. Against RefSpec over 60k Federal Register titles
and abstracts that carry a citation marker:

| Reader | CFR: only RefSpec reads | CFR: only this reader reads | U.S.C.: only RefSpec | U.S.C.: only this reader |
| --- | ---: | ---: | ---: | ---: |
| spicy-regs / projection | 1,072 | 14,065 | 1,360 | 18,120 |
| spicysearch | 1,214 | 132 | 1,797 | 276 |
| spicy-docs | 5,463 | 1,413 | 4,655 | 2,522 |

RefSpec stores CFR ranges under a separate key, so a reader that emits a range
start counts under "only this reader" (111 of spicysearch's 132, 511 of
spicy-regs', 62 of spicy-docs'); and 947 of spicy-docs' 5,463 CFR and 709 of
its 4,655 U.S.C. "only RefSpec" citations are ones spicy-docs reads but
respells with a trailing `.` or `-`. Hand-reading ten specimens each way,
RefSpec was right in all but three: it read `40 CFR Part 1500-1508` and
`1500-08` as one part and missed `21 U.S.C. 1901- 1908`.

spicy-regs' text grammar invents citations from years and street numbers
("11555 Rockville Pike"), but no production path reaches it: all 294,501 FR CFR
entries arrive as structured objects. Its production callers are four
functions (`parse_cfr_citation`'s dict branch, `normalize_rin`,
`normalize_regsgov_identifier`, `canonical_cfr_iri`). The projection's copy is
live code in the published `rulespec-projection` package (`projection.py:54-64`),
though nothing runs it outside its tests, and would mint wrong identifiers
(`8 CFR 213a` → part 213; `1395hh` → `1395h`; 28,862 modern FR numbers such as
`2010-1000`, which RefSpec mints as `rkaf:us-frdoc`, would land under
`urn:spicy-regs:frdoc:`, a prefix RefSpec's minter refuses). Its docket
normalizer accepts 84,074 non-Regulations.gov strings, which only the
published-row gate keeps from minting.

**Recommendation.**

- Make RefSpec's `citation_grammar` and `identifier_shapes` canonical. Move
  them into spicy-docs as standard-library modules, and have RefSpec import them
  back. The grammar is hashed into RefSpec's receipts, so the receipt identity
  moves; say so in that commit.
- Rewire spicy-docs `document_citations` to the moved grammar (A10) and bump
  its rule versions.
- In spicy-regs, keep a roughly 20-line dict reader plus the validators and
  delete about 700 unused lines and their tests.
- The projection reads parsed rows instead of carrying a grammar, and takes
  RefSpec's `iri_minting` (REF-024 puts identity functions in Rulespec Core).
- spicysearch keeps its query grammar behind its boundary test (plan §11): it
  detects shapes in query strings and refuses unlabelled tokens on purpose.
  Only the data-side grammar moves (spicy-regs decisions record, decision 14).
- RIN: keep `\d{4}-[A-Z]{2}\d{2}` as the published key. The wider shapes
  accept only damage (`1625-AAOO`) or placeholders (`2060-XXXX`): RefSpec and
  spicysearch accept 99 and 97 such values, and the `[A-Z][A-Z0-9]{3}` shape
  in spicy-docs `sources/federal_register/native.py:74` and DocSpec
  `application/catalog_policy.py:15` accepts 254 (e.g. `0648-A110`); spicy-docs
  `interpretation/citations.py:291` is already strict. Use the wider shapes for
  detection only.
- Bills: keep `CONGRESS_CHAMBER` plus `bill_type_and_number`; delete the
  patterns in `release_matching` and `bill_signals` (A9).
- Order: move and release in spicy-docs → `document_citations` → RefSpec →
  spicy-regs → projection.

Published-value impact: `rule_targets.cfr_ref` none (structured input);
`document_citations.target_key` about 305 respelled and 235 ranges split plus
the recall gain; `press_releases.bill_id` none on current rows.

## 6. Document text (B12)

The three XML/HTML-to-text readers (spicy-docs `extraction/body_text.py`,
DocSpec `processing/visible_text.py`, RefSpec `registry/xml_text.py`) all sit on
spicy-docs' reading layer (`reading/markup.py`; RefSpec's `xml_text.py` on
`reading/xml.py`). `body_text` and DocSpec extract the same characters in the
same order on 184 of 184 real inputs once quotes, heading markers and all
whitespace are removed and DocSpec's `<title>` is dropped from the 118 htm
files; that comparison cannot see words run together. RefSpec produced text for
6 of the 184. What differs is policy, and each has a defect:

- DocSpec keeps a `<title>` outside `<head>` in 118 of 118 GovInfo htm bodies,
  against its own comment, and runs words together at block boundaries with no
  source whitespace (`Provision.—Nothing`) and at `<br/>`.
- `body_text` splits at inline elements (`(Public` → `(` + `Public`: 6,617
  times in 30 of 42 bills by an independent alignment; 6,593 by the survey's
  token script, which stops at a document's first misalignment) and discards
  its reader's byte spans (`body_text.py:244-254`).
- RefSpec's reader refuses bill XML, public-law USLM and annual CFR.

**Recommendation:** one visible-text layout in spicy-docs `reading/`, taking
DocSpec's block-and-byte-run model with named profiles (RefSpec's block
vocabularies, `body_text`'s inline list, `<title>` suppression). RefSpec keeps
its codepoint projection; DocSpec's extractor id moves to v3 because its output
changes. Also:

- RefSpec's six direct `PdfReader` calls in five modules use `PypdfReader`
  where they can; the thesaurus reader relies on `visitor_text`, which
  `PypdfReader` does not offer. `fold_pdf_text` moves to spicy-docs
  `extraction/`.
- GPO normalization becomes an explicit per-collection profile. On 96 ordinary
  comment attachments it changed 26 after folding quotes (66 without), merging
  small-caps lines, stripping "gutter numbers" and, through the bullet rule
  `^[•·]\s*[A-Z]` (`gpo_normalize.py:33`), deleting 226 lines in 10
  attachments.
- The regex tag strippers use the markup events reader: spicy-docs
  `sources/federal_register/list_of_subjects.py:60` and
  `sources/uscode/classification.py:45,188`; spicy-regs
  `transforms/build_search_index.py:33`, which unescapes before stripping and
  so deletes decoded `<…>` text; RefSpec `ferc_elibrary_codes.py:398`,
  `census_geo_codes.py:357`, `fec_committee_codes.py:461` and
  `umthes_content.py:75`.
- Mirrulations derived-text fetching moves to spicy-docs
  `sources/mirrulations.py`, returning per-attachment key, tool, size and
  digest (A6).

`report_sections` and `bill_sections` stay unchanged if the htm profile keeps
its output; every DocSpec representation changes. Fold PDF ligatures (5,602
comment texts) in the search analyzer, not the published column.

## 7. Repeated work

- The rulemaking builders each rebuild the Federal Register index: four times
  per generation, 5.2 s plus a 4.2 s `record_id` pass each. `rule_targets`
  recomputes references per docket × citation × RIN
  (`build_rule_targets.py:268-284`). `proceedings` scans all groups per
  unresolved reference (`:407-415`); zero fire today.
- ECFS fetches 40 pages (10,000 records) before learning a window is over the
  ceiling, then walks both halves again.
- `bill_subjects` makes one request per bill; the bill family's BILLSTATUS
  bulk read already carries policy area and subjects.
- Amendment detail costs one request per amendment (about 89 minutes for a
  whole Congress). Whether BILLSTATUS amendment entries carry sponsors is
  unmeasured.
- `PriorIndex.held_codes`/`xml_codes` scan every printing per bill
  (`build_bill_family.py:602-610`): linear in bills × printings.
- The SAM extract download bypasses the bounded client, holds the file in
  memory about four times and keeps no evidence (spicy-docs
  `src/spicy_docs/sources/sam_extract.py:367-439`).
- spicy-regs `backfill_derived_text.py:156` holds every fetched comment text until the
  end (2.72 GB in the sample).

## 8. Rulings this adds

Numbered as in the plan's §5. Decided 2026-09-23 by delegation; the reasons are in
the spicy-regs decisions record (`docs/research/fork-delivery-decisions-2026-09-22.md`,
decisions 17–21).

5. `cfr_ref` for title 43's subpart-numbered sections (A8): **the printed
   citation (`43-1601.0-1`), with part 1600.**
6. Whether `rule_targets`, `proceedings` and `comment_periods` admit
   label-derived dockets and unpadded FR numbers (A7, A12): **both, with one
   actor-id bump per table, through RefSpec's reader.**
7. Comment text without an extraction record, and which Mirrulations tool wins
   (A6): **status `derived`; one tool per comment by a fixed, measured
   preference order.**
8. Keep `catalog.json` (§9): **no; keep only `table_metadata.json`.**
9. Who normalizes search fields (§9): **spicysearch for now; spicy-docs after
   D3.**

## 9. Metadata (spicysearch, spicy-regs, DocSpec)

spicysearch builds per-record search metadata (facets, dates, identifiers,
display) from DocSpec Federal Register and Regulations.gov records
(`spicysearch/src/spicysearch/metadata/preparation.py:164` `prepare`;
`metadata/enrichment.py:120`, `derive` at `:159,176`). spicy-regs builds
per-table and per-column metadata (`src/spicy_regs/data_dictionary.py`,
`data_dictionary/catalog.json`, `src/spicy_regs/table_metadata.json`, the
publication index). They meet in one place: spicysearch's vendored
`vendor/spicy-regs-catalog-dictionary.json`, which no code reads and which is
stale (75 classes against 79; 9 commits behind).

- spicy-regs' outputs agree with each other and with spicy-docs:
  `catalog.json` is an exact projection of `table_metadata.json` for 79 of 79
  tables; the 39 contract tables equal the 0.29.0 contracts in columns, prose,
  grain and identity; the 74 tables in `publication.json` match their declared
  columns and types.
- `DERIVED_SCHEMAS` (`data_dictionary.py:250-648`) repeats a producer's column
  constant in 18 of 26 entries (e.g. `build_cfr_sections.COLUMNS`);
  `federal_register`'s entry is a third copy (plan B2). `table_metadata.json`
  declares no identity for 23 of the 74 published tables, though each
  `merge_table` call is given one.
- The real overlap is with DocSpec: spicysearch re-derives from raw source
  facts the fields DocSpec stores in `normalizedMetadata`. On 8,663 retained
  records (a stratified audit sample, not random) they agree 100% wherever
  DocSpec has a value (title, type, publication day, comment close, dockets,
  RINs); 79 of 2,496 FR agency values differ because the retained state
  predates DocSpec's current agency rule. Both read the same raw fields, so
  agreement shows duplicated work, not correctness.
- Identifier enrichment (`spicysearch/src/spicysearch/catalog_enrichment.py:88`,
  `resolve_many` at `:123`; spicyengine `indexing/enrichment.py:45`) added no
  key the prepared identifiers lacked on those 8,663 records, and costs one
  DocSpec operation per record: about 7 h and 26 GB for the 1.0M FR records at
  the plan's 25 ms and ~26 KB per record.
- The preparer refuses rows shaped like a spicy-regs generation ("requires
  exactly one identity-matched native fact"), so deriving search metadata over
  admitted generations (plan D3/D5) needs a reader keyed on spicy-docs'
  contracts. spicy-docs 0.26.6's `TABLE_CONTRACTS` already covers 38 of 39
  tables as 0.29.0 does (only `congress_bills` adds `url_source`).
- The MCP server re-reads every table's footer on a cold start (about 35 s),
  although `publication.json` already carries the columns.

Scripts and outputs:
`~/Work/corpora/fork-execution-2026-09-21/survey-validation-2026-09-23/metadata/`.

## 10. Not verified

- Whether the congress bill walk has already lost bills.
- Whether Congress.gov's `toDateTime` is inclusive; the bill and amendment
  walks spell the window end differently.
- How often a comment has more than one Mirrulations tool directory.
- The GPO normalizer on real GovInfo PDFs; none are retained.
- The CFR heading pattern beyond 3 packages against MODS, 14 granules against
  granule ancestry and 3 parts against eCFR; 1,449 parts with neither heading
  nor running head were spot-checked in one volume.
- Whether the volume bytes from `/content/pkg` equal spicy-docs' bulkdata
  locator's.
