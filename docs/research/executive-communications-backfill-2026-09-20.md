# The pre-114th executive communications are already published, in the Record

Status: measured 2026-09-20 against Congress.gov and GovInfo. **40 requests**
(10 Congress.gov, 30 GovInfo), every cap declared before its run. Input pins,
the commands, the retained bytes and the request ledger are in
`~/Work/corpora/supply-2026-09-02/receipts/executive-communications-backfill-2026-09-20/`.
Nothing under `src/` or `tools/` was changed; this is research.

This note reopens [gap A6](closing-the-gaps-2026-09-19.md). That row measured
requirement 8070's 92,450 matching communications, found detail records only
from the 114th Congress (26,725 rows, 28.9%), read 28.9% against a
self-declared 50% threshold, and left `house_requirements` unhosted. The
threshold was a prior judgment made in the absence of an alternative. There is
an alternative, and it is the publisher of record.

**The finding.** Congress.gov's `house-communication` detail record is a
decomposition of one sentence printed in the Congressional Record's House
section `EXECUTIVE COMMUNICATIONS, ETC.`. For 114th EC 4329 the publisher's
`abstract` **equals** the printed entry under exactly two normalizations, and
`submittingAgency`, `submittingOfficial`, `legalAuthority` and the committee
referral are spans of that same sentence. The Record prints that section for
every House sitting day back to 1994 -- the whole 104th-113th gap -- as a
titled GovInfo granule with an HTML rendition. The pre-114th details are not
missing. They were never absent; they are only un-decomposed.

## 1. What Congress.gov actually states before the 114th

| Route | Answer | Evidence |
| --- | --- | --- |
| `house-communication/104`, `house-communication/108` | HTTP 200, `count: 0`, zero rows | `congress-gov/p3`, `p4` |
| `house-communication/108/ec/543` | HTTP 404 | `congress-gov/probe-congress-log.json` |
| `house-communication/112/EC/2`, **the publisher's own stated URL** | HTTP 404 | `congress-gov/probe-case-log.json` |
| `house-communication/114/EC/4329`, same spelling | HTTP 200, 15 fields | `congress-gov/p9-detail-era-publisher-url.json` |
| `house-requirement/8070/matching-communications` | 92,450 rows of **five** fields: `chamber`, `communicationType{code,name}`, `congress`, `number`, `url` | `congress-gov/p1`, `p2` |
| `house-requirement/8070` | one row; `updateDate` `2021-08-13` | `congress-gov/p6` |

Two things follow, and the brief's third route dies on the first of them.

**There is no pre-114th list row to host.** The `house-communication` list
route answers 200 with a declared count of zero. Per
[`AGENTS.md`](../../AGENTS.md), that is a *requested-empty*, not absence -- but
it is also not a row. The only Congress.gov statement of a pre-114th EC number
is the 8070 matching list, and its five fields carry no date, agency, subject,
authority or referral. A table built from them would state that a
communication exists and nothing about what it communicated.

**The detail floor is the publisher's answer, not the probe's spelling.**
`tools/analysis/legislative_data_map.py`'s `measure_requirements` builds its
detail path with `code.lower()`, while the publisher's own list row spells it
`.../house-communication/112/EC/2`. A measurement that only ever asked the
lowercased form could not have seen a route that answers the uppercased one.
Probe 6 requested the publisher's locator verbatim, read off the retained list
page rather than rebuilt: 404 for the 112th, 200 for the 114th. A6's floor
survives re-derivation under a different construction.

## 2. The decisive measurement: the abstract *is* the Record entry

Seven daily Record issues, one per sampled Congress, each resolved to its House
`EXECUTIVE COMMUNICATIONS, ETC.` granule through the repository's own
`GovInfoBodyAcquirer.acquire_granule` (granule summary, granule MODS, then the
keyless HTML rendition -- identity proved before bytes, as
[`docs/sources/govinfo-bodies.md`](../sources/govinfo-bodies.md) requires):

| Congress | Package | Granule | Entries | EC numbers |
| --- | --- | --- | ---: | --- |
| 104 | `CREC-1996-06-12` | `-pt1-PgH6282-5` | 54 | 3,517-3,570 |
| 106 | `CREC-2000-06-14` | `-pt1-PgH4483` | 30 | 8,123-8,152 |
| 108 | `CREC-2004-06-16` | `-pt1-PgH4278` | 26 | 8,544-8,569 |
| 110 | `CREC-2008-06-11` | `-pt1-PgH5326-4` | 14 | 7,086-7,099 |
| 112 | `CREC-2012-06-06` | `-pt1-PgH3575-8` | 41 | 6,321-6,361 |
| 113 | `CREC-2014-06-11` | `-pt1-PgH5317-3` | 29 | 5,913-5,941 |
| 114 | `CREC-2016-02-12` | `-pt1-PgH815-4` | 22 | 4,329-4,350 |

Every issue carries the section as a `granuleClass: HOUSE` granule titled
exactly `EXECUTIVE COMMUNICATIONS, ETC.`, offering `htm` and `pdf`. Each day's
EC numbers are **contiguous and strictly increasing**.

The seventh issue is the control that makes the rest mean something.
2016-02-12 is the `congressionalRecordDate` the 114th EC 4329 detail record
states, so it is the one day whose printed entries can be checked against the
publisher's own decomposition of the same communications.

> **Printed** (`CREC-2016-02-12-pt1-PgH815-4`): *A letter from the Deputy
> Director, Directorate of Cooperative and State Programs, Occupational Safety
> and Health Administration, Department of Labor, transmitting the Department's
> final rule **--** Maine State Plan ... (RIN: 1218-AC97) received February 9,
> 2016, pursuant to 5 U.S.C. 801(a)(1)(A); Added by Public Law 104-121,
> **Sec.** 251; (110 Stat. 868); to the Committee on Education and the
> Workforce.*
>
> **`abstract`** (`house-communication/114/EC/4329`): identical, with `--`
> folded to ` - ` and `Sec.` expanded to `section`.

The first comparison, run byte for byte, said *not equal*, which is what a
measurement that encodes its own assumption looks like. Re-derived with those
two publisher normalizations relaxed and named, `abstract == printed entry` for
both ground-truth rows (`relaxed-comparison.json`). The typed fields are spans
of the same sentence:

| Contract column | Where it lives in the printed entry | EC 4329 | EC 4350 |
| --- | --- | --- | --- |
| `abstract` | the entry itself | equal | equal |
| `submitting_official` + `submitting_agency` | between `A letter from the ` and `, transmitting ` | concatenation equal | concatenation equal |
| `report_nature` | between `transmitting ` and `, pursuant to` | equal after capitalisation | equal after capitalisation |
| `legal_authority` | between `pursuant to ` and the referral tail | equal | equal |
| `referral_committee_name`, `referral_count`, `committees_json` | the `; to the Committee(s) on ...` tail | 1 committee | 3 committees, in printed order |
| `congressional_record_date`, `referral_date` | the granule's own issue date | `2016-02-12` | `2016-02-12` |
| `rin`, `rin_rule`, `rin_matched_text` | `(RIN: nnnn-XXnn)` inside the subject | `1218-AC97` | none stated |
| `matching_requirement_number` | **not in the Record at all** | 8070 | 3182 |

`interpretation/communication_rin.py`'s existing rule, unchanged, fires on a
`report_nature` reconstructed this way: 88 of the 216 entries (40.7%).

### How far one candidate parse rule gets

Written from the two ground-truth rows, then run over all 216 entries -- six of
the seven issues are text the rule was not fitted to:

| Span | Found | Share |
| --- | ---: | ---: |
| `A letter from the ` opening | 216/216 | 100% |
| `, transmitting ` split | 216/216 | 100% |
| committee referral tail | 216/216 | 100% |
| `pursuant to ` authority | 210/216 | 97.2% |
| RIN (repo's own rule) | 88/216 | 40.7% |

The six entries with no authority state none; that is a real absence, correctly
NULL. Four entries are joint referrals.

## 3. Four measured failure modes, and what each costs

1. **GPO's inline page marker.** `[[Page H6284]]` appears mid-sentence in the
   Record HTML and silently swallowed the referral tail of 2 of 216 entries.
   Stripping it took referral recovery from 214/216 to 216/216. The repository
   already owns this problem for PDF text in
   [GPO text normalization](../extraction-gpo.md); the HTML path needs the same
   treatment, gated on the marker's own evidence.
2. **A day can print the section twice.** `CREC-2004-06-16` carries **two**
   `granuleClass: HOUSE` granules titled `EXECUTIVE COMMUNICATIONS, ETC.` --
   `pt1-PgH4278` and `pt2-PgH4285`. A backfill that takes the first granule
   per issue silently drops the second. Take every match.
3. **Committee names cannot be tokenized.** Splitting the referral tail on
   `and`/`,` shattered *Education and the Workforce* into two and *Ways and
   Means* into two. Committee names must be resolved against the Congress.gov
   committee roster (`committees.system_code`, which the repository already
   hosts), never parsed out of the sentence.
4. **The official/agency split point is not derivable from punctuation.** The
   concatenation matched the publisher exactly on both ground truths, but the
   boundary sits after two comma-groups in EC 4329 and after one in EC 4350.
   This is the one field pair a punctuation rule cannot produce.

## 4. The ranked routes

### 1. GovInfo CREC `EXECUTIVE COMMUNICATIONS, ETC.` granules — **the production route**

*States*: EC number, transmitting official, agency, subject including rule title
and RIN, statutory authority, committee referral(s), and by the granule's own
`dateIssued` the Record date. Everything the `house_communications` contract
fills except `matching_requirement_number`, `is_rulemaking` and `update_date`.

*Coverage floor*: every House sitting day from 1994 forward, so the whole
104th-113th gap. My own earliest verified issue is 1996-06-12; a delegated
search reports the earliest EC granule as `CREC-1994-01-25-pt1-PgH74`, which
this note has not re-derived.

*Measured*: 7 of 7 issues resolved, 216 entries, the shares in §2, two
ground-truth rows agreeing with the publisher's own decomposition
(`govinfo-crec/probe-crec-log.json`, `parse-rule-measurement-v2.json`,
`relaxed-comparison.json`).

*Failure mode*: the four in §3, plus the cost -- there is **no bulk rendition**.
[GovInfo bulk data](https://www.govinfo.gov/bulkdata/json) publishes 15
collections and CREC is not among them, so the backfill is per-granule: one
keyed granules page plus `acquire_granule`'s three requests per issue.

*What makes it production*: a committee-name resolver, a policy for the
official/agency split, taking every matching granule per issue, the page-marker
strip, and the completeness witness in §6.

### 2. Congressional Record Index (`CRI-{year}-EXECUTIVE-COMMUNICATIONS`) — **the locator and the recall audit**

*States*: agency heading, subject phrase, chamber, Record page, EC number and
the Index's own day-month date. Keyless HTML at
`https://www.govinfo.gov/content/pkg/CRI-{year}/html/CRI-{year}-EXECUTIVE-COMMUNICATIONS.htm`.

*Measured, by this note's own fetch* (`cri/probe-cri-log.json`,
`cri-recall.json`): CRI-1996 is 879,478 bytes and names 3,574 distinct House EC
numbers; CRI-2012 is 445,743 bytes and names 4,579. Against the printed block
for the same day: **53 of 54 (98.1%)** in 1996 and **41 of 41 (100%)** in 2012,
and in both years **zero** index numbers fall inside the day's block that the
Record did not print.

*Failure mode*: it is a subject index, not a register, and it carries
typographical errors of its own -- CRI-2012 prints `H5008 (EC69723, EC69724)`
among neighbours numbered near 6,900. It also multiplexes several ECs behind
one locator, which a naive `(ECnnnn) [date]` pattern under-counts.

*Role*: never a source of record. It converts the backfill from "read every
issue" into "read the issues the index names", and it audits the parser's
recall from outside. *What makes it production*: recall measured on twenty or
more days across the era rather than two, and a pinned multi-number locator
grammar.

### 3. `house-requirement/8070/matching-communications` — **a membership witness**

*States*: five fields, and a `url` that 404s for every pre-114th row. 65,725
pre-114th rows, all of them Congressional Review Act rule submissions.

*Role*: an independent second derivation of `is_rulemaking` and
`matching_requirement_number = 8070`, against the Record's own
`pursuant to 5 U.S.C. 801(a)(1)(A)` clause. *Failure mode*: it is a 2021
snapshot (`updateDate` 2021-08-13) and it names only the CRA subset.

### 4. Senate communications, 96th Congress forward — **a cross-chamber check, and a reopened decision**

`senate-communication/{congress}` reaches the 96th Congress (4,424-12,758 rows
per Congress in the [data map](legislative-data-map-2026-09-18.md)), and its
detail carries the abstract, the referral and the Record date, with the RIN
inside the abstract. Because the CRA requires submission to both chambers, a
House CRA EC has a Senate twin joinable on `(rin, received date)`.

Separately: the same CREC issue carries a `granuleClass: SENATE` granule
`EXECUTIVE AND OTHER COMMUNICATIONS` (seen in `CREC-2004-06-16-granules.json`).
[`schemas/congress_index_tables.py`](../../src/spicy_docs/schemas/congress_index_tables.py)
omits `senate_communications` because the Senate *detail record* carries none
of the bridge's fields. If the Senate Record section shares the House section's
sentence grammar, that premise no longer holds -- the fields would come from
the Record, not the detail. **Unmeasured**; one granule would test it.

### 5. GAO Congressional Review Act database — **RIN enrichment, major rules only**

`gao.gov` refuses automated requests (403). A maintained MIT-licensed mirror,
[`regulatorystudies/Reg-Stats`](https://github.com/regulatorystudies/Reg-Stats),
commits `data/major_rules/raw_data/rule_detail_major.json`: 2,346 records,
received dates 1996-04-11 to 2025-04-29, 2,162 with a RIN. **Major rules only**,
so it cannot carry the bulk of 92,450 CRA ECs. Delegated finding, not
re-derived here.

### 6. House Calendar (`CCAL`) — **a per-session reconciliation total**

Carries an aggregate only (*"Executive departments transmitted 2,907
communications"*), no numeric list. Useful as a per-session total to reconcile
a completed backfill against. Delegated finding, not re-derived here.

### Rejected, with the reason

- **An existing dataset.** A GitHub code and repository search across
  [`unitedstates/congress`](https://github.com/unitedstates/congress),
  [`unitedstates/congressional-record`](https://github.com/unitedstates/congressional-record),
  GovTrack, Sunlight, ProPublica and the LOC org found **no** parser of
  executive communications from the Record. `unitedstates/congress` has no CREC
  task at all; `congressional-record` and `judgelord/congressionalrecord` parse
  speeches by speaker and would hand back the EC granule as one untagged blob.
  [`Democracy-Lab/uscongress-data`](https://github.com/Democracy-Lab/uscongress-data)
  is a reusable CREC downloader whose parser also emits speeches only.
  `joshuafayallen/executivecommunications-py` is a presidential-speech dataset
  and a name collision. Delegated finding.
- **The House Clerk.** No published EC index found; `clerk.house.gov/legislative/`
  answers 403 and `.../Legislative/ExecutiveCommunications` 404. Delegated.
- **The Daily Digest.** Present as a `granuleClass: DAILYDIGEST` granule in
  every issue sampled, but it summarises floor action and states no EC numbers.
  Not separately probed.
- **ProQuest Congressional, HeinOnline, Legistorm.** Gated re-hosts of the same
  Record text with no added structure.

## 5. Recommended plan

**Land the backfilled rows in the existing `house_communications` contract, not
a sibling.** The grain is identical -- one row per House executive
communication -- the identity `(congress, communication_type, number)` is the
publisher's own on both sides of 2015, and the reconstruction fills the same
columns from the same sentence the publisher itself decomposed. A sibling table
would split one fact across two contracts and force every consumer to union
them.

Add provenance rather than a second table:

| New column | Why |
| --- | --- |
| `source_route` | `congress-gov-detail` or `congressional-record-granule`; a consumer must be able to filter to publisher-decomposed rows alone |
| `record_package_id`, `record_granule_id` | the CREC granule that printed the entry -- the locator that makes the row replayable, the way `package_id` works for `committee_reports` |
| `record_entry_text` | the exact printed sentence, kept beside the derived fields the way `rin_matched_text` is, so a bad parse is readable from the row |
| `reconstruction_rule_version` | the parse rule that produced the row |

Three contract rules this needs, each of which is a bug if missed:

1. **`url` stays NULL on a backfilled row.** The publisher's detail URL 404s for
   every pre-114th communication (measured, §1). Writing it would assert a
   route that refuses.
2. **The merge must prefer provenance over `update_date`.** `update_date` is the
   contract's version column and the merge prefers the larger value; a
   reconstructed row has none. A `congress-gov-detail` row must win over a
   `congressional-record-granule` row for the same identity regardless of
   `update_date`, so that a later publisher backfill of the detail era
   overwrites the reconstruction and never the reverse.
3. **`submitting_official` / `submitting_agency` land NULL when the split is
   unresolved**, with the whole from-clause retained in `record_entry_text`. A
   guessed split is an invented fact; a NULL beside the printed sentence is not.

Join keys, all of which already exist:

- `house_communications.communication_id` = `(congress, communication_type, number)` — one key across both eras.
- `record_package_id` = `CREC-{congressional_record_date}` → `record_issues` via `(volume, issue)`.
- `matching_requirement_number` → `house-requirement/{n}`; 8070 for every row whose authority cites 5 U.S.C. 801(a)(1)(A).
- `rin` → `federal_register.regulation_id_numbers_json`, the bridge A5 already built.
- `referral_system_code` → `committees.system_code`.
- `(rin, received date)` → Senate communications, for the CRA subset.

**Order of work.** Parse rule and its fixture first, measured against the
overlap era; then the acquisition run; then the contract change. The overlap era
is the asset that makes this safe: **26,725 communications** exist both as
printed Record entries and as publisher-decomposed detail records, so the parser
can be scored field by field against the publisher on tens of thousands of rows
before a single reconstructed row is written. A rule validated only against
itself would be a formatting assertion; this one can fail.

**What it is worth.** Requirement 8070's detail-era share goes from 28.9% to
effectively complete, and A6's rejection reverses on its own stated terms. The
scale: the detail era holds 41,709 rows across six Congresses (6,952 per
Congress). The sampled pre-114th issues put lower bounds on their own Congresses
already at or above that -- 108th ≥ 8,569, 106th ≥ 8,152, 110th ≥ 7,099, all by
mid-Congress -- so ten pre-114th Congresses is on the order of 70,000-95,000
communications. `house_communications` roughly triples.

**What it costs.** A delegated search puts the House EC granules at about 2,800
for 1994-2014, with its own caveat that the count came from a full-text search
and needs re-deriving by granule enumeration. At four requests per issue that is
roughly 11,000 GovInfo requests: a detached run under
[`AGENTS.md`](../../AGENTS.md)'s fetcher rules, resuming from its own output,
retrying every unsuccessful row.

## 6. The completeness witness

Each day's section prints a **contiguous, strictly increasing** block of EC
numbers -- 7 of 7 issues. EC numbering runs continuously through a Congress. So
concatenating every House sitting day's block for one Congress must yield
`1..N` with no holes, and a hole names the exact issue that was missed or
misparsed. That check needs no external authority, runs over the acquired rows
alone, and can fail. It should gate the run, with the Congressional Record
Index (§4.2) as the independent second opinion and the House Calendar's
per-session total as the third.

## 7. What could not be established

- **Whether `CREC-2004-06-16-pt2-PgH4285` continues pt1's block or reprints it.**
  Not requested; it sat outside probe 2's declared 30-request cap, and the cap
  was not moved after the fact. Three requests settle it, and the answer
  decides whether §3.2 is a duplicate-suppression problem or a missing-rows
  problem.
- **Contiguity across a whole Congress.** One issue per Congress was read, so
  §6's witness is measured *within* a day and only argued across one.
- **Whether every House sitting day has the section.** Seven Wednesdays and one
  Friday were chosen because the House reliably sits on them. A day with no
  executive communications, or a section under a variant heading, would be
  invisible to this sample.
- **The 1994 floor.** Reported by a delegated search
  (`CREC-1994-01-25-pt1-PgH74`); my own earliest verified issue is 1996-06-12.
- **The 106th cross-check is inconclusive by construction, not by result.** The
  retained 250-row page of the 8070 list samples about 3.1% of that Congress's
  7,978 rows, so zero overlap with a 30-number window has probability ≈ 0.40
  under a uniform sample. It carries no signal either way and is recorded as
  such rather than as agreement.
- **Only two ground-truth rows.** EC 4329 and EC 4350 were compared field by
  field. The overlap era offers 26,725, and the parse rule's real score is
  unknown until it is run against them.
- **Whether the Senate Record section shares the House grammar**, which is what
  would reopen the `senate_communications` omission.
- **GAO's own CRA database** -- coverage, fields, any export. `gao.gov` returns
  403 to automated requests; every statement about it here is inferred from a
  third-party mirror's committed data, not from GAO.
- **Academic and ICPSR datasets.** The delegated search was search-engine
  mediated and could not query Dataverse or ICPSR directly, so the negative is
  weaker than the GitHub one.

## Sources

- [Congress.gov API: House Communication endpoint](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HouseCommunicationEndpoint.md)
- [GovInfo CREC collection](https://www.govinfo.gov/app/collection/crec) and the [GovInfo API](https://api.govinfo.gov/docs/)
- [GovInfo bulk data index](https://www.govinfo.gov/bulkdata/json) — 15 collections, CREC not among them
- [Congressional Record Index, 1996 executive communications](https://www.govinfo.gov/content/pkg/CRI-1996/html/CRI-1996-EXECUTIVE-COMMUNICATIONS.htm)
- [`regulatorystudies/Reg-Stats`](https://github.com/regulatorystudies/Reg-Stats) — GAO CRA mirror, major rules
- [`Democracy-Lab/uscongress-data`](https://github.com/Democracy-Lab/uscongress-data) — reusable CREC downloader
- [`unitedstates/congressional-record`](https://github.com/unitedstates/congressional-record) — speech parser, no EC handling
- [Federal Register API](https://www.federalregister.gov/developers/api/v1) — keyless RIN join
- In this repository: [gap register A5/A6](closing-the-gaps-2026-09-19.md),
  [legislative data map](legislative-data-map-2026-09-18.md),
  [table contracts](../tables.md),
  [`schemas/congress_index_tables.py`](../../src/spicy_docs/schemas/congress_index_tables.py),
  [`sources/congress/listing.py`](../../src/spicy_docs/sources/congress/listing.py),
  [`sources/govinfo/bodies.py`](../../src/spicy_docs/sources/govinfo/bodies.py),
  [`interpretation/communication_rin.py`](../../src/spicy_docs/interpretation/communication_rin.py)
