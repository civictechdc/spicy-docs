"""Known source excerpts and counterexamples for raw AUTH metadata capture.

Pins exact text runs and source scope, structural heads and sources,
whitespace/entity/parser-chunk fidelity, namespace handling, provisional
callbacks, and the byte, depth, observation and text bounds with their refusals.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers.expat import ExpatError

import pytest

from spicy_docs.sources.cfr.authority import scan_ecfr_authority_notes
from spicy_docs.sources.cfr.models import CfrSourceError

FIXTURES = Path(__file__).parent / "fixtures" / "cfr"


@pytest.mark.parametrize("title,part,division", [(1, "18", "DIV5"), (5, "550", "DIV6")])
def test_retained_authority_keeps_source_scope_and_exact_text(title, part, division):
    """A retained authority keeps its exact text, runs, nearest part and division, plus input digests and counts."""
    path = FIXTURES / f"ecfr-authority-title{title}-part{part}.xml"
    body = path.read_bytes()
    authority, headings, sources, parts = [], [], [], []
    result = scan_ecfr_authority_notes(
        body,
        on_authority=authority.append,
        on_heading=headings.append,
        on_source=sources.append,
        on_part=parts.append,
    )
    raw = ET.fromstring(body)
    expected = next(raw.iter("AUTH"))
    assert authority[0].text == "".join(expected.itertext())
    assert "".join(authority[0].text_runs) == authority[0].text
    assert "Authority:" in authority[0].text_runs
    assert authority[0].nearest_part.attributes["N"] == part
    assert authority[0].nearest_division.tag == division
    assert result.input_sha256 == hashlib.sha256(body).hexdigest()
    assert result.input_bytes == len(body)
    assert result.parts == len(parts) == 1
    assert result.authorities == len(authority) == 1
    assert result.sources == len(sources) == 1
    assert result.headings == len(headings) == (1 if title == 1 else 2)
    provenance = next(
        row for row in json.loads((FIXTURES / "authority-provenance.json").read_text()) if row["fixture"] == path.name
    )
    assert provenance["fixture_sha256"] == result.input_sha256


def test_retained_scope_mutation_does_not_invent_part_or_authority():
    """A renamed scope mutation invents no part or authority, keeping ancestors and divisions literal."""
    body = (FIXTURES / "ecfr-authority-title5-part550.xml").read_bytes()
    notes = []
    result = scan_ecfr_authority_notes(body.replace(b'TYPE="PART"', b'TYPE="UNKNOWN"'), on_authority=notes.append)
    assert result.parts == 0
    assert notes[0].nearest_part is None
    assert notes[0].ancestors[0].attributes["TYPE"] == "UNKNOWN"
    assert notes[0].nearest_division.attributes["N"] == "A"
    renamed = body.replace(b"<AUTH>", b"<SECAUTH>").replace(b"</AUTH>", b"</SECAUTH>")
    assert scan_ecfr_authority_notes(renamed).authorities == 0


def test_existing_bulk_fixture_uses_the_same_source_reader():
    """The existing bulk fixture reads through the same source reader with its root and notes."""
    body = (FIXTURES / "ecfr-bulk-title1.xml").read_bytes()
    notes = []
    result = scan_ecfr_authority_notes(body, on_authority=notes.append)
    expected = ["".join(element.itertext()) for element in ET.fromstring(body).iter("AUTH")]
    assert result.root_tag == "DLPSTEXTCLASS"
    assert [note.text for note in notes] == expected
    assert expected


def test_empty_multiple_nested_and_orphan_notes_are_observations():
    """Empty, multiple, nested and orphan notes are observations with exact nearest scopes."""
    body = b"""<ECFR><AUTH/><DIV5 TYPE="PART" N="outer"><AUTH>A<AUTH>B</AUTH>C</AUTH>
    <DIV5 TYPE="PART"><AUTH> inner </AUTH></DIV5><AUTH/></DIV5>
    <DIV5 TYPE="PART" N="none"/><PART/><PARAUTH>outside</PARAUTH><SECAUTH>outside</SECAUTH></ECFR>"""
    parts, notes = [], []
    result = scan_ecfr_authority_notes(body, on_part=parts.append, on_authority=notes.append)
    assert result.parts == 3
    assert result.authorities == 5
    assert [note.text for note in notes] == ["", "B", "ABC", " inner ", ""]
    assert notes[0].nearest_part is None
    assert notes[0].nearest_division is None
    assert notes[1].nearest_part.attributes["N"] == "outer"
    assert notes[2].text_runs == ("A", "B", "C")
    assert notes[3].nearest_part.attributes == {"TYPE": "PART"}
    assert notes[3].nearest_part.source_xpath == "/*[1]/*[2]/*[2]"
    assert parts[-1].element.attributes["N"] == "none"


def test_structural_heads_and_sources_keep_actual_context():
    """Structural heads and sources keep their actual division, part and ancestor context."""
    body = b"""<root><HEAD>orphan</HEAD><DIV5 TYPE="PART" N="7"><HEAD>part</HEAD>
    <DIV6 TYPE="SUBPART" N="A"><HEAD>subpart<E> title</E></HEAD><AUTH a="x">authority</AUTH>
    <DIV8 TYPE="SECTION" N="7.1"><HEAD>section</HEAD><SOURCE>section source</SOURCE>
    <P><HEAD>inline</HEAD></P></DIV8></DIV6><DIV class="table"><HEAD>table</HEAD></DIV></DIV5>
    <SOURCE>orphan source</SOURCE></root>"""
    heads, notes, sources = [], [], []
    scan_ecfr_authority_notes(body, on_authority=notes.append, on_heading=heads.append, on_source=sources.append)
    assert [row.text for row in heads] == ["part", "subpart title", "section"]
    assert notes[0].element.attributes == {"a": "x"}
    assert notes[0].nearest_division.attributes["N"] == "A"
    assert sources[0].nearest_division.attributes["N"] == "7.1"
    assert sources[1].nearest_part is None
    assert [item.tag for item in notes[0].ancestors] == ["root", "DIV5", "DIV6"]


def test_text_runs_preserve_whitespace_entities_and_element_boundaries():
    """Text runs preserve whitespace, entities and element boundaries; comments and PIs add nothing while CDATA does."""
    notes = []
    body = b"<AUTH>\r\n<HED>Authority:</HED><PSPACE>A&amp;B&#32;C<E>D</E>E<BR/>F</PSPACE>\t</AUTH>"
    scan_ecfr_authority_notes(body, on_authority=notes.append)
    assert notes[0].text == "\nAuthority:A&B CDEF\t"
    assert notes[0].text_runs == ("\n", "Authority:", "A&B C", "D", "E", "F", "\t")
    # Comments/PI do not contribute source text; CDATA does, without a false gap.
    notes.clear()
    scan_ecfr_authority_notes(b"<AUTH>A<!--comment-->B<?hint x?>C<![CDATA[D]]>E</AUTH>", on_authority=notes.append)
    assert notes[0].text_runs == ("ABCDE",)


def test_parser_chunks_do_not_split_runs():
    """Parser chunk boundaries do not split text runs."""
    notes = []
    body = b"<AUTH>" + b"a" * 65530 + b"&amp;b</AUTH>"
    scan_ecfr_authority_notes(body, on_authority=notes.append)
    assert notes[0].text_runs == ("a" * 65530 + "&b",)


def test_declared_encoding_is_decoded_by_xml_parser():
    """The declared encoding is decoded by the XML parser."""
    notes = []
    scan_ecfr_authority_notes(
        b'<?xml version="1.0" encoding="ISO-8859-1"?><AUTH>\xa7</AUTH>', on_authority=notes.append
    )
    assert notes[0].text == "§"


def test_local_names_select_and_expanded_names_survive():
    """Selection uses local names while expanded names survive on elements and scopes."""
    notes = []
    scan_ecfr_authority_notes(
        b'<x:DIV5 xmlns:x="urn:source" TYPE="PART" N="x"><x:AUTH x:flag="y">raw</x:AUTH></x:DIV5>',
        on_authority=notes.append,
    )
    assert notes[0].element.tag == "{urn:source}AUTH"
    assert notes[0].element.attributes == {"{urn:source}flag": "y"}
    assert notes[0].nearest_part.tag == "{urn:source}DIV5"


def test_callback_snapshots_do_not_mutate_scanner_ancestry():
    """Callback snapshots do not mutate the scanner's ancestry."""
    notes = []

    def mutate(part):
        part.element.attributes.clear()

    scan_ecfr_authority_notes(
        b'<DIV5 TYPE="PART" N="1"><AUTH>x</AUTH></DIV5>', on_part=mutate, on_authority=notes.append
    )
    assert notes[0].nearest_part.attributes == {"TYPE": "PART", "N": "1"}


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<ECFR>",
        b"<ECFR><AUTH>x</AUTH></wrong>",
        b'<!DOCTYPE AUTH SYSTEM "file:///tmp/unread"><AUTH/>',
        b'<!DOCTYPE AUTH [<!ENTITY x "secret">]><AUTH>&x;</AUTH>',
        b"<AUTH>&unknown;</AUTH>",
        b"<AUTH>\xff</AUTH>",
    ],
)
def test_unsafe_or_malformed_xml_refuses(body):
    """Unsafe or malformed XML is refused."""
    with pytest.raises(CfrSourceError):
        scan_ecfr_authority_notes(body)


def test_callbacks_are_provisional_until_success():
    """Callbacks are provisional: a later failure discards the run."""
    notes = []
    with pytest.raises(CfrSourceError):
        scan_ecfr_authority_notes(b"<root><AUTH>seen</AUTH><bad></root>", on_authority=notes.append)
    assert len(notes) == 1


@pytest.mark.parametrize("sink", ["on_part", "on_authority", "on_heading", "on_source"])
@pytest.mark.parametrize("error_type", [ValueError, ExpatError])
def test_callback_error_keeps_original_identity(sink, error_type):
    """A callback error propagates as the same object."""
    failure = error_type("receiver failure")

    def refuse(_row):
        raise failure

    with pytest.raises(error_type) as raised:
        scan_ecfr_authority_notes(b'<DIV5 TYPE="PART"><AUTH/><HEAD/><SOURCE/></DIV5>', **{sink: refuse})
    assert raised.value is failure


@pytest.mark.parametrize("option", ["max_bytes", "max_depth", "max_observations", "max_text_characters"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_bounds_require_positive_integers(option, value):
    """Bounds must be positive integers."""
    with pytest.raises(CfrSourceError):
        scan_ecfr_authority_notes(b"<AUTH/>", **{option: value})


def test_byte_depth_observation_and_active_text_bounds():
    """Byte, depth, observation and active-text bounds each refuse on violation; only concurrently open text counts."""
    with pytest.raises(CfrSourceError, match="max_bytes"):
        scan_ecfr_authority_notes(b"<AUTH/>", max_bytes=6)
    with pytest.raises(CfrSourceError, match="depth"):
        scan_ecfr_authority_notes(b"<AUTH><AUTH/></AUTH>", max_depth=1)
    with pytest.raises(CfrSourceError, match="max_observations"):
        scan_ecfr_authority_notes(b'<DIV5 TYPE="PART"><AUTH/><HEAD/><SOURCE/></DIV5>', max_observations=3)
    with pytest.raises(CfrSourceError, match="max_text_characters"):
        scan_ecfr_authority_notes(
            b"<AUTH><AUTH>123</AUTH></AUTH>", on_authority=lambda row: None, max_text_characters=5
        )
    # Only requested, concurrently open text counts toward this buffer limit.
    scan_ecfr_authority_notes(
        b"<root><AUTH>123</AUTH><AUTH>456</AUTH></root>", on_authority=lambda row: None, max_text_characters=3
    )
    assert scan_ecfr_authority_notes(b"<AUTH>123456</AUTH>", max_text_characters=1).authorities == 1


def test_noncallable_sink_refuses_before_scan():
    """A non-callable sink refuses before the scan starts."""
    with pytest.raises(CfrSourceError, match="callable"):
        scan_ecfr_authority_notes(b"<AUTH/>", on_authority=1)
