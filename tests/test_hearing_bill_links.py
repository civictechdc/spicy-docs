"""The two hearing-to-bill link rules, over the records the measurement retained.

Every number asserted here is one the
[linkage note](../docs/research/hearing-bill-linkage-2026-09-20.md) states and
the receipt's own offline recompute produced, re-derived through the product
code rather than restated: 12 `COVER` bills on one hearing, 8 against 9 on the
hearing that has both sources, 0 on a Senate record, and one `BR` document
refused for naming no number.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.interpretation.hearing_bill_links import (
    HEARING_BILL_LINK_RULE_VERSION,
    HEARING_BILL_LINK_RULES,
    HEARING_BILL_LINK_RULES_BY_NAME,
    LINK_SOURCES,
    RELATIONS,
    HearingBillLinkError,
    agenda_links,
    check_meeting_identity,
    cover_links,
)
from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.document_citation_tables import bill_key
from spicy_docs.schemas.hearing_bill_link_tables import shape_hearing_bill_link
from spicy_docs.sources.congress.house_committee_repository import (
    HouseCommitteeRepositoryError,
    HouseMeetingLocator,
    bill_key_from_bills_file,
    bill_key_from_designator,
    house_meeting_xml_locator,
    locator_from_meeting,
    parent_committee_code,
    parse_house_committee_meeting,
)
from spicy_docs.sources.govinfo.bodies import package_mods_locator, validate_package_mods

FIXTURES = Path(__file__).parent / "fixtures" / "hearing_bill_links"

#: The one-to-many hearing: 12 bills on one transcript.
MANY = "CHRG-118hhrg56198"
#: The hearing both sources state, and disagree about in both directions.
BOTH = "CHRG-118hhrg52385"
#: A Senate hearing whose MODS states no bill in any context.
SENATE = "CHRG-118shrg56403"
#: The docs.house.gov event id for ``BOTH``.
EVENT = "115955"

#: A four-document record constructed by hand, not a publisher capture: the
#: type-less spelling some committees post, which the retained 115955 record
#: does not carry (fixture README).  Short enough to read in place, which is
#: the point of not keeping a second 22 KB file for one branch.
TYPELESS_MEETING = b"""<?xml version="1.0" encoding="utf-8"?>
<committee-meeting congress-num="118" session-num="2" meeting-id="HHRG117409" meeting-type="HHRG">
  <meeting-details>
    <subcommittees>
      <committee-name id="VR10" parent-id="VR00" parent-name="Committee on Veterans' Affairs">
        Subcommittee on Economic Opportunity</committee-name>
    </subcommittees>
    <meeting-date><calendar-date>2024-06-12</calendar-date></meeting-date>
  </meeting-details>
  <meeting-documents>
    <meeting-document type="BR">
      <description>H.R.226, Veterans Collaboration Act (Rep. Wittman)</description>
      <legis-num>226</legis-num>
      <files><file doc-url="http://docs.house.gov/meetings/VR/VR10/20240612/117409/BILLS-118226ih.pdf"/></files>
    </meeting-document>
    <meeting-document type="BR">
      <description>H.R. 8592, Warriors to Workforce Act (Rep. Van Orden)</description>
      <legis-num>X</legis-num>
      <files><file doc-url="http://docs.house.gov/meetings/VR/VR10/20240612/117409/BILLS-118Xih.pdf"/></files>
    </meeting-document>
    <meeting-document type="BR">
      <description>H.R. XXXX - SAVES Act (Rep. Luttrell)</description>
      <legis-num>XXX</legis-num>
      <files><file doc-url="http://docs.house.gov/meetings/VR/VR10/20240612/117409/BILLS-118XXXih.pdf"/></files>
    </meeting-document>
    <meeting-document type="SD">
      <description>Hearing Notice naming H.R. 226</description>
      <files><file doc-url="http://docs.house.gov/meetings/VR/VR10/20240612/117409/HHRG-118-VR10-SD001.pdf"/></files>
    </meeting-document>
  </meeting-documents>
</committee-meeting>
"""


def mods_for(package: str):
    """One retained MODS excerpt, proved through the ordinary package reader."""
    body = (FIXTURES / f"mods-{package}.excerpt.xml").read_bytes()
    return validate_package_mods(body, package=package, final_url=package_mods_locator(package), max_bytes=1_000_000)


@pytest.fixture(scope="module")
def meeting():
    return parse_house_committee_meeting((FIXTURES / "meeting-115955.xml").read_bytes())


# --- what the MODS states ------------------------------------------------------------


def test_the_mods_states_the_day_the_hearing_was_held_not_the_day_it_was_issued() -> None:
    """``heldDate`` is a separate fact from ``dateIssued``; the link rules join on the first."""
    mods = mods_for(BOTH)
    assert mods.held_date == "2023-05-23"
    assert [committee.authority_id for committee in mods.committees] == ["hsii00"]


def test_a_hearing_is_held_on_a_list_so_one_transcript_yields_twelve_rows() -> None:
    """The finding the whole table rests on: a scalar column would pick one of twelve."""
    links = cover_links(mods_for(MANY))
    assert len(links) == 12
    assert len({link.bill_id for link in links}) == 12
    assert {link.relation for link in links} == {"held_on"}
    assert {link.link_source for link in links} == {"mods_cover"}
    assert links[0].bill_id == "118-hr-226"
    assert links[0].held_date == "2024-06-12"
    assert links[0].committee_system_code == "hsvr00"
    assert links[0].chamber == "house"


def test_a_body_mention_is_counted_and_never_linked() -> None:
    """0 of 23 BODY-only mentions carried a confirming action, so none becomes a row."""
    mods = mods_for(MANY)
    contexts = [bill.context for bill in mods.bills]
    assert contexts.count("COVER") == 12
    assert contexts.count("BODY") == 17
    assert contexts.count("PRIMARY") == 0
    linked = {link.bill_id for link in cover_links(mods)}
    body_only = {bill_key(bill) for bill in mods.bills if bill.context == "BODY"} - linked
    assert len(body_only) == 5
    assert not body_only & linked


def test_a_senate_mods_states_no_bill_so_the_cover_rule_yields_nothing() -> None:
    """Silence here is the publisher's, not the hearing's; nothing in a row says which."""
    mods = mods_for(SENATE)
    assert mods.bills == ()
    assert mods.held_date == "2024-07-11"
    assert cover_links(mods) == ()


def test_a_cover_row_carries_the_event_id_its_caller_read() -> None:
    """The MODS never states one, so the hearing-detail route's value is passed in."""
    links = cover_links(mods_for(BOTH), event_id=EVENT)
    assert {link.event_id for link in links} == {EVENT}
    assert cover_links(mods_for(BOTH))[0].event_id is None


# --- what docs.house.gov states ------------------------------------------------------


def test_the_agenda_is_read_typed_and_only_br_documents_name_a_bill(meeting) -> None:
    assert meeting.event_id == EVENT
    assert meeting.congress == 118
    assert meeting.calendar_date == "2023-05-23"
    assert meeting.parent_committee_codes == ("hsii00",)
    assert [committee.container for committee in meeting.committees] == ["subcommittees"]
    assert len(meeting.documents) == 12
    assert len(meeting.agenda_documents) == 9
    assert {document.type for document in meeting.documents} == {"BR", "SD", "HT"}
    assert all(document.bill_id is None for document in meeting.documents if document.type != "BR")


def test_thirty_six_of_forty_six_is_eight_of_nine_on_this_record(meeting) -> None:
    """The one refusal is a discussion draft with no number, and it says so."""
    resolved = [document for document in meeting.agenda_documents if document.bill_id]
    refused = [document for document in meeting.agenda_documents if document.bill_id is None]
    assert len(resolved) == 8
    assert len(refused) == 1
    assert refused[0].legis_num is None
    assert "H.R. _____" in (refused[0].description or "")
    assert "states a bill type and number" in (refused[0].refusal or "")
    # Four resolve from the machine-written file name and four from their
    # ``<legis-num>``: this committee appends a short title to half its file
    # names, which puts the extension out of the measured pattern's reach.
    rules = sorted(document.bill_id_rule for document in resolved)
    assert rules == ["docs_house_bills_filename"] * 4 + ["docs_house_legis_num"] * 4


def test_a_typeless_legis_num_falls_through_to_the_description_and_is_never_guessed() -> None:
    """``BILLS-118226ih.pdf`` states no type; the description does, and a draft states none."""
    meeting = parse_house_committee_meeting(TYPELESS_MEETING)
    agenda = meeting.agenda_documents
    assert [document.bill_id for document in agenda] == ["118-hr-226", "118-hr-8592", None]
    assert [document.bill_id_rule for document in agenda] == [
        "docs_house_description",
        "docs_house_description",
        None,
    ]
    # The refused one is the discussion draft: the description spells no number
    # either, so nothing states which measure it is.
    assert "BILLS-118XXXih.pdf" in (agenda[2].refusal or "")
    # An SD document names a bill in its description and is still not one: a
    # hearing notice is not an agenda entry.
    notice = meeting.documents[3]
    assert notice.type == "SD"
    assert "H.R. 226" in (notice.description or "")
    assert (notice.bill_id, notice.bill_id_rule, notice.refusal) == (None, None, None)


def test_the_file_name_rule_refuses_the_typeless_and_cross_congress_spellings() -> None:
    assert bill_key_from_bills_file("BILLS-118HR188ih.pdf") == "118-hr-188"
    assert bill_key_from_bills_file("BILLS-118SRES21ih.pdf") == "118-sres-21"
    assert bill_key_from_bills_file("BILLS-118226ih.pdf") is None
    assert bill_key_from_bills_file("BILLS-118HR188ih.pdf", congress=117) is None
    assert bill_key_from_bills_file(None) is None


def test_a_bare_designator_needs_a_congress_and_the_citation_rules_rejects_apply() -> None:
    assert bill_key_from_designator("H.R.226, Veterans Collaboration Act", 118) == "118-hr-226"
    assert bill_key_from_designator("H.R.226", None) is None
    # ``HR974`` is one of the ``bill_number`` rule's own measured rejects.
    assert bill_key_from_designator("HR974", 118) is None
    assert bill_key_from_designator("H.R. _____ (Rep. Neguse)", 118) is None


def test_the_parent_code_rule_is_the_one_the_identity_check_measured() -> None:
    assert parent_committee_code("VR10") == "hsvr00"
    assert parent_committee_code("GO00") == "hsgo00"
    assert parent_committee_code("vr10") is None
    assert parent_committee_code(None) is None


def test_the_locator_rebuilt_from_the_record_is_the_address_the_receipt_fetched(meeting) -> None:
    """The static GET whose bytes equal the postback's, 2 of 2 by SHA-256."""
    locator = house_meeting_xml_locator(locator_from_meeting(meeting))
    assert locator == ("https://docs.house.gov/meetings/II/II10/20230523/115955/HHRG-118-II10-20230523.xml")
    digest = hashlib.sha256((FIXTURES / "meeting-115955.xml").read_bytes()).hexdigest()
    assert digest == "928a1497cefa978a75a929473d23a445e34322e3402f1fbe871e92755ea10320"


def test_an_address_part_the_publisher_did_not_state_refuses_rather_than_guessing(meeting) -> None:
    with pytest.raises(HouseCommitteeRepositoryError, match="calendar-date"):
        locator_from_meeting(replace(meeting, calendar_date=None))
    with pytest.raises(HouseCommitteeRepositoryError, match="names no committee"):
        locator_from_meeting(replace(meeting, committees=()))
    with pytest.raises(HouseCommitteeRepositoryError, match="subcommittee"):
        HouseMeetingLocator(
            congress=118, meeting_type="HHRG", subcommittee="II", calendar_date="2023-05-23", event_id=EVENT
        )


def test_a_record_whose_meeting_id_is_not_its_type_plus_its_event_refuses() -> None:
    broken = TYPELESS_MEETING.replace(b'meeting-id="HHRG117409"', b'meeting-id="MARKUP117409"')
    with pytest.raises(HouseCommitteeRepositoryError, match="meeting-type"):
        parse_house_committee_meeting(broken)


# --- the two sources together --------------------------------------------------------


def test_the_agenda_rows_are_noticed_and_disagree_with_the_cover_both_ways(meeting) -> None:
    """Keeping a row per source is what makes the disagreement readable."""
    mods = mods_for(BOTH)
    cover = {link.bill_id for link in cover_links(mods)}
    agenda = agenda_links(mods, meeting)
    noticed = {link.bill_id for link in agenda}
    assert len(cover) == 8
    assert len(noticed) == 8
    assert cover - noticed == {"118-hr-1450"}
    assert noticed - cover == {"118-hr-2997"}
    assert {link.relation for link in agenda} == {"noticed"}
    assert {link.event_id for link in agenda} == {EVENT}
    assert {link.held_date for link in agenda} == {"2023-05-23"}


def test_the_event_id_equality_is_checked_on_every_row_and_not_assumed_once(meeting) -> None:
    """Neither publisher documents it, so a mismatch has to refuse rather than link."""
    mods = mods_for(BOTH)
    check_meeting_identity(mods, meeting)
    with pytest.raises(HearingBillLinkError, match="not the same event"):
        agenda_links(replace(mods, held_date="2023-05-24"), meeting)
    with pytest.raises(HearingBillLinkError, match="not the same committee"):
        agenda_links(replace(mods_for(MANY), held_date=meeting.calendar_date), meeting)


def test_one_pair_from_two_sources_is_two_rows_that_key_apart(meeting) -> None:
    contract = TABLE_CONTRACTS["hearing_bill_links"]
    mods = mods_for(BOTH)
    rows = [
        shape_hearing_bill_link(link) for link in (*cover_links(mods, event_id=EVENT), *agenda_links(mods, meeting))
    ]
    keys = [contract.key(contract.checked(row)) for row in rows]
    assert len(keys) == 16
    assert len(set(keys)) == 16
    shared = {key[1] for key in keys if key[2] == "mods_cover"} & {key[1] for key in keys if key[2] == "docs_house_br"}
    assert len(shared) == 7


# --- the rules themselves ------------------------------------------------------------


def test_the_sealed_vocabularies_name_every_measured_source_and_two_relations() -> None:
    assert LINK_SOURCES == (
        "mods_cover",
        "docs_house_br",
        "daily_digest_entry",
        "congress_related_items",
        "front_matter_designator",
    )
    assert RELATIONS == ("held_on", "noticed")
    assert [rule.name for rule in HEARING_BILL_LINK_RULES if rule.implemented] == ["mods_cover", "docs_house_br"]
    assert HEARING_BILL_LINK_RULES_BY_NAME["docs_house_br"].relation == "noticed"


def test_the_rule_set_version_is_pinned_and_moves_when_a_rule_changes() -> None:
    """Derived, so editing what a rule reads moves it even if its own version stands still."""
    from spicy_docs.interpretation.hearing_bill_links import _rule_set_version

    assert HEARING_BILL_LINK_RULE_VERSION == "27acfc7cf7ae"
    assert _rule_set_version(HEARING_BILL_LINK_RULES) == HEARING_BILL_LINK_RULE_VERSION
    edited = (replace(HEARING_BILL_LINK_RULES[0], reads="something else"), *HEARING_BILL_LINK_RULES[1:])
    assert _rule_set_version(edited) != HEARING_BILL_LINK_RULE_VERSION
    promoted = (replace(HEARING_BILL_LINK_RULES[2], implemented=True), *HEARING_BILL_LINK_RULES[3:])
    assert _rule_set_version(promoted) != _rule_set_version(HEARING_BILL_LINK_RULES[2:])


def test_a_rule_asserting_a_relation_outside_the_sealed_pair_refuses() -> None:
    with pytest.raises(HearingBillLinkError, match="relation"):
        replace(HEARING_BILL_LINK_RULES[0], relation="heard")


# --- the reproduction tool -----------------------------------------------------------


def _miniature_receipt(root: Path) -> Path:
    """A one-hearing receipt in the shape the real one has, from the committed fixtures.

    The real receipt lives outside this repository, so the offline suite cannot
    read it.  What it *can* prove is that the comparison machinery reads both
    sides, agrees when they agree and fires when they do not -- which is the
    only part of the tool that could be quietly inert.
    """
    responses = root / "responses"
    responses.mkdir(parents=True)
    (responses / f"p1-mods-{BOTH}.xml").write_bytes((FIXTURES / f"mods-{BOTH}.excerpt.xml").read_bytes())
    (responses / f"p1-meeting-{EVENT}.xml").write_bytes((FIXTURES / "meeting-115955.xml").read_bytes())
    mods = mods_for(BOTH)
    meeting = parse_house_committee_meeting((FIXTURES / "meeting-115955.xml").read_bytes())
    cover = sorted(link.bill_id for link in cover_links(mods))
    agenda = list(meeting.agenda_documents)
    (root / "cover-agreement.json").write_text(
        json.dumps(
            {
                "bills_in_agreeing_comparisons": len(cover),
                "rows": [{"package_id": BOTH, "against": "the fixture itself", "cover": len(cover), "equal": True}],
            }
        )
    )
    (root / "probe1-recomputed.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "package_id": BOTH,
                        "event_id": EVENT,
                        "mods_cover": cover,
                        "docs_BR_keys": sorted({document.bill_id for document in agenda if document.bill_id}),
                        "docs_parent_codes": list(meeting.parent_committee_codes),
                        "docs_BR_detail": [{"key": document.bill_id} for document in agenda],
                    }
                ]
            }
        )
    )
    return root


def test_the_recompute_tool_agrees_with_a_receipt_that_states_what_the_rules_produce(tmp_path) -> None:
    from tools.analysis.hearing_bill_links_recompute import compare, shaped_rows

    receipt = _miniature_receipt(tmp_path / "receipt")
    checks, report = compare(receipt)
    assert report["disagreements"] == []
    assert report["requests"] == 0
    assert len(checks) == 7
    assert all(check.agrees for check in checks)
    rows = shaped_rows(receipt, BOTH, EVENT)
    assert len(rows) == 16
    assert {row["link_source"] for row in rows} == {"mods_cover", "docs_house_br"}


def test_the_recompute_tool_fires_when_the_receipt_and_the_rules_disagree(tmp_path) -> None:
    """A comparison that cannot fail is a formatting assertion; this proves it bites."""
    from tools.analysis.hearing_bill_links_recompute import compare

    receipt = _miniature_receipt(tmp_path / "receipt")
    stated = json.loads((receipt / "probe1-recomputed.json").read_text())
    stated["rows"][0]["mods_cover"] = ["118-hr-9999"]
    stated["rows"][0]["docs_BR_detail"].append({"key": "118-hr-9999"})
    (receipt / "probe1-recomputed.json").write_text(json.dumps(stated))
    checks, report = compare(receipt)
    claims = {entry["claim"] for entry in report["disagreements"]}
    assert any("COVER set" in claim for claim in claims)
    assert any("BR documents in all" in claim for claim in claims)
    assert report["agreeing"] < len(checks)
