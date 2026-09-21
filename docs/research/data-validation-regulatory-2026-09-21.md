# Regulatory data validation — 2026-09-21

The inspected source readers preserve substantially more useful information
than the currently published regulatory tables contain. The strongest immediate
work is adopting and backfilling existing fields, correcting identity errors,
and qualifying the derived lifecycle claims. A schema-valid public file is not
evidence that these steps have happened.

This audit covers 15 hosted tables and seven source families. It distinguishes
the current SpicyDocs checkout, the SpicyRegs host pinned to SpicyDocs 0.24.2,
retained native source bytes, and independently captured public artifacts.
No package release, upload, or deployment was performed by this audit.

## Evidence and method

New evidence is under
`~/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/`.
Below, `R` means its `regulatory/` directory and `P` means its `public/`
directory. Full paths, input digests, named source examples and per-table
dispositions are in `R/table-assessments.json`, `R/source-assessments.json`,
and `R/native-input-pins.json`.

- Inspected every retained ACF source record in the two source-native releases:
  391 dockets and 546 documents. Independent checks of the current conversion
  covered 9,289 fields. Their exact raw blob paths accompany each output row in
  `R/regs-dockets-ACF-pairs.json` and `R/regs-documents-ACF-pairs.json`.
- Compared the complete retained Fall 2025 Unified Agenda XML: 3,954 records,
  43,494 independent native-field checks and 67,218 public output comparisons.
- Compared 20 native Federal Register records with all 440 hosted fields;
  two FCC proceedings and two filings with all 64 hosted fields.
- Replayed retained annual CFR, eCFR title/part/section, title roster, annual
  MODS, agency roster, and two subject-index excerpts. Identity validation is
  distinct from whole-body extraction quality.
- Inspected complete public files for the other owned tables. The comment
  artifact is explicitly a sample: 212,733 rows from the first, middle and last
  row groups of a 23,889,661-row public object. It is not a random sample.
- Made ten small fresh read-only operations: six S3 operations for three
  named comments, two for one document with an unusual date, and two Federal
  Register daily metadata requests. Exact responses, object ETags and digests
  are retained. No model calls or full-population acquisition were used.

Public files were observed independently. In particular, `documents` refused
the earlier ETag with HTTP 412 and required a new version observation, retained
in `public-documents-refresh.json`. Small differences between derived files and
these parents cannot alone establish calculation errors or a shared generation.

`R/public-comparison-verified.json` is the authoritative comparison. The earlier
`R/public-comparison.json` used a Pandas conversion that turned some NULLs into
NaN and produced false differences. It is retained as a rejected intermediate;
the verified run uses Arrow values and preserves NULLs.

## Demonstrated findings

### Public regulatory rows omit known source facts

All 391 ACF docket identities and all 546 document identities were found in
the public files. Forty-seven source docket RIN values differ from public rows;
45 have the same `modify_date`. Ten of the 47 are the publisher's literal
`Not Assigned`, which must not be counted as usable RIN links. For example,
`ACF-2015-0001` supplies `0970-AC47`, while its public RIN is NULL.

Among the 546 document pairs, public rows differ on 496 attachment arrays,
492 primary URLs, 488 Federal Register numbers, 503 withdrawal values, and
five withdrawal reasons. Five hundred two rows differ despite an equal source
modification date. `ACF-2006-0058-0001` supplies PDF and HTML renditions and
FR number `06-04731`; the public row has NULLs for those fields.
`ACF-2019-0005-0243` is marked withdrawn for `duplicate document` in the
retained source, while the public withdrawal fields are NULL.

The current extractor preserves these fields. This is evidence for a public
backfill/adoption gap, not a reason to rewrite the current parser. Source
timestamps differ on four docket rows and three document rows; those rows
remain explicit cross-version comparisons.

Three fresh Mirrulations comment records also contain attachments absent from
their public rows: `ACF-2008-0001-0002`, `ACF-2009-0004-0002`, and
`ETA-2025-0001-0002`. Two contain organizations omitted publicly. The bounded
probe is not a population error estimate. `R/comments-probe.json` retains the
raw paths, source versions, current conversion, and actual public rows.

### Federal Register number-only identity loses distinct documents

The fresh daily responses contain two different documents numbered `00-111`:

| Publication date | Native title |
| --- | --- |
| 2000-01-14 | Compliance Monitoring and Miscellaneous Issues Relating to the Low-Income Housing Credit |
| 2000-01-18 | Notice of Filing of Plat of an Island; Minnesota |

The public table contains only the January 18 row. Both source responses are
retained in `R/fr-collision-response-1.bin` and `-2.bin`, with the selected
records and public survivor in `R/supplement.json`.

The current host builder's `ROW_NUMBER` partitions only by `document_number`
(`spicy-regs/src/spicy_regs/transforms/build_federal_register.py`). The
dictionary's `document_number` sentence likewise calls it the primary/dedup
key. The source-native composite release is a separate artifact and does not
repair that host behavior. The bounded correction is a composite key using
`document_number` and `publication_date`, followed by a consumer review.

Dependent surfaces need deliberate treatment: `build_fr_docket_links.py`
already carries both number and date and explodes each parent row; the
`ontology/citations.py` Federal Register identifier remains number-based;
Regulations.gov `fr_doc_num` is also a number-only observation. Preserve these
observations and refuse ambiguous joins instead of choosing a date silently.
No Federal Register implementation change was made in this audit unit.

### CFR part identifiers are truncated

The 319,186-row public CFR table contains 336 explicit lettered part tokens
whose hosted part and citation drop the suffix. For example, both
`CFR-2026-title14-vol5-part1203a` and `...part1203b` become `14-1203`;
`CFR-2026-title7-vol1-part15a` becomes `7-15`. The current regex reproduced
the error. Four retained-ID regression tests failed before the narrow fix;
all 21 CFR tests, focused Ruff and type checks passed afterward. The change
only preserves the explicit suffix; it does not infer more hierarchy.

A separate unresolved inference is demonstrated by the retained native eCFR
fixture: section `19-8.1` belongs to Part `241`. The current host's numeric
prefix rule produces Part `19` from the corresponding granule spelling.
The public older row has no part, so this is a current-converter defect rather
than a claim that its public value already changed. Also, `EcfrSelection`
currently rejects lettered part requests such as `1203a`. Both limits remain
open in `R/supplement.json`.

Annual identity also needs care: the retained 2025 Title 1 body states a 2023
revision, and MODS explicitly identifies the 2025 edition as cover-only.
The native readers preserve that distinction. The hosted section table has
neither body text nor these edition facts.

### Lifecycle labels omit or collapse source groups

The lifecycle output is a heuristic over posted dates and shared docket IDs,
not a qualified statement of regulatory completion. Its 26,516 rows mostly
reproduce the current calculation; one new OPM proposal explains the sole
additional expected row in the independently observed parents.

The calculation omits 647 proposal groups because their earliest Rule precedes
their earliest Proposed Rule: they become neither a pair nor a stuck proposal.
There are also 19 `stuck` rows with NULL docket IDs, one per agency. The complete
grain `(kind, docket_id, agency_code)` has no duplicate groups. The 5,132
NULL-docket parent proposals first form 75 agency groups; 19 groups survive
the earliest-date 2010 floor and collapse 48 source proposals. The other 56
groups, containing 5,084 source rows, fall below that floor. The retained rows
still lose document identity: two distinct OSTP proposals from 2012 and 2018
become one 2012 row. `R/lifecycle-null-grain-review.json` retains the independent
query and these separate denominators. The title uses
`ANY_VALUE`, so it is not guaranteed to describe the earliest dated proposal.
There are 1,573 zero-day pairs; this count is not an accuracy verdict.

The next step is to define pairing, missing-ID and evidence requirements before
qualifying the labels. Retain the participating document IDs. Do not classify
every omitted row as completed or stuck without source evidence.

### A source date anomaly is not a conversion error

Eight public documents state year `0000`. A fresh ETag-pinned mirror capture
for `ED-2020-SCC-0097-0002` also states `0000-12-30T00:00:00Z` in `postedDate`.
The raw value should remain available with an anomaly indication. It must not
be treated as an ordinary calendar year or silently replaced with another date.

## What the derived checks establish

| Table | Direct check | Limit or next action |
| --- | --- | --- |
| `fr_docket_links` | All 719,937 rows exactly equal independent array expansion, including display fields. | Only 47,693 link rows match an exact held Regulations.gov docket ID. Literal source IDs need qualified mapping, not automatic rewriting. |
| `agency_stats` | 316 agencies compared; four differ. | Differences are 22 comments across three agencies and one OPM docket/document; publish parent pins before claiming a common generation. |
| `agency_monthly_volume` | 77,932 groups; only OPM September 2026 Proposed Rule count differs by one. | 2,020 parent rows have unparseable dates; year-zero values need explicit analytic handling. |
| `feed_summary` | Matching titles, deadlines and creation dates agree. | One new OPM docket is absent; three comment counts and modification dates differ. |
| `comments_index` | All 112,861 keys are unique and counts positive; sampled comment agency/docket pairs exist. | Counts sum to 23,888,128, 1,533 below the independent monolith footer. A complete partition census was not acquired. |
| `discovery_signals` | All nine ratios equal `recent_30d / baseline`. | No as-of timestamp or parent version identifies the claimed 30-day window; the temporal calculation is unvalidated. |

## Useful source fields omitted by hosted selection

These omissions are directly observed, but adding columns is a separate design
decision. Source-native bytes already preserve many of them.

- The 546 ACF document records contain 206 nonempty `cfrPart` values, 127
  topic arrays and 19 document abstracts. `ACF-2006-0058-0001` states
  `45 CFR 303` and child-support topics; `ACF-2018-0004-0001` supplies an
  abstract explaining its proposed compliance/effective-date delay.
- Fall 2025 Agenda records contain 435 legal-deadline blocks, 379 related-RIN
  lists and 418 public-comment URLs omitted from the host. The complete raw
  timetable survives, but 2,922 entries use day `00`; derived scalar dates
  impute day one and do not carry an explicit precision column.
- FCC proceeding `26-24` supplies four topic tags omitted from its hosted row.
  Filings supply `date_last_modified` and stable submission-type codes that
  the host drops. Creation/receipt dates do not identify source corrections.
- All 20 inspected FR records supply `full_text_xml_url`, omitted from the
  hosted shape. Their native topic arrays remain outside that table as well.

## Four-dimension dispositions

“Supported” means supported only in the named inspected scope. “Limited”
means incomplete coverage or a shape that restricts the stated use. The JSON
assessment files provide exact artifact paths, denominators and next actions
for every row below; unknown evidence is not counted as a pass.

| Table | Conversion | Completeness | Shape | Useful analysis and next action |
| --- | --- | --- | --- | --- |
| `dockets` | Supported for retained mapped facts | Defect: missing known RIN values | Supported sampled identities | Docket discovery; backfill the RIN bridge. |
| `documents` | Supported for retained mapped facts | Defect: known links/withdrawal facts omitted | Limited; no captured bodies | Evidence retrieval; backfill existing fields and preserve read state. |
| `comments` | Supported in three raw/public pairs | Defect: known attachments omitted | Limited body/read provenance | Read submissions; backfill attachments and broaden native sampling. |
| `comments_index` | Unvalidated against complete partitions | Limited generation accounting | Supported full index keys/count domains | Fast comment counts; reconcile a pinned partition generation. |
| `feed_summary` | Supported calculation in compared scope | Limited cross-version match | Limited build provenance | Browse docket activity; publish parent pins and build time. |
| `agency_stats` | Supported calculation in compared scope | Limited cross-version match | Limited build provenance | Agency volume comparisons; distinguish missing input from zero. |
| `agency_monthly_volume` | Supported grouped counts | Limited date/generation scope | Limited date anomalies | Monthly activity; disclose excluded and anomalous dates. |
| `rulemaking_lifecycles` | Limited heuristic | Defect: omitted proposal groups | Defect: unknown IDs collapse | Candidate lifecycle research; qualify pairing and retain evidence IDs. |
| `fr_docket_links` | Supported all-row expansion | Limited exact-ID coverage | Supported literal links | Printing lookup; qualify cross-source mapping. |
| `discovery_signals` | Unvalidated temporal claim | Limited as-of evidence | Defect: missing time identity | Spike triage; retain as-of and parent version. |
| `cfr_sections` | Defect: lettered parts truncated | Limited metadata-only coverage | Limited hierarchy/edition facts | Annual structure lookup; adopt suffix fix and resolve hierarchy separately. |
| `unified_agenda` | Supported full selected edition | Limited hosted fields/history | Limited scalar date precision | Planned-action tracking; retain needed deadlines and date precision. |
| `federal_register` | Defect: number-only identity collapse | Defect: lost date-distinct item | Defect: ambiguous key | Metadata retrieval; adopt composite identity with consumer review. |
| `fcc_proceedings` | Supported two source pairs | Limited field/history sample | Limited revision provenance | Proceeding lookup; preserve useful topics and correction state. |
| `fcc_filings` | Supported two source pairs | Limited accumulating sample | Limited revision provenance | Express-comment/attachment retrieval; preserve modification identity. |

The seven source-family dispositions separately cover `regulations_gov`,
`mirrulations`, `public_comments`, `federal_register`, `unified_agenda`, `cfr`,
and `fcc_ecfs`. The public-comment row reader conserved all 212,733 sampled
rows and 525 attachment rendition links with zero refusals or diagnostics.
This establishes conservation of its table input, not completeness against
the original publisher. Native partition acquisition, uninspected body routes,
and historical populations remain explicitly unvalidated.

The raw CFR/index/roster checks support their inspected identity and metadata
behavior; they do not establish whole-report body extraction accuracy or a
hosted field for every reader. No inference accuracy threshold was invented
after inspecting these examples.
