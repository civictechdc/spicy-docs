"""Literal GovInfo PREMIS 2 preservation metadata, including files without fixity."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from spicy_docs.reading.xml_tree import XmlTreeElement, read_xml_tree
from spicy_docs.transport.captured import CapturedBodyResponse

PREMIS_NAMESPACE = "info:lc/xmlns/premis-v2"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"


class GovInfoPremisError(ValueError):
    """The retained source cannot be safely read as GovInfo PREMIS 2 XML."""


def _name(name: str) -> str:
    if name.startswith("{}"):
        return name[2:]
    return name if name.startswith("{") else f"{{{PREMIS_NAMESPACE}}}{name}"


@dataclass(frozen=True, slots=True)
class PremisObject:
    """Typed source groups over one complete object; all repeated values survive."""

    element: XmlTreeElement

    def fields(self, *path: str) -> tuple[XmlTreeElement, ...]:
        return self.element.findall(*(_name(name) for name in path))

    @property
    def object_type(self) -> str | None:
        """Literal xsi:type, without resolving or changing its QName spelling."""
        return self.element.attribute(f"{{{XSI_NAMESPACE}}}type")

    @property
    def identifiers(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("objectIdentifier")

    @property
    def characteristics(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("objectCharacteristics")

    @property
    def fixities(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("objectCharacteristics", "fixity")

    @property
    def original_names(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("originalName")

    @property
    def storage(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("storage")


@dataclass(frozen=True, slots=True)
class GovInfoPremisRead:
    element: XmlTreeElement
    source_sha256: str
    source_byte_size: int
    element_count: int
    objects: tuple[PremisObject, ...]


def read_govinfo_premis(
    body: bytes,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    max_elements: int = 100_000,
    max_depth: int = 64,
) -> GovInfoPremisRead:
    """Read every direct PREMIS 2 object and preserve the whole source tree.

    This maps source observations, not XSD validity or authenticity. Unknown
    elements/attributes, repeated groups, absent fixity and literal algorithms,
    digests, locations and names survive. PREMIS 3 is an explicit unsupported
    source version. Namespace declarations and element positions are retained;
    original bytes preserve comments and lexical details. Nothing is fetched.
    """
    tree = read_xml_tree(
        body,
        expected_root=_name("premis"),
        error_type=GovInfoPremisError,
        label="GovInfo PREMIS",
        max_bytes=max_bytes,
        max_elements=max_elements,
        max_depth=max_depth,
    )
    return GovInfoPremisRead(
        tree.element,
        "sha256:" + hashlib.sha256(body).hexdigest(),
        len(body),
        tree.element_count,
        tuple(PremisObject(element) for element in tree.element.findall(_name("object"))),
    )


@dataclass(frozen=True, slots=True)
class GovInfoPremisComparison:
    """SHA-256 agreement for one exact URL and source object, never authenticity."""

    status: Literal["consistent", "mismatch", "not-comparable"]
    reason: str
    premis_sha256: str
    premis_byte_size: int
    capture_sha256: str
    capture_byte_size: int
    capture_url: str
    object_path: tuple[int, ...] | None = None
    characteristics_path: tuple[int, ...] | None = None
    fixity_path: tuple[int, ...] | None = None
    published_sha256: str | None = None


def _scalar(elements: tuple[XmlTreeElement, ...]) -> str | None:
    if len(elements) != 1 or elements[0].children:
        return None
    return elements[0].leading_text


def _location_match(location: XmlTreeElement, selected_url: str) -> tuple[bool, str | None]:
    """Refuse competing/malformed claims containing the exact selected URL."""
    values = location.findall(_name("contentLocationValue"))
    if not any(selected_url in value.text.split() for value in values):
        return False, None
    types = location.findall(_name("contentLocationType"))
    if len(types) != 1 or types[0].children:
        return False, "ambiguous-location-type"
    if _scalar(types) != "URI":
        return False, "unsupported-location-type"
    value = _scalar(values)
    if value is None:
        return False, "ambiguous-location-value"
    uris = []
    for token in value.split():
        if not token.lower().startswith(("http:", "https:")):
            continue
        try:
            parsed = urlsplit(token)
        except ValueError:
            return False, "malformed-location-uri"
        if not parsed.netloc:
            return False, "malformed-location-uri"
        uris.append(token)
    if len(uris) != 1:
        return False, "ambiguous-location-uri"
    return uris[0] == selected_url, None


def compare_govinfo_premis(
    capture: CapturedBodyResponse,
    metadata: GovInfoPremisRead,
    *,
    original_name: str | None = None,
) -> GovInfoPremisComparison:
    """Compare raw capture SHA-256 to one unambiguous level-zero file statement.

    The resolved URL must exactly equal the single absolute HTTP(S) URI token
    in a URI-typed contentLocationValue. An optional original name requires a
    singleton scalar originalName and further narrows that exact selection;
    it is never a URL or basename fallback. Malformed competing claims refuse.
    A complete unencoded HTTP 200 GET capture, one literal file object, one SHA-256
    fixity and its own compositionLevel=0 are required. Other source shapes
    return an explicit non-comparison. Published sizes remain raw metadata;
    this helper compares SHA-256 only. It neither fetches nor authenticates.
    """
    capture_digest = capture.sha256
    selected: PremisObject | None = None
    characteristics: XmlTreeElement | None = None
    fixity: XmlTreeElement | None = None

    def result(
        reason: str,
        status: Literal["consistent", "mismatch", "not-comparable"] = "not-comparable",
        digest: str | None = None,
    ) -> GovInfoPremisComparison:
        return GovInfoPremisComparison(
            status,
            reason,
            metadata.source_sha256,
            metadata.source_byte_size,
            capture_digest,
            capture.byte_size,
            capture.resolved_url,
            selected.element.path if selected else None,
            characteristics.path if characteristics else None,
            fixity.path if fixity else None,
            digest,
        )

    if capture.method != "GET":
        return result("unsupported-request-method")
    if capture.status_code != 200:
        return result("unsupported-response-status")
    if capture.content_encoding != "identity":
        return result("encoded-capture")
    matches = []
    for obj in metadata.objects:
        matched = False
        for location in obj.fields("storage", "contentLocation"):
            location_matches, reason = _location_match(location, capture.resolved_url)
            if reason:
                selected = obj
                return result(reason)
            matched |= location_matches
        if not matched:
            continue
        if original_name is not None:
            names = obj.original_names
            if len(names) > 1 or (names and names[0].children):
                selected = obj
                return result("ambiguous-original-name")
            if _scalar(names) != original_name:
                continue
        matches.append(obj)
    if not matches:
        return result("no-matching-file")
    if len(matches) != 1:
        return result("ambiguous-file")
    selected = matches[0]
    if selected.object_type != "file":
        return result("unsupported-object-type")
    fixities = [(block, item) for block in selected.characteristics for item in block.findall(_name("fixity"))]
    if not fixities:
        return result("missing-fixity")
    sha256 = []
    for block, item in fixities:
        algorithm = _scalar(item.findall(_name("messageDigestAlgorithm")))
        if algorithm is None:
            return result("ambiguous-algorithm")
        if algorithm == "SHA-256":
            sha256.append((block, item))
    if not sha256:
        return result("unsupported-algorithm")
    if len(sha256) != 1:
        return result("ambiguous-fixity")
    characteristics, fixity = sha256[0]
    level = _scalar(characteristics.findall(_name("compositionLevel")))
    if level is None or level.strip() != "0":
        return result("unsupported-composition")
    digest = _scalar(fixity.findall(_name("messageDigest")))
    if digest is None or re.fullmatch(r"[a-fA-F0-9]{64}", digest.strip()) is None:
        return result("malformed-sha256")
    published = "sha256:" + digest.strip().lower()
    if published == capture_digest:
        return result("sha256-match", "consistent", published)
    return result("sha256-mismatch", "mismatch", published)
