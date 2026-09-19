"""Enacted-law rows: the citation reaches the row only through a proved join.

The law record and the USLM file are the same law, Public Law 119-1 (S. 5,
the only enacted measure in the captured BILLSTATUS set), cut from the
2026-09-19 captures in
`corpora/supply-2026-09-02/receipts/laws-contract-2026-09-19/` and the
retained ``plaw-119publ1.xml`` fixture: the shaper refuses a USLM meta that
states another law, so a citation can never land on the wrong row. The
whole-corpus facts (108 laws on the list route, 104 in PLAW bulk, 4 lagging;
583 classification rows in both orders) are receipted in that directory.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.schemas.law_tables import (
    STAT_CITE,
    USLM_OUTCOMES,
    law_id,
    shape_law,
    shape_law_code_section,
    shape_table3_record,
)
from spicy_docs.schemas.tables import TableContractError, digest, read_json_column
from spicy_docs.sources.govinfo.uslm import (
    PublicLawSelection,
    public_law_xml_locator,
    validate_public_law_xml,
)
from spicy_docs.sources.uscode import parse_table3_page
from spicy_docs.sources.uscode.classification import parse_classification_table

FIXTURES = Path(__file__).parent / "fixtures"
LAW_RECORD = json.loads((FIXTURES / "listings/congress-law-119-1.json").read_text())
SELECTION = PublicLawSelection(119, "public", 1)
USLM_BYTES = (FIXTURES / "uslm/plaw-119publ1.xml").read_bytes()
USLM = validate_public_law_xml(USLM_BYTES, selection=SELECTION, final_url=public_law_xml_locator(SELECTION))
#: Digested from the fixture's own bytes, so the pin cannot drift from the
#: file; a literal here once carried the law-list page's digest instead.
USLM_SHA256 = digest(USLM_BYTES.decode("utf-8"))
OBSERVED_AT = "2026-09-19T00:00:00Z"


def captured_row():
    return shape_law(
        LAW_RECORD,
        LAW_RECORD["laws"][0],
        uslm=USLM,
        uslm_sha256=USLM_SHA256,
        uslm_observed_at=OBSERVED_AT,
        uslm_outcome="captured",
    )


def test_the_statutes_at_large_citation_comes_from_the_uslm_meta_only_through_a_proved_join():
    row = captured_row()
    assert row["law_id"] == "119-public-1"
    assert (row["congress"], row["law_type"], row["number"]) == ("119", "public", "1")
    assert row["law_number"] == "119-1" and row["publisher_law_type"] == "Public Law"
    assert row["package_id"] == "PLAW-119publ1"
    assert (row["bill_id"], row["bill_type"], row["bill_number"]) == ("119-s-5", "s", "5")
    assert row["statutes_at_large_cite"] == "139 Stat. 3"
    assert (row["statutes_at_large_volume"], row["statutes_at_large_page"]) == ("139", "3")
    assert row["approved_date"] == "2025-01-29"
    assert row["uslm_title"].startswith("Public Law 119–1:")
    assert row["uslm_processed_date"] == "2026-09-09"
    assert row["uslm_sha256"] == USLM_SHA256 and row["uslm_outcome"] == "captured"


def test_a_uslm_meta_for_another_law_never_fills_a_row():
    other = json.loads((FIXTURES / "listings/congress-law-list.json").read_text())["bills"][0]
    with pytest.raises(TableContractError, match="USLM meta states"):
        shape_law(other, {"number": "119-110", "type": "Public Law"}, uslm=USLM, uslm_outcome="captured")


def test_a_null_citation_is_read_through_its_outcome_column():
    plain = shape_law(LAW_RECORD, LAW_RECORD["laws"][0])
    assert plain["statutes_at_large_cite"] is None
    assert plain["uslm_outcome"] == "not_requested"
    assert plain["uslm_sha256"] is None and plain["approved_date"] is None
    lagged = shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="unavailable")
    assert lagged["statutes_at_large_cite"] is None and lagged["uslm_outcome"] == "unavailable"


def test_a_captured_uslm_that_names_no_statutes_citation_is_refused():
    # ``captured`` promises a citation; a meta without one must not publish a NULL that reads as the bulk lag.
    with pytest.raises(TableContractError, match="names no Statutes at Large citation"):
        shape_law(
            LAW_RECORD,
            LAW_RECORD["laws"][0],
            uslm=replace(USLM, citable_as=("Public Law 119-1",)),
            uslm_outcome="captured",
        )


def test_the_outcome_and_the_uslm_record_travel_together():
    for outcome in USLM_OUTCOMES:
        assert outcome in ("captured", "unavailable", "not_requested")
    with pytest.raises(TableContractError, match="exactly when"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm=USLM, uslm_outcome="not_requested")
    with pytest.raises(TableContractError, match="exactly when"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="captured")
    with pytest.raises(TableContractError, match="uslm_outcome must be one of"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="assumed")


def test_the_law_number_carries_its_own_congress():
    assert law_id(119, "public", 1) == "119-public-1"
    with pytest.raises(TableContractError, match="another Congress"):
        shape_law({"congress": 118, "type": "S", "number": "5"}, {"number": "119-1", "type": "Public Law"})
    with pytest.raises(TableContractError, match="not congress-number"):
        shape_law({"congress": 119, "type": "S", "number": "5"}, {"number": "119-", "type": "Public Law"})


def test_the_publishers_law_type_folds_onto_one_sealed_spelling():
    assert STAT_CITE.fullmatch("139 Stat. 3")[0] == "139 Stat. 3"
    private = shape_law(LAW_RECORD, {"number": "119-1", "type": "Private Law"})
    assert (private["law_type"], private["publisher_law_type"]) == ("private", "Private Law")
    assert private["package_id"] == "PLAW-119pvtl1"
    with pytest.raises(TableContractError, match="unknown law type"):
        shape_law(LAW_RECORD, {"number": "119-1", "type": "Pocket Law"})
    with pytest.raises(TableContractError, match="needs a string type"):
        shape_law(LAW_RECORD, {"number": "119-1", "type": None})


def test_law_code_sections_rows_from_the_classification_table():
    table = parse_classification_table(
        (FIXTURES / "uscode/classification-tbl119pl_2nd-head.htm").read_bytes(), congress=119, session=2
    )
    row = shape_law_code_section(table.records[0], table=table, observed_at=OBSERVED_AT)
    assert (row["congress"], row["session"], row["seq"]) == ("119", "2", "0")
    assert (row["law_id"], row["law_type"], row["law_number"]) == ("119-public-70", "public", "119-70")
    assert (row["usc_title"], row["usc_section"], row["action"]) == ("42", "5301", "nt new")
    assert (row["statutes_at_large_volume"], row["statutes_at_large_page"]) == ("140", "3")
    assert (row["link_volume"], row["link_page"]) == ("140", "3")
    assert row["table_order"] == "public-law"
    assert row["stated_laws"] == "Public Law 119-70 and Public Laws 119-74 through 119-110"
    spanned = next(record for record in table.records if record.link_volume is None)
    span_row = shape_law_code_section(spanned, table=table, observed_at=OBSERVED_AT)
    assert span_row["action"] is None  # the legend reads blank as amended; the row keeps the blank
    assert span_row["statutes_at_large_page"] == "637, 638"
    assert span_row["link_volume"] is None and span_row["link_page"] is None


def test_table3_records_rows_from_the_table_iii_page():
    page = parse_table3_page((FIXTURES / "uscode/table3-111_226-head.htm").read_bytes(), key="111-226")
    row = shape_table3_record(page.records[0], page=page, seq=0, observed_at=OBSERVED_AT)
    assert row["act_key"] == "111-226"
    assert row["stated_key"] == "111–226"  # the page spells the key with an en dash; both are kept
    assert (row["congress"], row["act_date"]) == ("111th Cong.", "Aug. 10, 2010")
    assert row["statutes_at_large_volume"] == "124 Stat."
    assert row["release_point"] == "119-73"
    assert (row["act_section"], row["usc_title"], row["usc_section"]) == ("1", "26", "1 nt")
    assert (row["record_volume"], row["record_page"]) == ("124", "2389")
    assert row["status"] is None


def test_the_committee_fold_builds_one_json_row_per_detail_record():
    # Placed here so the whole laws/rosters shaping surface is exercised through
    # one import; the committees-specific refusals live in test_committee_rosters.py.
    from spicy_docs.schemas.roster_tables import shape_committee

    detail = json.loads((FIXTURES / "listings/congress-committee-detail.json").read_text())["committee"]
    row = shape_committee(
        json.loads((FIXTURES / "listings/congress-committee-hsju00-list-row.json").read_text()), detail
    )
    assert row["system_code"] == "hsju00" and row["detail_captured"] == "true"
    assert row["subcommittee_count"] == "15"
    assert read_json_column(row["subcommittees_json"])[:3] == ["hlqj00", "hsju11", "hsju04"]
    assert row["history_count"] == "1"
    assert read_json_column(row["history_json"])[0]["officialName"] == "Committee on the Judiciary"
    assert row["is_current"] == "true" and row["bill_count"] == "74362"


def test_the_detail_wins_the_subcommittee_fold_even_when_it_lists_none():
    from spicy_docs.schemas.roster_tables import shape_committee

    list_row = json.loads((FIXTURES / "listings/congress-committee-hsju00-list-row.json").read_text())
    detail = json.loads((FIXTURES / "listings/congress-committee-detail.json").read_text())["committee"]
    assert len(list_row["subcommittees"]) == 7 and len(detail["subcommittees"]) == 15
    assert shape_committee(list_row)["subcommittee_count"] == "7"
    assert shape_committee(list_row, detail)["subcommittee_count"] == "15"
    emptied = shape_committee(list_row, {**detail, "subcommittees": []})
    assert emptied["subcommittee_count"] == "0" and read_json_column(emptied["subcommittees_json"]) == []
    with pytest.raises(TableContractError, match="needs a systemCode"):
        shape_committee(list_row, {**detail, "subcommittees": [{"name": "no code"}]})
