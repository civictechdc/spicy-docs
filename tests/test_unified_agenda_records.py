"""Literal Unified Agenda fields remain separate from receiver interpretation."""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers.expat import ExpatError

import pytest

from spicy_docs.reading.xml_observations import XmlObservationScan
from spicy_docs.sources.unified_agenda import (
    UnifiedAgendaEdition,
    unified_agenda_xml_locator,
    validate_unified_agenda_xml,
)
from spicy_docs.sources.unified_agenda.records import UnifiedAgendaSourceError, scan_unified_agenda_records

FIXTURE = Path(__file__).parent / "fixtures" / "unified_agenda" / "reginfo-rin-data-202510.xml"


def read(body, **kwargs):
    rows = []
    result = scan_unified_agenda_records(body, on_record=rows.append, **kwargs)
    return result, rows


def fields(record, tag):
    return [field for field in record.fields if field.element.tag == tag]


def test_retained_records_expose_exact_selected_fields_and_source_positions():
    body = FIXTURE.read_bytes()
    result, rows = read(body)
    expected = ET.fromstring(body)
    assert result.record_count == len(rows) == 2
    assert result.input_sha256 == hashlib.sha256(body).hexdigest()
    assert result.input_bytes == len(body)
    assert result.root.attributes == expected.attrib
    for index, row in enumerate(rows, 1):
        assert row.element.source_xpath == f"/*[1]/*[{index}]"
        for field in row.fields:
            source = next(item for item in expected[index - 1] if item.tag == field.element.tag)
            assert field.text == "".join(source.itertext())
            assert field.leading_text == (source.text or "")
            assert field.element.attributes == source.attrib
    first = rows[0]
    assert fields(first, "RIN")[0].text == "0503-AA90"
    assert [item.text for item in fields(first, "LEGAL_AUTHORITY_LIST")[0].children] == [
        "5 U.S.C. 301",
        "42 U.S.C. 2000bb et seq",
    ]
    assert fields(first, "TIMETABLE_LIST")[0].children[0].children[1].text == "11/00/2026"
    assert "<!DOCTYPE html>" in fields(first, "ABSTRACT")[0].text
    assert fields(first, "AGENCY")[0].children[0].text == "0503"
    assert fields(first, "PARENT_AGENCY")[0].children[0].text == "0500"
    assert fields(first, "ADDITIONAL_INFO") == []


def test_retained_continuation_is_literal_source_text_without_interpretation():
    path = FIXTURE.parent / "record-199704-1115-AE47.xml"
    body = path.read_bytes()
    result, rows = read(body)
    raw = ET.fromstring(body).find("RIN_INFO/ADDITIONAL_INFO")
    item = fields(rows[0], "ADDITIONAL_INFO")[0]
    assert item.text == item.leading_text == "".join(raw.itertext())
    assert "1186b" in item.text and "1447" in item.text
    provenance = json.loads((FIXTURE.parent / "records-provenance.json").read_text())
    assert next(row for row in provenance if row["fixture"] == path.name)["fixture_sha256"] == result.input_sha256


def test_retained_publisher_control_byte_is_not_repaired_by_source_reader():
    path = FIXTURE.parent / "record-200404-1084-AA00.xml"
    body = path.read_bytes()
    assert body.count(b"\x19") == 1 and b"Department\x19s" in body
    with pytest.raises(UnifiedAgendaSourceError, match="malformed"):
        read(body)
    provenance = json.loads((FIXTURE.parent / "records-provenance.json").read_text())
    assert (
        next(row for row in provenance if row["fixture"] == path.name)["fixture_sha256"]
        == hashlib.sha256(body).hexdigest()
    )


def test_missing_empty_repeated_and_unknown_children_survive_in_source_order():
    body = b"""<REGINFO_RIN_DATA><RIN_INFO note="raw"><RIN/><RIN> second </RIN>
    <PUBLICATION/><PUBLICATION><PUBLICATION_ID/><PUBLICATION_ID> x </PUBLICATION_ID></PUBLICATION>
    <CFR_LIST/><CFR_LIST a="v"><CFR/><CFR> </CFR><OTHER flag="x">unexpected</OTHER></CFR_LIST>
    <LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY/><LEGAL_AUTHORITY>literal</LEGAL_AUTHORITY></LEGAL_AUTHORITY_LIST>
    <TIMETABLE_LIST><TIMETABLE/><TIMETABLE><TTBL_DATE/><TTBL_DATE>00/00/0000</TTBL_DATE><FR_CITATION/></TIMETABLE></TIMETABLE_LIST>
    <ADDITIONAL_INFO/><ADDITIONAL_INFO> A\n\nB^PC </ADDITIONAL_INFO><UNKNOWN>unselected</UNKNOWN>
    </RIN_INFO><RIN_INFO/></REGINFO_RIN_DATA>"""
    _, rows = read(body)
    assert rows[1].fields == ()
    assert rows[0].element.attributes == {"note": "raw"}
    assert [item.text for item in fields(rows[0], "RIN")] == ["", " second "]
    assert len(fields(rows[0], "PUBLICATION")) == 2
    cfr = fields(rows[0], "CFR_LIST")
    assert cfr[0].children == () and cfr[0].text == ""
    assert [item.text for item in cfr[1].children] == ["", " ", "unexpected"]
    assert cfr[1].children[2].element.attributes == {"flag": "x"}
    assert fields(rows[0], "TIMETABLE_LIST")[0].children[0].children == ()
    assert [item.text for item in fields(rows[0], "ADDITIONAL_INFO")] == ["", " A\n\nB^PC "]
    assert fields(rows[0], "UNKNOWN") == []


def test_descendant_and_leading_text_are_distinct_without_normalization():
    body = b"""<REGINFO_RIN_DATA><RIN_INFO><ADDITIONAL_INFO>\r\nA&amp;B<x:span xmlns:x="urn:unknown" x:a="v">child</x:span>tail<empty/>end</ADDITIONAL_INFO></RIN_INFO></REGINFO_RIN_DATA>"""
    _, rows = read(body)
    item = fields(rows[0], "ADDITIONAL_INFO")[0]
    assert item.text == "\nA&Bchildtailend"
    assert item.leading_text == "\nA&B"
    assert item.children[0].element.tag == "{urn:unknown}span"
    assert item.children[0].element.attributes == {"{urn:unknown}a": "v"}
    assert item.children[0].element.source_xpath == "/*[1]/*[1]/*[1]/*[1]"
    assert item.children[0].text == item.children[0].leading_text == "child"
    assert item.children[1].text == item.children[1].leading_text == ""


def test_parser_chunks_entities_comments_and_cdata_do_not_change_text():
    content = b"x" * 65520 + b"&amp;y<!-- ignored -->z<?hint x?><![CDATA[<p>html</p>]]>"
    _, rows = read(b"<REGINFO_RIN_DATA><RIN_INFO><ABSTRACT>" + content + b"</ABSTRACT></RIN_INFO></REGINFO_RIN_DATA>")
    item = fields(rows[0], "ABSTRACT")[0]
    assert item.text == item.leading_text == "x" * 65520 + "&yz<p>html</p>"


def test_retained_mutations_preserve_raw_occurrences_while_validator_checks_identity():
    body = FIXTURE.read_bytes().replace(b"<RIN>0503-AA90</RIN>", b"<RIN>0503-AA90</RIN><RIN/>", 1)
    _, rows = read(body)
    assert len(fields(rows[0], "RIN")) == 2
    with pytest.raises(UnifiedAgendaSourceError, match="exactly one RIN"):
        validate_unified_agenda_xml(
            body,
            edition=UnifiedAgendaEdition("202510"),
            final_url=unified_agenda_xml_locator(UnifiedAgendaEdition("202510")),
        )
    changed = FIXTURE.read_bytes().replace(b"<CFR_LIST>", b"<CFR_LIST/><CFR_LIST>", 1)
    assert len(fields(read(changed)[1][0], "CFR_LIST")) == 2


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<wrong/>",
        b"<REGINFO_RIN_DATA><RIN_INFO>",
        b"<REGINFO_RIN_DATA><RIN_INFO><ADDITIONAL_INFO>bad\x19text</ADDITIONAL_INFO></RIN_INFO></REGINFO_RIN_DATA>",
        b'<!DOCTYPE REGINFO_RIN_DATA SYSTEM "file:///tmp/unread"><REGINFO_RIN_DATA/>',
        b'<!DOCTYPE REGINFO_RIN_DATA [<!ENTITY x "bad">]><REGINFO_RIN_DATA/>',
        b"<REGINFO_RIN_DATA><REGINFO_RIN_DATA/></REGINFO_RIN_DATA>",
    ],
)
def test_malformed_or_unsafe_source_refuses(body):
    with pytest.raises(UnifiedAgendaSourceError):
        read(body)


@pytest.mark.parametrize(
    "body",
    [
        b"<REGINFO_RIN_DATA><wrapper><RIN_INFO/></wrapper></REGINFO_RIN_DATA>",
        b"<REGINFO_RIN_DATA><RIN_INFO><RIN_INFO/></RIN_INFO></REGINFO_RIN_DATA>",
        b"<REGINFO_RIN_DATA><RIN_INFO><ADDITIONAL_INFO><RIN_INFO/></ADDITIONAL_INFO></RIN_INFO></REGINFO_RIN_DATA>",
    ],
)
def test_misplaced_records_refuse_instead_of_disappearing(body):
    with pytest.raises(UnifiedAgendaSourceError, match="direct child"):
        read(body)


def test_empty_root_is_a_zero_observation_scan():
    result, rows = read(b"<REGINFO_RIN_DATA/>")
    assert result.record_count == 0 and rows == []


@pytest.mark.parametrize("error_type", [ValueError, ExpatError, RuntimeError])
def test_callback_exception_identity_and_provisional_prefix(error_type):
    failure = error_type("receiver refused")

    def refuse(_row):
        raise failure

    with pytest.raises(error_type) as raised:
        scan_unified_agenda_records(b"<REGINFO_RIN_DATA><RIN_INFO/></REGINFO_RIN_DATA>", on_record=refuse)
    assert raised.value is failure
    rows = []
    with pytest.raises(UnifiedAgendaSourceError):
        scan_unified_agenda_records(b"<REGINFO_RIN_DATA><RIN_INFO/><bad>", on_record=rows.append)
    assert len(rows) == 1


@pytest.mark.parametrize("option", ["max_bytes", "max_records", "max_fields", "max_text_characters", "max_depth"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_bounds_refuse(option, value):
    with pytest.raises(UnifiedAgendaSourceError):
        read(b"<REGINFO_RIN_DATA/>", **{option: value})


def test_record_node_text_and_depth_budgets():
    with pytest.raises(UnifiedAgendaSourceError, match="max_bytes"):
        read(b"<REGINFO_RIN_DATA/>", max_bytes=1)
    with pytest.raises(UnifiedAgendaSourceError, match="max_records"):
        read(b"<REGINFO_RIN_DATA><RIN_INFO/><RIN_INFO/></REGINFO_RIN_DATA>", max_records=1)
    body = b"<REGINFO_RIN_DATA><RIN_INFO><CFR_LIST><CFR>ab</CFR><CFR>cd</CFR></CFR_LIST></RIN_INFO></REGINFO_RIN_DATA>"
    with pytest.raises(UnifiedAgendaSourceError, match="max_fields"):
        read(body, max_fields=2)
    # Scalar text is stored in ancestor text, own text and own leading_text.
    with pytest.raises(UnifiedAgendaSourceError, match="max_text_characters"):
        read(body, max_text_characters=11)
    assert read(body, max_text_characters=12)[0].record_count == 1
    with pytest.raises(UnifiedAgendaSourceError, match="depth"):
        read(body, max_depth=3)
    repeated = b"<REGINFO_RIN_DATA>" + b"<RIN_INFO><RIN>ab</RIN></RIN_INFO>" * 2 + b"</REGINFO_RIN_DATA>"
    assert read(repeated, max_text_characters=4)[0].record_count == 2


def test_identity_validation_does_not_buffer_unrequested_metadata():
    body = (
        b"<REGINFO_RIN_DATA><RIN_INFO><RIN>x</RIN><PUBLICATION><PUBLICATION_ID>202510</PUBLICATION_ID></PUBLICATION><ABSTRACT>"
        + b"x" * (3 * 1024 * 1024)
        + b"</ABSTRACT></RIN_INFO></REGINFO_RIN_DATA>"
    )
    assert (
        validate_unified_agenda_xml(
            body,
            edition=UnifiedAgendaEdition("202510"),
            final_url=unified_agenda_xml_locator(UnifiedAgendaEdition("202510")),
        ).record_count
        == 1
    )
    with pytest.raises(UnifiedAgendaSourceError, match="max_text_characters"):
        read(body)


def test_field_capture_does_not_recopy_ancestor_attribute_maps(monkeypatch):
    maps = []

    class CountedAttributes(dict):
        copies = 0

        def __iter__(self):
            return super().__iter__()

        def keys(self):
            self.copies += 1
            return super().keys()

    original = XmlObservationScan.start

    def start(scanner, tag, attributes):
        counted = CountedAttributes(attributes)
        maps.append((tag, counted))
        original(scanner, tag, counted)

    monkeypatch.setattr(XmlObservationScan, "start", start)
    body = (
        b'<REGINFO_RIN_DATA big="source"><RIN_INFO big="record"><CFR_LIST>'
        + b"<CFR>x</CFR>" * 100
        + b"</CFR_LIST></RIN_INFO></REGINFO_RIN_DATA>"
    )
    read(body)
    assert [(tag, attributes.copies) for tag, attributes in maps[:2]] == [("REGINFO_RIN_DATA", 1), ("RIN_INFO", 1)]
