"""House Clerk and Senate roster files prove what each states about itself.

Fixtures are bounded cuts of the 2026-09-19 captures: five House seats
including a vacancy and a Chair, the full 27-committee/109-subcommittee names
block, and six senators including a Chairman; whole-file facts are receipted
outside the repository. Pins each file's own identity statement, name
resolution, vacancy and placeholder handling, system-code rules, assignment
keying and acquisition evidence.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from spicy_docs.schemas.roster_tables import shape_house_assignment, shape_senate_assignment
from spicy_docs.sources.congress.committee_rosters import (
    SENATE_CVC_URL,
    CommitteeRosterAcquirer,
    CommitteeRosterBudget,
    CommitteeRosterError,
    CommitteeRosterIdentityError,
    CommitteeRosterRefusedError,
    CommitteeRosterUnavailableError,
    house_system_code,
    parse_house_member_data,
    parse_senate_cvc,
    senate_system_code,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE_XML = (FIXTURES / "congress_rosters/memberdata-119-excerpt.xml").read_bytes()
SENATE_XML = (FIXTURES / "congress_rosters/cvc-member-data-excerpt.xml").read_bytes()
BUDGET = CommitteeRosterBudget(max_requests=3, max_bytes=4 * 1024**2, timeout_seconds=7, min_request_interval_seconds=0)
OBSERVED_AT = "2026-09-19T00:00:00Z"


def _vacancy_span(body: bytes) -> tuple[int, bytes]:
    """The FL20 member element: the excerpt's vacancy."""
    start = body.rindex(b"<member>", 0, body.index(b"<statedistrict>FL20</statedistrict>"))
    end = body.index(b"</member>", start) + len(b"</member>")
    return start, body[start:end]


def test_the_house_file_proves_the_congress_and_session_it_states():
    """The House file's stated congress, session, publish date and clerk are read as native identity."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    assert (roster.congress, roster.session) == (119, 2)
    assert roster.congress_text == "One Hundred Nineteenth Congress"
    assert roster.publish_date == "September 2, 2026"
    assert roster.clerk == "KEVIN F. McCUMBER"
    assert roster.identity_basis == ("congress:native", "session:native")


def test_a_file_stating_another_congress_or_session_is_refused_with_both_sides_named():
    """A file stating another congress or session is refused with both requested and stated values."""
    with pytest.raises(CommitteeRosterIdentityError) as refused:
        parse_house_member_data(HOUSE_XML, congress=118)
    assert refused.value.requested == (118, None)
    assert refused.value.stated == (119, 2)
    with pytest.raises(CommitteeRosterIdentityError):
        parse_house_member_data(HOUSE_XML, congress=119, session=1)


def test_the_house_names_block_resolves_every_assignment_code():
    """The names block resolves all 27 committees and 109 subcommittee parents."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    assert len(roster.committees) == 27
    assert len(roster.committee_names) == 136  # 27 committees + 109 subcommittees
    assert len(roster.parent_codes) == 109
    assert roster.committee_names["II00"] == "Committee on Natural Resources"
    assert roster.parent_codes["II06"] == "II00"


def test_vacancies_are_seats_without_members_and_placeholders_are_not_assignments():
    """A vacancy is a seat with no member and placeholders are not assignments."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    vacant = next(member for member in roster.members if member.vacant)
    assert vacant.state_district == "FL20"
    assert vacant.bioguide_id is None
    assert vacant.assignments == () and vacant.placeholder_assignments == 1
    assert sum(member.placeholder_assignments for member in roster.members) == 2


def test_a_vacancy_listing_a_real_assignment_is_a_malformed_file_not_a_seat():
    """A vacancy listing a real assignment is malformed, not a seat."""
    start, span = _vacancy_span(HOUSE_XML)
    mutated = (
        HOUSE_XML[:start]
        + span.replace(b'<committee rank=""/>', b'<committee comcode="II00" rank="1"/>')
        + HOUSE_XML[start + len(span) :]
    )
    with pytest.raises(CommitteeRosterError, match="vacancy that still lists committee assignments"):
        parse_house_member_data(mutated, congress=119)


def test_leadership_is_kept_verbatim():
    """Leadership values are kept verbatim."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    chairs = [member for member in roster.members if any(a.leadership == "Chair" for a in member.assignments)]
    assert len(chairs) == 1


def test_the_system_code_rules_are_the_maps_two_edges():
    """The two system-code maps translate House and Senate codes and refuse empty input."""
    assert house_system_code("II00") == "hsii00"
    assert house_system_code("II06") == "hsii06"
    assert house_system_code("hsju00") == "hsju00"
    assert senate_system_code("SPAG00") == "spag00"
    assert senate_system_code("sssb00") == "sssb00"
    with pytest.raises(CommitteeRosterError, match="cannot be empty"):
        house_system_code("  ")
    with pytest.raises(CommitteeRosterError, match="cannot be empty"):
        senate_system_code("")


def test_the_senate_file_states_an_update_date_and_no_congress():
    """The Senate file states an update date and no congress, with LIS ids and bioguide ids per senator."""
    roster = parse_senate_cvc(SENATE_XML)
    assert roster.last_update_date == "Saturday, September 19, 2026"
    assert roster.identity_basis == ("root:native", "update-date:native")
    assert not hasattr(roster, "congress")
    assert [(senator.lis_id, senator.last) for senator in roster.senators] == [
        ("S428", "Alsobrooks"),
        ("S440", "Armstrong"),
        ("S354", "Baldwin"),
        ("S429", "Banks"),
        ("S317", "Barrasso"),
        ("S343", "Boozman"),
    ]
    alsobrooks = roster.senators[0]
    assert alsobrooks.bioguide_id == "A000382"
    assert (alsobrooks.committees[0].code, alsobrooks.committees[0].name) == ("SPAG00", "Special Committee on Aging")


def test_a_repeated_or_unidentified_senator_is_refused():
    """A repeated senator, a missing bioguide id or a wrong root is refused."""
    first = SENATE_XML[SENATE_XML.index(b"<senator ") : SENATE_XML.index(b"</senator>") + len(b"</senator>")]
    duplicated = SENATE_XML.replace(b"</senators>", first + b"\n</senators>")
    with pytest.raises(CommitteeRosterError, match="repeats senator"):
        parse_senate_cvc(duplicated)
    anonymous = SENATE_XML.replace(b"<bioguideId>A000382</bioguideId>", b"", 1)
    with pytest.raises(CommitteeRosterError, match="missing <bioguideId>"):
        parse_senate_cvc(anonymous)
    with pytest.raises(CommitteeRosterError, match="root must be <senators>"):
        parse_senate_cvc(b"<members/>")


def test_house_assignment_rows_key_on_bioguide_and_system_code():
    """House assignment rows key on bioguide and system code and carry file-derived congress, name, rank and date."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    member = next(m for m in roster.members if m.bioguide_id == "B001323")
    row = shape_house_assignment(member, member.assignments[0], roster=roster, observed_at=OBSERVED_AT)
    assert row["congress"] == "119" and row["congress_basis"] == "file"
    assert (row["system_code"], row["committee_code"]) == ("hsii00", "II00")
    assert row["bioguide_id"] == "B001323"
    assert row["committee_name"] == "Committee on Natural Resources"
    assert row["rank"] == "22" and row["is_subcommittee"] == "false"
    assert row["session"] == "2" and row["file_date"] == "September 2, 2026"


def test_a_subcommittee_seat_carries_its_parents_code():
    """A subcommittee seat carries its parent's system code, and a full committee has none."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    member = next(m for m in roster.members if any(a.kind == "subcommittee" for a in m.assignments))
    sub = next(a for a in member.assignments if a.kind == "subcommittee")
    row = shape_house_assignment(member, sub, roster=roster, observed_at=OBSERVED_AT)
    assert row["is_subcommittee"] == "true"
    assert row["parent_system_code"] == roster.parent_system_code(sub.code) == "hsii00"
    assert roster.parent_system_code("II00") is None  # a full committee has no parent
    assert row["committee_name"] == "Energy and Mineral Resources"


def test_a_vacant_seat_never_reaches_the_assignment_table():
    """A vacant seat cannot be shaped into an assignment row."""
    roster = parse_house_member_data(HOUSE_XML, congress=119, session=2)
    vacant = next(m for m in roster.members if m.vacant)
    with pytest.raises(Exception, match="no member to key on"):
        shape_house_assignment(vacant, None, roster=roster, observed_at=OBSERVED_AT)


def test_a_senate_row_says_its_congress_came_from_the_caller():
    """A Senate row records that its congress came from the caller, with LIS id and no session or rank."""
    roster = parse_senate_cvc(SENATE_XML)
    senator = roster.senators[0]
    row = shape_senate_assignment(senator, senator.committees[0], congress=119, roster=roster, observed_at=OBSERVED_AT)
    assert row["congress"] == "119" and row["congress_basis"] == "caller"
    assert (row["system_code"], row["bioguide_id"], row["lis_id"]) == ("spag00", "A000382", "S428")
    assert row["chamber"] == "senate" and row["session"] is None and row["rank"] is None
    assert row["committee_name"] == "Special Committee on Aging"
    assert row["file_date"] == "Saturday, September 19, 2026"


class Transport(httpx.MockTransport):
    """A mock transport that records calls and serves queued responses."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def xml_response(body: bytes, status: int = 200):
    """An HTTPX response carrying XML bytes."""
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "text/xml"})


def test_the_acquirer_captures_each_chambers_file_once_with_its_evidence():
    """The acquirer captures each chamber's file once with exact bytes, locator and per-call request count."""
    transport = Transport(xml_response(HOUSE_XML), xml_response(SENATE_XML))
    with CommitteeRosterAcquirer(budget=BUDGET, transport=transport) as source:
        house = source.acquire_house(congress=119, session=2)
        senate = source.acquire_senate()
    assert house.roster.congress == 119 and len(house.roster.members) == 5
    assert house.capture.byte_size == len(HOUSE_XML)
    assert house.capture.requested_url == "https://clerk.house.gov/xml/lists/MemberData.xml"
    assert house.request_count == 1 and house.budget == BUDGET
    assert senate.roster.last_update_date == "Saturday, September 19, 2026"
    assert senate.capture.requested_url == SENATE_CVC_URL
    assert senate.request_count == 1  # request_count is per capture call


def test_the_acquirer_refuses_another_congress_and_keeps_refusals_retained():
    """The acquirer refuses another congress and keeps unavailable/refused evidence, with 404 mapped to unavailable."""
    transport = Transport(xml_response(HOUSE_XML), xml_response(b"<html>no</html>", 401), xml_response(b"", 404))
    with CommitteeRosterAcquirer(budget=BUDGET, transport=transport) as source:
        with pytest.raises(CommitteeRosterIdentityError):
            source.acquire_house(congress=118)
        with pytest.raises(CommitteeRosterRefusedError):
            source.acquire_senate()
        with pytest.raises(CommitteeRosterUnavailableError) as unavailable:
            source.acquire_senate()
    assert unavailable.value.capture.status_code == 404
