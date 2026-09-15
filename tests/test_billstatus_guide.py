"""Literal guide values and original byte positions precede code-set interpretation."""

import dataclasses
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.sources.congress.billstatus_codes import (
    BillStatusGuideError,
    BillStatusGuideText,
    read_billstatus_guide,
)

FIXTURES = Path(__file__).parent / "fixtures"
GUIDE = (FIXTURES / "billstatus_codes" / "guide-2026-08-03.md").read_bytes()


def spans(value):
    if isinstance(value, BillStatusGuideText):
        yield value
    elif dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from spans(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from spans(item)


@pytest.mark.parametrize("body", [GUIDE, b"Unicode prefix: \xc3\xa9\n" + GUIDE, GUIDE.replace(b"\n", b"\r\n")])
def test_all_spans_replay_exact_original_bytes_and_line_numbers(body):
    result = read_billstatus_guide(body)
    for span in spans(result):
        assert body[span.byte_start : span.byte_end].decode("utf-8") == span.text
        assert body[: span.byte_start].count(b"\n") + 1 == span.line_number
    assert result.input_sha256 == hashlib.sha256(body).hexdigest()
    assert result.input_bytes == len(body)


def test_complete_raw_guide_retains_codes_headers_context_and_version_explanation():
    result = read_billstatus_guide(GUIDE)
    assert [value.value for value in result.bill_type_statements[0].values] == [
        "H",
        "S",
        "HRES",
        "SRES",
        "HJRES",
        "SJRES",
        "HCONRES",
        "SCONRES",
    ]
    assert [(table.section_number, len(table.rows)) for table in result.tables] == [
        ("3", 36),
        ("4", 26),
        ("5", 88),
        ("6", 24),
    ]
    actions = result.tables[0]
    assert "provided as a courtesy" in actions.context.text
    assert "a complete, authoritative list of action codes does not exist" in actions.context.text
    assert [cell.value for cell in actions.header.cells] == ["Code", "Text in the `<actionCode>` Element"]
    assert actions.rows[0].cells[0].raw.text == " **B00100** "
    assert actions.rows[0].cells[0].value == "B00100" and actions.rows[0].cells[0].bold
    assert result.tables[2].rows[0].cells[0].value == "00"
    assert result.tables[2].rows[1].cells[0].value == "00"
    assert result.tables[2].rows[0].cells[1].value == "HOUSE"
    assert result.tables[2].rows[1].cells[1].value == "SENATE"
    assert "increment value when data format changes" in result.version_notes[0].text.text
    pin = json.loads((FIXTURES / "billstatus_codes" / "provenance.json").read_text())
    assert (result.input_sha256, result.input_bytes) == (pin["sha256"], pin["bytes"])


def test_guide_section_values_and_current_xml_are_not_reconciled():
    result = read_billstatus_guide(GUIDE)
    assert "- House Bill (HR)" in result.bill_type_introductions[0].text.text
    assert result.bill_type_statements[0].values[0].value == "H"
    source = ET.fromstring((FIXTURES / "govinfo_bills" / "status-119hr6028.xml").read_bytes())
    assert source.findtext("bill/type") == "HR"
    assert source.findtext("version") == "3.0.0"


def test_unicode_presentation_whitespace_preserves_values_and_exact_spans():
    body = (
        "### `<billType>`\n\u00a0\n\u00a0Bill type (Possible values are H, S).\u00a0\n"
        "# 4. Actions Type Element Possible Values\n"
        "\u00a0| Kind |\u00a0\n\u00a0| --- |\u00a0\n\u00a0| \u00a0value\u00a0 |\u00a0\n"
    ).encode()
    result = read_billstatus_guide(body)
    assert [cell.value for cell in result.bill_type_statements[0].values] == ["H", "S"]
    assert result.tables[0].rows[0].cells[0].value == "value"
    for span in spans(result):
        assert body[span.byte_start : span.byte_end].decode() == span.text
        assert body[: span.byte_start].count(b"\n") + 1 == span.line_number


def test_unknown_empty_and_repeated_source_values_survive():
    changed = GUIDE.replace(b"H, S, HRES", b"H, , H, lower, HRES", 1)
    changed = changed.replace(
        b"| **B00100** | Sponsor introductory remarks on measure |", b"| **z?** |  |\n| **z?** | second |", 1
    )
    result = read_billstatus_guide(changed)
    assert [cell.value for cell in result.bill_type_statements[0].values][:4] == ["H", "", "H", "lower"]
    assert [row.cells[0].value for row in result.tables[0].rows][:2] == ["z?", "z?"]
    assert result.tables[0].rows[0].cells[1].value == ""


def test_repeated_sections_are_separate_and_absent_sections_stay_absent():
    result = read_billstatus_guide(GUIDE + b"\n### `<billType>`\nBill type (Possible values are NEW).\n")
    assert len(result.bill_type_statements) == 2
    assert result.bill_type_statements[-1].values[0].value == "NEW"
    assert read_billstatus_guide(b"# Other source\n").tables == ()
    table = b"# 4. Actions Type Element Possible Values\n\n| Kind |\n| --- |\n| one |\n"
    assert len(read_billstatus_guide(table + table).tables) == 2


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\xff",
        b"### `<billType>`\nwrong sentence\n",
        b"### `<billType>`\n",
        b"# 3. Action Code Element Possible Values\nno table\n",
        b"# 3. Action Code Element Possible Values\n| Code | Value |\n| bad | --- |\n",
        b"# 3. Action Code Element Possible Values\n| Code | Value |\n| --- | --- |\n| a | b | c |\n",
        b"# 3. Action Code Element Possible Values\n| Code | Value |\n| --- | --- |\n| a | b ",
    ],
)
def test_unsupported_or_malformed_source_shape_refuses(body):
    with pytest.raises(BillStatusGuideError):
        read_billstatus_guide(body)


def test_escaped_pipes_and_separated_second_table_refuse_explicitly():
    table = b"# 4. Actions Type Element Possible Values\n| Type |\n| --- |\n| value |\n"
    with pytest.raises(BillStatusGuideError, match="escaped pipes"):
        read_billstatus_guide(table.replace(b"value", b"a\\|b"))
    with pytest.raises(BillStatusGuideError, match="multiple pipe tables"):
        read_billstatus_guide(table + b"\n| Type |\n| --- |\n| second |\n")


def test_empty_table_and_case_and_whitespace_preserve_source_observations():
    result = read_billstatus_guide(b"# 4. Actions Type Element Possible Values\n| Kind |\n| --- |\n")
    assert result.tables[0].rows == ()
    result = read_billstatus_guide(b"### `<billType>`\nBill type (Possible values are and H, and\tS, low).\n")
    assert [cell.value for cell in result.bill_type_statements[0].values] == ["and H", "S", "low"]


@pytest.mark.parametrize("option", ["max_bytes", "max_rows"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_limits_refuse(option, value):
    with pytest.raises(BillStatusGuideError):
        read_billstatus_guide(GUIDE, **{option: value})


def test_byte_row_and_column_limits_refuse():
    with pytest.raises(BillStatusGuideError, match="max_bytes"):
        read_billstatus_guide(GUIDE, max_bytes=len(GUIDE) - 1)
    with pytest.raises(BillStatusGuideError, match="max_rows"):
        read_billstatus_guide(GUIDE, max_rows=100)
    with pytest.raises(BillStatusGuideError, match="max_rows"):
        read_billstatus_guide(b"### `<billType>`\nBill type (Possible values are " + b"," * 10000 + b").\n", max_rows=2)
    with pytest.raises(BillStatusGuideError, match="32 columns"):
        read_billstatus_guide(b"# 4. Actions Type Element Possible Values\n|" + b" x |" * 33 + b"\n| --- |\n")
