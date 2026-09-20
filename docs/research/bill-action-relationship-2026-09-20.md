# The print states what happened to the bill, and often it is the only record of a hearing

Status: measured 2026-09-20. **Every figure but one comes from retained
bytes** — the eight activity-report PDFs in the rollup receipt's `blobs/`,
their package MODS in the MODS re-check's `mods/`, the publisher's BILLSTATUS
guide as a committed fixture, and the hosted `congress_bills` export as a local
Parquet file. The exception is the row-for-row overlap: **20 keyed requests**,
bounded in the tool, for the whole action list of 20 sampled bills, because the
claim it settles must rest on rows and not on a code table.

Sidecar: [`bill-action-relationship-2026-09-20.json`](bill-action-relationship-2026-09-20.json).
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/bill-action-relationship-2026-09-20/`.
Rules: [`src/spicy_docs/interpretation/bill_actions.py`](../../src/spicy_docs/interpretation/bill_actions.py).
Contract: [`src/spicy_docs/schemas/bill_action_tables.py`](../../src/spicy_docs/schemas/bill_action_tables.py).
Tool: [`tools/analysis/bill_action_relationship.py`](../../tools/analysis/bill_action_relationship.py),
six phases, all through `uv run --frozen`; it imports the rules rather than
restating them, so the measurement and the contract cannot disagree. The numbers block below is rendered
from the sidecar by `render`, and a test byte-compares the two.

This answers build-order item 8 and the caveat of
[the MODS re-check](pdf-yield-mods-recheck-2026-09-20.md): *the package MODS
states that a House committee activity report names `H.R. 1093`; the print
states what happened to it, and no index in that measurement states the
relationship — but that measurement compared keys, never relationships.*

## The verdict

**Host the single-bill subset with its precision stated; keep the rest as
evidence in the same table.** `bill_committee_actions`
(`schemas/bill_action_tables.py`), keyed
`(document_key, text_sha256, bill_id, print_phrasing, span_start)`, 27 columns,
shaped from `interpretation/bill_actions.py`.

The figures a consumer acts on, all hand-checked on 60 mentions:

| | Rows | Published rows that are right kind **and** right bill |
| --- | ---: | ---: |
| `attachment_confidence = 'single'` | **4,089 of 4,456 (91.8%)** | **83.3%** (30 of 36) |
| `attachment_confidence = 'multi'` | 367 (8.2%) | 50.0% (2 of 4) |

So the trusted view costs 8% of the volume and publishes rows that are right
five times in six. The `multi` rows stay in the table rather than being
dropped: a coin-flip row a reader can open at `sentence_start` and check beats
a fact nobody can see.

**Recall is a separate axis and it is 59.6%.** 83.3% says *what is published is
right*; it does not say *what the document contains is captured*. A consumer
counting hearings off these rows is counting a floor. The five measurements
that would raise it are listed below, and every one of them is request-free.

### What this is worth, and the two claims that were wrong before it

**A subcommittee hearing on a bill is often recorded nowhere else.** Asked for
the whole action list of 20 of these bills — 20 keyed requests, 197 published
actions — the publisher has **no counterpart at all to 10 of the 15
subcommittee hearings the print states**: no action, no code, no wording. The
five it does state come from two bills and both carry `H21000` *Subcommittee
Hearings Held*.

**Markups are stated in full, and saying so is what makes the first claim
credible.** All 8 markup rows appear in the publisher's list, coded
`H15000-B`, `H15001` or `H22000` by the `House committee actions` source
system, which files 48 of the 197 actions. For a markup the print is a
*second, coded* source, not the only one.

Five more phrasings have no known code at all — `favorably_forwarded` (the
subcommittee-to-full-committee step), `declined_markup`, `not_considered`,
`included_in`, `vetoed` — 280 rows, three of them *negative* statements no
index carries.

#### Two retracted claims, and why both checks could not fail

This document has now been wrong about the same thing in both directions, and
the mechanism was identical each time: a check validated against a record that
was not the publisher's answer.

**First**, it read codes `72` *Hearing held in House* and `74` *Markup in
House* out of the guide and concluded BILLSTATUS already states a House
committee's hearings and markups, so the table was not worth building. Those
are **section 5** values — the mapping of LOC *summaries* version codes to
`<actionDesc>` text, the `<versionCode>` child of `<summaries>` — and the
self-check scanned the whole guide, so it validated against a 123-code superset
drawn from three tables.

**Second**, the correction scoped the scan to section 3, found no House hearing
or markup code, and concluded the publisher **has** none and the print is the
only structured source. That is false on the wire. Section 3's own first
paragraph says *"Codes in this table are representational... It is provided as
a courtesy; a complete, authoritative list of action codes does not exist."*
**13 of the 35 distinct action codes in the retained responses appear nowhere
in it** — `H11000`, `H15000-B`, `H15001`, `H19000`, `H21000`, `H22000`,
`H23000`, `H25000`, `H30300`, `H37100`, `H37220`, `H38800`, `Intro-H`. A list
the publisher calls incomplete is not a vocabulary.

The comparison that found it had the same defect as the claim: it asked whether
the publisher states a code *this repository maps the phrasing to*, and for
hearings and markups that mapping was empty by construction, so the branch
reading `actionCode` was dead and `code_matched == 0` was an identity restated
as a finding — with a test asserting the identity. The overlap now reads the
publisher's codes off the response, matched on the event's wording, and reports
which of them the retained guide never lists.

### What it duplicates, and that is fine

Most of it. Of the single-attachment rows whose phrasing carries a known code,
the publisher states the same code on the great majority — referrals,
introductions, reportings, passage. Those rows are not the reason to build;
they are what makes the table joinable, and `billstatus_action_code` carries
the code so a consumer can drop them with one predicate.

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

Measured 2026-09-20 from retained bytes, **0 requests**: 1,249 pages of the eight prints, 6,365 bill mentions over 978 distinct bills, 4,456 action rows. Phrasing rule set `f9130c97fe4b`, `bill_number` rule version `001`.

### Every print phrasing, with what the sealed vocabulary makes of it

`Orphan` counts the same phrasing in a sentence that names no bill at all — what no
sentence-scoped rule can ever attach. † marks a code the retained user guide does not
list and that only the publisher's own responses show.

| Print phrasing | Rows | Orphan | Bills | `bill_stage` rung | BILLSTATUS action code, House |
| --- | ---: | ---: | ---: | --- | --- |
| `introduced` | 753 | 238 | 699 | `introduced` | `1000` |
| `referred` | 744 | 105 | 501 | `other_chamber` | `H11100`, `2000` |
| `held_hearing` | 420 | 1,590 | 333 | **none** | `H21000` † |
| `ordered_reported` | 270 | 124 | 175 | `committee` | `H12200`, `5000` |
| `became_public_law` | 263 | 230 | 126 | `law` | `36000`, `E40000`, `E30000` |
| `considered` | 245 | 109 | 146 | **none** | `H30000` |
| `favorably_reported` | 228 | 31 | 215 | `committee` | `H12200`, `5000` |
| `held_markup` | 219 | 57 | 155 | `committee` | `H15000-B`, `H15001`, `H22000` † |
| `discharged` | 206 | 17 | 104 | **none** | `H12300` |
| `reported` | 162 | 54 | 145 | `committee` | `H12200`, `5000` |
| `suspension` | 146 | 38 | 134 | **none** | `H37300` |
| `favorably_forwarded` | 139 | 1 | 136 | **none** | **none** |
| `report_filed` | 138 | 92 | 138 | **none** | `H12100` |
| `passed_house` | 132 | 186 | 112 | **none** | `8000` |
| `received_in_chamber` | 118 | 4 | 116 | `other_chamber` | `H14000` |
| `included_in` | 83 | 6 | 73 | **none** | **none** |
| `passed_senate` | 55 | 26 | 43 | **none** | **none** |
| `presented_to_president` | 30 | 0 | 29 | **none** | `E20000`, `28000` |
| `placed_on_calendar` | 27 | 1 | 22 | `other_chamber` | `H12410` |
| `declined_markup` | 25 | 1 | 25 | **none** | **none** |
| `not_considered` | 25 | 3 | 25 | **none** | **none** |
| `agreed_to` | 9 | 11 | 6 | **none** | `8000` |
| `rule_for_consideration` | 9 | 0 | 7 | **none** | `H1L210` |
| `vetoed` | 8 | 13 | 4 | **none** | **none** |
| `conference` | 2 | 15 | 1 | `conference` | `H25200` |

**2,786 of 4,456** action rows carry a phrasing one of `bill_stage`'s sealed matchers reads; **1,670** carry one it does not — `passed_house`, `suspension`, `held_hearing`, `discharged` and `report_filed` among them, so the print's own spelling of passage and of every committee step falls outside the sealed ladder.

**2,952 further phrase occurrences** sit in a sentence that names no bill, against 4,456 that reach one.

**5 phrasings have no known action code at all** — `vetoed`, `not_considered`, `declined_markup`, `favorably_forwarded`, `included_in`, 280 rows. **2 more (`held_markup`, `held_hearing`, 639 rows) are coded by the publisher through a code the retained guide never lists.** That is a gap in the *document*, not in the vocabulary: section 3 says in its own first paragraph that it is representational and that no authoritative list exists, and 13 of the 35 distinct codes in the retained responses appear nowhere in it.

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
| **A published row is right kind and right bill — `single`** | 36 | 30 | **83.3%** |
| **— `multi`** | 4 | 2 | **50.0%** |
| Recall, re-weighted by stratum | 148 | 94 | **59.6%** |
| — where the tool found an action | 108 | 77 | 71.3% |
| — where it found none | 40 | 17 | 42.5% |

**4,089 of 4,456 rows (91.8%) are `single`**, so a consumer filtering to the trusted class keeps 91.8% of the volume at 83.3% precision. Recall is a separate axis and is 59.6%: this is a statement about what is published, never about what a reader sees captured.

### The row-for-row BILLSTATUS overlap, 20 keyed requests

The retained `congress_bills` export carries one action per bill, so it can only floor the duplication. This asked the publisher for the **whole action list** of 20 of the bills these prints act on — 197 published actions, 35 distinct action codes — and compared 76 single-attachment print rows against them. The publisher's codes are read off the response and matched on the event's *wording*, never on this repository's own mapping, because a comparison against one's own mapping is a check that cannot fail.

| | Print rows | States the event | Codes the publisher uses for it |
| --- | ---: | ---: | --- |
| `held_hearing` | 15 | **5** | `H21000` |
| `held_markup` | 8 | **8** | `H15000-B`, `H15001`, `H22000` |

**10 of 15 subcommittee hearings the print states have no counterpart in BILLSTATUS at all** — no action, no code, no wording. The 5 rows it does state come from two bills and both carry `H21000` *Subcommittee Hearings Held*. **Markups are stated in full**: all 8 of them, coded `H15000-B`, `H15001`, `H22000`, filed by the `House committee actions` source system (48 of 197 actions). So for a markup the print is a **second, coded** source, and for a subcommittee hearing it is often the **only** record — which is the narrower claim this table earns its place on.

### Against the hosted `congress_bills` export

The retained `congress_bills` export holds 418,657 bills, Congresses 6 to 119. **958 of the 978** bills these prints attach an action to have a hosted row; 20 do not. Every bill the prints act on is from Congress 118 — **this sample contains no pre-108th bill at all**, so what the print would add before the 108th is not measured here. Of the 4,390 action rows whose bill is hosted, **849** state a rung the hosted row's *latest action alone* already states.

<!-- generated by tools/analysis/bill_action_relationship.py: end -->

## What the print says that BILLSTATUS does not

Two records were compared, and they answer different questions.

**The hosted `congress_bills` export, offline.** It carries
`latest_action_date` and `latest_action_text` — *one* action per bill — so it
can only floor the duplication: a rung the single latest action already states
is certainly duplicated, and one it does not may still sit in the full list.
849 of 4,390 rows (19.3%) are duplicated even against that floor. That is the
safe direction for an argument *against* building and the unsafe one for an
argument for it, which is why it is not the argument this document rests on.

**The publisher's whole action list, 20 keyed requests.** Twenty of the 978
bills, weighted by construction towards hearings and markups because those are
the events the code table says have no House entry. 197 published actions, 76
single-attachment print rows compared. The result is in the generated block
above; the three numbers that matter:

- **10 of 15** subcommittee hearings the print states are absent from
  BILLSTATUS altogether — no action, no code, no wording.
- The **5** it does state come from two bills, both coded `H21000`.
- **8 of 8** markups are stated and coded (`H15000-B`, `H15001`, `H22000`), by
  the `House committee actions` source system, which files 48 of the 197
  actions.

So the print is often the only record of a subcommittee hearing, and a second,
coded source for a markup. Saying both is what makes the first credible.

**What this still cannot see.** Twenty bills is 2% of the sample and the draw
is deliberately not uniform, so these are statements about hearings and markups
and not a corpus-wide duplication rate. Closing that needs one BILLSTATUS
document per sampled bill.

## What is missing, and the measurement that closes each

Five request-free measurements against the same eight retained prints, in the
order their expected yield puts them. Every one re-scores against the 60
hand-checked mentions already in the receipt, so none of them needs new hand
work except where it says so.

1. **Anaphora — the largest single gap.** *"H.R. 1713 was introduced by
   Representative Frank Lucas on March 22, 2023. The bill was referred to the
   Committee on Science, Space, and Technology... which reported the bill, as
   amended, on May 11, 2023."* One row is produced, for the introduction. Bind
   "the bill" / "the measure" / "the resolution" to the nearest preceding
   mention inside the entry window and re-score; the window scaffolding is
   already in `sample` (`ENTRY_WINDOW`). Four of the sample's 60 contexts lose
   three or more actions exactly this way.
2. **List headings.** *"May 17, 2023—Markup held on:"* followed by six bill
   entries: the heading's colon keeps it inside the first entry's sentence, so
   the first bill gets `held_markup` and the other five get nothing. Propagate
   a heading-scoped action to every bill until the next heading.
   `CRPT-118hrpt977:64495` and `:300897` in the receipt's contexts file are the
   two documented failures.
3. **The entry is not a sentence, per committee.** `CRPT-118hrpt968` writes a
   bill's long title as its own sentence and the disposition as the fragment
   after it, which is why it yields 23 rows over 179 MODS-stated bills while
   `CRPT-118hrpt974` yields 1,441. Fall back to the `ENTRY_WINDOW` unit where
   the sentence carries no bill, and re-score on the same 60.
4. **The en-bloc disposition.** *"The measures considered en bloc were ordered
   favorably reported to the House by voice vote."* names no bill; the six are
   listed above it. **This one must be scored on a held-out slice**, not on the
   eight prints its rule would be tuned on — a rule fitted to `CRPT-118hrpt968`'s
   house style and scored on it is a formatting assertion.
5. **Ruled-table column headers.** `CRPT-118hrpt974`'s "Bill No. | Date of
   Committee Consideration | Title" grid states a consideration date for every
   bill in it and no sentence rule can see a column header. Re-run `text` with
   `tables=True` and read the grid. Costs seconds, not requests — the re-check
   measured table detection at 15.0–164.6 ms/page against 9.8 without.

Two gaps are acquisition-gated and stay named as such.

- **The row-for-row `bill_actions` overlap is now partly closed**: 20 keyed
  requests, 20 bills, reported above. It is 20 of 978 bills and weighted
  towards hearings and markups by construction, so it settles the hearing claim
  and does not establish a corpus-wide duplication rate. Closing that needs one
  BILLSTATUS document per sampled bill.
- **The pre-108th case is untestable on anything retained.** Before the 108th
  Congress there is no BILLSTATUS bulk at all (gap A11), so a committee
  activity report may be the only statement of a bill's committee history that
  exists — which would make this table's value much larger than measured here.
  **No CRPT artifact outside the 118th and 119th Congresses is retained
  anywhere in this corpus.** What would establish it: one `published` walk of
  GovInfo's `CRPT` collection with an early `dateIssued` window, which states
  whether the collection reaches earlier Congresses at all and returns package
  ids if it does. That is one keyed request, and it is the cheapest unanswered
  question in this document.

## The five failure shapes, in the print's own words

The hand check's 60 contexts are in the receipt with every verdict. Five shapes
account for almost all of the loss. None is a tuning problem, and each is
sized by one of the measurements above.

**The entry is not a sentence, and every committee sets it differently.** In
`CRPT-118hrpt968` a markup item's long title ends in a period and the
disposition follows as a fragment — *"...and for other purposes. (Green)
(ordered favorably reported to the House, as amended, 26Y–23N)"* — so the bill
and its disposition are two sentences and the second names no bill. **116 of
that print's 125 "ordered favorably reported" occurrences sit in a sentence
naming no bill at all**, which is why it yields 23 rows over 179 MODS-stated
bills, while `CRPT-118hrpt965` — writing the same events as clean
`Legislative History` sentences — yields 1,764 over 282 pages. That is 0.4
rows per page against 6.3, a factor of 15.

**The en-bloc disposition names no bill by design.** *"The measures considered
en bloc were ordered favorably reported to the House by voice vote."* is a
sentence about "the measures", with six bills listed above it as numbered
items.

**The print writes "the bill".** *"H.R. 1713 was introduced by Representative
Frank Lucas on March 22, 2023. The bill was referred to the Committee on
Science, Space, and Technology... which reported the bill, as amended, on May
11, 2023. On December 4, 2023, the bill was considered under suspension of the
rules and agreed to by voice vote."* One row, for the introduction.

**A list heading covers many bills and reaches the first.** *"May 17,
2023—Markup held on:"* then six entries: the colon keeps the heading in the
first entry's sentence, so one bill gets `held_markup` and five get nothing.

**A ruled table states the action in a column header.** `CRPT-118hrpt974`'s
"Bill No. | Date of Committee Consideration | Title" grid states a committee
consideration date for every bill in it, and no sentence rule can see a column
header.

The two classification failures that are not structural are worth naming
because they publish confidently wrong facts: a `Pub. L.` cite inside a bill's
*description* (*"H.R. 6972 amends the Federal Vacancies Reform Act of 1998
(P.L. 105–277)"*) read as the bill becoming that law, and *"reported to
Congress for review"* inside a bill's subject matter read as a committee
reporting it. Both are visible in `matched_text` on the row itself, which is
why that column is published.

**The 1,590 orphan `held_hearing` occurrences are mostly not misses.** A
sample of 25 of them reads as general oversight hearings — hearings on a
subject, not on a measure — and index or table-of-contents lines. The orphan
count is the ceiling on what an entry rule could recover, not an estimate of
what it would.

## Complexity

**20 keyed requests**, all in the `billstatus` phase and bounded there; every
other phase is offline. `text` is linear in retained pages: 1,249 pages of
eight PDFs in about 7 s with table detection off. `measure` is one pass per rule over each
document, `O(K·C)` for `K` = 25 rules and `C` = 3.3 M characters, plus a binary
search per mention into the sentence offsets — about 1 s for the whole corpus.
The overlap is one hash join in DuckDB over a 418,657-row Parquet export.
Nothing here is superlinear in the corpus.

## What this measurement cannot see

- **One Congress.** All 978 bills the prints act on are 118th, so the pre-108th
  question the verdict turns on is untested — see "What would change this
  verdict".
- **The row-for-row comparison covers 20 of 978 bills**, drawn towards
  hearings and markups on purpose. It settles what the print is the only
  source for; it does not establish a corpus-wide duplication rate.
- **Eight prints, eight committees.** The per-print spread is the finding, not
  noise: 23 rows from a complete 56-page print against 1,764 from a 282-page
  one — 0.4 rows per page against 6.3, a factor of 15. A ninth committee's
  house style is unmeasured.
- **60 mentions.** At 40 judged rows the classification rate has roughly a
  ±9-point interval, and the multi-bill attachment cell is 4 rows. The 892
  multi-bill mentions and the 2,952 orphan phrases are corpus-wide counts and
  carry no such uncertainty; they, not the hand-check rates, are what the
  verdict leans on.
- **Dates are extracted, published and never scored.** `print_dates` reads the
  ISO date off each sentence and `bill_committee_actions.stated_date` carries
  the first of them; whether it belongs to *this* action rather than to a
  neighbouring clause was not hand-checked. `stated_date_count` flags the
  sentences where the attribution is least safe. Scoring it is the sixth
  request-free measurement and runs on the same 60 mentions.
- **The phrasing vocabulary is a floor.** A phrasing no rule spells is invisible
  here and makes the print look thinner: *"voted to advance all four pieces of
  legislation"* and *"was not agreed to in the full House vote"* both appear in
  the sample and neither has a rule. That error runs towards the verdict this
  document reaches, which is the direction that deserves the suspicion; the
  orphan count (2,952) and the recall figure (59.6%) both already price it.
