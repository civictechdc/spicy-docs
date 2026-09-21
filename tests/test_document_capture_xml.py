"""Full structural reversibility over every retained capture and a fresh PDF adapter result.

Pins round-trip equality and re-encoding, parent-property coverage, mutation
detection by full-value comparison, exact extension types, and refusal of
unsupported values, wrong identity, malformed XML and DOCTYPEs.
"""

from __future__ import annotations

import copy
import json
import math
import re
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
    """Load one committed capture JSON."""
    return json.loads(path.read_bytes())


@pytest.fixture(scope="module")
def senate():
    """The committed fresh Senate adapter capture."""
    return load(SENATE / "senate-page17.capture.json")


def test_every_tracked_capture_and_profile_enters_the_proof():
    """Every tracked capture and profile enters the proof."""
    assert len(CAPTURES) >= 7
    assert {load(p)["profile"]["name"] for p in CAPTURES} == set(dc.load_schema("PINS.json")["profiles"])


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_full_capture_round_trip(path):
    """Every capture round-trips to identical values and re-encodes to the same XML."""
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
    """A fresh Senate adapter capture round-trips and matches the committed result on structure and observations."""
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
        derived_from=source,
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
    """Every parent property is exercised by the real fixtures or the supplement, and round-trips."""
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
        "span-ownership",
        "span-order",
        "span-reference-order",
        "heading-attachment",
        "footnote-attachment",
        "span-style",
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
    """Each XML mutation fails full equality at its named path; text concatenation would miss most of them."""
    original = optional_fields
    if mutation in {"heading-attachment", "footnote-attachment"}:
        original = load(next(p for p in CAPTURES if p.name == "fr-2026-19200.capture.json"))
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
        expected = "$/nodes/1: object properties changed"
    elif mutation == "span-order":
        spans = find("evidence")
        first = spans[0]
        spans.remove(first)
        spans.insert(1, first)
        # The supplemental first span has sha256; the second does not.
        expected = "$/evidence/0: object properties changed"
    elif mutation in {"span-ownership", "span-reference-order"}:
        owners = [
            (i, n.find(Q + "evidence")) for i, n in enumerate(find("nodes")) if n.find(Q + "evidence") is not None
        ]
        if mutation == "span-ownership":
            (index, left), (_, right) = [(i, e) for i, e in owners if len(e)][:2]
            assert left[0].text != right[0].text
            left[0].text, right[0].text = right[0].text, left[0].text
        else:
            index, left = next((i, e) for i, e in owners if len(e) > 1)
            assert left[0].text != left[1].text
            left[0].text, left[1].text = left[1].text, left[0].text
        expected = f"$/nodes/{index}/evidence/0: value changed"
    elif mutation in {"node-parent", "heading-attachment", "footnote-attachment"}:
        nodes = find("nodes")
        kind = {"node-parent": "cell", "heading-attachment": "heading", "footnote-attachment": "footnote"}[mutation]
        index, node = next((i, n) for i, n in enumerate(nodes) if n.find(Q + "kind").text == kind)
        parent = node.find(Q + "parent")
        parent_ids = {n["parent"] for n in original["nodes"]}
        # Reattach to another existing non-root parent that precedes this node.
        replacement = next(
            n.find(Q + "id").text
            for n in list(nodes)[1:index]
            if n.find(Q + "id").text in parent_ids and n.find(Q + "id").text != parent.text
        )
        assert parent.get("type") == "string"
        assert parent.text in parent_ids and parent.text != nodes[0].find(Q + "id").text
        parent.text = replacement
        expected = f"$/nodes/{index}/parent: value changed"
    elif mutation in {"cell-geometry", "cell-position", "decision"}:
        index, cell = next((i, n) for i, n in enumerate(find("nodes")) if n.find(Q + "kind").text == "cell")
        if mutation == "cell-geometry":
            source = cell.find(Q + "source")
            source.remove(source.find(Q + "box"))
            expected = f"$/nodes/{index}/source: object properties changed"
        elif mutation == "cell-position":
            cell.find(Q + "cell/" + Q + "column").text = "99"
            expected = f"$/nodes/{index}/cell/column: value changed"
        else:
            cell.find(Q + "decision/" + Q + "rule").text += " changed"
            expected = f"$/nodes/{index}/decision/rule: value changed"
    else:
        paths = {
            "extension": "profile/ext/packageId",
            "span-offset": "evidence/item/start",
            "span-style": "evidence/item/style/bold",
            "schema-pin": "schema/sha256",
            "capture-time": "capture/capturedAt",
            "artifact-digest": "artifact/sha256",
            "artifact-locator": "artifact/locator/path",
            "rendition": "rendition/textStream/normalization/statement",
            "converter": "converter/implementation/fileSha256",
            "profile-pin": "profile/schema/sha256",
            "node-depth": "nodes/item/depth",
            "node-ordinal": "nodes/item/ordinal",
            "exact-text": "evidence/item/exact",
            "unresolved": "unresolved/item/detail",
            "issue": "issues/item/detail",
        }
        element = find(paths[mutation])
        if element.get("type") == "integer":
            element.text = str(int(element.text) + 1)
        elif element.get("type") == "boolean":
            element.text = "false" if element.text == "true" else "true"
        else:
            element.set("type", "string")
            element.text = (element.text or "") + " changed"
        expected = "$/" + paths[mutation].replace("/item/", "/0/") + ": value changed"
    # These remain decodable XML; only the independent full-value comparison
    # can establish loss. Text concatenation misses most of these mutations.
    changed = decode_capture(ET.tostring(root))
    with pytest.raises(AssertionError, match="^" + re.escape(expected) + "$"):
        assert_same_value(original, changed)


def test_extension_types_keys_and_string_codepoints_are_exact(senate):
    """Extension types, keys and string code points survive exactly."""
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
    "value, reason",
    [
        (float("nan"), "non-finite numbers are not JSON values"),
        (float("inf"), "non-finite numbers are not JSON values"),
        (-float("inf"), "non-finite numbers are not JSON values"),
        (Decimal("314159.265358979"), "Decimal"),
        (("credential-sentinel",), "tuple"),
        ({1: "key"}, "object keys must be strings"),
        (b"credential-sentinel", "bytes"),
        ("\ud800", "surrogate code points are not supported; supply Unicode scalar values"),
        ("\ud800\udc00", "surrogate code points are not supported; supply Unicode scalar values"),
        ({"\ud800": "key"}, "surrogate code points are not supported; supply Unicode scalar values"),
    ],
)
def test_unsupported_values_refuse_instead_of_coercing(senate, value, reason):
    """Unsupported values refuse with the named reason instead of coercing."""
    capture = copy.deepcopy(senate)
    capture["profile"]["ext"] = {"value": value}
    if reason in {"Decimal", "tuple", "bytes"}:
        reason = (
            f"unsupported type {reason} at $/profile/ext/value; "
            "only JSON dict, list, str, int, finite float, bool and None values are supported"
        )
    with pytest.raises(CaptureXmlError) as error:
        encode_capture(capture)
    assert str(error.value) == reason


@pytest.mark.parametrize("key, token", [("value", "value"), ("a/b~c", "a~1b~0c"), ("", ""), ("非ASCII", "非ASCII")])
def test_unsupported_type_path_tracks_nested_arrays_and_escaped_keys(senate, key, token):
    """The unsupported-type path tracks nested arrays and escaped keys."""
    capture = copy.deepcopy(senate)
    capture["profile"]["ext"] = {key: [{"nested": b"credential-sentinel"}]}
    with pytest.raises(CaptureXmlError) as error:
        encode_capture(capture)
    assert str(error.value) == (
        f"unsupported type bytes at $/profile/ext/{token}/0/nested; "
        "only JSON dict, list, str, int, finite float, bool and None values are supported"
    )


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
    """A wrong capture identity refuses."""
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
    """Malformed or ambiguous XML refuses."""
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
    """DOCTYPEs refuse before entity resolution."""
    xml = encode_capture(senate).split(b"\n", 1)[1]
    with pytest.raises(CaptureXmlError, match="DTDs"):
        decode_capture(declaration.encode() + xml)


def test_malformed_xml_root_version_and_argument_refuse(senate):
    """A malformed root, wrong version or bad argument refuses."""
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
    """The comparator detects scalar values Python considers equal but that differ."""
    for left, right in [(1, True), (1, 1.0), (-0.0, 0.0), ({}, {"x": None}), ([], {})]:
        with pytest.raises(AssertionError):
            assert_same_value(left, right)
