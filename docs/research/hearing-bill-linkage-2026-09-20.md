# Which source states the bills a hearing was held on

Status: measured 2026-09-20. Read-only research, nothing published, no source
changed. 198 requests, all HTTP 200, every one retained.
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/hearing-bill-linkage-2026-09-20/`
(`README.md` there carries the per-probe caps, the request tally and the
credential check; `scripts/` holds the capture and the offline recomputes).

**This reopens gap [A2](closing-the-gaps-2026-09-19.md) without contradicting
it.** The [2026-09-19 receipt](closing-the-gaps-2026-09-19.md) left
`hearing_transcripts.bill_id` NULL because no hearing in 52 stated a `PRIMARY`
bill and no meeting in 12 stated one in `relatedItems.bills`. Both findings
still hold — re-measured here, no hearing states a `PRIMARY` bill, and a `BODY`
mention is confirmed by nothing. What was wrong was the conclusion drawn from
them: **that measurement asked the two sources a committee *report* answers,
and read their silence as the absence of any source.** A hearing does not have
a `PRIMARY` bill because a hearing is not filed against one bill; a legislative
hearing is held on a *list* of bills, and four independent publishers state that
list. The reason the column stays NULL changes from "no source states it" to
"the relationship is one-to-many and a scalar column is the wrong shape".

## What is now measured

Six set-comparisons between the MODS `COVER` rule and a statement made by a
*different* process are **6 of 6 set-equal, over 55 bills** — no bill either way
in any of them (`cover-agreement.json`):

| Transcript | Compared against | Bills | Equal |
| --- | --- | --- | --- |
| `CHRG-118hhrg52385` | Congress.gov hearing title | 8 | yes |
| `CHRG-118hhrg56198` | Congress.gov hearing title | 12 | yes |
| `CHRG-118hhrg57459` | Congress.gov hearing title | 9 | yes |
| `CHRG-118hhrg56198` | Daily Digest committee entry | 12 | yes |
| `CHRG-118hhrg54612` | Congress.gov `relatedItems.bills` | 2 | yes |
| `CHRG-118hhrg56198` | CHRG front matter, first page | 12 | yes |

And the bill's own action list, a fourth publisher, confirms **19 of 20**
`COVER` pairs as a *Hearings Held* action by that committee on that date, while
confirming **0 of 23** `BODY`-only mentions.

## The routes, ranked

Coverage floors below are stated as **measured** or **unmeasured**; every one
was measured on the 118th Congress only, so no floor claim reaches further than
that without the census named in §"What could not be established".

### 1. GovInfo CHRG MODS, `<bill context="COVER">` — free, House, highest precision

**What it states.** The bill list printed on the hearing's own cover — what the
hearing was convened on, as distinct from `BODY`, which is any bill the
transcript happens to mention. `PackageModsIdentity.bills` already carries the
context ([`bodies.py`](../../src/spicy_docs/sources/govinfo/bodies.py)), and
`GovInfoBodyAcquirer` already fetches this MODS for **every body it reads**, so
this route costs no request at all.

**Coverage.** 2 of 20 sampled House hearings of the 118th carry a `COVER` bill;
both are legislative hearings, and the other 18 are oversight hearings that were
not held on a bill. 0 of 3 sampled **Senate** hearings carry one — those three
MODS state no bill in any context, while Congress.gov states one to two for each
(`probe2b.json`). Senate reach: **none measured**. Pre-118th: unmeasured.

**Measured.** 6 of 6 set agreements above; 19 of 20 `COVER` pairs confirmed by
the bill's own *Hearings Held* action, the one exception being a bill with three
actions in total, so the bill side is silent rather than contradicting
(`probe3.json`, `probe1-recomputed.json`).

**Failure mode.** Silence on oversight hearings is correct, not a gap; silence
on the Senate is a gap and is currently indistinguishable from the first.
Nothing in the row says which.

**To make it the production route.** A `PackageModsIdentity.cover_bills`
accessor beside `primary_bill`, and one census: how many CHRG packages per
Congress and per chamber carry a `COVER` bill. If the Senate count stays zero
across a real sample, the contract must say so, because a NULL that means "this
publisher never states it for this chamber" is not the same NULL as "this
hearing had no bill".

### 2. The transcript's own title — free, both chambers, a backstop

**What it states.** `LEGISLATIVE HEARING ON H.R. 226, H.R. 7543, … AND H.R.
8607`, on the title page and as the Congress.gov hearing `title`.

**Coverage.** Whenever the hearing was titled after its bills. Unmeasured as a
rate.

**Measured.** The rule `bill_designator_in_text` over the first page returned
**12 of 12** on `CHRG-118hhrg56198`, equal to `COVER`; the Congress.gov title
gave the same set on 3 of 3 hearings that have a `COVER` list.

**Failure mode.** A hearing titled only `LEGISLATIVE HEARING`
(`CHRG-118hhrg57073`) states nothing, and `H.R. ____` discussion drafts have no
number to read. The rule cannot distinguish "held on" from "mentioned in the
title".

**To make it the production route.** It should not be one. It is the tie-break
that makes `COVER` checkable without a request, and the fallback where `COVER`
is empty but the title is explicit — earning a lower `link_rule` rank, never
the same one.

### 3. docs.house.gov Committee Repository, `<meeting-document type="BR">` — one keyless request, House, the agenda

**What it states.** The documents posted for a House committee meeting, typed:
`BR` is a bill on the agenda, with `<legis-num>` and a
`BILLS-{congress}{TYPE}{number}{stage}.pdf` file whose name restates it.
`<committee-name id>` gives the subcommittee, `<calendar-date>` the date.

**The key question, answered: `EventID` is Congress.gov's `eventId`.** 9 of 9
sampled `associatedMeeting.eventId` values resolved on docs.house.gov, and all
9 passed an identity check rather than a status check — the XML's
`<calendar-date>` equalled the CHRG MODS `heldDate` and `<committee-name id>`'s
parent code equalled the MODS `congCommittee` authority id under the rule
`docs_house_parent_code` (`VR10` → `hsvr00`). This is what
[A7](closing-the-gaps-2026-09-19.md)'s `committee_meetings.event_id` key opens.

**The rendition is a plain GET.** The page offers the XML only as an ASP.NET
`__doPostBack`, with no `.xml` href anywhere on it, so the first capture used
the postback. It is *also* a static file at
`/meetings/{CMTE}/{SUBCMTE}/{yyyymmdd}/{EventID}/{TYPE}-{congress}-{SUBCMTE}-{yyyymmdd}.xml`,
and the two are **byte-identical, 2 of 2 by SHA-256** — checked that way rather
than by status, because this publisher serves its own pages at 200.

**Coverage.** The limiter is not docs.house.gov: **only 9 of 20** sampled
hearings state an `eventId` at all on Congress.gov, and all 9 that do resolve.
4 of those 9 carry `BR` documents. Of 36 `BR` documents, **29 resolve to a bill
key** and 7 do not — the `BILLS-118Xih.pdf` discussion drafts.

**Measured.** Where `BR` and `COVER` agree, the bill side confirms **18 of 18**.
Where `BR` states a bill `COVER` does not, the bill side confirms 1 of 18,
contradicts 1 (`118-hr-2997`, noticed for 2023-05-23, heard 2023-06-22) and is
silent on 16.

**Failure mode.** It states *intent*, not what happened: a bill noticed and
dropped stays on the agenda. Some committees omit the bill type from both
`<legis-num>` and the file name (`BILLS-118226ih.pdf`), so the number alone is
ambiguous and the rule refuses it rather than guessing `hr`.

**To make it the production route.** Label the rows `noticed`, not `heard`, and
promote to `heard` only on a bill-side confirmation. Then measure the two
unknowns: how far back the Repository reaches, and whether the per-committee
feed `https://docs.house.gov/Committee/RSS.ashx?Code={code}` (200, RSS 2.0, 26
items for `VR00`, each item's `<guid>` the event id and its `<enclosure>` the
static XML) enumerates more than a rolling window. That feed is the recovery
path for the 11 of 20 hearings Congress.gov gives no `eventId` for.

### 4. The Congressional Record Daily Digest — keyless bodies, both chambers, the deepest floor

**What it states.** One sentence per committee per day: the committee, the
action verb, and the bills. `Committee on Veterans' Affairs: Subcommittee on
Economic Opportunity held a hearing on H.R. 226, the "Veterans Collaboration
Act"; …`. Two granules per issue, `Daily Digest/House Committee Meetings` and
`Daily Digest/Senate Committee Meetings`, reachable through
[`acquire_granule`](../../src/spicy_docs/sources/govinfo/bodies.py).

**Coverage.** Both chambers, CREC from volume 140 (1994) forward. The 1994 floor
is the publisher's own statement, checked by a second pass against
`CREC-1994-01-25`; this probe verified the structure on 2024-06-12 only.

**Measured.** 16 committee entries on that date, 7 with a bill. The entry for
the hearing already in this receipt names **exactly** the transcript's 12
`COVER` bills, set-equal. Every one of those 12 also appears among the granule
MODS's 47 `Congressional Bill citation` `relatedItem`s — but those are
granule-level and flat: on that date they mix four committees together, so the
structured field alone cannot attribute a bill to a committee. The text must be
parsed for that.

**Failure mode.** The Digest describes the *event*, not the transcript, so
reaching a CHRG package still needs a `(committee, date)` join — and that join
fans out (below). The committee entry is prose; the parse is a rule with an
unmeasured error rate over one date.

**To make it the production route.** It is the strongest long-term spine,
because it is the only route with both chambers and a 1994 floor. It needs the
measurement this probe did not do: the entry parse over a few hundred granules
spread across Congresses, scored against `COVER` where both exist. One
correction worth carrying: the first pass here cut each entry at 260 characters
and silently lost three bills off the longest one; `recompute4.py` re-reads the
same bytes splitting on the next committee line instead.

### 5. Congress.gov `committee-meeting` `relatedItems.bills` — one keyed request, the only Senate source measured

**What it states.** The bills the publisher relates to a scheduled meeting.
Already contracted as `committee_meetings.bill_ids_json`
([`congress_index_tables.py`](../../src/spicy_docs/schemas/congress_index_tables.py)).

**The prior 0 of 12 was a skewed frame, not a property of the field.** Those 12
were reached *through hearings*, so every one was a hearing with a published
transcript. Sampling the meeting list route directly, 60 meetings of the 118th
(40 House, 20 Senate; declared totals 2,149 and 1,135):

| Chamber | `type` | Meetings | With a bill | Bills |
| --- | --- | --- | --- | --- |
| house | Hearing | 35 | 2 | 6 |
| house | Markup | 3 | 2 | 30 |
| house | Meeting | 2 | 0 | 0 |
| senate | Meeting | 20 | 6 | 69 |

**10 of 60 meetings state a bill**, 108 bills in all. Restricted to the 42 with
a transcript jacket — the population A2 asks about — 5 state a bill: 2 of 29
House hearings and 3 of 13 Senate. Sparse, but not zero, and for the Senate it
is the **only** source measured here that states anything.

**Failure mode, found here.** The meeting-to-jacket edge is many-valued and at
least one value can be the wrong transcript. Meeting 117714 lists jackets 57459
and 57458; hearing 57459's own title is a nine-bill list matching its `COVER`,
and it names **no** associated meeting. Attributing the meeting's four bills to
that transcript would have been wrong. Separately, the Senate detail types every
meeting `Meeting`, so a Senate markup and a Senate hearing are not separable by
`type` — only by the title text.

**To make it the production route.** Never attribute a meeting's bills to a
transcript on the meeting's `hearingTranscript` alone. Require the reverse edge:
the hearing's own `associatedMeeting.eventId` must equal that meeting's
`eventId`. The `hearing-detail` route in
[`listing.py`](../../src/spicy_docs/sources/congress/listing.py) already supplies
it, and [A7](closing-the-gaps-2026-09-19.md) already fills
`hearing_transcripts.event_id` from it.

### 6. Bill actions, `(committee, date)` — a confirmer, not a discoverer

**What it states.** `Committee Hearings Held` / `Subcommittee Hearings Held`
with the committee system code and the date, on every bill's own action list.

**Measured.** As a confirmer it is excellent: 18 of 18 on pairs both `COVER` and
the House agenda state, 19 of 20 on `COVER`, 0 of 23 on `BODY`-only mentions.
As a discoverer it fails on arity: over the bills retained here,
`hsii10|2023-05-23` → **8** distinct bills and `hsvr10|2024-06-12` → **12**.
0 of 2 committee-days resolve to exactly one bill.

**Failure mode.** Congress.gov records the action inconsistently: 2 of the 4
sampled agenda events have no *Hearings Held* action on **any** of their bills,
so a missing action is not evidence the hearing did not happen.

**To make it the production route.** It should not be the route that *finds* the
bill. It should be the column that says whether an independently discovered pair
was confirmed — which is a request-free join in spicy-regs, whose family rollup
already holds every bill's actions ([A3](closing-the-gaps-2026-09-19.md)).

### 7. The Senate committee schedule XML — structured, prospective, no archive

`https://www.senate.gov/general/committee_schedules/hearings.xml` answered 200
`text/xml`, root `<css_meetings_scheduled>`. It states bills **structurally**,
not only as prose: `<Documents><AssociatedDocument congress="119"
document_num="226" document_prefix="HR" document_description="…"/>`, with
`document_prefix` `PN` for nominations, so nominations are separable without
parsing prose. The long-standing community scraper reads the free-text
`<matter>` field with a regex instead and ignores `Documents` entirely
([`committee_meetings.py`](https://github.com/unitedstates/congress/blob/master/congress/tasks/committee_meetings.py));
reading the attributes is strictly better.

The fetched file held 18 meetings spanning **20-SEP-2026 to 29-SEP-2026** — a
rolling window of about ten days, rewritten in place, with no archive. 4 of 18
carried documents, 25 documents in all. It cannot backfill anything. It is worth
polling **only if polling starts**, because nothing recovers its past.

### 8. MODS `BODY` mentions — never promote

0 of 23 confirmed by the bill side. They are what the transcript cites, not what
it was held on. The existing rule is correct and now has a number behind it.
Keep the count; do not make a link row.

## What everyone else does, and why none of it is a shortcut

Nobody publishes this linkage as data today, and the reasons are worth knowing
before building it.

* **[`unitedstates/congress`](https://github.com/unitedstates/congress/blob/master/congress/tasks/committee_meetings.py)**
  is the only maintained open scraper. It reads
  `meeting-document[@type='BR']/legis-num` for the House, keys its records on
  `house_event_id`, and writes `bill_ids` into
  `committee_meetings_house.json` / `committee_meetings_senate.json`. Two of its
  choices are measurably wrong for our purposes: it defaults a type-less
  `<legis-num>` to `hr`, which this receipt's rule refuses instead (a bare `226`
  at a House hearing can be a Senate measure); and for the Senate it regexes the
  free-text `<matter>` field while ignoring the structured `AssociatedDocument`
  attributes beside it.
* **GovTrack** has the column and does not fill it: its `CommitteeMeeting` model
  carries a `bills` many-to-many, but its scraper runs the same upstream task
  with documents disabled, and its own calendar page states it discontinued that
  product because Congress.gov's is better. Its live committee feed carries no
  bill links.
* **ProPublica's Congress API** is retired and its hearings route was documented
  for the 114th–117th only, so it never covered the 118th. There is no successor.

So the `unitedstates/congress` project is prior art for the *route* — it
confirms docs.house.gov and the Senate XML are where this is stated — but not
for the *data*, and not for the rules.

**One caveat on the `EventID` identity that no publisher removes.** It held 9 of
9 here under a committee-and-date check, and a second, independently chosen
event (118 House 115538) matched as well. But Congress.gov's own endpoint
documentation never mentions docs.house.gov, and its OpenAPI spec spells the
field `eventid` while the wire spells it `eventId`. The equality is a measured
regularity, not a stated contract; a linkage built on it should carry the
committee-and-date identity check as a row-level condition, not a one-time
assumption.

## Recommended plan

**Leave `hearing_transcripts.bill_id` NULL, and change the stated reason.** A
legislative hearing is held on a list — 12 bills on one hearing here — so a
scalar column forces an arbitrary pick. The contract line in
[`committee_report_tables.py`](../../src/spicy_docs/schemas/committee_report_tables.py)
should say the relationship is one-to-many and name the link table, the way
`event_id` names `committee_meetings`.

**Leave `committee_meetings.bill_ids_json` as it is.** It is the publisher's own
field, correctly shaped, and probe 2 shows it is populated for 10 of 60
meetings. What it needs is not a new column but the reverse-edge check before
anything joins it to a transcript.

**Add one link table in the `fr_docket_links` shape**, the shape
`document_citations` already uses
([`document_citation_tables.py`](../../src/spicy_docs/schemas/document_citation_tables.py)),
one row per `(hearing, bill, rule)` — not per `(hearing, bill)`, because two
sources naming the same pair is the strongest evidence in this measurement and
collapsing them would delete it:

| Column | Meaning |
| --- | --- |
| `package_id` | The CHRG package, this table's document key |
| `event_id` | The meeting event id where one is known, so the House agenda rows join `committee_meetings` |
| `bill_id` | The bill's natural key, `118-hr-226` |
| `link_rule` | `mods_cover`, `docs_house_br`, `daily_digest_entry`, `congress_related_items`, `front_matter_designator` |
| `link_source` | The publisher that stated it: `govinfo_mods`, `docs_house_gov`, `govinfo_crec`, `congress_gov` |
| `relation` | `held_on` for a cover or digest statement, `noticed` for an agenda-only one |
| `committee_system_code`, `held_date` | The join key the bill-side confirmation uses |
| `confirmed_by_bill_action` | True, false, or NULL where the bill's actions were not read — NULL is "not looked up", never "no" |
| `evidence_text` | The exact string the rule matched, so a false positive is readable from the row |
| `rule_version` | So a re-extraction under a corrected rule is attributable |

**The precision each source earns**, as the rank a consumer should apply:

| `link_rule` | Earned on | Measured |
| --- | --- | --- |
| `mods_cover` ∩ `docs_house_br` | Promote unconditionally | 18 of 18 confirmed by the bill side |
| `mods_cover` | Promote; `relation = held_on` | 19 of 20 confirmed; 6 of 6 set-equal to an independent source |
| `congress_related_items` | Promote **only** with the reverse jacket edge | 4 of 5 attributable; 1 of 5 pointed at the wrong transcript |
| `daily_digest_entry` | Pilot; needs the multi-Congress parse measurement | 12 of 12 on one entry, 7 of 16 entries carry a bill |
| `front_matter_designator` | Fallback where `mods_cover` is empty | 12 of 12 on one front page |
| `docs_house_br` alone | `relation = noticed`; promote on confirmation only | 1 of 18 confirmed, 1 contradicted, 16 silent |
| `mods_body` | Never a row | 0 of 23 confirmed |

**Build order.** `mods_cover` first, because it is free on bodies already
acquired and carries the highest measured precision; then the docs.house.gov
agenda, which needs one keyless request and unlocks markups, where the
transcript route has nothing at all; then the Daily Digest, which is the only
route that reaches both chambers back to 1994 and is the one that would close
the Senate gap the other routes cannot.

## What could not be established

* **Every coverage floor.** Every number here is the 118th Congress plus one
  119th event. No route's reach into earlier Congresses was measured, including
  the one claim most load-bearing for build order: how far back docs.house.gov's
  Committee Repository goes.
* **Whether `COVER` is absent for the Senate as a rule.** 3 of 3 Senate CHRG
  MODS stated no bill in any context. Three is not a rule, and the difference
  between "the Senate's MODS never carries `COVER`" and "these three hearings
  had no bill" decides whether the Senate needs the Digest route at all.
* **The true reverse fan-out of `(committee, date)`.** The 8 and 12 are lower
  bounds: the bills fetched were chosen from the candidate lists, so this
  measurement cannot establish that no *other* bill carries such an action. The
  census is request-free in spicy-regs, over `bill_actions`.
* **Why 11 of 20 hearings state no `eventId`.** Whether those meetings exist in
  the Repository under another key, or were never posted, was not probed. It
  bounds route 3's real coverage and nothing here bounds it.
* **Whether the Daily Digest entry parse generalises.** One date, 16 entries,
  one committee cross-checked. The action verbs differ by chamber and the
  entries are prose; the error rate is unmeasured.
* **How common the wrong-jacket edge is.** 1 of 5 meetings with both a jacket
  and a bill pointed at a transcript that disowns it. Five is not a rate.
* **Nothing about the 7 unresolvable `BR` drafts.** `BILLS-118Xih.pdf` names a
  discussion draft with no number; whether those drafts later acquire a bill
  number that could be joined back was not investigated.
* **Whether the `eventId` equality is a contract.** It is a measured regularity
  over 10 events and is documented by neither publisher. Nothing here would
  detect it silently ceasing to hold except the per-row identity check this note
  recommends keeping.

## Sources

* [GovInfo MODS for a package](https://api.govinfo.gov/packages/CHRG-118hhrg56198/mods) — keyed; `<extension><bill context="COVER">`.
* [House Committee Repository, by event](https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=117409) and the [static meeting XML](https://docs.house.gov/meetings/VR/VR10/20240612/117409/HHRG-118-VR10-20240612.xml) — keyless.
* [House Committee Repository, per-committee feed](https://docs.house.gov/Committee/RSS.ashx?Code=VR00) — keyless RSS 2.0, each item's `<enclosure>` the static XML.
* [Congress.gov committee-meeting detail](https://api.congress.gov/v3/committee-meeting/118/house/117714) and [hearing detail](https://api.congress.gov/v3/hearing/118/house/57459) — keyed.
* [Congress.gov bill actions](https://api.congress.gov/v3/bill/118/hr/226/actions) — keyed.
* [Congressional Record Daily Digest, House Committee Meetings](https://www.govinfo.gov/content/pkg/CREC-2024-06-12/html/CREC-2024-06-12-pt1-PgD612.htm) — keyless.
* [Senate committee schedule XML](https://www.senate.gov/general/committee_schedules/hearings.xml) — keyless, rolling window.
* [`unitedstates/congress` `committee_meetings` task](https://github.com/unitedstates/congress/blob/master/congress/tasks/committee_meetings.py) — the prior art: it reads `meeting-document[@type='BR']/legis-num` for the House, keys its records on `house_event_id`, and regexes the Senate `<matter>` text rather than reading `AssociatedDocument`.
