"""The CBO cost-estimate index: the element the reader now reads, the fold, and the two parse rules.

Every fixture is a bounded excerpt of a real BILLSTATUS record from the two
bulk zips the routes measurement retained; see
``tests/fixtures/cbo_cost_estimates/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_family import BillFamilyCapture, EngineStamp, build_bill_family
from spicy_docs.schemas import CBO_COST_ESTIMATES
from spicy_docs.schemas.cost_estimate_tables import (
    BILLSTATUS_BULK,
    PUBLICATION_ID_RULE,
    fold_cbo_cost_estimates,
    publication_id,
    report_citation_parts,
    shape_cbo_cost_estimate,
)
from spicy_docs.schemas.tables import TableContractError, read_json_column
from spicy_docs.sources.congress.bill_status import BillIdentity, CboCostEstimate, parse_bill_status

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_cost_estimates"
ENGINE = EngineStamp(name="deltatrack", version="0.1.0", revision="0" * 40)


def status(stem: str, identity: BillIdentity):
    return parse_bill_status((FIXTURES / f"{stem}.excerpt.xml").read_bytes(), identity=identity)


HR801 = BillIdentity(118, "hr", 801)
HR3091 = BillIdentity(118, "hr", 3091)
HR589 = BillIdentity(118, "hr", 589)
S3139 = BillIdentity(118, "s", 3139)


# --- the reader ---------------------------------------------------------------------


def test_reader_states_the_estimate_and_the_report_citation() -> None:
    parsed = status("BILLSTATUS-118hr801", HR801)
    assert len(parsed.cbo_cost_estimates) == 1
    estimate = parsed.cbo_cost_estimates[0]
    assert estimate.pub_date == "2023-05-05T16:34:00Z"
    assert estimate.url == "https://www.cbo.gov/publication/59139"
    assert estimate.title == "H.R. 801, Securing the Border for Public Health Act of 2023"
    assert estimate.description == (
        "As ordered reported by the House Committee on Energy and Commerce on March 24, 2023"
    )
    assert parsed.report_citations == ("H. Rept. 118-53",)


def test_reader_defaults_are_empty_for_a_bill_the_publisher_never_scored() -> None:
    """The element is never emitted empty, so absent is the ordinary case."""
    body = (Path(__file__).parent / "fixtures" / "govinfo_bills" / "status-119hr6028.xml").read_bytes()
    parsed = parse_bill_status(body, identity=BillIdentity(119, "hr", 6028))
    assert parsed.cbo_cost_estimates == ()
    assert parsed.report_citations == ()


def test_reader_falls_back_to_the_guide_spelling() -> None:
    """The user guide documents ``rptPubDate``/``rptTitle``/``rptUrl``; the live files disagree.

    No measured record uses the guide's names, so this pins the fallback
    directly rather than through a fixture that cannot exist.
    """
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<billStatus><version>3.0.0</version><bill>
  <number>801</number><type>HR</type><congress>118</congress><title>Guide spelling</title>
  <cboCostEstimates><item>
    <rptPubDate>2023-05-05T16:34:00Z</rptPubDate>
    <rptTitle>H.R. 801</rptTitle>
    <rptUrl>https://www.cbo.gov/publication/59139</rptUrl>
  </item></cboCostEstimates>
</bill></billStatus>"""
    estimate = parse_bill_status(body, identity=HR801).cbo_cost_estimates[0]
    assert estimate.pub_date == "2023-05-05T16:34:00Z"
    assert estimate.url == "https://www.cbo.gov/publication/59139"
    assert estimate.title == "H.R. 801"
    assert estimate.description is None


# --- the publication-id rule --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.cbo.gov/publication/59139/",
        "https://www.cbo.gov/publication/59139?utm=1",
        "http://www.cbo.gov/publication/59139",
        "https://cbo.gov/publication/59139",
        "https://www.cbo.gov/publication/59139/html",
        "https://www.cbo.gov/system/files/2020-07/HR1957directspending.pdf",
        "https://www.cbo.gov/publication/0",
        "",
        None,
        17,
    ],
)
def test_publication_id_refuses_every_url_outside_the_measured_shape(url: object) -> None:
    assert publication_id(url) is None


def test_publication_id_reads_the_measured_shape() -> None:
    assert publication_id("https://www.cbo.gov/publication/59139") == "59139"
    assert publication_id("  https://www.cbo.gov/publication/59139  ") == "59139"


# --- the report-citation rule -------------------------------------------------------


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        ("H. Rept. 118-53", {"congress": "118", "report_type": "hrpt", "number": "53", "part": None}),
        ("S. Rept. 118-201", {"congress": "118", "report_type": "srpt", "number": "201", "part": None}),
        ("H. Rept. 118-4, Part 1", {"congress": "118", "report_type": "hrpt", "number": "4", "part": "1"}),
    ],
)
def test_report_citation_parts_read_the_three_measured_shapes(citation: str, expected: dict) -> None:
    parts = report_citation_parts(citation)
    assert parts == {"citation": citation, **expected}


@pytest.mark.parametrize(
    "citation",
    ["H. Doc. 118-53", "S. Exec. Rept. 118-1", "H. Rept. 53", "Report 118-53", "", None],
)
def test_report_citation_parts_keep_an_unparsed_citation_whole(citation: object) -> None:
    """An unparsed citation is still the publisher saying a report exists."""
    parts = report_citation_parts(citation)
    assert parts["citation"] == (citation if isinstance(citation, str) else None)
    assert parts["report_type"] is None
    assert parts["number"] is None


# --- the fold -----------------------------------------------------------------------


def test_one_publication_stated_twice_is_one_row() -> None:
    parsed = status("BILLSTATUS-118hr3091", HR3091)
    assert len(parsed.cbo_cost_estimates) == 2
    folded, unkeyable = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    assert unkeyable == ()
    assert len(folded) == 1
    assert folded[0].publication_id == "59168"
    assert folded[0].estimate_index == 0
    assert folded[0].stated_count == 2
    assert folded[0].restatements == ()


def test_a_restated_title_is_kept_rather_than_folded_away() -> None:
    parsed = status("BILLSTATUS-118hr589", HR589)
    (entry,), unkeyable = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    assert unkeyable == ()
    assert entry.stated_count == 2
    assert entry.restatements == (
        {"estimate_index": 1, "title": "H.R. 589, Mahsa Amini Human Rights and Security Accountability Act"},
    )
    assert entry.estimate.title == "H.R. 589, Mahsa Amini Human rights and Security Accountability Act"


def test_a_url_outside_the_measured_shape_is_returned_for_refusal_not_dropped() -> None:
    estimates = (
        CboCostEstimate("2023-05-05T16:34:00Z", "kept", "https://www.cbo.gov/publication/59139", None),
        CboCostEstimate(None, "refused", "https://www.cbo.gov/publication/59139/html", None),
    )
    folded, unkeyable = fold_cbo_cost_estimates(estimates)
    assert [entry.publication_id for entry in folded] == ["59139"]
    assert unkeyable == ((1, "https://www.cbo.gov/publication/59139/html"),)


def test_fold_keeps_the_publisher_order_of_first_statement() -> None:
    estimates = (
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/2", None),
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/1", None),
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/2", None),
    )
    folded, _ = fold_cbo_cost_estimates(estimates)
    assert [(entry.publication_id, entry.estimate_index) for entry in folded] == [("2", 0), ("1", 1)]


# --- the row ------------------------------------------------------------------------


def test_row_carries_the_estimate_and_the_text_route_reachability() -> None:
    parsed = status("BILLSTATUS-118hr801", HR801)
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    row = CBO_COST_ESTIMATES.checked(shape_cbo_cost_estimate(HR801, entry, report_citations=parsed.report_citations))
    assert CBO_COST_ESTIMATES.key(row) == ("118-hr-801", "59139")
    assert row["source"] == BILLSTATUS_BULK
    assert row["publication_id_rule"] == PUBLICATION_ID_RULE
    assert row["stated_count"] == "1"
    assert row["restatements_json"] == "[]"
    assert row["report_citation_count"] == "1"
    assert read_json_column(row["report_citations_json"]) == [
        {"citation": "H. Rept. 118-53", "congress": "118", "report_type": "hrpt", "number": "53", "part": None}
    ]


def test_a_bill_with_no_report_states_the_text_route_is_closed() -> None:
    parsed = status("BILLSTATUS-118hr801", HR801)
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    row = shape_cbo_cost_estimate(HR801, entry, report_citations=())
    assert row["report_citation_count"] == "0"
    assert row["report_citations_json"] == "[]"


def test_an_unsealed_source_is_refused() -> None:
    parsed = status("BILLSTATUS-118s3139", S3139)
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    with pytest.raises(TableContractError, match="source must be one of"):
        shape_cbo_cost_estimate(S3139, entry, source="scraped")


# --- the family pass ----------------------------------------------------------------


def test_the_family_pass_produces_the_estimate_rows_from_the_same_document() -> None:
    parsed = status("BILLSTATUS-118s3139", S3139)
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert len(family.cbo_cost_estimates) == 1
    row = family.cbo_cost_estimates[0]
    assert CBO_COST_ESTIMATES.key(row) == ("118-s-3139", "60334")
    assert json.loads(row["report_citations_json"])[0]["citation"] == "S. Rept. 118-289"


def test_the_family_pass_refuses_an_unkeyable_url_by_name() -> None:
    parsed = status("BILLSTATUS-118hr801", HR801)
    broken = parsed.__class__(
        **{field: getattr(parsed, field) for field in parsed.__dataclass_fields__ if field != "cbo_cost_estimates"},
        cbo_cost_estimates=(CboCostEstimate(None, None, "https://www.cbo.gov/publication/59139/html", None),),
    )
    family = build_bill_family(BillFamilyCapture(status=broken, versions=()), engine=ENGINE, diff=False)
    assert family.cbo_cost_estimates == ()
    refusal = next(r for r in family.refusals if r.table == "cbo_cost_estimates")
    assert refusal.identity == ("118-hr-801", "0")
    assert "publication-page shape" in refusal.reason
