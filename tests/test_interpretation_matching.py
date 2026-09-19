"""Vote, release, member and interest-area matching: the corrected behaviours, measured."""

import re
from pathlib import Path

import pytest

from spicy_docs.interpretation.interest_areas import InterestArea, Section, find_matching_sections
from spicy_docs.interpretation.member_matching import (
    MemberQuery,
    MemberRow,
    index_members,
    last_name_of,
    match_member,
)
from spicy_docs.interpretation.release_matching import (
    Release,
    compile_bill_patterns,
    match_releases,
)
from spicy_docs.interpretation.vote_matching import (
    RECORDED_VOTE_FIELDS,
    VoteKey,
    VoteMatchError,
    house_vote_references,
    index_vote_references,
    match_votes,
    recorded_vote_references,
)
from spicy_docs.sources.congress.bill_status import BillIdentity
from spicy_docs.sources.legislators import parse_legislators

LEGISLATORS = Path(__file__).parent / "fixtures" / "legislators" / "legislators-current-excerpt.json"

HR1 = BillIdentity(119, "hr", 1)
S123 = BillIdentity(119, "s", 123)

# One voted action as the publisher serves it: exactly the six measured fields.
VOTED_ACTION = {
    "actionCode": "H37100",
    "actionDate": "2025-09-08",
    "text": "On passage Passed by the Yeas and Nays: 217 - 212.",
    "type": "Floor",
    "recordedVotes": [
        {
            "chamber": "House",
            "congress": 119,
            "date": "2025-09-08T22:56:43Z",
            "rollNumber": 240,
            "sessionNumber": 1,
            "url": "https://clerk.house.gov/evs/2025/roll240.xml",
        }
    ],
}
SENATE_VOTED_ACTION = {
    "actionCode": "17000",
    "text": "Passed Senate with an amendment by Yea-Nay Vote. 51 - 50.",
    "recordedVotes": [
        {
            "chamber": "Senate",
            "congress": 119,
            "date": "2025-07-01T16:00:00Z",
            "rollNumber": 372,
            "sessionNumber": 1,
            "url": "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00372.xml",
        }
    ],
}


# --- vote matching ---


def test_the_six_recorded_vote_fields_are_the_sealed_shape() -> None:
    assert RECORDED_VOTE_FIELDS == ("chamber", "congress", "date", "rollNumber", "sessionNumber", "url")


def test_a_recorded_vote_is_matched_by_roll_number() -> None:
    read = recorded_vote_references(HR1, ({"text": "Introduced in House"}, VOTED_ACTION))
    assert len(read.references) == 1 and read.refusals == ()
    index = index_vote_references(read.references)
    matches = match_votes((VoteKey(119, "house", 1, 240),), index)
    assert len(matches) == 1
    assert matches[0].bill == HR1
    assert matches[0].rule == "bill_action_recorded_vote"
    assert matches[0].url == "https://clerk.house.gov/evs/2025/roll240.xml"


def test_a_senate_vote_matches_too() -> None:
    # The behaviour being corrected: roll-call-votes.ts:143 required an "R"
    # after [HS], so no Senate vote could ever match its bill.
    assert re.search(r"\b([HS])\.?\s*R\.?\s*(\d+)\b", "On Passage of S. 123") is None
    index = index_vote_references(recorded_vote_references(S123, (SENATE_VOTED_ACTION,)).references)
    matches = match_votes((VoteKey(119, "senate", 1, 372),), index)
    assert matches[0].bill == S123


def test_an_unreferenced_vote_is_named_unmatched_rather_than_guessed() -> None:
    index = index_vote_references(recorded_vote_references(HR1, (VOTED_ACTION,)).references)
    matches = match_votes((VoteKey(119, "house", 1, 999),), index)
    assert (matches[0].bill, matches[0].rule) == (None, "unmatched")


def test_the_house_vote_route_names_its_bill_in_two_fields() -> None:
    references = house_vote_references(
        (
            {
                "congress": 119,
                "sessionNumber": 1,
                "rollCallNumber": 240,
                "legislationType": "HR",
                "legislationNumber": "3424",
                "sourceDataURL": "https://clerk.house.gov/evs/2025/roll240.xml",
            },
            {"congress": 119, "sessionNumber": 1, "rollCallNumber": 241},
        )
    )
    assert len(references) == 1
    assert references[0].bill == BillIdentity(119, "hr", 3424)
    assert references[0].rule == "house_vote_legislation"


def test_a_recorded_vote_missing_a_sealed_field_is_refused() -> None:
    action = {"recordedVotes": [{"chamber": "House", "congress": 119, "rollNumber": 240, "sessionNumber": 1}]}
    read = recorded_vote_references(HR1, (action,))
    assert read.references == ()
    assert len(read.refusals) == 1
    assert "url" in read.refusals[0].reason


def test_one_bad_entry_costs_that_entry_and_not_the_bill() -> None:
    def good(roll: int) -> dict[str, object]:
        return {
            "chamber": "House",
            "congress": 119,
            "date": "2025-09-08T22:56:43Z",
            "rollNumber": roll,
            "sessionNumber": 1,
            "url": f"https://clerk.house.gov/evs/2025/roll{roll:03d}.xml",
        }

    entries = [good(roll) for roll in range(1, 31)]
    entries.insert(17, {"chamber": "House", "congress": 119, "rollNumber": 99, "sessionNumber": 1})
    read = recorded_vote_references(HR1, ({"recordedVotes": entries},))
    assert len(read.references) == 30
    assert [(r.action_index, r.entry_index) for r in read.refusals] == [(0, 17)]


def test_a_recorded_votes_that_is_not_a_list_is_a_shape_error() -> None:
    with pytest.raises(VoteMatchError, match="list of entries"):
        recorded_vote_references(HR1, ({"recordedVotes": "roll 240"},))


def test_the_same_roll_call_on_two_actions_is_one_entry_and_no_conflict() -> None:
    # The publisher files the same vote as a chamber action and as a Library of
    # Congress summary action; both carry the identical recordedVote.
    summary_action = {"text": "Passed/agreed to in House.", "recordedVotes": VOTED_ACTION["recordedVotes"]}
    read = recorded_vote_references(HR1, (VOTED_ACTION, summary_action))
    assert len(read.references) == 2
    index = index_vote_references(read.references)
    assert len(index.by_vote) == 1
    assert index.conflicts == ()


def test_two_sources_disagreeing_on_a_vote_are_kept_as_a_conflict() -> None:
    house = house_vote_references(
        (
            {
                "congress": 119,
                "sessionNumber": 1,
                "rollNumber": 240,
                "legislationType": "HR",
                "legislationNumber": "999",
            },
        )
    )
    index = index_vote_references((*recorded_vote_references(HR1, (VOTED_ACTION,)).references, *house))
    assert index.by_vote[VoteKey(119, "house", 1, 240)].bill == HR1
    assert len(index.conflicts) == 1


# --- release matching ---


def test_release_matching_compiles_one_pattern_per_bill(monkeypatch: pytest.MonkeyPatch) -> None:
    bills = tuple(BillIdentity(119, "hr", number) for number in range(1, 201))
    releases = tuple(Release(f"release-{index}", f"Chairman statement on H.R. {index + 1}") for index in range(500))

    compiles = 0
    real_compile = re.compile

    def counting_compile(*args, **kwargs):
        nonlocal compiles
        compiles += 1
        return real_compile(*args, **kwargs)

    monkeypatch.setattr(re, "compile", counting_compile)
    patterns = compile_bill_patterns(bills)
    assert compiles == 200

    compiles = 0
    matches = match_releases(releases, patterns)
    # BillTrax rebuilt a pattern per (release, bill) pair: 500 x 200 here.
    assert compiles == 0
    assert len(matches) == 500
    assert matches[0].bill == BillIdentity(119, "hr", 1)


def test_a_release_with_no_description_still_matches_on_its_title() -> None:
    # The Senate committee feed sends no <description> at all, so an excerpt is
    # permanently empty there and title-only matching is the whole of it.
    patterns = compile_bill_patterns((BillIdentity(119, "s", 4045),))
    matches = match_releases((Release("senate-1", "Committee Advances S. 4045", None),), patterns)
    assert matches[0].bill == BillIdentity(119, "s", 4045)
    assert matches[0].matched_field == "title"
    assert matches[0].matched_text == "S. 4045"
    assert matches[0].rule == "bill_number_in_title"


def test_an_excerpt_match_is_reported_as_one() -> None:
    patterns = compile_bill_patterns((BillIdentity(119, "hr", 4366),))
    release = Release("house-1", "Chairman statement on the funding bill", "The bill, H.R. 4366, advances today.")
    match = match_releases((release,), patterns)[0]
    assert (match.matched_field, match.rule) == ("excerpt", "bill_number_in_excerpt")


def test_a_bare_number_no_longer_matches_every_bill() -> None:
    # press-releases.ts offered the raw bill number as a third alternative, so
    # bill 1 matched any "1" in any title.
    patterns = compile_bill_patterns((BillIdentity(119, "hr", 1),))
    matches = match_releases((Release("r", "Committee marks up 1 bill on 1 January"),), patterns)
    assert (matches[0].bill, matches[0].rule) == (None, "unmatched")


def test_the_pattern_is_built_from_the_bill_s_own_type() -> None:
    patterns = compile_bill_patterns((BillIdentity(119, "s", 100),))
    assert match_releases((Release("r", "Statement on H.R. 100"),), patterns)[0].bill is None
    assert match_releases((Release("r", "Statement on S. 100"),), patterns)[0].bill is not None


def test_a_longer_number_does_not_match_a_shorter_bill() -> None:
    patterns = compile_bill_patterns((BillIdentity(119, "hr", 5),))
    assert match_releases((Release("r", "Statement on H.R. 50"),), patterns)[0].bill is None


# --- member matching ---


def crosswalk():
    return parse_legislators(LEGISLATORS.read_bytes(), max_bytes=1 << 20)


MEMBERS = (
    MemberRow("A000055", "Rep. Aderholt, Robert B. [R-AL-4]"),
    MemberRow("C000127", "Sen. Cantwell, Maria [D-WA]"),
    MemberRow("X000001", "Rep. Aderholt, Q. Notreal [R-XX-1]", end_date="2019-01-03"),
)


def test_bioguide_beats_name() -> None:
    match = match_member(
        MemberQuery(bioguide="A000055", name="Sen. Cantwell, Maria [D-WA]"),
        crosswalk=crosswalk(),
        members=index_members(MEMBERS),
    )
    assert (match.bioguide, match.rule, match.score) == ("A000055", "bioguide", 1.0)


def test_lis_resolves_through_the_crosswalk_before_any_name() -> None:
    match = match_member(
        MemberQuery(lis="S275", name="Rep. Aderholt, Robert B. [R-AL-4]"),
        crosswalk=crosswalk(),
        members=index_members(MEMBERS),
    )
    assert (match.bioguide, match.rule) == ("C000127", "lis")


def test_name_matching_is_the_last_resort_and_exposes_its_score() -> None:
    index = index_members(MEMBERS)
    match = match_member(MemberQuery(name="Rep. Aderholt, Robert B. [R-AL-4]"), crosswalk=crosswalk(), members=index)
    assert (match.bioguide, match.rule, match.score) == ("A000055", "name_exact", 1.0)

    partial = match_member(MemberQuery(name="Rep. Aderholt"), crosswalk=crosswalk(), members=index)
    assert (partial.bioguide, partial.rule) == ("A000055", "name_last")
    assert 0.0 < partial.score < 1.0


def test_the_surname_is_read_from_the_publisher_s_own_spelling() -> None:
    # Taking the last whitespace token of this string yields "[R-AL-4]".
    assert last_name_of("Rep. Aderholt, Robert B. [R-AL-4]") == "Aderholt"
    assert last_name_of("Rep. Smith") == "Smith"
    assert last_name_of("Sen. Cantwell, Maria [D-WA]") == "Cantwell"


def test_a_last_name_match_ignores_members_whose_term_has_ended() -> None:
    match = match_member(MemberQuery(name="Rep. Notreal"), crosswalk=crosswalk(), members=index_members(MEMBERS))
    assert (match.bioguide, match.rule) == (None, "unmatched")


def test_nothing_to_go_on_is_unmatched_rather_than_a_guess() -> None:
    assert match_member(MemberQuery(), crosswalk=crosswalk(), members=index_members(MEMBERS)).rule == "unmatched"


def test_member_rows_are_normalized_once_however_many_queries_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import spicy_docs.interpretation.member_matching as module

    calls = 0
    real = module.normalize_for_comparison

    def counting(value: str) -> str:
        nonlocal calls
        calls += 1
        return real(value)

    monkeypatch.setattr(module, "normalize_for_comparison", counting)
    rows = tuple(MemberRow(f"X{index:06d}", f"Rep. Surname{index}, First [R-XX-1]") for index in range(200))
    index = index_members(rows)
    # Two per row: the full name, and the surname for the serving-member map.
    assert calls == 400

    calls = 0
    for _ in range(50):
        match_member(MemberQuery(name="Rep. Surname7"), members=index)
    # Two per query -- the query's own name and its surname -- and none per row.
    assert calls == 100


# --- interest areas ---

SECTIONS = (
    Section("sec-1", "ver-1", "119-hr-1", "Funds for coastal resilience and levee repair.", "Coastal grants"),
    Section("sec-2", "ver-1", "119-hr-1", "The Secretary shall report annually on staffing.", "Reports"),
)


def test_any_keyword_token_matches_and_the_hit_names_its_keywords() -> None:
    matches = find_matching_sections((InterestArea("Water", ("levee", "aquifer")),), SECTIONS)
    assert len(matches) == 1
    assert matches[0].section_id == "sec-1"
    assert matches[0].keywords == ("levee",)
    assert matches[0].rule == "keyword_any"
    assert matches[0].area_name == "Water"


def test_the_excerpt_is_the_fixed_length_the_original_stored() -> None:
    section = Section("sec-3", "ver-1", "119-hr-1", "levee " + "x" * 500)
    match = find_matching_sections((InterestArea("Water", ("levee",)),), (section,))[0]
    assert len(match.excerpt) == 200


def test_the_limit_bounds_each_area_and_then_the_whole_result() -> None:
    sections = tuple(Section(f"sec-{index}", "v", "b", "levee repair") for index in range(10))
    areas = (InterestArea("A", ("levee",)), InterestArea("B", ("repair",)))
    matches = find_matching_sections(areas, sections, limit=3)
    assert len(matches) == 3
    assert {match.area_name for match in matches} == {"A"}


def test_an_area_with_no_keywords_matches_nothing() -> None:
    assert find_matching_sections((InterestArea("Empty", ()),), SECTIONS) == ()


@pytest.mark.parametrize(
    ("keyword", "rule"),
    [
        pytest.param("ai", "innodb_ft_min_token_size", id="below-the-3-character-floor"),
        pytest.param("x" * 85, "innodb_ft_max_token_size", id="above-the-84-character-ceiling"),
        pytest.param("for", "innodb_ft_default_stopword", id="a-word-in-the-default-stopword-table"),
    ],
)
def test_a_keyword_the_innodb_index_would_drop_never_matches_even_though_the_word_is_present(
    keyword: str, rule: str
) -> None:
    section = Section("sec-x", "ver-1", "119-hr-1", f"Provisions on {keyword} apply broadly.")
    matches = find_matching_sections((InterestArea("Area", (keyword,)),), (section,))
    assert matches == (), f"{keyword!r} should be dropped by {rule} before matching"


def test_relevance_is_the_count_of_distinct_matched_keywords_ordered_then_by_position() -> None:
    sections = (
        Section("sec-a", "v", "b", "levee repair funding.", "A"),
        Section("sec-b", "v", "b", "levee aquifer repair funding.", "B"),
        Section("sec-c", "v", "b", "levee repair funding.", "C"),
    )
    area = InterestArea("Water", ("levee", "aquifer", "repair"))
    matches = find_matching_sections((area,), sections)
    # sec-b matches all three keywords (relevance 3); sec-a and sec-c tie at
    # two (levee, repair) and keep their input order (0 before 2).
    assert [match.section_id for match in matches] == ["sec-b", "sec-a", "sec-c"]
    assert [match.relevance for match in matches] == [3, 2, 2]


# --- end to end: the parser's own output feeds the rules, no hand-built input ---

GOVINFO_BILLS = Path(__file__).parent / "fixtures" / "govinfo_bills"


def enacted_status():
    from spicy_docs.sources.congress.bill_status import parse_bill_status

    return parse_bill_status((GOVINFO_BILLS / "status-119s5.xml").read_bytes(), identity=BillIdentity(119, "s", 5))


def test_signed_date_reads_a_parsed_status_end_to_end() -> None:
    from spicy_docs.interpretation.bill_stage import infer_stage, signed_date

    status = enacted_status()
    finding = signed_date(status)
    assert finding.public_law_number == "119-1"
    assert finding.signed_date == "2025-01-29"
    assert finding.rule == "public_law_and_became_law_action"
    assert finding.action_code == "36000"
    # The same status, folded: the publisher serves actions newest-first.
    assert infer_stage(status.actions).stage == "law"


def test_recorded_votes_on_a_parsed_status_match_both_chambers() -> None:
    status = enacted_status()
    read = recorded_vote_references(status.identity, status.actions)
    assert read.refusals == ()
    index = index_vote_references(read.references)
    matches = match_votes((VoteKey(119, "house", 1, 23), VoteKey(119, "senate", 1, 7)), index)
    assert [match.bill for match in matches] == [BillIdentity(119, "s", 5), BillIdentity(119, "s", 5)]
    assert [match.rule for match in matches] == ["bill_action_recorded_vote"] * 2
    assert matches[0].url == "https://clerk.house.gov/evs/2025/roll023.xml"


def test_committee_codes_on_a_parsed_status_raise_the_referral_signal() -> None:
    from spicy_docs.interpretation.money_bills import referrals_from_committee_codes
    from spicy_docs.sources.congress.bill_status import parse_bill_status

    status = parse_bill_status(
        (GOVINFO_BILLS / "status-119hres10.xml").read_bytes(), identity=BillIdentity(119, "hres", 10)
    )
    codes = tuple(committee.system_code for committee in status.committees if committee.system_code)
    assert codes == ("hsru00",)
    # The Rules Committee is not one of the six, so it raises nothing.
    assert referrals_from_committee_codes(codes) == frozenset()


def test_a_member_query_is_built_from_the_parsed_sponsor() -> None:
    sponsor = enacted_status().sponsors[0]
    assert (sponsor.bioguide_id, sponsor.full_name) == ("B001319", "Sen. Britt, Katie Boyd [R-AL]")
    match = match_member(MemberQuery(bioguide=sponsor.bioguide_id, name=sponsor.full_name))
    assert (match.bioguide, match.rule) == ("B001319", "bioguide")
    assert last_name_of(sponsor.full_name) == "Britt"
