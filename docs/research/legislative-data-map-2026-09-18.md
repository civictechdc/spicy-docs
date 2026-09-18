# Legislative-branch data map: coverage, candidates, sequencing

Status: reference + proposal, not started. Written 2026-09-18 against
spicy-docs `5d3626f` (v0.20.0-3) and the
[BillTrax port plan](billtrax-port-2026-09-15.md) (`a6b685f`/`2cc2f4e` pins).
Sources: the CDTF Legislative Branch Data Map
(<https://usgpo.github.io/innovation/data.json>, fetched 2026-09-18; 119
entries, ~35 machine-readable) reconciled against this repo's integrated
sources and the port phases. Candidates are proposals; nothing here is a
commitment until it has a `docs/decisions.md` record. Claims re-checked
2026-09-18 against the live data.json, GovInfo bulkdata listings,
api.congress.gov, and BillTrax `a6b685f`.

Scope: US Congress (House + Senate), legislative-branch support agencies
(CRS, CBO, GAO, Architect/Clerk-side offices), and the bill→law→code
pipeline. Judicial (CourtListener, Supreme Court), regulatory (FR, eCFR,
CFR annual editions, Unified Agenda) and executive-branch spending
(USAspending, SAM) sources exist in this repo but are out of scope here;
their CDTF entries were skipped on that boundary, not on merit.

## Status vocabulary

| Tag | Meaning |
|---|---|
| `have` | Integrated in spicy-docs today |
| `port N` | Arrives with BillTrax port phase N |
| `candidate` | Genuine gap; proposal only |
| `rejected` | Deliberate no, reason retained |

## Bills, resolutions, amendments, text

| Data | Route | Status | Note |
|---|---|---|---|
| Bills metadata/status/text-versions | Congress.gov v3 + GovInfo XML | `have` | `congress/bill_acquisition.py`, `bill_status.py`, `bill_text.py` |
| Amendments listing | Congress.gov API | `port 4` | replaces `fetchAmendments`; carry real `amendment.status` (ledger #7) |
| Committee-referred bills listing | Congress.gov API | `port 4` | replaces `fetchCommitteeBills` |
| BILLSTATUS bulk ZIP | GovInfo `/bulkdata/BILLSTATUS` | `port 6` | decision 2 (bulk-scope record) first; builds on `zip_archive.py` |
| Bill text bulk ZIP | GovInfo `/bulkdata/BILLS` | `rejected` | derived re-export of Congress.gov/GovInfo routes in use; revisit only as resync optimization |
| Bill summaries bulk | GovInfo `/bulkdata/BILLSUM` | `rejected` | CRS *bill* summaries already arrive as a typed field of bill acquisition (`congress-bills.md:48`); `crs_summaries.py` carries CRS *report* summaries, a different collection |
| Bill PDFs (GovInfo package PDFs, `content/pkg/BILLS-…/pdf`) | GovInfo | `port 5` | decision 1 (PDF identity semantics) first; slug map is a sealed vocabulary (port contract) |

## Votes

| Data | Route | Status | Note |
|---|---|---|---|
| Vote references on bill actions (`recordedVotes`: chamber, roll number, publisher URL) | Congress.gov API `/bill/{congress}/{type}/{n}/actions` | `port 4` | replaces `sync-roll-call-votes.ts`, which reads only these references; its unbounded 429 recursion (ledger #4) dies with the TS |
| House member-level votes | Congress.gov API `/house-vote/{congress}/{session}/{roll}/members` (bioguide-keyed; 5,079 votes listed 2026-09-18) or `clerk.house.gov/evs/{year}/roll{N}.xml` | `candidate` | not in the port plan; the API route is the tier-1 fit and names the Clerk XML as its `sourceDataURL` |
| Senate member-level votes | `senate.gov/legislative/votes_new.htm` per-vote XML | `candidate` | LIS-tagged, not bioguide; no Congress.gov route exists (`/senate-vote` answers 404), so the XML is the only source |
| Bill↔vote matching | BillTrax | `rejected` (here) | interpretation; stays BillTrax-side |

## Members, committees, crosswalks

| Data | Route | Status | Note |
|---|---|---|---|
| Community legislators YAML | `unitedstates/congress-legislators` | `rejected` | port decision: PyYAML forbidden, community source, ~6 portable lines |
| Bioguide bulk JSON | `bioguide.congress.gov` | `candidate` | publisher-canonical replacement for the rejected YAML if member matching ever needs more than bioguide IDs |
| House MemberData.xml | `clerk.house.gov/xml/lists/MemberData.xml` | `candidate` | members + committee assignments w/ codes, monthly |
| Senate committee XML | `senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml` | `candidate` | bioguide⇄LIS crosswalk, daily |
| House members.xml extras | `member-info.house.gov/members.xml` | `candidate` | photos/social; only if Bioguide lacks a needed field |
| Member matching | BillTrax | `rejected` (here) | interpretation |

## Nominations

| Data | Route | Status | Note |
|---|---|---|---|
| Senate nominations lifecycle (9 feeds: confirmed, pending-committee, pending-calendar, military, privileged, failed/returned, withdrawn) | `senate.gov/legislative/LIS/nominations/Nom{Category}.xml` | `candidate` | no nominations coverage anywhere in repo; orthogonal to BillTrax |

## Floor and committee proceedings

| Data | Route | Status | Note |
|---|---|---|---|
| House committee + floor repositories | `docs.house.gov/committee`, `/floor` (weekly XML + RSS on `/floor`; no JSON feed found on either) | `candidate` | strongest dovetail: the only proposed route for the port's re-hydration contract (`hearing_transcripts.text`, `committee_reports.text` in `catalog-tables.ts:54-59`), which today has no fetch route in either repo |
| House floor summary | `clerk.house.gov/floorsummary/floor-download.aspx` + RSS | `candidate` | timestamped floor chronology |
| Senate hearings calendar XML | `senate.gov/general/committee_schedules/hearings.xml` | `candidate` | forward-looking only |
| Senate session calendar | senate.gov per-year XML (`{year}_schedule.xml`) | `rejected` | trivial; take if ever load-bearing |
| Committee reports text | GovInfo CRPT (API collection, not bulkdata) | `candidate` | no route in either repo: spicy-docs names no CRPT source, and BillTrax `committee_reports` rows come only from uploads (`api/reports/route.ts:38`); the port's re-hydration contract implies capturing report bodies |
| House committee activity reports | GovInfo search over doctype HRPT (no bulkdata); CHA monthly PDFs | `rejected` | end-of-Congress PDF cadence; low value now |

## Laws and codification

| Data | Route | Status | Note |
|---|---|---|---|
| Public/private laws (PLAW) | GovInfo USLM + bulk | `have` | `govinfo/uslm.py` |
| Statute compilations (COMPS) | GovInfo | `have` | `govinfo/uslm_acquisition.py` |
| Statutes at Large bulk | GovInfo `/bulkdata/STATUTE` | `candidate` | volumes 1–137 (1789–2023), one XML per volume, no gaps; PLAW bulk starts at the 113th Congress (2013), so this is the only XML route for every earlier law |
| US Code, Popular Names, Table III | OLRC | `have` | `uscode/` |
| eCFR bulk mirror | GovInfo `/bulkdata/ECFR` | `rejected` | derived, catalog itself says "not an official legal edition"; eCFR API is canonical |
| Pre-1994 Federal Register PDFs | GovInfo FR collection | `rejected` | only residual FR gap; revisit on historical-reach need |

## CRS

| Data | Route | Status | Note |
|---|---|---|---|
| CRS report metadata/summaries (by report id) | Congress.gov v3 `/crsreport/{id}` | `have` | `crs_summaries.py`; the port plan names its query-param key (`:54`) as the legacy exception, so it is not the pattern to clone |
| CRS report PDFs | congress.gov crs-products | `have` | `crs_files.py` |
| EveryCRSReport bulk | `everycrsreport.com` (→ AmericaLabs) | `candidate` | versioned, broader than congress.gov's collection; civil society — verify maintenance cadence before relying |

## GAO / CBO

| Data | Route | Status | Note |
|---|---|---|---|
| Reports/testimony feed + PDFs | `gao.gov` RSS, `files.gao.gov` | `have` | `gao/rss.py`, `gao/files.py` |
| GAO product pages | `gao.gov` | `have` | gated pages via Zyte |
| GAO legal products (appropriations-law decisions, bid protests + docket, other legal opinions) and the restricted-reports list | `gao.gov/legal/...`; `gao.gov/reports-testimonies/restricted` | `candidate` | distinct collections beyond reports/testimony |
| CBO cost estimates/reports feeds | `cbo.gov` | `have` | behind bot wall |
| Agency uploaded-report PDFs | BillTrax uploads | `port 5` | `report-parser` ports; extraction channel |

## Lobbying, ethics, disclosures

| Data | Route | Status | Note |
|---|---|---|---|
| Senate LDA filings | `lda.gov/api/v1` (`lda.senate.gov/api` 301-redirects there) | `have` | `lda.py` |
| House LDA filings | `lobbyingdisclosure.house.gov` | `candidate` | the other half of LDA |
| House Clerk disclosures (financial, foreign travel, privately-sponsored travel, mass comms, post-employment) | clerk microsites | `rejected` | search-site PDFs; take per-collection when a need names one |
| Senate financial disclosure / gifts | efdsearch.senate.gov | `rejected` | JS/agreement-gated; hard fetch, not worth the scrape without a driver |

## Legislative-branch spending and staffing

| Data | Route | Status | Note |
|---|---|---|---|
| House Statement of Disbursements | clerk.house.gov, CSV since 2016 | `candidate` | USAspending excludes Congress |
| Secretary of the Senate report | senate.gov, PDF since 2011 | `rejected` | PDF-only; revisit if XML/CSV appears |
| PLUM Report (senior positions) | opm.gov, annual CSV | `candidate` | "thousands" of filled/vacant senior positions per the catalog; no count verified against the publisher |

## Reference and org data

| Data | Route | Status | Note |
|---|---|---|---|
| MODS/PREMIS metadata, GovInfo discovery | GovInfo | `have` | `govinfo/mods.py`, `premis.py`, `discovery.py` |
| Government Manual bulk | GovInfo `/bulkdata/GOVMAN` | `candidate` | clean org XML |
| House Rules & Manual bulk | GovInfo `/bulkdata/HMAN` | `candidate` | clean XML |
| Privacy Act Issuances bulk | GovInfo `/bulkdata/PAI` | `rejected` | biennial SOR descriptions; no current consumer |
| Pictorial Directory | GovInfo | `rejected` | Bioguide covers |
| Appropriations status table | crsreports.congress.gov HTML | `rejected` | HTML table; low structure |
| President's Budget Appendix / CBJs | OMB, agencies | `rejected` | PDF-heavy; OMB non-compliant on format |
| Press releases (member/committee RSS) | varied | `port` (unphased) | the RSS source in plan section A (cloning `gao/rss.py` discipline) is assigned to no phase; feed-URL unification is port decision 5, which blocks phase 2 |
| CISA .gov domain registry | github.com/cisagov/dotgov-data | `candidate` | agency-entity resolution CSV |

## Sequencing against the port

- **Phases 0–7**: no data.json candidate blocks or aids them. Port with the
  Congress.gov API routes already named in the plan.
- **Phase 4/8**: docs.house.gov committee/floor repositories belong here if
  adopted — they back the capture/re-hydration contract, not new
  interpretation. Land as tier-1 acquisition beside the Congress.gov
  endpoints, after the port contract is stable.
- **Member-level votes, STATUTE, nominations, SoD, PLUM, House LDA, GAO legal, CRPT**:
  independent of the port. Any adoption is a separate initiative with its
  own decision record; do not interleave with port phases.
- **Port conventions apply to every future candidate** (tier-1 first,
  credentials header-only, decision record for new scope, one
  `docs/sources/*.md` page per source).

## Catalog caveats (when citing the CDTF map)

- `CDTF-DATASET-97` ("Civilian Pending in Committee") has a copy-pasted
  description about presidential papers 2009–2016 and duplicates
  `CDTF-DATASET-102`'s URL. Its metadata is unreliable.
- `distribution.accessURL` is a bare publisher homepage on 115 of 119 entries
  (3 deep links, 1 missing), and sometimes the wrong publisher (USAspending's
  → oversight.gov). The real URL is `landingPage.accessURL`, nested in an
  object rather than the DCAT string.
- Most entries are landing pages; `accrualPeriodicity` is present but
  format/coverage fields are absent throughout.
