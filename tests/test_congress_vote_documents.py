"""Senate en-bloc votes preserve the complete ordered document list."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.interpretation.vote_matching import VoteKey
from spicy_docs.schemas.congress_activity_tables import shape_roll_call_vote
from spicy_docs.sources.congress.votes import VoteLocator, VoteSourceError, parse_senate_vote

FIXTURES = Path(__file__).parent / "fixtures" / "congress_votes"
RAW = (FIXTURES / "senate-vote-119-1-00522.xml").read_bytes()
LOCATOR = VoteLocator("senate", 119, 1, 522)


def document_fields(element):
    return {
        "congress": int(element.findtext("document_congress")),
        **{
            name: (element.findtext("document_" + name) or "").strip() or None
            for name in ("type", "number", "name", "title", "short_title")
        },
    }


def test_native_plural_documents_keep_every_field_and_source_order():
    vote = parse_senate_vote(RAW, LOCATOR)
    raw_documents = ET.fromstring(RAW).findall("document")
    assert len(vote.documents) == len(raw_documents) == 48
    assert [asdict(document) for document in vote.documents] == [document_fields(raw) for raw in raw_documents]
    assert [document.number for document in vote.documents[:3]] == ["55-25", "55-45", "54-7"]
    assert vote.document is None
    raw_amendments = ET.fromstring(RAW).findall("amendment")
    assert len(vote.amendments) == len(raw_amendments) == 48
    assert vote.amendment is None
    assert [asdict(amendment) for amendment in vote.amendments] == [
        {
            field: (raw.findtext("amendment_" + field) or "").strip() or None
            for field in (
                "number",
                "to_amendment_number",
                "to_amendment_to_amendment_number",
                "to_document_number",
                "to_document_short_title",
                "purpose",
            )
        }
        for raw in raw_amendments
    ]
    assert len(vote.member_votes) == 100
    row = shape_roll_call_vote(vote, tally=vote.tallies)
    assert json.loads(row["documents_json"]) == [document_fields(raw) for raw in raw_documents]
    assert json.loads(row["amendments_json"]) == [asdict(amendment) for amendment in vote.amendments]


def test_single_document_compatibility_and_zero_document_absence():
    raw = (FIXTURES / "senate-vote-119-1-00001.xml").read_bytes()
    locator = VoteLocator("senate", 119, 1, 1)
    one = parse_senate_vote(raw, locator)
    assert one.documents == (one.document,)
    assert one.document.number == "5"
    assert one.amendments == (one.amendment,)
    manual_legacy = replace(one, documents=(), amendments=())
    for field in ("documents_json", "amendments_json"):
        assert shape_roll_call_vote(manual_legacy)[field] == shape_roll_call_vote(one)[field]
    plural = parse_senate_vote(RAW, LOCATOR)
    with_legacy_alias = replace(plural, document=one.document, amendment=one.amendment)
    for field in ("documents_json", "amendments_json"):
        assert shape_roll_call_vote(with_legacy_alias)[field] == shape_roll_call_vote(plural)[field]
    root = ET.fromstring(raw)
    root.remove(root.find("document"))
    root.remove(root.find("amendment"))
    none = parse_senate_vote(ET.tostring(root), locator)
    assert none.documents == () and none.document is None
    assert none.amendments == () and none.amendment is None
    for field in ("documents_json", "amendments_json"):
        assert shape_roll_call_vote(none)[field] == "[]"
        assert shape_roll_call_vote(VoteKey(119, "senate", 1, 1))[field] is None


@pytest.mark.parametrize("malformed", ["congress", "repeated_number"])
def test_malformed_document_fields_still_refuse(malformed):
    root = ET.fromstring(RAW)
    document = root.findall("document")[2]
    if malformed == "congress":
        document.find("document_congress").text = "unknown"
    else:
        ET.SubElement(document, "document_number").text = "other"
    with pytest.raises(VoteSourceError):
        parse_senate_vote(ET.tostring(root), LOCATOR)


def test_repeated_child_within_an_amendment_still_refuses():
    root = ET.fromstring(RAW)
    ET.SubElement(root.findall("amendment")[2], "amendment_number").text = "other"
    with pytest.raises(VoteSourceError):
        parse_senate_vote(ET.tostring(root), LOCATOR)
