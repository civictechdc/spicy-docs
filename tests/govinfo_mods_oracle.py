# Frozen MODS tree mapper from fe6f3e7; only scanner import made absolute.
"""Map MODS records without narrowing the publisher's vocabulary or date syntax.

Field meanings and preservation rules: docs/sources/govinfo-metadata.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from spicy_docs.sources.xml import scan_xml

MODS_NAMESPACE = "http://www.loc.gov/mods/v3"
DEFAULT_MAX_ELEMENTS = 100_000


class GovInfoModsError(ValueError):
    """The input cannot be safely mapped as one MODS record."""


def _name(name: str) -> str:
    if name.startswith("{}"):
        return name[2:]
    return name if name.startswith("{") else f"{{{MODS_NAMESPACE}}}{name}"


@dataclass(frozen=True, slots=True)
class ModsElement:
    """One source element; content retains ordered text and children.

    Names are namespace-expanded. Paths count element children from one; they
    are positions in the input tree, not byte offsets. Namespace declarations
    remain on the declaring element so QName-valued extensions retain context.
    """

    name: str
    attributes: tuple[tuple[str, str], ...]
    namespace_declarations: tuple[tuple[str, str], ...]
    path: tuple[int, ...]
    content: tuple[str | ModsElement, ...]

    @property
    def children(self) -> tuple[ModsElement, ...]:
        return tuple(item for item in self.content if isinstance(item, ModsElement))

    @property
    def text(self) -> str:
        """Decoded XML text in source order; no whitespace trimming."""
        return "".join(item if isinstance(item, str) else item.text for item in self.content)

    def attribute(self, name: str) -> str | None:
        return next((value for key, value in self.attributes if key == name), None)

    def findall(self, *path: str) -> tuple[ModsElement, ...]:
        """Select a relative child path; bare names mean the MODS namespace."""
        if not path:
            return self.children
        nodes = (self,)
        for name in path:
            nodes = tuple(child for node in nodes for child in node.children if child.name == _name(name))
        return nodes


@dataclass(frozen=True, slots=True)
class ModsRecord:
    """Standard MODS views over one mapped element; repeated values stay tuples."""

    element: ModsElement

    def fields(self, *path: str) -> tuple[ModsElement, ...]:
        return self.element.findall(*path)

    @property
    def titles(self) -> tuple[ModsElement, ...]:
        return self.fields("titleInfo")

    @property
    def names(self) -> tuple[ModsElement, ...]:
        return self.fields("name")

    @property
    def identifiers(self) -> tuple[ModsElement, ...]:
        return self.fields("identifier")

    @property
    def origins(self) -> tuple[ModsElement, ...]:
        return self.fields("originInfo")

    @property
    def languages(self) -> tuple[ModsElement, ...]:
        return self.fields("language")

    @property
    def locations(self) -> tuple[ModsElement, ...]:
        return self.fields("location")

    @property
    def urls(self) -> tuple[ModsElement, ...]:
        return self.fields("location", "url")

    @property
    def subjects(self) -> tuple[ModsElement, ...]:
        return self.fields("subject")

    @property
    def notes(self) -> tuple[ModsElement, ...]:
        return self.fields("note")

    @property
    def record_info(self) -> tuple[ModsElement, ...]:
        return self.fields("recordInfo")

    @property
    def extensions(self) -> tuple[ModsElement, ...]:
        return self.fields("extension")

    @property
    def related_items(self) -> tuple[ModsRecord, ...]:
        return tuple(ModsRecord(element) for element in self.fields("relatedItem"))

    @property
    def parent_ids(self) -> tuple[ModsElement, ...]:
        return tuple(element for element in self.identifiers if element.attribute("type") == "Parent Id")

    @property
    def preferred_citations(self) -> tuple[ModsElement, ...]:
        return tuple(element for element in self.identifiers if element.attribute("type") == "preferred citation")


@dataclass(frozen=True, slots=True)
class GovInfoModsPackage:
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


@dataclass(slots=True)
class _Frame:
    name: str
    attributes: tuple[tuple[str, str], ...]
    namespaces: tuple[tuple[str, str], ...]
    path: tuple[int, ...]
    content: list[str | ModsElement] = field(default_factory=list)
    pending_text: list[str] = field(default_factory=list)
    child_count: int = 0

    def flush(self) -> None:
        # Expat can split text at entities/chunk boundaries. Coalesce once per
        # segment so parser chunking does not change the mapped source record.
        if self.pending_text:
            self.content.append("".join(self.pending_text))
            self.pending_text.clear()


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
    if isinstance(max_elements, bool) or not isinstance(max_elements, int) or max_elements <= 0:
        raise GovInfoModsError("max_elements must be a positive integer")
    stack: list[_Frame] = []
    declarations: list[tuple[str, str]] = []
    root: ModsElement | None = None
    count = 0

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if count > max_elements:
            raise GovInfoModsError("GovInfo MODS exceeds max_elements")
        path = (1,)
        if stack:
            parent = stack[-1]
            parent.flush()
            parent.child_count += 1
            path = (*parent.path, parent.child_count)
        elif name != _name("mods"):
            raise GovInfoModsError("GovInfo metadata must have one MODS v3 root")
        stack.append(_Frame(name, tuple(attributes.items()), tuple(declarations), path))
        declarations.clear()

    def end(_name: str) -> None:
        nonlocal root
        frame = stack.pop()
        frame.flush()
        element = ModsElement(frame.name, frame.attributes, frame.namespaces, frame.path, tuple(frame.content))
        if stack:
            stack[-1].content.append(element)
        else:
            root = element

    def data(text: str) -> None:
        if stack:
            stack[-1].pending_text.append(text)

    scan_xml(
        body,
        start=start,
        end=end,
        data=data,
        namespace=lambda prefix, uri: declarations.append((prefix, uri)),
        max_bytes=max_bytes,
        max_depth=64,
        error_type=GovInfoModsError,
        label="GovInfo MODS",
    )
    assert root is not None
    return GovInfoModsPackage(ModsRecord(root), "sha256:" + hashlib.sha256(body).hexdigest(), len(body), count)
