"""Native parent-document evidence stays distinct from docket and object IDs."""

import hashlib
import json
from pathlib import Path

from spicy_docs.schemas.regulations import COMMENT
from spicy_docs.sources.regulations_gov.records import classify_comment


def test_retained_null_docket_comment_preserves_parent_reference():
    body = (Path(__file__).parent / "fixtures/regulations_gov_comments/ODNI-2009-0004-0002.source.json").read_bytes()
    assert hashlib.sha256(body).hexdigest() == "d5ac7aa71069e0b52efc05497f623f804118b029db76ba0a967680ed64433413"
    raw = json.loads(body)
    parsed = classify_comment(raw)
    row = COMMENT.extract(parsed)
    assert row["docket_id"] is None
    assert row["comment_on_document_id"] == "ODNI-2009-0004-0001"
    assert row["comment_on_object_id"] == "0900006480a18cfe"
    assert row["original_document_id"] == "ODNI_FRDOC_0001-0004"
    assert json.loads(row["comment_reference_values_json"]) == {
        field: raw["data"]["attributes"][field] for field in ("commentOnDocumentId", "commentOn", "originalDocumentId")
    }


def test_projection_preserves_missing_null_and_empty_reference_states():
    for attributes in ({}, {"commentOnDocumentId": None}, {"commentOnDocumentId": ""}):
        row = COMMENT.extract({"data": {"attributes": attributes}})
        assert json.loads(row["comment_reference_values_json"]) == attributes
