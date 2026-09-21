"""Publisher metadata remains usable without losing its original structure."""

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

import pytest

from spicy_docs.sources.govinfo import GovInfoModsError, parse_govinfo_mods

FIXTURE = Path(__file__).parent / "fixtures/govinfo/cfr-mods-excerpt.xml"
BODY = FIXTURE.read_bytes()
NS = "http://www.loc.gov/mods/v3"
XML = "http://www.w3.org/XML/1998/namespace"
XLINK = "http://www.w3.org/1999/xlink"


def mods(content: str, attrs: str = "") -> bytes:
    """Parse the fixture MODS body."""
    return f'<mods xmlns="{NS}" {attrs}>{content}</mods>'.encode()


def test_publisher_package_and_constituents_are_mapped_with_source_provenance():
    """The publisher package and constituents map with source digests, byte size and element count."""
    mapped = parse_govinfo_mods(BODY)
    package = mapped.package
    assert mapped.source_sha256 == "sha256:" + hashlib.sha256(BODY).hexdigest()
    assert mapped.source_byte_size == 15418
    assert mapped.element_count == 203
    assert package.element.attribute("version") == "3.3"
    assert package.titles[0].findall(f"{{{NS}}}title")[0].text == "General Provisions"
    assert [x.text for x in package.titles[0].findall(f"{{{NS}}}partNumber")] == ["Title 1", "Volume 1"]
    assert len(package.names) == 2
    assert package.origins[0].findall(f"{{{NS}}}dateIssued")[0].attribute("encoding") == "w3cdtf"
    assert package.languages[0].findall(f"{{{NS}}}languageTerm")[0].text == "eng"
    assert package.record_info[0].findall(f"{{{NS}}}recordChangeDate")[0].text == "2025-11-19"
    assert len(package.extensions) == 2 and len(package.locations) == 1
    assert package.preferred_citations[0].text.endswith("January 1, 2025")
    assert [item.element.attribute("type") for item in package.related_items] == [
        "host",
        "constituent",
        "constituent",
        "constituent",
    ]
    part, section, chapter = mapped.constituents
    assert section.parent_ids[0].text == part.element.attribute("ID")
    assert section.preferred_citations[0].text == "1 CFR § 1.1"
    assert section.fields("extension", "granuleNumber")[0].text == "§ 1.1 "
    assert [url.attribute("displayLabel") for url in section.urls] == [
        "Content Detail",
        "PDF rendition",
        "XML rendition",
    ]
    assert section.element.attribute(f"{{{XLINK}}}href").endswith("/mods.xml")
    assert section.fields("extension", "fr", "pages")[1].attribute("pages") == "12466"
    assert part.fields("extension", "authority")[0].text.startswith("44 U.S.C. 1506;")
    assert chapter.fields("extension", "granuleLabel")[0].text == "chapter"
    assert chapter.fields("extension", "cfr", "part")[0].attribute("number") == "VI"
    assert not chapter.fields("extension", "cfr", "chapter")  # Do not repair publisher hints.
    # These parents were deliberately omitted from the bounded excerpt.
    assert chapter.parent_ids[0].text == "id-CFR-2025-title1-vol1"


def test_entire_excerpt_matches_an_independent_xml_tree():
    """The entire excerpt matches an independent XML tree, including unmodeled fields."""
    mapped = parse_govinfo_mods(BODY)

    def compare(source, actual, path):
        assert actual.name == source.tag
        assert dict(actual.attributes) == source.attrib
        assert actual.path == path
        assert actual.text == "".join(source.itertext())
        expected = []
        if source.text:
            expected.append(source.text)
        for index, child in enumerate(source, 1):
            expected.append(child)
            compare(child, actual.children[index - 1], (*path, index))
            if child.tail:
                expected.append(child.tail)
        assert len(expected) == len(actual.content)
        for left, right in zip(expected, actual.content, strict=True):
            assert (left if isinstance(left, str) else left.tag) == (right if isinstance(right, str) else right.name)

    compare(ET.fromstring(BODY), mapped.package.element, (1,))


def test_repeated_partial_dates_roles_and_unknown_values_are_not_coerced():
    """Repeated, partial, unknown and empty values are not coerced or repaired."""
    package = parse_govinfo_mods(
        mods("""
      <originInfo><dateIssued encoding="w3cdtf" point="start" qualifier="approximate">2020</dateIssued>
        <dateIssued point="end">2021-03</dateIssued></originInfo>
      <originInfo><dateOther type="local" encoding="future">around spring</dateOther></originInfo>
      <recordInfo><recordChangeDate>yesterday</recordChangeDate></recordInfo>
      <recordInfo><recordChangeDate>2026</recordChangeDate></recordInfo>
      <identifier type="Parent Id">same</identifier><identifier type="Parent Id">same</identifier>
      <subject authority="future"><topic>Literal topic</topic></subject>
      <note type="future">  Keep space.  </note><note/>
      <extension><isCoverOnly>maybe</isCoverOnly><newField code="007">0001</newField></extension>
    """)
    ).package
    dates = package.fields("originInfo", "dateIssued")
    assert [x.text for x in dates] == ["2020", "2021-03"]
    assert dict(dates[0].attributes) == {"encoding": "w3cdtf", "point": "start", "qualifier": "approximate"}
    assert len(package.origins) == 2 and len(package.record_info) == 2
    assert [x.text for x in package.parent_ids] == ["same", "same"]
    assert package.subjects[0].attribute("authority") == "future"
    assert [x.text for x in package.notes] == ["  Keep space.  ", ""]
    assert package.fields("extension", "isCoverOnly")[0].text == "maybe"
    assert package.fields("extension", "newField")[0].text == "0001"


def test_unknown_namespaces_mixed_text_and_inherited_context_survive_json():
    """Unknown namespaces, mixed text and inherited context survive JSON without deduplication."""
    body = mods(
        """<extension><g:item xmlns:g="urn:inner" xsi:type="g:Type">Before <g:b/> after &amp; <![CDATA[<end>]]>.</g:item>
      <g:item>outer</g:item><item>mods</item><item xmlns="">none</item></extension>
      <relatedItem type="constituent" ID="duplicate"><location><url>../raw.xml</url></location>
        <relatedItem type="constituent" ID="nested"/></relatedItem>
      <relatedItem type="constituent" ID="duplicate"/>
      """,
        'xmlns:g="urn:outer" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xml:base="https://example.test/base/" xml:lang="en" xml:space="preserve"',
    )
    mapped = parse_govinfo_mods(body)
    package = mapped.package
    assert dict(package.element.namespace_declarations)["g"] == "urn:outer"
    assert package.element.attribute(f"{{{XML}}}base") == "https://example.test/base/"
    assert package.element.attribute(f"{{{XML}}}lang") == "en"
    assert package.element.attribute(f"{{{XML}}}space") == "preserve"
    inner = package.fields("extension", "{urn:inner}item")[0]
    assert inner.path == (1, 1, 1)
    assert inner.namespace_declarations == (("g", "urn:inner"),)
    assert inner.attribute("{http://www.w3.org/2001/XMLSchema-instance}type") == "g:Type"
    assert inner.text == "Before  after & <end>."
    assert inner.content[0] == "Before " and inner.content[2] == " after & <end>."
    assert package.fields("extension", "{urn:outer}item")[0].text == "outer"
    assert package.fields("extension", "item")[0].text == "mods"
    assert package.fields("extension", "{}item")[0].text == "none"
    assert package.extensions[0].children[-1].name == "item"
    assert package.extensions[0].children[-1].namespace_declarations == (("", ""),)
    assert len(mapped.constituents) == 2  # No flattening or ID-based deduplication.
    first = mapped.constituents[0]
    assert first.urls[0].text == "../raw.xml"  # No resolution or fetching.
    assert first.related_items[0].element.attribute("ID") == "nested"
    assert first.element is package.related_items[0].element
    output = json.loads(json.dumps(asdict(mapped), ensure_ascii=False))
    assert "constituents" not in output
    assert output["package"]["element"]["content"][0]["content"][0]["content"][2] == " after & <end>."


def test_chunk_boundaries_and_entities_do_not_split_mapped_text():
    """Decoder chunk boundaries and entities do not split mapped text."""
    value = "a" * 70_000 + "&amp;" * 1000 + "z" * 70_000
    node = parse_govinfo_mods(mods(f"<note>{value}</note>")).package.notes[0]
    assert node.content == ("a" * 70_000 + "&" * 1000 + "z" * 70_000,)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html/>",
        b"<mods/>",
        mods("")[:-2],
        b'<!DOCTYPE mods SYSTEM "https://example.test/mods.dtd">' + mods(""),
        b'<!DOCTYPE mods [<!ENTITY x "injected">]>' + mods("&x;"),
        mods("&unknown;"),
        mods("<extension>" * 64 + "</extension>" * 64),
        f'<modsCollection xmlns="{NS}"/>'.encode(),
    ],
)
def test_unsafe_malformed_or_wrong_root_xml_refuses(body):
    """Unsafe, malformed or wrong-root XML is refused."""
    with pytest.raises(GovInfoModsError):
        parse_govinfo_mods(body)


def test_byte_and_element_bounds_are_inclusive():
    """Byte and element bounds are inclusive and refuse one over."""
    assert parse_govinfo_mods(BODY, max_bytes=len(BODY), max_elements=203).element_count == 203
    with pytest.raises(GovInfoModsError, match="max_bytes"):
        parse_govinfo_mods(BODY, max_bytes=len(BODY) - 1)
    with pytest.raises(GovInfoModsError, match="max_elements"):
        parse_govinfo_mods(BODY, max_elements=202)
    for invalid in (True, 0, -1, 1.1):
        with pytest.raises(GovInfoModsError, match="max_elements"):
            parse_govinfo_mods(BODY, max_elements=invalid)
