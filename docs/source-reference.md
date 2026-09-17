# Source fields and native references

For supported releases, start with [`source_native_profiles.py`](../src/spicy_docs/source_native_profiles.py):
Federal Register metadata, Regulations.gov documents/dockets/comments, GAO pages,
and captured community comments. These profiles drive acquisition and replay.
[Raw readers](sources/raw-readers.md) supply other data without release guarantees.

SpicyRegs owns its [data dictionary](../../spicy-regs/src/spicy_regs/data_dictionary.py)
and producing transforms. Check both for actual columns and availability.
Publisher access alone establishes neither per-record access status,
redistribution permission, nor availability through every route.

## Knowledge retained from the former profile catalog

These relationships come from retired
`policies/profile-resource-applicability-input-v0.json` at revision `04ade52`,
recorded `2026-08-03T12:00:00Z` and reviewed against local implementations on
September 11, 2026. Reference names are research identifiers, not current RefSpec
inventory, dependency pins, or processor instructions. Experiments choose and pin
resources themselves. The unused generator and unenforced processing flags were removed.

### Regulations.gov dockets

Preserve docket type, agency, ID, and RIN. `regulations-gov-native-controls` covers
classifications, identifiers, and structure; `rin-authority` identifies RINs.
Keep exact source values; the reader assigns no downstream subjects.

### Regulations.gov documents

Preserve document/attachment type, agency, docket ID, Federal Register number,
and dates. `regulations-gov-native-controls` covers classifications, identifiers,
and structure. A Federal Register link does not make its topics native document metadata.

### Regulations.gov comments

Preserve submitter, attachment, participation, and access/privacy fields.
`regulations-gov-native-controls` covers classifications, identifiers, and structure.
Distinguish supplied values from fields unavailable or withheld on this route.

### Federal Register metadata

Preserve topics, category, presidential subtype, agency, RIN, docket/CFR references,
and publication identity. References: `federal-register-api-topics` vocabulary,
`federal-register-native-controls` classifications/identifiers/structure,
`rin-authority` identifiers. Identity includes number and date; body links contain
no body bytes. Historical `toc_subject` is absent from current native API/table fields.

### Unified Agenda observations

Preserve edition, RIN, agency, stage, priority, timetable, legal authority, CFR
references, related RIN, and NAICS. References: `unified-agenda-native-controls`
classifications/identifiers, `rin-authority` identifiers, `naics` classification.
This description supplies no SpicyDocs release adapter.

### CFR metadata and separately acquired XML

Preserve hierarchy, citations, edition, and XML structure. References:
`ecfr-govinfo-cfr-structure` identifiers/structure, `uslm` XML structure,
`cfr-list-of-subjects` separately sourced vocabulary. SpicyRegs `cfr_sections`
contains metadata, not section bodies or proof of USLM text/Lists of Subjects.
SpicyDocs has no CFR release profile.

Existing implementations to reuse:

- **SpicyRegs:** `sources/cfr_sections.py` and its transform acquire annual CFR
  package/granule JSON and publish section metadata.
- **RefSpec:** `registry/ecfr.py` and `registry/xml_text.py` read retained eCFR
  API XML into text, native nodes and source maps; `section_addresses` locates
  sections. Source-map coordinates are decoded characters, not raw XML bytes.
- **Rulespec:** `rulespec_extrapolator/uslm.py` already consumes that RefSpec
  reader through an installed wheel for document preparation and reference lookup.
- **DocSpec:** supplied-record catalogs, injected fetchers, XML extraction and
  retained-input reprocessing already exist; no current dedicated CFR adapter.

RefSpec also retains a whole-title research downloader under
`research/evidence/ecfr-authority-notes-2026-08-24/scripts/fetch_titles.py`.
Archived SpicyRegs/DocSpec evaluation code fetched dated CFR/eCFR sections.
These are implemented acquisition examples; qualify their bounds, resume identity
and response evidence before promoting them to reusable source APIs.

The canonical [SpicyDocs acquisition API](sources/cfr.md) now owns explicit eCFR
API, annual CFR and bulk eCFR captures, using shared bounded HTTP and XML scanning.
The historical research downloader remains an experiment; existing receiving
applications have not automatically migrated to this API.
Keep annual CFR editions and eCFR snapshot dates distinct. RefSpec's current reader
accepts `ECFR` or typed `DIV` roots; GovInfo bulk eCFR's `DLPSTEXTCLASS` wrapper and
annual CFR body XML need separate format qualification. Do not strip the bulk
wrapper blindly: its `DIV1/@N` can identify a volume rather than a title.

### Congress bill metadata and separately acquired XML

Preserve bill type, actions, versions, committees, BioGuide IDs, and XML structure.
References: `congress-billstatus-native-controls` classifications/identifiers/structure,
`federal-legislative-identifiers`, `uslm`, and supplied vocabularies
`crs-legislative-subject-terms` / `crs-policy-areas`. Check actual endpoint fields;
a bill record/link does not establish full XML or all subject metadata.

### SAM entity metadata

Preserve supplied UEI, CAGE, NAICS, legal name, registration state, location,
and hierarchy. References: `entity-identifier-authorities`, `naics`,
`federal-hierarchy` identifiers/classification. Respect route access conditions;
this is no native SpicyDocs adapter.

### Lobbying filings

Preserve issue code, filing type/period/status, client, registrant, government
target, and amendment context. `lda-native-controls` covers vocabulary,
classifications, and identifiers; no topic inference is implied.

### FEC committees

Preserve committee ID, type/designation, organization/party, sponsor, candidate
links, cycle, and effective dates. References: `fec-native-controls`
identifiers/classifications and linked `federal-legislative-identifiers`.
The producer determines available fields and temporal scope.

### GAO product pages and RSS

Preserve product/report identity, literal page topic, and supplied product type/date.
References: `gao-topics` vocabulary and `gao-native-controls` classifications/identifiers.
Native pages retain exact label/slug/link. SpicyRegs RSS reserves `topics_json`
and `agencies_json` as empty lists, not captured evidence. Recommendations and
full-text analysis require separate inputs.

### CRS reports and legislative metadata

Preserve report number, type, edition/status, supplied topics/subjects/policies,
and bill/committee links. References: `crs-native-controls` vocabulary/classifications/identifiers,
plus supplied `crs-legislative-subject-terms` and `crs-policy-areas`.
Do not assume every field appears in a feed or summary.

### Court opinion declaration

The former `court_opinions` declaration described court/case identity, type,
citations, and version/package identity under `court-identifiers-and-controls`.
No current SpicyRegs producer was found; use actual cluster/body producers below.

### CourtListener dockets

Preserve court, Nature of Suit, case/party identity, status, dates, and access fields.
References: `court-identifiers-and-controls` identifiers/classifications and
`nature-of-suit` classification. Docket metadata does not establish captured text.

### CourtListener opinion clusters

Preserve court/case identity, date, precedential status, citations, and supplied
Nature of Suit. References: `court-identifiers-and-controls` and `nature-of-suit`.
Use the SpicyRegs cluster transform and dictionary, not the old opinion declaration.

### CourtListener opinion bodies

Preserve opinion type, authorship, case links, and supplied text versions under
`court-identifiers-and-controls`. SpicyRegs has a body producer; exact raw-reader
inputs and transformations determine text and provenance.

### USAspending recipients

Preserve recipient identity and supplied entity/classification references.
References: `entity-identifier-authorities`, `naics`, `psc`, and
`federal-hierarchy`. Old UEI/CAGE/NAICS/PSC/hierarchy notes identify fields to
inspect, not proof that a recipient table supplies them all.

### FCC proceedings

Preserve ECFS proceeding number/name, rulemaking flag, bureau, status, and dates.
`fcc-ecfs-native-controls` covers classifications/identifiers/structure.
The producer keys rows by `name`, not former `id_proceeding`. FRN and 47 CFR
procedure classification need their own source evidence.

### FCC filings

Preserve description, filer/author, supplied FRN, bureau/status/access fields,
and attachments. References: `fcc-ecfs-native-controls`, supplied `frn-authority`
identifiers, and separately evidenced `cfr47-procedure`. Federal Register topics
are not native FCC topics; genre/procedure classifiers belong to experiments.

## Use the supported source description

- **Native release:** use its profile for schema/identity and admitted
  `collection_outcome` for selectors and digest-checked acquisition facts.
  See [outcomes](source-native-outcomes.md) and [workflows](source-workflows.md).
- **SpicyRegs table:** use its dictionary and producing transform. Former `text_columns` entries for CFR
  `text`/`full_text`/`xml_text` and Federal Register
  `body_text`/`body_html`/`full_text` declarations were not current columns.
  There is no shadow dictionary or `declared_profile_for_table` compatibility API.
- **Dataset item:** the builder decides whether partition indexes or record links
  become processed items; acquisition supplies no exclusion flag.

Prior Rulespec probe results remain historical. Its current-provider probe lists
installed native profiles and the absent CFR adapter, separately citing SpicyRegs
CFR metadata. DocSpec [D32/D34](../../DocSpec/docs/dataset-experiments-todo.md#d32)
own experiment configuration/cleanup. Search's former SC04 recipe task no longer
exists: its SC lane was superseded by the direct Parquet dataset lane
(spicysearch `docs/history/2026-09-11-parquet-dataset.md`), and Engine reads
DocSpec's retained state directly (`EC00`–`EC02`). Removing flags completes
neither destination's work.
Use [documented-value drift](source-domain-drift.md) to compare retained table
values with pinned publisher documentation.
