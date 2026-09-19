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
| `bill_stage` | `BillStatus.actions` (or action-text strings) and `BillStatus.laws` | `StageFinding` (stage, rule, matcher, action index and date) and `SignedDateFinding` (date, public law number, rule, action code) |
| `money_bills` | a bill title, its identity, and referral signals from `BillStatus.committees` system codes | `MoneyBillFinding` (kind, subcommittee, fiscal year, rule, reason codes) |
| `bill_signals` | normalized document text and candidate catalog rows | `ExtractedSignals` (with `title_source`) and ranked `BillMatch` records, each signal reported with its weight and score |
| `vote_matching` | `BillAction.recorded_votes`, and House vote `legislationType`/`legislationNumber` | `RecordedVoteReferences` (references plus per-entry refusals), a `VoteIndex` with conflicts, and one `VoteMatch` per vote |
| `release_matching` | committee RSS items (title, and description where a feed sends one) and bill identities | one compiled `BillPattern` per bill, and `ReleaseMatch` naming the field the mention was found in |
| `member_matching` | a bioguide id, a Senate LIS id or a sponsor display string, the legislators crosswalk, and a `MemberIndex` built once from published member rows | `MemberMatch` (bioguide, rule, score) |
| `interest_areas` | a reader's keyword list and parsed bill sections | `SectionMatch` (excerpt, area, matched keywords, rule, relevance) |
| `version_kind` | a bill version's `version_code` slug and, for the size heuristic, its extracted section count or body byte length | `VersionKindFinding` (kind, the rule that fired, section count, body bytes); `version_kind` is a thin wrapper returning just the kind |
| `section_classification` | parsed bill sections and an injected `ModelCall` | `SectionClassification` with model, prompt version, prompt hash, batch and timestamps |
| `bill_summaries` | one bill version's text, title, status and money-bill kind, and an injected `ModelCall`; or, for `summarize_diff`, a section diff's changed items (`op`, both placements' heading and body) and an injected `ModelCall` | `BillSummaryResult` with model, prompt version, content hash, token counts and timestamps; `summarize_diff` produces `DiffSummaryResult` (headline, key changes, sections added/removed, dollar changes) with the same provenance columns |
| `model_call` | — | the one injected model seam (`ModelCall`, `ModelResponse`, `ModelCallError`) the two model-backed modules share |
| `bill_family` | one `BillFamilyCapture` (a `BillStatus` and every acquired printing), plus three injected model seams | twelve tables' worth of rows from `spicy_docs.schemas`, each one already proved against its own contract, and a `FamilyRefusal` for every row it could have produced and did not — see [`tables.md`](tables.md) |

`normalize_for_comparison` and `token_jaccard` live in `bill_signals`, where
their contract is stated, and are imported by `member_matching` and
`interest_areas` rather than copied.

`tools/analysis/audit_bill_identify.py` is the acceptance harness for
`bill_signals`: it reads a CSV of candidate bills and their version text and
prints the per-type extraction tally, including the title-source breakdown and
the bills whose title extraction failed although the catalog holds a short
title.

`bill_stage`, `money_bills` and `vote_matching` read `BillStatus` directly:
`laws`, `committees` and each action's `recorded_votes` were added to
`sources/congress/bill_status.py` in this change, from the publisher's own
guide, so no rule here needs an input the parser cannot produce.

## Corrections carried in the port

These change behaviour deliberately. Each is covered by a test that shows the
old outcome beside the new one.

- **Stage inference reads untruncated action text.** The source truncated the
  status to 100 characters before inferring, although the column held 500.
- **One signing-date derivation.** The bill's `laws` entry establishes that it
  became law; the action whose `actionCode` is the publisher's became-public-law
  code supplies the date. Neither of the two disagreeing keyword scans survives,
  and a law without a coded action is reported as such rather than guessed at.
  Measured 2026-09-19 over the 118th Congress's `hr` and `s` BILLSTATUS bulk
  zips (16,213 members, none refused): 269 bills carry a `laws` entry, and all
  269 carry the coded became-law action -- none carries `type == "BecameLaw"`
  without the code, and none hits the `public_law_without_became_law_action`
  fallback. The fallback rule stays regardless, both because it is cheaper
  than assuming every future bill's action will be coded and because the
  measurement covers two bill types of one Congress, not `hjres`/`sjres` or
  every Congress. The receipt -- script, command, both zips' sha256 digests
  and the full output -- is retained outside this repository at
  `~/Work/corpora/supply-2026-09-02/receipts/signed-date-fallback-118th-2026-09-19/`.
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
  committee names. This narrows the signal on purpose: an appropriations
  *sub*committee raised it before and does not now.
- **Classifications carry provenance.** Model and prompt version are recorded,
  which the source's classification table did not hold.
- **The stage fold takes the latest classified action**, not the furthest rung,
  because `STAGES` is a display order that disagrees with rule precedence.
  Enactment is the one terminal rung.
- **One bad recorded vote costs that entry, not the bill.** Refusals are
  returned beside the references rather than raised over the whole action list.

The prompts and their `PROMPT_VERSION` are sealed together, down to the
typography: the em and en dashes the source wrote are pinned by a `sha256`
test, because a prompt that changes silently makes every stored row
unattributable.

## What these rules cannot see

`interest_areas` now encodes the InnoDB boolean-mode defaults BillTrax's
`MySQL 8.4` ran under, measured from its `docker-compose*.yml` files (every
one that defines a `mysql` service -- `docker-compose.yml.example`,
`docker-compose.prod.yml`, `docker-compose.staging.yml` -- pins `mysql:8.4`
and none overrides the full-text variables; `docker-compose.test.yml`
defines no `mysql` service) against the MySQL 8.4
Reference Manual: a token shorter than `innodb_ft_min_token_size` (3) or
longer than `innodb_ft_max_token_size` (84), or one of the 35 distinct words
in the default `INNODB_FT_DEFAULT_STOPWORD` table (36 rows; the manual's own
example output lists "the" twice), is dropped from both a keyword and a body
before matching -- see
[`fulltext-fine-tuning.html`](https://dev.mysql.com/doc/refman/8.4/en/fulltext-fine-tuning.html)
and
[`information-schema-innodb-ft-default-stopword-table.html`](https://dev.mysql.com/doc/refman/8.4/en/information-schema-innodb-ft-default-stopword-table.html).
Results are ordered by relevance -- the count of distinct matched keywords,
then the section's position -- which is the documented boolean-mode formula
(sum of matched terms' weights) with each term weighted 1, because a pure
per-call function has no corpus-wide document frequency to weight it
properly; see
[`fulltext-boolean.html`](https://dev.mysql.com/doc/refman/8.4/en/fulltext-boolean.html).
That page also states boolean-mode results are **not** sorted by relevance
automatically, and BillTrax's own query carried no `ORDER BY`, so BillTrax's
rows arrived in storage order, not relevance order. This module's ordering is
therefore a rule it adopts, not a reproduction of an order BillTrax's rows
ever actually carried; no live comparison of the two orders has been run (see
`docs/research/billtrax-value-inventory-2026-09-19.md` §7 Q5).

`STAGES` is display order, not progress order, and `stage_index` and
`stage_progress` answer only "where does this rung get drawn". They cannot say
which of two stages is further along: `referred` maps to `other_chamber`,
which is drawn after `committee` and `passed_chamber` although every bill's
introduction is a referral. `infer_stage` therefore folds by recency, not by
rung.

`release_matching` cannot tell a bill mentioned in passing from the bill a
release is about; it reports the first bill named and which field named it, so
a consumer can weigh a title match differently from a body one.

## Decision

See ["Interpretation lives in spicy-docs; hosted tables carry its
outputs"](decisions.md#interpretation-lives-in-spicy-docs-hosted-tables-carry-its-outputs)
in `docs/decisions.md`.
