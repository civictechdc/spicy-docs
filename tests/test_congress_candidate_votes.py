"""Candidate-choice election totals stay distinct from ordinary position totals."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.schemas.congress_activity_tables import shape_member_vote, shape_roll_call_vote
from spicy_docs.sources.congress.votes import VoteLocator, VoteSourceError, parse_clerk_vote, parse_senate_vote

FIXTURES = Path(__file__).parent / "fixtures" / "congress_votes"
SPEAKER = (FIXTURES / "clerk-speaker-119-1-2.xml").read_bytes()
LOCATOR = VoteLocator("house", 119, 1, 2)


def candidate_xml(choice: str = "Named candidate", count: str = "1") -> bytes:
    return f"""<rollcall-vote><vote-metadata><congress>119</congress><session>1st</session>
<rollcall-num>2</rollcall-num><vote-totals><totals-by-candidate><candidate>{choice}</candidate>
<candidate-total>{count}</candidate-total></totals-by-candidate></vote-totals></vote-metadata>
<vote-data><recorded-vote><legislator name-id="A000001" party="D" state="CA">First member</legislator>
<vote>{choice}</vote></recorded-vote></vote-data></rollcall-vote>""".encode()


def test_complete_native_speaker_election_retains_all_choices_and_counts():
    vote = parse_clerk_vote(SPEAKER, LOCATOR)
    native = ET.fromstring(SPEAKER)
    raw_members = native.findall("./vote-data/recorded-vote")
    counts = {
        el.findtext("candidate"): int(el.findtext("candidate-total"))
        for el in native.findall("./vote-metadata/vote-totals/totals-by-candidate")
    }
    assert vote.tally_kind == "candidates"
    assert (
        dict(vote.tallies)
        == counts
        == {"Johnson (LA)": 218, "Jeffries": 215, "Emmer": 1, "Present": 0, "Not Voting": 0}
    )
    assert len(vote.member_votes) == len(raw_members) == 434
    assert Counter(member.vote for member in vote.member_votes) == Counter(counts)
    for member, raw in zip(vote.member_votes, raw_members, strict=True):
        legislator = raw.find("legislator")
        assert (member.bioguide_id, member.name, member.party, member.state, member.vote) == (
            legislator.get("name-id"),
            legislator.text,
            legislator.get("party"),
            legislator.get("state"),
            raw.findtext("vote"),
        )
        assert member.vote_normalized is None
        shaped = shape_member_vote(member, vote=vote)
        assert shaped["position"] == member.vote and shaped["position_normalized"] is None
    row = shape_roll_call_vote(vote, tally=vote.tallies, member_vote_count=len(vote.member_votes))
    assert row["tally_kind"] == "candidates" and row["member_vote_count"] == "434"
    assert row["documents_json"] == row["amendments_json"] == "[]"
    assert json.loads(row["tallies_json"]) == counts
    assert all(row[field] is None for field in ("yea", "nay", "present", "not_voting"))


@pytest.mark.parametrize(
    ("choice", "normalized"),
    [("Named candidate", None), ("Present", "present"), ("Not Voting", "not_voting"), ("yeas", None)],
)
def test_candidate_choice_normalization_never_fabricates_ordinary_tally(choice, normalized):
    vote = parse_clerk_vote(candidate_xml(choice), LOCATOR)
    assert vote.member_votes[0].vote == choice
    assert vote.member_votes[0].vote_normalized == normalized
    row = shape_roll_call_vote(vote, tally=vote.tallies, member_vote_count=1)
    assert json.loads(row["tallies_json"]) == {choice: 1}
    assert all(row[field] is None for field in ("yea", "nay", "present", "not_voting"))


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "mixed",
        "duplicate_label",
        "empty_label",
        "missing_count",
        "malformed_count",
        "negative_count",
        "mismatched_count",
        "unknown_choice",
        "duplicate_member",
    ],
)
def test_invalid_candidate_election_refuses(change):
    root = ET.fromstring(candidate_xml())
    totals = root.find("./vote-metadata/vote-totals")
    entry = totals.find("totals-by-candidate")
    if change == "missing":
        totals.remove(entry)
    elif change == "mixed":
        ET.SubElement(totals, "totals-by-vote")
    elif change == "duplicate_label":
        totals.append(ET.fromstring(ET.tostring(entry)))
    elif change == "empty_label":
        entry.find("candidate").text = ""
    elif change == "missing_count":
        entry.remove(entry.find("candidate-total"))
    elif change in {"malformed_count", "negative_count", "mismatched_count"}:
        entry.find("candidate-total").text = {"malformed_count": "x", "negative_count": "-1", "mismatched_count": "2"}[
            change
        ]
    elif change == "unknown_choice":
        root.find("./vote-data/recorded-vote/vote").text = "Undeclared choice"
    elif change == "duplicate_member":
        data = root.find("vote-data")
        data.append(ET.fromstring(ET.tostring(data.find("recorded-vote"))))
        entry.find("candidate-total").text = "2"
    with pytest.raises(VoteSourceError):
        parse_clerk_vote(ET.tostring(root), LOCATOR)


def test_ordinary_unknown_position_still_refuses():
    raw = (FIXTURES / "clerk-roll240.xml").read_bytes().replace(b"<vote>Yea</vote>", b"<vote>Named candidate</vote>", 1)
    with pytest.raises(VoteSourceError, match="unrecognized roll-call vote"):
        parse_clerk_vote(raw, VoteLocator("house", 119, 1, 240))


def test_ordinary_house_and_senate_keep_their_existing_totals():
    house = parse_clerk_vote((FIXTURES / "clerk-roll240.xml").read_bytes(), VoteLocator("house", 119, 1, 240))
    senate = parse_senate_vote(
        (FIXTURES / "senate-vote-119-1-00001.xml").read_bytes(), VoteLocator("senate", 119, 1, 1)
    )
    for vote, expected in [(house, ("397", "1", "0", "32")), (senate, ("84", "9", "0", "6"))]:
        assert vote.tally_kind == "positions"
        row = shape_roll_call_vote(vote, tally=vote.tallies, member_vote_count=len(vote.member_votes))
        assert row["tally_kind"] == "positions"
        assert tuple(row[field] for field in ("yea", "nay", "present", "not_voting")) == expected
        assert all(member.vote_normalized is not None for member in vote.member_votes)
