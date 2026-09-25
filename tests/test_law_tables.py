"""Enacted-law rows: the citation reaches the row only through a proved join.

Pins Public Law 119-1 (S. 5) from the retained list record and
``plaw-119publ1.xml`` fixture: the Statutes at Large cite, volume and page come
from the USLM meta only when it states the same law, and ``captured`` promises
a citation. Also pins the classification-table, Table III and committee-detail
folds, and the U.S. Code section key both OLRC tables append.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.schemas.law_tables import (
    LAW_CODE_SECTIONS,
    STAT_CITE,
    TABLE3_RECORDS,
    USLM_OUTCOMES,
    law_id,
    shape_law,
    shape_law_code_section,
    shape_table3_record,
)
from spicy_docs.schemas.tables import (
    DASH_SPELLINGS,
    TableContractError,
    digest,
    read_json_column,
    usc_section_key,
)
from spicy_docs.sources.govinfo.uslm import (
    PublicLawSelection,
    UslmIdentityError,
    UslmSourceError,
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
    """The shaped row carries law and bill identity plus the Statutes at Large cite from the proved USLM join."""
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
    """A USLM meta stating another law raises ``TableContractError`` instead of filling the row."""
    other = json.loads((FIXTURES / "listings/congress-law-list.json").read_text())["bills"][0]
    with pytest.raises(TableContractError, match="USLM meta states"):
        shape_law(other, {"number": "119-110", "type": "Public Law"}, uslm=USLM, uslm_outcome="captured")


def test_a_null_citation_is_read_through_its_outcome_column():
    """A missing citation stays null with outcome ``not_requested``, and ``unavailable`` keeps it null too."""
    plain = shape_law(LAW_RECORD, LAW_RECORD["laws"][0])
    assert plain["statutes_at_large_cite"] is None
    assert plain["uslm_outcome"] == "not_requested"
    assert plain["uslm_sha256"] is None and plain["approved_date"] is None
    lagged = shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="unavailable")
    assert lagged["statutes_at_large_cite"] is None and lagged["uslm_outcome"] == "unavailable"


def test_a_captured_uslm_without_a_statutes_citation_retains_native_metadata():
    row = shape_law(
        LAW_RECORD,
        LAW_RECORD["laws"][0],
        uslm=replace(USLM, citable_as=("Public Law 119-1",)),
        uslm_outcome="captured",
        uslm_sha256=USLM_SHA256,
        uslm_observed_at=OBSERVED_AT,
    )
    assert row["uslm_outcome"] == "captured_partial"
    assert row["uslm_reason"] == "statutes_citation_not_stated"
    assert row["statutes_at_large_cite"] is None
    assert row["uslm_sha256"] == USLM_SHA256 and row["approved_date"] == USLM.approved_date
    assert json.loads(row["uslm_citable_as_json"]) == ["Public Law 119-1"]


def test_the_outcome_and_the_uslm_record_travel_together():
    """The USLM record and a non-``not_requested`` outcome must travel together, and an unknown outcome is refused."""
    for outcome in USLM_OUTCOMES:
        assert outcome in (
            "captured",
            "captured_partial",
            "captured_refused",
            "request_failed",
            "unavailable",
            "not_requested",
        )
    with pytest.raises(TableContractError, match="exactly when"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm=USLM, uslm_outcome="not_requested")
    with pytest.raises(TableContractError, match="exactly when"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="captured")
    with pytest.raises(TableContractError, match="uslm_outcome must be one of"):
        shape_law(LAW_RECORD, LAW_RECORD["laws"][0], uslm_outcome="assumed")


def test_the_law_number_carries_its_own_congress():
    """``law_id`` composes congress-type-number; a law number from another Congress or without a dash is refused."""
    assert law_id(119, "public", 1) == "119-public-1"
    with pytest.raises(TableContractError, match="another Congress"):
        shape_law({"congress": 118, "type": "S", "number": "5"}, {"number": "119-1", "type": "Public Law"})
    with pytest.raises(TableContractError, match="not congress-number"):
        shape_law({"congress": 119, "type": "S", "number": "5"}, {"number": "119-", "type": "Public Law"})


def test_the_publishers_law_type_folds_onto_one_sealed_spelling():
    """Public and private law types fold to sealed spellings with package ids; unknown or missing types are refused."""
    assert STAT_CITE.fullmatch("139 Stat. 3")[0] == "139 Stat. 3"
    private = shape_law(LAW_RECORD, {"number": "119-1", "type": "Private Law"})
    assert (private["law_type"], private["publisher_law_type"]) == ("private", "Private Law")
    assert private["package_id"] == "PLAW-119pvtl1"
    with pytest.raises(TableContractError, match="unknown law type"):
        shape_law(LAW_RECORD, {"number": "119-1", "type": "Pocket Law"})
    with pytest.raises(TableContractError, match="needs a string type"):
        shape_law(LAW_RECORD, {"number": "119-1", "type": None})


def test_law_code_sections_rows_from_the_classification_table():
    """Classification rows shape law id, USC and Statutes at Large fields, keeping blank actions and page spans."""
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
    """Table III rows keep the page's en-dash key spelling and shape act, USC and record fields."""
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


def test_the_section_key_folds_case_and_dashes_and_leaves_a_plain_number_alone():
    """``usc_section_key`` lower-cases a printed capital and folds a Unicode dash; a plain number is unchanged."""
    table = parse_classification_table(
        (FIXTURES / "uscode/classification-tbl119pl_2nd-head.htm").read_bytes(), congress=119, session=2
    )
    plain = shape_law_code_section(table.records[0], table=table, observed_at=OBSERVED_AT)
    assert (plain["usc_section"], plain["usc_section_key"]) == ("5301", "5301")
    lettered = next(record for record in table.records if record.usc_section == "4980D")
    row = shape_law_code_section(lettered, table=table, observed_at=OBSERVED_AT)
    assert (row["usc_title"], row["usc_section"], row["usc_section_key"]) == ("26", "4980D", "4980d")

    page = parse_table3_page((FIXTURES / "uscode/table3-111_226-head.htm").read_bytes(), key="111-226")
    compound = next(record for record in page.records if record.usc_section == "1396r-8")
    assert shape_table3_record(compound, page=page, seq=2, observed_at=OBSERVED_AT)["usc_section_key"] == "1396r-8"
    # No retained row prints a Unicode dash in its section, but the release point spells every compound section
    # with an en dash, so the same row spelled that way must key where the printed hyphen does.
    dashed = replace(compound, usc_section="1396r\u20138")
    row = shape_table3_record(dashed, page=page, seq=2, observed_at=OBSERVED_AT)
    assert (row["usc_section"], row["usc_section_key"]) == ("1396r\u20138", "1396r-8")
    went_nowhere = replace(compound, usc_title=None, usc_section=None)
    assert shape_table3_record(went_nowhere, page=page, seq=2, observed_at=OBSERVED_AT)["usc_section_key"] is None


#: The nine dash code points RefSpec's ``normalize_section`` folds, spelled here
#: rather than read from ``DASH_SPELLINGS`` so dropping one from it fails.
NINE_DASHES = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212", "\x96", "\x97")


def test_every_dash_spelling_folds_to_one_ascii_hyphen():
    """Each of the nine dash spellings, and surrounding whitespace, fold away; ``None`` stays ``None``."""
    assert set(DASH_SPELLINGS) == set(NINE_DASHES)
    assert {usc_section_key(f" 1400Z{dash}1 ") for dash in NINE_DASHES} == {"1400z-1"}
    assert usc_section_key(None) is None


#: The column order each OLRC table was published in before the key existed,
#: read from the retained Parquet (``usc-section-key-2026-09-23/measure.out``).
PUBLISHED_LAW_CODE_SECTIONS = (
    "congress",
    "session",
    "seq",
    "law_id",
    "law_number",
    "law_type",
    "number",
    "usc_title",
    "usc_section",
    "action",
    "act_section",
    "statutes_at_large_volume",
    "statutes_at_large_page",
    "link_volume",
    "link_page",
    "table_order",
    "stated_laws",
    "prepared_date",
    "observed_at",
)
PUBLISHED_TABLE3_RECORDS = (
    "act_key",
    "stated_key",
    "seq",
    "congress",
    "act_date",
    "statutes_at_large_volume",
    "release_point",
    "act_section",
    "record_volume",
    "record_page",
    "usc_title",
    "usc_section",
    "status",
    "observed_at",
)


def test_the_section_key_is_appended_last_so_published_files_still_merge():
    """Both tables keep their published columns and identity, with ``usc_section_key`` appended after them.

    The host NULL-fills a column a prior Parquet file lacks, so appending is a backfill; moving a published column
    or the identity would not be.
    """
    assert LAW_CODE_SECTIONS.columns == (*PUBLISHED_LAW_CODE_SECTIONS, "usc_section_key")
    assert TABLE3_RECORDS.columns == (*PUBLISHED_TABLE3_RECORDS, "usc_section_key")
    assert LAW_CODE_SECTIONS.identity == ("congress", "session", "seq")
    assert TABLE3_RECORDS.identity == ("act_key", "seq")


def test_the_committee_fold_builds_one_json_row_per_detail_record():
    """A committee list row plus detail shapes one JSON row with parsed subcommittee and history columns."""
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
    """Supplied detail wins the subcommittee count even when empty, and a subcommittee without a code is refused."""
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


@pytest.mark.parametrize("number", [1, 2])
def test_native_private_laws_retain_their_actual_citations(number):
    body = (FIXTURES / f"uslm/plaw-119pvtl{number}.xml").read_bytes()
    selection = PublicLawSelection(119, "private", number)
    meta = validate_public_law_xml(body, selection=selection, final_url=public_law_xml_locator(selection))
    row = shape_law(
        LAW_RECORD,
        {"number": f"119-{number}", "type": "Private Law"},
        uslm=meta,
        uslm_outcome="captured",
        uslm_sha256=digest(body.decode()),
        uslm_observed_at=OBSERVED_AT,
    )
    assert row["uslm_outcome"] == "captured_partial"
    assert row["approved_date"] == "2026-03-26"
    assert row["uslm_title"] == meta.title
    assert json.loads(row["uslm_citable_as_json"]) == [f"Private Law 119–{number}"]
    assert row["statutes_at_large_cite"] is None


def test_table3_preserves_meaningful_native_rows_without_act_labels():
    body = (FIXTURES / "uscode/table3-119_37.htm").read_bytes()
    page = parse_table3_page(body, key="119-37")
    assert len(page.records) == 110  # Exact native data-row count in this retained publisher page.
    blank = [
        (r.statutes_at_large_page, r.usc_title, r.usc_section, r.status) for r in page.records if r.act_section is None
    ]
    assert blank == [
        ("511", "7", "2254", None),
        ("534", "42", "1769g", None),
        ("534", "42", "1758", None),
        ("563", "2", "60a nt", "Elim."),
    ]
    # A completely empty decorative data row carries no source observation.
    empty = b'<tr class="table3row_even"><td class="actsection"></td></tr>'
    decorated = body.replace(b"<!-- field-end:documentdata -->", empty + b"<!-- field-end:documentdata -->")
    assert decorated != body
    assert parse_table3_page(decorated, key="119-37").records == page.records


def test_table3_drops_a_row_whose_only_content_is_a_non_statute_link():
    body = (FIXTURES / "uscode/table3-119_37.htm").read_bytes()
    page = parse_table3_page(body, key="119-37")
    linked = b'<tr class="table3row_odd"><td class="actsection"><a href="/view.xhtml?req=nothing">&nbsp;</a></td></tr>'
    decorated = body.replace(b"<!-- field-end:documentdata -->", linked + b"<!-- field-end:documentdata -->")
    assert decorated != body
    assert parse_table3_page(decorated, key="119-37").records == page.records


def test_identity_and_shape_refusals_are_distinct_errors():
    """A USLM file for another law is an identity refusal; an HTML page is only a shape refusal."""
    body = (FIXTURES / "uslm/plaw-119pvtl1.xml").read_bytes()
    other = PublicLawSelection(119, "private", 2)
    with pytest.raises(UslmIdentityError, match="native identity"):
        validate_public_law_xml(body, selection=other, final_url=public_law_xml_locator(other))
    with pytest.raises(UslmSourceError) as refused:
        validate_public_law_xml(
            b"<html><body>not the requested native XML</body></html>",
            selection=other,
            final_url=public_law_xml_locator(other),
        )
    assert not isinstance(refused.value, UslmIdentityError)
