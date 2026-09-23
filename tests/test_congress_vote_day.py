"""The vote day: each chamber's printed vote date read as an ISO day, and the ``roll_call_votes.vote_day`` it fills.

The four native fixtures (``tests/fixtures/congress_votes/README.md``) pin the
real spellings; boundary cases are synthetic literals in those spellings.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from spicy_docs.interpretation.vote_matching import VoteKey, VoteMatch
from spicy_docs.schemas.congress_activity_tables import shape_roll_call_vote
from spicy_docs.sources.congress.votes import (
    VoteLocator,
    VoteSourceError,
    parse_clerk_vote,
    parse_senate_vote,
    vote_day,
)

FIXTURES = Path(__file__).parent / "fixtures" / "congress_votes"
CLERK_240 = (FIXTURES / "clerk-roll240.xml").read_bytes()
CLERK_240_LOCATOR = VoteLocator("house", 119, 1, 240)


def _parse(name: str, locator: VoteLocator):
    body = (FIXTURES / name).read_bytes()
    return parse_clerk_vote(body, locator) if locator.chamber == "house" else parse_senate_vote(body, locator)


@pytest.mark.parametrize(
    "name,locator,printed,day",
    [
        ("clerk-roll240.xml", CLERK_240_LOCATOR, "8-Sep-2025", "2025-09-08"),
        ("clerk-speaker-119-1-2.xml", VoteLocator("house", 119, 1, 2), "3-Jan-2025", "2025-01-03"),
        ("senate-vote-119-1-00001.xml", VoteLocator("senate", 119, 1, 1), "January 9, 2025,  02:54 PM", "2025-01-09"),
        (
            "senate-vote-119-1-00522.xml",
            VoteLocator("senate", 119, 1, 522),
            "September 17, 2025,  11:02 AM",
            "2025-09-17",
        ),
    ],
)
def test_every_native_fixture_reads_to_the_day_it_prints(name, locator, printed, day):
    vote = _parse(name, locator)
    assert vote.date == printed  # the literal is kept unchanged beside its reading
    assert vote.day == day
    row = shape_roll_call_vote(vote, tally=vote.tallies)
    assert row["vote_date"] == printed and row["vote_day"] == day


def test_a_house_record_without_an_action_date_has_no_day_and_is_not_refused():
    """``votes.py`` has always let a missing ``action-date`` through; the day follows it rather than refusing."""
    printed = b"<action-date>8-Sep-2025</action-date>"
    assert CLERK_240.count(printed) == 1
    for body in (CLERK_240.replace(printed, b""), CLERK_240.replace(printed, b"<action-date/>")):
        vote = parse_clerk_vote(body, CLERK_240_LOCATOR)
        assert vote.date is None and vote.day is None
        assert shape_roll_call_vote(vote, tally=vote.tallies)["vote_day"] is None


def test_a_senate_record_without_a_vote_date_has_no_day():
    body = (FIXTURES / "senate-vote-119-1-00001.xml").read_bytes()
    printed = b"<vote_date>January 9, 2025,  02:54 PM</vote_date>"
    assert body.count(printed) == 1
    vote = parse_senate_vote(body.replace(printed, b""), VoteLocator("senate", 119, 1, 1))
    assert vote.date is None and vote.day is None


@pytest.mark.parametrize(
    "chamber,literal,day",
    [
        # Year boundary, both sides.
        ("house", "31-Dec-2025", "2025-12-31"),
        ("house", "1-Jan-2026", "2026-01-01"),
        ("senate", "December 31, 2025,  11:59 PM", "2025-12-31"),  # already January 1 in UTC
        ("senate", "January 1, 2026,  12:05 AM", "2026-01-01"),  # 12 AM is just after midnight, not noon
        # Month boundary, including a leap day.
        ("house", "30-Sep-2025", "2025-09-30"),
        ("house", "1-Oct-2025", "2025-10-01"),
        ("house", "29-Feb-2024", "2024-02-29"),
        ("senate", "February 28, 2025,  11:45 PM", "2025-02-28"),
        ("senate", "March 1, 2025,  12:00 AM", "2025-03-01"),
        # Surrounding whitespace and a single space before the Senate's time read the same.
        ("house", " 8-Sep-2025 ", "2025-09-08"),
        ("senate", "January 9, 2025, 02:54 PM", "2025-01-09"),
    ],
)
def test_the_day_is_the_printed_day_across_year_and_month_boundaries(chamber, literal, day):
    assert vote_day(chamber, literal) == day


def test_every_day_of_a_leap_and_a_common_year_round_trips_through_both_spellings():
    """The C library's own month names, not this module's table, spell each day; every one reads back."""
    day = date(2024, 1, 1)
    while day.year < 2026:
        assert vote_day("house", f"{day.day}-{day.strftime('%b')}-{day.year}") == day.isoformat()
        assert vote_day("senate", f"{day.strftime('%B')} {day.day}, {day.year},  11:59 PM") == day.isoformat()
        day += timedelta(days=1)


def test_the_day_sorts_chronologically_where_the_literal_does_not():
    printed = ["9-Sep-2024", "10-Jan-2025", "19-Mar-2025", "1-Apr-2025"]  # chronological
    days = [vote_day("house", literal) for literal in printed]
    assert sorted(days) == days
    assert sorted(printed) == ["1-Apr-2025", "10-Jan-2025", "19-Mar-2025", "9-Sep-2024"]


@pytest.mark.parametrize("literal", [None, "", "   "])
@pytest.mark.parametrize("chamber", ["house", "senate"])
def test_an_absent_or_blank_date_is_no_day_not_a_refusal(chamber, literal):
    assert vote_day(chamber, literal) is None


@pytest.mark.parametrize(
    "chamber,literal",
    [
        ("house", "January 9, 2025,  02:54 PM"),  # the other chamber's spelling
        ("senate", "9-Jan-2025"),
        ("senate", "January 3, 2025"),  # a Senate date with no time is not a measured spelling
        ("house", "2025-01-03"),
        ("house", "29-Feb-2025"),  # not a real day
        ("senate", "January 9, 2025,  13:54 PM"),
        # The pattern matches but the month is not in the chamber's table: every
        # retained Senate body spells the month in full, every Clerk body in three letters.
        ("house", "8-Foo-2025"),
        ("senate", "Sept 9, 2025,  02:54 PM"),
        ("senate", "Sep 9, 2025,  02:54 PM"),
        ("house", "8-September-2025"),
    ],
)
def test_an_unrecognized_spelling_refuses_rather_than_guessing(chamber, literal):
    with pytest.raises(VoteSourceError, match="not the chamber's own spelling"):
        vote_day(chamber, literal)


def test_an_unknown_chamber_refuses_even_without_a_date():
    with pytest.raises(VoteSourceError, match="chamber must be"):
        vote_day("joint", None)


def test_a_record_whose_printed_date_cannot_be_read_refuses_at_parse_time():
    body = CLERK_240.replace(b"<action-date>8-Sep-2025</action-date>", b"<action-date>2025-09-08</action-date>")
    with pytest.raises(VoteSourceError, match="not the chamber's own spelling"):
        parse_clerk_vote(body, CLERK_240_LOCATOR)
    senate = (FIXTURES / "senate-vote-119-1-00001.xml").read_bytes()
    printed = b"<vote_date>January 9, 2025,  02:54 PM</vote_date>"
    assert senate.count(printed) == 1
    for unreadable in (b"<vote_date>2025-01-09</vote_date>", b"<vote_date>Sept 9, 2025,  02:54 PM</vote_date>"):
        with pytest.raises(VoteSourceError, match="not the chamber's own spelling"):
            parse_senate_vote(senate.replace(printed, unreadable), VoteLocator("senate", 119, 1, 1))


def test_a_linkage_only_row_never_takes_its_day_from_the_references_utc_instant():
    """A ``VoteKey`` row's ``vote_date`` falls back to the recordedVotes date, a UTC instant; ``vote_day`` stays NULL."""
    key = VoteKey(congress=119, chamber="house", session=1, roll_number=240)
    match = VoteMatch(vote=key, bill=None, rule="unmatched", date="2025-09-09T00:56:00Z")
    row = shape_roll_call_vote(key, match=match)
    assert row["vote_date"] == "2025-09-09T00:56:00Z"
    assert row["vote_day"] is None


def test_a_vote_date_override_keeps_the_day_only_when_it_is_the_records_own_date():
    vote = parse_clerk_vote(CLERK_240, CLERK_240_LOCATOR)
    assert shape_roll_call_vote(vote, vote_date=vote.date)["vote_day"] == "2025-09-08"
    overridden = shape_roll_call_vote(vote, vote_date="9-Sep-2025")
    assert overridden["vote_date"] == "9-Sep-2025" and overridden["vote_day"] is None
