# Proposal: close the known gaps as one spicy-docs program

Status: in execution, 2026-09-19 evening; see §2.0 for per-row state
(written against spicy-docs `main` at v0.21.1
plus docs (5,425 tests), spicy-regs fork branch `billtrax-hosting-prep`
(1,433 tests, 46 hosted tables), and the day's measurements; both trees
have moved since -- each row's status below is the live record). It answers the
GovernmentXML proposal (an external draft dated the same day, not in this
repository) by folding its sound parts into this repository
and replacing its corpus choice with what the census measured. Every gap
below names its evidence, its fix, the measurement that proves the fix, and
the home it lands in: spicy-docs (ingestion, parsing, shared logic),
spicy-regs (hosted tables), upstream (`civictechdc/DeltaTrack`), or the
user (calls only they can make). Nothing here is a commitment until it has a
`docs/decisions.md` record.

## 0. The principle

**Retrieve, then reconstruct, then interpret; never in the other order.** A
body is taken in the publisher's most structured rendition (XML, then HTML,
then text, then PDF as the last resort; measured and sealed 2026-09-19).
Reconstruction runs only where retrieval has nothing structured to give, and
its output is a derivative that says so on every row. Interpretation runs
over facts and findings, names its rule, and never rewrites text. A gap is
closed only by a measurement, and a measurement that could not fail is not a
measurement.

## 1. Where the stack stands

Measured on 2026-09-19 unless stated:

- **Acquisition**: Congress.gov list routes (a route table), GovInfo bodies by
  package id (CRPT, CHRG, CDOC, CDIR, CREC, BILLS) with identity proved before
  bytes, BILLSTATUS bulk zips with a listing-based unchanged skip, USLM laws
  and compilations, press releases, House Clerk and Senate LIS votes, the
  legislators crosswalk, CRS, GAO, CBO, the Court, the Federal Register, CFR
  and eCFR, the Unified Agenda, the U.S. Code, FEC, LDA, SAM, USAspending,
  CourtListener, FCC ECFS, regulations.gov.
- **Parsing**: the bill tree and section diff as adapters over the pinned
  DeltaTrack package, the sealed version-code vocabulary (72 entries, 24
  measured in the 119th), GPO PDF text normalization derived on PyMuPDF and
  measured against upstream's pypdfium2 pipeline, one `body_text` per
  rendition, the agency report-block parser.
- **Interpretation**: stage, money bills, signals, vote, release and member
  matching, section classification, bill and diff summaries with prompts
  sealed by digest, all pure, all naming their rule.
- **Hosting**: 22 contracts over 407 columns in `schemas/`, the bill family
  in one pass, activity events from snapshot comparison, six spicy-regs
  rollups incremental where the source allows, a data dictionary reading its
  column prose from the installed contract.
- **Bodies**: 8 source families are PDF-only in practice, 7 are PDF-primary
  with a text alternative now preferred, the rest are structured or
  metadata-only ([census](pdf-only-corpus-2026-09-19.md)).

## 2. The gap register

### 2.0 Execution status (maintained; updated as each branch merges or stalls)

| # | Status, 2026-09-19 evening |
|---|---|
| A1, A2, A3 | Landed on spicy-regs `billtrax-hosting-prep` (merge 1f18898), twice reviewed. The linkage receipt corrected the hearing figures to 10 hearings with mentions in 31 entries; the load-bearing 12-of-12 report agreement and 0-of-52 PRIMARY hearings held throughout. The `press_releases` NULL-match exposure is a documented residual, not a refusal. |
| A4 | Landed in spicy-docs: the Senate LIS vote-menu index (`VoteAcquirer.list_senate_votes`, `parse_senate_vote_menu`, `locator_from_menu_entry`). |
| A5, A7, A10 | The route table they sit on landed at 1f515bb (three review rounds). The contracts landed after review (APPROVE; two prose nits applied): `house_communications`, `committee_meetings`, `record_issues`, `treaties`, `nominations`, `hearing_transcripts.event_id`, `interpretation/communication_rin.py` -- 27 tables over 516 columns. All six flagged decisions upheld; the disclosed limits (18 of 25 sampled, one hearing/meeting pair, cross-chamber uniqueness unmeasured) are stated in the docs. Receipts: an 18-detail RIN sample (18 dated referrals, 12 rulemakings, the same 12 with a RIN) and a 2-request meeting-edges run (hearing 64431 <-> meeting 119003, jackets both ways). `senate_communications` deliberately omitted: the Senate detail lacks the bridge's fields. The Federal Register `rin` join column is spicy-regs rollup work; no acquisition-policy change was needed. |
| A6 | Measured and landed with the map merge: the 370-page walk histograms all 92,450 requirement communications at roughly a 29 percent detail-era share, under the stated 50 percent useful-share threshold, so `house_requirements` is not hosted; the histogram and the detail floor are written into the map. |
| A8, A9 | In progress: builder branch `worktree-agent-a95d88c5a12a6e7de`, resumed after an API outage killed it mid-measurement. |
| A11 | In progress: spicy-regs branch `hosting-a11-backfill` (worktree `spicy-regs-wt-a11`), resumed after the same outage. |
| A12, A13, E4, E5 | Built and reviewed APPROVE on branch `worktree-agent-ad19194ecd76ab500` (every `have` row verified against live `LIST_ROUTES`, `check_evidence` hardened so a `have` row must name a real route and a defined symbol, the weekly live-publisher workflow, the README index test); landed on main. |
| B1 | Sized: the held-out measurement merged at 8c0e023 -- section recovery 100/100 out of sample, quoted-block macro recall 83 percent (the one fitted rule), 141 requests with a retained receipt. The reconstruction pilot (§3) finished its review fix round on `reconstruction-pilot` (rules frozen at da96d21, then re-fetched and re-scored at the same 40 granules with all 84 requests logged: text 99.93/99.96, hierarchy F1 1.0000, acceptance 78 percent, the critical-discrepancy check now able to see en-dash numbers); verification review in progress. |
| B2, B7, A10 (the CPRT row), the ModsBill accessor | Fix round complete on `worktree-agent-acc262b1a0cfd2cdd`, review in progress. The decision record landed; the USLM proof was re-derived and measured: the census's apparent ten entries are 5 BILLS packages (hconres11 double-pinned under enr and rds; three more bills multi-pinned; the other 4 entries are PLAW collection packages outside B7's scope), all five fetched live and parsed, roots measured on two bill types (`<bill>` and `<resolution>`). Both receipts written with the not-retained-log statement. |
| B3 | Landed: the CRS HTML rendition is preferred for the current version, with the preference structural rather than a passed-arg convention (merge 4e9ab7c). |
| B5 | Landed: `TableObservation` in the evidence model, opt-in via `tables=True` (merge 1477d84). |
| B6 | Landed: the 42-document corpus validation (merge b16c77c); two `_layout_verdict` false negatives fixed; the widened rule's blast radius pinned by a multi-page test. |
| C1, C4 | Not started. |
| C2, C3 | Landed, with post-merge review fixes: real receipts for both measurements, the fabricated 40,260-row claim rewritten, the Federal Register locator claim actually asserted and its inputs pinned. |
| C5 | Closed as no-change: the HTML rendition removed the measured defect. |
| D1, D4 | Open. |
| D2 | Landed (SR01: the bill reader walks spicy-docs's listing route). |
| D3 | Waiting on the user: re-vendor after the fork merges upstream. |
| D5 | Closed by plan: acceptable; measured when D1 runs. |
| E1, E2 | Open; the user files the upstream issues. |
| E3 | Measured, not gated: `ty check` on main finds 1,139 errors (553 invalid-argument-type, 517 unresolved-attribute, then a thin tail; 1 unresolved-import), so gating now would fail the tree; the cleanup is scoped for after the in-flight branches merge, and spicy-regs already gates it. |
| Releases | spicy-docs 0.21.2 owed once the in-flight branches merge; spicy-regs adoption follows. |

### A. Joins the data map measured and nothing drives

The [legislative data map](legislative-data-map-2026-09-18.md) resolved 51
of 55 edges on real items. These are the ones with no consumer.

| # | Gap | Evidence | Fix | Proof | Home |
|---|---|---|---|---|---|
| A1 | `press_releases.bill_id` is NULL though `release_matching` exists | spicy-regs `build_press_releases.py:15` | The transform reads the current `congress_bills` identities (one prior download it already makes) and calls `match_releases` with one compiled pattern per bill | Fixture run: the House feed's items that name a bill match; `matched_field` is `title` on the Senate feed | spicy-regs |
| A2 | `committee_reports.bill_id` and `hearing_transcripts.bill_id` are NULL | `build_committee_reports.py:18`; the map's `report→bill` edge resolved 17 of 17 via `associatedBill[]`, `hearing→meeting→bill` 6 of 6 | The committee-report and hearing list routes (already in `listing.py`) supply the linkage; the transform indexes packages by the stem the route's format URL states and fills `bill_id` from `associatedBill` and from `relatedItems.bills` | Fixture pages from the two routes; every CRPT row for the 119th sample gets a bill or a named refusal | spicy-regs |
| A3 | `recordedVotes` on bill actions is not a second vote linkage | `build_roll_call_votes.py:17-21`; the map resolved `bill→house-vote` 5 of 5 and `bill→senate-xml` by url | The family rollup already holds every bill's actions; it emits the `(bill_id, chamber, congress, session, roll)` references as a fifteenth family output, and the votes rollup joins on them at merge time, so no rollup reads another's output | The 58-entry measured sample resolves 34 distinct roll calls to bills | spicy-regs |
| A4 | Senate roll calls have no index route | Congress.gov has `house-vote` only; the Senate LIS `vote_menu_{c}_{s}.xml` serves the session's list (measured: 101st onward, 149 KB) | `sources/congress/votes.py` gains `list_senate_votes(congress, session)` over the menu file, keyless, identity proved from its own congress and session; the votes rollup walks it newest first with the same held-set skip | Fixture menu; the first vote of the 119th resolves to `vote_119_1_00001.xml` already fixtured | spicy-docs, then spicy-regs |
| A5 | The regulatory bridge is acquired and unconsumed | House communications carry `isRulemaking`, CRA authority, committee referral with system code, matching requirement and the RIN in `reportNature` (17 of 25 sampled are rulemakings); the RIN resolves in the Federal Register API | **spicy-docs side landed 2026-09-19**: the `house_communications` contract in `schemas/congress_index_tables.py` (27 columns: every typed detail field, the referral's system code and date, `is_rulemaking`, the cited `legal_authority`, the matching requirement, and `rin`/`rin_rule`/`rin_matched_text` from the measured `RIN: nnnn-XXnn` rule in `interpretation/communication_rin.py`). The Federal Register side needs no acquisition change: the source record already carries `regulation_id_numbers` and `schemas/federal_register.py` publishes `regulation_id_numbers_json`, so the `rin` join is spicy-regs rollup work. No `senate_communications`: the Senate detail carries none of the bridge's fields (module docstring). Still open: the spicy-regs rollup and join | Fixture EC 4752 with its list row through the generic loop; re-measured on 18 of the 25 newest inside the day's 20-request budget: 18 of 18 carry a dated referral, 12 are rulemakings and the same 12 carry a RIN under the measured rule and under a relaxed FR-shaped rule, 15 name a requirement (`corpora/supply-2026-09-02/receipts/house-communications-rin-2026-09-19/`; `tests/test_congress_index_tables.py`) | spicy-docs contract, spicy-regs rollup |
| A6 | The requirement route is a count, not an index | Requirement 8070 lists 92,450 communications unordered by Congress; a full walk is 370 pages, about five minutes; detail records exist only from the 114th | Run the two bounded measurements the map names: walk the list once and histogram by Congress; probe one detail per Congress from the 105th to pin the floor. Host `house_requirements` (3,226 rows, a 2021 snapshot) only if the histogram shows the detail era covers a useful share | The histogram and the floor, written into the map | spicy-docs measurement first |
| A7 | Meetings, hearings and documents chain unhosted | `committee-meeting` (111th+, 18,133) links `eventId → hearing jacket → CHRG package` and `relatedItems.bills`; `witnessDocuments[].url` resolve | **spicy-docs side landed 2026-09-19**: the `committee_meetings` contract keyed `(congress, chamber, event_id)` with `hearing_jacket` beside `hearing_jackets_json` (the captured hearing's meeting names two jackets), `bill_ids_json`, `document_urls_json` and every typed detail field; `hearing_transcripts` gained `event_id`, appended last; a `hearing-detail` route in `listing.py` supplies it from `associatedMeeting.eventId`. Still open: the spicy-regs rollup | `hearing→meeting` and `meeting→hearing` re-run on the captured pair (jacket 64431 ↔ event 119003, each way), `meeting→bill` 9 of 9 on the captured markup 119565, `record→package` by the hearing's own `formats[].url` stem, all in `tests/test_congress_index_tables.py`; the pair cost two keyed requests (`corpora/supply-2026-09-02/receipts/committee-meetings-edges-2026-09-19/`). The map's 4 of 4 and 6 of 6 were live samples; the fixtures hold one pair and one markup | spicy-docs contract, spicy-regs rollup |
| A8 | Enacted-law list, Statutes at Large, OLRC tables unused | `law/{c}` is the cheap enumeration (108 rows for the 119th); PLAW USLM states `NNN Stat. NNN`; STATUTE bulk reaches volume 137; Table III and the classification tables resolve from the law number | `laws` contract keyed by `(congress, law_type, number)` from `law/{c}` plus the PLAW package id and the citation from its USLM `meta`; `statutes_at_large_cite` on `congress_bills` stops being a preserved NULL; OLRC classification rows as `law_code_sections` (law number, title, section, action) from the per-Congress table | The 119th's 108 laws: 104 in PLAW bulk, 4 lagging, as measured; Table III page states act, Congress and volume back | spicy-docs contract, spicy-regs rollup |
| A9 | Rosters: committees and members from the API, assignments from the chamber files | `committee` (818, from the 53rd) and `member` (2,696, from the 68th) are API-first; the map's comparison found the chamber files add only committee assignments and the LIS id | `committees` and `committee_assignments` contracts: the API for identity and history, `MemberData.xml` and `cvc_member_data.xml` for current assignments, keyed by system code and bioguide; the legislators JSON stays the LIS crosswalk | Comparison rerun: API 555 vs files 541 for the 119th, the 14 API-only all with ended terms | spicy-docs sources and contracts, spicy-regs rollup |
| A10 | Treaties, committee prints, the daily Record index, nominations feeds | `treaty` (786) resolves to CDOC; CPRT (7,784) is not in the body grammar; `daily-congressional-record` is the legislative-day calendar (sections per issue name the chamber); nomination feeds are a keyless status cross-check | **Contracts landed 2026-09-19** in `schemas/congress_index_tables.py`: `record_issues` keyed `(volume, issue)`, its `chambers` derived from the detail's section names as the calendar and its `package_id` from the whole-issue link's stem; `treaties` keyed `(congress_received, number, suffix)` with `package_id` by the `CDOC-{c}tdoc{n}` rule on an unpartitioned treaty; `nominations` keyed `(congress, citation)` over the list route. Feeds stay a cross-check with no contract. The CPRT row is on its own branch (`worktree-agent-acc262b1a0cfd2cdd`). Still open: the spicy-regs rollups | `record→legislative-day` on issue 172/148 (a Senate-only day) and `record→package` (`CREC-2026-09-18`), `treaty→cdoc` on 119-2 → `CDOC-119tdoc2`, on fixtures in `tests/test_congress_index_tables.py`; every contract through the generic loop from captured list pages and details | spicy-docs, spicy-regs |
| A11 | Bills before the 108th have no bulk status | BILLSTATUS bulk is 108–119; the API bill list reaches the 82nd | The family rollup's backfill for older Congresses walks the `bill` list route by Congress under the same per-run cap and builds status from the detail route; the contract is unchanged | One older Congress walked end to end, counts against the route's declared total | spicy-regs |
| A12 | The map document is stale about what landed | Rows for bill PDFs, press releases, report parsing, both vote XML files and the two matching rows still read `port` or `candidate` or `rejected (here)` | Update `ROWS` in `tools/analysis/legislative_data_map.py` to `have` with the module paths; regenerate with `--offline`; the fixture test then proves every `have` row names a file that exists | `uv run --frozen pytest -q tests/test_legislative_data_map_tool.py` | spicy-docs |
| A13 | Floors the walk stopped short of | Committee prints populated again at the 94th, treaties at the 81st, committees below the 60th cap | Raise the walk caps for those three routes and re-run `--floors` | The regenerated floors | spicy-docs |

### B. Bodies and extraction

| # | Gap | Evidence | Fix | Proof | Home |
|---|---|---|---|---|---|
| B1 | Bills before the 113th have no XML, so no section tree and no diff (sized by the [HTML-to-XML gap measurement](bill-html-xml-gap-2026-09-19.md), 2026-09-19) | [Census](pdf-only-corpus-2026-09-19.md): 2005-era and 1990s-era bills offer `htm` and `pdf` only; the BILLS API reaches 1993 | Reconstruction (§3): the HTML rendition into the bill DTD that DeltaTrack parses, so ten Congresses gain sections and diffs | The paired benchmark: hide the XML of 113th-era bills, reconstruct from their HTML, compare | spicy-docs |
| B2 | The daily Record is PDF-only at package level | CREC packages state `pdf` only; the granules have HTML | Body acquisition takes a granule id (the grammar already accepts the split-day suffix) and prefers the granule's HTML; the package PDF stays the fallback | One issue's granules fetched and parsed; the package PDF path exercised once | spicy-docs |
| B3 | CRS HTML answers 403 to a plain client while the API states it | Measured live 2026-09-19 | Measure once whether the publisher's stated `formats[]` HTML answers with the same headers the CRS file route already uses; if it does, HTML becomes the preferred rendition for CRS; if not, record the refusal as the publisher's and keep the PDF | The measurement, in `docs/sources/crs-files.md` | spicy-docs |
| B4 | CBO estimates sit behind a bot wall; the Court, disclosure sites and activity reports are PDF-only with no target vocabulary | Census; the map's `rejected` rows | No change: extraction into the evidence model only; no schema target exists and the proposal's non-goals exclude forcing one | None needed | none |
| B5 | Table geometry and reading order are not retained | `extraction/model.py` keeps `raw` (PyMuPDF's full dict) but no table structure; the CRPT measurement showed PyMuPDF emits every label then every amount | Add a `TableObservation` to the evidence model built from PyMuPDF's `find_tables` on the retained page, kept beside the text, never merged into it; measure against the HTML's 841 intact rows on CRPT-113srpt77 | Row-recovery rate on the two appropriations reports whose HTML is the reference | spicy-docs |
| B6 | The GPO normalizer is validated on four fixtures and synthetic cases | The below-floor run test's residual false-positive shape is stated, not measured | A corpus run: forty GPO bill PDFs across print stages and Congresses through the integration path, with the layout verdict and rejoin counts pinned per document, the way upstream validated its floor on sixty | The pinned table in `docs/extraction-gpo.md` | spicy-docs |
| B7 | The USLM bill rendition is recognized but not acquirable | `PACKAGE_BODY_FORMATS` is htm, xml, txt, pdf; 10 of 240 sampled version entries stated USLM | Add the `uslm` rendition (folder `uslm/{id}.xml`) to the grammar and the sealed order after `xml` (it is a second structured rendition); measure on the ten | The ten fetched and parsed by `uslm.py`'s grammar | spicy-docs |
| B8 | Extraction backends beyond native text are unqualified for this corpus | `docs/extraction/pdf-extraction-choices.md`: OCR and vision candidates measured on forms, not on legislative print | Scope OCR to the one corpus that needs it, pre-XML scans (CFR and Federal Register editions before their XML era), and only when a consumer asks; the born-digital program needs none | Deferred until a corpus asks | spicy-docs |

### C. Interpretation

| # | Gap | Evidence | Fix | Proof | Home |
|---|---|---|---|---|---|
| C1 | The model-backed modules have never run live | `classify_sections`, `summarize_bill`, `summarize_diff` are wired behind `GEMINI_API_KEY` and exercised only with stubs | One bounded live run over one fixture bill through `extraction/gemini`'s client adapter, recording model, prompt digest, tokens and cost; the coverage statements then say "measured" | The run's provenance rows in the model tables; cost per bill stated | spicy-regs run, spicy-docs adapter |
| C2 | `interest_areas` cannot reproduce MySQL boolean-mode search | `docs/interpretation.md`: the token-length floor, the stopword list and the relevance order are unreproduced | Measure BillTrax's engine defaults (InnoDB minimum token length 3, its stopword list, its relevance formula) against the pure implementation on the fixtures; either encode them as a named rule or state the divergence on the finding | A parametrized test over the measured cases | spicy-docs |
| C3 | The signed-date fallback rule's frequency is unmeasured | `public_law_without_became_law_action` exists so a fallback need can be counted | Count it over one Congress's enacted bills from bulk status | The count, in the module docstring | spicy-docs |
| C4 | The bill-signals audit harness has no run | `tools/analysis/audit_bill_identify.py` reads a candidates CSV nobody has produced | Export the candidates from one family run and run the tally; compare with BillTrax's reported rates | The tally in the research folder | spicy-docs |
| C5 | Report-block headers on all-caps title-page sentences | Documented limit on the parser page | Leave as is; the HTML rendition removed the hyphen-wrap fragments, which were the measured defect | None | none |

### D. Hosting

| # | Gap | Evidence | Fix | Proof | Home |
|---|---|---|---|---|---|
| D1 | Coverage statements say "Sampled, and accumulating" with no full run measured | Every rollup is stubbed in tests; no production run has happened | One measured run per rollup on the fork branch against real publishers, under the stated caps, recording rows, requests, wall time and refusals; `measured_on` set from it | The dictionary's coverage statements carry the numbers | spicy-regs |
| D2 | SR01: spicy-regs's hand-rolled `congress_bills` reader still exists beside `listing.py` | spicy-regs `PLAN.md`; the narrow writer keeps the frozen ten-column prefix | Retire the reader in favour of the bill list route with the same window logic; the coalesce merge already protects the family's columns | The 21 existing tests plus the end-to-end merge test stay green | spicy-regs |
| D3 | spicysearch vendors a 24-table catalog | Measured: `01c77a4a…` vs the fork's `d08822d8…`; now 46 tables | Re-vendor after the spicy-regs branch merges upstream | spicysearch's receiver tests | user, then spicysearch |
| D4 | `hearing_transcripts` is exercised only by a synthetic record | Contract tests | Capture one small CHRG package's HTML body as a fixture with provenance | The generic contract loop runs on it | spicy-docs |
| D5 | The family rollup re-walks eight archives per run | The listing skip removes the download, not the walk; each unchanged archive still costs one listing read | Acceptable: eight small reads. Measure a night's request count in D1 and stop here unless it exceeds the cap | D1's numbers | none unless measured |

### E. Upstream and tooling

| # | Gap | Evidence | Fix | Proof | Home |
|---|---|---|---|---|---|
| E1 | Seven validated DeltaTrack gaps are unfiled | [Issue list](deltatrack-upstream-issues-2026-09-19.md): A1 collision-group cap (8.74 s for 300 same-path sections), A4 hyphen-tolerant tokens, A6+A7 version keyword and a parsed-tree entry, A8 the XML path imports pypdfium2, B1 the DSK-literal regex, B4 and B5 the two hyphen mechanisms | File them as same-org issues in priority order with the bodies as written; A6+A7 also removes the temp file and second parse in `bill_tree.py` | Issue numbers recorded in the doc; the pin moves when a fix lands | user files; spicy-docs tracks |
| E2 | DeltaTrack is pinned by git sha; the gate fetches GitHub on a cold cache; spicy-regs vendors a locally built wheel | `pyproject.toml`; `docs/sources/congress-bill-tree.md` | Ask upstream for a tagged release and a PyPI publish (one more issue); move both pins to it | The pin line changes once | user, upstream |
| E3 | `ty check` is configured but not gated in spicy-docs; spicy-regs carries one pre-existing diagnostic | `scripts/check` runs ruff and pytest only | Add `uv run --frozen ty check` to `scripts/check` once clean; fix the spicy-regs diagnostic | The gate | spicy-docs, spicy-regs |
| E4 | Integration tests never run on a schedule, so publisher drift is found by accident | A pinned Federal Register day's replay now fails on a digest mismatch, found while doing other work | A weekly workflow running `-m integration` against the live publishers and filing the drift as a report, never a failure of the default gate; triage the FR day now | The first weekly report | spicy-docs |
| E5 | The docs index is maintained by hand | Five index lines added today by hand | A test that every `docs/sources/*.md` and top-level guide is linked from `docs/README.md` | The test | spicy-docs |

## 3. Reconstruction: GovernmentXML as a spicy-docs subpackage

The external proposal's architecture is right and about half of it is
already here. The resolver is this repository's acquisition layer; the
evidence layer is `extraction/` with `raw` retained; the rule discipline is
the interpretation package's contract; DocSpec is a sibling. What does not
exist is the profile, the structural parser, the serializer, schema
validation, the benchmark and the review report. Those become
`src/spicy_docs/reconstruction/`, behind a `reconstruct` extra (lxml for
DTD and XSD validation; nothing else in core), for these reasons: the
resolver and the evidence model are not rebuilt, one release train carries
it to spicy-regs, and the split stays intact (spicy-docs parses, spicy-regs
hosts the derivative rows with `derivation = reconstructed` on every one).

### 3.1 The corpus decision

The external draft picks annual CFR first because it has a guide and XML.
That makes it a paired benchmark only: every edition GovInfo serves has XML,
so reconstructing it is the experiment the draft itself calls "not the
primary production use case". The census found the PDF-only remainder is
reports and opinions with no target vocabulary. The one family with a real
corpus, a real target and a text rendition to reconstruct from is **bill
text from the 103rd to the 112th Congress**: HTML and PDF only, ten
Congresses, the bill DTD as target, DeltaTrack as the consumer, and section
diffs across versions as the outcome nobody has today.

So: CFR stays the controlled benchmark (hide the XML, reconstruct, compare,
blind splits grouped by edition), and pre-113th bills are the deployment
corpus and the second profile. Reconstruction reads the **HTML rendition**,
not the PDF, wherever it exists; the CRPT measurement (PDF text splits about
1,870 words per report and keeps no account rows where the HTML keeps 841)
is the reason, and it is the retrieve-first principle applied one level
down.

### 3.2 Modules

| Module | Responsibility | Reuses |
|---|---|---|
| `reconstruction/profiles/` | One versioned profile per family: `cfr` (GPO CFR XML guide, pinned DTD), `bill_dtd` (xml.house.gov bill DTD, the version the 113th-era files declare). A profile is a frozen record: applicability rule, schema bundle digests, interpretation rules as a table, serializer, validation rules, fixture references. Three rule kinds kept distinct: schema requirement, guide convention, project heuristic | `interpretation/`'s rule-table shape |
| `reconstruction/evidence.py` | The evidence-linked document model: blocks with spans, page or line coordinates, style observations, `TableObservation` (B5), reading-order candidates; unresolved regions survive with an issue attached | `extraction/model.py`, `body_text` |
| `reconstruction/parse.py` | Deterministic structural parsing: numbering, indentation, typography and context jointly propose the tree; every node carries `evidence_refs` and a `decision` naming the rule; where rules cannot decide, a bounded `classify_and_attach` model call chooses between evidence-backed alternatives with abstention, never rewriting text | `interpretation/model_call.py`, `extraction/gemini` |
| `reconstruction/serialize.py` | Deterministic XML in the target vocabulary from the document model; a sidecar source map from XML paths to evidence; no custom attributes in the official vocabulary; generated ids marked as generated | `sources/xml.py` conventions |
| `reconstruction/validate.py` | Five checks, each a separate finding: schema validity (lxml against the pinned bundle, catalog-resolved, no network), content fidelity (normalized text equality with the reversible normalization stated), structural fidelity (boundaries, hierarchy, footnote attachment), coverage (every region classified), acceptance gates | `gpo_normalize`'s record shape for counts |
| `reconstruction/review.py` | An HTML report: PDF or HTML page beside the tree, node to evidence; issues listed; no editor until error analysis asks for one | none |
| `tools/analysis/reconstruction_benchmark.py` | The paired corpus builder and scorer: development, tuning and blind splits grouped by edition; text precision and recall, hierarchy F1, critical-discrepancy count, acceptance coverage, cost per accepted document | `tools/analysis/legislative_data_map.py`'s evidence discipline |

### 3.3 Gates

Engineering targets, not results: all accepted XML passes its pinned
schema; text precision and recall at or above 99.9% on born-digital
material with the normalization stated; hierarchy F1 at or above 0.98 on
supported structures; no unresolved change to a number, date, negation or
provision marker in accepted output; every region accounted for; at least
70% acceptance without review in the declared slice; cost per accepted
document reported. A hundred clean documents still permit a 3% error rate
at a one-sided 95% bound, so the audit grows with the claim.

### 3.4 What reconstruction does not do

It does not promise byte recovery of lost XML, does not carry GovInfo's
signature onto derived files (the original is retained separately), does not
interpret legal effect or consolidate amendments, does not force reports into
a legislative schema, does not OCR scans in the pilot, and does not take
private documents.

## 4. Waves and gates

| Wave | Scope | Gate to pass |
|---|---|---|
| **1. Joins and hygiene** (days) | A1, A2, A3, A4, A12, A13, D4, E3, E5; triage E4's Federal Register drift | The four linkage columns non-NULL on fixtures; the map regenerated with every landed row `have`; the Senate index fixture parsed |
| **2. The rest of the map** (a week) | A5, A7, A8, A9, A10, A11, B2, B7, then A6's two measurements | Each new contract with a fixture record through the generic loop; the regulatory bridge answering `communication ↔ rule` on the fixture; the histogram deciding the requirements table |
| **3. Reconstruction pilot** (six to eight engineering weeks, one engineer, a part-time reviewer) | §3: the CFR benchmark first, then the `bill_dtd` profile on pre-113th HTML, B5's table observations alongside | The blind-split numbers against §3.3; ten Congresses of sections and diffs hosted with `derivation = reconstructed` |
| **4. Measured operation** (ongoing) | D1, C1, C2, C3, C4, B6, B3, D2 | Coverage statements carrying real numbers; model tables with provenance rows; the normalizer's corpus table |
| **Standing** | E1, E2 (user files; pins move when upstream ships), D3 (after the upstream merge), releases 0.21.x to 0.22 with each wave, the spicy-regs pull request when the user names the branch | Issue numbers in the doc; pins on a release; the catalog re-vendored |

Order within a wave follows value per request: everything in wave 1 needs
no new publisher and no new credential.

## 5. What stays out

BillTrax itself (external; its delete column is a record, not work). HTML
scraping of the sites the map rejected. A universal PDF-to-XML converter or
"supply any XSD". OCR of scans until a consumer names the corpus. Any push
to the upstream spicy-regs origin without the user naming the branch.
Licensing as a selection criterion: the user ruled results only, and the
PyMuPDF pipeline stays because it measured best.

## 6. Verification

Every check through the project's own runner, never a bare binary:

```sh
# spicy-docs
./scripts/check
uv run --frozen python -m tools.analysis.legislative_data_map --offline \
  --output docs/research/legislative-data-map-2026-09-18.json \
  --map docs/research/legislative-data-map-2026-09-18.md
uv run --frozen pytest -q -m integration   # weekly, reported not gated

# spicy-regs, fork branch
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen spicy-regs-dict check
uv run --frozen spicy-regs-dict generate && git status --short docs/tables data_dictionary
```
