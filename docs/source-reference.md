# Source fields and native references

Use the source's schema and acquisition policy to determine what a supported
release contains. The public profiles in
[`source_native_profiles.py`](../src/spicy_docs/source_native_profiles.py) describe
Federal Register metadata, Regulations.gov documents/dockets/comments, GAO
product pages, and captured community comments. They drive working acquisition
and replay. [Raw readers](sources/raw-readers.md) offer additional source data
without those release guarantees.

SpicyRegs owns its published table definitions. Consult its
[data dictionary](../../spicy-regs/src/spicy_regs/data_dictionary.py) and the
table's producing transform for columns and availability. A column name in a
planning note does not establish that a producer populates it. Public publisher
access also does not establish every record's access status, permission to
redistribute it, or availability through a particular route.

## Knowledge retained from the former profile catalog

The retired catalog mixed table-field notes with processor selection, allowed
concept schemes, region adapters, and workflow-stage flags. Nothing in source
acquisition enforced those processing choices. The generator, custom content
seals, generated files, and fixture-pinning workflow had no identified production
consumer in the checked repositories. They have been removed together.

The table below retains useful source-reference relationships from
`policies/profile-resource-applicability-input-v0.json` at SpicyDocs revision
`04ade52`. That input recorded `2026-08-03T12:00:00Z`; this source review and its
corrections were made on September 11, 2026 against the local implementations.
The reference names are research identifiers from that inventory. They are not
a current RefSpec resource inventory, a dependency pin, or an instruction to run
a processor. A dataset experiment must choose and pin any resource it uses.

| Source surface | Source fields or structures worth preserving | Reference names and relationship | Limit on the claim |
| --- | --- | --- | --- |
| Regulations.gov dockets | Docket type, agency, docket ID, RIN | `regulations-gov-native-controls`: classifications, identifiers, structure; `rin-authority`: identifier | Preserve exact source values. The source reader does not assign downstream subjects. |
| Regulations.gov documents | Document/attachment type, agency, docket ID, Federal Register number, dates | `regulations-gov-native-controls`: classifications, identifiers, structure | A Federal Register document reference is a link to another source. It does not make Federal Register topics native document metadata. |
| Regulations.gov comments | Submitter fields, attachment metadata, participation category, source access/privacy fields | `regulations-gov-native-controls`: classifications, identifiers, structure | Distinguish fields the source supplies from fields unavailable or withheld on that route. |
| Federal Register metadata | Topics, category, presidential subtype, agency, RIN, docket and CFR references, publication identity | `federal-register-api-topics`: publisher vocabulary; `federal-register-native-controls`: classifications, identifiers, structure; `rin-authority`: identifier | Body locators do not contain body bytes. The native identity includes document number and publication date. The former inventory's `toc_subject` is historical reference context, not a field in the current native API or SpicyRegs table. |
| Unified Agenda observations | RIN, agency, stage, priority, timetable, legal authority, CFR references, related RIN, NAICS | `unified-agenda-native-controls`: classifications and identifiers; `rin-authority`: identifier; `naics`: classification | Keep the agenda edition with the observation. This table description is not a SpicyDocs release adapter. |
| CFR metadata and separately acquired XML | Hierarchy, citations, edition and source XML structure | `ecfr-govinfo-cfr-structure`: identifiers and structure; `uslm`: XML structure; `cfr-list-of-subjects`: separately sourced vocabulary | SpicyRegs' `cfr_sections` producer publishes metadata, not section bodies. Its table does not establish possession of USLM text or Lists of Subjects. SpicyDocs has no CFR release profile. |
| Congress bill metadata and separately acquired XML | Bill type, actions, versions, committees, BioGuide identifiers and XML structure | `congress-billstatus-native-controls`: classifications, identifiers, structure; `federal-legislative-identifiers`: identifiers; `uslm`: XML structure; `crs-legislative-subject-terms` and `crs-policy-areas`: publisher vocabulary when supplied | Confirm the actual endpoint and fields. A bill record or link does not establish possession of full bill XML or all subject metadata. |
| SAM entity metadata | UEI, CAGE, NAICS, legal name, registration state, location, hierarchy references | `entity-identifier-authorities`: identifiers; `naics`: classification; `federal-hierarchy`: identifiers/classification | Use the actual supplied entity fields and route's access conditions. This is not a native SpicyDocs adapter. |
| Lobbying filings | Issue code, filing type/period/status, client, registrant, government target, amendment | `lda-native-controls`: publisher vocabulary, classifications, identifiers | Preserve filing context and amendments; no topic inference is implied. |
| FEC committees | Committee ID, type/designation, organization/party, sponsor, candidate links, cycle and effective dates | `fec-native-controls`: identifiers/classifications; `federal-legislative-identifiers`: linked identifiers | The available fields and temporal scope come from the producing source/table. |
| GAO product pages and RSS metadata | Product/report identity, publisher topic on the product page, product type/date where supplied | `gao-topics`: literal publisher vocabulary; `gao-native-controls`: classifications/identifiers | The native GAO page profile retains the exact topic label/slug/link. SpicyRegs' RSS producer reserves `topics_json` and `agencies_json` as empty lists; those placeholders are not captured topic or agency evidence. Recommendations and full-text analysis require separate inputs. |
| CRS reports and related legislative metadata | Report number, product type, edition/status, supplied topic/subject/policy fields, bill and committee references | `crs-native-controls`: vocabulary, classifications, identifiers; `crs-legislative-subject-terms` and `crs-policy-areas`: supplied publisher vocabulary | Do not infer every field is present in a report feed or summary capture. |
| Court opinion declaration | Court/case identity, opinion type, citations, version/package identity | `court-identifiers-and-controls`: identifiers/classifications | No current producer for the former `court_opinions` declaration was found in the checked SpicyRegs implementation. Use the actual cluster/body producers below. |
| CourtListener dockets | Court identity, Nature of Suit, case/party identity, status, dates and source access fields | `court-identifiers-and-controls`: identifiers/classifications; `nature-of-suit`: classification | A docket record does not establish captured opinion or filing text. |
| CourtListener opinion clusters | Court/case identity, date, precedential status, citations, Nature of Suit when supplied | `court-identifiers-and-controls`: identifiers/classifications; `nature-of-suit`: classification | SpicyRegs has a cluster producer. Consult that transform as well as its dictionary; do not substitute the old generic opinion declaration. |
| CourtListener opinion bodies | Opinion type, authorship, case links and supplied text versions | `court-identifiers-and-controls`: identifiers/classifications | SpicyRegs has a body producer. The raw reader's exact input and transformation determine available text and provenance. |
| USAspending recipients | Recipient identity and supplied entity/classification references | `entity-identifier-authorities`: identifiers; `naics` and `psc`: classifications; `federal-hierarchy`: identifiers/classifications | UEI/CAGE/NAICS/PSC/hierarchy fields in the old inventory are areas to inspect, not proof that the recipient table supplies all of them. |
| FCC proceedings | ECFS proceeding number/name, rulemaking flag, bureau, status and dates | `fcc-ecfs-native-controls`: classifications, identifiers, structure | The producing table is keyed by `name`, not the old declaration's `id_proceeding`. FRN and 47 CFR procedure classification require their own source fields/evidence. |
| FCC filings | Filing description, filer/author, supplied FRN, bureau/status/access fields, attachment metadata | `fcc-ecfs-native-controls`: classifications, identifiers, structure; `frn-authority`: supplied identifier; `cfr47-procedure`: separately evidenced procedure reference | Federal Register topics are not native FCC filing topics. A genre map or procedure classifier belongs to a selected downstream experiment. |

An aggregate comment index describes partitions. A Federal Register-to-docket
link describes a relationship between records. Both can be useful source data;
whether either should become a separately processed dataset item is the dataset
builder's decision, not an exclusion flag in the acquisition package.

## Use the supported source description

For a native release, inspect its existing profile and the admitted reader's
`collection_outcome`. The profile supplies the schema and source identity; the
outcome supplies requested selectors and digest-checked acquisition policy facts.
See [collection outcomes](source-native-outcomes.md) for the exact scope of those
claims and [source workflows](source-workflows.md) for usable stopping points.

For a SpicyRegs table, start from that product's dictionary and producing
transform. In particular, former `text_columns` entries such as CFR
`text`/`full_text`/`xml_text` and Federal Register
`body_text`/`body_html`/`full_text` were not current table columns. There is no
replacement shadow dictionary or `declared_profile_for_table` compatibility API.

The prior Rulespec profile-lookup probe and its result remain historical evidence.
Its current-provider probe records the installed native profiles and the absence
of a CFR release adapter, alongside a separate citation to SpicyRegs CFR metadata.
This retires the inaccurate capability signal without rewriting earlier results.

DocSpec [D32/D34](../../DocSpec/docs/dataset-experiments-todo.md#d32) own real
experiment configuration and cleanup; Search [SC04](../../spicysearch/PLAN.md#sc04)
owns a selected search recipe. Removing old source-side flags neither copies
those choices into another product nor completes either destination's work.
Use the [documented-value diagnostic](source-domain-drift.md) when comparing
actual retained table values with pinned publisher documentation.
