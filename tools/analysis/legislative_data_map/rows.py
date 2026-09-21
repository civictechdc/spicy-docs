"""The map's route vocabulary and row judgments: what is measured and what each row claims."""

from __future__ import annotations

from dataclasses import dataclass

from tools.analysis.shared import JSON_TYPES

CURRENT_CONGRESS = 119
XML_TYPES = ("text/xml", "application/xml", "application/rss+xml", "application/atom+xml")

# --- what is measured ---------------------------------------------------------


@dataclass(frozen=True)
class CongressRoute:
    """One Congress.gov collection route: its list key, its per-Congress path when it has one, and the unit
    its descent floor counts in."""

    route: str
    records_key: str
    descent: str | None = None
    start: int = CURRENT_CONGRESS
    unit: str = "congress"


CONGRESS_ROUTES = (
    CongressRoute("bill", "bills", "bill/{c}"),
    CongressRoute("amendment", "amendments", "amendment/{c}"),
    CongressRoute("summaries", "summaries", "summaries/{c}"),
    CongressRoute("law", "bills", "law/{c}"),
    CongressRoute("committee-report", "reports", "committee-report/{c}"),
    CongressRoute("committee-print", "committeePrints", "committee-print/{c}"),
    CongressRoute("committee-meeting", "committeeMeetings", "committee-meeting/{c}"),
    CongressRoute("hearing", "hearings", "hearing/{c}"),
    CongressRoute("nomination", "nominations", "nomination/{c}"),
    CongressRoute("treaty", "treaties", "treaty/{c}"),
    CongressRoute("house-communication", "houseCommunications", "house-communication/{c}"),
    CongressRoute("senate-communication", "senateCommunications", "senate-communication/{c}"),
    CongressRoute("house-requirement", "houseRequirements"),
    CongressRoute("house-vote", "houseRollCallVotes", "house-vote/{c}"),
    CongressRoute("member", "members", "member/congress/{c}"),
    CongressRoute("committee", "committees", "committee/{c}"),
    CongressRoute(
        "daily-congressional-record", "dailyCongressionalRecord", "daily-congressional-record/{c}", 172, unit="volume"
    ),
    CongressRoute(
        "bound-congressional-record", "boundCongressionalRecord", "bound-congressional-record/{c}", 2020, unit="year"
    ),
    CongressRoute("crsreport", "CRSReports"),
)

GOVINFO_COVERAGE = (
    "BILLS", "BILLSTATUS", "BILLSUM", "PLAW", "STATUTE", "COMPS", "CRPT", "CHRG", "CREC", "CRECB",
    "CPRT", "CDOC", "CDIR", "HMAN", "SMAN", "GOVMAN", "PAI", "CCAL", "HOB", "USCODE",
)  # fmt: skip

SAMPLES = {
    "clerk-vote": ("https://clerk.house.gov/evs/2025/roll240.xml", XML_TYPES),
    "senate-vote": ("https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml", XML_TYPES),
    "senate-nomination-feed": ("https://www.senate.gov/legislative/LIS/nominations/NomWithdrawn.xml", XML_TYPES),
    "house-memberdata": ("https://clerk.house.gov/xml/lists/MemberData.xml", XML_TYPES),
    "house-members-xml": ("https://member-info.house.gov/members.xml", XML_TYPES),
    "senate-cvc": ("https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml", XML_TYPES),
    "senate-contact": ("https://www.senate.gov/general/contact_information/senators_cfm.xml", XML_TYPES),
    "senate-hearings": ("https://www.senate.gov/general/committee_schedules/hearings.xml", XML_TYPES),
    "senate-calendar": ("https://www.senate.gov/legislative/2025_schedule.xml", XML_TYPES),
    "docs-house-floor-rss": ("https://docs.house.gov/BillsThisWeek-RSS.xml", XML_TYPES),
    "lda-filings": ("https://lda.gov/api/v1/filings/?page_size=1", JSON_TYPES),
    "lda-contributions": ("https://lda.gov/api/v1/contributions/?page_size=1", JSON_TYPES),
    "legislators-current-json": (
        "https://unitedstates.github.io/congress-legislators/legislators-current.json",
        JSON_TYPES,
    ),
    "legislators-historical-json": (
        "https://unitedstates.github.io/congress-legislators/legislators-historical.json",
        JSON_TYPES,
    ),
    "crs-appropriations-table": ("https://crsreports.congress.gov/AppropriationsStatusTable", ("text/html",)),
}


# --- the judgments ------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One map row: the judgment, the measurement it reads, and the repo evidence a claim rests on."""

    table: str
    subject: str
    data: str
    route: str
    status: str
    credential: str
    note: str
    measure: tuple[str, str] | None = None
    evidence: tuple[str, ...] = ()


KEY = "api.data.gov key"
NONE = "none"
A, B, C, D = "A", "B", "C", "D"
ROWS = (
    # Table A: Congress.gov API. One credential family, one pagination contract, one reader.
    Row(A, "bills", "Bill metadata, status, text versions", "`bill`", "have", KEY,
        "`congress/bill_acquisition.py`, `bill_status.py`, `bill_text.py`", ("congress", "bill"),
        ("src/spicy_docs/sources/congress/bill_acquisition.py", "src/spicy_docs/sources/congress/bill_status.py",
         "src/spicy_docs/sources/congress/bill_text.py")),
    Row(A, "bills", "CRS bill summaries", "`summaries`", "have", KEY,
        "a typed field of bill acquisition (`congress-bills.md:48`); the list route declared 6 records, all 119th, so it is no inventory",
        ("congress", "summaries"),
        ("docs/sources/congress-bills.md",)),
    Row(A, "bills", "Amendments listing", "`amendment`", "have", KEY,
        "route table in `congress/listing.py` (landed 2026-09-19); BillTrax's `fetchAmendments` retires against it, carrying the real `amendment.status` (ledger #7)",
        ("congress", "amendment"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "bills", "Committee-referred bills", "`committee/{chamber}/{code}/bills`", "have", KEY,
        "route table in `congress/listing.py`; the list nests its array under a wrapper, which the shared reader now reads by path; sort ignored, date window honored (measured 2026-09-19)",
        None, ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "bills", "Amendment text", "`amendment/.../text` where present", "candidate", KEY,
        "the listing port carries no text; amendment text otherwise lives in the Record and on rules.house.gov", None),
    Row(A, "laws", "Enacted bills list", "`law/{c}`", "have", KEY,
        "listing route landed in `congress/listing.py`: the one cheap enumeration of enacted bills per Congress (108 rows for the "
        "119th, each with the bill and its law number); law bodies are PLAW USLM (Table B)", ("congress", "law"),
        ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "votes", "Vote references on bill actions (`recordedVotes`)", "`bill/{c}/{type}/{n}/actions`", "have", KEY,
        "route table in `congress/listing.py`; sort and date window both ignored by the publisher (measured 2026-09-19); BillTrax's `sync-roll-call-votes.ts` retires against it",
        None, ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "votes", "House member-level votes", "`house-vote/{c}/{session}/{roll}/members`", "candidate", KEY,
        "not in the port plan; bioguide-keyed; names the Clerk XML as `sourceDataURL`; the list ignores sort and its default order is "
        "not by update date, so freshness is a floor", ("congress", "house-vote")),
    Row(A, "committees", "Committee reports", "`committee-report` (+ `/text`)", "have", KEY,
        "listing route landed in `congress/listing.py` 2026-09-19; report bodies come from the GovInfo body fetch (Table B)", ("congress", "committee-report"),
        ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "committees", "Hearings", "`hearing`", "have", KEY,
        "listing route landed in `congress/listing.py` 2026-09-19; transcript bodies come from the GovInfo body fetch (Table B)", ("congress", "hearing"),
        ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "committees", "Committee meetings (scheduled)", "`committee-meeting`", "have", KEY,
        "listing route landed in `congress/listing.py`; overlaps docs.house.gov and the Senate hearings calendar; API-first",
        ("congress", "committee-meeting"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "committees", "Committee prints", "`committee-print`", "have", KEY,
        "listing route landed in `congress/listing.py`; low volume; take with reports",
        ("congress", "committee-print"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "committees", "Committee rosters", "`committee`", "have", KEY,
        "listing route landed in `congress/listing.py`; API-first over the Clerk and Senate XML rosters",
        ("congress", "committee"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "members", "Members", "`member`", "have", KEY,
        "listing route landed in `congress/listing.py`; bioguide-keyed; API-first over Bioguide bulk and the House/Senate XML",
        ("congress", "member"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "nominations", "Nominations", "`nomination`", "have", KEY,
        "listing route landed in `congress/listing.py` 2026-09-19; the first coverage of nominations in the repo; the nine Senate LIS feeds stay a cross-check",
        ("congress", "nomination"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "treaties", "Treaties", "`treaty`", "have", KEY,
        "listing route landed in `congress/listing.py`; not previously mapped", ("congress", "treaty"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "record", "Daily Congressional Record", "`daily-congressional-record`", "have", KEY,
        "listing route landed in `congress/listing.py`; the primary floor record and the legislative-day calendar: one issue per "
        "day either chamber met, pro forma days included, with House and Senate sections saying which; the Clerk floor summary is "
        "its digest", ("congress", "daily-congressional-record"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "record", "Bound Congressional Record", "`bound-congressional-record`", "candidate", KEY,
        "historical only; take on a historical-reach need", ("congress", "bound-congressional-record")),
    Row(A, "communications", "House executive communications", "`house-communication` (+ detail)", "have", KEY,
        "listing route landed in `congress/listing.py` 2026-09-19; typed: isRulemaking, CRA authority, committee referral with systemCode and date, matching requirement, "
        "RIN in reportNature (17 of 25 sampled are rulemakings with a RIN); the RIN resolves in the Federal Register API by its structured filter, "
        "so this is the bridge from this repo's regulatory sources to Congress; `congress/record_communications.py` also reads House CREC granules through "
        "`parse_granule_body`, with `shape_record_communication` in `schemas/congress_index_tables.py` retaining the Record provenance; committee-name-to-code resolution remains open",
        ("congress", "house-communication"), ("src/spicy_docs/sources/congress/listing.py",
         "src/spicy_docs/sources/congress/record_communications.py", "src/spicy_docs/schemas/congress_index_tables.py")),
    Row(A, "communications", "Senate executive communications", "`senate-communication`", "have", KEY,
        "listing route landed in `congress/listing.py`; abstract, committee referral and Record date only; no rulemaking flag, "
        "authority or RIN field (sampled)", ("congress", "senate-communication"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "reference", "House reporting requirements", "`house-requirement` (+ `/matching-communications`)", "have", KEY,
        "listing route landed in `congress/listing.py`; 3,226 requirements, each with legal authority, frequency, agency and its "
        "matching communications; requirement 8070's 92,450-row CRA list (A6) walked in full and histogrammed by Congress, detail "
        "records resolving from the 114th on (28.9% of the walked rows, not a useful share by the proposal's rule); every "
        "requirement's own update date is 2021-11-05, so the requirement list itself is a snapshot; the index of the agency "
        "reports to Congress that BillTrax takes as uploads, entered from the communication side",
        ("congress", "house-requirement"), ("src/spicy_docs/sources/congress/listing.py",)),
    Row(A, "crs", "CRS report metadata and summaries", "`crsreport/{id}`", "have", KEY,
        "`crs_summaries.py`; the port plan names its query-param key (`:54`) as the legacy exception, not the pattern to clone",
        ("congress", "crsreport"),
        ("src/spicy_docs/sources/congress/crs_summaries.py", "src/spicy_docs/sources/congress/listing.py")),
    # Table B: GovInfo API and bulkdata. Discovery and MODS are collection-agnostic; bodies are per collection.
    Row(B, "bills", "BILLSTATUS bulk ZIP", "`bulkdata/BILLSTATUS`", "have", NONE,
        "`congress/bulk_status.py` (landed 2026-09-19): one Congress and one bill type per call, per-member outcomes with digests, bounds from the measured sizes; "
        "the parser now reads both publisher summary placements and 0 of 1,566 H.Res. files refuse", ("govinfo", "BILLSTATUS"),
        ("src/spicy_docs/sources/congress/bulk_status.py", "src/spicy_docs/reading/zip_archive.py")),
    Row(B, "bills", "Bill text bulk ZIP", "`bulkdata/BILLS`", "rejected", NONE,
        "derived re-export of the routes in use; revisit only as a resync optimization", ("govinfo", "BILLS")),
    Row(B, "bills", "Bill summaries bulk", "`bulkdata/BILLSUM`", "rejected", NONE,
        "CRS bill summaries already arrive as a typed bill field (Table A)", ("govinfo", "BILLSUM")),
    Row(B, "bills", "Bill PDFs", "`content/pkg/BILLS-…/pdf`", "have", NONE,
        "`congress/bill_pdf.py`: ported from BillTrax's `govinfo-pdf-fetch.ts` fetch half; the slug map is a sealed vocabulary",
        None, ("src/spicy_docs/sources/congress/bill_pdf.py",)),
    Row(B, "laws", "Public and private laws (PLAW)", "`bulkdata/PLAW` USLM", "have", NONE, "`govinfo/uslm.py`",
        ("govinfo", "PLAW"), ("src/spicy_docs/sources/govinfo/uslm.py",)),
    Row(B, "laws", "Statute compilations (COMPS)", "`bulkdata/COMPS` USLM", "have", NONE, "`govinfo/uslm_acquisition.py`",
        ("govinfo", "COMPS"), ("src/spicy_docs/sources/govinfo/uslm_acquisition.py",)),
    Row(B, "laws", "Statutes at Large", "`bulkdata/STATUTE`", "candidate", NONE,
        "one XML per volume; the only XML route for every law before PLAW bulk begins", ("govinfo", "STATUTE")),
    Row(B, "committees", "Committee report bodies", "`CRPT` package body", "have", KEY,
        "`govinfo/body_acquisition.py` (landed 2026-09-19): summary, then MODS, then the body, identity proved before any body byte; the offered formats "
        "are read from MODS because the summary names none for this collection", ("govinfo", "CRPT"), ("src/spicy_docs/sources/govinfo/body_acquisition.py", "src/spicy_docs/sources/govinfo/bodies.py")),
    Row(B, "committees", "Hearing transcript bodies", "`CHRG` package body", "have", KEY,
        "`govinfo/body_acquisition.py`: `GovInfoBodyAcquirer` fetches the transcript; `schemas/hearing_bill_link_tables.py` adds `shape_hearing_bill_link` "
        "for source-keyed MODS cover and House agenda links, distinguishing held-on from noticed bills; other link sources remain unimplemented",
        ("govinfo", "CHRG"), ("src/spicy_docs/sources/govinfo/body_acquisition.py", "src/spicy_docs/sources/govinfo/bodies.py",
         "src/spicy_docs/schemas/hearing_bill_link_tables.py")),
    Row(B, "committees", "Congressional documents", "`CDOC` package body", "have", KEY,
        "same module; CDOC carries treaty documents (`CDOC-119tdoc2` resolved in the flow pass)", ("govinfo", "CDOC"),
        ("src/spicy_docs/sources/govinfo/body_acquisition.py", "src/spicy_docs/sources/govinfo/bodies.py")),
    Row(B, "committees", "Committee prints", "`CPRT` package body", "have", KEY,
        "`govinfo/bodies.py`: `parse_package_id` accepts the measured HPRT/SPRT/JPRT grammar; `GovInfoBodyAcquirer` in `govinfo/body_acquisition.py` "
        "fetches the MODS-offered rendition with identity checks", ("govinfo", "CPRT"),
        ("src/spicy_docs/sources/govinfo/bodies.py", "src/spicy_docs/sources/govinfo/body_acquisition.py")),
    Row(B, "record", "Congressional Record bodies", "`CREC` package and granule bodies (daily)", "have", KEY,
        "`govinfo/bodies.py`, `govinfo/body_acquisition.py`: `GovInfoBodyAcquirer` accepts split-day package suffixes and `acquire_granule` "
        "proves the granule's identity and package membership before fetching its body", ("govinfo", "CREC"),
        ("src/spicy_docs/sources/govinfo/body_acquisition.py", "src/spicy_docs/sources/govinfo/bodies.py")),
    Row(B, "record", "Bound Congressional Record bodies", "`CRECB` package body", "candidate", KEY,
        "`govinfo/bodies.py`: the sealed body grammar has no CRECB entry, so `parse_package_id` refuses it before acquisition; "
        "discovery coverage does not establish a supported body path; widening requires retained measurement", ("govinfo", "CRECB"),
        ("src/spicy_docs/sources/govinfo/bodies.py",)),
    Row(B, "reference", "Congressional Directory", "`CDIR` package body", "have", KEY,
        "same module; offers PDF and text, the PDF above the evidence bound", ("govinfo", "CDIR"), ("src/spicy_docs/sources/govinfo/body_acquisition.py", "src/spicy_docs/sources/govinfo/bodies.py")),
    Row(B, "reference", "Government Manual", "`bulkdata/GOVMAN`", "candidate", NONE, "clean org XML", ("govinfo", "GOVMAN")),
    Row(B, "reference", "House Rules and Manual", "`bulkdata/HMAN`", "candidate", NONE, "clean XML", ("govinfo", "HMAN")),
    Row(B, "reference", "Privacy Act Issuances", "`bulkdata/PAI`", "rejected", NONE, "biennial SOR descriptions; no consumer",
        ("govinfo", "PAI")),
    Row(B, "reference", "Congressional Pictorial Directory", "GovInfo collection", "rejected", KEY, "Bioguide and `member` cover it"),
    Row(B, "reference", "MODS, PREMIS, discovery", "`packages`, `granules`, `published`, `collections`", "have", KEY,
        "`govinfo/mods.py`, `premis.py`, `discovery.py`", None,
        ("src/spicy_docs/sources/govinfo/mods.py", "src/spicy_docs/sources/govinfo/premis.py",
         "src/spicy_docs/sources/govinfo/discovery.py")),
    Row(B, "committees", "House committee activity reports", "`CRPT` published listing and package bodies", "have", KEY,
        "`govinfo/activity_reports.py`: `is_activity_report` selects CRPT titles; `schemas/document_citation_tables.py` adds `shape_activity_report` "
        "and `shape_document_citation`; `schemas/bill_action_tables.py` adds `shape_bill_committee_action` for interpreted print actions; "
        "the measured title rule misses two of seventeen reports, and CHA monthly PDFs remain unimplemented",
        None, ("src/spicy_docs/sources/govinfo/activity_reports.py", "src/spicy_docs/schemas/document_citation_tables.py",
         "src/spicy_docs/schemas/bill_action_tables.py")),
    Row(B, "spending", "Report of the Secretary of the Senate", "`GPO-CDOC-…` package and granule PDFs", "have", KEY,
        "`schemas/senate_expenditure_tables.py`: `shape_senate_expenditure_rows` publishes ruled rows and funding blocks; `govinfo/bodies.py` "
        "and `govinfo/body_acquisition.py` support GPO-CDOC reprints; payee/payment parsing and later report sections remain unqualified",
        ("cdtf", "104"), ("src/spicy_docs/schemas/senate_expenditure_tables.py", "src/spicy_docs/sources/govinfo/bodies.py",
         "src/spicy_docs/sources/govinfo/body_acquisition.py")),
    Row(B, "reference", "President's Budget volumes (including Appendix)", "`BUDGET-{year}-{part}`", "have", KEY,
        "`schemas/budget_volume_tables.py`: `shape_budget_volume` publishes volume facts and citation counts; `govinfo/bodies.py` accepts thirteen measured parts, "
        "with CLIMATE/DB/TAB bodies at granules and LRB XLS-only, outside the body formats; `govinfo/body_acquisition.py` follows the offered renditions",
        ("cdtf", "63"), ("src/spicy_docs/schemas/budget_volume_tables.py", "src/spicy_docs/sources/govinfo/bodies.py",
         "src/spicy_docs/sources/govinfo/body_acquisition.py")),
    # Table C: publisher XML, feeds and sites. Keyless; identity is what the sample shows.
    Row(C, "votes", "House per-vote XML", "`clerk.house.gov/evs/{year}/roll{N}.xml`", "have", NONE,
        "`congress/votes.py`: the `house-vote` API names this file as its source; bioguide-keyed", ("sample", "clerk-vote"),
        ("src/spicy_docs/sources/congress/votes.py",)),
    Row(C, "votes", "Senate per-vote XML", "`senate.gov/legislative/LIS/roll_call_votes/vote{c}{s}/vote_{c}_{s}_{n}.xml`",
        "have", NONE,
        "`congress/votes.py`: LIS-keyed, not bioguide; no Congress.gov route exists, so this is the only source; `votes.py` also "
        "gains the session's vote-menu index -- `parse_senate_vote_menu` reads the file into a `SenateVoteMenu`, identity proved "
        "from its own congress and session; `VoteAcquirer`'s `list_senate_votes` fetches and parses one keylessly into a "
        "`SenateVoteMenuAcquisition`; `locator_from_menu_entry` builds the `VoteLocator` for one entry",
        ("sample", "senate-vote"), ("src/spicy_docs/sources/congress/votes.py",)),
    Row(C, "members", "House MemberData.xml", "`clerk.house.gov/xml/lists/MemberData.xml`", "have", NONE,
        "`congress/committee_rosters.py`: `CommitteeRosterAcquirer` and `parse_house_member_data` read current members and committee assignments, "
        "prove Congress/session, and retain vacancies and empty-assignment counts", ("sample", "house-memberdata"),
        ("src/spicy_docs/sources/congress/committee_rosters.py",)),
    Row(C, "members", "House members.xml extras", "`member-info.house.gov/members.xml`", "candidate", NONE,
        "photos and social; only if the API lacks a needed field", ("sample", "house-members-xml")),
    Row(C, "members", "Senate committee XML", "`senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml`", "have", NONE,
        "`congress/committee_rosters.py`: `CommitteeRosterAcquirer` and `parse_senate_cvc` read current assignments and both member ids; "
        "the file states no Congress, so that value remains caller-supplied; the historical LIS crosswalk stays in `sources/legislators.py`",
        ("sample", "senate-cvc"), ("src/spicy_docs/sources/congress/committee_rosters.py",)),
    Row(C, "members", "Senate contact XML", "`senate.gov/general/contact_information/senators_cfm.xml`", "rejected", NONE,
        "cvc covers it", ("sample", "senate-contact")),
    Row(C, "members", "Bioguide bulk JSON", "`bioguide.congress.gov`", "rejected", NONE,
        "the `member` route is bioguide-keyed and tier-1 but its floor measured at the 68th Congress; Bioguide holds the earlier "
        "members, so take it only for them or for biography text", ("cdtf", "67")),
    Row(C, "nominations", "Senate LIS nomination feeds (9)", "`senate.gov/legislative/LIS/nominations/Nom{Category}.xml`",
        "candidate", NONE, "alternative to the `nomination` API; take only for fields the API lacks",
        ("sample", "senate-nomination-feed")),
    Row(C, "proceedings", "House committee repository", "`docs.house.gov/meetings/.../*.xml`", "have", NONE,
        "`congress/house_committee_repository.py`: `parse_house_committee_meeting` reads one retained agenda and `house_meeting_xml_locator` builds "
        "its known address; BR documents supply noticed-bill links through `schemas/hearing_bill_link_tables.py`; first-fetch discovery remains unimplemented",
        None, ("src/spicy_docs/sources/congress/house_committee_repository.py", "src/spicy_docs/schemas/hearing_bill_link_tables.py")),
    Row(C, "proceedings", "House floor repository", "`docs.house.gov/floor` (weekly XML + RSS)", "candidate", NONE,
        "floor documents remain unimplemented; the RSS measured 38.9 MB on 2026-09-18, so the weekly XML is the proposed route",
        ("sample", "docs-house-floor-rss")),
    Row(C, "proceedings", "House Rules Committee", "`rules.house.gov`", "candidate", NONE,
        "amendment text and rules for floor bills; fills part of the amendment-text gap", ("cdtf", "85")),
    Row(C, "proceedings", "House floor summary", "`clerk.house.gov/floorsummary/floor-download.aspx` + RSS", "candidate", NONE,
        "timestamped floor chronology; unsampled", ("cdtf", "78")),
    Row(C, "proceedings", "Senate hearings calendar", "`senate.gov/general/committee_schedules/hearings.xml`", "candidate", NONE,
        "forward-looking only", ("sample", "senate-hearings")),
    Row(C, "proceedings", "Senate session calendar", "`senate.gov/legislative/{year}_schedule.xml`", "rejected", NONE,
        "lists recess periods and one convene date only (the sample's `dates` holds 15 `date` entries for 2025), never legislative "
        "days; actual days derive from Record issues", ("sample", "senate-calendar")),
    Row(C, "lobbying", "Senate LDA filings", "`lda.gov/api/v1/filings`", "have", "optional token", "`lda.py`",
        ("sample", "lda-filings"), ("src/spicy_docs/sources/lda.py",)),
    Row(C, "lobbying", "LDA contributions, registrants, clients, lobbyists", "`lda.gov/api/v1/{contributions,…}`", "candidate",
        "optional token", "URL builders on the existing family", ("sample", "lda-contributions")),
    Row(C, "lobbying", "House LDA filings", "`lobbyingdisclosure.house.gov`", "candidate", NONE, "the other half of LDA",
        ("cdtf", "81")),
    Row(C, "ethics", "House Clerk disclosures (financial, travel, mass comms, post-employment)", "clerk microsites", "rejected",
        NONE, "search-site PDFs; take per collection when a need names one", ("cdtf", "70")),
    Row(C, "ethics", "Senate financial disclosure and gifts", "`efdsearch.senate.gov`", "rejected", NONE,
        "agreement-gated search; not worth a driver", ("cdtf", "108")),
    Row(C, "spending", "House Statement of Disbursements", "`house.gov`, CSV since 2016", "candidate", NONE,
        "USAspending excludes Congress", ("cdtf", "86")),
    Row(C, "spending", "PLUM report", "`opm.gov`, annual", "candidate", NONE,
        "\"thousands\" of filled and vacant senior positions per the catalog; no count verified", ("cdtf", "64")),
    Row(C, "gao", "GAO reports and testimony feed, files", "`gao.gov` RSS, `files.gao.gov`", "have", NONE,
        "`gao/rss.py`, `gao/files.py`", ("cdtf", "19"), ("src/spicy_docs/sources/gao/rss.py", "src/spicy_docs/sources/gao/files.py")),
    Row(C, "gao", "GAO product pages", "`gao.gov`", "have", "Zyte", "gated pages via `gao/native.py`", None,
        ("src/spicy_docs/sources/gao/native.py", "src/spicy_docs/sources/zyte.py")),
    Row(C, "gao", "GAO legal products and the restricted-reports list",
        "`gao.gov/legal/...`; `gao.gov/reports-testimonies/restricted`", "candidate", NONE,
        "appropriations-law decisions, bid protests and docket, other opinions", ("cdtf", "14")),
    Row(C, "cbo", "CBO cost-estimate feeds", "`cbo.gov/rss/{c}congress-cost-estimates.xml`", "have", NONE,
        "`sources/cbo.py` reads the keyless feed; `schemas/cost_estimate_tables.py` adds `shape_cbo_cost_estimate` for the BILLSTATUS index, "
        "and `interpretation/cbo_estimates.py` adds `read_cbo_estimate` for letters reprinted in CRPT bodies; CBO-hosted documents remain gated, "
        "and a reprinted letter is not assigned a publication id", ("cdtf", "6"),
        ("src/spicy_docs/sources/cbo.py", "src/spicy_docs/schemas/cost_estimate_tables.py",
         "src/spicy_docs/interpretation/cbo_estimates.py", "src/spicy_docs/schemas/committee_report_tables.py")),
    Row(C, "jct", "Joint Committee on Taxation estimates and publications", "`jct.gov`", "candidate", NONE,
        "support agency absent from the catalog and the map; unsampled"),
    Row(C, "uscode", "US Code, Popular Names, Table III", "OLRC `uscode.house.gov`", "have", NONE, "`uscode/`", ("cdtf", "62"),
        ("src/spicy_docs/sources/uscode/__init__.py",)),
    Row(C, "uscode", "OLRC classification tables (per Congress)", "`uscode.house.gov/classification`", "have", NONE,
        "`uscode/classification.py`: `parse_classification_table` reads each session's fixed-width rows in either order and proves Congress/session; "
        "`uscode/acquisition.py` adds index and table capture through `UsCodeAcquirer`", None,
        ("src/spicy_docs/sources/uscode/classification.py", "src/spicy_docs/sources/uscode/acquisition.py")),
    Row(C, "crs", "CRS report PDFs", "`congress.gov/crs_external_products`", "have", NONE,
        "`congress/crs_files.py`: `acquire_report` now prefers current-version HTML and retains refusals before PDF fallback; historical versions go directly to PDF", None,
        ("src/spicy_docs/sources/congress/crs_files.py",)),
    Row(C, "reference", "CISA .gov domain registry", "`github.com/cisagov/dotgov-data`", "candidate", NONE,
        "agency-entity resolution CSV", ("cdtf", "11")),
    Row(C, "reference", "Appropriations status table", "`crsreports.congress.gov` HTML", "rejected", NONE,
        "low structure; a keyless request is redirected (301) and the redirect target answers HTTP 403", ("sample", "crs-appropriations-table")),
    Row(C, "reference", "Agency congressional budget justifications (CBJs)", "agencies", "rejected", NONE,
        "PDF-heavy agency files remain rejected; the GovInfo budget-volume landing covers the President's Budget only"),
    # Table D: civil society, BillTrax-side, and interpretation.
    Row(D, "crs", "EveryCRSReport bulk", "`everycrsreport.com` (AmericaLabs)", "candidate", NONE,
        "versioned and broader than congress.gov; verify maintenance cadence first", ("cdtf", "4")),
    Row(D, "members", "Community legislators JSON (current + historical)", "`unitedstates.github.io/congress-legislators/legislators-*.json`",
        "have", NONE,
        "`sources/legislators.py` (landed 2026-09-19): keyless, byte-bounded, shape-checked, pinned by capture digest; an identifier hub keyed by bioguide with "
        "LIS, FEC candidate, ICPSR, GovTrack and OpenSecrets ids; presidential FEC ids carry no state letters, which the shape rule accepts", ("sample", "legislators-historical-json"),
        ("src/spicy_docs/sources/legislators.py",)),
    Row(D, "press", "Press releases (member and committee RSS)", "varied", "have", NONE,
        "`congress/press_releases.py`: the House and Senate Appropriations Committees' feeds, a clone of `gao/rss.py`'s shape",
        None, ("src/spicy_docs/sources/congress/press_releases.py",)),
    Row(D, "reports", "Agency uploaded-report PDFs", "BillTrax uploads", "have", NONE,
        "`agency_reports/report_blocks.py` ports `report-parser.ts`'s header split; `extraction/gpo_normalize.py` strips GPO "
        "print artifacts first", None,
        ("src/spicy_docs/sources/agency_reports/report_blocks.py", "src/spicy_docs/extraction/gpo_normalize.py")),
    Row(D, "votes", "Bill⇄vote matching", "BillTrax", "have", "n/a",
        "`interpretation/vote_matching.py`: joins a roll call to its bill from `recordedVotes` references only, replacing "
        "BillTrax's Senate-unreachable regex", None, ("src/spicy_docs/interpretation/vote_matching.py",)),
    Row(D, "members", "Member matching", "BillTrax", "have", "n/a",
        "`interpretation/member_matching.py`: bioguide, then the LIS crosswalk, then name, replacing BillTrax's name-only path",
        None, ("src/spicy_docs/interpretation/member_matching.py",)),
)  # fmt: skip
