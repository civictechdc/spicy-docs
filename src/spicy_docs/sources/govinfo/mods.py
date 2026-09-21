"""Map MODS records without narrowing the publisher's vocabulary or date syntax.

Field meanings and preservation rules: docs/sources/govinfo-metadata.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from spicy_docs.reading.xml_tree import XmlTreeElement, read_xml_tree

MODS_NAMESPACE = "http://www.loc.gov/mods/v3"
DEFAULT_MAX_ELEMENTS = 100_000


class GovInfoModsError(ValueError):
    """The input cannot be safely mapped as one MODS record."""


def _name(name: str) -> str:
    if name.startswith("{}"):
        return name[2:]
    return name if name.startswith("{") else f"{{{MODS_NAMESPACE}}}{name}"


@dataclass(frozen=True, slots=True)
class ModsRecord:
    """Standard MODS views over one mapped element; repeated values stay tuples."""

    element: XmlTreeElement

    def fields(self, *path: str) -> tuple[XmlTreeElement, ...]:
        return self.element.findall(*(_name(name) for name in path))

    @property
    def titles(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("titleInfo")

    @property
    def names(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("name")

    @property
    def identifiers(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("identifier")

    @property
    def origins(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("originInfo")

    @property
    def languages(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("language")

    @property
    def locations(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("location")

    @property
    def urls(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("location", "url")

    @property
    def subjects(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("subject")

    @property
    def notes(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("note")

    @property
    def record_info(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("recordInfo")

    @property
    def extensions(self) -> tuple[XmlTreeElement, ...]:
        return self.fields("extension")

    @property
    def related_items(self) -> tuple[ModsRecord, ...]:
        return tuple(ModsRecord(element) for element in self.fields("relatedItem"))

    @property
    def parent_ids(self) -> tuple[XmlTreeElement, ...]:
        return tuple(element for element in self.identifiers if element.attribute("type") == "Parent Id")

    @property
    def preferred_citations(self) -> tuple[XmlTreeElement, ...]:
        return tuple(element for element in self.identifiers if element.attribute("type") == "preferred citation")


@dataclass(frozen=True, slots=True)
class GovInfoModsPackage:
    """One mapped MODS package root with its exact-input digest and element count."""

    package: ModsRecord
    source_sha256: str
    source_byte_size: int
    element_count: int

    @property
    def constituents(self) -> tuple[ModsRecord, ...]:
        """Direct constituent records; other/nested relationships remain mapped."""
        return tuple(
            record for record in self.package.related_items if record.element.attribute("type") == "constituent"
        )


def parse_govinfo_mods(
    body: bytes,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    max_elements: int = DEFAULT_MAX_ELEMENTS,
) -> GovInfoModsPackage:
    """Map one package/granule MODS root with exact-input provenance.

    This is source mapping, not XSD validation: unknown fields, repeated values,
    partial dates and unresolved links survive. XML comments, processing
    instructions and lexical spelling remain in the original bytes, not here.
    """
    tree = read_xml_tree(
        body,
        expected_root=_name("mods"),
        error_type=GovInfoModsError,
        label="GovInfo MODS",
        max_bytes=max_bytes,
        max_elements=max_elements,
        max_depth=64,
    )
    return GovInfoModsPackage(
        ModsRecord(tree.element), "sha256:" + hashlib.sha256(body).hexdigest(), len(body), tree.element_count
    )
