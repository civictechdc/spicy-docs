# The print states what happened to the bill. It is not extractable well enough to host

Status: measured 2026-09-20. **Offline: zero requests.** Everything this needed
was already retained — the eight activity-report PDFs in the rollup receipt's
`blobs/`, their package MODS in the MODS re-check's `mods/`, the publisher's
own BILLSTATUS guide as a committed fixture, and the hosted `congress_bills`
export as a local Parquet file.

Sidecar: [`bill-action-relationship-2026-09-20.json`](bill-action-relationship-2026-09-20.json).
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/bill-action-relationship-2026-09-20/`.
Tool: [`tools/analysis/bill_action_relationship.py`](../../tools/analysis/bill_action_relationship.py),
five phases, all through `uv run --frozen`. The numbers block below is rendered
from the sidecar by `render`, and a test byte-compares the two.

This answers build-order item 8 and the caveat of
[the MODS re-check](pdf-yield-mods-recheck-2026-09-20.md): *the package MODS
states that a House committee activity report names `H.R. 1093`; the print
states what happened to it, and no index in that measurement states the
relationship — but that measurement compared keys, never relationships.*

## The verdict

**Evidence only. Do not host a `bill_committee_actions` relationship contract.**

Three numbers decide it, and the third is the one that settles it.

1. **A published row would be right 80% of the time.** On 60 hand-checked
   mentions: the action *kind* is read correctly 90.0% of the time (36 of 40),
   and given a correct reading the row names the right bill 88.9% of the time
   (32 of 36). Multiplied, 32 of 40 rows a contract would publish are both the
   right kind and the right bill — **one published row in five is wrong**. In a
   one-bill sentence attachment is 93.8%; in a multi-bill sentence it is 50.0%.
2. **It would miss 40% of what a reader plainly sees.** Re-weighted recall
   against the actions a reader reads in the entry is **59.6%** — 71.3% where
   the rule fires at all, 42.5% where it does not. And 2,952 further phrase
   occurrences sit in a sentence that names no bill, against 4,456 that reach
   one.
3. **Almost none of it is a fact BILLSTATUS lacks.** Of the 25 measured
   phrasings, 20 have an action code in the publisher's own BILLSTATUS guide —
   including `72` *Hearing held in House* and `74` *Markup in House*, the two
   the print's "committee narrative" was supposed to be the only source for.
   Five do not, and they carry **280 of 4,456 rows (6.3%)**. The hosted
   `bill_actions` contract already holds every action a BILLSTATUS document
   states, with its code and its date.

So the print's bill-action relationship is real, and it is a worse copy of a
record this repository already ingests. The 6.3% that is genuinely the
committee's own voice — `favorably_forwarded`, `declined_markup`,
`not_considered`, `included_in` and `vetoed` — is 280 rows over eight prints,
at 80% row-level precision, and three of those five are *negative* statements
("Committee Republicans declined to mark up H.R. 4440") that no extraction rule
should be trusted to publish at that precision.

**What to do instead**, in order:

- **Ingest the CRPT MODS**, as the re-check's build-order item 2 already says.
  It costs no request and no rule.
- **Keep the print's action language as evidence, not as a relationship.** The
  `document_citations` contract already stores every `bill_number` occurrence
  with its span, its page and the text digest. A consumer that wants the
  narrative reads the span. Nothing new is needed, and nothing is lost: the
  spans this measurement classified are the spans that contract already
  publishes.
- **Do not widen `bill_stage`'s sealed matchers to the print register.** It
  would make the ladder read two different publishers' prose with one rule set,
  and only 2,786 of 4,456 rows map to a rung at all today. `bill_stage` reads
  BILLSTATUS action text; that is its contract and it should keep it.

### What would change this verdict

One thing, and it is not measurable on this sample. **Before the 108th Congress
there is no BILLSTATUS bulk at all** (gap row A11; the API's bill list reaches
the 82nd, and its pre-108th detail records carry only sub-route *counts* for
actions, so the action list is simply absent). For those Congresses a committee
activity report may be the only statement of a bill's committee history that
exists. **Every bill in this sample is 118th** — 978 of 978 — so this
measurement says nothing about it. If a pre-108th activity report is acquired
and its MODS compared against the API's pre-108th record, ask this question
again; the extraction quality measured here would still apply, but the
duplication argument that decides the verdict would not.

## How the relationship was read

One **mention** is one `bill_number` finding from
`interpretation/citations.py` — the same rule, at the same version (`001`),
the re-check measured the yield with. Its **sentence** is the unit an action is
read in, and an action phrase is attached to the **nearest bill designator in
that sentence**, ties going to the one after the phrase, because the print's
grammar puts the measure after the verb (*ordered H.R. 1432 favorably
reported*, *held a hearing on H.R. 2691*). Attaching every bill in the sentence
instead would publish 5,138 rows against 4,456, and the difference is the
multi-bill exposure.

The MODS-bill column totals 1,501 where the re-check's totals 1,500, and the
one is not a discrepancy: this reads the MODS's `(congress, type, number)`
natural keys while the re-check compares the congress-blind key the print
supports, and `CRPT-118hrpt975`'s MODS dates one of its bills to another
Congress — the single cross-Congress entry that measurement already named.

Action **kinds** are not invented here. Each matched phrase is run through
`interpretation/bill_stage.py`'s `infer_stage_from_text`, so a phrasing either
resolves to a sealed rung with the matcher that fired, or is reported unmapped.
The print phrasings themselves are a small measured vocabulary
(`PRINT_ACTION_RULES`), ordered by precedence the way `STAGE_RULES` is, and
derived from a mining pass over all 1,249 pages rather than from the sample.

Three defects were found by hand-checking and fixed **before** the 60 verdicts
were scored, and each is recorded beside the rule it corrected: a sentence
splitter that read "by a vote of 229 to 118." as a list marker and merged two
sentences; one that could not close a sentence inside its own quotation marks,
so a hearing on a *discussion draft* was attached to the bill named after it;
and a `reported` rule that read the plural noun in a bill's own title (*updated
reports relating to*) as a committee reporting it — 23 false rows against 162
real ones.

## The measured numbers

<!-- generated by tools/analysis/bill_action_relationship.py: start -->

Measured 2026-09-20 from retained bytes, **0 requests**: 1,249 pages of the eight prints, 6,365 bill mentions over 978 distinct bills, 4,456 action rows. Phrasing rule set `25d697b17e28`, `bill_number` rule version `001`.

### Every print phrasing, with what the sealed vocabulary makes of it

`Orphan` counts the same phrasing in a sentence that names no bill at all — what no
sentence-scoped rule can ever attach.

| Print phrasing | Rows | Orphan | Bills | `bill_stage` rung | Sealed matcher | BILLSTATUS code |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `introduced` | 753 | 238 | 699 | `introduced` | `introduced` | `1000`, `10000` |
| `referred` | 744 | 105 | 501 | `other_chamber` | `referred` | `H11100`, `2000`, `11000` |
| `held_hearing` | 420 | 1,590 | 333 | **none** | — | `72`, `73`, `13100` |
| `ordered_reported` | 270 | 124 | 175 | `committee` | `reported` | `H12200`, `5000` |
| `became_public_law` | 263 | 230 | 126 | `law` | `public law` | `36000`, `E40000`, `49` |
| `considered` | 245 | 109 | 146 | **none** | — | `H30000` |
| `favorably_reported` | 228 | 31 | 215 | `committee` | `reported` | `H12200`, `5000`, `79` |
| `held_markup` | 219 | 57 | 155 | `committee` | `markup` | `74`, `75`, `13200` |
| `discharged` | 206 | 17 | 104 | **none** | — | `H12300`, `77`, `78` |
| `reported` | 162 | 54 | 145 | `committee` | `reported` | `H12200`, `5000`, `79` |
| `suspension` | 146 | 38 | 134 | **none** | — | `H37300` |
| `favorably_forwarded` | 139 | 1 | 136 | **none** | — | **none** |
| `report_filed` | 138 | 92 | 138 | **none** | — | `H12100`, `14900` |
| `passed_house` | 132 | 186 | 112 | **none** | — | `8000`, `81` |
| `received_in_chamber` | 118 | 4 | 116 | `other_chamber` | `received in the senate` | `H14000` |
| `included_in` | 83 | 6 | 73 | **none** | — | **none** |
| `passed_senate` | 55 | 26 | 43 | **none** | — | `17000`, `82` |
| `presented_to_president` | 30 | 0 | 29 | **none** | — | `E20000`, `28000` |
| `placed_on_calendar` | 27 | 1 | 22 | `other_chamber` | `placed on the union calendar` | `H12410` |
| `declined_markup` | 25 | 1 | 25 | **none** | — | **none** |
| `not_considered` | 25 | 3 | 25 | **none** | — | **none** |
| `agreed_to` | 9 | 11 | 6 | **none** | — | `8000`, `17000` |
| `rule_for_consideration` | 9 | 0 | 7 | **none** | — | `H1L210` |
| `vetoed` | 8 | 13 | 4 | **none** | — | **none** |
| `conference` | 2 | 15 | 1 | `conference` | `conference report` | `H25200`, `47`, `48` |

**2,786 of 4,456** action rows carry a phrasing one of `bill_stage`'s sealed matchers reads; **1,670** carry one it does not — `passed_house`, `suspension`, `held_hearing`, `discharged` and `report_filed` among them, so the print's own spelling of passage and of every committee step falls outside the sealed ladder.

**2,952 further phrase occurrences** sit in a sentence that names no bill, against 4,456 that reach one.

Only 5 of the 25 phrasings — `vetoed`, `not_considered`, `declined_markup`, `favorably_forwarded`, `included_in`, **280 rows** — name an event the publisher's own BILLSTATUS guide states no action code for. Everything else the print says about a bill, BILLSTATUS has a code for.

### Per print

| Report | Pages | MODS bills | Mentions | Mentions with an action | In a multi-bill sentence | Action rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CRPT-118hrpt965 | 282 | 380 | 2,071 | 1,284 | 282 | 1,764 |
| CRPT-118hrpt968 | 56 | 179 | 267 | 20 | 3 | 23 |
| CRPT-118hrpt970 | 127 | 111 | 347 | 268 | 31 | 315 |
| CRPT-118hrpt972 | 119 | 217 | 427 | 151 | 183 | 186 |
| CRPT-118hrpt974 | 296 | 194 | 1,697 | 986 | 296 | 1,441 |
| CRPT-118hrpt975 | 103 | 91 | 479 | 227 | 71 | 316 |
| CRPT-118hrpt976 | 99 | 48 | 126 | 68 | 20 | 71 |
| CRPT-118hrpt977 | 167 | 281 | 951 | 306 | 6 | 340 |
| **Total** | 1,249 | 1,501 | 6,365 | 3,310 | 892 | 4,456 |

### The hand check

60 mentions, sampled across the eight prints and read in the extract text with the surrounding entry. 40 carried a tool action and 20 carried none.

| Measure | Judged | Correct | Rate |
| --- | ---: | ---: | ---: |
| Action classification | 40 | 36 | **90.0%** |
| Bill-to-action attachment, given a correct reading | 36 | 32 | **88.9%** |
| — one-bill sentence | 32 | 30 | 93.8% |
| — multi-bill sentence | 4 | 2 | 50.0% |
| **A published row is right kind and right bill** | 40 | 32 | **80.0%** |
| Recall, re-weighted by stratum | 148 | 94 | **59.6%** |
| — where the tool found an action | 108 | 77 | 71.3% |
| — where it found none | 40 | 17 | 42.5% |

### Against what BILLSTATUS already states

The retained `congress_bills` export holds 418,657 bills, Congresses 6 to 119. **958 of the 978** bills these prints attach an action to have a hosted row; 20 do not. Every bill the prints act on is from Congress 118 — **this sample contains no pre-108th bill at all**, so what the print would add before the 108th is not measured here. Of the 4,390 action rows whose bill is hosted, **849** state a rung the hosted row's *latest action alone* already states.

<!-- generated by tools/analysis/bill_action_relationship.py: end -->

## What the print says that BILLSTATUS does not

The comparison is against a **floor**, stated before the number: the retained
export is `congress_bills`, which carries `latest_action_date` and
`latest_action_text` — *one* action per bill. The hosted `bill_actions`
contract holds every action with its code and date, and no such export is
retained locally. So "the hosted row's latest action alone already states this
rung" is a lower bound on the duplication, and the full action list can only
duplicate more. That is the safe direction for a verdict that argues against
building and the unsafe one for a verdict that argues for it.

Even against that floor, 849 of 4,390 rows (19.3%) state a rung the *single*
latest action already states.

The stronger evidence is the publisher's own vocabulary, read from the
committed fixture `tests/fixtures/billstatus_codes/guide-2026-08-03.md` rather
than assumed. Its action-code tables list `72` *Hearing held in House*, `74`
*Markup in House*, `77` *Discharged from House committee*, `H12200` *Committee
reported*, `H12300` *Committee discharged*, `H12100` *Committee report of an
original measure*, `H1L210` *Rule provides for consideration of* and
`H37300` *Final Passage Under Suspension of the Rules Results*. The guide also
names `House committee actions` as one of four `sourceSystem` values. Every
common thing these prints say about a bill has a code there.

**What this cannot see**, and it matters: whether those codes are *populated*
for these 978 bills. The six BILLSTATUS fixtures this repository holds are
119th-Congress measures with two to five actions each, none of them
committee-sourced, so nothing retained here shows a real House committee action
list. The duplication argument therefore rests on the publisher's stated
vocabulary plus the latest-action floor, not on a row-for-row comparison
against `bill_actions`. Running that comparison needs one BILLSTATUS document
per sampled bill, which is a keyed acquisition this measurement did not make.

## Why the extraction is worse than it looks

The hand check's 60 contexts are in the receipt with every verdict. Five
failure shapes account for almost all of it, and none is a tuning problem.

**The entry is not a sentence, and every committee sets it differently.** In
`CRPT-118hrpt968` the markup item's long title ends in a period and the
disposition follows as a fragment — *"...and for other purposes. (Green)
(ordered favorably reported to the House, as amended, 26Y–23N)"* — so the bill
and its disposition are two sentences and the second names no bill. **116 of
that print's 125 "ordered favorably reported" occurrences sit in a sentence
naming no bill at all**, which is why it yields 27 rows over 179 MODS-stated
bills. In `CRPT-118hrpt974` the same committee action is one clean sentence and
the same rules reach 1,443 rows.

**The en-bloc disposition names no bill by design.** *"The measures considered
en bloc were ordered favorably reported to the House by voice vote."* is a
sentence about "the measures". Six bills were just listed above it as numbered
items. No sentence-scoped rule can attach it, and an entry-scoped rule has to
decide how far up the list "en bloc" reaches.

**The print writes "the bill".** *"H.R. 1713 was introduced by Representative
Frank Lucas on March 22, 2023. The bill was referred to the Committee on
Science, Space, and Technology... which reported the bill, as amended, on May
11, 2023. On December 4, 2023, the bill was considered under suspension of the
rules and agreed to by voice vote."* One row is produced, for the introduction,
because only the first sentence names the bill. Four of the sample's 60
contexts lose three or more actions exactly this way.

**A list heading covers many bills and reaches the first.** *"May 17,
2023—Markup held on:"* followed by six bill entries: the heading's colon keeps
it in the first entry's sentence, so the first bill gets `held_markup` and the
other five get nothing.

**A ruled table states the action in a column header.** `CRPT-118hrpt974`'s
"Bill No. | Date of Committee Consideration | Title" grid states a committee
consideration date for every bill in it. No sentence rule can see a column
header, and the re-check turned table detection off deliberately because a
citation contract does not need it.

The two classification false positives that are not structural are worth naming
because they would publish confidently wrong facts: a `Pub. L.` cite inside a
bill's *description* (*"H.R. 6972 amends the Federal Vacancies Reform Act of
1998 (P.L. 105–277)"*) read as the bill becoming that law, and
*"reported to Congress for review"* inside a bill's subject matter read as a
committee reporting it.

## Complexity

Zero requests. `text` is linear in retained pages: 1,249 pages of eight PDFs in
about 7 s with table detection off. `measure` is one pass per rule over each
document, `O(K·C)` for `K` = 25 rules and `C` = 3.3 M characters, plus a binary
search per mention into the sentence offsets — about 1 s for the whole corpus.
The overlap is one hash join in DuckDB over a 418,657-row Parquet export.
Nothing here is superlinear in the corpus.

## What this measurement cannot see

- **One Congress.** All 978 bills the prints act on are 118th, so the pre-108th
  question the verdict turns on is untested — see "What would change this
  verdict".
- **`bill_actions` itself was never compared row for row**, only the
  `congress_bills` latest action and the publisher's stated code vocabulary.
- **Eight prints, eight committees.** The per-print spread is the finding, not
  noise: 27 rows from one 56-page print and 1,443 from one 296-page print. A
  ninth committee's house style is unmeasured, and the two extremes here are
  four orders of magnitude apart per page.
- **60 mentions.** At 40 judged rows the classification rate has roughly a
  ±9-point interval, and the multi-bill attachment cell is 4 rows. The 892
  multi-bill mentions and the 2,952 orphan phrases are corpus-wide counts and
  carry no such uncertainty; they, not the hand-check rates, are what the
  verdict leans on.
- **Dates were extracted but never scored.** `print_dates` reads the ISO date
  off each sentence and the rows carry it; whether the date belongs to the
  action rather than to a neighbouring clause was not hand-checked.
- **The phrasing vocabulary is a floor.** A phrasing no rule spells is invisible
  here and makes the print look thinner: *"voted to advance all four pieces of
  legislation"* and *"was not agreed to in the full House vote"* both appear in
  the sample and neither has a rule. That error runs towards the verdict this
  document reaches, which is the direction that deserves the suspicion; the
  orphan count (2,952) and the recall figure (59.6%) both already price it.
