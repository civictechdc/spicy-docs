"""Faithful native FOIA and Oversight metadata/body boundaries on retained inputs."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spicy_docs.sources.agency_reports.foia import FoiaReportError, parse_foia_annual_report
from spicy_docs.sources.agency_reports.oversight import OversightReportError, parse_oversight_report

FIXTURES = Path(__file__).parent / "fixtures/agency_reports"
URL = "https://www.oversight.gov/reports/example-report"
ROOT = "http://leisp.usdoj.gov/niem/FoiaAnnualReport/exchange/1.03"
EXTENSION = "http://leisp.usdoj.gov/niem/FoiaAnnualReport/extension/1.03"
CORE = "http://niem.gov/niem/niem-core/2.0"


def foia(extra=b"", year="2025"):
    return (
        f'<r:FoiaAnnualReport xmlns:r="{ROOT}" xmlns:f="{EXTENSION}" xmlns:n="{CORE}" xmlns:s="http://niem.gov/niem/structures/2.0"><n:Organization s:id="ORG0"><n:OrganizationName>FEC</n:OrganizationName></n:Organization><f:DocumentFiscalYearDate>{year}</f:DocumentFiscalYearDate>'.encode()
        + extra
        + b"</r:FoiaAnnualReport>"
    )


def report(fields, *, recommendations="", depth=0):
    return (
        f'<!doctype html><html><header><h1>Source title</h1></header><main><article class="node--type-report"><div class="field-values-list__content">{fields}</div></article>{recommendations}{"<div>" * depth}wrapped value{"</div>" * depth}</main></html>'
    ).encode()


def field(name, value, label="Label"):
    return f'<div class="field field--name-{name}"><div class="title">{label}</div><div>{value}</div></div>'


def test_foia_literal_values_namespace_context_and_duplicate_associations():
    body = foia(
        b'<f:Unknown xmlns:q="urn:qualifier" s:type="q:Type">before<f:Amount>01.00</f:Amount>after<f:Amount></f:Amount>end</f:Unknown><f:Association s:ref="ORG0"/><f:Association s:ref="ORG0"/>'
    )
    result = parse_foia_annual_report(body)
    rows = result["elements"]
    unknown = rows[4]
    assert unknown["namespace_declarations"] == {"q": "urn:qualifier"}
    assert unknown["text"] == "before"
    assert rows[5]["text"] == "01.00" and rows[5]["tail"] == "after"
    assert rows[6]["text"] is None and rows[6]["tail"] == "end"
    assert rows[-2]["attributes"] == rows[-1]["attributes"]
    assert rows[-2]["child_indices"] != rows[-1]["child_indices"]
    assert result["metadata"]["fiscal_year"] == {"element": 3, "value": "2025"}
    assert result["metadata"]["organizations"][0]["id"] == "ORG0"
    assert result["source"]["sha256"] == "sha256:" + hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("version", ["1.02", "1.03"])
def test_native_report_versions_keep_literals_and_empty_fields(version):
    body = foia(b'<f:Unknown s:nil="true"/>', year=" 2025 ").replace(b"1.03", version.encode())
    if version == "1.02":
        body = body.replace(b"DocumentFiscalYearDate", b"DocumentFiscalYear")
    result = parse_foia_annual_report(body)
    assert result["metadata"]["schema_version"] == version
    assert result["metadata"]["fiscal_year"]["value"] == " 2025 "
    assert result["elements"][-1]["text"] is None


@pytest.mark.parametrize(
    "body, match",
    [
        (b"<html>denied</html>", "root"),
        (b'<pkg:package xmlns:pkg="http://schemas.microsoft.com/office/2006/xmlPackage"/>', "Word Flat OPC"),
        (foia(year=" "), "fiscal year"),
        (foia(b"<f:DocumentFiscalYearDate>2026</f:DocumentFiscalYearDate>"), "fiscal year"),
        (foia().replace(b"1.03", b"9.99"), "root"),
        (b'<!DOCTYPE r [<!ENTITY e "changed">]>' + foia(), "DOCTYPE|entity"),
        (foia()[:-20], "malformed"),
    ],
)
def test_foia_refuses_other_representations_or_ambiguous_identity(body, match):
    with pytest.raises(FoiaReportError, match=match):
        parse_foia_annual_report(body)


def test_foia_checks_limits_at_and_over_the_bound():
    body = foia()
    count = len(parse_foia_annual_report(body)["elements"])
    assert len(parse_foia_annual_report(body, max_bytes=len(body), max_elements=count)["elements"]) == count
    for options in ({"max_bytes": len(body) - 1}, {"max_elements": count - 1}, {"max_elements": True}):
        with pytest.raises(FoiaReportError):
            parse_foia_annual_report(body, **options)
    with pytest.raises(FoiaReportError, match="depth"):
        parse_foia_annual_report(foia(b"<f:x>" * 64 + b"</f:x>" * 64))


@pytest.mark.parametrize("year, version", [("2010", "1.02"), ("2025", "1.03")])
def test_retained_foia_matches_every_independently_read_xml_element(year, version):
    raw = (FIXTURES / f"foia-fec-{year}.xml").read_bytes()
    result = parse_foia_annual_report(raw)
    expected = []

    def visit(node, path, parent):
        index = len(expected)
        expected.append(
            {
                "child_indices": path,
                "parent": parent,
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text,
                "tail": node.tail,
            }
        )
        for i, child in enumerate(node):
            visit(child, [*path, i], index)

    visit(ET.fromstring(raw), [], None)
    assert [{k: v for k, v in row.items() if k != "namespace_declarations"} for row in result["elements"]] == expected
    assert result["metadata"]["schema_version"] == version
    assert result["metadata"]["fiscal_year"]["value"] == year
    assert result["metadata"]["organizations"][0]["abbreviations"][0]["value"] == "FEC"
    if year == "2025":
        assert result["metadata"]["creation_dates"][0]["value"] == "2026-05-06"


def test_oversight_preserves_fields_and_moves_description_out_of_metadata():
    fields = field("field-report-file", '<a href="/file.pdf">PDF</a><a href="/file.pdf">PDF copy</a>')
    fields += field("field-report-date-issued", '<time datetime="2026-01-02T00:00:00Z">Printed date</time>')
    fields += field("body", "<p>Exact <strong>body</strong></p>")
    fields += field("future-field", '<span content="-01.00">-$1</span>')
    fields += field("future-field", "")
    result = parse_oversight_report(report(fields), url=URL)
    rows = result["metadata"]["fields"]
    assert [r["native_field"] for r in rows] == [
        "field-report-file",
        "field-report-date-issued",
        "body",
        "future-field",
        "future-field",
    ]
    assert "value" not in rows[2] and rows[2]["body_index"] == 0
    assert result["bodies"][0]["text"] == "Exact body"
    assert rows[1]["times"] == [{"datetime": "2026-01-02T00:00:00Z"}]
    assert rows[3]["numeric_content"] == ["-01.00"] and rows[4]["value"] == ""
    assert [x["href"] for x in result["assets"]] == ["/file.pdf", "/file.pdf"]
    assert result["assets"][0]["source_position"] != result["assets"][1]["source_position"]
    assert rows[0]["links"][0]["url"] == "https://www.oversight.gov/file.pdf"


def test_retained_oversight_includes_recommendations_outside_the_report_article():
    raw = (FIXTURES / "oversight-data-act.html").read_bytes()
    result = parse_oversight_report(raw, url=URL)
    assert result["metadata"]["title"] == "Evaluation of the FEC’s DATA Act Compliance"
    report_file = result["metadata"]["fields"][0]
    assert [item["text"] for item in report_file["items"]] == ["View Report"]
    assert result["metadata"]["title_position"]["line"] == 547
    (recommendation_index,) = result["metadata"]["recommendation_body_indices"]
    section = result["bodies"][recommendation_index]
    (table,) = section["tables"]
    assert len(table["rows"]) == 9
    assert [r["cells"][0]["text"] for r in table["rows"][1::2]] == ["1", "2", "3", "4"]
    for row in table["rows"][2::2]:
        (cell,) = row["cells"]
        assert cell["attributes"]["colspan"] == "6"
        assert cell["text"].startswith("The OIG recommends")
    cells = table["rows"][1]["cells"]
    assert cells[2]["text"] == "$0" and cells[4]["text"] == ""
    assert cells[2]["attributes"]["headers"] == ["view-field-net-questioned-costs-table-column"]
    assert "This report has 4 open recommendations." in section["text"]


@pytest.mark.parametrize(
    "body, options, match",
    [
        (b"<html><h1>Access denied</h1></html>", {}, "article"),
        (report(field("body", "text"))[:-20], {}, "unclosed"),
        (
            report(field("body", "text")).replace(
                b"field field--name-body", b"field field--name-body field--name-other"
            ),
            {},
            "native name",
        ),
        (report(field("body", "text")).replace(b'class="field ', b'class="duplicate" class="field '), {}, "attribute"),
        (report(field("body", "text")), {"max_bytes": 1}, "max_bytes"),
        (report(field("body", "text") * 2), {"max_fields": 1}, "max_fields"),
        (report(field("body", "text")), {"max_fields": True}, "positive"),
        (report(field("body", "text"), depth=100), {"max_depth": 64}, "max_depth"),
        (
            report(field("other", '<div class="field-values-list__content">' + field("body", "nested") + "</div>")),
            {},
            "must not nest",
        ),
    ],
)
def test_oversight_refuses_wrong_shapes_and_bounds(body, options, match):
    with pytest.raises(OversightReportError, match=match):
        parse_oversight_report(body, url=URL, **options)


def test_oversight_depth_control_keeps_ordinary_wrapping_and_empty_bodies():
    raw = report(field("body", ""), depth=40)
    result = parse_oversight_report(raw, url=URL, max_bytes=len(raw), max_fields=1, max_depth=64)
    assert result["bodies"][0]["text"] == ""
    assert result["metadata"]["recommendation_body_indices"] == []


def test_retained_fixture_pins():
    for row in json.loads((FIXTURES / "sources.json").read_bytes()):
        raw = (FIXTURES / row["file"]).read_bytes()
        assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_oversight_keeps_repeated_items_without_leaking_body_items_into_metadata():
    items = '<div class="field__items"><div class="field__item">First agency</div><div class="field__item">Second agency</div></div>'
    result = parse_oversight_report(report(field("agency", items) + field("body", items)), url=URL)
    agency, description = result["metadata"]["fields"]
    assert [item["text"] for item in agency["items"]] == ["First agency", "Second agency"]
    assert "items" not in description and "value" not in description
    assert [i["text"] for i in result["bodies"][0]["items"]] == [
        "First agency",
        "Second agency",
    ]


def test_oversight_refuses_missing_article_close_even_when_main_and_html_close():
    with pytest.raises(OversightReportError, match="unclosed"):
        parse_oversight_report(report(field("body", "text")).replace(b"</article>", b""), url=URL)


def test_oversight_refuses_nested_recommendation_rows():
    block = (
        '<div class="view-report-recommendations"><table><tr><td>outer<tr><td>inner</td></tr></td></tr></table></div>'
    )
    with pytest.raises(OversightReportError, match="rows must not nest"):
        parse_oversight_report(report(field("body", "text"), recommendations=block), url=URL)
