"""Bounded publisher XML parsing with inert external DTDs when explicitly allowed."""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn
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
) -> None:
    """Visit XML without retaining a tree; callbacks choose which facts to keep.

    Names use ElementTree's expanded namespace spelling. No external resource is
    loaded. Internal declarations and unresolved entities refuse before they can
    change source text. The supplied body remains the caller's original bytes.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise error_type("max_bytes must be a positive integer")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth <= 0:
        raise error_type("max_depth must be a positive integer")
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise error_type(f"{label} must be nonempty bytes within max_bytes")
    parser = expat.ParserCreate(namespace_separator="}")
    depth = 0

    def name(value: str) -> str:
        return "{" + value if "}" in value else value

    def on_start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > max_depth:
            raise error_type(f"{label} exceeds the supported nesting depth")
        start(name(tag), {name(key): value for key, value in attributes.items()})

    def on_end(tag: str) -> None:
        nonlocal depth
        end(name(tag))
        depth -= 1

    def refuse_entity(*_args: object) -> NoReturn:
        raise error_type(f"{label} entity declarations and references are forbidden")

    def doctype(_name: str, system_id: str | None, _public_id: str | None, internal: bool) -> None:
        if not allow_external_doctype or internal or not system_id:
            raise error_type(f"{label} permits only an inert external DOCTYPE")

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    parser.CharacterDataHandler = data
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = refuse_entity
    parser.ExternalEntityRefHandler = refuse_entity
    parser.SkippedEntityHandler = refuse_entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
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
