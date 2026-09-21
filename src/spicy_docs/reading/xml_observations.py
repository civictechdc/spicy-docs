"""Bounded XML element positions shared by source observation readers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .xml import scan_xml


@dataclass(frozen=True, slots=True)
class XmlElement:
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
    def __init__(self, original: Exception) -> None:
        self.original = original


class XmlObservationScan:
    """Observe retained source XML or a fragment without constructing its tree."""

    def __init__(self, *, error_type: type[ValueError], label: str, max_depth: int = 256) -> None:
        self.error_type = error_type
        self.label = label
        self.stack: list[_Frame] = []
        self.max_depth = max_depth

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        """Push the element, numbering it among its parent's element children for its positional path."""
        if self.stack:
            self.stack[-1].children += 1
            position = self.stack[-1].children
        else:
            position = 1
        self.stack.append(_Frame(tag, attributes, position))
        self.observe_start(tag, attributes)

    def end(self, tag: str) -> None:
        """Pop the element after ``observe_end``."""
        self.observe_end(tag)
        self.stack.pop()

    def data(self, text: str) -> None:
        """Forward one character-data chunk to ``observe_text``."""
        self.observe_text(text)

    def snapshot(self) -> tuple[XmlElement, ...]:
        path = ""
        elements = []
        for frame in self.stack:
            path += f"/*[{frame.position}]"
            elements.append(XmlElement(frame.tag, dict(frame.attributes), path))
        return tuple(elements)

    def current_element(self) -> XmlElement:
        """Snapshot the current position without copying ancestor attributes."""
        current = self.stack[-1]
        path = "".join(f"/*[{frame.position}]" for frame in self.stack)
        return XmlElement(current.tag, dict(current.attributes), path)

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        pass

    def observe_end(self, tag: str) -> None:
        pass

    def observe_text(self, text: str) -> None:
        pass

    def emit(self, callback: Callable, observation: object) -> None:
        # Only the sink invocation is wrapped: parser/capture errors remain source
        # errors, while caller exceptions keep their original type and identity.
        try:
            callback(observation)
        except Exception as error:
            raise _CallbackError(error) from error

    def read(self, body: bytes, *, max_bytes: int) -> None:
        """Scan ``body``; a callback's own exception is re-raised with its original type and identity."""
        try:
            scan_xml(
                body,
                start=self.start,
                end=self.end,
                data=self.data,
                max_bytes=max_bytes,
                error_type=self.error_type,
                label=self.label,
                max_depth=self.max_depth,
            )
        except _CallbackError as failure:
            raise failure.original from None
