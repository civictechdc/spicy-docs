# Remaining data and delivery gaps — 2026-09-21

The next work is to publish corrected, explicitly scoped data; repair the
remaining demonstrated conversion defects; and qualify joins and interpretations
before using them for counts, money, status or affiliation claims. Adding more
table names is not the priority.

This is the consolidated backlog for SpicyDocs, SpicyRegs, Rulespec and RefSpec.
It incorporates the validation sprint, subsequent repairs, FEC continuation and
the fork's Cloudflare setup. It documents known gaps; it is not a new census of
every publisher or a claim that all data is accurate. “Open” includes missing
evidence, incomplete coverage and delivery work, as well as demonstrated bugs.

## Evidence and how to read status

The [70-table, 20-source-family scorecard](data-validation-tables-2026-09-21.md)
remains the exhaustive inventory for the initial sprint. Its 67 declared tables
plus three additional outputs describe that dated snapshot. The later host
dictionary has 71 declarations, including four FEC delivery tables. Those counts
describe different inventories, not 71 verified public datasets.

The detailed [legislative](data-validation-legislative-2026-09-21.md),
[regulatory](data-validation-regulatory-2026-09-21.md) and
[other-source](data-validation-other-2026-09-21.md) reports retain each output's
conversion, completeness, shape, usefulness, sample and raw evidence. The
[remediation record](data-remediation-sprint-2026-09-21.md),
[first implementation wave](remaining-gaps-wave1-2026-09-21.md) and maintained
[execution register](closing-the-gaps-2026-09-19.md#20-execution-status-maintained-updated-as-each-branch-merges-or-stalls)
supersede their initial bug statuses. The table-level limitations remain open
unless a later receipt explicitly closes them. Local and old-host artifacts do
not establish availability in the new Cloudflare account.

Priorities below mean **P1: protect correctness or enable a useful validated
release**, **P2: extend useful coverage**, and **conditional: pursue when that
consumer or hosting path is selected**. They are recommendations, not new
acquisition authorizations or deadlines. Each item names a completion check so
that “implemented,” “measured,” “published” and “deployed” stay distinguishable.

## Repairs already established; remaining adoption

| Finding | Established result | Remaining work |
| --- | --- | --- |
| H10 cosponsor counts | Corrected provider and installed host preserve the separate native cosponsor list. The 16,213-bill 118th HR/S candidate passes 1,189,950 named native-field comparisons. | SR01: qualify wider native cohorts and publish a coherent generation. Counts include withdrawn entries, not just active cosponsors. |
| H6 stale print/Senate/report reads | Successful-read checkpoints now include the relevant source/rule versions; successful empty rereads replace old findings, failures retain prior rows. | SR01/SR06: rebuild selected old outputs and demonstrate production correction coverage. |
| H11 CFR suffixes; H12 Federal Register identity | Lettered part tokens survive. Number-plus-date identity preserves the two distinct `00-111` records and downstream dated joins. | SR01/SD01: public regeneration and historical repair; the separate CFR hierarchy/selection defects remain. |
| H13 court body variants | Versioned output retains all eight native text variants. A new bounded original prefix gives 2,272 exact field comparisons across 284 records. | SR01/SR10: rebuild the selected population; the old 250,000-row file is not repaired by this sample. A positive native `xml_scan` witness remains absent. |
| Report headings | Literal headings survive; unresolved agency identities remain NULL. | SD04: segmentation limits and any actual agency resolver need separate qualification; SR01: public adoption. |
| H14 regulatory fields; F1 RIN sets | Retained repair restores fields despite equal publisher timestamps. Proceedings/comment periods use complete usable RIN sets. Direct replay: 10,969 comparisons, no mismatches, four newer priors preserved. | SR01/SR03: wider backfill, body acquisition and public/cross-source join qualification. |
| H7/H8 publication mechanics | Complete Parquet families undergo Rulespec verification, full decode and byte/count checks before a conditional pointer change. Actual R2 success, interrupted/concurrent writes, multipart retry and browser requests are checked. | SR01/SR02: real-source adoption and non-family/partitioned/Iceberg paths. This does not validate source completeness or semantic accuracy. |
| H3 six supposedly missing derived tables | All six were found nonempty on the prior public host. | Keep their declarations. Qualify their parents and calculations; do not withdraw them to reconcile an incorrect local inventory. |
| F2/F2b, F10/F11, G1/G2/G5/G6 | Shared Mirrulations refusal/recovery adoption, strict finite JSON, digest-equality semantics, reversible capture encoding, bounded Senate table preservation and installed Rulespec validator adoption are complete in their measured scopes. | SD07/SR04/RS01–RS02: provenance, logical types, mixed-rule inputs and wider extraction evidence. Do not reopen the repaired mechanisms from older prose. |
| H16 lobbying failure became data | SpicyRegs `7551f63` rejects failed, malformed and incomplete pages. Independent review reproduced old false-empty and false-partial publication paths; 63 focused and 2,107 full tests pass. Two live pages produce three records with all 42 cells checked. | SR07: initial backfill is unqualified. The bad zero-row family was withdrawn and the schedule is paused. |

## SpicyDocs — source conversion, interpretation and evidence

Use the existing source readers, refusal/resume support, raw captures and named
rules. Shared schema/verification additions belong in Rulespec; reference and
agency identity resolution belongs in RefSpec. The gaps below do not call for
new copies of those capabilities.

| ID / priority | Remaining gap and practical consequence | Next action and completion check |
| --- | --- | --- |
| **SD01 · P1 · joint SpicyRegs ownership** CFR hierarchy and selection | Suffix loss is fixed in the host, but the native fixture places section `19-8.1` in Part `241`; SpicyRegs `build_cfr_sections.py` infers Part `19`. SpicyDocs `EcfrSelection` rejects lettered part requests. Native readers already distinguish annual cover year, printed revision and cover-only editions. | SpicyDocs must allow source-supported selection and expose native ancestry; SpicyRegs must repair its inference and retain edition facts. Reproduce both counterexamples and compare native ancestry. A suffix-only regression does not close hierarchy or body extraction. [Regulatory evidence](data-validation-regulatory-2026-09-21.md#cfr-part-identifiers-are-truncated). |
| **SD02 · P1** Activity/action association and dates (H9/F4) | One rendered page omits H.R. 209/H.R. 3883, repeats action rows and attaches a printed-hearing locator across a date block. Single-bill precision was only 30/36 (83.3%); it is not a trust category. | Repair date/list boundaries, blank-number/footnote handling and locator-as-action confusion. Score an independently labeled held-out set with declared precision/recall and date criteria. Retain anaphora, list headings, committee entry grain, en-bloc wording and table headers as named cases. Wider bill-action overlap and pre-108th CRPT coverage remain unmeasured. [Witness](data-validation-legislative-2026-09-21.md#activity-rules-miss-bills-and-attach-evidence-across-hearing-blocks). |
| **SD03 · P1** Source-native location and nested identities | Meeting `119569` loses its full off-site address. Four committee codes occur only in nested arrays and lack identity rows. | Preserve the location variant and minimally evidenced child identities or explicit unresolved references; never invent absent detail. Reconcile all 240 unique source committee codes and the actual address witness. Host adoption is SR05. |
| **SD04 · P1** Interpretation quality (F4, C4/C5) | Inferred stages, signed dates, classifications, summaries, diff summaries, financial changes and agency assignments lack adequate held-out qualification. Live model rows prove output shape only. All-caps title-page segmentation remains a documented parser limit. | Declare acceptance thresholds and independent gold samples before model/rule changes. Measure source-supported claims, per-label errors, abstentions, dates/units and incorrect block boundaries. Run the existing bill-signals candidate audit. Preserve model/rule/input provenance; assess paid partial-answer loss at batch refusal separately. C2 search behavior and C3 fallback-frequency measurement are already complete. |
| **SD05 · P1** Citation recall and evidence | The budget witness contains five references to 31 USC 1106; three are found. Reverse wording is missed. Normalized targets do not preserve every original spelling or prove a correct cross-source join. | Add the demonstrated patterns with exact source spans/spellings; measure held-out precision/recall and resolution separately. Keep `target_resolved` distinct from an observed hosted target. [Citation witness](data-validation-legislative-2026-09-21.md#citation-findings-are-useful-but-incomplete-budget-amounts-are-not-hosted). |
| **SD06 · P1** Logical values (H1) | All-VARCHAR Parquet is deliberate. Logical dates/numbers/booleans remain insufficiently declared/validated; source dates can be malformed or less precise than a day. | Declare source-specific logical meanings and validate casts with named anomaly outcomes while preserving literals. Retain month precision rather than silently treating day `00` as day one. Test source year `0000` and numeric/boolean counterexamples. Typed consumer views belong to SR04; no blanket storage migration is required. |
| **SD07 · P1** Capture v2 adoption and missing evidence (G3/G4) | Rulespec's opt-in v2 is implemented, but converter/profile adoption and package release are separate. Two timestamps, three MODS records and six Senate cell boxes remain missing; CFR original PDF/acquisition time are unavailable or unproven. | Adopt the shared v2 fields through real converters and owner validators; preserve all old content and explicit missing findings. Acquire missing evidence where obtainable. Do not fabricate timestamps/geometry or promote a derived PDF digest into original-source proof. RS01/RS02 own shared requirements. |
| **SD08 · P2** Historical/body coverage (B1, F3/F5, D4) | Pre-113th HTML-to-bill reconstruction is not rolled out; amendments remain largely metadata-only; historical STATUTE bodies and law identity links remain absent. The generic hearing fixture uses CRPT bytes under a CHRG identity. | Finish the bounded `bill_dtd` reconstruction benchmark with explicit derivation, actual amendment/body routes and historical law mapping. Replace the mismatched hearing fixture with a retained native CHRG body. Reconcile keys, body outcomes and refusals, not just counts. The CFR reconstruction pilot, CREC granule acquisition and BILLS USLM support are already implemented. |
| **SD09 · P2** Executive communications reconstruction (A6) | Parser/overlap scoring landed, but the historical acquisition run, split-part granule case, Congress-wide contiguity and committee-name resolver remain open. The official/agency split failed its declared threshold and remains NULL. | Run a detached, resumable bounded acquisition from retained progress; inspect `CREC-2004-06-16-pt2-PgH4285`, reconcile sequence gaps and use RefSpec identity evidence for committee resolution. Retain native text and provenance; do not publish the failed official/agency split. |
| **SD10 · P2** Fiscal detail (F6/F7) | Senate ruled cells do not yet establish payment/payee, compensation/mail or whole-report coverage. House disbursement CSV is unacquired. Budget and CBO indexes/letters do not provide qualified numeric costs. | Qualify payment blocks and whole-report sections; acquire selected House periods with provenance. For numeric extraction, retain row/column, units, fiscal period, signs and footnotes; reconcile totals to the publisher. Keep file/index coverage distinct from amount extraction. |
| **SD11 · P2** CRS and related document provenance (F8) | CRS appended runs lack sufficient immutable run/input attribution; HTML/combined routes lack new independent source/output qualification. GAO and Supreme Court file checks establish complete selected files, not extracted text. | Add run/time/input pins and resume-across-input-version proof. Qualify exact selected HTML/PDF versions and revision links; join body observations to metadata without overwriting version identity. Current CRS HTML preference itself is implemented. |
| **SD12 · P2** Other native-source qualification | FOIA XML trees need version/namespace/unit definitions for comparable metrics; selected Oversight links/recommendations do not qualify all layouts or PDF bodies. CBO's four feeds are checked, standalone content is not. U.S. Code annual/appended/status text, Popular Names and reference routes lack complete output qualification. | Use the [source-by-source matrix](data-validation-tables-2026-09-21.md) to name a bounded route/edition and consumer question, then retain raw/output pairs and reconcile fields. Preserve NULL vs empty, literal ranges, edition/status notes and source precision. A zero-byte Title 53 capture is a failure, not an empty title. |
| **SD13 · P2** Long-term correction/route reliability | Successful selected captures do not establish complete pagination or stable publisher access. Per-request retry ceilings are not total-run request budgets. Package-only budget routes can expose no body while a granule does. | Measure bounded retries/resume and actual request totals; use publisher-stated rendition/granule routes, expected success shape and per-row failure state. Broader direct Regulations.gov/FCC attachments, GovInfo metadata/PREMIS and alternative bill renditions need route-specific evidence. Preserve missing PREMIS fixity. |
| **SD14 · P2** Upstream and quality gates (E1/E2/E3) | DeltaTrack issue filing/release packaging and SpicyDocs type-check cleanup remain tracked work. The source gate still omits `ty`; the old 1,139-error count is historical, not a fresh count. | Record upstream issue IDs and adopted tagged/package versions when available; remeasure current type failures, fix them, then add the gate. Check the host's optional `embed` dependencies separately. Weekly live-publisher reporting, map floors and docs-index checks (A12/A13/E4/E5) already exist. |

## SpicyRegs — coherent outputs, joins and publication

| ID / priority | Remaining gap and practical consequence | Next action and completion check |
| --- | --- | --- |
| **SR01 · P1** Corrected real generations (H4/H6/H10–H14) | Code/package adoption and local replays have advanced beyond public data. The corrected 118th HR/S five-table cohort, broad local bills and earlier public ten-column bills differ in scope. Native wider inputs, including the named 119th archive cohort, have not all been located/qualified. | Select and declare each release's source population. Rebuild bills and affected print/report, CFR, FR, court and regulatory outputs from pinned inputs; compare native keys/fields, parent-child keys and intended changes. Publish and verify the exact family in the new bucket. Preserve wider unread coverage explicitly; never silently substitute the 118th parent set for 119th children. |
| **SR02 · P1** Publication beyond managed Parquet families (H7/H8) | Family admission works; base regulations.gov, partitioned comments, Iceberg and the legacy docket-search derivative have different publication paths. Their consistency/correction behavior is not established by the family rehearsal. | Define and verify complete snapshot/partition membership, parent versions and failure/retry behavior for each chosen path. Decode real outputs and verify public readers select one intended generation. Keep declaration, attempted run, local output and public availability separate. |
| **SR03 · P1** Regulatory joins and analytic grain (F1/H15) | Full RIN arrays are retained locally, but historical/public backfill and cross-source identity joins remain incomplete. Lifecycle grouping collapses 48 proposals into 19 unknown-docket agency groups and excludes 647 other proposal groups; 5,132 is a different, wider denominator. | Retain participating document IDs and unresolved links/outcomes. Qualify proposal/final pairing before status/duration claims; compare all usable RINs and dated FR identities. Reconcile literal docket spellings with explicit mapping evidence. Exact array expansion alone does not qualify legal-matter identity. |
| **SR04 · P1** Safe analytic views and derived snapshots (H1) | Type casts and temporal aggregates lack explicit invalid-value/as-of handling. `discovery_signals` has no pinned 30-day window; separately observed parents can disagree. | Add source-defined typed views and named anomaly handling. Pin parents and observation/window times for agency counts, monthly volume, feed summaries and discovery ratios. Recompute by stable keys; preserve the 2,020 unparseable-date observations separately from valid calendar groups. |
| **SR05 · P1** Existing legislative joins (A2/A3/A4/A7/D4) | Code exists for report and plural hearing links, but the inspected hearing-link output is empty. Bill vote references cover the 118th while inspected votes cover 119th House only. Senate indexing exists in SpicyDocs but host use remains open. | Produce matched Congress/session bill-action/vote cohorts, host the Senate index, and build hearing→meeting/agenda→bill links with reverse-edge and per-row identity checks. Compare every link to native statements; retain missing event IDs, ambiguous sets and unresolved children. Acquire the COVER census by chamber/Congress and original bill-side action evidence before claiming its confirmation rates are replayable. |
| **SR06 · P1** Corrections beyond the current window (F9) | Recent overlaps do not recover old vote/court/FR corrections or older Congresses after a calendar rollover. Local stale-print repair does not establish all scheduled repair paths. | Retain publisher modification signals where offered; add bounded historical refresh and cross-Congress overlap. Demonstrate a held older record corrected after unchanged/recent discovery, with successful empty replacement and failed-read retention. Measure a second full D1 pass for held/unchanged skips. |
| **SR07 · P1** LDA initial backfill and useful activity shape (H16) | The failed-query publication bug is fixed. The corrected request advertised 1,977,046 filings, about 79,082 pages at 25; three checked records do not qualify a full seed within the 30-minute job. Flattened agencies omit activity→agency→lobbyist relationships; money/amendment meanings are unqualified. | Keep the schedule paused until a bounded, resumable seed reconciles page/key counts, preserves source dates and survives interruption. Examine the observed 1905/1940 posted dates on 1999/2000 filings before choosing catch-up windows. Publish only the declared validated scope. For issue/agency research, preserve nested activity relationships and filing-type/amendment semantics. |
| **SR08 · P1** Empty, undeclared and partially read outputs (H2/H5) | The initial profile has nine empty tables: `section_diffs`, `section_diff_items`, `financial_changes`, `section_classifications`, `bill_summaries`, `diff_summaries`, `hearing_bill_links`, `bill_family_backfills`, `bill_family_backfill_walks`. `bill_subjects` has local rows but no established public declaration/adoption. | Record input scope, capture/processing outcome and publication independently per table. Produce qualified examples only where useful; otherwise label unsupported/unproduced. Declare and validate `bill_subjects` before publication or keep it explicitly local. Preserve rows outside named cohorts rather than treating NULL/unread as publisher absence. |
| **SR09 · P1** SAM/USAspending observation and aggregation | Same-generation source extracts are missing for the inspected public comparisons. SAM description fields contain codes and expired rows still say Active. Recipient ID, not UEI, is the spending grain; 32,497 UEIs repeat. | Retain the producing extract, source codes/descriptions, observation date, amount period and recipient level. Reconcile actual source amounts at that grain. The 100,954 matched recipient rows support linkage, not a safe total across duplicated UEIs. |
| **SR10 · P2** Court scope, participants and source witnesses | Body representation is fixed locally, but old cluster/body outputs lack a coherent complete rebuild. Discovery is nature-of-suit 899, participants lose source IDs, and filing-date windows miss older corrections. | Retain original cluster/docket pairs and selected all-variant body inputs, preserve participant IDs, label query scope, and validate court/jurisdiction joins. Demonstrate selected historical refresh. Do not claim the bounded body prefix validates the old 10-million-row cluster population. |
| **SR11 · P2** Useful regulatory fields/body retrieval | Current retained mappings preserve many fields missing publicly. Further host selections omit document `cfrPart`/topics/abstracts, Agenda deadlines/related RINs/comment URLs/date precision, FCC topics/modification/type codes and FR XML locators/topics. Public metadata is much broader than acquired/extracted bodies. | Select fields for actual retrieval/join questions, preserve native structures and source-stated XML URLs, and version the output shape. Backfill from existing retained sources before new acquisition. Report attachment descriptions, downloaded bodies and extracted text separately. |
| **SR12 · P2** Comments completeness | The inspected index totals 23,888,128 comments, 1,533 below the independently observed monolith footer. Only three public row groups were profiled; a full partition census is absent. | Capture one coherent partition/index generation, reconcile exact keys/counts and parent versions, and account for failures/deletions. A date-mixed difference is not automatically a conversion defect. Source-table conservation does not establish publisher completeness. |
| **SR13 · P2** Research metadata and affiliation | GAO recent RSS, CRS current listings, court searches and FEC committee snapshots are narrower than their source archives. `org_committee_links.high` is a name-matching category without measured affiliation precision. | Join versioned native product/body/relationship evidence to the host. Preserve observed vs default/empty fields, dates and source scope. Challenge affiliation candidates using source-stated FEC identities; qualify accuracy before presenting candidates as facts. |
| **SR14 · P2** Historical legislative coverage | Old bill backfill plumbing does not establish a complete older Congress. Current assignments do not establish historical seats/parties. Law/Code and Table III joins need release-aware ranges/status; treaty/nominations/Record rows remain metadata in selected scopes. | Reconcile one older Congress to publisher totals; retain complete member source revisions and date-aware terms; test law/Code release identity and literal ranges. Treat historical hearing, press, treaty, nomination and Record details/bodies as separately bounded coverage tasks. |
| **SR15 · P1** FEC delivery and consumer adoption | Four locally pinned tables now work through CLI and MCP; this is a selected source generation, not full FEC history or an external public release. | Use the FEC backlog below for missing source coverage; publish an explicitly selected verified generation and repeat the real CLI/MCP query against its public pins. Re-vendor downstream catalogs only after checking current recipient pins (D3); this sprint does not verify SpicySearch's present adoption. |

## FEC — source-owner and host follow-through

The current owner records are SpicyRegs
[`docs/fec-gaps.md` (FG01–FG24)](../../../spicy-regs/docs/fec-gaps.md) and
[`fec-coverage-2026-09-21.md`](../../../spicy-regs/docs/research/fec-coverage-2026-09-21.md),
which reconcile every broad source family, bulk group and delivered output.
The condensed tasks below support cross-repository planning; the FG register
owns the detailed FEC queue. Earlier measurement records are
[`fec-generation-readiness-2026-09-21.md`](../../../spicy-regs/docs/research/fec-generation-readiness-2026-09-21.md),
[`fec-bulk-continuation-2026-09-21.md`](../../../spicy-regs/docs/research/fec-bulk-continuation-2026-09-21.md)
and [`fec-senate-recovery-2026-09-21.md`](../../../spicy-regs/docs/research/fec-senate-recovery-2026-09-21.md).
They supersede earlier selected-file counts without erasing their scopes.
The complete reconciliation and source-table pins are retained in
[`remaining-fec-gaps.md`](/Users/mikewolfd/Work/corpora/fork-cloudflare-2026-09-21/remaining-fec-gaps.md).

| ID / owner | Remaining gap | Completion check |
| --- | --- | --- |
| **FEC01 · SpicyDocs, P1** | The retained historical research PostgreSQL dump has no shared source reader. Its 262,276 rows, 73 fields and 76,277 committee IDs cover cycles 1976–2022; a 2026 archive capture is not 2026 data. Arrays may carry later information into earlier-cycle rows. | Read retained COPY data without executing dump SQL. Preserve original dump/table/row/decoded-stream provenance, NULL/empty/escape distinctions and historical semantics. Reconcile all rows/fields; do not apply the current API relationship mapper to historical arrays. |
| **FEC02 · SpicyDocs/SpicyRegs, P2** | Selected coverage of all 26 bulk groups is not complete historical/cycle coverage or record expansion. The 32,034,987-row `indiv26` main file remains file/member inventory; main/by-date byte counts are not equivalence or dedup proof. | Name cycle/file coverage and missing families, expand the selected individual stream with restart/count/byte proofs when needed, and qualify main/by-date equivalence independently. Keep historical acquisition gaps visible. |
| **FEC03 · SpicyDocs/SpicyRegs, P1** | Operating-expense source rows have 26 positions against a 25-column official header; slot 25 is populated in 411,233 rows and slot 26 is empty. Insert/delete streams and amendments are separate observations, not current totals. | Preserve positional data while resolving field-label evidence. Qualify amendment/transaction identity and correction rules before financial totals; source width disagreement must not be hidden by shifting columns. |
| **FEC04 · SpicyDocs/SpicyRegs, P2** | Senate recovery is selected originals and mirror evidence, not a reconciled full filing inventory. Legal audit/ADR/MUR complete-query success, additional financial/detail routes and historical generations remain unevenly qualified. | Reconcile source-listed expected filings with live, mirror, missing and refused outcomes; retain exact bytes and source basis. For each unvalidated route, retain a complete bounded native query plus actual outputs and field comparisons. Recheck the latest coverage matrix before acquiring duplicate originals. |
| **FEC05 · SpicyRegs, P1** | Current local CLI/MCP delivery is checked for 13,717,161 source records, 649 collections, 183,390 relationship observations and 26 catalog entries. This does not prove every catalog family has selected collections or every relationship is a positive/current affiliation. | Reconcile catalog→collection→record coverage, publish the declared scope, verify source pins and explicit blank/unresolved/identity states, and distinguish relationship observation counts from affirmative edges. Public FEC deployment is SR15. |
| **FEC06 · SpicyDocs/SpicyRegs, P2** | A direct join finds selected collections for 17 of 26 broader catalog families. Nine have none: `fec_access`, `fec_loans_debts`, `fec_party_allocation`, `fec_public_funding`, `fec_results_calendar`, `fec_legal`, `fec_guidance_meetings`, `fec_agency_reports`, `fec_oig`. These are different categories from the 26 bulk groups. | Reuse retained originals before acquiring missing source/period/route populations. Reconcile complete query/list membership and separately promised linked bodies. Zero collections in this delivery does not mean no originals exist elsewhere. |
| **FEC07 · SpicyDocs/SpicyRegs, P2** | Retained files remain outside the selected manifest: 2026 candidate/committee masters, linkage/summary/leadership counterparts; presidential size/ZIP exports; additional communication-cost, electioneering and independent-expenditure cycles; electronic daily and additional paper selections. | Declare exact file/period membership and integrate through existing readers with complete stream/count/field proofs. Six selected summary members, the 2026 intercommittee member and all-period lobbyist/bundling snapshots are already represented; do not reacquire them merely because an older report says missing. |
| **FEC08 · SpicyDocs, P2** | Senate discovery stops at 1,000 objects; continuation/search fail. The selected 599 originals comprise 598 live files and one mirror. All 479 listed `.fec` files were acquired, while 478 `.sql` and 42 `.img` objects remain inventory-only. | Establish an independently supported population denominator and reconcile expected/live/mirror/missing/refused outcomes. Qualify formats promised for delivery. Repeated first pages do not prove terminal discovery; an unsent publisher issue draft is not a filed issue. |
| **FEC09 · SpicyDocs/SpicyRegs, P1** | Fifteen files with legacy or differently spelled Senate headers remain unmapped. All 64 mapped `SEN-` references resolve within the selected set, while four `FEC-` references remain distinct; no interpreted Senate relationships were emitted. `48.fec` retains a native-parser refusal and 19 literal lines. | Qualify version-specific fields/reference namespaces, explicit unresolved states and any separately labeled mirror delivery. Preserve malformed originals; never silently repair bytes to manufacture a successful native parse. |
| **FEC10 · SpicyDocs/SpicyRegs, P1** | Retained-query and transport checks do not establish fresh complete API traversals or repeatable public refresh. | Verify current access and declared scope, then retain terminal membership, interruption/resume, correction and failure-preservation evidence plus public freshness. An earlier missing-credential observation is not a claim about today's credentials. |

The FEC register additionally tracks queryable publisher/source authority, caller discovery context, refusal and
mapping-status context; an explicit bulk-group selection map; raw evidence
currently retained locally rather than delivered with generation-bound public
access; provider release identities; and original-body/search adoption. The
`members.fec_ids_json` → `bioguide_id` → `member_votes` bridge already exists;
qualification of the combined selected data/query remains open. These are
delivery and evidence gaps, not a request to rebuild the existing bridge.

**Fresh operational evidence:** the scheduled [FEC committee run on
`43c06b6`](https://github.com/mikewolfd/spicy-regs/actions/runs/35645971109)
failed on September 21 before acquisition because its API key was absent.
The shared workflow supplies this source from `DATA_GOV_API_KEY`. This makes
credential configuration a currently observed FEC10/OPS07 blocker, beyond the
older reports' unverified credential state. Failure refusal worked; this run
does not establish publisher absence or a valid new generation. The raw failed
log is retained as `fec-committees-workflow-failure.log` under the fork receipt
root. Configure the required scoped source credential and repeat a bounded
complete acquisition before claiming schedule readiness.

## Rulespec — shared capture and artifact requirements

The owner is [`docs/document-capture-v2-provenance.md`](../../../rulespec/docs/document-capture-v2-provenance.md).
V2 is opt-in; v1 bytes/defaults remain unchanged. Independent preservation
covers seven captures, 934 nodes and 2,444 spans, not the truth of extraction.

| ID / priority | Remaining gap | Completion check |
| --- | --- | --- |
| **RS01 · P1** Capture v2 adoption/release | Shared source records, original/derived relationships, effective coordinates and rule/converter bindings exist locally. Released package availability, consumer pins/profiles and real converter adoption are separate. | Validate the installed owner package and migrated captures, preserve old fields, document each conditional provenance failure, then record release and consumer adoption separately. Keep the 11 missing evidence findings explicit; do not weaken requirements to hide unavailable inputs. |
| **RS02 · P1** Archive/member identity (G4) | SpicyDocs' public-law USLM extension preserves ZIP/member proof, but a shared archive/member definition and verifier are still pending. | Define byte identity and containment evidence once in Rulespec; test wrong archive/member paths, digests, duplicate/ambiguous members and absent bytes. Adopt the owner representation in SpicyDocs with exact existing proof preserved. Verification must not silently fetch evidence or claim semantic truth. |

## RefSpec — source-backed reference resolution

Read the current [`PLAN.md`](../../../RefSpec/PLAN.md) and
[`validation-cost-reset-plan.md` continuation](../../../RefSpec/plans/validation-cost-reset-plan.md)
before historical backlog text. Reader adoption and earlier performance work
have landed; this documentation pass makes no RefSpec code or artifact change.

| ID / priority | Remaining gap | Completion check |
| --- | --- | --- |
| **REF01 · P1** FERC docket-prefix evidence (REF-070) | Routing exists; the source directory PDF is not captured. The prior measurement attributes 51,015 distinct docket strings (6.5% of measured FR docket references) to this family. | Capture the authoritative directory through the shared source owner, pin source bytes and entries, then qualify routing/resolution on held-out positive and refusal cases. Retain original strings and source context. Do not turn a recognized prefix into a verified matter identity. |
| **REF02 · P1** Cross-source identity qualification | Dated FR keys, committee names/system codes, CFR parts, citation ranges and FEC affiliation observations require owner evidence. Host name matches or literal docket similarities do not prove identity. | Reuse existing resolvers and pinned agency/committee identity evidence. Compare candidate links to native IDs, retain unresolved/ambiguous states, and report precision/coverage for each relation. Coordinate SD05/SD09/SR03/SR13 rather than duplicating normalization in host builders. |
| **REF03 · P2** Audit/artifact freshness | The parked strict expected-failure registry audit snapshot predates the `term_explanation` manifest addition. Shared evidence regeneration has its own owner/measurement-lock boundary. | Reconcile the current manifest and tracked audit only through the established owner process; retain the prior artifact and record new pins. Reverify consumer adoption against the resulting artifact. This parked snapshot is not a current consumer outage. |
| **REF04 · conditional** Additional identifier families | A fifth term-explanation identifier family lacks actual instance-directory acquisition. Broader reference coverage remains family-specific. | Acquire and qualify real instance evidence before adding family claims; preserve source observations, normalized candidate and authority decision separately. Do not reopen closed performance/reader work without a new documented trigger. |
| **REF05 · P1** Retained-input integrity | The sealed agency crosswalk's docket-link input was overwritten: expected 715,080 rows, replacement 893,766. The earlier recovery sweep found no matching original. Act-index source ZIP URL/time evidence remains incomplete even though its portable distribution landed. | Recover the exact original digest if newly available, otherwise rebuild a new generation and preserve the old nonreproducible status. Verify independent durable storage/restore for exact source bytes. Never rewrite a historical receipt to bless replacements or invent acquisition provenance. |
| **REF06 · P1** Eight declared audit evidence gaps | Current audit declarations block `act_resolution`, `agency_crosswalk`, `eo_roster`, `hand_validated_interpretations`, `term_explanation`, `unified_agenda_parquet`, `usc_act_index` and `usc_section_oracle` for different reasons. Some consume derived/curated data intentionally; others lack source/execution linkage or original provenance. | Tie each applicable production execution to its real pinned input and substantive output. Preserve derived/curated classifications. Add per-ZIP paths/digests for all 32 held Code archives. Reobserve the old `claim_release_exports`, GAO and `usc_disposition_tables` execution failures rather than asserting they still occur unchanged. |
| **REF07 · P2** Per-resource admission/usefulness | Current catalog declares 117 resources: four `verifiedDistribution`, seven `evidenceOnly`, 106 `inventoryOnly`. These are declared states, not a fresh verification or 113 defects. | Follow each resource's `gap`, vintage, distribution and consumer need in the [owner catalog](../../../RefSpec/portfolio/resource-catalog-v0.json). Promote a chosen bounded resource only after coverage, immutable evidence and relevant acceptance/refusal checks pass. Do not require world completeness for an intentionally selected release. |
| **REF08 · P2, remeasure before implementation** Citation and interpretation residuals | Historical investigations mix real residuals, candidate repairs and landed fixes. Range/appendix endpoint evidence, authority-note meaning, timetable page-series bounds and per-value repairs remain qualified separately. | Use the research queue below: reproduce a current raw/output counterexample, state its population, then change and qualify only that behavior. Preserve original syntax, alternatives and authority verdict. |

RefSpec's retained research queue is explicitly part of this backlog. Its
[mined investigations](../../../RefSpec/research/investigations-mined-2026-08-31.md),
[backlog validation](../../../RefSpec/research/backlog-validation-2026-08-31.md)
and [raw-review wave](../../../RefSpec/research/raw-review-wave-2026-08-31.md)
retain the original witnesses and counts. The current owner reconciliation is
[`remaining-schema-reference-gaps.md`](/Users/mikewolfd/Work/corpora/fork-cloudflare-2026-09-21/remaining-schema-reference-gaps.md).

| Candidate / declared limit | Remaining check before closure |
| --- | --- |
| Range endpoints, appendix tails and qualifiers | Recount the named populations, retain both endpoints and distinguish true ranges from hyphenated identities, descending/degenerate inputs and shorthand. Current comments still name 144 appendix-tail rows and 15 Agenda endpoint-suffix cases; broader historical counts are different populations. |
| Misleading authority-note matches | Reproduce `present-by-stem`, note-range swallowing and fabricated Stat. pages against current output. The landed existence/oracle gate cannot prove the source construction means the matched U.S. Code section. |
| Timetable FR page bounds | Qualify against a pinned per-volume page roster and retain a separate verdict. The dated 223-row observation is not a current error count; a global page ceiling is insufficient. |
| B8 multi-candidate enlargement | Re-derive and adjudicate the proposed 1,902 corroborated cases. The sole-survivor/two-witness rule already landed; 454 witnessless cases remain refused. |
| Act/credit/occurrence edge cases | Reproduce capitalized act-section lookup, duplicated act rows, `283z-11` credit attachment and the `§` boundary branch through current callers. Preserve intentional occurrence distinctions; cited-division case handling is already fixed. |
| Attestation precision | Recheck the historical 38 appendix rows labeled false without an appendix observation; distinguish unknown from observed absence. Qualify six unpinned recodification families individually. Keep the deliberate bracketed repealed/omitted-stub exclusion. |
| Other semantic candidates | Reobserve wrong-title carry after a dot fence, off-form `None` severity, HTML-bearing Agenda abstracts and descending-span refusal. The dotted-first collateral-loss candidate has zero observed affected texts and waits for a specimen. |
| Per-value publisher attestation | `E5-2394Filed` has a visual witness; roughly 26 historical relatives were still pending. Require each value's own publisher page/colophon and alternatives before repair. |
| Research/operational findings needing refresh | Recheck roster witness paths/digests, year-specific FAA initialisms, language-scope exclusions, conformance references, reader prose, explorer assets and receipt counters against current artifacts. Old performance and obsolete candidate-release findings are not reopened. |

Additional reference acquisition candidates include EPA FRL, SEC releases/rule
filings, FAA airworthiness and OMB controls; REF-070's demand counts retain their
September 7 scope. FERC remains the selected next acquisition. Shared-reader
adoption, Agenda rebuild, portable act-index distribution and three-way act-name
absence reasons have landed. Old “publication open” and 107-name blanket-error
claims must not become new work.

## Fork operations — SpicyRegs and account settings

Cloudflare account `174055408ff1560e60601c4d12c561c4`
(`mdeeb@civictechdc.org`) now has the fork's bucket, five GitHub storage secrets,
named local login and working selected-host reads. Infrastructure/runtime
changes were independently reviewed. Actual synthetic publication passed;
all setup probe objects were removed. The subsequent invalid lobbying family
was withdrawn conditionally, with immutable diagnostic bytes retained.

The runbook is [`deploy/fork-setup.md`](../../../spicy-regs/deploy/fork-setup.md).
Evidence lives at `~/Work/corpora/fork-cloudflare-2026-09-21/`, including
`s3-generation-rehearsal.json`, `invalid-family-withdrawal.json`,
`lda-reader-repair/independent-review/certificate.json` and
`lda-final-host-gate.log`.

| ID / priority | Remaining gap | Completion check |
| --- | --- | --- |
| **OPS01 · P1** Useful real data | Storage tests do not establish a valid real-source family in the new bucket after withdrawing the bad lobbying output. | Execute SR01/SR07/SR15 for selected families; verify public source scope, exact admitted bytes and actual consumer reads. |
| **OPS02 · P1 if catalog jobs run** Catalog configuration | Catalog settings are separate from working storage credentials. Existing Iceberg ETL, seed, mirror, deduplication and attachment-backfill jobs depend on them. | Keep unconfigured paths inactive/not selected or configure the account-owned catalog, seed a bounded cohort and verify ingestion/mirror/reader identity. Local Parquet repair does not qualify Iceberg correction behavior. |
| **OPS03 · P2** Documentation deployment | The [data dictionary run](https://github.com/mikewolfd/spicy-regs/actions/runs/35642543802) built successfully but deployment failed with 404; GitHub Pages is not enabled on the fork. | Choose the docs host, configure its deployment path and verify the published fork URL/links. Core CI success is separate. Retained log: `pages-deployment-failure.log`. |
| **OPS04 · conditional** Public hostname and query service | The working `r2.dev` URL is [rate limited and intended for non-production traffic](https://developers.cloudflare.com/r2/buckets/public-buckets/#public-development-url). Production data hosting needs a suitable hostname independently of MCP. No custom-domain or Worker deployment/load qualification is established; local container queries and dry builds pass, but Containers account prerequisites remain unverified. | For production public traffic, configure the data hostname and recheck exact bytes/range/conditional reads. Separately, if MCP hosting is selected, verify prerequisites, deploy the reviewed configuration and test real queries, generation pins and concurrency against service expectations. Direct Parquet use does not require MCP deployment. |
| **OPS05 · P1 before advertising a fork service** Fork-facing defaults | The packaged landing page, plugin helpers and documentation still contain upstream endpoints/examples. Runtime host overrides work, but a fork visitor could copy an upstream installation/query link. | Establish canonical fork service/docs/install URLs, update or clearly label examples and test copy-paste flows against the fork. Preserve intentional compatibility defaults; use existing helper overrides. |
| **OPS06 · conditional** Portable identity and infrastructure management | The named local Wrangler login does not travel with Git. Terraform validates but has not been applied/imported with private state. The historical Cloud Run recipe still has upstream endpoints and can retain stale catalog settings. | On another runner, verify account/bucket/URL/catalog together. If Terraform is chosen, use account-owned private state and a reviewed plan. If Cloud Run is chosen, make data/catalog/smoke endpoints explicit and clear stale settings. These are optional paths, not unfinished bucket creation. |
| **OPS07 · per-source dependency** Credentials and schedule readiness | Storage secrets alone do not authorize every source API/model or make every existing schedule runnable. Only the lobbying schedule was explicitly paused during this incident. | Audit the jobs selected for service, their source/catalog credentials and limits before enabling them. Record missing dependencies and actual first-run results. Do not infer that other schedules are paused, healthy or fully configured. |

## Legacy register reconciliation and deferred scope

This mapping keeps older IDs discoverable without reopening completed work.
Within a row, “implemented” means the mechanism landed; source coverage and
publication still follow the items above and the table scorecard.

| Original IDs | Current disposition |
| --- | --- |
| A1/A2/A3 | Linkage mechanisms implemented; residual matching, plural hearing production and same-scope vote joins: SD04, SR05. |
| A4 | Senate source index implemented; hosting and older corrections: SR05/SR06. |
| A5/A7/A10 | Index/rollup mechanisms implemented; details, body coverage, reverse hearing edges and source omissions: SD03, SR03/SR05/SR14. Missing event IDs, House repository historical floor and RSS-window completeness remain unmeasured. |
| A6 | Measured reconstruction/parser implemented; historical run, split granules and resolver: SD09. The old “do not host because detail floor” conclusion is superseded. |
| A8/A9/A11 | Law/roster/backfill mechanisms implemented; full historical populations, release-aware joins and term identity: SR14. |
| A12/A13 | Map/floor work implemented; no new implementation task. |
| B1 | Reconstruction pilot measured; bill profile rollout: SD08. |
| B2/B3/B5/B6/B7 | CREC granules, CRS preference, table observations, 42-PDF normalizer check and USLM acquisition implemented. Wider independent body/extraction qualification: SD07/SD08/SD11/SD13. Shared PyMuPDF comparisons prove preservation, not independent table-extraction truth. |
| B4/B8 | Narrow print/CBO capabilities implemented; remaining amounts, payment detail, bodies and interpretation: SD02/SD04/SD10. OCR/vision for named pre-XML scans stays conditional, not required for born-digital work. |
| C1/C1a/C2/C3/C4/C5 | Live output, prompt repair, search semantics and signed-date frequency measured. Quality, existing signal audit and segmentation: SD04. |
| D1/D2/D4/D5 | Bounded first rollups, shared bill reader and request-budget measurement complete. Second run: SR06; false hearing fixture: SD08. Eight unchanged-archive listing reads are accepted, not optimization work. |
| D3 | Downstream catalog adoption: SR15; the old 24-table SpicySearch pin is historical until rechecked. |
| E1/E2/E3 | Open owner/upstream/type-gate work: SD14. |
| E4/E5 | Weekly publisher workflow and docs-index checks implemented; normal report triage continues. |
| F1/F2/F2b/F3/F4/F5/F6/F7/F8/F9/F10/F11 | F2/F2b and F10/F11 mechanisms closed. Remaining portions map to SR03/SR04/SR06 and SD04/SD06/SD08/SD10/SD11. |
| G1/G2/G3/G4/G5/G6 | G1/G5/G6 and bounded G2 preservation closed. Missing extraction/provenance evidence and opt-in v2/archive adoption: SD07, RS01/RS02. |
| H1/H2/H3/H4/H5 | H3 refuted; keep six tables. Logical views, empty/local scope and coherent releases: SD06, SR01/SR04/SR08. |
| H6/H7/H8/H9/H10/H11/H12/H13/H14/H15/H16 | Fix/adoption distinctions are in the repair table. Open public adoption, semantics, lifecycle grain and LDA backfill: SR01–SR07/SR10, SD02/SD04. |

House floor documents, agency congressional budget justifications and bound
Congressional Record (CRECB) bodies remain candidate/deferred routes in the
data map; daily CREC capability does not establish CRECB acquisition. A
universal PDF-to-XML converter, arbitrary-schema reconstruction and unrequested
OCR expansion remain outside the selected program. No upstream SpicyRegs push,
new cloud deployment or issue filing follows merely from listing a gap.

## Suggested next batch and closure evidence

1. Finish the bounded LDA seed/correction plan and publish one useful, coherent
   real generation. In parallel, repair SD01–SD03 from their retained witnesses.
2. Rebuild the already corrected bill/regulatory/FR/CFR/court cohorts, adopting
   one family at a time with public byte and native-field checks.
3. Qualify lifecycle/action/financial/affiliation meanings and the existing
   hearing/vote/RIN joins before presenting aggregate answers.
4. Adopt capture v2, finish archive/member proof and the FERC directory, then
   expand historical/FEC/fiscal/body coverage according to an actual consumer.

Close each item with its code/package commit where relevant, exact input/output
pins, independent source comparison, named scope/refusals, and public generation
or deployed endpoint when delivery is part of the item. Keep raw receipts
outside Git and the execution register updated on a separate status commit.
