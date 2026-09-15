"""Literal U.S. Code structure observations from retained OLRC XML.

These readers do not decide whether a provision exists or applies. Missing
statuses stay missing, appendix identifiers survive, and ranges stay ranges.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from .uscode import DEFAULT_MAX_XML_BYTES, USLM_NAMESPACE, UsCodeSourceError
from .uscode_xml import UsCodeElement, UsCodeXmlScan

_PREFIX = "{" + USLM_NAMESPACE + "}"
_IDENTIFIER = re.compile(r"/us/usc/t(?P<title>[0-9]+[aA]?)(?P<path>/.*)")
# Native subtitle/subchapter/subpart/subdivision markers precede section's s.
# Section coordinates can contain letters, so a numeric-only rule is too narrow.
_SECTION_COMPONENT = r"/s(?!(?i:t|ch|p|d))([^/]+)"
_SECTION = re.compile(_SECTION_COMPONENT)
_PART = re.compile(_SECTION_COMPONENT + r"/([^/]+)")
_CHAPTER = re.compile(r"(?:/[^/]+)*/ch([^/]+)")


@dataclass(frozen=True, slots=True)
class UsCodeIdentifierPiece:
    """One whitespace-separated identifier; recognized coordinates stay literal."""

    raw: str
    kind: Literal["section", "section-part", "chapter"] | None = None
    title: str | None = None
    appendix: bool | None = None
    section: str | None = None
    section_part: str | None = None
    chapter: str | None = None
    range_start: str | None = None
    range_end: str | None = None


def _identifier_piece(raw: str) -> UsCodeIdentifierPiece:
    match = _IDENTIFIER.fullmatch(raw)
    if match is None:
        return UsCodeIdentifierPiece(raw)
    title, path = match["title"], match["path"]
    piece = UsCodeIdentifierPiece(raw, title=title, appendix=title[-1:] in ("a", "A"))
    if found := _SECTION.fullmatch(path):
        piece = replace(piece, kind="section", section=found[1])
    elif found := _PART.fullmatch(path):
        piece = replace(piece, kind="section-part", section=found[1], section_part=found[2])
    elif found := _CHAPTER.fullmatch(path):
        piece = replace(piece, kind="chapter", chapter=found[1])
    if found is not None:
        ends = found[1].split("...")
        if len(ends) == 2 and all(ends):
            piece = replace(piece, range_start=ends[0], range_end=ends[1])
    return piece


@dataclass(frozen=True, slots=True)
class UsCodeStructureText:
    element: UsCodeElement
    text: str


@dataclass(frozen=True, slots=True)
class UsCodeStructureObservation:
    element: UsCodeElement
    ancestors: tuple[UsCodeElement, ...]
    identifier_pieces: tuple[UsCodeIdentifierPiece, ...]
    numbers: tuple[UsCodeStructureText, ...]
    headings: tuple[UsCodeStructureText, ...]

    @property
    def identifier(self) -> str | None:
        return self.element.attributes.get("identifier")

    @property
    def status(self) -> str | None:
        return self.element.attributes.get("status")


@dataclass(frozen=True, slots=True)
class UsCodeStructureCounts:
    sections: int
    section_parts: int
    chapters: int


@dataclass(slots=True)
class _Capture:
    depth: int
    elements: tuple[UsCodeElement, ...]
    pieces: tuple[UsCodeIdentifierPiece, ...]
    callbacks: tuple[Callable[[UsCodeStructureObservation], None], ...]
    numbers: list[UsCodeStructureText] = field(default_factory=list)
    headings: list[UsCodeStructureText] = field(default_factory=list)
    text_element: UsCodeElement | None = None
    text_parts: list[str] = field(default_factory=list)
    text_characters: int = 0


class _StructureScan(UsCodeXmlScan):
    def __init__(self, callbacks: dict[str, Callable[[UsCodeStructureObservation], None] | None]) -> None:
        super().__init__()
        self.callbacks = callbacks
        self.counts = dict.fromkeys(callbacks, 0)
        self.captures: list[_Capture] = []

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        depth = len(self.stack)
        local_tag = tag.removeprefix(_PREFIX)
        if self.captures and depth == self.captures[-1].depth + 1 and local_tag in ("num", "heading"):
            self.captures[-1].text_element = self.snapshot()[-1]
        pieces = tuple(_identifier_piece(raw) for raw in attributes.get("identifier", "").split())
        kinds = []
        if local_tag == "section":
            kinds.append("sections")
        if local_tag == "chapter":
            kinds.append("chapters")
        if "{" not in local_tag and any(piece.kind == "section-part" for piece in pieces):
            kinds.append("section_parts")
        for kind in kinds:
            self.counts[kind] += 1
        selected = tuple(callback for kind in kinds if (callback := self.callbacks[kind]) is not None)
        if selected:
            self.captures.append(_Capture(depth, self.snapshot(), pieces, selected))

    def observe_text(self, text: str) -> None:
        for capture in self.captures:
            if capture.text_element is not None:
                capture.text_characters += len(text)
                if capture.text_characters > 64 * 1024:
                    raise UsCodeSourceError("U.S. Code structure number or heading exceeds 65,536 characters")
                capture.text_parts.append(text)

    def observe_end(self, tag: str) -> None:
        if not self.captures:
            return
        depth = len(self.stack)
        # A direct heading can itself carry an identifier below its section.
        # Finish its parent's text even when the heading has its own callback.
        for active in self.captures:
            if active.text_element is not None and depth == active.depth + 1:
                field = active.numbers if tag.removeprefix(_PREFIX) == "num" else active.headings
                field.append(UsCodeStructureText(active.text_element, "".join(active.text_parts)))
                active.text_element = None
                active.text_parts.clear()
                active.text_characters = 0
        capture = self.captures[-1]
        if depth == capture.depth:
            observation = UsCodeStructureObservation(
                capture.elements[-1],
                capture.elements[:-1],
                capture.pieces,
                tuple(capture.numbers),
                tuple(capture.headings),
            )
            self.captures.pop()
            for callback in capture.callbacks:
                self.emit(callback, observation)


def scan_uscode_structure(
    body: bytes,
    *,
    on_section: Callable[[UsCodeStructureObservation], None] | None = None,
    on_section_part: Callable[[UsCodeStructureObservation], None] | None = None,
    on_chapter: Callable[[UsCodeStructureObservation], None] | None = None,
    max_bytes: int = DEFAULT_MAX_XML_BYTES,
) -> UsCodeStructureCounts:
    """Visit section/chapter elements and identifiers one path component below a section.

    Callbacks run on element close and are provisional until this function
    succeeds. A later malformed element invalidates the read. Inputs may be a
    full title or an OLRC fragment; acquisition identity checks are separate.
    Names and statuses are observations, not normalized legal identifiers.
    """
    callbacks = {"sections": on_section, "section_parts": on_section_part, "chapters": on_chapter}
    if any(callback is not None and not callable(callback) for callback in callbacks.values()):
        raise UsCodeSourceError("U.S. Code structure callbacks must be callable")
    scanner = _StructureScan(callbacks)
    scanner.read(body, max_bytes)
    return UsCodeStructureCounts(**scanner.counts)
