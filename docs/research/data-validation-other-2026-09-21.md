# Data validation: elections, organizations, spending, oversight and courts

## Decision

The inspected native election and agency-report outputs preserve their source
observations well. Their evidence is substantially stronger than the evidence
for the current hosted organization and court tables. Keep these conclusions
separate: a successful native release does not validate an unrelated public
generation, and a working identifier join does not validate an inferred
relationship.

The clearest output defect is in the retained `court_opinion_bodies`: **73 of
250,000 rows declare available HTML text but retain neither body column**.
Current code counts eight text variants and saves only two. The original
CourtListener opinion dump was not located, so the exact pre-conversion HTML
bytes remain unvalidated. A current publisher web page would not close that
historical source-byte gap. No schema expansion or product change was made in
this audit.

Useful joins already work. All **1,397** public organization-to-committee links
resolve to a public FEC committee. **100,954 of 113,051** public spending
recipient rows resolve to a SAM entity by Unique Entity ID (UEI). These are
key-integrity results, not proof that the name-derived political relationships
are correct or that spending totals can be summed across recipient levels.

## Evidence and method

New, replayable evidence is retained under
`~/Work/corpora/supply-2026-09-02/receipts/data-validation-sprint-2026-09-21/other/`.
The four scripts run with `uv run --frozen --all-extras python` from this
repository. `README.md` in that directory gives exact commands;
`audit-manifest.json` pins the scripts, results and checkout revisions.
Existing receipts were read without modification. No new network request,
model call, upload or population acquisition was made in this workstream.

The public files are the full objects acquired by the sprint coordinator into
the adjacent `public/` directory. Its `public-acquisition.jsonl` pins object
hashes and ETags. Older local files are named as such below. The coordinator's
`table-profiles-final.json` provides full structural profiles; this report adds
native comparisons, direct row inspection and useful-query checks.

Comparisons use independent JSON pointers, CSV/ZIP decoding, XML tree traversal,
HTML link/cell inspection, and PDF page inspection where practical. Current
reader replays are identified separately. Using Beautiful Soup for independent
HTML inspection provides a different mapping implementation but shares that
library with some product readers. A source fixture observed on September 14
and a later public row are not assumed to be the same generation. Differences
are retained; unexplained cross-date differences do not become conversion
failures or passes.

| Receipt | What it establishes |
| --- | --- |
| `native-results.json` | Complete selected FEC committee comparisons; native candidate/legal/bulk/positional records; FOIA and Oversight comparisons. |
| `extra-results.json` | F13 filings, original field values, relationship samples, Supreme Court indexes/PDFs, GAO indexes/PDFs, CRS files. |
| `reader-results.json` | Complete CourtListener courts CSV round-trip and current GAO product-page replay. |
| `../cbo-source-review.json` | Coordinator's independent native CBO feed comparison: 5,175 records and 36,225 fields across four Congresses. |
| `hosted-results.json` | Public-row comparisons, exact UEI/committee joins, SAM state/code distributions, actual retained court rows and the 73-body counterexample. |
| `pdf-inspection.json`, `*-first-page.png` | Native first-page text, page counts and visual inspection for one Supreme Court, GAO and CRS file. |
| `table-assessments.json`, `source-assessments.json` | Machine-readable dispositions for ten host tables and nine assigned source families. `congress-crs-file-assessments.json` supplies the CRS routes to the Congress family owner. |

## Hosted and materialized tables

“Unvalidated” below refers to the named evidence gap, not a finding that the
entire table is wrong. Counts describe inspected objects, not publisher totals.

| Table and inspected population | Conversion | Completeness and shape | Useful question and next action |
| --- | --- | --- | --- |
| `sam_entities`: 885,266 public rows | Two retained API identities match public rows; 7 of 36 fields differ. Both native descriptions say “U.S. Government Entity”; the hosted value is `2A`. Native exclusion/type values are absent from the output. One congressional district differs. Same-generation bulk-extract conversion is **unvalidated**. | Every non-null `entity_structure_desc` value is a code. Entity type, profit structure and exclusion flag are all-null columns. 119,055 rows labelled `Active` have expiration dates before September 21. Accumulated rows lack an observation time, so that label cannot establish current status. | Resolve a spending recipient to its registered identity by UEI. Retain the actual extract used to produce rows; distinguish code, description and observation date before status-dependent use. |
| `lobbying_filings`: 287,606 public rows | Two native records match 26 of 28 compared fields. Both document URLs differ only in the `lda.gov` versus `lda.senate.gov` hostname. Same-generation conversion is **unvalidated**. | UUID and client/registrant IDs survive. The current shape retains issue codes/descriptions but omits lobbyists and the relationship between each activity and its agencies; a separate agency list is flattened and deduplicated. The two inspected native examples do not qualify all multi-activity cases. | Find clients reporting an issue and follow the source filing. Preserve per-activity relationships before answering which lobbyist contacted which agency about which issue. Treat amendments and money fields according to filing type. |
| `fec_committees`: 89,643 public rows; separate qualified 27,311-row retained census | **Supported for the retained census:** all 27,311 IDs and all 436,976 mapped fields agree with 274 captured responses. This does **not** validate the larger public generation. | Sixteen hosted columns omit native affiliation/sponsor fields. The native release retains them. The inspected census is the selected 2024/2026 cycle query, not all historical committee states. | Retrieve committee identity and join candidate organization links. Use native relationship observations for affiliation evidence; qualify the current public generation separately. |
| `org_committee_links`: 1,397 public rows | All committee references resolve, but affiliation accuracy is **unvalidated**. The `high` confidence label is an algorithm category; no independent truth set or predeclared measured precision was established here. | These are name-derived candidates over selected commenting organizations. Method and ambiguity counts help review but do not turn a similar name into a source-stated relationship. | Prioritize organizations for affiliation review. Compare candidates against independent source-stated relationships before promoting them as facts. |
| `gao_reports`: 136 public rows | Two RSS identities match title/date/URL. One abstract difference is surrounding whitespace; the other is an unresolved cross-date content difference. `Report` is a pipeline default, not a publisher product-type observation. | Recent-feed accumulator, not a GAO archive. `agencies_json` and `topics_json` are reserved empty arrays. Product topics and report bodies exist on separate source routes. | Find recent oversight products by title/abstract. Enrich from named product-page/file observations; do not interpret empty placeholders as “no agencies/topics.” |
| `crs_reports`: 14,129 public rows | Two native list records match title/type/status/version/URL; update dates differ. The actual LSB11481 PDF cover matches the hosted report ID, title and publication date. Same-generation listing conversion remains **unvalidated**. | Current list metadata has report-ID grain; full version history, authors, formats and text are separate. Selected-version PDF readers are useful but do not populate this table's body text. | Find a report and retrieve its stated edition. Join metadata to versioned file evidence; preserve observation times and qualify HTML routes separately. |
| `court_dockets`: 7,766 public rows | Actual rows were inspected; a retained search fixture has a different query scope and was not paired to this generation. Native-to-public conversion is **unvalidated**. | The configured discovery scope is nature-of-suit 899, not all federal dockets. Participant names are retained but their source ID arrays are omitted. A date-filed discovery window does not itself guarantee later corrections to old cases. | Find cases in the selected scope and join clusters by docket ID. Retain source pages with the output generation and preserve participant IDs for entity research. |
| `usaspending_recipients`: 113,051 public rows | Two source recipients match identifiers, names, UEIs, DUNS and level; amounts differ across observation dates. Same-generation amount conversion is **unvalidated**. | A top-recipient accumulator, not all awards. There are 76,796 distinct nonempty UEIs across 110,156 rows; 32,497 UEIs occur more than once, covering 65,857 rows. Recipient ID, not UEI, is the table grain. Period/as-of context is absent. | Join 100,954 recipient rows to SAM. Choose the recipient level and period before totals; expose source scope and freshness. |
| `court_opinion_clusters`: 10,070,727 retained local rows | The actual materialization was inspected, but the original clusters dump was not located. Conversion is **unvalidated**. | This retained file has 36 columns, while current code declares 39; court ID/jurisdiction/federal fields are absent in the older file. `ingest_source` distinguishes bulk/search. This is not proof of a current public generation. | Join cases to dockets or retrieve cluster metadata. Retain bounded raw/output witnesses and qualify a coherent generation before court-jurisdiction filtering. |
| `court_opinion_bodies`: 250,000 retained local rows | **Output defect demonstrated:** 73 rows have positive text counts and an available `html` variant, but both retained body columns are null. The historical original variant bytes remain **unvalidated**. | A bounded bulk prefix, not all opinions. Code counts eight variants, but stores `plain_text` and `html_with_citations` only. A separate 1,155-row APA selection has preserved bodies; that does not repair this prefix. | Retrieve opinion text where a preserved variant exists. Retain an exact source-dump witness, then design a versioned all-variants or structured-original-text representation and review downstream migration before changing 19 columns to 25. |

The retained court files are under
`spicy-regs/output/court-data-2026-08-22/`; the separate scoped file is under
`spicy-regs/output/court-data-apa-2026-08-22/`. One exact missing-body example is
opinion `10573190`, cluster `10125235`, `available_text_fields="html"`,
`text_char_count="7537"`, with both preserved text columns null. Its source
locator names the New York opinion `2024_51205.htm`. No claim is made here that
the current web page equals the historical CourtListener field.

## Native FEC outputs: separate qualifications

These names identify actual native release schemas or emitted observation
files. They are not additional public catalog tables. File links, metadata,
body references and acquired bodies remain distinct outputs.

| Output/profile | Direct evidence and conversion | Completeness, shape and practical use |
| --- | --- | --- |
| `fec-committee-observation` 1.0 and its retained `fec_committees.parquet` consumer | Complete selected census: 274 captures, 27,311 unique IDs, 436,976 field comparisons, no discrepancies or missing/extra IDs. | Source metadata includes affiliation/sponsor fields omitted from the consumer. Use for committee identity and source-backed relationship review, within the selected cycle query. |
| `fec-candidate-observation` 1.0 | Three retained queries: one returned candidate, two requested-empty queries. The one record's entire metadata object equals its exact native JSON pointer. | Preserve empty-query scope; it does not prove that a named candidate does not exist. Candidate detail/history/search/totals routes are separate and unvalidated here. |
| `fec-filing-observation` 1.2 | All 31 records in the observed Form F13 query match complete native metadata and linked-asset pointers. Six negative and two null `file_number` values survive; `sub_id` supplies identity. | This is a processed-filing query, not acquisition of its linked originals or an authoritative amendment selection. Useful for locating inaugural filings and inspecting the source amendment chain. |
| `fec-legal-search-observation` 1.0, advisory opinions | Eight records match their entire native metadata objects; 40 linked assets and no embedded bodies. | Selected 2025 search answer, not full case files. Use for advisory-opinion discovery and exact document references. |
| Same legal profile, administrative fines | Sixteen records match their entire native objects; decimal tokens remain strings, with 27 assets and no embedded bodies. | Selected 2025 determination-date query. Useful for finding administrative-fine observations, not proving legal-document completeness. |
| Same legal profile, ADR and MUR | **Unvalidated real complete-query success.** Existing successes are synthetic controls; the retained MUR research route has a credential-bearing query boundary and was not relabelled as a new clean capture. | Keep alternative dispute resolution and enforcement matters as separate evidence gaps. Qualify a bounded complete query before a native-population claim. |
| `fec-audit-case-observation` 1.0 | **Unvalidated real complete-query success.** The retained partial audit page supports refusal behavior only; success tests are synthetic. | `audit_case_id` is distinct from `audit_id` and committee identity. Potential audit/committee/cycle retrieval needs a complete observed query and actual output witness. |
| `fec-bulk-file-observation` 1.0 | Two originals: `ccl24.zip` and its header CSV. Original pins and the full member name, ordinal, decoded byte size and SHA agree independently. | A file/member observation does not establish field semantics or all bulk families. Useful for selecting a known candidate-committee linkage source. |
| `fec-positional-row` 1.0 | Four files yield 8,702 records. Every one of 8,701 ordinary row byte slices matches its literal field array. The remaining record is an embedded text reference in Form F99, not a positional row. | Counts: `94293.fec` 60; `ElectioneeringComm_2026.csv` 20; `ccl24.zip` 8,619; `2011530.fec` two positional rows plus one text reference. The referenced F99 body was not independently qualified as prose in this run. |
| FEC form/version field annotations (`mapped-records.jsonl`) | All 1,546 original rows and 29,636 literal fields match their source slices. This includes 25 selected electronic examples and 1,521 paper records; 1,542 have mappings, four remain explicitly unselected. | The original positions and values survive. Workbook label/cell/ordinal mapping was qualified in the earlier retained campaign but was **not independently rerun here**. Caller-selected layout equality is not automatic form/version compatibility. |
| `fec_relationships.parquet`: 216,522 retained rows, 17 columns | Deterministic first five rows from each of seven native source families: all 35 referenced field sets match original JSON, ZIP/CSV or electronic-filing bytes. | This is a stratified convenience sample, not a precision estimate. Rows include blank/not-reported observations, so the total is not a positive-edge count. Source hashes, locators, observation time and value/identity status support review. Use reported source IDs and filter status explicitly; names must not be upgraded into IDs. |

The relationship families contain 84,102 committee-API observations, 83,214
committee-master observations, 18,352 candidate-master observations, 16,696
linkage observations, 12,311 Form 1 bulk observations, 1,740 leadership
observations and 107 original-statement observations. Those counts describe
retained evidence with distinct source/period meanings. They are not deduplicated
current organizational relationships.

Other FEC reader routes—including legal detail, rulemakings, statutes,
financial schedules/totals and additional bulk families—have no raw/output
qualification in this workstream. Their presence in code or older research
does not supply a pass. This report's FEC verdict is profile-specific.

## Other source-native readers and outputs

| Source/output | Checked input and output | Disposition and useful application |
| --- | --- | --- |
| FOIA `parse_foia_annual_report` → `metadata`/`elements` | Eighteen native XML capture occurrences, 8,675 elements: tags, attributes, text, tail, parent and child paths all agree with an independent XML traversal. One distinct Word Flat OPC input remains a refusal. The fiscal-year observations span 2009–2025, with a repeated 2025 input. | **Supported in this scope.** Namespace declarations were not independently compared here. Literal source trees support exact annual-metric lookup; normalized year-to-year metrics still require version-aware field/unit definitions. No all-agency coverage claim. |
| Oversight.gov `parse_oversight_report` → `metadata`/`bodies` | 103 retained FEC report pages: every main-content link and all 253 recommendation cells across six recommendation sections agree. | **Supported for links and cell text.** This does not qualify every HTML attribute/layout or linked PDF body. Useful for finding recommendations and their source assets. |
| GAO `gao-product-page-raw` 1.0 | Current offline replay of 47 complete retained product pages: publisher topic values match independent HTML extraction; each evidence ZIP retains the exact original HTML. | **Supported parser scope.** Response metadata was reconstructed for offline replay, so this is not a new acquisition or published-release requalification. Useful for source topic lookup, separate from interpreted taxonomy tags. |
| GAO `GaoReportIndex` / `GaoReportPdf` | Four complete online-report indexes retain their exact PDF links; four complete PDFs pass current file validation. One 84-page aviation cybersecurity report's cover was visually checked: GAO-26-107693 and title agree. | **Supported selected file scope.** File validation is not text extraction. Index availability is product-specific; missing/gated routes do not imply no report. Useful for retrieving the full file behind product metadata. |
| CRS `CrsFileSelection` → `CrsReportPdf` | Seven complete PDF cases accepted using each captured URL; six retained wrong/missing cases refused. LSB11481's five-page native PDF cover matches the hosted report's title, ID and September 14 date. | **Supported selected PDF scope.** Selected family/ID/version and byte completeness do not prove all report content. `CrsReportHtml` and combined HTML/PDF routes remain unvalidated in this workstream and should be reconciled with the legislative review. |
| Supreme Court `SupremeCourtTermIndex` | Six index renders, 417 total row occurrences, across four terms. Independent anchor extraction exactly reconstructs all opinion/revision PDF links, including preliminary-print page fragments. The first 2025 render retains ten rows without an opinion link, one of which has a revision link. | **Supported observed-render scope.** Different captures of the same URL are distinct observations. Useful for retrieving source-stated editions without guessing a filename from a docket number. |
| Supreme Court `SupremeCourtDocument` | Five complete retained PDFs pass current validation. One eight-page opinion was visually inspected: docket 25-767, *Margolin v. National Association of Immigration Judges*, decided May 26, 2026. | **Supported selected files.** This reader validates a complete file at an observed link; it does not emit opinion text or a comprehensive case table. |
| CourtListener `CourtListenerBulkReader("courts")` → `courtlistener-courts.jsonl` | Complete retained June 30 courts dump: 3,361 rows, 20 columns. Independent publisher-dialect re-export equals every original decompressed byte. 16,096 null cells and 11,808 empty strings remain distinct. | **Supported courts-dump scope.** It does not validate opinion/cluster/docket data. Useful for court identity/jurisdiction lookup and validating downstream joins. Search fixtures preserve native nesting; hosted mappings have the separately documented omissions. |
| SAM, LDA and USAspending source listings | Two native records per source compared with actual public rows; detailed differences remain in `hosted-results.json`. | **Partial native/public evidence**, with observation-date and route differences. These samples do not qualify full pagination, current populations or bulk extraction. Practical uses and next actions are in the table matrix. |
| CBO per-Congress feeds / standalone files | The coordinator independently compared all 5,175 records and 36,225 fields in four complete retained feeds for Congresses 116–119 with current parser output: no differences. `../cbo-source-review.json` pins each input and produced JSONL. The legislative review separately covers 1,431 bill-linked cost estimates from BILLSTATUS XML. | **Supported for the four observed native feeds.** Document/PDF acquisition and content remain **unvalidated**; a feed publication-page link is not acquired document text. Useful for estimate discovery by Congress, date and title. These scopes are separate from hosted bill-linked metadata. Legislators are separately assessed by the legislative review. |

## Recommended next changes

1. Close the court-body source-byte witness, then review a versioned representation
   that preserves all original text variants. Do not silently add six columns
   to a consumer-visible shape during this audit.
2. Give SAM and spending outputs explicit observation/period semantics and keep
   source codes distinct from descriptions. Reconcile retained source extract
   bytes before attributing cross-date differences to conversion code.
3. Use the existing source-stated FEC relationship observations to challenge
   organization-name links. Establish measured accuracy before interpreting
   `high` as evidence of affiliation.
4. Preserve issue-to-agency/lobbyist relationships and court participant IDs when
   those joins become an accepted consumer requirement.
5. Finish the named native evidence gaps—especially audit/ADR/MUR success and
   missing court dump witnesses—without treating broad unit-test success or a
   source family's existence in code as data qualification.

This audit added evidence and dispositions only. It did not refresh hosted
data, publish releases, change table schemas, or qualify the entire populations.
