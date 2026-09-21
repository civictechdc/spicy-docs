"""Bounded source XML trees with ordered decoded text and namespace context."""

from __future__ import annotations

from dataclasses import dataclass, field

from .xml import scan_xml


@dataclass(frozen=True, slots=True)
class XmlTreeElement:
    """One element; names are expanded and paths count element children from one.

    Namespace declarations remain on their declaring element, preserving context
    for QName-valued attributes. Positions are not byte offsets. Comments,
    processing instructions and lexical spelling remain in the original bytes.
    """

    name: str
    attributes: tuple[tuple[str, str], ...]
    namespace_declarations: tuple[tuple[str, str], ...]
    path: tuple[int, ...]
    content: tuple[str | XmlTreeElement, ...]

    @property
    def children(self) -> tuple[XmlTreeElement, ...]:
        return tuple(item for item in self.content if isinstance(item, XmlTreeElement))

    @property
    def leading_text(self) -> str | None:
        """Decoded text before the first child, matching ElementTree.text."""
        return self.content[0] if self.content and isinstance(self.content[0], str) else None

    @property
    def text(self) -> str:
        """All decoded descendant text in source order, without trimming."""
        pieces = []
        pending: list[str | XmlTreeElement] = [self]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                pieces.append(item)
            else:
                pending.extend(reversed(item.content))
        return "".join(pieces)

    def attribute(self, name: str) -> str | None:
        """The first value for this exact expanded name, or ``None``."""
        return next((value for key, value in self.attributes if key == name), None)

    def findall(self, *path: str) -> tuple[XmlTreeElement, ...]:
        """Select a relative child path using expanded names; bare names have no namespace.

        Each step matches direct children only, so an empty path returns ``children``.
        """
        if not path:
            return self.children
        nodes = (self,)
        for name in path:
            name = name.removeprefix("{}")
            nodes = tuple(child for node in nodes for child in node.children if child.name == name)
        return nodes


@dataclass(frozen=True, slots=True)
class XmlTreeRead:
    element: XmlTreeElement
    element_count: int


@dataclass(slots=True)
class _Frame:
    name: str
    attributes: tuple[tuple[str, str], ...]
    namespaces: tuple[tuple[str, str], ...]
    path: tuple[int, ...]
    content: list[str | XmlTreeElement] = field(default_factory=list)
    pending_text: list[str] = field(default_factory=list)
    child_count: int = 0

    def flush(self) -> None:
        # Coalesce Expat text chunks once per segment, including entity boundaries.
        if self.pending_text:
            self.content.append("".join(self.pending_text))
            self.pending_text.clear()


def read_xml_tree(
    body: bytes,
    *,
    expected_root: str,
    error_type: type[ValueError],
    label: str,
    max_bytes: int,
    max_elements: int,
    max_depth: int = 64,
) -> XmlTreeRead:
    """Retain one complete bounded tree using the shared XML safety scanner."""
    if isinstance(max_elements, bool) or not isinstance(max_elements, int) or max_elements <= 0:
        raise error_type("max_elements must be a positive integer")
    stack: list[_Frame] = []
    declarations: list[tuple[str, str]] = []
    root: XmlTreeElement | None = None
    count = 0

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if count > max_elements:
            raise error_type(f"{label} exceeds max_elements")
        path = (1,)
        if stack:
            parent = stack[-1]
            parent.flush()
            parent.child_count += 1
            path = (*parent.path, parent.child_count)
        elif name != expected_root:
            raise error_type(f"{label} requires root {expected_root}")
        stack.append(_Frame(name, tuple(attributes.items()), tuple(declarations), path))
        declarations.clear()

    def end(_name: str) -> None:
        nonlocal root
        frame = stack.pop()
        frame.flush()
        element = XmlTreeElement(frame.name, frame.attributes, frame.namespaces, frame.path, tuple(frame.content))
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
        max_depth=max_depth,
        error_type=error_type,
        label=label,
    )
    assert root is not None
    return XmlTreeRead(root, count)
