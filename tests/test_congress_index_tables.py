"""The Congress.gov index tables' own rules, and the data-map edges re-run on the captured records.

``tests/test_table_contracts.py`` proves every shaped row against its column
tuple; this file proves the things a column tuple cannot: that the RIN rule
reads what the map measured, that the truth fold refuses an unmeasured
spelling, that a list-only row leaves the detail's columns NULL rather than
empty, and that the map's ``hearing→meeting``, ``meeting→hearing``,
``meeting→bill``, ``record→legislative-day``, ``record→package`` and
``treaty→cdoc`` edges resolve on the fixtures the same way they resolved live
(``docs/research/legislative-data-map-2026-09-18.md``, flow pass; the
hearing/meeting pair captured 2026-09-19, receipt
``committee-meetings-edges-2026-09-19/``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from spicy_docs.interpretation.communication_rin import REPORT_NATURE_RIN, RinFinding, rin_from_report_nature
from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.committee_report_tables import COMMITTEE_REPORTS, HEARING_TRANSCRIPTS
from spicy_docs.schemas.congress_index_tables import (
    CHAMBERS_RULE,
    COMMUNICATION_SOURCE_ROUTES,
    PACKAGE_ID_RULE_RECORD,
    PACKAGE_ID_RULE_TREATY,
    shape_committee_meeting,
    shape_house_communication,
    shape_record_communication,
    shape_record_issue,
    shape_treaty,
    treaty_package_id,
)
from spicy_docs.schemas.tables import UNIT_SEPARATOR, TableContractError, read_json_column
from spicy_docs.sources.congress.record_communications import normalized_entry_text

LISTINGS = Path(__file__).parent / "fixtures" / "listings"
NATURAL_KEY = re.compile(r"^\d+-[a-z]+-\d+$")


def _listing(name: str) -> dict:
    """Build a listing record from the given detail fields."""
    return json.loads((LISTINGS / name).read_text())


# ---------------------------------------------------------------------------
# A5: the RIN rule and the truth fold.
# ---------------------------------------------------------------------------


#: Report natures as the publisher wrote them, from the 2026-09-19 sample
#: (receipt ``house-communications-rin-2026-09-19/measurement.json``), and
#: what the measured rule reads off each.  The three prose cases are verbatim
#: publisher text; the last four are spellings the sample did not contain,
#: named so the rule's boundaries are stated rather than implied.
REPORT_NATURES = [
    (
        (
            "The Administration's final rule - Termination of Excess Insurance Coverage (RIN: 3133-AF97) "
            "received August 25, 2026."
        ),
        "3133-AF97",
        "RIN: 3133-AF97",
    ),
    ("Six notifications of a vacancy, designation of acting officer, nomination.", None, None),
    ("The semiannual report from January 1 - June 30, 2026.", None, None),
    ("A rule (RIN 1004-AF39) without the colon.", "1004-AF39", "RIN 1004-AF39"),
    ("A rule (RIN:1004-AF39) with no space.", "1004-AF39", "RIN:1004-AF39"),
    ("An EPA notice (FRL No. 13314-01-OCSPP), which is not a RIN.", None, None),
    ("a lowercase label (rin: 1004-af39) is not the publisher's spelling.", None, None),
]


@pytest.mark.parametrize(("nature", "rin", "matched"), REPORT_NATURES, ids=lambda value: str(value)[:32])
def test_the_rin_rule_reads_what_the_map_measured(nature: str, rin: str | None, matched: str | None) -> None:
    """The RIN rule returns the RIN with its label rule, or an unmatched finding."""
    finding = rin_from_report_nature(nature)
    assert finding == RinFinding(rin, "report_nature_rin_label" if rin else "unmatched", matched)


def test_a_missing_report_nature_is_unmatched_not_an_error() -> None:
    """A missing report nature is unmatched, while a non-string is a TypeError."""
    assert rin_from_report_nature(None) == RinFinding(None, "unmatched", None)
    with pytest.raises(TypeError):
        rin_from_report_nature(3133)  # type: ignore[arg-type]


def test_the_rule_is_the_maps_own_pattern() -> None:
    """The measured label over the one published RIN shape; the map tool now reads this same compiled rule."""
    assert REPORT_NATURE_RIN.pattern == r"RIN:?\s*(\d{4}-[A-Z]{2}\d{2})"


def test_the_captured_communication_carries_the_bridge_on_one_row() -> None:
    """EC 4752: rulemaking, RIN, referral with system code and date, requirement 8070, all on one row."""
    listed = _listing("congress-house-communication-list.json")["houseCommunications"][0]
    detail = _listing("congress-house-communication-detail.json")["houseCommunication"]
    row = shape_house_communication(listed, detail, rin=rin_from_report_nature(detail["reportNature"]))
    assert row["communication_id"] == "119-ec-4752"
    assert row["is_rulemaking"] == "true"
    assert row["rin"] == "3133-AF97"
    assert row["rin_rule"] == "report_nature_rin_label"
    assert row["referral_system_code"] == "hsba00"
    assert row["referral_date"] == "2026-09-17"
    assert row["matching_requirement_number"] == "8070"
    assert row["legal_authority"].startswith("5 U.S.C. 801(a)(1)(A)")
    assert row["url"] == listed["url"]
    assert TABLE_CONTRACTS["house_communications"].checked(row) is row


# --- the two eras of one contract ------------------------------------------------------


def _record_entries(granule_id: str):
    """The retained Record entries fixture."""
    from spicy_docs.extraction.body_text import rendition_text
    from spicy_docs.sources.congress.record_communications import parse_record_communications

    body = (Path(__file__).parent / "fixtures/record_communications" / f"{granule_id}.excerpt.htm").read_bytes()
    entries = parse_record_communications(
        rendition_text(body, rendition="htm").text,
        package_id=granule_id.split("-pt")[0],
        granule_id=granule_id,
    )
    return {entry.number: entry for entry in entries}


def _reconstructed(number: int = 4329):
    """The retained reconstructed-entry fixtures."""
    entry = _record_entries("CREC-2016-02-12-pt1-PgH815-4")[number]
    return entry, shape_record_communication(
        entry, congress=114, record_date="2016-02-12", rin=rin_from_report_nature(entry.report_nature)
    )


def test_a_reconstructed_row_carries_the_same_identity_and_the_granule_that_printed_it() -> None:
    """The point of one contract rather than two: the key is the publisher's own on both sides."""
    entry, row = _reconstructed()
    assert row["communication_id"] == "114-ec-4329"
    assert TABLE_CONTRACTS["house_communications"].key(row) == ("114", "ec", "4329")
    assert row["source_route"] == "congressional-record-granule"
    assert row["record_package_id"] == "CREC-2016-02-12"
    assert row["record_granule_id"] == "CREC-2016-02-12-pt1-PgH815-4"
    assert row["record_entry_text"] == entry.entry_text
    assert row["reconstruction_rule_version"] == entry.rule_version
    assert row["rin"] == "1218-AC97"
    assert row["referral_committee_name"] == "Education and the Workforce"
    # Measured on 264 of 264 retained referrals: the publisher's referralDate
    # equals its congressionalRecordDate.
    assert row["referral_date"] == row["congressional_record_date"] == "2016-02-12"
    assert TABLE_CONTRACTS["house_communications"].checked(row) is row


def test_contract_rule_one_a_reconstructed_rows_url_is_null() -> None:
    """The publisher's detail route 404s for every pre-114th communication; writing a url would lie."""
    _, row = _reconstructed()
    assert row["url"] is None
    listed = _listing("congress-house-communication-list.json")["houseCommunications"][0]
    assert shape_house_communication(listed, None)["url"] == listed["url"]


def test_contract_rule_two_the_source_route_decides_the_merge_not_the_update_date() -> None:
    """A reconstructed row has no ``update_date``, so the version column alone cannot order the two."""
    _, reconstructed = _reconstructed()
    detail = _listing("congress-house-communication-detail.json")["houseCommunication"]
    published = shape_house_communication(detail, detail)
    assert reconstructed["update_date"] is None
    assert published["update_date"] is not None
    assert published["source_route"] == COMMUNICATION_SOURCE_ROUTES[0] == "congress-gov-detail"
    assert reconstructed["source_route"] == COMMUNICATION_SOURCE_ROUTES[1]
    # Every provenance column is NULL on the publisher's own row, so a consumer
    # can tell the two apart on either column.
    assert [published[name] for name in ("record_package_id", "record_granule_id", "record_entry_text")] == [
        None,
        None,
        None,
    ]
    assert published["reconstruction_rule_version"] is None


def test_contract_rule_three_an_unresolved_split_is_null_beside_the_retained_sentence() -> None:
    """The split scored 88.4% held-out, under the declared 90%, so it does not publish at all."""
    entry, row = _reconstructed()
    assert row["submitting_official"] is None
    assert row["submitting_agency"] is None
    # The rule *did* resolve this one -- the NULL is the contract's decision,
    # not the parser failing -- and the sentence it resolved from is on the row.
    assert entry.split_resolved is True
    assert entry.from_clause in row["record_entry_text"]

    # The same holds for every other field the Record does not state.
    assert row["is_rulemaking"] is None
    assert row["matching_requirement_number"] is None
    assert row["referral_system_code"] is None
    assert row["session"] is None


def test_a_reconstructed_rows_abstract_is_the_value_the_publisher_would_have_carried() -> None:
    """`abstract` is the print under the four normalizations; `record_entry_text` is the print.

    They are two different strings on this row, and the difference is exactly
    what the publisher's own abstract does to the same sentence -- which is why
    the column carrying "the publisher's abstract" cannot be the raw print.
    """
    from spicy_docs.sources.congress.record_communications import (
        expand_public_law_abbreviation,
        expand_section_abbreviation,
        fold_en_dash,
        fold_print_dash,
        publisher_normalized,
    )

    entry, row = _reconstructed()
    assert row["record_entry_text"] == entry.entry_text
    assert row["abstract"] == publisher_normalized(entry.entry_text)
    assert row["abstract"] != row["record_entry_text"]

    # The whole difference, rule by rule, with nothing else moving.
    assert "final rule -- Maine" in row["record_entry_text"]
    assert "final rule - Maine" in row["abstract"]
    assert "Public Law 104-121, Sec. 251" in row["record_entry_text"]
    assert "Public Law 104-121, section 251" in row["abstract"]
    assert row["abstract"] == fold_print_dash(
        expand_public_law_abbreviation(expand_section_abbreviation(fold_en_dash(row["record_entry_text"])))
    )

    # And it is the publisher's own captured string for the same communication.
    published = _listing("congress-house-communication-detail-114-ec-4329.json")["houseCommunication"]["abstract"]
    assert row["abstract"] == publisher_normalized(normalized_entry_text(published))


def test_the_referral_publishes_the_records_own_words_and_no_system_code() -> None:
    """The names are a fact the print states; the identity is not, until a resolver exists.

    They are published because the Record's name is the committee's name on the
    day, and the referral count agrees with the publisher on 95.1% of held-out
    rows. They are not the publisher's spelling of the same committee -- 71.5%
    -- so nothing joins on them.
    """
    _, row = _reconstructed()
    assert row["referral_committee_name"] == "Education and the Workforce"
    assert row["referral_count"] == "1"
    assert read_json_column(row["committees_json"]) == [{"name": "Education and the Workforce"}]
    assert row["referral_system_code"] is None

    # The publisher's own row for the same communication spells it differently
    # and carries the code; that is the drift, and it is why the code is the key.
    published = _listing("congress-house-communication-detail-114-ec-4329.json")["houseCommunication"]
    assert published["committees"][0]["name"] == "Education and Workforce Committee"
    assert published["committees"][0]["systemCode"] == "hsed00"


def test_a_joint_referral_reconstructs_with_every_committee_in_committees_json() -> None:
    """A joint referral reconstructs with all three committees in committees_json and the first as
    referral_committee_name.
    """
    entry, row = _reconstructed(4350)
    assert row["referral_count"] == "3"
    assert [item["name"] for item in read_json_column(row["committees_json"])] == list(entry.committee_names)
    assert row["referral_committee_name"] == "Appropriations"


def test_the_truth_fold_takes_the_publishers_two_spellings_and_refuses_a_third() -> None:
    """The truth fold accepts the publisher's two boolean spellings, maps absent to None and refuses a third."""
    detail = _listing("congress-house-communication-detail.json")["houseCommunication"]
    assert shape_house_communication(detail, detail)["is_rulemaking"] == "true"
    assert shape_house_communication(detail, {**detail, "isRulemaking": "False"})["is_rulemaking"] == "false"
    assert shape_house_communication(detail, {**detail, "isRulemaking": None})["is_rulemaking"] is None
    with pytest.raises(TableContractError, match="isRulemaking"):
        shape_house_communication(detail, {**detail, "isRulemaking": "yes"})


def test_a_list_only_row_leaves_the_details_columns_null_and_a_detail_states_none_as_empty() -> None:
    """NULL is "not read"; ``[]`` and ``0`` are "the publisher stated none".

    The publisher omits ``matchingRequirements`` from a communication that matches no
    requirement (measured: 3 of 18 sampled carry no such key), so a detail without the key
    is the stated-none case, and the record here is the captured detail with that key removed.
    """
    rows = _listing("congress-house-communication-list.json")["houseCommunications"]
    detail = _listing("congress-house-communication-detail.json")["houseCommunication"]
    unread = shape_house_communication(rows[1], None)
    assert unread["communication_id"] == "119-ml-136"
    assert unread["committees_json"] is None and unread["referral_count"] is None
    assert unread["matching_requirements_json"] is None and unread["rin_rule"] is None
    assert unread["url"] == rows[1]["url"]

    none_stated = {key: value for key, value in detail.items() if key != "matchingRequirements"}
    stated = shape_house_communication(rows[0], none_stated)
    assert stated["matching_requirements_json"] == "[]"
    assert stated["matching_requirement_count"] == "0"
    assert stated["matching_requirement_number"] is None


# ---------------------------------------------------------------------------
# A7: the hearing/meeting chain.
# ---------------------------------------------------------------------------


def test_hearing_to_meeting_and_back_on_the_captured_pair() -> None:
    """The map's ``hearing→meeting`` and ``meeting→hearing`` edges, re-run on the fixtures.

    Jacket 64431 names event 119003 as its meeting; meeting 119003 names jackets 63019 and
    64431 back -- two, which is why ``hearing_jacket`` alone is not the whole fact.  The
    hearing's own ``formats[].url`` stem is the CHRG package ``hearing_transcripts`` is keyed
    on (the map's ``hearing→package`` rule), so the three tables join on real identifiers.
    """
    hearing = _listing("congress-hearing-detail.json")["hearing"]
    meeting = _listing("congress-committee-meeting-detail-119003.json")["committeeMeeting"]
    row = shape_committee_meeting(meeting, meeting)

    assert hearing["jacketNumber"] == 64431
    assert hearing["associatedMeeting"]["eventId"] == "119003" == row["event_id"]
    assert read_json_column(row["hearing_jackets_json"]) == ["63019", "64431"]
    assert row["hearing_jacket"] == "63019" and row["hearing_jacket_count"] == "2"
    assert row["meeting_type"] == "Hearing" and row["chamber"] == "house"
    assert row["witness_count"] == "3" and row["witness_document_count"] == "9"
    assert row["meeting_document_count"] == "70"
    urls = read_json_column(row["document_urls_json"])
    assert len(urls) == 79 and urls[0].endswith("HHRG-119-GO00-Bio-TollgaardM-20260304.pdf")
    assert row["bill_count"] == "0" and row["bill_ids_json"] == "[]"

    stems = {url.rsplit("/", 1)[-1].split(".")[0] for url in (entry["url"] for entry in hearing["formats"])}
    assert stems == {"CHRG-119hhrg64431"}
    assert HEARING_TRANSCRIPTS.columns[19:] == ("event_id", "body_completeness", "text_derivation")
    # Both tables are the same nineteen package columns plus their own
    # appendix: the hearing adds event_id, the report adds the CBO estimate
    # columns (B4), and only positions 3 and 4 are spelled differently. Both
    # then append the body-completeness pair last.
    shared = [index for index in range(19) if index not in (3, 4)]
    assert [HEARING_TRANSCRIPTS.columns[i] for i in shared] == [COMMITTEE_REPORTS.columns[i] for i in shared]
    assert HEARING_TRANSCRIPTS.columns[-2:] == COMMITTEE_REPORTS.columns[-2:]
    assert len(HEARING_TRANSCRIPTS.columns) == 22


def test_meeting_to_bill_on_the_captured_markup() -> None:
    """The map's ``meeting→bill`` edge (6 of 6 live) re-run: every related bill is a natural key."""
    listed = _listing("congress-committee-meeting-list.json")["committeeMeetings"][1]
    meeting = _listing("congress-committee-meeting-detail.json")["committeeMeeting"]
    assert listed["eventId"] == meeting["eventId"] == "119565"
    row = shape_committee_meeting(listed, meeting)
    bills = read_json_column(row["bill_ids_json"])
    assert len(bills) == len(meeting["relatedItems"]["bills"]) == 9
    assert all(NATURAL_KEY.fullmatch(bill) for bill in bills)
    assert bills[0] == "119-hr-1653"
    assert row["bill_count"] == "9" and row["meeting_type"] == "Markup"
    assert row["hearing_jacket"] is None and row["hearing_jackets_json"] == "[]"
    assert row["url"] == listed["url"]
    assert TABLE_CONTRACTS["committee_meetings"].checked(row) is row


# ---------------------------------------------------------------------------
# A10: the Record calendar, the treaty package, the registry.
# ---------------------------------------------------------------------------


def test_a_record_issue_names_the_chambers_that_met_and_its_package() -> None:
    """The map's ``record→legislative-day`` and ``record→package`` edges on issue 172/148."""
    rows = _listing("congress-daily-congressional-record-list.json")["dailyCongressionalRecord"]
    issue = _listing("congress-daily-congressional-record-detail.json")["issue"]
    row = shape_record_issue(rows[0], issue)
    assert (row["volume"], row["issue"]) == ("172", "148")
    # Only the Senate sat that day: the detail lists a Daily Digest and a Senate Section.
    assert row["chambers"] == "senate" and row["chambers_rule"] == CHAMBERS_RULE
    assert row["section_names"] == UNIT_SEPARATOR.join(["Daily Digest", "Senate Section"])
    assert row["package_id"] == "CREC-2026-09-18" and row["package_id_rule"] == PACKAGE_ID_RULE_RECORD
    assert row["article_count"] == "10"

    unread = shape_record_issue(rows[1], None)
    assert unread["issue"] == "147"
    assert unread["chambers"] is None and unread["chambers_rule"] is None
    assert unread["package_id"] is None and unread["sections_json"] is None


def test_a_treaty_resolves_to_its_cdoc_package() -> None:
    """The map's ``treaty→cdoc`` edge (2 of 2 live): treaty 119-2 is ``CDOC-119tdoc2``."""
    listed = _listing("congress-treaty-list.json")["treaties"][0]
    treaty = _listing("congress-treaty-detail.json")["treaty"][0]
    row = shape_treaty(listed, treaty)
    assert row["treaty_id"] == "119-2" and row["suffix"] == ""
    assert row["package_id"] == "CDOC-119tdoc2" and row["package_id_rule"] == PACKAGE_ID_RULE_TREATY
    # The publisher's own index terms name the same document number back.
    assert "Treaty Doc. 119-2" in read_json_column(row["index_terms_json"])
    assert row["short_title"].startswith("Tax Convention with Croatia")
    assert row["url"] == listed["url"]
    # A partitioned treaty's package id was never measured, so the rule declines it.
    assert treaty_package_id(119, 2, "A") is None
    assert treaty_package_id(None, 2, "") is None


def test_the_registry_holds_the_five_index_tables() -> None:
    """The registry holds the five index tables."""
    assert {"house_communications", "committee_meetings", "record_issues", "treaties", "nominations"} <= set(
        TABLE_CONTRACTS
    )
