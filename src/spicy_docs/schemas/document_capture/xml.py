"""Reversible, capture-shaped XML; no publisher vocabulary or source acquisition.

Property names and explicit JSON types preserve the whole capture, including
fields unknown to this serializer. Parent/profile validation stays with the
schema owner. See docs/research/document-capture-xml-roundtrip-2026-09-20.md
for the versioned mapping, refusal rules, and measured fixture coverage.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

NAMESPACE = "urn:spicy-docs:document-capture:xml:1"
_PREFIX = f"{{{NAMESPACE}}}"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")
# CR is legal XML but a parser normalizes it to LF. Form feeds in real PDF
# captures are illegal XML 1.0, even as character references. Escape both.
_ESCAPE_STRING = re.compile(r"[\x00-\x08\x0b-\x1f\ud800-\udfff\ufffe\uffff]")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_TYPES = {
    dict: "object",
    list: "array",
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}
_SCALARS = {"integer": int, "number": float, "boolean": bool, "null": type(None)}


class CaptureXmlError(ValueError):
    """The supplied value or XML cannot be represented by capture XML version 1."""


def _check_string(value: str) -> None:
    # JSON readers combine escaped surrogate pairs into one code point, so
    # passing raw Python surrogate code points would not be reversible.
    if _SURROGATE.search(value):
        raise CaptureXmlError("surrogate code points are not supported; supply Unicode scalar values")


def _check_capture(value: Any) -> None:
    if (
        type(value) is not dict
        or value.get("recordType") != "DocumentCapture"
        or type(value.get("captureVersion")) is not int
        or value["captureVersion"] != 1
    ):
        raise CaptureXmlError("expected a DocumentCapture object with integer captureVersion 1")


def _encode(element: ET.Element, value: Any, path: str = "$") -> None:
    kind = _TYPES.get(type(value))
    if kind is None:
        raise CaptureXmlError(
            f"unsupported type {type(value).__name__} at {path}; "
            "only JSON dict, list, str, int, finite float, bool and None values are supported"
        )
    element.set("type", kind)
    if kind == "object":
        for key, item in value.items():
            if type(key) is not str:
                raise CaptureXmlError("object keys must be strings")
            _check_string(key)
            if _NAME.fullmatch(key):
                child = ET.SubElement(element, key)
            else:
                child = ET.SubElement(element, "property", {"name": json.dumps(key, ensure_ascii=True)})
            # JSON Pointer escaping keeps slashes and tildes in keys unambiguous.
            token = key.replace("~", "~0").replace("/", "~1")
            _encode(child, item, f"{path}/{token}")
    elif kind == "array":
        for index, item in enumerate(value):
            _encode(ET.SubElement(element, "item"), item, f"{path}/{index}")
    elif kind == "string":
        _check_string(value)
        if _ESCAPE_STRING.search(value):
            element.set("encoding", "json")
            element.text = json.dumps(value, ensure_ascii=True)
        else:
            element.text = value
    elif kind != "null":
        if kind == "number" and not math.isfinite(value):
            raise CaptureXmlError("non-finite numbers are not JSON values")
        element.text = json.dumps(value, allow_nan=False)


def encode_capture(capture: dict[str, Any]) -> bytes:
    """Encode parsed capture JSON as UTF-8 XML without changing any field.

    Integer/float types and signed floating zero survive; number lexemes from
    the original JSON file do not enter this API. Non-JSON objects, non-finite
    floats, cycles and structures exceeding Python's recursion limit refuse.
    This is format checking, not schema or evidence validation.
    """
    _check_capture(capture)
    # A local default namespace avoids changing ElementTree's process-global
    # namespace registry (which other serializers, including CFR, also use).
    root = ET.Element("DocumentCapture", {"xmlns": NAMESPACE})
    try:
        _encode(root, capture)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    except RecursionError:
        raise CaptureXmlError("capture is cyclic or exceeds the Python recursion limit") from None
    except ValueError as exc:
        if isinstance(exc, CaptureXmlError):
            raise
        raise CaptureXmlError("capture scalar exceeds Python's supported JSON representation") from None


class _CaptureTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise CaptureXmlError("DTDs are not part of capture XML")

    def comment(self, text: str) -> None:
        raise CaptureXmlError("comments are not part of capture XML")

    def pi(self, target: str, text: str) -> None:
        raise CaptureXmlError("processing instructions are not part of capture XML")


def _json_scalar(text: str, expected: type) -> Any:
    try:
        value = json.loads(text)
    except ValueError:
        raise CaptureXmlError("invalid JSON scalar spelling") from None
    if type(value) is not expected or (expected is float and not math.isfinite(value)):
        raise CaptureXmlError("scalar does not match its declared type or is non-finite")
    if expected is str:
        _check_string(value)
    return value


def _local_name(element: ET.Element) -> str:
    if not element.tag.startswith(_PREFIX) or not _NAME.fullmatch(element.tag[len(_PREFIX) :]):
        raise CaptureXmlError("element has the wrong namespace or property-name spelling")
    return element.tag[len(_PREFIX) :]


def _whitespace(text: str | None) -> bool:
    return not text or not text.strip(" \t\r\n")


def _decode(element: ET.Element, *, named: bool = False) -> Any:
    _local_name(element)
    allowed = {"type", "encoding"} | ({"name"} if named else set())
    if element.attrib.keys() - allowed:
        raise CaptureXmlError("unknown format attribute")
    kind = element.get("type")
    if kind not in _TYPES.values():
        raise CaptureXmlError("missing or unknown value type")
    if "encoding" in element.attrib and (kind != "string" or element.get("encoding") != "json"):
        raise CaptureXmlError("encoding must be json on a string")
    if kind in {"object", "array"}:
        if not _whitespace(element.text) or any(not _whitespace(child.tail) for child in element):
            raise CaptureXmlError("mixed content is not part of capture XML")
        if kind == "array":
            if any(_local_name(child) != "item" for child in element):
                raise CaptureXmlError("array children must be item elements")
            return [_decode(child) for child in element]
        result = {}
        for child in element:
            key = _local_name(child)
            named = key == "property" and "name" in child.attrib
            if named:
                key = _json_scalar(child.attrib["name"], str)
            if key in result:
                raise CaptureXmlError("duplicate object property")
            result[key] = _decode(child, named=named)
        return result
    if len(element):
        raise CaptureXmlError("scalar values cannot have child elements")
    text = element.text or ""
    if kind == "string":
        return _json_scalar(text, str) if "encoding" in element.attrib else text
    if kind == "null":
        if text:
            raise CaptureXmlError("null must have no text")
        return None
    return _json_scalar(text, _SCALARS[kind])


def decode_capture(xml_bytes: bytes) -> dict[str, Any]:
    """Decode capture XML, refusing ambiguous or unsupported format content.

    No URL, path, schema or entity is resolved. XML container indentation and
    namespace prefixes are immaterial; all capture strings remain exact.
    Validate the returned object against its pinned parent/profile separately.
    """
    if type(xml_bytes) is not bytes:
        raise CaptureXmlError("decode_capture expects XML bytes")
    try:
        root = ET.fromstring(xml_bytes, parser=ET.XMLParser(target=_CaptureTreeBuilder()))
        if root.tag != _PREFIX + "DocumentCapture":
            raise CaptureXmlError("expected DocumentCapture in the capture XML version 1 namespace")
        capture = _decode(root)
        _check_capture(capture)
        return capture
    except ET.ParseError:
        raise CaptureXmlError("malformed capture XML") from None
    except RecursionError:
        raise CaptureXmlError("capture XML exceeds the Python recursion limit") from None


__all__ = ["NAMESPACE", "CaptureXmlError", "decode_capture", "encode_capture"]
