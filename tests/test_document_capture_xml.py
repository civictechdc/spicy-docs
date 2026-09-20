"""Full structural reversibility over every retained capture and a fresh PDF adapter result."""

from __future__ import annotations

import copy
import json
import math
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

from spicy_docs.schemas.document_capture.xml import NAMESPACE, CaptureXmlError, decode_capture, encode_capture
from tools.analysis import document_capture as dc
from tools.analysis.measure_document_capture_xml import assert_same_value, capture_paths

CAPTURES = capture_paths()
SENATE = dc.FIXTURES / "document_capture_pdf_tables"
Q = f"{{{NAMESPACE}}}"


def load(path):
    return json.loads(path.read_bytes())


@pytest.fixture(scope="module")
def senate():
    return load(SENATE / "senate-page17.capture.json")


def test_every_tracked_capture_and_profile_enters_the_proof():
    assert len(CAPTURES) >= 7
    assert {load(p)["profile"]["name"] for p in CAPTURES} == set(dc.load_schema("PINS.json")["profiles"])


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_full_capture_round_trip(path):
    original = load(path)
    xml = encode_capture(original)
    restored = decode_capture(xml)
    assert_same_value(original, restored)
    assert encode_capture(restored) == xml
    parent, profiles, _ = dc.validators()
    for capture in (original, restored):
        parent.validate(capture)
        profiles[capture["profile"]["name"]].validate(capture)
        assert dc.check_invariants(capture) == []
    # A different XML parser also accepts the emitted XML 1.0, including PDF
    # form feeds represented by JSON escapes rather than illegal XML references.
    from lxml import etree

    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    assert root.tag == Q + "DocumentCapture"


def test_fresh_senate_adapter_capture_round_trips(senate, tmp_path):
    from spicy_docs.extraction import DocumentExtractor, NativeText
    from tools.analysis.document_capture_pdf_tables import convert_senate_pages

    source = load(SENATE / "source.json")
    path = SENATE / source["fixture"]
    pdf = path.read_bytes()
    assert dc.sha256(pdf) == source["sha256"]
    pages = list(DocumentExtractor(NativeText(), tables=True).extract(pdf, media_type="application/pdf"))
    capture = convert_senate_pages(
        pages,
        pdf=pdf,
        pdf_path=path,
        package_id=source["package_id"],
        file_name=source["source_file"],
        intermediate_path=tmp_path / "evidence.json",
    ).capture()
    assert_same_value(capture, decode_capture(encode_capture(capture)))
    # Time, revision and retained paths describe this fresh run. Structure and
    # observations must still agree with the committed adapter result.
    for key in ("nodes", "evidence", "profile", "unresolved", "issues"):
        assert_same_value(senate[key], capture[key])
    cells = [n for n in capture["nodes"] if n["kind"] == "cell"]
    assert len(cells) == 19
    assert any(n["ext"]["observedText"] == "" for n in cells)
    assert any(n.get("reviewStatus") == "needs_review" for n in cells)
    assert any("box" in n["source"] for n in cells)
    assert (
        dc.sha256((SENATE / "senate-page17.evidence.json").read_bytes())
        == senate["rendition"]["intermediate"]["sha256"]
    )
    assert senate["artifact"]["sha256"] == source["sha256"]


@pytest.fixture(scope="module")
def optional_fields(senate):
    """Supplement real fixtures only for the twelve parent properties they omit."""
    capture = copy.deepcopy(senate)
    cell = next(n for n in capture["nodes"] if n["kind"] == "cell" and n["evidence"])
    cell["cell"].update(rowSpan=1, columnSpan=1)
    cell["ref"] = {"target": "urn:test:resource", "mediaType": "image/png"}
    span = next(s for s in capture["evidence"] if s["id"] == cell["evidence"][0])
    span["sha256"] = dc.sha256(span["exact"])
    cell["evidence"].remove(span["id"])
    del cell["text"]
    capture["unresolved"].append(
        {
            "id": "u0001",
            "evidence": [span["id"]],
            "issue": "test-unplaced",
            "detail": "supplemental",
            "parent": cell["parent"],
        }
    )
    capture["issues"].append({"code": "test-resource", "detail": "supplemental", "node": cell["id"]})
    return capture


def test_every_parent_property_is_exercised(optional_fields):
    schema = dc.load_schema(dc.PARENT_SCHEMA)
    required_coverage = set()
    covered = set()

    def inventory(part, path="#"):
        if not isinstance(part, dict):
            return
        for key, value in part.items():
            if key == "properties":
                required_coverage.update(path + "/properties/" + k for k in value)
            if isinstance(value, dict):
                for name, child in value.items():
                    inventory(child, path + "/" + key + "/" + name)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inventory(child, path + "/" + key + "/" + str(index))

    def observe(part, value, path="#"):
        if "$ref" in part:
            path, part = part["$ref"], schema
            for key in path[2:].split("/"):
                part = part[key]
        if isinstance(value, dict):
            for key, child in part.get("properties", {}).items():
                if key in value:
                    covered.add(path + "/properties/" + key)
                    observe(child, value[key], path + "/properties/" + key)
        if isinstance(value, list) and "items" in part:
            for item in value:
                observe(part["items"], item, path + "/items")
        for keyword in ("oneOf", "anyOf"):
            for index, child in enumerate(part.get(keyword, [])):
                observe(child, value, path + "/" + keyword + "/" + str(index))

    inventory(schema)
    for capture in [*(load(p) for p in CAPTURES), optional_fields]:
        observe(schema, capture)
        assert_same_value(capture, decode_capture(encode_capture(capture)))
    assert required_coverage - covered == set()
    parent, profiles, _ = dc.validators()
    parent.validate(optional_fields)
    profiles["senate-expenditures-pdf"].validate(optional_fields)
    assert dc.check_invariants(optional_fields) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "node-order",
        "extension",
        "span-offset",
        "cell-geometry",
        "schema-pin",
        "capture-time",
        "artifact-digest",
        "artifact-locator",
        "rendition",
        "converter",
        "profile-pin",
        "node-parent",
        "node-depth",
        "node-ordinal",
        "decision",
        "exact-text",
        "cell-position",
        "unresolved",
        "issue",
    ],
)
def test_xml_mutation_fails_full_equality(optional_fields, mutation):
    original = optional_fields
    xml = encode_capture(original)
    assert_same_value(original, decode_capture(xml))
    root = ET.fromstring(xml)

    def find(path):
        element = root.find("/".join(Q + part for part in path.split("/")))
        assert element is not None, path
        return element

    if mutation == "node-order":
        nodes = find("nodes")
        first = nodes[1]
        nodes.remove(first)
        nodes.insert(2, first)
    elif mutation in {"cell-geometry", "cell-position", "decision"}:
        cell = next(n for n in find("nodes") if n.find(Q + "kind").text == "cell")
        if mutation == "cell-geometry":
            source = cell.find(Q + "source")
            source.remove(source.find(Q + "box"))
        elif mutation == "cell-position":
            cell.find(Q + "cell/" + Q + "column").text = "99"
        else:
            cell.find(Q + "decision/" + Q + "rule").text += " changed"
    else:
        paths = {
            "extension": "profile/ext/packageId",
            "span-offset": "evidence/item/start",
            "schema-pin": "schema/sha256",
            "capture-time": "capture/capturedAt",
            "artifact-digest": "artifact/sha256",
            "artifact-locator": "artifact/locator/path",
            "rendition": "rendition/textStream/normalization/statement",
            "converter": "converter/implementation/fileSha256",
            "profile-pin": "profile/schema/sha256",
            "node-parent": "nodes/item/parent",
            "node-depth": "nodes/item/depth",
            "node-ordinal": "nodes/item/ordinal",
            "exact-text": "evidence/item/exact",
            "unresolved": "unresolved/item/detail",
            "issue": "issues/item/detail",
        }
        element = find(paths[mutation])
        if element.get("type") == "integer":
            element.text = str(int(element.text) + 1)
        else:
            element.set("type", "string")
            element.text = (element.text or "") + " changed"
    # These remain decodable XML; only the independent full-value comparison
    # can establish loss. Text concatenation misses most of these mutations.
    changed = decode_capture(ET.tostring(root))
    with pytest.raises(AssertionError, match=r"\$"):
        assert_same_value(original, changed)


def test_extension_types_keys_and_string_codepoints_are_exact(senate):
    capture = copy.deepcopy(senate)
    values = [None, False, True, 0, 1, 1.0, -0.0, 2**100, 0.1, math.nextafter(0.1, 1), 5e-324, 1.7976931348623157e308]
    strings = ["", " ", "\t\n", "a\rb\r\nc", "\f", "<&>\"'", "é e\u0301 😀", "\\f", "\ufffe\uffff", "\x00"]
    capture["profile"]["ext"] = {
        "types": values + strings + [[], {}],
        "": {"$id": "id", "xml:lang": "en", "property": "literal", "item": "literal", "\r\n\t": "key"},
        "非ASCII": "key",
    }
    capture["nodes"][0]["ext"] = {"deep": [{"nested": [False, None, ""]}]}
    assert_same_value(capture, decode_capture(encode_capture(capture)))


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        Decimal("0.1"),
        (1, 2),
        {1: "key"},
        b"bytes",
        "\ud800",
        "\ud800\udc00",
        {"\ud800": "key"},
    ],
)
def test_unsupported_values_refuse_instead_of_coercing(senate, value):
    capture = copy.deepcopy(senate)
    capture["profile"]["ext"] = {"value": value}
    with pytest.raises(CaptureXmlError):
        encode_capture(capture)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        {"recordType": "DocumentCapture", "captureVersion": True},
        {"recordType": "DocumentCapture", "captureVersion": 2},
    ],
)
def test_wrong_capture_identity_refuses(value):
    with pytest.raises(CaptureXmlError):
        encode_capture(value)


@pytest.mark.parametrize(
    "content",
    [
        '<x type="string">one</x><x type="string">two</x>',
        '<x type="string">one</x><property name="&quot;x&quot;" type="string">two</property>',
        '<x type="array"><wrong type="null"/></x>',
        '<x type="string"><item type="string"/></x>',
        '<x type="object">lost</x>',
        '<x type="object"><y type="null"/>lost</x>',
        '<x type="number">NaN</x>',
        '<x type="number">1e999</x>',
        '<x type="integer">1.0</x>',
        '<x type="number">1</x>',
        '<x type="boolean">1</x>',
        '<x type="integer">01</x>',
        '<x type="null">null</x>',
        '<x type="mystery"/>',
        "<x/>",
        '<x type="string" encoding="base64">YQ==</x>',
        '<x type="string" ignored="lost"/>',
        '<x type="string" encoding="json">123</x>',
        '<x type="string" encoding="json">"\\ud800"</x>',
        '<x type="string" encoding="json">"broken</x>',
        '<x type="object" encoding="json"/>',
        '<x xmlns="urn:wrong" type="null"/>',
        '<property name="123" type="string"/>',
        '<x name="&quot;y&quot;" type="null"/>',
        '<x type="array"><item name="&quot;y&quot;" type="null"/></x>',
        "<!-- lost -->",
        "<?lost information?>",
    ],
)
def test_malformed_or_ambiguous_xml_refuses(content):
    xml = (
        f'<DocumentCapture xmlns="{NAMESPACE}" type="object">'
        '<recordType type="string">DocumentCapture</recordType><captureVersion type="integer">1</captureVersion>'
        + content
        + "</DocumentCapture>"
    ).encode()
    with pytest.raises(CaptureXmlError):
        decode_capture(xml)


@pytest.mark.parametrize(
    "declaration",
    ['<!DOCTYPE DocumentCapture SYSTEM "file:///never-read">', '<!DOCTYPE DocumentCapture [<!ENTITY x "expanded">]>'],
)
def test_doctype_refuses_before_entity_resolution(senate, declaration):
    xml = encode_capture(senate).split(b"\n", 1)[1]
    with pytest.raises(CaptureXmlError, match="DTDs"):
        decode_capture(declaration.encode() + xml)


def test_malformed_xml_root_version_and_argument_refuse(senate):
    xml = encode_capture(senate)
    for broken in [
        b"<",
        xml.replace(NAMESPACE.encode(), b"urn:other"),
        xml.replace(b"DocumentCapture", b"Other"),
        xml.replace(b'<captureVersion type="integer">1', b'<captureVersion type="integer">2'),
        xml.decode(),
    ]:
        with pytest.raises(CaptureXmlError):
            decode_capture(broken)


def test_comparator_detects_python_equal_but_different_scalar_values():
    for left, right in [(1, True), (1, 1.0), (-0.0, 0.0), ({}, {"x": None}), ([], {})]:
        with pytest.raises(AssertionError):
            assert_same_value(left, right)
