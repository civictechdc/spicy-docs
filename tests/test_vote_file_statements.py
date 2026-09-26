"""A roll call's link to a bill from its own file: the Clerk's legis-num, the Senate's document or amended document.

The real fixtures pin one of each measured shape; synthetic rows isolate the refusals. Every case reads a
``roll_call_votes`` row, the same columns a held row is relinked from without fetching its file again.
"""

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.vote_matching import (
    VOTE_FILE_RULE,
    VOTE_MATCH_RULES,
    VoteMatchError,
    read_vote_file_statement,
)
from spicy_docs.schemas.congress_activity_tables import ROLL_CALL_VOTES, shape_roll_call_vote
from spicy_docs.schemas.tables import bill_id
from spicy_docs.sources.congress.votes import VoteLocator, parse_clerk_vote, parse_senate_vote

FIXTURES = Path(__file__).parent / "fixtures" / "congress_votes"


def _row(name, locator):
    parse = parse_clerk_vote if locator.chamber == "house" else parse_senate_vote
    return shape_roll_call_vote(parse((FIXTURES / name).read_bytes(), locator))


@pytest.mark.parametrize(
    ("fixture", "locator", "status", "statement", "bill"),
    [
        ("clerk-roll240.xml", VoteLocator("house", 119, 1, 240), "bill", "H R 3424", "119-hr-3424"),
        ("clerk-speaker-119-1-2.xml", VoteLocator("house", 119, 1, 2), "none", None, None),
        ("senate-vote-119-1-00001.xml", VoteLocator("senate", 119, 1, 1), "bill", "S. 5", "119-s-5"),
        ("senate-vote-108-2-00213.xml", VoteLocator("senate", 108, 2, 213), "bill", "S. 2986", "108-s-2986"),
        # An impeachment verdict names the House resolution that impeached.
        ("senate-vote-117-1-00059.xml", VoteLocator("senate", 117, 1, 59), "bill", "H.Res. 24", "117-hres-24"),
        # En bloc nominations: 48 documents, none a bill.
        ("senate-vote-119-1-00522.xml", VoteLocator("senate", 119, 1, 522), "not_a_bill", None, None),
    ],
)
def test_each_real_file_links_only_the_bill_it_names(fixture, locator, status, statement, bill):
    row = _row(fixture, locator)
    read = read_vote_file_statement(row)
    assert read.status == status
    if statement is not None:
        assert read.statement == statement
    assert (None if read.reference is None else bill_id(read.reference.bill)) == bill
    if bill is not None:
        assert read.reference.rule == VOTE_FILE_RULE and read.reference.url == row["source_url"]
        assert read.reference.action_index is None


def test_the_contract_keeps_the_clerks_legis_num_so_a_held_row_relinks_without_its_file():
    assert ROLL_CALL_VOTES.columns[-1] == "legis_num"
    assert _row("clerk-roll240.xml", VoteLocator("house", 119, 1, 240))["legis_num"] == "H R 3424"
    assert _row("clerk-speaker-119-1-2.xml", VoteLocator("house", 119, 1, 2))["legis_num"] == ""
    assert _row("senate-vote-119-1-00001.xml", VoteLocator("senate", 119, 1, 1))["legis_num"] is None
    assert VOTE_FILE_RULE in VOTE_MATCH_RULES


HOUSE = {"congress": "108", "chamber": "house", "session": "1", "roll_number": "7", "source_url": "u"}


@pytest.mark.parametrize(
    ("legis_num", "status", "bill"),
    [
        ("H R 3354", "bill", "108-hr-3354"),
        ("H RES 682", "bill", "108-hres-682"),
        ("H J RES 1", "bill", "108-hjres-1"),
        ("H CON RES 5", "bill", "108-hconres-5"),
        ("S 2986", "bill", "108-s-2986"),
        ("S J RES 9", "bill", "108-sjres-9"),
        ("S CON RES 12", "bill", "108-sconres-12"),
        ("QUORUM", "not_a_bill", None),
        ("JOURNAL", "not_a_bill", None),
        ("ADJOURN", "not_a_bill", None),
        ("MOTION", "not_a_bill", None),
        ("", "none", None),
        (None, "none", None),
        ("H AMDT 5", "unrecognized", None),
        ("H R", "unrecognized", None),
    ],
)
def test_the_clerks_measured_legis_num_vocabulary(legis_num, status, bill):
    read = read_vote_file_statement(HOUSE | {"legis_num": legis_num})
    assert read.status == status
    assert (None if read.reference is None else bill_id(read.reference.bill)) == bill


SENATE = {"congress": "108", "chamber": "senate", "session": "1", "roll_number": "305", "source_url": "u"}


def _senate(documents, amendments=()):
    return read_vote_file_statement(
        SENATE | {"documents_json": json.dumps(list(documents)), "amendments_json": json.dumps(list(amendments))}
    )


def _document(kind, number, congress=None):
    return {"congress": congress, "type": kind, "number": number}


@pytest.mark.parametrize(
    ("documents", "amendments", "status", "bill"),
    [
        # 108th files often omit document_congress; the vote's own Congress is the bill's.
        ([_document("H.R.", "1307")], [], "bill", "108-hr-1307"),
        ([_document("S.Res.", "30", 108)], [], "bill", "108-sres-30"),
        # An amendment vote's document is empty; its amendment names the measure amended.
        (
            [_document(None, None, 108)],
            [{"number": "S.Amdt. 1383", "to_document_number": "H.R. 2555"}],
            "bill",
            "108-hr-2555",
        ),
        ([_document("PN", "17")], [], "not_a_bill", None),
        ([_document("Treaty Doc.", "107-8")], [], "not_a_bill", None),
        ([_document("S.Amdt.", None), _document("PN", "55-25")], [], "not_a_bill", None),
        ([_document(None, None)], [{"to_document_number": "Treaty Doc. 107-8"}], "not_a_bill", None),
        ([_document("H.R.", "1"), _document("S.", "2")], [], "several", None),
        ([_document("H.R.", "1"), _document("H.R.", "1")], [], "bill", "108-hr-1"),
        ([_document(None, None)], [], "none", None),
        ([], [], "none", None),
        ([_document("Mystery", "1")], [], "unrecognized", None),
    ],
)
def test_the_senates_documents_and_amended_documents(documents, amendments, status, bill):
    read = _senate(documents, amendments)
    assert read.status == status
    assert (None if read.reference is None else bill_id(read.reference.bill)) == bill


def test_a_legacy_row_without_documents_states_nothing_and_a_malformed_list_refuses():
    assert read_vote_file_statement(SENATE | {"documents_json": None, "amendments_json": None}).status == "none"
    with pytest.raises(VoteMatchError, match="lists of objects"):
        read_vote_file_statement(SENATE | {"documents_json": '{"type": "S."}', "amendments_json": "[]"})
