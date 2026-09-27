"""Native positive amendment/treaty blocks stay independent and publisher-spelled."""

import hashlib
import json
from pathlib import Path

from spicy_docs.sources.congress.votes import VoteLocator, parse_senate_vote

FIXTURES = Path(__file__).parent / "fixtures/congress_votes"


def source(name, kind):
    body = (FIXTURES / name).read_bytes()
    receipts = json.loads((FIXTURES / "amendment-treaty-provenance-2026-09-27.json").read_text())
    receipt = next(row for row in receipts if row["kind"] == kind)
    assert "sha256:" + hashlib.sha256(body).hexdigest() == receipt["sha256"]
    return body


def test_native_amendment_does_not_require_a_nonempty_document_block():
    vote = parse_senate_vote(source("senate-vote-108-2-00172.xml", "amendment"), VoteLocator("senate", 108, 2, 172))
    assert vote.amendments[0].number == "S.Amdt. 3609"
    assert vote.amendments[0].to_document_number == "H.R. 4567"
    assert vote.documents[0].number is None
    assert vote.documents[0].congress is None


def test_treaty_document_number_can_name_a_different_congress_than_vote_context():
    vote = parse_senate_vote(source("senate-vote-109-1-00244.xml", "treaty"), VoteLocator("senate", 109, 1, 244))
    document = vote.documents[0]
    assert (document.congress, document.type, document.number, document.name) == (
        109,
        "Treaty Doc.",
        "108-6",
        "Treaty Doc. 108-6",
    )
    assert vote.amendments[0].number is None
    assert vote.amendments[0].purpose == "No Statement of Purpose on File."
