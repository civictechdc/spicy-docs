"""Whole retained PREMIS XML and mutations preserve raw groups before selection."""

import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from spicy_docs.sources.govinfo.mods import GovInfoModsError, parse_govinfo_mods
from spicy_docs.sources.govinfo.premis import PREMIS_NAMESPACE, GovInfoPremisError, read_govinfo_premis
from tests import govinfo_mods_oracle as old_mods

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (FIXTURES / "govinfo_premis/cfr-2023-title1-vol1-premis-2026-09-15.xml").read_bytes()
P = "{" + PREMIS_NAMESPACE + "}"


def premis(content, attributes=""):
    return f'<premis xmlns="{PREMIS_NAMESPACE}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" {attributes}>{content}</premis>'.encode()


def compare_tree(source, actual, path=(1,)):
    assert actual.name == source.tag
    assert dict(actual.attributes) == source.attrib
    assert actual.path == path
    assert actual.leading_text == source.text
    assert actual.text == "".join(source.itertext())
    assert len(actual.children) == len(source)
    expected = []
    if source.text:
        expected.append(source.text)
    for index, child in enumerate(source, 1):
        expected.append(child.tag)
        compare_tree(child, actual.children[index - 1], (*path, index))
        if child.tail:
            expected.append(child.tail)
    assert [item if isinstance(item, str) else item.name for item in actual.content] == expected


def test_complete_retained_source_keeps_all_objects_events_agents_and_raw_fields():
    result = read_govinfo_premis(BODY)
    source = ET.fromstring(BODY)
    compare_tree(source, result.element)
    assert result.source_sha256 == "sha256:2e6e84ab8c95f0ee904053ea6485896a88fcb81e03bfce482b6ed36fc53e80ba"
    assert result.source_byte_size == 179574
    assert result.element_count == sum(1 for _ in source.iter())
    assert len(result.objects) == 46
    assert Counter(obj.object_type for obj in result.objects) == {"file": 33, "representation": 13}
    assert sum(not obj.fixities for obj in result.objects if obj.object_type == "file") == 30
    assert sum(len(obj.fixities) for obj in result.objects) == 3
    assert result.element.attribute("version") == "2.0"
    xml_file = next(
        obj for obj in result.objects if any(n.text == "CFR-2023-title1-vol1.xml" for n in obj.original_names)
    )
    assert xml_file.identifiers[0].findall(P + "objectIdentifierValue")[0].text == "D09002ee1e746227e"
    assert (
        xml_file.fixities[0].findall(P + "messageDigest")[0].text
        == "933d9cf35c4342d4d55cd4dc771a73b46a0c8f88423b935da470ad5862d13e0d"
    )
    assert xml_file.fields("storage", "contentLocation", "contentLocationValue")[0].text == (
        "Public Access Rendition https://www.govinfo.gov/content/pkg/CFR-2023-title1-vol1/xml/CFR-2023-title1-vol1.xml"
    )


def test_repeated_missing_empty_and_unknown_metadata_survives_without_validation():
    body = premis(
        """
      <object xsi:type="file">
        <objectIdentifier/><objectIdentifier><objectIdentifierType>Future</objectIdentifierType>
          <objectIdentifierValue>  repeated  </objectIdentifierValue><objectIdentifierValue/></objectIdentifier>
        <objectCharacteristics><compositionLevel>unknown</compositionLevel><fixity/>
          <fixity><messageDigestAlgorithm>future</messageDigestAlgorithm><messageDigest>not hex</messageDigest></fixity>
          <size>unknown</size><format><new>raw</new></format></objectCharacteristics>
        <objectCharacteristics><fixity/><compositionLevel>1</compositionLevel></objectCharacteristics>
        <originalName/><originalName>literal</originalName><storage/><storage><contentLocation/></storage>
        <extension xmlns:q="urn:inner" q:attr="01">before<q:item xsi:type="q:Future"/>after &amp;<![CDATA[<literal>]]></extension>
        <bare xmlns="">none</bare>
      </object><object/><object xsi:type="future"/><event><unknown/></event>
    """,
        'xmlns:q="urn:outer" version="future"',
    )
    result = read_govinfo_premis(body)
    compare_tree(ET.fromstring(body), result.element)
    first = result.objects[0]
    assert len(first.identifiers) == 2 and len(first.characteristics) == 2
    assert len(first.fixities) == 3 and len(first.original_names) == 2 and len(first.storage) == 2
    assert first.fields("objectIdentifier", "objectIdentifierValue")[1].leading_text is None
    assert len(result.objects) == 3 and result.objects[1].fixities == ()
    assert first.fields("{}bare")[0].text == "none"
    extension = first.fields("extension")[0]
    assert extension.namespace_declarations == (("q", "urn:inner"),)
    assert dict(result.element.namespace_declarations)["q"] == "urn:outer"
    assert extension.children[0].name == "{urn:inner}item"
    assert extension.text == "beforeafter &<literal>"
    assert extension.leading_text == "before"
    assert extension.path == (1, 1, 9)
    json.dumps(asdict(result), ensure_ascii=False)


def test_empty_root_is_an_empty_observation_and_nested_objects_remain_in_raw_tree():
    assert read_govinfo_premis(premis("")).objects == ()
    result = read_govinfo_premis(premis("<extension><object/></extension>"))
    assert result.objects == ()
    assert len(result.element.findall(P + "extension", P + "object")) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html/>",
        b"<premis/>",
        b'<premis xmlns="http://www.loc.gov/premis/v3"/>',
        premis("<object>")[:-1],
        premis("&undefined;"),
        b'<!DOCTYPE premis SYSTEM "https://example.org/source.dtd">' + premis(""),
        b'<!DOCTYPE premis [<!ENTITY x "injected">]>' + premis("&x;"),
    ],
)
def test_unsafe_malformed_wrong_namespace_and_premis3_refuse(body):
    with pytest.raises(GovInfoPremisError):
        read_govinfo_premis(body)


@pytest.mark.parametrize(
    "option,value", [("max_bytes", True), ("max_elements", 0), ("max_depth", -1), ("max_elements", 1.5)]
)
def test_invalid_limits_use_source_error(option, value):
    with pytest.raises(GovInfoPremisError):
        read_govinfo_premis(BODY, **{option: value})


def test_unknown_elements_depth_and_byte_bounds_are_inclusive():
    body = premis("<unknown><other/></unknown>")
    assert read_govinfo_premis(body, max_elements=3, max_bytes=len(body), max_depth=3).element_count == 3
    for options in ({"max_elements": 2}, {"max_depth": 2}, {"max_bytes": len(body) - 1}):
        with pytest.raises(GovInfoPremisError):
            read_govinfo_premis(body, **options)


def test_decoder_chunk_boundaries_do_not_change_leading_or_descendant_text():
    text = "a" * 70000 + "&amp;" * 1000
    result = read_govinfo_premis(premis(f"<object><originalName>{text}<part/>tail</originalName></object>"))
    element = result.objects[0].original_names[0]
    assert element.leading_text == "a" * 70000 + "&" * 1000
    assert element.text == element.leading_text + "tail"
    assert len(element.content) == 3


MODS = (FIXTURES / "govinfo/cfr-mods-excerpt.xml").read_bytes()


@pytest.mark.parametrize(
    "body",
    [
        MODS,
        MODS.replace(b"</mods>", b'<note>before<x xmlns="urn:foreign"/> after &amp;</note></mods>'),
        MODS.replace(b"</mods>", b"<relatedItem/><relatedItem/><note/></mods>"),
        MODS.replace(b"2025-11-19", b"future date"),
        b"<html/>",
        MODS[:-3],
        b'<!DOCTYPE mods [<!ENTITY x "bad">]>' + MODS,
    ],
)
def test_mods_data_and_refusals_match_frozen_mapper_after_tree_promotion(body):
    try:
        old = old_mods.parse_govinfo_mods(body)
    except old_mods.GovInfoModsError:
        with pytest.raises(GovInfoModsError):
            parse_govinfo_mods(body)
    else:
        assert asdict(parse_govinfo_mods(body)) == asdict(old)


def test_premis_and_xml_tree_import_without_httpx():
    code = """
import importlib.abc
import sys
class NoHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'httpx' or fullname.startswith('httpx.'):
            raise AssertionError('raw parser imported HTTPX')
sys.meta_path.insert(0, NoHttpx())
from spicy_docs.sources.govinfo.premis import read_govinfo_premis, compare_govinfo_premis
from spicy_docs.sources.xml_tree import XmlTreeElement
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
