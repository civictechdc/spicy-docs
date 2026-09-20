# The publisher states the hearing on the meeting, never on the bill

Status: measured 2026-09-20. **140 requests**, five probes, each with its cap
declared before it ran and counted against its own log.
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/committee-action-sources-2026-09-20/`.

This extends [the bill-action relationship](bill-action-relationship-2026-09-20.md),
whose corrected finding — BILLSTATUS has **no counterpart to 10 of the 15**
subcommittee hearings the House committee activity prints state, while **8 of 8**
markups are stated and coded — was measured on one surface, the bill's own
action list. This asks what *other* source would supply the missing
relationship, and what would make the action-code vocabulary complete.

## The verdict, in one paragraph

The missing thing is not missing from the publisher. It is missing from the
**bill's** record and present on the **meeting's** record — but only when the
committee files the meeting as a *markup* or a *meeting*, never when it files
it as a *hearing*. The recommended route is therefore Congress.gov's
`committee-meeting` detail record joined to the House Committee Repository's
per-event XML, which between them state the date, the committee, the
**subcommittee**, the event type and the bills, structurally and per meeting.
It closes the markup side completely and the legislative-hearing side only
where the committee chose the `Meeting` filing. For an event filed as a
`Hearing`, **no structured field on any of the five surfaces measured names a
bill**, and the committee activity print keeps its place as the only record —
which is the narrower claim the branch's table already earns.

### The control that makes every zero above a finding

A zero is worth nothing unless the same check can produce a one. Congress.gov
event **`116376`** is an Energy and Commerce **Subcommittee on Health**
legislative meeting of **2023-09-14**. Its repository XML names five bills as
`BR` documents; its Congress.gov record lists four in `relatedItems/bills`.
Asked for two of those bills, BILLSTATUS answers with **no action on that date
and no hearing wording anywhere in the record** — only `Referred to` on the
Health Subcommittee block:

| Bill | BILLSTATUS actions | Actions naming a hearing | Actions dated 2023-09-14 | Subcommittee block |
| --- | ---: | ---: | ---: | --- |
| `118-hr-167` | 4 | 0 | 0 | Health Subcommittee: `Referred to` 2023-01-20 |
| `118-hr-3008` | 4 | 0 | 0 | Health Subcommittee: `Referred to` 2023-05-05 |

The publisher holds the relationship and does not put it on the bill. That is
the whole finding, and it is why the branch's 10-of-15 is a property of the
record rather than of the 20-bill draw.

## The ten events this is measured against

Re-derived from the prior receipt's retained bytes, **0 requests**, and
independently of the branch's attachment rule: the print writes
*"On `<date>`, the `<body>` held a hearing on `<designator>`."*, so the
designator inside that sentence is the event's own, and
`scripts/derive_events.py` reads the 254 such sentences in `CRPT-118hrpt965`
by that grammar rather than by nearest-mention. All ten of the branch's
print-only hearings reappear, with their subcommittee:

| Date | Bill | Committee | Subcommittee |
| --- | --- | --- | --- |
| 2023-06-13 | `118-hr-3631` | Energy and Commerce | Health |
| 2023-06-14 | `118-hr-2365` | Energy and Commerce | Health |
| 2023-06-21 | `118-hr-3892` | Energy and Commerce | Health |
| 2023-09-19 | `118-hr-3842` | Energy and Commerce | Health |
| 2023-09-27 | `118-hr-4814` | Energy and Commerce | Innovation, Data, and Commerce |
| 2023-09-27 | `118-hr-5556` | Energy and Commerce | Innovation, Data, and Commerce |
| 2023-10-19 | `118-hr-2377` | Energy and Commerce | Health |
| 2023-10-19 | `118-hr-4104` | Energy and Commerce | Health |
| 2024-09-10 | `118-hr-6770` | Energy and Commerce | Health |
| 2024-09-10 | `118-hr-7563` | Energy and Commerce | Health |

Seven distinct dates, one committee, two subcommittees. One committee is a
real limit and is named again under "what could not be established".

## The ranked routes

### 1. Congress.gov `committee-meeting` + the House Committee Repository — recommended

**What it states.** Congress.gov's meeting record
([`/committee-meeting/{congress}/{chamber}/{eventId}`](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeMeetingEndpoint.md))
carries `date`, `type` (`Hearing`, `Markup`, `Meeting`), `committees[].systemCode`
**including the subcommittee**, `title`, `meetingStatus`, `witnesses`,
`meetingDocuments[]` and `relatedItems.bills`. The House Committee Repository's
per-event XML at `docs.house.gov` carries the same event with
`meeting-document[@type='BR']/legis-num` — a bill designator per document —
plus `current-status`, `subcommittees/committee-name/@id` and, on a markup,
the disposition in `description`.

**What was measured.** 20 keyed Congress.gov requests and 29 keyless
`docs.house.gov` requests. 18 meeting records and 13 repository XML documents
retained (`notes/docs-house-result.json`):

| Congress.gov `type` | Records | With `relatedItems.bills` | Repository XML served | With `BR` documents |
| --- | ---: | ---: | ---: | ---: |
| `Hearing` | 13 | **0** | 10 | **0** |
| `Markup` | 2 | 2 | 2 | 2 (26 bills) |
| `Meeting` | 3 | 2 | 1 | 1 (5 bills) |

The sharpest single row is event `115945`, whose own `meeting-title` reads
*"Legislative hearing on: • H.R. 524 (Rep. Rouzer)… • H.R. 615 (Rep. Wittman)…"*
and whose repository XML contains **no `legis-num` element anywhere** — 17 `SD`
documents and one `HT`. The bills of a legislative hearing are in the title
string and nowhere else.

**Coverage floor.** Not established. Both endpoint documents defer to
[Coverage Dates for Congress.gov Collections](https://www.congress.gov/help/coverage-dates),
and congress.gov answers an automated client `403` with a Cloudflare challenge
carrying no error text — the exact shape `AGENTS.md` warns about. What is
demonstrated is 2,149 House committee meetings for the 118th Congress, which is
the count the list route itself declares.

**Failure mode.** Three, and each is a source rule this measurement had to
learn:

1. **The list route states no date.** Its item is
   `{chamber, congress, eventId, updateDate, url}` over 2,149 rows, so reaching
   one day costs one detail request per meeting. A 12-request bisection for
   2023-06-13 failed: `eventId` is **not** monotone in meeting date — it
   converged on two 2023-06-14 meetings (`116024`, `116025`) with the
   neighbouring ids `116020`–`116023` all dated 2023-05-24 and no integer
   between. The trail is in `congress-meetings/bisect-2023-06-13.json`.
2. **The repository locator is stated, not constructed.** The stem has three
   forms, not two — `HHRG`, `HMKP` and **`HMTG`** — and every constructed
   locator for a `Meeting` answered `404` until `HMTG` was read off that same
   record's `meetingDocuments[].url`. The subcommittee in the path is not
   always the one Congress.gov names (`115988` is `hsif00` on Congress.gov and
   `IF02` in its document URLs). Build the locator from the publisher's stated
   document URL, never from the type name.
3. **`docs.house.gov` offers no keyless discovery.** The day folder, the event
   folder and the day folder of a date *known* to hold an event all answer
   `403`; the stem without an `EventID` answers `404`; `ByDay.aspx` answers
   `302` (`notes/docs-house-discovery.json`). The `EventID` is mandatory and
   Congress.gov is its only source here.

**What would make it the production route.** One bounded backfill: walk the
nine `committee-meeting` list pages per chamber per Congress, then one detail
request per `eventId` — **2,149 requests for the 118th House**, at the
documented 5,000/hour, resumable from its own output the way `crs_summaries.py`
resumes. The repository XML is then keyless and one request per event, its
locator read from the retained record. Both fit the repo's existing
`BoundedHttpCapture` and `SourceAcquirer` patterns unchanged.

### 2. The Congressional Record Daily Digest — the complete *event* record, not a bill record

**What it states.** The Daily Digest's Committee Meetings section states, per
meeting, the committee, the **subcommittee**, the verb (*held a hearing* /
*held a markup*), the hearing's quoted title and the witnesses — and, for a
markup, the measures and their disposition.

**What was measured.** 19 requests of a declared 30: one keyed
`/packages/CREC-{date}/granules?granuleClass=DAILYDIGEST` listing per distinct
target date, then the keyless `html` body of each *Daily Digest/House Committee
Meetings* granule.

- **Every one of the ten events is stated.** All seven dates carry the Energy
  and Commerce subcommittee hearing the print names, by committee, subcommittee
  and title (`notes/digest-grammar.json`).
- **None of the ten bills is named.** 0 of 10 (`notes/daily-digest-result.json`).
- The grammar is why, and it splits exactly the way every other surface does.
  Over 127 House committee-meeting entries in the seven retained sections:

  | Entry kind | Entries | Naming at least one bill |
  | --- | ---: | ---: |
  | *held a hearing* | 99 | **11 (11%)** |
  | *held a markup* | 16 | **14 (88%)** |
  | business meeting | 4 | 0 |
  | other | 8 | 5 |

- The other place a bill could be stated is the previous issue's
  *"COMMITTEE MEETINGS FOR `<date>`"* announcement. Three target dates were
  tested through their prior issue: **0 of 5** target bills named, and the
  Energy and Commerce lines give the hearing title and room, never a measure
  (`notes/digest-announcement-result.json`). One answer would not have
  established a route, which is why three were taken.

**Coverage floor.** The best of any route, and publisher-stated:
*"GovInfo currently contains Congressional Record volumes from 140 (1994) to
the present"* ([govinfo.gov/help/crec](https://www.govinfo.gov/help/crec)),
which also documents the `D` page prefix that makes the Digest granules
addressable. That is roughly seventeen Congresses before BILLSTATUS bulk
begins, and it covers **both chambers**, where `docs.house.gov` is House-only.

**Failure mode.** It is prose, and it is committee-scoped rather than
bill-scoped: the `<bill>` elements in the granule MODS are granule-scoped, so a
three-page section covering a dozen meetings emits a handful of bills with no
pairing. Split days duplicate the section (`CREC-2023-09-27` publishes `pt1`
and `pt2`, and only `pt2` carries the House section), so the granule must be
selected by title and not by an inferred page number.

**What would make it the production route.** For **markups and Senate
meetings**, very little: the entry grammar is regular
(`Committee on X: Subcommittee on Y held a markup on H.R. N…`), the repo
already acquires CREC granules through `acquire_granule`, and the existing
`bill_number` citation rule reads the designators. For **hearings** it cannot
become the bill-link route at all, because the Digest does not state the link —
this is the measurement that settles it, and it settles it against the route.

### 3. BILLSTATUS `<committees>/<subcommittees>/<activities>` — a second surface, same answer

The retained user guide documents a second place on the same record where a
hearing could be stated: `<committees><billCommittees><item><subcommittees>
<item><activities><item><name>` with a `<date>`, whose vocabulary includes
`Hearings by` alongside `Referred to`, `Markup by` and `Reported by`. The
branch's probe read `<actions>` only.

12 keyless bulk requests. Of the ten print-only hearings, **0 of 10** carry a
subcommittee `Hearings by` activity, and **0 of 10** carry one on the printed
date. The block is not empty — it states `Referred to` for the subcommittee on
every one of the ten, and `Markup by` / `Reported by` where a markup happened —
so this is an absence the publisher's own populated field declines to state,
not an unpopulated element (`notes/billstatus-committees-result.json`).

This route earns its rank by **confirming the branch's claim on independent
bytes**: two different surfaces of the same record, fetched through two
different transports, agree.

### 4. The Senate — no retrospective equivalent

`https://www.senate.gov/general/committee_schedules/hearings.xml` is keyless
and does carry structured bills, as `Documents/AssociatedDocument` with
`document_prefix` and `document_num` — richer than the `<matter>` free text the
`unitedstates/congress` task regexes. But the page it drives states that it
shows meetings *"scheduled to take place today, and on days thereafter"*: it is
a forward-looking file with no archive, so it must be polled and accumulated
from now on and cannot be backfilled. **Not probed here** — no request was
spent on it, because a route with no archive cannot answer a 2023 question and
saying so costs nothing. For the Senate retrospectively, route 2 is the only
one, and route 1's `committee-meeting` covers the Senate with every meeting
typed `Meeting`.

### Rejected, with what would reverse each

- **GovInfo `CHRG` (printed hearing transcripts).** Its MODS states `<bill>`
  and, on recent packages, an `<eventId>` that joins to routes 1 and 2. It is
  rejected as the *primary* route because a printed transcript is published
  long after the hearing and not for every hearing, so it can only ever floor
  coverage. **Reversed by** a measurement showing what share of 118th-Congress
  House committee meetings have a CHRG package within N months, and whether
  `<eventId>` is present before 2023 — it is absent on a 2011 package.
- **GovInfo bulk data.** There is no hearings or meetings collection: the
  keyless listing at `govinfo.gov/bulkdata/json/` names CFR, FR, BILLSTATUS,
  CBD, PPP, SCD, BILLS, GOVMAN, BILLSUM, PAI, ECFR, HMAN, PLAW, STATUTE and
  COMPS. **Reversed by** GPO adding one.
- **`unitedstates/congress`'s `committee_meetings` task.** It reads exactly the
  routes ranked 1 and 4 above and extracts `bill_ids` from
  `meeting-document[@type='BR']/legis-num`, which is the same field this
  measurement landed on independently — a useful confirmation that the field is
  the right one. It is rejected as a *dependency* because it keeps only 60 days
  of the rolling per-committee RSS and backfills by enumerating an `EventID`
  integer range, which is the same unbounded walk route 1's list route avoids.
  Its `activity_text_map` (`"Hearings by": ["hearings"]`) is worth porting as
  the vocabulary for route 3.
- **GovTrack and ProPublica.** Neither publishes an action-code mapping;
  GovTrack consumes `unitedstates/congress`'s already-parsed types and its
  developer API is gone, and ProPublica's Congress API is retired and its docs
  publish no action enumeration.

## The action-code vocabulary

### The union

Three published lists exist. **They are not one vocabulary**, and treating them
as one is the same defect as the branch's two retractions, one level up.

| List | Codes | How it was read here |
| --- | ---: | --- |
| [BILLSTATUS user guide §3](https://github.com/usgpo/bill-status/blob/main/BILLSTATUS-XML_User_User-Guide.md) | 36 | the committed fixture `tests/fixtures/billstatus_codes/guide-2026-08-03.md`, section 3 only |
| [congress.gov field values for action codes](https://www.congress.gov/help/field-values/action-codes) | 75 | re-derived with `curl` from a retained Wayback snapshot; the live page answers `403` |
| [congress.gov action search scope notes](https://www.congress.gov/help/action-search-scope-notes) | 12 | **transcribed, not re-derived** — see below |
| **Published union** | **109** | |

Against them, **42 distinct codes** observed on the wire over 90 bill records:
the prior receipt's 20 Congress.gov `/actions` responses (35 codes), this
receipt's **60 BILLSTATUS bulk files of the 118th** (32 codes) and the 10
target files (21 codes).

**15 of the 42 appear in no published list at all** (`notes/action-code-union.json`):

| Code | Published in | Wire text, as the publisher files it | Seen |
| --- | --- | --- | ---: |
| `1000` | guide §3, field values | Introduced in House | 62 |
| `10000` | guide §3, field values | Introduced in Senate | 28 |
| `14000` | guide §3, field values | Committee on Homeland Security and Governmental Affairs. Reported by Senator Pet… | 8 |
| `14500` | guide §3, field values | Senate Committee on Health, Education, Labor, and Pensions discharged by Unanimo… | 13 |
| `17000` | guide §3, field values | Passed/agreed to in Senate: … | 27 |
| **`20500`** | **none** | Resolving differences -- Senate actions: Senate agreed to the House amendment | 1 |
| `28000` | guide §3, field values | Presented to President. | 19 |
| `31000` | field values | Vetoed by President. | 1 |
| `35000` | field values | Failed of passage in Senate over veto: … | 1 |
| `36000` | guide §3, field values | Signed by President. | 36 |
| `5000` | guide §3, field values | Reported (Amended) by the Committee on … | 16 |
| `8000` | guide §3, field values | Passed/agreed to in House: … | 22 |
| `B00100` | guide §3 | Sponsor introductory remarks on measure. | 2 |
| `E20000` | guide §3 | Presented to President. | 19 |
| `E30000` | guide §3 | Signed by President. | 19 |
| `E40000` | guide §3 | Became Public Law No: 118-66. | 18 |
| **`H11000`** | **none** | **Referred to the Subcommittee on Health.** | 16 |
| `H11100` | guide §3 | Referred to the House Committee on … | 81 |
| `H12200` | guide §3 | Reported (Amended) by the Committee on … | 16 |
| `H12410` | guide §3 | Placed on the Union Calendar, Calendar No. 2… | 15 |
| `H14000` | guide §3 | Received in the House. | 7 |
| `H15000` | guide §3 | Held at the desk. | 7 |
| **`H15000-B`** | **none** | **Committee Consideration and Mark-up Session Held** | 9 |
| **`H15001`** | **none** | **Committee Consideration and Mark-up Session Held** | 3 |
| **`H19000`** | **none** | **Ordered to be Reported in the Nature of a Substitute (Amended)** | 9 |
| `H1L210` | guide §3 | Rules Committee Resolution H. Res. 906 Reported to House | 5 |
| `H1L220` | guide §3 | Rule H. Res. 906 passed House. | 1 |
| **`H21000`** | **none** | **Subcommittee Hearings Held** | 2 |
| **`H22000`** | **none** | **Subcommittee Consideration and Mark-up Session Held** | 4 |
| **`H23000`** | **none** | **Forwarded by Subcommittee to Full Committee by Voice Vote.** | 4 |
| **`H25000`** | **none** | **Subcommittee on Energy and Mineral Resources Discharged** | 1 |
| `H30000` | guide §3 | Considered as unfinished business. | 31 |
| **`H30300`** | **none** | **Mr. Bilirakis moved to suspend the rules and pass the bill** | 20 |
| `H35000` | guide §3 | The previous question was ordered pursuant to the rule. | 2 |
| **`H37100`** | **none** | **On passage Passed by the Yeas and Nays: 210 - 189** | 2 |
| **`H37210`** | **none** | **At the conclusion of debate, the chair put the question** | 1 |
| **`H37220`** | **none** | **At the conclusion of debate, the Yeas and Nays were demanded** | 6 |
| `H37300` | guide §3 | On motion to suspend the rules and pass the bill, as amended | 20 |
| `H38310` | guide §3 | Motion to reconsider laid on the table. | 22 |
| **`H38800`** | **none** | **The title of the measure was amended.** | 4 |
| `H8D000` | guide §3 | DEBATE … | 27 |
| **`Intro-H`** | **none** | **Introduced in House** | 62 |

Two additions to the branch's 13: **`H37210`** and **`20500`**, both found by
widening the sample. `20500` is the more instructive of the two — it is
numeric, and the published list has `20000` *Resolving differences — Senate
actions* but not `20500`, so the numeric namespace is incomplete too and the
gap is not a property of the `H` prefix.

### Two things the union shows that neither list alone does

**The lists collide.** Ten of the 42 observed `H`-prefixed codes have a bare-number twin
in the published list that means something entirely different. Stripping the
prefix to "resolve" one would publish confident nonsense:

| Wire code and its text | Published code and its text |
| --- | --- |
| `H21000` Subcommittee Hearings Held | `21000` Conference report agreed to in House |
| `H22000` Subcommittee Consideration and Mark-up Session Held | `22000` Conference report disagreed to in House |
| `H23000` Forwarded by Subcommittee to Full Committee | `23000` Conference report agreed to in Senate |
| `H19000` Ordered to be Reported in the Nature of a Substitute | `19000` Resolving differences — House actions |
| `H11000` Referred to the Subcommittee | `11000` Referred to Senate committee |
| `H25000` Subcommittee … Discharged | `25000` Roll call votes on measures in House |

(Four more: `H14000`/`14000`, `H15000`/`15000`, `H30000`/`30000`,
`H35000`/`35000`. Two further guide-§3 codes, `H17000` and `H81000`, collide the
same way but were not observed in either wire sample.)

**The published numeric list is a *search* vocabulary, not the wire's.** 82 of
the 109 published codes were never observed in either wire sample — and among
them are `4100` *House committee/subcommittee hearings*, `4200` *House
committee/subcommittee markups* and `3000` *Referred to House subcommittee*.
congress.gov's own page spells these as query expressions
(`actionCode:"4200"`), and they index the House committee activity that
BILLSTATUS's `<actionCode>` element never emits. So the House hearing and
markup codes the first retraction went looking for **do exist and are
published** — in the search index, on a different surface, in a namespace the
bulk feed does not use. That is the third form of the same mistake this
document's ancestors made twice, and naming it is what stops a fourth.

### What the publisher says about its own vocabulary

Beyond section 3's *"a complete, authoritative list of action codes does not
exist"*, GPO answered this question directly in
[usgpo/bill-status issue #6](https://github.com/usgpo/bill-status/issues/6):
*"My suggestion is to focus on Action Codes, which are a controlled
vocabulary… Actions that do not have Action Codes should not be expected to be
consistently used nor sufficiently unique."* The `H*` namespace is `sourceSystem`
2 (House floor) primary-source data that the publisher declines to treat as a
controlled vocabulary. Section 3 itself grows by community pull request
(issues #130–#132 add `H1L220` and `H35000`), so it is an accretion of reported
codes, not a register.

**`204 of the 628` actions in the 60-file sample carry no `actionCode` at
all** — 32.5%, mostly `sourceSystem` 0 (Senate) and 1 (House committee
actions). A vocabulary cannot be completed past that: for a third of actions
the publisher files no code to complete.

## The recommended plan

**1. `bill_committee_actions` gains a `source` column and keeps its grain.**
The table stays as the branch shaped it — one row per action phrase a stating
document makes about one bill — and `source` records *which publisher said so*:
`house_activity_report` for today's rows, `congress_committee_meeting` and
`house_committee_repository` for route 1's, `congressional_record_digest` for
route 2's. A sibling table would force a consumer to union two schemas for one
question; one table with a `source` predicate lets a consumer take the coded
rows alone, or take the print rows only where no publisher row exists for the
same `(bill_id, stated_date, print_phrasing)`. `attachment_confidence` already
carries the reliability axis, and rows from route 1 would be `single` by
construction because the publisher states the pairing rather than a sentence
implying it. The measured precisions are not comparable and must not be merged
into one figure: the print's is 83.3% and a `BR` document's pairing is the
publisher's own statement.

**2. A `committee_meetings` contract is the acquisition this needs.** One row
per event, keyed `(chamber, congress, event_id)`, with `date`, `type`,
`committee_system_code`, `subcommittee_system_code`, `title`, `meeting_status`
and the stated repository locator; and one row per meeting document in a child
grain, with `document_type`, `legis_num` and the publisher's `url`. The
bill-to-event edge then falls out of the `BR` rows and needs no interpretation
at all. This is an acquisition contract, not an interpretation one, and it sits
beside `house_activity_reports` in the registry.

**3. Seal `BILLSTATUS_ACTION_CODES` against a stated sample, not against a
list.** The branch's `GuideCode.source` already distinguishes `FROM_GUIDE` from
`FROM_THE_WIRE`. Three changes make it defensible:

- Add the two codes this widening found — `H37210` and `20500` — and record
  `H11000` *Referred to the Subcommittee* and `H23000` *Forwarded by
  Subcommittee to Full Committee*, which are the wire's spellings of the
  print's `favorably_forwarded`, today mapped to no code at all.
- Add a third `source`, `FROM_SEARCH_VOCABULARY`, for `4100`/`4200`/`3000`, and
  state in the module that they are congress.gov *search* codes that the bulk
  feed does not emit, with the 90-record observation as the evidence. Without
  that note the next reader finds `4100 House committee/subcommittee hearings`
  in a published list and repeats the first retraction.
- State the seal's strength as a sample: *42 distinct codes over 90 bill
  records of the 118th Congress (20 API responses, 60 stratified bulk files, 10
  targets), of which 15 appear in no published list, and 32.5% of actions carry
  no code.* A completeness claim without that sentence is the identity the
  branch already retracted twice.

**4. Do not widen `bill_stage` to the print's register.** Unchanged from the
branch's reasoning, and route 1 strengthens it: `Hearing`, `Markup` and
`Meeting` are the publisher's own event types, and a `committee_meetings`
contract carries them verbatim rather than mapping them onto a sealed ladder
built for a different publisher's prose.

## What could not be established

- **The ten events' own repository records.** `docs.house.gov` has no keyless
  discovery and Congress.gov's list route states no date, so reaching the
  Energy and Commerce Subcommittee on Health hearing of, say, 2023-06-13
  requires an `eventId` this probe's 20-request cap could not find — the
  bisection failed because `eventId` is not monotone in meeting date. **So it
  is not established whether those ten events are filed as `Hearing` (no bill
  link) or as `Meeting` (fully bill-linked).** Event `116376` shows the same
  subcommittee filing a legislative meeting *with* its five bills, so the
  optimistic case is real and unmeasured. What closes it: the 2,149-request
  detail walk of the 118th House in route 1's backfill, which answers it for
  every event at once rather than for ten.
- **Every coverage floor but the Record's.** CREC is publisher-stated at volume
  140 (1994). Congress.gov's committee-meeting and hearing floors are stated
  only by a page that answers `403` to every automated client, and
  `docs.house.gov`'s floor is unprobed — its pages are JS-rendered and its
  folders forbidden. Neither should be cited as a year until a browser-rendered
  read or an `eventId` walk establishes it.
- **The congress.gov scope-notes list was not re-derived.** The live page
  answers `403` and the Internet Archive answered `503 "Temporarily Offline"`
  at measurement time — a transport failure, which establishes nothing. Its 12
  codes are transcribed from a browser-engine read. The headline count is
  insensitive to it: **15 absent either way**, because none of the 42 wire
  codes is in that list. Nothing load-bearing rests on the un-re-derived input,
  and that is stated rather than hidden.
- **One committee, one Congress.** All ten events are Energy and Commerce,
  118th. The 18 meeting records span ten full committees and 13 distinct
  committee or subcommittee codes, which is what carries the type-level
  finding; the ten-event figure does not.
- **The Senate was reasoned about, not probed.** Zero requests were spent on
  `senate.gov`. The claim that its schedule file has no archive rests on the
  publisher's own "today, and on days thereafter" wording, not on a measurement
  here.
- **Whether a `Hearing`-typed event ever carries a `BR` document.** 0 of 10 in
  this sample, and the sample was drawn by a bisection trail rather than by
  design. A wider draw could find one; the claim is bounded at 10.

## Complexity

Every measurement is linear in what it reads. The union is one pass over 109
published rows and 90 XML/JSON documents. The proposed backfill is
`O(meetings)` requests — 2,149 for the 118th House — with the repository XML
one further keyless request per event; both are bounded per Congress per
chamber and neither is superlinear. The Digest route is `O(legislative days)`,
two requests a day, about 300 a year.

## Sources

- [BILLSTATUS XML User Guide](https://github.com/usgpo/bill-status/blob/main/BILLSTATUS-XML_User_User-Guide.md) — §3 action codes, §2.1 `<committees>`; retained as `tests/fixtures/billstatus_codes/guide-2026-08-03.md`
- [usgpo/bill-status issue #6](https://github.com/usgpo/bill-status/issues/6) — GPO on which codes are a controlled vocabulary
- [congress.gov field values for action codes](https://www.congress.gov/help/field-values/action-codes) — 75 numeric codes
- [congress.gov action search scope notes](https://www.congress.gov/help/action-search-scope-notes) — 12 further numeric codes
- [Congress.gov API committee-meeting endpoint](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeMeetingEndpoint.md) and [hearing endpoint](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/HearingEndpoint.md)
- [GovInfo Congressional Record collection](https://www.govinfo.gov/help/crec) — the 1994 floor and the `D` page prefix
- [GovInfo bulk data listing](https://www.govinfo.gov/bulkdata/json/) — the collections that exist
- [`unitedstates/congress` `committee_meetings.py`](https://github.com/unitedstates/congress/blob/main/congress/tasks/committee_meetings.py) — `meeting-document[@type='BR']/legis-num`, the rolling-RSS limit
- [`unitedstates/congress` `bill_info.py`](https://github.com/unitedstates/congress/blob/main/congress/tasks/bill_info.py) — the `activity_text_map` for `<committees>` activities
- [Senate committee schedule](https://www.senate.gov/general/committee_schedules/hearings.xml) and [the page it drives](https://www.senate.gov/committees/hearings_meetings.htm)
