"""The agency's submitter class and campaign count reach the comments table as stated."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS
from spicy_docs.schemas.regulations import COMMENT
from spicy_docs.sources.regulations_gov.definitions import RegulationsGovSourceError
from spicy_docs.sources.regulations_gov.records import classify_comment
from spicy_docs.sources.regulations_gov.validation import _validate_comment_attributes

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


def test_unstated_and_stated_null_fields_stay_null_and_a_stated_zero_stays_zero():
    def fields(attributes):
        row = COMMENT.extract({"data": {"attributes": attributes}})
        return row["subtype"], row["duplicate_comments"]

    assert fields({}) == (None, None)  # not stated
    assert fields({"subtype": None, "duplicateComments": None}) == (None, None)  # stated null: never "" or 0
    assert fields({"subtype": "", "duplicateComments": 0}) == ("", 0)  # stated empty and zero, as stated


@pytest.mark.parametrize("stated", ["5", True, 1.5, -1, 2**31])
def test_a_count_that_is_not_a_non_negative_32_bit_integer_refuses(stated):
    """Never coerced: the host's Int32 frame would turn "5" into 5, True into 1 and 1.5 into 1."""
    with pytest.raises(ValueError, match="duplicateComments"):
        COMMENT.extract({"data": {"attributes": {"duplicateComments": stated}}})
    with pytest.raises(RegulationsGovSourceError, match="duplicateComments"):
        _validate_comment_attributes({"duplicateComments": stated})


def test_the_largest_count_is_kept():
    assert (
        COMMENT.extract({"data": {"attributes": {"duplicateComments": 2**31 - 1}}})["duplicate_comments"] == 2**31 - 1
    )


@pytest.mark.parametrize("stated", ["3", -1, True, 2**31])
def test_page_count_is_admitted_only_as_the_projector_types_it(stated):
    """A typed host column takes page_count as INTEGER; the validator admits no more than that."""
    with pytest.raises(RegulationsGovSourceError, match="pageCount"):
        _validate_comment_attributes({"pageCount": stated})


def test_the_contract_types_the_count_and_appends_both():
    """Appended, so every live column keeps its position (docs/tables.md) and a catalog ADD COLUMN agrees."""
    contract = TABLE_CONTRACTS["comments"]
    assert contract.column_type("duplicate_comments") == "INTEGER"
    assert contract.column_type("subtype") == "VARCHAR"
    assert contract.columns[-2:] == ("subtype", "duplicate_comments")
    assert tuple(COMMENT.schema)[-2:] == ("subtype", "duplicate_comments")
