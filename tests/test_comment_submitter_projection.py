"""The agency's submitter class and campaign count reach the comments table as stated."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.regulations import COMMENT
from spicy_docs.sources.regulations_gov.records import classify_comment

FIXTURES = Path(__file__).parent / "fixtures/regulations_gov_comments"
SHA256 = {
    "EPA-HQ-OW-2022-0114-1811": "dccedb9f286dfca158b5a2ae6d0a77cda946b7d1fd884098e36a2444391b0261",
    "EPA-HQ-OW-2022-0114-0017": "895d3528bd3bdaa12cd1e43ff9401c8f388724e0a7fa338d8454015fedd43127",
    "EPA-HQ-OW-2022-0114-0002": "69ec303bb31cac609d99c9619109059c95a8d5e4133e125f1826e7d0b23829af",
    "CMS-2016-0123-0993": "8d6e7d9e6dcbcd02d7c597690836175eb0ace9a5402ac8323df7c65f53961630",
}


def _row(comment_id: str) -> dict:
    body = (FIXTURES / f"{comment_id}.source.json").read_bytes()
    assert hashlib.sha256(body).hexdigest() == SHA256[comment_id]
    return COMMENT.extract(classify_comment(json.loads(body)))


@pytest.mark.parametrize(
    ("comment_id", "subtype", "duplicate_comments"),
    [
        # A campaign: one posted record for 15,851 submissions.
        ("EPA-HQ-OW-2022-0114-1811", "Mass Mail Campaign", 15851),
        # An organization EPA classifies although the record names no organization.
        ("EPA-HQ-OW-2022-0114-0017", "Company/Organization Comment", 1),
        ("EPA-HQ-OW-2022-0114-0002", "Public Comment", 1),
        # An agency that does not count states 0, which stays 0.
        ("CMS-2016-0123-0993", "Public Comment", 0),
    ],
)
def test_retained_records_publish_subtype_and_count_as_stated(comment_id, subtype, duplicate_comments):
    row = _row(comment_id)
    assert row["comment_id"] == comment_id
    assert (row["subtype"], row["duplicate_comments"]) == (subtype, duplicate_comments)
    assert type(row["duplicate_comments"]) is int
    assert TABLE_CONTRACTS["comments"].checked({**row, "pdf_extraction_results_json": None})


def test_the_organization_class_is_in_subtype_not_organization():
    row = _row("EPA-HQ-OW-2022-0114-0017")
    assert row["organization"] is None and row["category"] is None


def test_unstated_fields_stay_null_and_a_stated_null_subtype_stays_null():
    assert {
        k: v for k, v in COMMENT.extract({"data": {"attributes": {}}}).items() if k in ("subtype", "duplicate_comments")
    } == {"subtype": None, "duplicate_comments": None}
    assert (
        COMMENT.extract({"data": {"attributes": {"subtype": None, "duplicateComments": 0}}})["duplicate_comments"] == 0
    )


def test_the_contract_types_the_count_and_places_both_after_category():
    contract = TABLE_CONTRACTS["comments"]
    assert contract.column_type("duplicate_comments") == "INTEGER"
    assert contract.column_type("subtype") == "VARCHAR"
    at = contract.columns.index("category")
    assert contract.columns[at + 1 : at + 3] == ("subtype", "duplicate_comments")
