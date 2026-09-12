"""Validate a publisher XML document without rewriting its bytes.

The canonical URL binds the publication date; FRDOC proves the document number.
The printed filing date is a different fact and is not used as publication time.
Validation checks identity and XML shape, not the complete publisher schema.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from xml.parsers import expat

from .body_sources import (
    FederalRegisterBodySourceError,
    _validated_max_bytes,
    _validated_publication_date,
    _validated_source_id,
)

_DOCUMENT_TYPES = frozenset({"RULE", "PRORULE", "NOTICE", "PRESDOCU"})
_FRDOC_MARKER = re.compile(
    r"\s*\[FR Doc\.\s+(?P<number>[A-Za-z0-9][A-Za-z0-9.-]{0,127})"
    r"(?P<ending>\s+Filed[^\[\]]*\]|\s*\]|\s*)\s*\Z"
)


@dataclass(frozen=True, slots=True)
class PublisherXmlIdentity:
    """An exact FRDOC number, with the publication date bound to its URL."""

    source_document_number: str
    marker_document_number: str
    publication_date: str
    document_type: str
    match_kind: Literal["publisher-document-number"] = "publisher-document-number"


def publisher_xml_locator(document_number: str, publication_date: str) -> str:
    """Return the canonical full-document XML URL for this source record."""

    source_id = _validated_source_id(document_number, label="document_number")
    safe_date = _validated_publication_date(publication_date)
    return f"https://www.federalregister.gov/documents/full_text/xml/{safe_date.replace('-', '/')}/{source_id}.xml"


class _PublisherXmlHandler:
    """Keep only the root type and one leaf's text while Expat visits the body."""

    def __init__(self) -> None:
        self.depth = 0
        self.document_type = ""
        self.marker_count = 0
        self.marker_depth: int | None = None
        self.marker_text: list[str] = []
        self.filed_depth: int | None = None
        self.filed_text: list[str] = []
        self.next_sibling_depth: int | None = None

    def start(self, name: str, _attributes: Mapping[str, str]) -> None:
        self.depth += 1
        if self.depth == 1:
            if name not in _DOCUMENT_TYPES:
                raise FederalRegisterBodySourceError("publisher XML document root is unsupported")
            self.document_type = name
        elif name in _DOCUMENT_TYPES:
            raise FederalRegisterBodySourceError("publisher XML nests document roots")
        if self.marker_depth is not None or self.filed_depth is not None:
            raise FederalRegisterBodySourceError("publisher XML FRDOC and paired FILED must be leaf elements")
        if self.next_sibling_depth is not None:
            if self.depth == self.next_sibling_depth and name == "FILED":
                self.filed_depth = self.depth
            self.next_sibling_depth = None
        if name == "FRDOC":
            self.marker_count += 1
            if self.marker_count != 1:
                raise FederalRegisterBodySourceError("publisher XML has more than one FRDOC marker")
            self.marker_depth = self.depth

    def data(self, value: str) -> None:
        if self.marker_depth is not None:
            self.marker_text.append(value)
        elif self.filed_depth is not None:
            self.filed_text.append(value)
        elif self.next_sibling_depth is not None and value.strip():
            self.next_sibling_depth = None

    def end(self, _name: str) -> None:
        if self.depth == self.marker_depth:
            self.marker_depth = None
            marker = _FRDOC_MARKER.fullmatch("".join(self.marker_text))
            if self.document_type == "PRESDOCU" and marker is not None and not marker.group("ending").strip():
                self.next_sibling_depth = self.depth
        elif self.depth == self.filed_depth:
            self.filed_depth = None
        elif self.next_sibling_depth is not None and self.depth < self.next_sibling_depth:
            self.next_sibling_depth = None
        self.depth -= 1


def validate_publisher_xml(
    body: bytes,
    *,
    source_document_number: str,
    publication_date: str,
    final_url: str,
    max_bytes: int,
) -> PublisherXmlIdentity:
    """Prove one bounded document's XML shape, canonical URL, and FRDOC number.

    DTDs and declared entities are forbidden. Parsing takes O(B) time and
    O(D + F) auxiliary space for body bytes B, XML depth D, and FRDOC/FILED text F;
    it retains no document tree. The original body remains the caller's evidence.
    """

    exact_body = _validated_max_bytes(body, max_bytes, label="publisher XML")
    if not exact_body:
        raise FederalRegisterBodySourceError("publisher XML is empty")
    source_id = _validated_source_id(source_document_number, label="document_number")
    safe_date = _validated_publication_date(publication_date)
    if final_url != publisher_xml_locator(source_id, safe_date):
        raise FederalRegisterBodySourceError("publisher XML final URL differs from the requested locator")

    handler = _PublisherXmlHandler()
    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartElementHandler = handler.start
    parser.EndElementHandler = handler.end
    parser.CharacterDataHandler = handler.data

    def refuse_declaration(*_values: object) -> None:
        raise FederalRegisterBodySourceError("publisher XML DTD and entity declarations are forbidden")

    parser.StartDoctypeDeclHandler = refuse_declaration
    parser.EntityDeclHandler = refuse_declaration
    parser.ExternalEntityRefHandler = refuse_declaration
    try:
        parser.Parse(exact_body, True)
    except FederalRegisterBodySourceError:
        raise
    except expat.ExpatError as error:
        raise FederalRegisterBodySourceError("publisher XML is malformed") from error

    if handler.marker_count != 1:
        raise FederalRegisterBodySourceError("publisher XML has no native FRDOC marker")
    marker = _FRDOC_MARKER.fullmatch("".join(handler.marker_text))
    if marker is None:
        raise FederalRegisterBodySourceError("publisher XML FRDOC marker is malformed")
    # Presidential XML can place the closing bracket and filing date in FILED.
    if not marker.group("ending").strip():
        filed = "".join(handler.filed_text)
        if handler.document_type != "PRESDOCU" or re.fullmatch(r"\s*Filed\s+[^\[\]]+\]\s*", filed) is None:
            raise FederalRegisterBodySourceError("publisher XML FRDOC marker has no paired FILED leaf")
    marker_number = marker.group("number")
    if marker_number != source_id:
        raise FederalRegisterBodySourceError("publisher XML FRDOC document number differs from the request")
    return PublisherXmlIdentity(
        source_document_number=source_id,
        marker_document_number=marker_number,
        publication_date=safe_date,
        document_type=handler.document_type,
    )


__all__ = ["PublisherXmlIdentity", "publisher_xml_locator", "validate_publisher_xml"]
