"""Parametrized ports of BillTrax's two committee-report aggregate queries, over plain row mappings."""

import pytest

from spicy_docs.interpretation.report_sections import agency_recurrence, sections_for_agency


def _row(
    congress,
    bill_number,
    agency_label,
    body="",
    *,
    bill_id=None,
    report_id=None,
    chamber="house",
    label=None,
    date=None,
    text=None,
    source="upload",
    section_id=None,
    seq=0,
):
    return {
        "congress": congress,
        "bill_number": bill_number,
        "bill_id": bill_id or f"bill-{bill_number}",
        "report_id": report_id or f"report-{bill_number}-{chamber}",
        "chamber": chamber,
        "report_label": label or f"{chamber} report {bill_number}",
        "date": date,
        "report_text": text or "full report text",
        "source": source,
        "section_id": section_id or f"section-{bill_number}-{agency_label}",
        "seq": seq,
        "agency_label": agency_label,
        "body": body,
    }


# ---- agency_recurrence ----


def test_agency_recurrence_counts_distinct_congresses_across_bills():
    rows = [
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "body one"),
        _row(117, "HR2", "DEPARTMENT OF DEFENSE", "body two"),
        _row(116, "HR3", "OFFICE OF MANAGEMENT AND BUDGET", "unrelated"),
    ]
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
    assert result["count"] == 2
    assert [c["congress"] for c in result["congresses"]] == [118, 117]


@pytest.mark.parametrize(
    "query_label",
    ["Department of Defense", " DEPARTMENT OF DEFENSE ", "department of defense", "DEPARTMENT OF DEFENSE"],
)
def test_agency_recurrence_normalizes_the_query_label_upper_and_trim(query_label):
    rows = [_row(118, "HR1", "DEPARTMENT OF DEFENSE", "body")]
    assert agency_recurrence(rows, query_label)["count"] == 1


def test_agency_recurrence_normalizes_row_labels_the_same_way():
    rows = [_row(118, "HR1", "  Department Of Defense  ", "body")]
    assert agency_recurrence(rows, "DEPARTMENT OF DEFENSE")["count"] == 1


def test_agency_recurrence_dedupes_multiple_reports_in_the_same_congress_keeping_one():
    rows = [
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "house body", chamber="house"),
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "senate body", chamber="senate", report_id="report-HR1-senate"),
    ]
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
    assert result["count"] == 1
    assert len(result["congresses"]) == 1


def test_agency_recurrence_excerpt_is_the_first_two_hundred_characters_of_body():
    long_body = "X" * 250
    rows = [_row(118, "HR1", "DEPARTMENT OF DEFENSE", long_body)]
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
    assert result["congresses"][0]["excerpt"] == "X" * 200


def test_agency_recurrence_orders_congresses_descending():
    rows = [
        _row(115, "HR1", "DEPARTMENT OF DEFENSE"),
        _row(118, "HR2", "DEPARTMENT OF DEFENSE"),
        _row(116, "HR3", "DEPARTMENT OF DEFENSE"),
    ]
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
    assert [c["congress"] for c in result["congresses"]] == [118, 116, 115]


def test_agency_recurrence_limit_caps_raw_rows_before_per_congress_dedup():
    # BillTrax's SQL LIMIT applies to the SELECT DISTINCT rows, before the app-level per-congress
    # dedup -- so duplicate rows for the top congress can starve out an older, less-represented one.
    rows = [_row(200, f"HR{i}", "DEPARTMENT OF DEFENSE", body=f"body {i}", report_id=f"r{i}") for i in range(3)]
    rows.append(_row(100, "HR-OLD", "DEPARTMENT OF DEFENSE", body="older congress"))
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE", limit=3)
    # All three raw rows for congress 200 exhaust the limit=3 cap before congress 100 is ever read.
    assert result["count"] == 1
    assert result["congresses"][0]["congress"] == 200


def test_agency_recurrence_no_match_returns_zero_and_empty_list():
    rows = [_row(118, "HR1", "DEPARTMENT OF DEFENSE")]
    result = agency_recurrence(rows, "SMALL BUSINESS ADMINISTRATION")
    assert result == {"count": 0, "congresses": []}


def test_agency_recurrence_default_limit_is_twenty():
    rows = [_row(300 - i, f"HR{i}", "DEPARTMENT OF DEFENSE", report_id=f"r{i}") for i in range(25)]
    result = agency_recurrence(rows, "DEPARTMENT OF DEFENSE")
    assert result["count"] == 20


# ---- sections_for_agency ----


def test_sections_for_agency_filters_by_bill_id_and_exact_agency_label():
    rows = [
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "match", bill_id="bill-1"),
        _row(118, "HR1", "OFFICE OF MANAGEMENT AND BUDGET", "wrong agency", bill_id="bill-1"),
        _row(118, "HR2", "DEPARTMENT OF DEFENSE", "wrong bill", bill_id="bill-2"),
    ]
    result = sections_for_agency(rows, "bill-1", "DEPARTMENT OF DEFENSE")
    assert len(result) == 1
    assert result[0]["section"]["body"] == "match"


def test_sections_for_agency_match_is_case_sensitive_unlike_agency_recurrence():
    rows = [_row(118, "HR1", "Department Of Defense", "body", bill_id="bill-1")]
    assert sections_for_agency(rows, "bill-1", "DEPARTMENT OF DEFENSE") == ()
    assert len(sections_for_agency(rows, "bill-1", "Department Of Defense")) == 1


def test_sections_for_agency_orders_by_chamber_alphabetically():
    rows = [
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "senate body", bill_id="bill-1", chamber="senate", report_id="r-s"),
        _row(118, "HR1", "DEPARTMENT OF DEFENSE", "house body", bill_id="bill-1", chamber="house", report_id="r-h"),
        _row(
            118,
            "HR1",
            "DEPARTMENT OF DEFENSE",
            "conference body",
            bill_id="bill-1",
            chamber="conference",
            report_id="r-c",
        ),
    ]
    result = sections_for_agency(rows, "bill-1", "DEPARTMENT OF DEFENSE")
    assert [entry["report"]["chamber"] for entry in result] == ["conference", "house", "senate"]


def test_sections_for_agency_report_sections_field_is_always_empty():
    # Matches BillTrax's own construction (committee-reports.ts:200): the embedded report carries no
    # `sections` list of its own, even though a real report may have several.
    rows = [_row(118, "HR1", "DEPARTMENT OF DEFENSE", "body", bill_id="bill-1")]
    result = sections_for_agency(rows, "bill-1", "DEPARTMENT OF DEFENSE")
    assert result[0]["report"]["sections"] == []


def test_sections_for_agency_shapes_report_and_section_like_billtrax_camel_case_fields():
    rows = [
        _row(
            118,
            "HR1",
            "DEPARTMENT OF DEFENSE",
            "body text",
            bill_id="bill-1",
            report_id="report-1",
            chamber="house",
            label="H. Rept. 118-1",
            date="2024-01-01",
            text="full report",
            source="upload",
            section_id="section-1",
            seq=3,
        )
    ]
    (entry,) = sections_for_agency(rows, "bill-1", "DEPARTMENT OF DEFENSE")
    assert entry["report"] == {
        "id": "report-1",
        "bill_id": "bill-1",
        "chamber": "house",
        "label": "H. Rept. 118-1",
        "date": "2024-01-01",
        "text": "full report",
        "source": "upload",
        "sections": [],
    }
    assert entry["section"] == {
        "id": "section-1",
        "report_id": "report-1",
        "seq": 3,
        "agency_label": "DEPARTMENT OF DEFENSE",
        "body": "body text",
    }


def test_sections_for_agency_no_match_returns_empty_tuple():
    rows = [_row(118, "HR1", "DEPARTMENT OF DEFENSE", bill_id="bill-1")]
    assert sections_for_agency(rows, "bill-1", "NOT PRESENT") == ()
    assert sections_for_agency(rows, "not-this-bill", "DEPARTMENT OF DEFENSE") == ()
