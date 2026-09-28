"""The CBO cost-estimate index: the element the reader now reads, the fold, and the two parse rules.

Every fixture is a bounded excerpt of a real BILLSTATUS record from a retained
bulk zip; see ``tests/fixtures/cbo_cost_estimates/README.md``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.interpretation.bill_family import (
    BillFamilyCapture,
    EngineStamp,
    build_bill_family,
    build_cbo_feed_cost_estimates,
)
from spicy_docs.schemas import CBO_COST_ESTIMATES, CONGRESS_BILLS
from spicy_docs.schemas.cost_estimate_tables import (
    BILLSTATUS_BULK,
    CBO_FEED,
    ESTIMATE_SOURCES,
    FOUND_BY,
    PUBLICATION_ID_RULE,
    SOURCE_PRECEDENCE,
    TITLE_BILL_ID_RULE,
    fold_cbo_cost_estimates,
    merge_cbo_cost_estimates,
    publication_id,
    report_citation_parts,
    shape_cbo_cost_estimate,
)
from spicy_docs.schemas.tables import TableContractError, read_json_column
from spicy_docs.sources.cbo import CboEstimateItem, CboSourceError, feed_item_pub_date, parse_cbo_cost_estimates_feed
from spicy_docs.sources.congress.bill_status import BillIdentity, CboCostEstimate, parse_bill_status

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_cost_estimates"
ENGINE = EngineStamp(name="deltatrack", version="0.1.0", revision="0" * 40)


def status(stem: str, identity: BillIdentity):
    """Parse a BILLSTATUS fixture as a bill status."""
    return parse_bill_status((FIXTURES / f"{stem}.excerpt.xml").read_bytes(), identity=identity)


HR801 = BillIdentity(118, "hr", 801)
HR3091 = BillIdentity(118, "hr", 3091)
HR589 = BillIdentity(118, "hr", 589)
S3139 = BillIdentity(118, "s", 3139)


# --- the reader ---------------------------------------------------------------------


def test_reader_states_the_estimate_and_the_report_citation() -> None:
    """The reader states one estimate with its date, URL, title and description, plus the report citation."""
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


def test_reader_records_an_absent_element_without_claiming_an_unscored_bill() -> None:
    """An absent element is recorded as requested-empty:absent, not as an unscored bill."""
    body = (Path(__file__).parent / "fixtures" / "govinfo_bills" / "status-119hr6028.xml").read_bytes()
    parsed = parse_bill_status(body, identity=BillIdentity(119, "hr", 6028))
    assert parsed.cbo_cost_estimates == ()
    assert parsed.report_citations == ()
    assert parsed.cbo_cost_estimates_outcome == "requested-empty:absent"


@pytest.mark.parametrize(
    ("block", "outcome"),
    [
        ("", "absent"),
        ("<cboCostEstimates/>", "present-and-empty"),
        ("<cboCostEstimates> \n </cboCostEstimates>", "present-and-empty"),
        ("<cboCostEstimates>challenge</cboCostEstimates>", "unexpected-shape:container-text"),
        ("<cboCostEstimates><estimate/></cboCostEstimates>", "unexpected-shape:non-item-child"),
        ("<cboCostEstimates><item/></cboCostEstimates>", "unexpected-shape:empty-item"),
        ("<cboCostEstimates/><cboCostEstimates/>", "unexpected-shape:multiple-containers"),
        ("<cboCostEstimates><item><url/><url/></item></cboCostEstimates>", "unexpected-shape:duplicate-item-field"),
        ("<cboCostEstimates><item><mystery/></item></cboCostEstimates>", "unexpected-shape:unknown-item-field"),
        (
            "<cboCostEstimates><item><url><value/></url></item></cboCostEstimates>",
            "unexpected-shape:non-scalar-item-field",
        ),
    ],
)
def test_empty_observations_publish_on_the_bill_without_estimate_rows(block: str, outcome: str) -> None:
    """Empty observations publish their outcome on the bill with no estimate rows."""
    xml = (
        "<billStatus><version>3.0.0</version><bill><congress>118</congress><type>HR</type>"
        f"<number>801</number><title>Example</title>{block}</bill></billStatus>"
    ).encode()
    parsed = parse_bill_status(xml, identity=HR801)
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert parsed.cbo_cost_estimates == ()
    assert parsed.cbo_cost_estimates_outcome == f"requested-empty:{outcome}"
    assert family.bills[0]["cbo_cost_estimates_outcome"] == f"requested-empty:{outcome}"
    assert family.cbo_cost_estimates == ()


def test_unread_and_populated_are_distinct_and_the_column_is_appended() -> None:
    """Unread and populated outcomes are distinct, and the outcome column is appended after
    related_bill_count in congress_bills; subsequent additions stay after it.
    """
    parsed = status("BILLSTATUS-118hr801", HR801)
    assert parsed.cbo_cost_estimates_outcome == "populated"
    for value in (None, "populated"):
        family = build_bill_family(
            BillFamilyCapture(status=replace(parsed, cbo_cost_estimates_outcome=value), versions=()),
            engine=ENGINE,
            diff=False,
        )
        assert family.bills[0]["cbo_cost_estimates_outcome"] == value
    assert CONGRESS_BILLS.columns[47:50] == ("related_bill_count", "cbo_cost_estimates_outcome", "url_source")
    assert CONGRESS_BILLS.columns[50:] == ("cosponsors_outcome",)


def test_url_source_names_billstatus_only_when_the_document_states_a_url() -> None:
    """url_source is billstatus exactly when the document states a url, and NULL alongside a NULL url."""
    parsed = status("BILLSTATUS-118hr801", HR801)
    stated = "https://www.congress.gov/bill/118th-congress/house-bill/801"
    for url, source in ((stated, "billstatus"), (None, None)):
        family = build_bill_family(
            BillFamilyCapture(status=replace(parsed, legislation_url=url), versions=()), engine=ENGINE, diff=False
        )
        assert (family.bills[0]["url"], family.bills[0]["url_source"]) == (url, source)


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
        "http://www.cbo.gov/publication/59139/",
        "ftp://www.cbo.gov/publication/59139",
        "https://cbo.gov/publication/59139",
        "http://cbo.gov/publication/59139",
        "https://www.cbo.gov/publication/59139/html",
        "https://www.cbo.gov/system/files/2020-07/HR1957directspending.pdf",
        "https://www.cbo.gov/publication/0",
        "",
        None,
        17,
    ],
)
def test_publication_id_refuses_every_url_outside_the_measured_shape(url: object) -> None:
    """Publication ids are refused for every URL outside the measured shape."""
    assert publication_id(url) is None


def test_publication_id_reads_the_measured_shape() -> None:
    """Publication ids are read from the measured URL shapes, trimming surrounding whitespace.

    The 108th-111th state every estimate on ``http`` as well as ``https``; nothing else about the shape widened.
    """
    assert publication_id("https://www.cbo.gov/publication/59139") == "59139"
    assert publication_id("  https://www.cbo.gov/publication/59139  ") == "59139"
    assert publication_id("http://www.cbo.gov/publication/14390") == "14390"


# --- the report-citation rule -------------------------------------------------------


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        ("H. Rept. 118-53", {"congress": "118", "report_type": "hrpt", "number": "53", "part": None}),
        ("S. Rept. 118-201", {"congress": "118", "report_type": "srpt", "number": "201", "part": None}),
        # The publisher writes the part form with no space after the comma;
        # all thirteen measured citations are spelled that way.
        ("H. Rept. 118-167,Part 2", {"congress": "118", "report_type": "hrpt", "number": "167", "part": "2"}),
        ("H. Rept. 118-4, Part 1", {"congress": "118", "report_type": "hrpt", "number": "4", "part": "1"}),
    ],
)
def test_report_citation_parts_read_the_three_measured_shapes(citation: str, expected: dict) -> None:
    """Report citation parts are read from the three measured citation shapes."""
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
    """A publication stated twice folds to one row with stated_count 2 and no restatements."""
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
    """A restated title is kept as a restatement rather than folded away."""
    parsed = status("BILLSTATUS-118hr589", HR589)
    (entry,), unkeyable = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    assert unkeyable == ()
    assert entry.stated_count == 2
    assert entry.restatements == (
        {"estimate_index": 1, "title": "H.R. 589, Mahsa Amini Human Rights and Security Accountability Act"},
    )
    assert entry.estimate.title == "H.R. 589, Mahsa Amini Human rights and Security Accountability Act"


def test_an_estimate_stated_on_http_and_https_is_one_row_on_https_that_keeps_both() -> None:
    """The 108th-111th shape: the https statement is the row, and its http twin, listed first, a restatement.

    Each run of the 108th-111th bill family refused the 4,762 http statements before 0.50.1, so the https twin was the
    row the fork published. It still is, with the same fields and index; stated_count and restatements_json now record
    the twin.
    """
    parsed = status("BILLSTATUS-108hconres96", BillIdentity(108, "hconres", 96))
    (entry,), unkeyable = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    assert unkeyable == ()
    assert (entry.publication_id, entry.estimate_index, entry.stated_count) == ("14390", 1, 2)
    assert entry.estimate.url == "https://www.cbo.gov/publication/14390"
    assert entry.estimate.description.startswith("Cost estimate for the bill")
    assert entry.restatements == (
        {
            "estimate_index": 0,
            "url": "http://www.cbo.gov/publication/14390",
            "description": (
                "<p>Cost estimate for the bill as ordered reported by the House Committee on Transportation and "
                "Infrastructure on April 9, 2003</p>"
            ),
        },
    )
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    (row,) = family.cbo_cost_estimates
    assert CBO_COST_ESTIMATES.key(row) == ("108-hconres-96", "14390")
    assert (row["url"], row["estimate_index"], row["stated_count"]) == (entry.estimate.url, "1", "2")
    assert not [r for r in family.refusals if r.table == "cbo_cost_estimates"]


def test_the_row_is_the_first_https_statement_else_the_first() -> None:
    """Synthetic orders: http first, https first, http only, and two https statements with an http one between."""

    def item(url: str, title: str) -> CboCostEstimate:
        return CboCostEstimate(None, title, url, None)

    http, https = "http://www.cbo.gov/publication/", "https://www.cbo.gov/publication/"
    estimates = (
        item(http + "1", "a0"),
        item(https + "1", "a1"),
        item(https + "2", "b2"),
        item(http + "2", "b3"),
        item(http + "3", "c4"),
        item(http + "4", "d5"),
        item(https + "4", "d6"),
        item(http + "4", "d7"),
        item(https + "4", "d8"),
    )
    folded, unkeyable = fold_cbo_cost_estimates(estimates)
    assert unkeyable == ()
    assert [(f.publication_id, f.estimate_index, f.estimate.title, f.stated_count) for f in folded] == [
        ("1", 1, "a1", 2),
        ("2", 2, "b2", 2),
        ("3", 4, "c4", 1),
        ("4", 6, "d6", 4),
    ]
    assert [r["estimate_index"] for r in folded[3].restatements] == [5, 7, 8]


def test_a_url_outside_the_measured_shape_is_returned_for_refusal_not_dropped() -> None:
    """A URL outside the measured shape is returned as unkeyable for refusal, not dropped."""
    estimates = (
        CboCostEstimate("2023-05-05T16:34:00Z", "kept", "https://www.cbo.gov/publication/59139", None),
        CboCostEstimate(None, "refused", "https://www.cbo.gov/publication/59139/html", None),
    )
    folded, unkeyable = fold_cbo_cost_estimates(estimates)
    assert [entry.publication_id for entry in folded] == ["59139"]
    assert unkeyable == ((1, "https://www.cbo.gov/publication/59139/html"),)


def test_fold_keeps_the_publisher_order_of_first_statement() -> None:
    """Folding keeps the publisher order of first statement."""
    estimates = (
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/2", None),
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/1", None),
        CboCostEstimate(None, None, "https://www.cbo.gov/publication/2", None),
    )
    folded, _ = fold_cbo_cost_estimates(estimates)
    assert [(entry.publication_id, entry.estimate_index) for entry in folded] == [("2", 0), ("1", 1)]


# --- the row ------------------------------------------------------------------------


def test_row_carries_the_estimate_and_the_text_route_reachability() -> None:
    """The row carries the estimate plus its publication rule, stated count, restatements and report citation
    reachability.
    """
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
    """A bill with no report states a zero citation count and an empty citations column."""
    parsed = status("BILLSTATUS-118hr801", HR801)
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    row = shape_cbo_cost_estimate(HR801, entry, report_citations=())
    assert row["report_citation_count"] == "0"
    assert row["report_citations_json"] == "[]"


def test_an_unsealed_source_is_refused() -> None:
    """A source outside the sealed set is refused."""
    parsed = status("BILLSTATUS-118s3139", S3139)
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    with pytest.raises(TableContractError, match="source must be one of"):
        shape_cbo_cost_estimate(S3139, entry, source="scraped")


def test_the_contract_names_both_routes_and_what_a_112th_113th_absence_means() -> None:
    """The sealed vocabularies only grow, in their published order, and the text says which source each row came
    from, that the feed is read for every Congress and merged, that BILLSTATUS names no estimate in the 112th-113th,
    and that a missing row there is not an unscored bill."""
    assert ESTIMATE_SOURCES == ("billstatus_bulk", "congress_api", "cbo_feed")
    assert (BILLSTATUS_BULK, CBO_FEED) == ("billstatus_bulk", "cbo_feed")
    assert FOUND_BY == ("billstatus", "bill_number", "title", "title_law")
    assert "CBO's per-Congress feed, read for every Congress and merged" in CBO_COST_ESTIMATES.grain
    source = CBO_COST_ESTIMATES.descriptions["source"]
    assert "The feed is read for every Congress" in source and "an estimate no BILLSTATUS record lists" in source
    assert "BILLSTATUS states no estimate for the 112th-113th" in source
    assert "never established as unscored" in source and "`congress_api` is reserved" in source
    stated_count = CBO_COST_ESTIMATES.descriptions["stated_count"]
    assert "from the 112th on" not in stated_count and "the 112th-113th's state none" in stated_count
    assert "title_bill_id names the bill the estimate scores" in CBO_COST_ESTIMATES.descriptions["bill_id"]
    assert CBO_COST_ESTIMATES.columns[-3:] == ("title_bill_id", "found_by", "title_bill_id_rule")
    assert "Congress.gov" not in " ".join((CBO_COST_ESTIMATES.grain, *CBO_COST_ESTIMATES.descriptions.values()))


# --- the feed route -----------------------------------------------------------------

#: Ten real items of the 112th feed, re-keyed; ``tests/fixtures/cbo/README.md``.
FEED_112 = parse_cbo_cost_estimates_feed(
    (Path(__file__).parent / "fixtures" / "cbo" / "cbo-112congress-cost-estimates.excerpt.xml").read_bytes()
)
S3240 = BillIdentity(112, "s", 3240)


def test_the_feed_route_shapes_rows_through_the_fold_with_feed_dates_and_billstatus_citations() -> None:
    """Every bill the feed names by Bill_Number or by the title of a blank item gets one row per publication, oldest
    first; report citations come from the BILLSTATUS record the host supplies, and NULL where it supplies none."""
    tables = build_cbo_feed_cost_estimates(FEED_112, 112, report_citations={S3240: ("S. Rept. 112-203",)})
    assert tables.refusals == ()
    rows = {CBO_COST_ESTIMATES.key(row): CBO_COST_ESTIMATES.checked(row) for row in tables.cbo_cost_estimates}
    assert sorted(rows) == [
        ("112-hr-1707", "43626"),
        ("112-hr-3082", "22065"),
        ("112-hr-4402", "43585"),
        ("112-s-1065", "42930"),
        ("112-s-1065", "43482"),
        ("112-s-3240", "43273"),
        ("112-s-3240", "43280"),
        ("112-s-3240", "43405"),
    ]
    first = rows[("112-s-3240", "43273")]
    assert (first["source"], first["pub_date"], first["estimate_index"], first["stated_count"]) == (
        CBO_FEED,
        "2012-05-25T14:01:12Z",
        "0",
        "1",
    )
    assert [rows[("112-s-3240", p)]["estimate_index"] for p in ("43273", "43280", "43405")] == ["0", "1", "2"]
    # S. 1065: 43482 is dated 2012-01-01 and 42930 2012-01-18, so oldest first is not publication-id order.
    assert [rows[("112-s-1065", p)]["estimate_index"] for p in ("43482", "42930")] == ["0", "1"]
    assert {row["title_bill_id_rule"] for row in rows.values()} == {TITLE_BILL_ID_RULE} == {"cbo_title_citation/1"}
    assert (first["report_citation_count"], json.loads(first["report_citations_json"])[0]["number"]) == ("1", "203")
    assert first["description"] == "As introduced in the United States Senate on May 24, 2012"
    by_title = rows[("112-hr-4402", "43585")]
    assert (by_title["report_citation_count"], by_title["report_citations_json"]) == (None, None)


def test_title_bill_id_names_the_bill_a_title_leads_with_and_exposes_a_wrong_number() -> None:
    """CBO filed its estimate of S. 1707 under Bill_Number H.R. 1707: bill_id keeps the published number and
    title_bill_id the bill the title names. A title citing the bill after its start, or a public law, names none."""
    rows = {row["publication_id"]: row for row in build_cbo_feed_cost_estimates(FEED_112, 112).cbo_cost_estimates}
    assert (rows["43626"]["bill_id"], rows["43626"]["title_bill_id"]) == ("112-hr-1707", "112-s-1707")
    assert rows["43273"]["title_bill_id"] == rows["43273"]["bill_id"] == "112-s-3240"
    assert rows["43280"]["title_bill_id"] is None  # "... Under Title I of S. 3240"
    assert rows["43585"]["title_bill_id"] == "112-hr-4402"  # found by its title, so equal by construction
    assert rows["22065"]["title_bill_id"] is None  # "P.L. 111-322, ...": a law, and no host map to its bill


def test_a_blank_item_titled_by_a_public_law_has_a_row_only_through_the_hosts_laws() -> None:
    """The 110th's P.L. 110-50 and the 112th's P.L. 112-8 have an empty Bill_Number and a title that leads with the
    law. With the host's laws map each is a row of the bill that enacted it (retained BILLSTATUS: 110 S. 966, 112
    H.R. 1363), found_by title_law; without it each is counted as public_law and has no row."""
    feed_110 = parse_cbo_cost_estimates_feed(
        (FIXTURES.parent / "cbo" / "cbo-110congress-cost-estimates.excerpt.xml").read_bytes()
    )
    law_bills = {"110-public-50": "110-s-966", "112-public-8": "112-hr-1363"}
    for feed, congress, key in ((feed_110, 110, ("110-s-966", "19115")), (FEED_112, 112, ("112-hr-1363", "22098"))):
        bare = build_cbo_feed_cost_estimates(feed, congress)
        assert key[1] not in {r["publication_id"] for r in bare.cbo_cost_estimates} and bare.refusals == ()
        rows = {
            CBO_COST_ESTIMATES.key(r): r
            for r in build_cbo_feed_cost_estimates(feed, congress, law_bills=law_bills).cbo_cost_estimates
        }
        row = CBO_COST_ESTIMATES.checked(rows[key])
        assert (row["found_by"], row["title_bill_id"], row["source"]) == ("title_law", key[0], "cbo_feed")
    by_way = {
        r["publication_id"]: r["found_by"] for r in build_cbo_feed_cost_estimates(FEED_112, 112).cbo_cost_estimates
    }
    assert (by_way["43626"], by_way["43585"]) == ("bill_number", "title")


def test_found_by_is_billstatus_on_the_bills_own_record_and_a_feed_way_on_a_feed_row() -> None:
    parsed = status("BILLSTATUS-118hr801", HR801)
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert family.cbo_cost_estimates[0]["found_by"] == "billstatus"
    (entry,), _ = fold_cbo_cost_estimates(parsed.cbo_cost_estimates)
    for source, way in (("cbo_feed", "billstatus"), ("billstatus_bulk", "title"), ("cbo_feed", "guessed")):
        with pytest.raises(TableContractError, match="found_by"):
            shape_cbo_cost_estimate(HR801, entry, source=source, found_by=way)


def test_a_title_leading_with_a_public_law_names_the_bill_the_host_says_enacted_it() -> None:
    """CBO filed its estimate of P.L. 111-322 under the 112th's H.R. 3082, the enacting bill's number in the 111th.
    With the host's laws map (retained 111th BILLSTATUS H.R. 3082 states that law) title_bill_id names the 111th
    bill, so the wrong Congress shows; a map without the law leaves it NULL, and a bad map value is a refusal."""
    law_bills = {"111-public-322": "111-hr-3082"}
    rows = {
        r["publication_id"]: r
        for r in build_cbo_feed_cost_estimates(FEED_112, 112, law_bills=law_bills).cbo_cost_estimates
    }
    assert (rows["22065"]["bill_id"], rows["22065"]["title_bill_id"]) == ("112-hr-3082", "111-hr-3082")
    assert rows["43626"]["title_bill_id"] == "112-s-1707"  # a bill-led title ignores the map
    empty = build_cbo_feed_cost_estimates(FEED_112, 112, law_bills={}).cbo_cost_estimates
    assert next(r for r in empty if r["publication_id"] == "22065")["title_bill_id"] is None
    tables = build_cbo_feed_cost_estimates(FEED_112, 112, law_bills={"111-public-322": ""})
    assert "22065" not in {r["publication_id"] for r in tables.cbo_cost_estimates}
    (refusal,) = tables.refusals
    assert refusal.identity == ("112-hr-3082", "22065") and "law_bills" in refusal.reason
    refused = build_cbo_feed_cost_estimates(FEED_112, 112, law_bills={"112-public-8": "not a bill"}).refusals
    assert [(r.identity, "not-a-bill-id" in r.reason) for r in refused] == [(("112", "22098"), True)]
    # A law is enacted from a bill of its own Congress: the feed's own wrong number, offered as the law's bill, refuses.
    other = build_cbo_feed_cost_estimates(FEED_112, 112, law_bills={"111-public-322": "112-hr-3082"})
    assert [(r.identity, "other-congress" in r.reason) for r in other.refusals] == [(("112-hr-3082", "22065"), True)]
    assert "22065" not in {r["publication_id"] for r in other.cbo_cost_estimates}


def test_title_bill_id_is_filled_on_billstatus_rows_too() -> None:
    """The BILLSTATUS route reads the same title rule; a title naming another bill shows as a differing id."""
    parsed = status("BILLSTATUS-118hr801", HR801)
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert family.cbo_cost_estimates[0]["title_bill_id"] == "118-hr-801"
    (estimate,) = parsed.cbo_cost_estimates
    renamed = replace(parsed, cbo_cost_estimates=(replace(estimate, title="H.R. 810, a misnumbered estimate"),))
    family = build_bill_family(BillFamilyCapture(status=renamed, versions=()), engine=ENGINE, diff=False)
    assert (family.cbo_cost_estimates[0]["bill_id"], family.cbo_cost_estimates[0]["title_bill_id"]) == (
        "118-hr-801",
        "118-hr-810",
    )
    by_law = replace(parsed, cbo_cost_estimates=(replace(estimate, title="P.L. 118-5, the Act as enacted"),))
    capture = BillFamilyCapture(status=by_law, versions=())
    assert build_bill_family(capture, engine=ENGINE, diff=False).cbo_cost_estimates[0]["title_bill_id"] is None
    mapped = build_bill_family(capture, engine=ENGINE, diff=False, law_bills={"118-public-5": "118-hr-801"})
    assert mapped.cbo_cost_estimates[0]["title_bill_id"] == "118-hr-801"


def test_an_unmappable_item_or_an_undated_one_is_a_named_refusal() -> None:
    """A Bill_Number no rule maps and a Date that names no instant each file a refusal, never a row or silence."""
    body = (
        b'<?xml version="1.0"?>\n<response><item key="0"><Title>T</Title><Date>Tue, 18 Sep 2012 23:59:00 -0400</Date>'
        b"<Link>https://www.cbo.gov/publication/1</Link><Description></Description><Bill_Number>S.A. 948</Bill_Number>"
        b'</item><item key="1"><Title>T</Title><Date>18 September 2012</Date><Link>https://www.cbo.gov/publication/2'
        b"</Link><Description></Description><Bill_Number>S. 2</Bill_Number></item></response>"
    )
    tables = build_cbo_feed_cost_estimates(parse_cbo_cost_estimates_feed(body), 112)
    assert tables.cbo_cost_estimates == ()
    assert [(r.identity, r.reason.split(":")[0]) for r in tables.refusals] == [
        (("112", "1"), "cbo_feed_bill"),
        (("112", "2"), "cbo_feed_date"),
    ]
    assert "bill_number 'S.A. N'" in tables.refusals[0].reason


@pytest.mark.parametrize(
    ("stated", "instant"),
    [
        ("Fri, 25 May 2012 10:01:12 -0400", "2012-05-25T14:01:12Z"),
        ("Mon, 07 Mar 2011 01:00:00 -0500", "2011-03-07T06:00:00Z"),
        ("Wed, 31 Dec 2014 23:30:00 -0500", "2015-01-01T04:30:00Z"),
    ],
)
def test_a_feed_date_is_its_utc_instant_in_the_billstatus_spelling(stated: str, instant: str) -> None:
    item = CboEstimateItem(0, "1", "T", stated, "https://www.cbo.gov/publication/1", None, None)
    assert feed_item_pub_date(item) == instant


@pytest.mark.parametrize("stated", ["Fri, 25 May 2012 10:01:12", "18 September 2012", "yesterday"])
def test_a_feed_date_without_an_instant_refuses(stated: str) -> None:
    with pytest.raises(CboSourceError):
        feed_item_pub_date(CboEstimateItem(0, "1", "T", stated, "https://www.cbo.gov/publication/1", None, None))


def test_a_merge_keeps_billstatus_over_the_feed_then_the_larger_pub_date() -> None:
    """Two routes stating one bill and publication keep the bill's own BILLSTATUS record, whatever the dates say;
    within one route the larger pub_date wins; first-seen order holds and an unknown source refuses."""
    assert SOURCE_PRECEDENCE == ("billstatus_bulk", "congress_api", "cbo_feed")

    def row(source: str, pub_date: str | None, publication: str = "1") -> dict:
        return {"bill_id": "112-hr-1", "publication_id": publication, "source": source, "pub_date": pub_date}

    feed_later, bulk = row("cbo_feed", "2012-06-01T00:00:00Z"), row("billstatus_bulk", "2012-05-01T00:00:00Z")
    other = row("cbo_feed", None, "2")
    assert merge_cbo_cost_estimates([feed_later, other, bulk]) == (bulk, other)
    assert merge_cbo_cost_estimates([bulk, feed_later]) == (bulk,)
    newer = row("cbo_feed", "2012-07-01T00:00:00Z")
    assert merge_cbo_cost_estimates([feed_later, newer, row("cbo_feed", None)]) == (newer,)
    with pytest.raises(TableContractError, match="source must be one of"):
        merge_cbo_cost_estimates([row("scraped", None)])


def test_one_publication_under_two_bills_publishes_both_rows_through_the_merge() -> None:
    """22065, CBO's estimate of P.L. 111-322: the 112th feed files it under Bill_Number H.R. 3082, the 112th's, and
    the 111th's H.R. 3082 BILLSTATUS lists it, twice, on http and https (retained BILLSTATUS-111-hr.zip). The identity
    is (bill_id, publication_id), so the merge keeps both, and title_bill_id names the bill scored on each."""
    title = "P.L. 111-322, the Continuing Appropriations and Surface Transportation Extensions Act, 2011"
    text = "CBO estimate of the Act providing funding for discretionary activities through March 4, 2011"
    stated = (
        CboCostEstimate("2011-03-07T06:00:00Z", title, "http://www.cbo.gov/publication/22065", f"<p>{text}</p>"),
        CboCostEstimate("2011-03-07T06:00:00Z", title, "https://www.cbo.gov/publication/22065", text),
    )
    law_bills = {"111-public-322": "111-hr-3082"}
    (entry,), _ = fold_cbo_cost_estimates(stated)
    billstatus = shape_cbo_cost_estimate(BillIdentity(111, "hr", 3082), entry, title_bill_id="111-hr-3082")
    feed = build_cbo_feed_cost_estimates(FEED_112, 112, law_bills=law_bills).cbo_cost_estimates
    merged = merge_cbo_cost_estimates([billstatus, *feed])
    both = [(r["bill_id"], r["source"], r["title_bill_id"]) for r in merged if r["publication_id"] == "22065"]
    assert both == [("111-hr-3082", "billstatus_bulk", "111-hr-3082"), ("112-hr-3082", "cbo_feed", "111-hr-3082")]
    assert len(merged) == len(feed) + 1


# --- the family pass ----------------------------------------------------------------


def test_the_family_pass_produces_the_estimate_rows_from_the_same_document() -> None:
    """The family pass produces estimate rows keyed to the bill from the same document."""
    parsed = status("BILLSTATUS-118s3139", S3139)
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert len(family.cbo_cost_estimates) == 1
    row = family.cbo_cost_estimates[0]
    assert CBO_COST_ESTIMATES.key(row) == ("118-s-3139", "60334")
    assert json.loads(row["report_citations_json"])[0]["citation"] == "S. Rept. 118-289"


def test_the_family_pass_refuses_an_unkeyable_url_by_name() -> None:
    """The family pass refuses an unkeyable URL by name with the publication-page reason."""
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


def test_refused_query_credential_never_reaches_a_reason_row_or_log(caplog: pytest.LogCaptureFixture) -> None:
    """A credential in a refused query never reaches the refusal reason, the repr or the log."""
    sentinel = "sentinel-credential-must-not-survive"
    parsed = replace(
        status("BILLSTATUS-118hr801", HR801),
        cbo_cost_estimates=(
            CboCostEstimate(None, None, f"https://www.cbo.gov/publication/59139?api_key={sentinel}", None),
        ),
    )
    family = build_bill_family(BillFamilyCapture(status=parsed, versions=()), engine=ENGINE, diff=False)
    assert family.cbo_cost_estimates == ()
    refusal = next(r for r in family.refusals if r.table == "cbo_cost_estimates")
    assert refusal.reason == (
        "cbo_publication_url: cost-estimate url is outside the measured publication-page shape; "
        "host=www.cbo.gov; path shape=/publication/{id}"
    )
    assert sentinel not in refusal.reason
    assert sentinel not in repr(family)
    logging.getLogger(__name__).warning("Family result: %s", family)
    assert "Family result:" in caplog.text
    assert sentinel not in caplog.text


def test_family_refusal_scrubs_free_text_before_truncation() -> None:
    """Family refusals scrub free text before truncating."""
    from spicy_docs.interpretation.bill_family import _Admitter

    admit = _Admitter()
    admit.refuse("cbo_cost_estimates", ("118-hr-801", "0"), "x" * 1980 + " api_key=" + "sentinel" * 20)
    assert "sentinel" not in admit.refusals[0].reason
    assert "<redacted>" in admit.refusals[0].reason
