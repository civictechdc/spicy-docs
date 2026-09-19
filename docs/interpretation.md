# Interpretation

`spicy_docs.interpretation` holds the shared logic that reads publisher facts
and decides something about them. Acquisition and publisher-format parsing stay
in `spicy_docs.sources`; the tables these rules populate are hosted elsewhere.
Every module is pure: no network, no database, no clock except an injected one.
Inputs are this repository's own dataclasses or plain mappings shaped like the
published tables, and every output is a frozen record naming the rule that fired
and the identifiers it fired on, so a hosted row can carry its own provenance.

Rules are data. Each module states its vocabulary as a tuple of frozen rule
records read in order, so a vocabulary has one home and the order is readable
rather than buried in control flow.

## Modules

| Module | Consumes | Produces |
| --- | --- | --- |
| `bill_stage` | `BillAction` records, action-text strings, a bill's `laws` entries | `StageFinding` (stage, rule, matcher, action index and date) and `SignedDateFinding` (date, public law number, rule, action code) |
| `money_bills` | a bill title, its identity, and referral signals from the six committee system codes | `MoneyBillFinding` (kind, subcommittee, fiscal year, rule, reason codes) |
| `bill_signals` | normalized document text and candidate catalog rows | `ExtractedSignals` (with `title_source`) and ranked `BillMatch` records, each signal reported with its weight and score |
| `vote_matching` | `recordedVotes` on bill actions, and House vote `legislationType`/`legislationNumber` | `VoteReference`, a `VoteIndex` with conflicts, and one `VoteMatch` per vote |
| `release_matching` | committee RSS items (title, and description where a feed sends one) and bill identities | one compiled `BillPattern` per bill, and `ReleaseMatch` naming the field the mention was found in |
| `member_matching` | a bioguide id, a Senate LIS id or a sponsor display string, the legislators crosswalk, published member rows | `MemberMatch` (bioguide, rule, score) |
| `interest_areas` | a reader's keyword list and parsed bill sections | `SectionMatch` (excerpt, area, matched keywords, rule) |
| `section_classification` | parsed bill sections and an injected `ModelCall` | `SectionClassification` with model, prompt version, prompt hash, batch and timestamps |
| `bill_summaries` | one bill version's text, title, status and money-bill kind, and an injected `ModelCall` | `BillSummaryResult` with model, prompt version, content hash, token counts and timestamps |
| `model_call` | — | the one injected model seam (`ModelCall`, `ModelResponse`, `ModelCallError`) the two model-backed modules share |

`normalize_for_comparison` and `token_jaccard` live in `bill_signals`, where
their contract is stated, and are imported by `member_matching` and
`interest_areas` rather than copied.

`tools/analysis/audit_bill_identify.py` is the acceptance harness for
`bill_signals`: it reads a CSV of candidate bills and their version text and
prints the per-type extraction tally, including the title-source breakdown and
the bills whose title extraction failed although the catalog holds a short
title.

## Corrections carried in the port

These change behaviour deliberately. Each is covered by a test that shows the
old outcome beside the new one.

- **Stage inference reads untruncated action text.** The source truncated the
  status to 100 characters before inferring, although the column held 500.
- **One signing-date derivation.** The bill's `laws` entry establishes that it
  became law; the action whose `actionCode` is the publisher's became-public-law
  code supplies the date. Neither of the two disagreeing keyword scans survives,
  and a law without a coded action is reported as such rather than guessed at.
- **Vote matching reads structured references.** The regex over vote question
  text could not match any Senate bill. `recordedVotes` on the bill's own action
  is the join, and the House vote route states the legislation in two fields.
- **Release matching compiles one pattern per bill, once**, built from that
  bill's own type with the number escaped and bounded. The source rebuilt a
  pattern per (release, bill) pair and offered the bare number as an
  alternative, so bill 1 matched any `1`. Matching runs field by field, title
  first, and reports which field matched, because one of the two feeds sends no
  description at all.
- **Member matching prefers identifiers.** Bioguide, then LIS through the
  crosswalk, then the name; the name path strips the bracketed
  party/state/district block and reads the surname before the comma, and always
  exposes its score.
- **Committee referrals come from system codes**, not from substring matching on
  committee names.
- **Classifications carry provenance.** Model and prompt version are recorded,
  which the source's classification table did not hold.

## What these rules cannot see

`interest_areas` reproduces the decision in the original MySQL boolean-mode
query -- a section matches when it holds any keyword token -- and reproduces
neither the engine's minimum token length, its stopword list nor its relevance
order. Comparing the two on real data is a measurement still owed, not an
assumption made here.

`bill_stage.signed_date` reads `laws` from a mapping because `BillStatus` does
not yet parse the BILLSTATUS `<laws>` element. Nothing changes here when it
does.

## Decision

**Interpretation lives in spicy-docs; the tables it produces are hosted
elsewhere.** spicy-docs is the one home for code: acquisition, publisher-format
parsing and shared interpretation alike. A metadata host receives tables and
their documentation, never logic, and an application keeps only auth, email,
per-user rows and pages. This package is the interpretation half of that split,
and the columns each rule populates -- stage, money-bill kind and reason codes,
identification confidence, vote and release bill links, classification and
summary provenance -- are what the host publishes.
