"""House Clerk and Senate LIS roll-call vote XML: shape, identity proof, crosswalk and mocked acquisition.

``tests/fixtures/congress_votes/README.md`` documents where the two pinned
vote bodies came from. Minimal synthetic bodies below isolate one field or one
refusal at a time; the pinned fixtures prove the real publisher shapes,
including every field BillTrax's ``roll-call-votes.ts``/``sync-roll-call-votes.ts``
discarded (party totals, ``legis-num``, ``vote-type``, ``action-time``, the
Senate's long-form text fields, ``tie_breaker``, and every member's own
crosswalked bioguide -- BillTrax's ``upsertMemberVote`` was written but never
called, so no member-level vote ever reached its database).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.congress.votes import (
    CLERK_URL_RE,
    DEFAULT_MAX_BYTES,
    MAX_VOTE_BYTES,
    SENATE_URL_RE,
    RollCallVote,
    VoteAcquirer,
    VoteBudget,
    VoteIdentityError,
    VoteLocator,
    VoteRefusedError,
    VoteSourceError,
    VoteUnavailableError,
    clerk_url,
    locator_from_recorded_vote_url,
    normalize_vote,
    parse_clerk_vote,
    parse_senate_vote,
    senate_url,
)
from spicy_docs.sources.legislators import parse_legislators
from spicy_docs.transport import retry
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures" / "congress_votes"
CLERK_FIXTURE = (FIXTURES / "clerk-roll240.xml").read_bytes()
SENATE_FIXTURE = (FIXTURES / "senate-vote-119-1-00001.xml").read_bytes()

LEGISLATORS_FIXTURE = Path(__file__).parent / "fixtures" / "legislators" / "legislators-current-excerpt.json"
CURRENT_LEGISLATORS = parse_legislators(LEGISLATORS_FIXTURE.read_bytes(), max_bytes=DEFAULT_MAX_BYTES)

CLERK_LOCATOR = VoteLocator("house", 119, 1, 240)
SENATE_LOCATOR = VoteLocator("senate", 119, 1, 1)

CLERK_MINIMAL = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<!DOCTYPE rollcall-vote PUBLIC "-//US Congress//DTDs/vote v1.0 20031119 //EN" "../vote.dtd">'
    b"<rollcall-vote><vote-metadata>"
    b"<majority>R</majority><congress>119</congress><session>1st</session>"
    b"<chamber>U.S. House of Representatives</chamber><rollcall-num>1</rollcall-num>"
    b"<legis-num>H R 1</legis-num><vote-question>On Passage</vote-question>"
    b"<vote-type>YEA-AND-NAY</vote-type><vote-result>Passed</vote-result>"
    b'<action-date>3-Jan-2025</action-date><action-time time-etz="12:00">12:00 PM</action-time>'
    b"<vote-desc>Test Act</vote-desc>"
    b"<vote-totals>"
    b"<totals-by-party><party>Republican</party><yea-total>1</yea-total><nay-total>0</nay-total>"
    b"<present-total>0</present-total><not-voting-total>0</not-voting-total></totals-by-party>"
    b"<totals-by-vote><total-stub>Totals</total-stub><yea-total>1</yea-total><nay-total>0</nay-total>"
    b"<present-total>0</present-total><not-voting-total>0</not-voting-total></totals-by-vote>"
    b"</vote-totals>"
    b"</vote-metadata><vote-data>"
    b'<recorded-vote><legislator name-id="A000001" sort-field="Test" unaccented-name="Test" party="R" '
    b'state="TX" role="legislator">Test</legislator><vote>Yea</vote></recorded-vote>'
    b"</vote-data></rollcall-vote>"
)

SENATE_MINIMAL = (
    b'<?xml version="1.0" encoding="UTF-8"?><roll_call_vote>'
    b"<congress>119</congress><session>1</session><congress_year>2025</congress_year>"
    b"<vote_number>1</vote_number><vote_date>January 3, 2025</vote_date>"
    b"<modify_date>January 4, 2025</modify_date>"
    b"<vote_question_text>On Passage</vote_question_text>"
    b"<vote_document_text>A bill.</vote_document_text>"
    b"<vote_result_text>Passed (1-0)</vote_result_text>"
    b"<question>On Passage</question><vote_title>Test Vote</vote_title>"
    b"<majority_requirement>1/2</majority_requirement><vote_result>Passed</vote_result>"
    b"<count><yeas>1</yeas><nays>0</nays><present/><absent>0</absent></count>"
    b"<tie_breaker><by_whom/><tie_breaker_vote/></tie_breaker>"
    b"<members><member><member_full>Test (R-TX)</member_full><last_name>Test</last_name>"
    b"<first_name>Tex</first_name><party>R</party><state>TX</state><vote_cast>Yea</vote_cast>"
    b"<lis_member_id>S001</lis_member_id></member></members>"
    b"</roll_call_vote>"
)

MINIMAL_LOCATOR = VoteLocator("house", 119, 1, 1)
MINIMAL_SENATE_LOCATOR = VoteLocator("senate", 119, 1, 1)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(retry.random, "uniform", lambda *_: 0)


# --- vote value normalization: every spelled value the fixtures contain, plus the wider vocabulary ---------


def test_the_fixtures_only_ever_spell_yea_nay_and_not_voting():
    clerk_values = {member.vote for member in parse_clerk_vote(CLERK_FIXTURE, CLERK_LOCATOR).member_votes}
    senate_values = {member.vote for member in parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR).member_votes}
    assert clerk_values == {"Yea", "Nay", "Not Voting"}
    assert senate_values == {"Yea", "Nay", "Not Voting"}


@pytest.mark.parametrize(
    "spelled,expected",
    [
        ("Yea", "yea"),
        ("yea", "yea"),
        ("Aye", "yea"),
        ("Nay", "nay"),
        ("No", "nay"),
        ("Present", "present"),
        ("Not Voting", "not_voting"),
        ("not   voting", "not_voting"),  # collapsed whitespace, still recognized
    ],
)
def test_normalize_vote_covers_the_full_clerk_and_senate_vocabulary(spelled, expected):
    assert normalize_vote(spelled) == expected


def test_normalize_vote_refuses_an_unrecognized_spelling():
    with pytest.raises(VoteSourceError, match="unrecognized"):
        normalize_vote("Abstain")


# --- parsing the pinned Clerk fixture: nothing the file states is dropped -----------------------------------


def test_clerk_fixture_matches_the_measured_2026_09_18_shape():
    vote = parse_clerk_vote(CLERK_FIXTURE, CLERK_LOCATOR)
    assert vote.publisher == "clerk" and vote.chamber == "house"
    assert (vote.congress, vote.session, vote.roll_number) == (119, 1, 240)
    assert vote.source_url == "https://clerk.house.gov/evs/2025/roll240.xml"
    assert vote.majority == "R"
    assert vote.session_raw == "1st"
    assert vote.chamber_raw == "U.S. House of Representatives"
    assert vote.legis_num == "H R 3424"
    assert vote.question == "On Motion to Suspend the Rules and Pass"
    assert vote.vote_type == "2/3 YEA-AND-NAY"
    assert vote.result == "Passed"
    assert vote.date == "8-Sep-2025"
    assert vote.action_time == "6:56 PM" and vote.action_time_etz == "18:56"
    assert vote.vote_desc == "SPACE Act"
    assert dict(vote.tallies) == {"yea-total": 397, "nay-total": 1, "present-total": 0, "not-voting-total": 32}
    assert len(vote.member_votes) == 430
    parties = {party.party: dict(party.counts) for party in vote.party_totals}
    assert parties == {
        "Republican": {"yea-total": 202, "nay-total": 0, "present-total": 0, "not-voting-total": 16},
        "Democratic": {"yea-total": 195, "nay-total": 1, "present-total": 0, "not-voting-total": 16},
        "Independent": {"yea-total": 0, "nay-total": 0, "present-total": 0, "not-voting-total": 0},
    }
    # every totals-by-vote count equals the sum of the per-party rows
    for field in ("yea-total", "nay-total", "present-total", "not-voting-total"):
        assert sum(party.counts[field] for party in vote.party_totals) == vote.tallies[field]
    # Senate-only fields stay unset on a Clerk record
    assert vote.congress_year is None and vote.tie_breaker is None and vote.vote_title is None


def test_clerk_fixture_members_carry_every_legislator_attribute():
    vote = parse_clerk_vote(CLERK_FIXTURE, CLERK_LOCATOR)
    by_bioguide = {member.bioguide_id: member for member in vote.member_votes}
    adams = by_bioguide["A000370"]
    assert adams.name == "Adams" and adams.sort_field == "Adams" and adams.unaccented_name == "Adams"
    assert adams.party == "D" and adams.state == "NC" and adams.role == "legislator"
    assert adams.vote == "Yea" and adams.vote_normalized == "yea"
    assert adams.lis_id is None  # the Clerk file carries no LIS id at all

    amodei = by_bioguide["A000369"]
    assert amodei.name == "Amodei (NV)" and amodei.sort_field == "Amodei (NV)"  # a disambiguated display name

    zinke = by_bioguide["Z000018"]
    assert zinke.vote == "Not Voting" and zinke.vote_normalized == "not_voting"

    yeas = sum(1 for m in vote.member_votes if m.vote_normalized == "yea")
    nays = sum(1 for m in vote.member_votes if m.vote_normalized == "nay")
    not_voting = sum(1 for m in vote.member_votes if m.vote_normalized == "not_voting")
    assert (yeas, nays, not_voting) == (397, 1, 32)


# --- parsing the pinned Senate fixture: nothing the file states is dropped -----------------------------------


def test_senate_fixture_matches_the_measured_2026_09_18_shape():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR)
    assert vote.publisher == "senate-lis" and vote.chamber == "senate"
    assert (vote.congress, vote.session, vote.roll_number) == (119, 1, 1)
    assert vote.source_url == "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml"
    assert vote.congress_year == 2025
    assert vote.date == "January 9, 2025,  02:54 PM"
    assert vote.modify_date == "January 10, 2025,  02:57 PM"
    assert vote.vote_question_text == "On Cloture on the Motion to Proceed S. 5"
    assert vote.vote_document_text.startswith("A bill to require the Secretary")
    assert vote.vote_result_text == "Cloture on the Motion to Proceed Agreed to (84-9, 3/5 majority required)"
    assert vote.question == "On Cloture on the Motion to Proceed"
    assert vote.vote_title == "Motion to Invoke Cloture: Motion to Proceed to S. 5"
    assert vote.majority_requirement == "3/5"
    assert vote.result == "Cloture on the Motion to Proceed Agreed to"
    assert dict(vote.tallies) == {"yeas": 84, "nays": 9, "present": 0, "absent": 6}
    assert len(vote.member_votes) == 99
    # Clerk-only fields stay unset on a Senate record
    assert vote.majority is None and vote.legis_num is None and vote.party_totals == ()


def test_senate_fixture_tie_breaker_is_present_but_empty_when_the_vote_was_not_tied():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR)
    assert vote.tie_breaker is not None
    assert vote.tie_breaker.by_whom is None and vote.tie_breaker.tie_breaker_vote is None


def test_senate_fixture_document_and_amendment_are_kept():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR)
    assert vote.document is not None
    assert vote.document.congress == 119
    assert vote.document.type == "S."
    assert vote.document.number == "5"
    assert vote.document.name == "S. 5"
    assert vote.document.title.startswith("A bill to require the Secretary")
    assert vote.document.short_title is None  # <document_short_title/> is present but empty

    assert vote.amendment is not None
    assert vote.amendment.purpose == "No Statement of Purpose on File."
    # this vote carried no amendment, so every other amendment field is empty
    assert vote.amendment.number is None
    assert vote.amendment.to_amendment_number is None
    assert vote.amendment.to_amendment_to_amendment_number is None
    assert vote.amendment.to_document_number is None
    assert vote.amendment.to_document_short_title is None

    # Clerk records never carry either block
    clerk = parse_clerk_vote(CLERK_FIXTURE, CLERK_LOCATOR)
    assert clerk.document is None and clerk.amendment is None


def test_senate_fixture_members_carry_every_field_and_the_vote_totals_sum():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR)
    by_lis = {member.lis_id: member for member in vote.member_votes}
    alsobrooks = by_lis["S428"]
    assert alsobrooks.member_full == "Alsobrooks (D-MD)"
    assert alsobrooks.first_name == "Angela" and alsobrooks.last_name == "Alsobrooks"
    assert alsobrooks.party == "D" and alsobrooks.state == "MD"
    assert alsobrooks.vote == "Yea" and alsobrooks.vote_normalized == "yea"
    assert alsobrooks.name == "Alsobrooks (D-MD)"  # the shared "name" field mirrors member_full
    assert alsobrooks.bioguide_id is None  # not in the small legislators excerpt used elsewhere in this file

    yeas = sum(1 for m in vote.member_votes if m.vote_normalized == "yea")
    nays = sum(1 for m in vote.member_votes if m.vote_normalized == "nay")
    not_voting = sum(1 for m in vote.member_votes if m.vote_normalized == "not_voting")
    assert (yeas, nays, not_voting) == (84, 9, 6)
    assert not_voting == vote.tallies["absent"]  # the Senate calls its "not voting" bucket "absent"


# --- the LIS crosswalk, resolved through the existing legislators fixture -------------------------------------


def test_the_lis_crosswalk_resolves_senate_members_sharing_the_legislators_excerpt():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR, CURRENT_LEGISLATORS)
    by_lis = {member.lis_id: member for member in vote.member_votes}
    # Cantwell, Sanders and Warner are all in both the 119th Congress vote and
    # tests/fixtures/legislators/legislators-current-excerpt.json (reused, not duplicated).
    assert by_lis["S275"].bioguide_id == "C000127"  # Cantwell
    assert by_lis["S313"].bioguide_id == "S000033"  # Sanders
    assert by_lis["S327"].bioguide_id == "W000805"  # Warner
    # A voter whose LIS id the small excerpt does not carry resolves to None, not a refusal.
    assert by_lis["S428"].bioguide_id is None


def test_no_crosswalk_leaves_every_bioguide_id_unset():
    vote = parse_senate_vote(SENATE_FIXTURE, SENATE_LOCATOR, crosswalk=None)
    assert all(member.bioguide_id is None for member in vote.member_votes)


# --- identity proof: the parsed congress/session/roll number must equal the locator's ----------------------


def test_clerk_identity_refusal_on_a_mismatched_locator():
    wrong = VoteLocator("house", 119, 1, 999)
    with pytest.raises(VoteIdentityError) as raised:
        parse_clerk_vote(CLERK_FIXTURE, wrong)
    assert raised.value.locator == wrong
    assert raised.value.parsed == (119, 1, 240)


def test_senate_identity_refusal_on_a_mismatched_locator():
    wrong = VoteLocator("senate", 119, 2, 1)
    with pytest.raises(VoteIdentityError) as raised:
        parse_senate_vote(SENATE_FIXTURE, wrong)
    assert raised.value.locator == wrong
    assert raised.value.parsed == (119, 1, 1)


def test_parse_clerk_vote_refuses_a_senate_locator_and_vice_versa():
    with pytest.raises(VoteSourceError, match="'house' locator"):
        parse_clerk_vote(CLERK_FIXTURE, SENATE_LOCATOR)
    with pytest.raises(VoteSourceError, match="'senate' locator"):
        parse_senate_vote(SENATE_FIXTURE, CLERK_LOCATOR)


# --- locator round trip from measured recordedVotes urls -----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://clerk.house.gov/evs/2025/roll240.xml",  # this fixture's own url
        "https://clerk.house.gov/evs/2025/roll190.xml",  # data map "bill->clerk-xml" edge, legis-num 'H R 1'
        "https://clerk.house.gov/evs/2025/roll050.xml",  # a real sub-100 roll (billtrax-raw-data sidecar), zero-padded
    ],
)
def test_clerk_locator_round_trips_from_a_measured_recorded_vote_url(url):
    locator = locator_from_recorded_vote_url(url)
    assert locator.chamber == "house" and locator.congress == 119 and locator.session == 1
    assert clerk_url(locator) == url == locator.url()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml",  # this fixture
        "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00372.xml",  # data map edge
    ],
)
def test_senate_locator_round_trips_from_a_measured_recorded_vote_url(url):
    locator = locator_from_recorded_vote_url(url)
    assert locator.chamber == "senate" and locator.congress == 119 and locator.session == 1
    assert senate_url(locator) == url == locator.url()


def test_locator_from_url_refuses_an_unrecognized_shape():
    with pytest.raises(VoteSourceError, match="not a recognized"):
        locator_from_recorded_vote_url("https://example.com/vote.xml")


def test_clerk_url_refuses_a_congress_before_the_fixed_session_calendar():
    with pytest.raises(VoteSourceError, match="predates the fixed session calendar"):
        clerk_url(VoteLocator("house", 50, 1, 1))


def test_senate_url_refuses_a_congress_before_the_lis_archive_floor():
    """Measured 2026-09-19: vote_menu_101_1.xml serves real content; 100 and 099 both redirect to
    roll-call-vote-not-available.htm. Below this floor every real congress is two digits, so a build
    that reached the interpolation would silently break the 3-digit `SENATE_URL_RE` round trip; refusing
    first means `senate_url` never has to zero-pad a congress it has no evidence the publisher folds."""
    with pytest.raises(VoteSourceError, match="predates the Senate LIS archive"):
        senate_url(VoteLocator("senate", 99, 1, 1))


def test_locator_from_url_refuses_a_senate_url_predating_the_archive_floor():
    with pytest.raises(VoteSourceError, match="predates the LIS archive"):
        locator_from_recorded_vote_url(
            "https://www.senate.gov/legislative/LIS/roll_call_votes/vote0991/vote_099_1_00001.xml"
        )


def test_clerk_url_and_senate_url_each_require_their_own_chamber():
    with pytest.raises(VoteSourceError, match="'house' locator"):
        clerk_url(SENATE_LOCATOR)
    with pytest.raises(VoteSourceError, match="'senate' locator"):
        senate_url(CLERK_LOCATOR)


# --- VoteLocator shape ------------------------------------------------------------------------------------


def test_vote_locator_is_frozen_and_matches_congress_gov_url_grammars():
    with pytest.raises(AttributeError):
        CLERK_LOCATOR.congress = 118  # type: ignore[misc]
    assert CLERK_URL_RE.match(CLERK_LOCATOR.url())
    assert SENATE_URL_RE.match(SENATE_LOCATOR.url())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chamber": "senate2"},
        {"congress": -1},
        {"session": True},
        {"roll_number": "240"},
    ],
)
def test_vote_locator_validates_its_fields(kwargs):
    base = {"chamber": "house", "congress": 119, "session": 1, "roll_number": 240}
    with pytest.raises(VoteSourceError):
        VoteLocator(**{**base, **kwargs})


def test_vote_locator_as_vote_key_matches_vote_matching():
    from spicy_docs.interpretation.vote_matching import VoteKey

    assert CLERK_LOCATOR.as_vote_key() == VoteKey(congress=119, chamber="house", session=1, roll_number=240)


# --- malformed bodies: a handful of shape refusals, one field at a time ---------------------------------------


@pytest.mark.parametrize(
    "body,message",
    [
        (b"<not-a-vote/>", "root must be"),
        (
            CLERK_MINIMAL.replace(b"<vote-metadata>", b"<other>").replace(b"</vote-metadata>", b"</other>"),
            "vote-metadata",
        ),
        (CLERK_MINIMAL.replace(b'name-id="A000001" ', b""), "missing name-id"),
        (CLERK_MINIMAL.replace(b"<vote>Yea</vote>", b"<vote></vote>"), "empty"),
        (CLERK_MINIMAL.replace(b"<congress>119</congress>", b"<congress>abc</congress>"), "integer"),
        (CLERK_MINIMAL.replace(b"<session>1st</session>", b"<session>first</session>"), "ordinal"),
    ],
)
def test_clerk_shape_refusals_name_the_failed_check(body, message):
    with pytest.raises(VoteSourceError, match=message):
        parse_clerk_vote(body, MINIMAL_LOCATOR)


@pytest.mark.parametrize(
    "body,message",
    [
        (b"<not-a-vote/>", "root must be"),
        (SENATE_MINIMAL.replace(b"<lis_member_id>S001</lis_member_id>", b""), "lis_member_id"),
        (SENATE_MINIMAL.replace(b"<vote_cast>Yea</vote_cast>", b"<vote_cast>Maybe</vote_cast>"), "unrecognized"),
        (SENATE_MINIMAL.replace(b"<vote_number>1</vote_number>", b""), "vote_number"),
    ],
)
def test_senate_shape_refusals_name_the_failed_check(body, message):
    with pytest.raises(VoteSourceError, match=message):
        parse_senate_vote(body, MINIMAL_SENATE_LOCATOR)


def test_minimal_bodies_parse_cleanly():
    clerk = parse_clerk_vote(CLERK_MINIMAL, MINIMAL_LOCATOR)
    assert clerk.member_votes[0].vote_normalized == "yea"
    senate = parse_senate_vote(SENATE_MINIMAL, MINIMAL_SENATE_LOCATOR)
    assert senate.member_votes[0].vote_normalized == "yea"


# --- empty roster: a well-formed file with zero recorded-vote/member children is a refusal, not a success ----

CLERK_EMPTY_ROSTER = CLERK_MINIMAL.replace(
    b'<recorded-vote><legislator name-id="A000001" sort-field="Test" unaccented-name="Test" party="R" '
    b'state="TX" role="legislator">Test</legislator><vote>Yea</vote></recorded-vote>',
    b"",
)
SENATE_EMPTY_ROSTER = SENATE_MINIMAL.replace(
    b"<member><member_full>Test (R-TX)</member_full><last_name>Test</last_name>"
    b"<first_name>Tex</first_name><party>R</party><state>TX</state><vote_cast>Yea</vote_cast>"
    b"<lis_member_id>S001</lis_member_id></member>",
    b"",
)


def test_clerk_vote_with_no_recorded_votes_is_a_refusal_not_an_empty_success():
    assert b"<recorded-vote>" not in CLERK_EMPTY_ROSTER  # the mutation actually emptied vote-data
    with pytest.raises(VoteSourceError, match="lists no recorded votes"):
        parse_clerk_vote(CLERK_EMPTY_ROSTER, MINIMAL_LOCATOR)


def test_senate_vote_with_no_members_is_a_refusal_not_an_empty_success():
    assert b"<member>" not in SENATE_EMPTY_ROSTER  # the mutation actually emptied members
    with pytest.raises(VoteSourceError, match="lists no members"):
        parse_senate_vote(SENATE_EMPTY_ROSTER, MINIMAL_SENATE_LOCATOR)


# --- acquisition, mocked ----------------------------------------------------------------------------------


class Transport(httpx.MockTransport):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(request)
        return next(self.responses)


def response(body, status=200, *, content_type="text/xml; charset=UTF-8"):
    return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": content_type})


BUDGET = VoteBudget(3, DEFAULT_MAX_BYTES, 7, 0)


def test_acquirer_captures_exact_clerk_bytes_keyless():
    transport = Transport(response(CLERK_FIXTURE))
    with VoteAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(CLERK_LOCATOR)
    assert result.capture.body == CLERK_FIXTURE
    assert result.capture.requested_url == CLERK_LOCATOR.url()
    assert isinstance(result.vote, RollCallVote) and len(result.vote.member_votes) == 430
    assert result.request_count == 1 and result.budget == BUDGET
    assert transport.calls[0].headers["accept-encoding"] == "identity"
    assert "x-api-key" not in transport.calls[0].headers


def test_acquirer_captures_exact_senate_bytes_and_resolves_the_crosswalk():
    transport = Transport(response(SENATE_FIXTURE))
    with VoteAcquirer(budget=BUDGET, transport=transport) as source:
        result = source.acquire(SENATE_LOCATOR, crosswalk=CURRENT_LEGISLATORS)
    assert result.capture.body == SENATE_FIXTURE
    by_lis = {member.lis_id: member for member in result.vote.member_votes}
    assert by_lis["S275"].bioguide_id == "C000127"


@pytest.mark.parametrize(
    "answer,error,message",
    [
        (response(b"gone", 404, content_type="text/html"), VoteUnavailableError, "HTTP 404"),
        (response(b"", 410), VoteUnavailableError, "HTTP 410"),
        (response(b"<html>blocked</html>", content_type="text/html"), VoteSourceError, "Content-Type"),
    ],
)
def test_wrong_shape_or_unavailable_vote_never_succeeds(answer, error, message):
    transport = Transport(answer)
    with VoteAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(error, match=message) as raised:
        source.acquire(CLERK_LOCATOR)
    assert raised.value.vote_acquisition["chamber"] == "house"
    assert len(transport.calls) == 1


def test_a_mismatched_locator_refuses_and_retains_the_fetched_bytes_as_evidence():
    """The acquirer-level identity refusal: a real file fetched for the wrong roll number."""
    wrong = VoteLocator("house", 119, 1, 1)  # roll240.xml actually states roll 240
    transport = Transport(response(CLERK_FIXTURE))
    with VoteAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(VoteIdentityError) as raised:
        source.acquire(wrong)
    assert raised.value.capture.body == CLERK_FIXTURE
    assert raised.value.refused_response.response_bytes == CLERK_FIXTURE


@pytest.mark.parametrize("status", [401, 403])
def test_a_public_access_refusal_on_a_keyless_route_is_named_not_a_credential_refusal(status):
    body = b"rate limited"
    transport = Transport(response(body, status, content_type="text/plain"))
    with VoteAcquirer(budget=BUDGET, transport=transport) as source, pytest.raises(VoteRefusedError) as raised:
        source.acquire(SENATE_LOCATOR)
    assert isinstance(raised.value, VoteSourceError)
    assert not isinstance(raised.value, CredentialRefusedError)
    assert raised.value.url == SENATE_LOCATOR.url()
    refusal = raised.value.refused_response
    assert refusal.response_bytes == body and refusal.request_key == SENATE_LOCATOR.url()


def test_acquire_requires_a_vote_locator():
    with VoteAcquirer(budget=BUDGET, transport=Transport()) as source, pytest.raises(TypeError):
        source.acquire("roll240")  # type: ignore[arg-type]


def test_budget_and_client_configuration_are_explicit():
    for fields in ({"max_requests": 0}, {"max_bytes": MAX_VOTE_BYTES + 1}, {"timeout_seconds": 0}):
        with pytest.raises(ValueError):
            VoteBudget(
                **{
                    "max_requests": 3,
                    "max_bytes": 4096,
                    "timeout_seconds": 7,
                    "min_request_interval_seconds": 0,
                    **fields,
                }
            )
    with pytest.raises(TypeError):
        VoteAcquirer(budget=(3, 4096, 7, 0), transport=Transport())  # type: ignore[arg-type]


# --- live, keyless, bounded to one request per publisher -----------------------------------------------------


@pytest.mark.integration
def test_live_clerk_vote_meets_the_2026_09_18_measured_floor():
    budget = VoteBudget(2, DEFAULT_MAX_BYTES, 30, 1.0)
    with VoteAcquirer(budget=budget) as source:
        result = source.acquire(CLERK_LOCATOR)
    assert result.vote.roll_number == 240 and len(result.vote.member_votes) >= 400
    assert result.capture.sha256.startswith("sha256:")
    assert result.request_count == 1


@pytest.mark.integration
def test_live_senate_vote_meets_the_2026_09_18_measured_floor():
    budget = VoteBudget(2, DEFAULT_MAX_BYTES, 30, 1.0)
    with VoteAcquirer(budget=budget) as source:
        result = source.acquire(SENATE_LOCATOR)
    assert result.vote.roll_number == 1 and len(result.vote.member_votes) >= 90
    assert result.capture.sha256.startswith("sha256:")
    assert result.request_count == 1
