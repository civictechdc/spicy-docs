"""Bounded OLRC XML ancestry shared by the structure and reference readers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .uscode import DEFAULT_MAX_XML_BYTES, UsCodeSourceError, _limit
from .xml import scan_xml


@dataclass(frozen=True, slots=True)
class UsCodeElement:
    """One element's literal attributes and namespace-independent positional XPath.

    ``/*[1]/*[2]`` selects the root's second element child, regardless of XML
    namespace prefixes. It is an element position, never a byte offset.
    """

    tag: str
    attributes: dict[str, str]
    source_xpath: str


@dataclass(slots=True)
class _Frame:
    tag: str
    attributes: dict[str, str]
    position: int
    children: int = field(default=0)


class _CallbackError(Exception):
    def __init__(self, original: ValueError) -> None:
        self.original = original


class UsCodeXmlScan:
    """Observe a retained OLRC title or fragment without constructing its tree."""

    def __init__(self, *, max_depth: int = 256) -> None:
        self.stack: list[_Frame] = []
        self.max_depth = max_depth

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        if self.stack:
            self.stack[-1].children += 1
            position = self.stack[-1].children
        else:
            position = 1
        self.stack.append(_Frame(tag, attributes, position))
        self.observe_start(tag, attributes)

    def end(self, tag: str) -> None:
        self.observe_end(tag)
        self.stack.pop()

    def data(self, text: str) -> None:
        self.observe_text(text)

    def snapshot(self) -> tuple[UsCodeElement, ...]:
        path = ""
        elements = []
        for frame in self.stack:
            path += f"/*[{frame.position}]"
            elements.append(UsCodeElement(frame.tag, dict(frame.attributes), path))
        return tuple(elements)

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        pass

    def observe_end(self, tag: str) -> None:
        pass

    def observe_text(self, text: str) -> None:
        pass

    def emit(self, callback: Callable, observation: object) -> None:
        # scan_xml labels parser ValueErrors as malformed source XML. A sink's
        # ValueError instead belongs to the caller and must retain its identity.
        try:
            callback(observation)
        except ValueError as error:
            raise _CallbackError(error) from error

    def read(self, body: bytes, max_bytes: int = DEFAULT_MAX_XML_BYTES) -> None:
        _limit(max_bytes)
        try:
            scan_xml(
                body,
                start=self.start,
                end=self.end,
                data=self.data,
                max_bytes=max_bytes,
                error_type=UsCodeSourceError,
                label="U.S. Code XML",
                max_depth=self.max_depth,
            )
        except _CallbackError as failure:
            raise failure.original from None
