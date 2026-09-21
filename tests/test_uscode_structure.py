"""scan_uscode_structure retains native source facts; legal normalization and attestation remain downstream.

Publisher identifiers, ranges, appendix fragments, headings, and statuses survive; foreign-namespace elements are
ignored; partial callbacks are not success when later XML fails; and unsafe or excessive input refuses."""

import io
import zipfile
from pathlib import Path
from xml.parsers.expat import ExpatError

import pytest

from spicy_docs.sources.uscode import USLM_NAMESPACE, UsCodeSourceError
from spicy_docs.sources.uscode.structure import scan_uscode_structure

FIXTURES = Path(__file__).parent / "fixtures" / "uscode"


def test_complete_publisher_title_keeps_unidentified_sections_and_native_structure():
    with zipfile.ZipFile(io.BytesIO((FIXTURES / "xml_usc01@119-103.zip").read_bytes())) as archive:
        body = archive.read("usc01.xml")
    sections, parts, chapters = [], [], []
    counts = scan_uscode_structure(
        body, on_section=sections.append, on_section_part=parts.append, on_chapter=chapters.append
    )
    assert (counts.sections, counts.section_parts, counts.chapters) == (53, 31, 3)
    assert sum(row.identifier is None for row in sections) == 14
    first = sections[0]
    assert first.identifier == "/us/usc/t1/s1"
    assert first.status is None
    assert first.numbers[0].element.attributes["value"] == "1"
    assert first.numbers[0].text == "§\u202f1."
    assert first.headings[0].text == " Words denoting number, gender, and so forth"
    assert parts[0].identifier_pieces[0].section_part == "a"
    assert parts[0].element.tag == "{" + USLM_NAMESPACE + "}subsection"
    assert chapters[0].identifier_pieces[0].chapter == "1"


def test_publisher_range_list_chapter_and_unidentified_appendix_fragments_survive():
    sections, chapters = [], []
    scan_uscode_structure(
        (FIXTURES / "structure-observations.xml").read_bytes(), on_section=sections.append, on_chapter=chapters.append
    )
    span = sections[0].identifier_pieces[0]
    assert (span.section, span.range_start, span.range_end) == ("1...1j", "1", "1j")
    assert sections[0].status == "repealed"
    assert [piece.section for piece in sections[1].identifier_pieces] == ["3", "4"]
    assert chapters[0].identifier_pieces[0].raw == "/us/usc/t10/stA/ptI/ch1"
    assert chapters[0].identifier_pieces[0].chapter == "1"
    assert sections[2].identifier is None and sections[2].status == "transferred"
    assert sections[2].numbers[0].text == "[§\u202f1."
    assert chapters[1].identifier_pieces[0].raw == "/us/usc/t14/stI/ch1"
    assert chapters[1].identifier_pieces[0].kind == "chapter"
    assert chapters[1].identifier_pieces[0].chapter == "1"
    assert chapters[1].headings[0].text == "ESTABLISHMENT AND DUTIES"


def test_literal_appendix_case_dashes_ranges_unknowns_and_element_kind_are_retained():
    body = """<uscDoc><appendix><chapter identifier="/us/usc/t5A/ch1...3">
      <section identifier="/us/usc/t5A/s7A–1 unrecognized" status="publisher-new-status">
      <num value="7A–1">[§7A–1.</num><heading> Raw <b>heading</b> ]</heading>
      <paragraph identifier="/us/usc/t5A/s7A–1/B"><num>(B)</num></paragraph>
      <subparagraph identifier="/us/usc/t5A/s7A–1/B/i"/>
      </section></chapter></appendix></uscDoc>""".encode()
    sections, parts, chapters = [], [], []
    scan_uscode_structure(body, on_section=sections.append, on_section_part=parts.append, on_chapter=chapters.append)
    assert len(parts) == 1 and parts[0].element.tag == "paragraph"
    assert parts[0].identifier_pieces[0].section_part == "B"
    assert parts[0].element.source_xpath == "/*[1]/*[1]/*[1]/*[1]/*[3]"
    assert parts[0].ancestors[1].tag == "appendix"
    piece, unknown = sections[0].identifier_pieces
    assert (piece.title, piece.appendix, piece.section) == ("5A", True, "7A–1")
    assert unknown.raw == "unrecognized" and unknown.kind is None
    assert sections[0].status == "publisher-new-status"
    assert sections[0].headings[0].text == " Raw heading ]"
    assert (chapters[0].identifier_pieces[0].range_start, chapters[0].identifier_pieces[0].range_end) == ("1", "3")


def test_fragments_and_foreign_namespace_elements_do_not_change_source_vocabulary():
    sections = []
    body = b'<root xmlns:x="urn:foreign"><x:section identifier="/us/usc/t1/s2"/><section/></root>'
    counts = scan_uscode_structure(body, on_section=sections.append)
    assert counts.sections == 1 and len(sections) == 1
    assert sections[0].element.source_xpath == "/*[1]/*[2]"


def test_a_heading_identifier_does_not_capture_following_section_body_as_heading_text():
    sections, parts = [], []
    body = b"""<section identifier="/us/usc/t1/s1">
      <num identifier="/us/usc/t1/s1/n">1</num>
      <heading identifier="/us/usc/t1/s1/h">Title <b>here</b></heading>
      <content>Body belongs outside the heading.</content>
    </section>"""
    scan_uscode_structure(body, on_section=sections.append, on_section_part=parts.append)
    assert len(parts) == 2
    assert [part.element.tag for part in parts] == ["num", "heading"]
    assert sections[0].numbers[0].text == "1"
    assert sections[0].headings[0].text == "Title here"


def test_longer_native_scope_markers_do_not_become_sections_or_section_parts():
    body = b"""<uscDoc>
      <chapter identifier="/us/usc/t14/stI/ch1"/>
      <chapter identifier="/us/usc/t14/schI/ch1"/>
      <chapter identifier="/us/usc/t14/sptI/ch1"/>
      <chapter identifier="/us/usc/t14/spI/ch1"/>
      <chapter identifier="/us/usc/t14/sdI/ch1"/>
      <chapter identifier="/us/usc/t14/sTI/ch1"/>
      <chapter identifier="/us/usc/t14/sCHI/ch1"/>
      <chapter identifier="/us/usc/t14/sPI/ch1"/>
      <chapter identifier="/us/usc/t14/sDI/ch1"/>
      <part identifier="/us/usc/t14/stI/ptA"/>
      <paragraph identifier="/us/usc/t14/s1/ch1"/>
      <paragraph identifier="/us/usc/t14/sa/ch1"/>
      <section identifier="/us/usc/t14/sa"/>
      <section identifier="/us/usc/t14/stI /us/usc/t14/schI /us/usc/t14/sptI /us/usc/t14/spI /us/usc/t14/sdI"/>
    </uscDoc>"""
    chapters, parts, sections = [], [], []
    scan_uscode_structure(body, on_chapter=chapters.append, on_section_part=parts.append, on_section=sections.append)
    assert len(chapters) == 9 and all(row.identifier_pieces[0].kind == "chapter" for row in chapters)
    assert chapters[5].identifier_pieces[0].raw == "/us/usc/t14/sTI/ch1"
    assert [(row.identifier_pieces[0].section, row.identifier_pieces[0].section_part) for row in parts] == [
        ("1", "ch1"),
        ("a", "ch1"),
    ]
    assert sections[0].identifier_pieces[0].kind == "section"
    assert sections[0].identifier_pieces[0].section == "a"
    assert [piece.raw for piece in sections[1].identifier_pieces] == [
        "/us/usc/t14/stI",
        "/us/usc/t14/schI",
        "/us/usc/t14/sptI",
        "/us/usc/t14/spI",
        "/us/usc/t14/sdI",
    ]
    assert all(piece.kind is None for piece in sections[1].identifier_pieces)


@pytest.mark.parametrize(
    "body,message",
    [
        (b'<!DOCTYPE root [<!ENTITY e "bad">]><root/>', "DOCTYPE"),
        (b"<root><section>", "malformed"),
        (b"", "empty"),
        (b"<section><heading>" + b"x" * 65537 + b"</heading></section>", "65,536"),
    ],
)
def test_structure_refuses_unsafe_incomplete_and_excessive_fields(body, message):
    with pytest.raises(UsCodeSourceError, match=message):
        scan_uscode_structure(body, on_section=lambda row: None)


def test_partial_callbacks_are_not_a_success_when_later_xml_fails():
    rows = []
    with pytest.raises(UsCodeSourceError, match="malformed"):
        scan_uscode_structure(b'<root><section identifier="/us/usc/t1/s1"/><broken>', on_section=rows.append)
    assert len(rows) == 1
    with pytest.raises(UsCodeSourceError):
        scan_uscode_structure(b"<section/>", max_bytes=2)
    with pytest.raises(UsCodeSourceError, match="callable"):
        scan_uscode_structure(b"<section/>", on_section=123)


@pytest.mark.parametrize("error_type", [ValueError, ExpatError])
def test_valid_xml_preserves_a_sink_error_instead_of_claiming_malformed_input(error_type):
    error = error_type("sink rejected this row")

    def reject(row):
        raise error

    with pytest.raises(error_type) as caught:
        scan_uscode_structure(b'<section identifier="/us/usc/t1/s1"/>', on_section=reject)
    assert caught.value is error
