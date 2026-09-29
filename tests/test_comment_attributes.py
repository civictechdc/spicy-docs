"""comment_attributes: document_attributes' rules applied to comments, less the owner's email, phone and fax ruling."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spicy_docs.schemas import TABLE_CONTRACTS, TableContractError
from spicy_docs.schemas.regulations import COMMENT
from spicy_docs.schemas.regulations_attribute_tables import (
    COMMENT_ATTRIBUTES_LEFT_OUT,
    attribute_of,
    project_comment_attributes,
)
from spicy_docs.sources.regulations_gov.definitions import COMMENT_ATTRIBUTE_FIELDS

FIXTURES = Path(__file__).parent / "fixtures/regulations_gov_comments"
#: Stated rows and exact distinct values per attribute the thin table does not map, over the spicy-regs re-read of every
#: comment (2026-09-28); the fixture README names its receipt.
CENSUS = json.loads((FIXTURES / "attribute-census.json").read_text())

#: comment_attributes as first published, in attribute order like document_attributes. Frozen: a newly stated attribute
#: is appended after these, so no published column moves.
FIRST_PUBLISHED = (
    "comment_id",
    "address1",
    "address2",
    "city",
    "country",
    "display_properties_json",
    "doc_abstract",
    "field1",
    "field2",
    "file_formats_json",
    "gov_agency",
    "gov_agency_type",
    "legacy_id",
    "object_id",
    "page_count",
    "postmark_date",
    "reason_withdrawn",
    "restrict_reason",
    "restrict_reason_type",
    "state_province_region",
    "submitter_rep",
    "submitter_rep_address",
    "submitter_rep_city_state",
    "tracking_nbr",
    "withdrawn",
    "zip",
)


def _constant(stated: dict | None) -> bool:
    """Stated on every comment read, with one value."""
    return stated is not None and stated["stated"] == CENSUS["rows"] and stated["distinct_values"] == 1


#: What each reason for leaving an attribute out claims of the census; the owner's ruling is by attribute, whatever is
#: stated.
_REASON_HOLDS = {
    "private contact details, left out by owner ruling (2026-09-28)": lambda stated: True,
    "never stated": lambda stated: stated is None,
    "constant (false)": _constant,
}


def _records() -> dict[str, dict]:
    return {
        data["id"]: data
        for data in (json.loads(path.read_text())["data"] for path in sorted(FIXTURES.glob("*.source.json")))
    }


def _thin_attributes() -> set[str]:
    """The attributes COMMENT.extract reads, derived: changing one changes the extracted row."""
    read = set()
    for data in _records().values():
        raw = {"data": data}
        base = COMMENT.extract(raw)
        for key in data["attributes"]:
            changed = json.loads(json.dumps(raw))
            changed["data"]["attributes"][key] = "⁣probe"
            try:
                if COMMENT.extract(changed) != base:
                    read.add(key)
            except ValueError:  # the extract reads it and refuses the probe's type (duplicateComments)
                read.add(key)
    return read


def test_every_comment_attribute_is_a_column_carried_by_comments_or_left_out_for_a_stated_reason():
    columns = {attribute_of(column) for column in TABLE_CONTRACTS["comment_attributes"].columns[1:]}
    left_out = [attribute for attributes in COMMENT_ATTRIBUTES_LEFT_OUT.values() for attribute in attributes]
    thin = _thin_attributes()
    assert len(left_out) == len(set(left_out))
    parts = (columns, thin, set(left_out))
    assert set().union(*parts) == COMMENT_ATTRIBUTE_FIELDS
    assert sum(len(part) for part in parts) == len(COMMENT_ATTRIBUTE_FIELDS)  # disjoint


def test_the_census_holds_every_column_and_every_reason_for_leaving_one_out():
    """A published attribute the census never finds stated fails, as does a left-out one it contradicts (moving
    ``fileFormats`` to "never stated", mutant M9) and an attribute it finds stated that is neither."""
    census = CENSUS["attributes"]
    columns = {attribute_of(column) for column in TABLE_CONTRACTS["comment_attributes"].columns[1:]}
    left_out = {attribute: reason for reason, group in COMMENT_ATTRIBUTES_LEFT_OUT.items() for attribute in group}
    assert set(census) <= columns | set(left_out)
    assert columns <= set(census)
    assert not [attribute for attribute in columns if _constant(census[attribute])]
    assert not [(a, reason) for a, reason in left_out.items() if not _REASON_HOLDS[reason](census.get(a))]


def test_the_first_published_column_order_is_frozen_and_a_later_attribute_appends():
    assert TABLE_CONTRACTS["comment_attributes"].columns[: len(FIRST_PUBLISHED)] == FIRST_PUBLISHED


def test_email_phone_and_fax_are_left_out_even_when_stated():
    contract = TABLE_CONTRACTS["comment_attributes"]
    assert not {"email", "phone", "fax"} & set(contract.columns)
    assert COMMENT_ATTRIBUTES_LEFT_OUT["private contact details, left out by owner ruling (2026-09-28)"] == (
        "email",
        "fax",
        "phone",
    )
    stated = {"email": "a@example.org", "phone": "555", "fax": "202-555-0100", "city": "Washington"}
    row = project_comment_attributes("X-1", stated)
    assert row["city"] == "Washington" and not {"email", "phone", "fax"} & set(row)


def test_the_exclusion_is_by_attribute_not_by_value():
    """A contact-shaped value typed into a published field is published as stated (owner, 2026-09-28)."""
    row = project_comment_attributes("X-1", {"city": "someone@example.org", "submitterRep": "202-555-0100"})
    assert (row["city"], row["submitter_rep"]) == ("someone@example.org", "202-555-0100")


def test_the_contact_columns_are_decision_66s_less_email_phone_and_fax():
    documents = set(TABLE_CONTRACTS["document_attributes"].columns)
    comments = set(TABLE_CONTRACTS["comment_attributes"].columns)
    contact = {"address1", "address2", "city", "state_province_region", "zip", "country", "submitter_rep"}
    assert contact <= comments and contact <= documents
    assert "fax" in documents and "fax" not in comments


def test_retained_comments_project_typed_as_stated():
    records = _records()
    campaign = records["EPA-HQ-OW-2022-0114-1811"]
    row = project_comment_attributes(campaign["id"], campaign["attributes"])
    stated = campaign["attributes"]
    assert (row["withdrawn"], row["page_count"], row["object_id"], row["tracking_nbr"]) == (
        stated["withdrawn"],
        stated["pageCount"],
        stated["objectId"],
        stated["trackingNbr"],
    )
    assert type(row["page_count"]) is int and type(row["withdrawn"]) is bool
    mailed = project_comment_attributes("X-1", {"postmarkDate": "2021-10-26T00:00:00Z"})
    assert mailed["postmark_date"] == datetime(2021, 10, 26, tzinfo=UTC)


@pytest.mark.parametrize(
    ("attribute", "stated"),
    [
        ("postmarkDate", "2021-10-26"),
        ("postmarkDate", "2021-10-26T00:00:00.5Z"),
        ("withdrawn", "true"),
        ("pageCount", 2**31),
        ("pageCount", "3"),
        ("displayProperties", "labels"),
        ("city", 7),
    ],
)
def test_a_value_of_the_wrong_type_refuses(attribute, stated):
    with pytest.raises(TableContractError):
        project_comment_attributes("X-1", {attribute: stated})
