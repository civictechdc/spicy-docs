# Scoring the Record parse rule against the publisher, on the overlap era

Status: **measured 2026-09-20**, 296 requests (40 GovInfo, 256 keyed
Congress.gov), both caps declared before the run. The receipt is
`~/Work/corpora/supply-2026-09-02/receipts/record-communications-overlap-2026-09-20/`
and the sidecar is
[`record-communications-overlap-2026-09-20.json`](record-communications-overlap-2026-09-20.json).

**Verdict: the parse rule clears the declared threshold on every field it will
publish, and the official/agency split does not.** The contract change lands
with the split columns NULL on a reconstructed row — which is the behaviour
[§5 rule 3](executive-communications-backfill-2026-09-20.md) prescribed before
this ran, for exactly the case this measured.

The [backfill research](executive-communications-backfill-2026-09-20.md)
established that Congress.gov's `house-communication` detail record is a
decomposition of the sentence the Congressional Record prints in its House
`EXECUTIVE COMMUNICATIONS, ETC.` section, and that the publisher's `abstract`
equals the printed entry under named normalizations. It established that on
**two rows**. Its own §7 says so: *"Only two ground-truth rows. The overlap era
offers 26,725, and the parse rule's real score is unknown until it is run
against them."* This is that run, over
`sources/congress/record_communications.py` through
`tools/analysis/record_communications_overlap.py`.

## The threshold, stated before the run

The plan's contract change lands **only if**:

- `abstract` equals the printed entry on **at least 95%** of scored rows; and
- each derived field — `report_nature`, `legal_authority`,
  `submitting_official`, `submitting_agency`, the committee referral and the
  RIN — agrees on **at least 90%** of the rows *where the publisher states it*.

Denominators are per field and are the rows the publisher states that field on,
never the whole sample: a field the publisher leaves empty is not a row the rule
got wrong.

**The official/agency pair gets one denominator, declared here**: the rows where
the split rule fired *and* the publisher decomposed the from-clause at all. Two
reasons. A row where the rule declined is excluded, because a deliberate NULL is
the rule refusing and counting it as a miss would read "refused to guess" as
"guessed wrong" — how often it declines is reported separately, as coverage. And
the two sides share that one denominator rather than each getting its own,
because the split is one boundary decision: scoring each side only on the rows
the publisher happened to state *that* side on lets the pair look like one
passing field and one failing one, which is a fact about the denominators and
not about the rule. The narrower per-side view is reported beside it.

If a field misses its threshold, that field does not publish, and this note
records what was measured and what would reverse it.

## The commands and their caps

Caps declared before the first request, enforced by a counter read back from the
retained request log across resumes: **40 GovInfo requests and 600 keyed
Congress.gov requests** for the whole campaign. Spent: 40 and 256. The GovInfo
allowance is exhausted, so a further sample needs a newly declared cap; it was
not moved after the fact.

```sh
uv run --frozen python -m tools.analysis.record_communications_overlap fetch \
    --receipt ~/Work/corpora/supply-2026-09-02/receipts/record-communications-overlap-2026-09-20
uv run --frozen python -m tools.analysis.record_communications_overlap score \
    --receipt ~/Work/corpora/supply-2026-09-02/receipts/record-communications-overlap-2026-09-20 \
    --output docs/research/record-communications-overlap-2026-09-20.json
uv run --frozen python -m tools.analysis.record_communications_overlap render \
    --output docs/research/record-communications-overlap-2026-09-20.json \
    --report docs/research/record-communications-overlap-2026-09-20.md
```

The sample is ten House sitting days, two per Congress from the 114th through
the 118th, named in the tool rather than discovered (discovery is itself a keyed
walk and the cap is for the measurement). Every number those days printed is
requested at the publisher's own upper-case locator
`house-communication/{congress}/EC/{n}`, round-robin across issues so a cap that
bites truncates every issue's tail rather than deleting the last Congresses.

## What the first run found, and what was changed because of it

The first score was **58.4% on `abstract`**. That is the measurement doing its
job: two ground-truth rows had agreed, and 166 did not. Three print artifacts
accounted for nearly all of it, each found by disagreement with the publisher
and each fixed in the rule with its reason beside it:

1. **GPO's hyphenated line wrap.** The Record prints
   `[Docket No.: FDA-2013-` and breaks the line, and collapsing the layout left
   `FDA-2013- C-1008` where the publisher has no space. It is the artifact
   `extraction/gpo_normalize.py` already handles for PDF text and §3.1 of the
   research said the HTML path would need; the rule here is slightly wider,
   because GPO wraps after a digit as readily as after a letter. It was also
   eating RINs: `(RIN: 1625-` / `AA00)` read as no RIN at all.
2. **A fourth publisher normalization.** The Record prints `Pub. L. 95-452`
   where the publisher writes `Public Law 95-452` — the same kind of edit as
   `Sec.` → `section`, which the research had named. Three, not four, was a
   floor established on two rows.
3. **A print dash the Record spells with four hyphens.** `-{2,3}` folded three
   and left the fourth standing as a second dash.

Then a fourth finding, from the sections themselves rather than from any field
comparison: **the 117th and 118th sections parsed to zero entries.** The Record
changed how it numbers an entry — `1205.` through 2020, `EC-1205.` from 2021 —
and the entry pattern only matched the older spelling. A field-by-field score
can never report this, because a section that yields no entries yields nothing
to disagree about; only the per-issue contiguity witness and the printed-entry
count show it. The pattern now accepts both spellings.

**What this costs the score's independence, stated plainly.** The three print
fixes were derived from the 114th and 115th sections alone, so those 112 rows
are in-sample and their column is an upper bound. The 144 rows of the 116th
through 118th were not read while any field rule was being changed, and the
threshold is applied to them. The entry-pattern widening is the one exception:
it was found by reading zero entries out of the 117th and 118th, so those
sections' *recall* is in-sample even though every field rule scored on them is
not.

## The measurement

<!-- generated: record-communications-overlap -->

Measured 2026-09-20 against rule `record-communication-effcf9cdf71c`. 40 GovInfo requests of 40 and 256 keyed Congress.gov requests of 600.

256 entries printed across 10 retained sections; 256 have a publisher decomposition to score against. The official/agency split rule fired on 234 of them.

**Held out** is the 144 rows of the Congresses the rule was never revised against; **tuning** is the 112 rows of the 114th and 115th, whose disagreements produced the three print-artifact fixes, so its column is an in-sample upper bound. The threshold applies to the held-out column.

| Field | Held out | | Tuning | | Whole sample | |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| | agreed/stated | precision | agreed/stated | precision | agreed/stated | precision |
| `abstract` | 141/144 | 97.9% | 110/112 | 98.2% | 251/256 | 98.0% |
| `from_clause_concatenation` | 133/136 | 97.8% | 98/99 | 99.0% | 231/235 | 98.3% |
| `legal_authority` | 112/113 | 99.1% | 89/89 | 100.0% | 201/202 | 99.5% |
| `referral_count` | 137/144 | 95.1% | 111/112 | 99.1% | 248/256 | 96.9% |
| `referral_names` | 103/144 | 71.5% | 112/112 | 100.0% | 215/256 | 84.0% |
| `report_nature` | 138/144 | 95.8% | 89/99 | 89.9% | 227/243 | 93.4% |
| `rin` | 34/34 | 100.0% | 54/54 | 100.0% | 88/88 | 100.0% |
| `submitting_agency` | 114/129 | 88.4% | 86/94 | 91.5% | 200/223 | 89.7% |
| `submitting_agency_where_both_stated` | 114/121 | 94.2% | 86/94 | 91.5% | 200/215 | 93.0% |
| `submitting_official` | 110/129 | 85.3% | 87/94 | 92.5% | 197/223 | 88.3% |
| `submitting_official_where_both_stated` | 110/121 | 90.9% | 87/94 | 92.5% | 197/215 | 91.6% |
| `submitting_split` | 110/129 | 85.3% | 86/94 | 91.5% | 196/223 | 87.9% |

`submitting_official`, `submitting_agency` and `submitting_split` share one denominator: the rows the split rule answered and the publisher decomposed at all. The two `_where_both_stated` rows are the narrower view, over the rows the publisher decomposed into both sides. Which side of the pair looks like the failure depends on that choice, so both are printed.

Per-issue completeness witness:

| Congress | Granule | Entries | Block | Holes | Contiguous |
| ---: | --- | ---: | --- | ---: | --- |
| 114 | `CREC-2015-06-10-pt1-PgH4133-4` | 31 | 1772-1802 | 0 | yes |
| 114 | `CREC-2016-06-15-pt1-PgH3912-2` | 31 | 5687-5717 | 0 | yes |
| 115 | `CREC-2017-06-14-pt1-PgH4917-3` | 20 | 1661-1680 | 0 | yes |
| 115 | `CREC-2018-06-13-pt1-PgH5150-4` | 30 | 5136-5165 | 0 | yes |
| 116 | `CREC-2019-06-12-pt2-PgH4625-3` | 29 | 1266-1294 | 0 | yes |
| 116 | `CREC-2020-09-16-pt1-PgH4488-2` | 25 | 5277-5301 | 0 | yes |
| 117 | `CREC-2021-06-16-pt1-PgH2889` | 35 | 1358-1392 | 0 | yes |
| 117 | `CREC-2022-06-15-pt1-PgH5608-2` | 14 | 4345-4358 | 0 | yes |
| 118 | `CREC-2023-06-14-pt1-PgH2929-2` | 30 | 1205-1234 | 0 | yes |
| 118 | `CREC-2024-06-12-pt1-PgH3973` | 11 | 4520-4530 | 0 | yes |

Publisher answers on the detail route: 256 ok.

<!-- end generated -->

## The verdict, field by field

Against the held-out column and the threshold declared above:

| Field | Held out | Threshold | |
| --- | ---: | ---: | --- |
| `abstract` | 141/144 · 97.9% | 95% | **passes** |
| `legal_authority` | 112/113 · 99.1% | 90% | **passes** |
| `rin` | 34/34 · 100% | 90% | **passes** |
| `report_nature` | 138/144 · 95.8% | 90% | **passes** |
| `referral_count` | 137/144 · 95.1% | 90% | **passes** |
| `submitting_agency` | 114/129 · 88.4% | 90% | **misses** |
| `submitting_official` | 110/129 · 85.3% | 90% | **misses** |
| `submitting_split` (the pair) | 110/129 · 85.3% | 90% | **misses** |
| `referral_names` | 103/144 · 71.5% | — | published, not joinable; see below |

So: the contract change lands, and `submitting_official` / `submitting_agency`
stay NULL on a reconstructed row. **On the one declared denominator the pair
fails on both sides**, which is the reason. §5 rule 3 already said a row whose
split is unresolved carries NULLs beside the retained sentence; what this
measurement establishes is that the split rule is unresolved *at publishable
precision*, not that it fails to fire. It fires on 129 of 144 held-out rows.

### The denominator is load-bearing, so both views are reported

| View | n | `submitting_agency` | `submitting_official` |
| --- | ---: | ---: | ---: |
| Rule fired and the publisher decomposed (**declared**) | 129 | 88.4% | 85.3% |
| The publisher decomposed into **both** sides | 121 | 94.2% | 90.9% |

The 8-row gap is one publisher artifact, and it is the whole difference:
`118-ec-4522` through `4530` in `CREC-2024-06-12-pt1-PgH3973`, where
Congress.gov put the **entire** printed from-clause — *Director, Mission
Statement, Office of Legislative Affairs, Department of Homeland Security* —
into `submittingAgency` and stated no `submittingOfficial` at all. The Record
printed an ordinary from-clause; the publisher's own decomposition is what
collapsed. All 8 are held out, all 8 count as agency disagreements (8 of the
15), and none of them can count as an official disagreement under a
per-side denominator, because the publisher states no official to disagree
with.

Read per side, that artifact alone moves `submitting_agency` from 94.2% to
88.4% and `submitting_official` from 90.9% to 85.3% — so which side of the pair
looks like the failure is a choice of denominator, not a property of the rule.
Under **either** view at least one side misses 90%, so the landed decision does
not turn on the choice; its stated reason does, and the reason is that the pair
is one boundary decision and the declared view fails on both sides.

### `referral_names` is a naming drift, not a rule's score

The Record's committee names **are** published on a reconstructed row, in
`referral_committee_name` and `committees_json`: they are the committee's name
on the day the entry was printed, and `referral_count` — whether the referral
tail was read correctly at all — agrees with the publisher on 95.1% of held-out
rows. What 71.5% measures is whether the two publishers spell the same committee
the same way, and they do not: the 116th Record prints *Oversight and Reform*
where Congress.gov states *Oversight and Government Reform Committee* for the
same referral. So the name is published and nothing joins on it;
`referral_system_code` is the key, it is NULL on a reconstructed row, and the
resolver that would fill it is **not built** (see "still open").

## The failure shapes, with examples

- **The official/agency boundary sits one comma group further left than the
  rule puts it, whenever the agency chain begins with a sub-agency unit whose
  head noun is not an organization word.** `114-ec-1773`: the publisher's
  `submittingAgency` is *Postsecondary Education, Department of Education*; the
  rule starts the agency at *Department of Education* and leaves *Postsecondary
  Education* with the official. Same shape for *Acquisition, Technology, and
  Logistics*, *Personnel and Readiness* and *FDA*. This is §3.4's finding,
  quantified: the boundary is a fact about the publisher's own hierarchy, not
  about the sentence's punctuation.
- **A joint referral to exactly two committees with no comma between them reads
  as one name.** `118-ec-4525`: *jointly to the Committees on Energy and
  Commerce and the Judiciary* — the only separator is `and`, and splitting on
  `and` shatters *Ways and Means*, which §3.3 measured. 7 of 144 held-out rows.
  The whole tail is retained, so the roster can resolve both.
- **An entry with two `pursuant to` clauses splits at the first; the publisher
  splits at the last.** `114-ec-1785` and `117-ec-4345`: the publisher's
  `reportNature` carries the first clause and its `legalAuthority` starts at the
  second. 6 of 144 on `report_nature`, 1 of 113 on `legal_authority`.
- **Three held-out abstracts still differ**, each on a residual GPO spacing
  artifact inside a bracketed identifier that no rule here folds.
- **Two publisher-side artifacts**, both counted as disagreements because the
  comparison was not relaxed after the held-out read:
  `114-ec-5712`'s `submittingAgency` is ` Department of Health and Human
  Services`, with a leading space; and the eight rows `118-ec-4522`..`4530` of
  `CREC-2024-06-12-pt1-PgH3973` carry the whole printed from-clause in
  `submittingAgency` with no `submittingOfficial`, which is the entire gap
  between this note's two split denominators.

## What this sample cannot see

- **It is 256 rows of the 26,725 the overlap era offers**, two days per
  Congress, all but one of them a Wednesday in June. A day whose section carries
  an unusual entry shape — a memorial printed under this heading, a
  communication with no referral — is invisible to it.
- **It says nothing directly about the pre-114th era it exists to license.**
  Every scored row is from a Congress the publisher decomposes. The 104th-113th
  sentences are the same grammar on the seven issues the backfill research read
  (216 entries; 216/216 for the opening, the `transmitting` split and the
  referral), but no publisher record exists to score them against — that is the
  whole reason for the backfill, and also the reason this measurement is
  indirect. The argument it supports is: *the rule reads the publisher's own era
  correctly, and the earlier era is the same sentence.*
- **It cannot establish contiguity across a Congress.** Ten issues, each
  contiguous within itself (10 of 10, no holes, strictly increasing), which is
  the same within-day witness the research already had. The across-Congress
  check needs every sitting day of one Congress.
- **It cannot see a day whose section is missing entirely.** All ten sampled
  days carried one, and the granule selector takes every match — but a House
  sitting day with no `EXECUTIVE COMMUNICATIONS, ETC.` granule would look
  identical to a day that was never sampled.
- **The split rule's coverage and its precision are measured on the same rows.**
  It declines on 15 of 144 held-out rows and is right on 114 of the 129 it
  answers; whether the rows it declines are the rows it would have got wrong is
  not established.
- **It cannot separate 88.4% from 90%.** 144 held-out rows put a wide interval
  on every figure here, and the split's two views sit either side of the
  threshold. What the sample does establish is that one publisher artifact from
  one granule moves either side by six points, which is the reason the pair is
  scored and published as a pair.
- **The committee-name resolver does not exist**, so `referral_system_code` is
  NULL on every reconstructed row and nothing in this measurement exercises the
  join the table is for. Building it against `committees.system_code` — with the
  name drift this note measured as the thing it has to absorb — is the next
  piece of work `house_communications` needs.

## What would reverse the split-column decision

`submitting_split` — both sides, on the declared denominator — at or above 90%
on a **fresh held-out draw**, under a newly declared request cap, with the
agency vocabulary widened by the sub-agency units the publisher places on the
agency side. The units this run
names — *Postsecondary Education*, *Personnel and Readiness*, *Acquisition,
Technology, and Logistics*, *FDA* — are not a rule; they are four
disagreements, and fitting to them and re-scoring the same rows would be the
formatting assertion this note exists to avoid. The right shape is a resolver
against a published organization roster, the way the committee names already
resolve against `committees.system_code`.

Until then the from-clause is retained whole on every row
(`record_entry_text`), it agrees with the publisher's two fields concatenated on
97.8% of held-out rows, and a downstream consumer can split it later without
re-acquiring anything.
