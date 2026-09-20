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
| `model_call` | — | the one injected model seam (`ModelCall`, `ModelResponse`, `ModelCallError`) the two model-backed modules share, and the `AnswerField` declaration each prompt, each reader and each request schema (`answer_schema`) is derived from |
| `gemini_call` | a `GenerationClient` (`extraction/gemini`'s `GeminiClient`, or a stub) | that client as a `ModelCall`: it builds the request, sends the caller's `response_schema` as `responseJsonSchema`, parses the answer and carries the publisher's token counts |
| `citations` | one document's normalized text, its per-page split where the rendition has one, the Congress its own index record states, and the chamber-roster vocabulary the caller already parsed | one `CitationFinding` per occurrence (kind, rule version, canonical target key, whether the key is the hosted target's own spelling, the matched text, the character span, and the printed page) |
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

- **A prompt states the JSON shape its reader parses, and so does the
  request.** Each model-backed module declares its answer's keys, types and
  enforced counts once as `AnswerField` records (`model_call.py`); the prompt's
  key list, the reader's lookups and — since 2026-09-20 — the draft 2020-12
  schema the request carries (`answer_schema`, sent as `responseJsonSchema`)
  all come from that one declaration, so the request and the contract cannot
  drift apart. `v1` left the spelling to the model and the summary prompt named
  no key at all; the port had also dropped the schema BillTrax passed on every
  one of these three requests. The reader's refusal stays the contract: a
  provider may accept a schema and answer around it.
- **A refused model answer is a refusal, not an aborted bill.** `bill_family`
  runs the three generators inside the same guard its shapers run inside, so a
  `ModelCallError` becomes a `FamilyRefusal` naming the model's own reason and
  the pass finishes. A credential refusal and a transport failure still abort.

The prompts and their `PROMPT_VERSION` are sealed together, down to the
typography: the em and en dashes the source wrote are pinned by a `sha256`
test, because a prompt that changes silently makes every stored row
unattributable. A version is per prompt, so the constants may sit apart: the
two summary prompts are at `v2` (2026-09-19) and the classification prompt at
`v3` (2026-09-20, one field's wording). Two of the three — the diff-summary and
classification prompts — are **no longer byte-identical to their BillTrax
sources**, deliberately: the originals enforced their key set with a schema on
the request, which the port did not carry over, so reproducing their bytes
alone reproduces a prompt that is refused on arrival. See the decision.

## What the model-backed modules have actually been run against

Until 2026-09-19 `summarize_bill`, `classify_sections` and `summarize_diff` had
only ever been exercised with stubs — and every stub answered with the keys the
reader wanted, which is why nothing offline could see what the first live call
saw. Four runs of `gemini-3.8-flash` over this repository's own fixtures now
stand behind them, receipts (model, prompt digest, tokens, cost, parsed rows)
under `~/Work/corpora/supply-2026-09-02/receipts/` in
`d1-measured-run-2026-09-19/`, `c1-prompt-fix-2026-09-19/`,
`c1-classification-2026-09-20/` and `c1-classification-v3-2026-09-20/`. The
first three each found something no stub could: a stub that answers the way its
reader reads is a formatting assertion, not a measurement. All three modules
now produce live rows.

| | Coverage |
| --- | --- |
| `summarize_bill` | **Measured live, refused under `v1`, read under `v2`.** The first call (119 HR 6028, 204 in / 206 out) answered with `most_affected_audience` and `notable_provisions` where the reader requires `audience` and `topThreeProvisions`, so it was refused — a keyed production run would have published **zero** `bill_summaries` rows. The spelling was not even stable across invocations of the identical prompt: that receipt's README tabulates `affected_audience` from another one, and both refuse identically. The same bill under `v2` (250 in / 197 out, USD 0.00057 at the pinned rate) is read into a row carrying its audience, three provisions and full provenance. |
| `summarize_diff` | **Measured live under `v2`**: all five keys returned, one `diff_summaries` row, over the constructed division fixtures — 119 HR 6028's own two printings settle as entirely unchanged, so the family declines that pair before asking. What a live diff of two *published* printings returns is still unmeasured. |
| `classify_sections` | **Measured live, refused under `v2`, read under `v3`.** Asked again on 2026-09-20 with the answer's schema on the request (`c1-classification-2026-09-20/`, same batch, byte-identical prompt digest `6add710c…`, 263 in / 80 out, one keyed call): the answer honoured the schema in every respect it constrains — bare array, three rows, three keys and no others, a sealed label, a confidence in range — and the batch guard refused it again, because **the model returned each section id with the prompt's own square brackets around it** (`[introduced-in-house\|govinfo\|0]`). `section_block` writes `[<id>] <heading>` — BillTrax's own line — and the `v2` field asked for "the section's bracketed id, copied exactly as given below", so copying exactly included the brackets while `_read_row` requires the bare id. **A keyed run under `v2` publishes zero `section_classifications` rows.** `v3` rewords that one field ("the text inside the square brackets below, without the brackets") and nothing else, and is proved live: two identical keyed calls (`c1-classification-v3-2026-09-20/`, prompt digest `411e9f67…`, 534 in / 200 out, USD 0.00066) each answered in the batch's own ids and each stored **three rows**, under `prompt_version` `v3`, with no refusal. The `v2` answer is retained as a committed fixture and a test, so the wording cannot quietly regress. Label *quality* is unmeasured. |

See the decision ["A prompt states the JSON shape its reader
parses"](decisions.md#a-prompt-states-the-json-shape-its-reader-parses-from-one-declaration).

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

`citations` reads what a document *prints*, which is a narrower thing than
what it cites. It cannot see a cite the print spells in a form no measured
rule covers, it attributes a match straddling a page break to the page it
began on, and its `committee_name` rule is a **candidate** finder: the target
key is a `system_code` only where the roster vocabulary the caller supplied
settles the printed name, and an unsettled candidate is reported unsettled
rather than guessed at. A bill key needs a Congress the print never writes, so
the caller supplies its index record's; with none, the finding keeps the
printed form and says the key is not the catalog's. Sixteen rules exist and
nine are stored: `bioguide_id` measured zero across ten families because no
publisher prints one, and `dollar_amount` and `fiscal_year` are quantities
with no target. Finally, a span is only meaningful against the exact text it
was measured in, which is why every row carries that text's digest.

## Decision

See ["Interpretation lives in spicy-docs; hosted tables carry its
outputs"](decisions.md#interpretation-lives-in-spicy-docs-hosted-tables-carry-its-outputs)
in `docs/decisions.md`.
