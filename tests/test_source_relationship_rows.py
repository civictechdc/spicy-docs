"""Native cosponsor/affiliation replay plus explicitly synthetic missingness controls."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.bill_tables import BILL_COSPONSORS, shape_bill_cosponsor
from spicy_docs.schemas.legislator_tables import MEMBER_PARTY_AFFILIATIONS, shape_member_party_affiliation
from spicy_docs.schemas.tables import TableContractError
from spicy_docs.sources.congress.bill_status import BillIdentity, parse_bill_status
from spicy_docs.sources.legislators import LegislatorsSourceError, parse_legislators

FIXTURES = Path(__file__).parent / "fixtures"
BILL = FIXTURES / "govinfo_bills/status-118hr1-cosponsors.xml"
HISTORY = FIXTURES / "legislators/legislators-historical-excerpt.json"


def test_every_native_cosponsor_field_and_occurrence_survives() -> None:
    body = BILL.read_bytes()
    status = parse_bill_status(body, identity=BillIdentity(118, "hr", 1))
    native = ET.fromstring(body).findall("bill/cosponsors/item")
    assert len(status.cosponsors) == len(native) == 49
    assert status.cosponsors_outcome == "populated"
    assert status.input_sha256 == "sha256:" + hashlib.sha256(body).hexdigest()
    columns = {
        "bioguide_id": "bioguideId",
        "full_name": "fullName",
        "party": "party",
        "state": "state",
        "district": "district",
        "sponsorship_date": "sponsorshipDate",
        "sponsorship_withdrawn_date": "sponsorshipWithdrawnDate",
        "is_original_raw": "isOriginalCosponsor",
    }
    keys = []
    for ordinal, source in enumerate(native):
        row = BILL_COSPONSORS.checked(shape_bill_cosponsor(status, cosponsor_index=ordinal))
        keys.append(BILL_COSPONSORS.key(row))
        assert tuple(row) == BILL_COSPONSORS.columns
        for column, field in columns.items():
            node = source.find(field)
            assert row[column] == (None if node is None else node.text or "")
        retained = ET.fromstring(row["source_xml"])
        assert [(c.tag, c.text, c.attrib) for c in retained] == [(c.tag, c.text, c.attrib) for c in source]
        # The item's own markup: no whitespace that follows it in the list (0.50.0 kept that tail), and here
        # byte-identical to the publisher's item.
        assert row["source_xml"].startswith("<item>") and row["source_xml"].endswith("</item>")
        assert row["source_xml"] in body.decode("utf-8")
        assert ET.fromstring(body).find(row["source_path"].removeprefix("/billStatus/")) is not None
    assert len(set(keys)) == 49
    first = shape_bill_cosponsor(status, cosponsor_index=0)
    assert (
        first["bioguide_id"],
        first["sponsorship_date"],
        first["is_original_raw"],
        first["state"],
        first["district"],
    ) == ("M001159", "2023-03-14", "True", "WA", "5")
    assert first["sponsorship_withdrawn_date"] is None


@pytest.mark.parametrize("index", [49, 50, -1, True, "0"], ids=["length", "past length", "negative", "bool", "str"])
def test_an_index_outside_the_list_is_a_named_refusal(index: object) -> None:
    """An index the 49-entry list does not hold refuses as a contract error, which the bill family files by name.

    An ``IndexError`` or ``TypeError`` from the list would escape ``SHAPER_REFUSALS`` and abort the bill's pass.
    """
    status = parse_bill_status(BILL.read_bytes(), identity=BillIdentity(118, "hr", 1))
    assert len(status.cosponsors) == 49
    with pytest.raises(TableContractError, match="cosponsor_index"):
        shape_bill_cosponsor(status, cosponsor_index=index)  # type: ignore[arg-type]


def test_native_present_empty_withdrawal_is_not_absent() -> None:
    body = (FIXTURES / "govinfo_bills/status-113hr4200.xml").read_bytes()
    status = parse_bill_status(body, identity=BillIdentity(113, "hr", 4200))
    assert status.cosponsors[0].sponsorship_withdrawn_date == ""
    assert status.cosponsors[0].sponsorship_withdrawn_date_status == "empty"


@pytest.mark.parametrize("container, state", [(None, "absent"), ("", "empty")])
def test_cosponsor_list_observation_is_separate_from_zero(container: str | None, state: str) -> None:
    root = ET.fromstring(BILL.read_bytes())
    bill = root.find("bill")
    element = bill.find("cosponsors")
    if container is None:
        bill.remove(element)
    else:
        element.clear()
    status = parse_bill_status(ET.tostring(root), identity=BillIdentity(118, "hr", 1))
    assert status.cosponsors == ()
    assert status.cosponsors_outcome == state


def test_repeated_member_and_invalid_literal_date_remain_observations() -> None:
    root = ET.fromstring(BILL.read_bytes())
    entries = root.find("bill/cosponsors")
    entries.append(ET.fromstring(ET.tostring(entries[0])))
    entries[-1].find("sponsorshipDate").text = "2023-02-30"
    status = parse_bill_status(ET.tostring(root), identity=BillIdentity(118, "hr", 1))
    row = shape_bill_cosponsor(status, cosponsor_index=49)
    assert row["bioguide_id"] == "M001159"
    assert row["sponsorship_date"] == "2023-02-30"
    assert row["sponsorship_date_status"] == "invalid"
    assert BILL_COSPONSORS.key(row) != BILL_COSPONSORS.key(shape_bill_cosponsor(status, cosponsor_index=0))


def test_native_party_change_preserves_both_assertions_and_provenance() -> None:
    body = HISTORY.read_bytes()
    parsed = parse_legislators(body, max_bytes=len(body))
    member = parsed.by_bioguide["T000254"]
    term = member.terms[3]
    assert term.party == "Republican"
    assert term.party_affiliations_state == "populated"
    assert [(a.start, a.end, a.party) for a in term.party_affiliations] == [
        ("1961-01-03", "1964-09-16", "Democrat"),
        ("1964-09-16", "1967-01-03", "Republican"),
    ]
    for index in range(2):
        row = MEMBER_PARTY_AFFILIATIONS.checked(
            shape_member_party_affiliation(
                member,
                term_index=3,
                affiliation_index=index,
                input_sha256=parsed.input_sha256,
                observed_at="2026-09-19T00:00:00Z",
            )
        )
        target = json.loads(body)
        for component in row["source_path"].split("/")[1:]:
            target = target[int(component)] if isinstance(target, list) else target[component]
        assert json.loads(row["source_json"]) == target
        assert row["input_sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()
        assert row["term_party"] == "Republican"
    # The transition date occurs on both source boundaries. No party is chosen
    # here: treating the first end as exclusive is explicitly consumer policy.
    assert term.party_affiliations[0].end == term.party_affiliations[1].start


@pytest.mark.parametrize("value,state", [("absent", "absent"), (None, "null"), ([], "empty")])
def test_affiliation_list_states_survive(value: object, state: str) -> None:
    raw = json.loads(HISTORY.read_bytes())
    source = next(r for r in raw if r["id"]["bioguide"] == "T000254")
    if value == "absent":
        del source["terms"][3]["party_affiliations"]
    else:
        source["terms"][3]["party_affiliations"] = value
    body = json.dumps([source]).encode()
    term = parse_legislators(body, max_bytes=len(body)).records[0].terms[3]
    assert term.party_affiliations_state == state
    assert term.party_affiliations == ()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("Democrat", r"party_affiliations must be a list or null"),
        ({"party": "Democrat"}, r"party_affiliations must be a list or null"),
        (["Democrat"], r"party_affiliations\[0\] must be an object"),
        ([{"start": 19610103, "party": "Democrat"}], r"party_affiliations\[0\]\.start must be a string or null"),
        ([{"start": "1961-01-03", "end": ["1964-09-16"]}], r"party_affiliations\[0\]\.end must be a string or null"),
        ([{"start": "1961-01-03", "party": True}], r"party_affiliations\[0\]\.party must be a string or null"),
    ],
    ids=["string", "object", "string entry", "integer start", "list end", "boolean party"],
)
def test_a_malformed_affiliation_list_refuses_the_document(value: object, message: str) -> None:
    """Synthetic shapes the crosswalk has not published: each refuses, never read as an empty list or a coerced value."""
    source = next(r for r in json.loads(HISTORY.read_bytes()) if r["id"]["bioguide"] == "T000254")
    source["terms"][3]["party_affiliations"] = value
    body = json.dumps([source]).encode()
    with pytest.raises(LegislatorsSourceError, match=message):
        parse_legislators(body, max_bytes=len(body))


def test_overlaps_gaps_missing_ends_and_invalid_dates_are_not_repaired() -> None:
    source = next(r for r in json.loads(HISTORY.read_bytes()) if r["id"]["bioguide"] == "T000254")
    intervals = [
        {"start": "1961-01-03", "end": "1964-09-17", "party": "Democrat"},
        {"start": "1964-09-16", "end": "1965-01-01", "party": "Republican"},
        {"start": "1966-01-01", "party": "Independent"},
        {"start": "not-a-date", "end": None, "party": None, "extra": "retained"},
    ]
    source["terms"][3]["party_affiliations"] = intervals
    body = json.dumps([source]).encode()
    term = parse_legislators(body, max_bytes=len(body)).records[0].terms[3]
    assert [json.loads(a.raw_json) for a in term.party_affiliations] == intervals
    assert term.party_affiliations[2].end is None
    assert term.party_affiliations[3].start_status == "invalid"
    assert term.party == "Republican"


def test_declared_relationships_include_source_part_and_meeting_scope() -> None:
    expected = {
        "bill_sections": [
            (("bill_id", "version_code", "source"), "bill_versions", ("bill_id", "version_code", "source"))
        ],
        "section_diffs": [
            (("bill_id", "from_version_code", "from_source"), "bill_versions", ("bill_id", "version_code", "source")),
            (("bill_id", "to_version_code", "to_source"), "bill_versions", ("bill_id", "version_code", "source")),
        ],
        "report_sections": [(("package_id", "part_id"), "committee_reports", ("package_id", "part_id"))],
        "hearing_transcripts": [
            (("congress", "chamber", "event_id"), "committee_meetings", ("congress", "chamber", "event_id"))
        ],
    }
    for name, links in expected.items():
        actual = {(r.child_columns, r.parent_table, r.parent_columns) for r in TABLE_CONTRACTS[name].references}
        assert set(links) <= actual
        for _child, parent_name, parent in links:
            assert parent == TABLE_CONTRACTS[parent_name].identity
    # A same short label in another source, part or chamber must not match: every declared reference to these
    # parents, in any contract, pairs the parent's qualifying column with the child's own column for it.
    qualifier = {"bill_versions": "source", "committee_reports": "part_id", "committee_meetings": "chamber"}
    checked = 0
    for contract in TABLE_CONTRACTS.values():
        for reference in contract.references:
            if reference.parent_table in qualifier:
                paired = dict(zip(reference.parent_columns, reference.child_columns, strict=True))
                column = qualifier[reference.parent_table]
                assert paired[column].endswith(column), (contract.name, reference)
                checked += 1
    assert checked >= sum(len(links) for links in expected.values())


def test_retained_positive_withdrawal_date_preserves_native_occurrence():
    body = (FIXTURES / "govinfo_bills/status-119s1224-withdrawal.xml").read_bytes()
    receipt = json.loads((FIXTURES / "govinfo_bills/status-119s1224-withdrawal.provenance.json").read_text())
    assert "sha256:" + hashlib.sha256(body).hexdigest() == receipt["sha256"]
    status = parse_bill_status(body, identity=BillIdentity(119, "s", 1224))
    native = ET.fromstring(body).findall("bill/cosponsors/item")
    assert len(status.cosponsors) == len(native)
    withdrawals = []
    for ordinal, item in enumerate(native):
        if item.findtext("sponsorshipWithdrawnDate"):
            row = BILL_COSPONSORS.checked(shape_bill_cosponsor(status, cosponsor_index=ordinal))
            assert row["sponsorship_withdrawn_date"] == item.findtext("sponsorshipWithdrawnDate")
            assert row["sponsorship_withdrawn_date_status"] == "valid"
            withdrawals.append(row)
    assert len(withdrawals) == 1
    assert withdrawals[0]["bioguide_id"] == "C001047"
    assert withdrawals[0]["sponsorship_date"] == "2026-03-18"
    assert withdrawals[0]["sponsorship_withdrawn_date"] == "2026-03-19"
    assert withdrawals[0]["is_original_raw"] == "False"
