"""Source values survive without census, identifier or legal policy.

Pins the retained agency roster's every row, reference and parent path; survival
of unknown, missing, null, empty, duplicate and malformed values with issues;
raw retention on unexpected document shape; and JSON, numeric and bound refusals.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from spicy_docs.sources.cfr.agencies import read_ecfr_agency_roster
from spicy_docs.sources.cfr.models import CfrSourceError

FIXTURES = Path(__file__).parent / "fixtures" / "cfr_metadata"


def test_retained_complete_roster_has_every_row_reference_and_parent() -> None:
    """The retained roster yields 316 records and 487 references, with every parent path and reference source path
    matching its raw source.
    """
    payload = (FIXTURES / "ecfr-agencies.json").read_bytes()
    result = read_ecfr_agency_roster(payload)
    assert result.raw == json.loads(payload)
    assert not result.issues
    assert len(result.raw["agencies"]) == 153
    assert len(result.records) == 316
    assert sum(len(row.references) for row in result.records) == 487
    assert not any(row.issues for row in result.records)
    indexed = {row.source_path: row for row in result.records}
    for row in result.records:
        assert all(indexed[path].parent_path == row.source_path for path in row.child_paths)
        for ordinal, reference in enumerate(row.references):
            assert reference.source_path == f"{row.source_path}.cfr_references[{ordinal}]"
            assert reference.raw == row.raw["cfr_references"][ordinal]


def test_unknown_missing_null_empty_duplicate_and_malformed_values_survive() -> None:
    """Unknown, missing, null, empty, duplicate and malformed values survive as raw source with issue codes,
    including a Decimal extension.
    """
    raw = {
        "extension": 1.25,
        "agencies": [
            {
                "slug": "same",
                "short_name": "",
                "children": [None, {"slug": "same", "short_name": None}],
                "cfr_references": [None, {"title": "unknown", "extension": False}],
            },
            {"slug": "same", "children": None, "cfr_references": "wrong"},
        ],
    }
    result = read_ecfr_agency_roster(json.dumps(raw).encode())
    assert result.raw["extension"] == Decimal("1.25")
    assert len(result.records) == 4
    assert [row.source_path for row in result.records] == [
        "$.agencies[0]",
        "$.agencies[0].children[0]",
        "$.agencies[0].children[1]",
        "$.agencies[1]",
    ]
    first, malformed, child, last = result.records
    assert first.raw["short_name"] == ""
    assert child.raw["short_name"] is None
    assert "short_name" not in last.raw
    assert malformed.raw is None
    assert malformed.issues[0].code == "object_expected"
    assert first.references[0].raw is None
    assert first.references[1].raw == {"title": "unknown", "extension": False}
    assert ("$.agencies[1].children", "array_expected") in {(x.source_path, x.code) for x in last.issues}


@pytest.mark.parametrize(
    "payload,code", [(b"null", "object_expected"), (b"{}", "missing_field"), (b'{"agencies":null}', "array_expected")]
)
def test_unexpected_document_shape_retains_raw_with_issue(payload: bytes, code: str) -> None:
    """An unexpected document shape retains the raw payload and files an issue code instead of records."""
    result = read_ecfr_agency_roster(payload)
    assert result.raw == json.loads(payload)
    assert result.records == ()
    assert result.issues[0].code == code


@pytest.mark.parametrize(
    "payload",
    [b'{"agencies":[],"agencies":[]}', b'{"agencies":[{"x":1,"x":2}]}', b'{"agencies": [NaN]}', b"\xff", b"{"],
)
def test_ambiguous_or_invalid_json_refuses(payload: bytes) -> None:
    """Ambiguous or invalid JSON is refused."""
    with pytest.raises(CfrSourceError):
        read_ecfr_agency_roster(payload)


@pytest.mark.parametrize("number", [b"9" * 5000, b"1e999999999999999999999999"])
def test_unsupported_numeric_sizes_use_source_refusal(number: bytes) -> None:
    """Unsupported numeric sizes refuse with a source error naming them."""
    with pytest.raises(CfrSourceError, match="unsupported number"):
        read_ecfr_agency_roster(b'{"agencies":[],"extension":' + number + b"}")


@pytest.mark.parametrize(
    "kwargs", [{"max_bytes": 1}, {"max_nodes": 1}, {"max_depth": 1}, {"max_nodes": True}, {"max_depth": 0}]
)
def test_bounds_cover_unknown_fields_too(kwargs: dict[str, int]) -> None:
    """Byte bounds cover unknown fields too."""
    with pytest.raises(CfrSourceError):
        read_ecfr_agency_roster(b'{"agencies":[],"unknown":{"deep":[1]}}', **kwargs)
