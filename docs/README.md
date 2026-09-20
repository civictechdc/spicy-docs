# Documentation

**Start here:** [Run the offline example](../README.md#try-it-offline) ·
[Contribute a change](../CONTRIBUTING.md)

## Use SpicyDocs

- [Installation](installation.md): core reader or optional acquisition, table and extraction tools.
- [Source workflows](source-workflows.md): choose raw records, releases or tables.
- [Mapped markup](markup-reading.md): XML/HTML observations and original byte positions.
- [Image headers](image-headers.md): declared dimensions without image decoding.
- [JSON reading](json-reading.md): source values and exact record positions.
- [PDF/image extraction API](extraction/pdf-extraction-api.md): injected readers, strategies
  and recognition backends with separate metadata, body and raw observations.
- [PDF page text](pdf-page-text.md): pypdf's original page strings, installed separately from any renderer, OCR engine or model.
- [GPO text normalization](extraction-gpo.md): the post-extraction step that strips GPO line numbers, footers and page numbers from PyMuPDF page text, by page-level evidence, before any text parser reads it.
- [PDF extraction choices](extraction/pdf-extraction-choices.md): saved native, OCR, vision
  and converter candidates by source and page type, with tested settings and limits.
- [Commands](cli.md): publish, verify, replay and run campaigns.
- [Collection outcomes](source-native-outcomes.md): scope, failures and evidence.
- [Raw readers](sources/raw-readers.md): Mirrulations, CourtListener and FEC acquisition.

## Work on a source

- [Federal Register](sources/federal-register.md) · [GovInfo bodies](sources/federal-register-body-sources.md) · [reference data](sources/federal-register-reference.md) · [topics](sources/federal-register-topics.md)
- [Regulations.gov](sources/regulations-gov.md)
- [GAO pages](sources/gao.md)
- [Congressional bills](sources/congress-bills.md)
- [CFR/eCFR XML](sources/cfr.md)
- [eCFR authority notes and source metadata](sources/ecfr-authority.md)
- [CFR agencies and subject index](sources/cfr-roster-index.md)
- [Public laws and statute compilations](sources/uslm-laws.md): keyless GovInfo USLM XML with native identity checks.
- [Publisher list pages](sources/listings.md): Congress.gov, GovInfo, GAO feed, LDA, CourtListener search, SAM.gov, USAspending and FCC ECFS on one traversal rule; `spicy-docs-list` walks any of them from the [command line](cli.md).
- [Unified Agenda](sources/unified-agenda.md): one reginfo.gov edition file, proved from every record.
- [U.S. Code](sources/uscode.md): OLRC release-point USLM titles, annual archives, the Popular Name Tool and Table III · [structure](sources/uscode-structure.md) · [references and source credits](sources/uscode-references.md).
- [OLRC classification tables](sources/uscode-classification.md): the per-Congress table of which Code sections each new public law touched, proving the Congress and session its own caption states.
- [Supreme Court](sources/supreme-court.md): slip-opinion term index and official opinion PDFs.
- [CRS report files](sources/crs-files.md): report PDFs by the publisher's stated URL, beside the CRS listing.
- [GAO report files](sources/gao-files.md): keyless report PDFs and online-report index behind product pages.
- [regulations.gov API](sources/regulations-gov-api.md): keyed document list and detail, attachment relationships, attachment PDFs.
- [CBO cost estimates](sources/cbo.md): per-Congress cost-estimate feeds and estimate documents.
- [Congress bulk status](sources/congress-bulk-status.md): one BILLSTATUS zip per Congress and bill type, every member proved or refused with its digest · [guide code tables](sources/billstatus-guide.md): the BILLSTATUS guide's own bill-type sentence and code tables.
- [GovInfo package bodies](sources/govinfo-bodies.md): a report, hearing, Record, document or directory body by package id, identity proved from the summary and MODS before any body byte.
- [Legislators crosswalk](sources/legislators.md): the community legislators JSON as the bioguide, LIS and FEC identifier crosswalk, pinned by capture.
- [Appropriations press releases](sources/press-releases.md): the House and Senate Appropriations Committees' RSS feeds at their two live URLs, every channel and item field kept, identity proved from the channel body.
- [Roll-call votes](sources/congress-votes.md): House Clerk and Senate LIS vote XML by locator, identity proved against the file, tallies and every member's vote with bioguide ids through the legislators crosswalk.
- [Committee rosters](sources/committee-rosters.md): the Congress.gov committee route beside the House Clerk's and Senate's roster files, whose assignments are proved from each file's own Congress statement.
- [Agency report blocks](sources/agency-report-blocks.md): the committee-report heading splitter over extracted page text and the two report-section aggregates, measured on real reports · [agency report readers](sources/agency-reports.md): native FOIA XML and Oversight.gov HTML for agency-report inputs.
- [Bill versions](sources/congress-bill-versions.md): the sealed version-code vocabulary against the publisher's measured codes, format choice by rendition folder, and bill PDFs through the GovInfo body acquirer.
- [Bill tree and section diff](sources/congress-bill-tree.md): the DeltaTrack engine as a pinned dependency behind the `bill-diff` extra, with thin adapters that gate bytes through this repo's XML entry, keep an inventory of dropped elements, and shape diff records with provenance.
- [Interpretation](interpretation.md): shared judgment over publisher facts, rules in tables and findings that name the rule: bill stage, money bills, bill signals, vote, release and member matching, section classification and summaries.
- [Reconstruction](reconstruction.md): deterministic structure from text renditions where retrieval has nothing structured to give -- evidence-linked nodes that name the rule that placed them, serialization to a pinned vocabulary with a source-map sidecar, five validation findings and an acceptance gate; the CFR benchmark measures it.
- [Tables](tables.md): the thirty-five table contracts spicy-regs hosts, each with grain, identity, version column, supplier and per-column descriptions, and the one-pass bill-family build behind them.
- [GovInfo metadata](sources/govinfo-metadata.md): published field definitions and mapped source records · [preservation metadata (PREMIS)](sources/govinfo-premis.md): retained GovInfo PREMIS 2 XML and digest comparison.
- [Captured public comments](sources/public-comments.md)
- [Fetcher formats](fetcher-formats.md): current inputs and XML/JSON opportunities.
- [Source-field references](source-reference.md) · [Documented-value drift](source-domain-drift.md)
- [FEC acquisition](sources/fec.md): official JSON/XML metadata and separate originals · [bulk originals](sources/fec-bulk.md) · [positional rows](sources/fec-rows.md) · [filing fields](sources/fec-filing-fields.md).
- [FEC research and integration handoff](research/fec-data-2026-09-11.md): inventory, bulk acquisition plan and retained evidence.
- [BillTrax intake plan](research/billtrax-port-2026-09-15.md): acquisition and parsing port from the sibling BillTrax app, phased with open decisions.
- [Legislative-branch data map](research/legislative-data-map-2026-09-18.md): what each Congress.gov, GovInfo and publisher route lists, from when, and which are integrated, ported or proposed; tables generated by `tools/analysis/legislative_data_map.py`.
- [Document capture schema](research/document-capture-schema-2026-09-19.md): one JSON shape for a captured federal document in any rendition, composing Rulespec's parent schema per family; six worked conversions produced by `tools/analysis/document_capture.py`.

## Change shared behavior

- [Architecture](architecture.md): find the implementation and tests.
- [Releases](releases.md): publication, checks and profile extensions.
- [Ownership](source-ownership.md): SpicyDocs, SpicyRegs, DocSpec and Rulespec.
- [Decisions](decisions.md): reasons for unusual rules and current formats.
- [Task status](simplification-todo.md): open follow-ups, completed work and deferrals · [pre-work inventory](remaining-source-prework.md): the reuse review captured before the source fidelity fixes.
- [Release specification](superpowers/specs/2026-08-25-source-native-release-spec.md): exact format requirements.

[Corpus diagnostics](../tools/README.md), [repository checks](../scripts/README.md)
and [documentation maintenance](documentation.md) have their own guides.
