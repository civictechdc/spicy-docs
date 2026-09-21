"""Source rows remain literal while receivers decide whether to accept them."""

import hashlib
import json
from pathlib import Path

import pytest

from spicy_docs.sources.federal_register.reference_data import (
    FederalRegisterReferenceError,
    read_fr_agencies,
    read_fr_documented_enums,
    read_fr_type_facets,
)

FIXTURES = Path(__file__).parent / "fixtures/federal_register_reference"
AGENCIES = (FIXTURES / "fr-agencies-2026-08-15.json").read_bytes()
DOCUMENTATION = (FIXTURES / "fr-api-documentation-2026-08-15.json").read_bytes()
FACETS = (FIXTURES / "fr-documents-facets-type-2026-08-15.json").read_bytes()


def test_all_retained_agency_fields_and_positions():
    """Every retained agency field and position is read literally with its source path and digest."""
    result = read_fr_agencies(AGENCIES)
    raw = json.loads(AGENCIES)
    assert result.raw == raw
    assert result.input_sha256 == "70dd0e8fa373a22d5c9577ac1f70ea736542f0e564f816c3caf28014bd05a92b"
    assert result.input_bytes == 694024
    assert len(result.records) == 472
    for index, (row, source) in enumerate(zip(result.records, raw, strict=True)):
        assert row.raw == source
        assert row.source_path == f"$[{index}]"
        assert row.agency_id == source["id"]
        for name in ("slug", "name", "short_name", "description", "url", "json_url", "agency_url", "parent_id"):
            assert getattr(row, name) == source[name]
        assert row.child_ids == tuple(source["child_ids"])
        assert row.child_slugs == tuple(source["child_slugs"])
    assert result.records[0].agency_url == ""
    assert result.records[0].raw["logo"] is None
    assert result.records[1].raw["logo"]["thumb_url"].endswith("thumb.png?1279162074")


def test_all_retained_enum_sets_and_facets():
    """Every retained enum set and facet is read with its schema path and values."""
    result = read_fr_documented_enums(DOCUMENTATION)
    source = json.loads(DOCUMENTATION)
    assert result.raw == source
    assert result.raw["info"]["version"] == ""
    assert result.input_sha256 == "9190df715f0227e62acb57ff924635fc7115732064a5d2c1fb15a57d80879a42"
    assert result.input_bytes == 229776
    assert {row.schema_name: len(row.values) for row in result.enums} == {
        "Agency": 472,
        "DocumentField": 56,
        "DocumentType": 4,
        "Facet": 10,
        "PublicInspectionDocumentField": 27,
        "President": 6,
        "PresidentialDocumentType": 7,
        "Format": 2,
        "Section": 6,
        "SuggestedSearch": 93,
        "Topic": 7772,
    }
    for row in result.enums:
        schema = source["components"]["schemas"][row.schema_name]
        items = "items" in schema
        assert row.raw_schema == schema
        assert row.values == tuple((schema["items"] if items else schema)["enum"])
        assert row.schema_path == f'$.components.schemas["{row.schema_name}"]'
        assert row.source_path == row.schema_path + (".items.enum" if items else ".enum")
    facets = read_fr_type_facets(FACETS)
    assert facets.raw == json.loads(FACETS)
    assert facets.input_sha256 == hashlib.sha256(FACETS).hexdigest()
    assert facets.input_bytes == 187
    assert [row.code for row in facets.records] == ["NOTICE", "RULE", "PRORULE", "PRESDOCU"]
    for row in facets.records:
        assert row.name == row.raw["name"]
        assert row.count == row.raw["count"]
        assert row.source_path == f'$["{row.code}"]'


def test_source_reader_preserves_unreviewed_values_and_unknown_metadata():
    """The source reader preserves unreviewed values and unknown metadata, including duplicate and null enum entries."""
    row = json.loads(AGENCIES)[0]
    row.update(
        id=-1,
        slug="",
        name="",
        url="relative",
        parent_id=99999,
        child_ids=[-2, -2],
        child_slugs=["", ""],
        extra={"decimal": 0.25},
    )
    result = read_fr_agencies(json.dumps([row, row]).encode())
    assert [entry.agency_id for entry in result.records] == [-1, -1]
    assert result.records[0].raw == row
    assert result.records[1].source_path == "$[1]"
    assert read_fr_agencies(b"[]").records == ()
    facets = read_fr_type_facets(b'{"UNKNOWN":{"name":"","count":-2,"extra":true}}')
    assert facets.records[0].raw["extra"] is True
    enum = read_fr_documented_enums(b'{"components":{"schemas":{"new.name":{"enum":[null,7,7],"items":{"enum":[]}}}}}')
    assert enum.enums[0].values == (None, 7, 7)
    assert enum.enums[1].values == ()
    assert enum.enums[0].source_path == '$.components.schemas["new.name"].enum'


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("slug", None),
        ("name", 7),
        ("parent_id", False),
        ("child_ids", [True]),
        ("child_slugs", [None]),
        ("short_name", []),
    ],
)
def test_known_agency_field_types_refuse(field, value):
    """Known agency field types that drift are refused."""
    row = json.loads(AGENCIES)[0]
    row[field] = value
    with pytest.raises(FederalRegisterReferenceError):
        read_fr_agencies(json.dumps([row]).encode())


@pytest.mark.parametrize(
    "reader,payload",
    [
        (read_fr_agencies, b"{}"),
        (read_fr_agencies, b"[{}]"),
        (read_fr_documented_enums, b"{}"),
        (read_fr_documented_enums, b'{"components":{"schemas":{"X":{"enum":"x"}}}}'),
        (read_fr_type_facets, b"[]"),
        (read_fr_type_facets, b'{"X":{"name":"x","count":true}}'),
    ],
)
def test_wrong_source_shapes_refuse(reader, payload):
    """Wrong source shapes are refused."""
    with pytest.raises(FederalRegisterReferenceError):
        reader(payload)


@pytest.mark.parametrize("kwargs", [{"max_bytes": 1}, {"max_nodes": 1}, {"max_depth": 1}, {"max_bytes": True}])
def test_bounds_cover_the_whole_source(kwargs):
    """Bounds cover the whole source."""
    with pytest.raises(FederalRegisterReferenceError):
        read_fr_documented_enums(DOCUMENTATION, **kwargs)
