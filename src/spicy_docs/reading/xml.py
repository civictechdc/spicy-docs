"""Bounded publisher XML parsing with inert external DTDs when explicitly allowed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn
from xml.etree.ElementTree import Element, TreeBuilder
from xml.parsers import expat


def scan_xml(
    body: bytes,
    *,
    start: Callable[[str, dict[str, str]], object],
    end: Callable[[str], object],
    data: Callable[[str], object],
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    allow_external_doctype: bool = False,
    max_depth: int = 256,
    namespace: Callable[[str, str], object] | None = None,
    byte_index: Callable[[Callable[[], int]], object] | None = None,
) -> None:
    """Visit XML without retaining a tree; callbacks choose which facts to keep.

    Names use ElementTree's expanded namespace spelling. No external resource is
    loaded. Internal declarations and unresolved entities refuse before they can
    change source text. The supplied body remains the caller's original bytes.
    ``byte_index`` is handed, once, a function returning the offset in ``body``
    of the event a callback is running for: a start or end tag's ``<``.
    """
    _validate_xml_input(body, max_bytes=max_bytes, error_type=error_type, label=label)
    parser = expat.ParserCreate(namespace_separator="}")

    def name(value: str) -> str:
        return "{" + value if "}" in value else value

    _configure_xml_parser(
        parser,
        start=lambda tag, attributes: start(name(tag), {name(key): value for key, value in attributes.items()}),
        end=lambda tag: end(name(tag)),
        data=data,
        error_type=error_type,
        label=label,
        allow_external_doctype=allow_external_doctype,
        max_depth=max_depth,
    )
    if namespace is not None:
        parser.StartNamespaceDeclHandler = lambda prefix, uri: namespace(prefix or "", uri or "")
    if byte_index is not None:
        byte_index(lambda: parser.CurrentByteIndex)
    _feed_xml(body, parser, error_type=error_type, label=label)


def _validate_xml_input(
    body: bytes,
    *,
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    allow_empty: bool = False,
) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise error_type("max_bytes must be a positive integer")
    if not isinstance(body, bytes) or (not body and not allow_empty) or len(body) > max_bytes:
        requirement = "bytes" if allow_empty else "nonempty bytes"
        raise error_type(f"{label} must be {requirement} within max_bytes")


def _configure_xml_parser(
    parser: Any,
    *,
    start: Callable[[str, dict[str, str]], object],
    end: Callable[[str], object],
    data: Callable[[str], object],
    error_type: type[ValueError],
    label: str,
    allow_external_doctype: bool = False,
    max_depth: int = 256,
    doctype: Callable[[str, str | None, str | None], object] | None = None,
) -> None:
    """Apply the same depth/entity rules to ordinary and positioned readers."""
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth <= 0:
        raise error_type("max_depth must be a positive integer")
    depth = 0

    def on_start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > max_depth:
            raise error_type(f"{label} exceeds the supported nesting depth")
        start(tag, attributes)

    def on_end(tag: str) -> None:
        nonlocal depth
        end(tag)
        depth -= 1

    def refuse_entity(*_args: object) -> NoReturn:
        raise error_type(f"{label} entity declarations and references are forbidden")

    def on_doctype(name: str, system_id: str | None, public_id: str | None, internal: bool) -> None:
        if not allow_external_doctype or internal or not system_id:
            raise error_type(f"{label} permits only an inert external DOCTYPE")
        if doctype is not None:
            doctype(name, system_id, public_id)

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    parser.CharacterDataHandler = data
    parser.StartDoctypeDeclHandler = on_doctype
    parser.EntityDeclHandler = refuse_entity
    parser.ExternalEntityRefHandler = refuse_entity
    parser.SkippedEntityHandler = refuse_entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)


def _feed_xml(body: bytes, parser: Any, *, error_type: type[ValueError], label: str) -> None:
    """Feed bounded chunks; preserve the existing source-error boundary."""
    try:
        # Feeding bounded chunks avoids Expat retaining a second full input copy.
        for offset in range(0, len(body), 64 * 1024):
            parser.Parse(body[offset : offset + 64 * 1024], False)
        parser.Parse(b"", True)
    except (expat.ExpatError, ValueError) as error:
        if isinstance(error, error_type):
            raise
        raise error_type(f"{label} is malformed") from error


def parse_xml(
    body: bytes,
    *,
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    allow_external_doctype: bool = False,
    max_depth: int = 256,
) -> Element:
    """Build a tree for small documents using the same XML safety rules."""
    builder = TreeBuilder()
    scan_xml(
        body,
        start=builder.start,
        end=builder.end,
        data=builder.data,
        max_bytes=max_bytes,
        error_type=error_type,
        label=label,
        allow_external_doctype=allow_external_doctype,
        max_depth=max_depth,
    )
    return builder.close()


def _tag_end(body: bytes, start: int) -> int:
    """The offset just past the tag that opens at ``start``, a ``>`` inside a quoted attribute value skipped."""
    quote = 0
    for index in range(start + 1, len(body)):
        byte = body[index]
        if quote:
            quote = 0 if byte == quote else quote
        elif byte in (0x22, 0x27):
            quote = byte
        elif byte == 0x3E:
            return index + 1
    raise ValueError("XML tag does not close")


def parse_xml_with_spans(
    body: bytes,
    *,
    path: tuple[str, ...],
    max_bytes: int,
    error_type: type[ValueError],
    label: str,
    allow_external_doctype: bool = False,
    max_depth: int = 256,
) -> tuple[Element, dict[Element, tuple[int, int]]]:
    """``parse_xml``'s tree, plus the exact byte span in ``body`` of every element at ``path`` from the root.

    A span runs from the element's ``<`` to just past its own end tag (or its
    ``/>``), so ``body[start:end]`` is the publisher's markup for it,
    unreserialized: expat reports each tag's offset during the one parse the
    tree already needs. Only how many leading ``path`` elements are open is
    tracked, two integer comparisons an event, because this runs on every
    element of the document.
    """
    if not path or not all(isinstance(tag, str) and tag for tag in path):
        raise ValueError("path must name at least one element")
    builder = TreeBuilder()
    target = len(path)
    depth = matched = 0
    opened: list[tuple[Element, int, int | None]] = []
    spans: dict[Element, tuple[int, int]] = {}
    position: list[Callable[[], int]] = []

    def start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth, matched
        element = builder.start(tag, attributes)
        if matched == depth < target and tag == path[depth]:
            matched += 1
            if matched == target:
                begin = position[0]()
                tag_end = _tag_end(body, begin)
                # Expat reports a self-closed element's end at the next token, so its span ends with its own tag.
                opened.append((element, begin, tag_end if body[tag_end - 2] == 0x2F else None))
        depth += 1

    def end(tag: str) -> None:
        nonlocal depth, matched
        builder.end(tag)
        depth -= 1
        if matched == depth + 1:
            if matched == target:
                element, begin, closed = opened.pop()
                spans[element] = (begin, closed if closed is not None else _tag_end(body, position[0]()))
            matched -= 1

    try:
        scan_xml(
            body,
            start=start,
            end=end,
            data=builder.data,
            max_bytes=max_bytes,
            error_type=error_type,
            label=label,
            allow_external_doctype=allow_external_doctype,
            max_depth=max_depth,
            byte_index=position.append,
        )
    finally:
        # The offset function holds the parser, whose handlers hold these closures and so the tree: a cycle that
        # would keep every parsed document alive until the cyclic collector ran (measured: 31 s against 25 s over
        # the 39,147-document corpus while the caller kept its results).
        position.clear()
    return builder.close(), spans


class IdentityXmlScan:
    """Keep bounded ancestry and selected scalar fields, never a document tree.

    ``fields`` are element paths in the expanded-name spelling ``scan_xml``
    reports. Subclasses observe starts, text and ends to check identity; the
    error type and label keep each source family's refusals in its own words.
    """

    def __init__(self, fields: set[tuple[str, ...]], *, error_type: type[ValueError], label: str) -> None:
        self.fields = fields
        self.error_type = error_type
        self.label = label
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.values: dict[tuple[str, ...], list[str]] = {}
        self._active: list[tuple[tuple[str, ...], list[str]]] = []
        self._field_characters = 0
        self.root = ""
        self.body_found = False

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(tag for tag, _attrs in self.stack)

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        self.stack.append((tag, attributes))
        if len(self.stack) == 1:
            self.root = tag
        if self.path in self.fields:
            if sum(map(len, self.values.values())) + len(self._active) >= 256:
                raise self.error_type(f"{self.label} repeats too many identity fields")
            self._active.append((self.path, []))
        self.observe_start(tag, attributes)

    def data(self, text: str) -> None:
        for _path, parts in self._active:
            self._field_characters += len(text)
            if self._field_characters > 64 * 1024:
                raise self.error_type(f"{self.label} identity fields exceed 65,536 characters")
            parts.append(text)
        self.observe_text(text)

    def end(self, tag: str) -> None:
        if self._active and self._active[-1][0] == self.path:
            path, parts = self._active.pop()
            self.values.setdefault(path, []).append("".join(parts))
        self.observe_end(tag)
        self.stack.pop()

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        pass

    def observe_text(self, text: str) -> None:
        pass

    def observe_end(self, tag: str) -> None:
        pass

    def field(self, path: tuple[str, ...], *, required: bool = False) -> str | None:
        values = self.values.get(path, [])
        if len(values) > 1:
            raise self.error_type(f"{self.label} repeats an identity field: " + "/".join(path))
        value = values[0] if values else None
        if value is None or not value.strip():
            if required:
                raise self.error_type(f"{self.label} lacks an identity field: " + "/".join(path))
            return None
        return value

    def read(self, body: bytes, max_bytes: int) -> None:
        scan_xml(
            body,
            start=self.start,
            end=self.end,
            data=self.data,
            max_bytes=max_bytes,
            error_type=self.error_type,
            label=self.label,
        )
