"""Ordered markup observations with original-byte text positions and no layout policy."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Literal
from xml.parsers import expat

from .xml import _configure_xml_parser, _feed_xml, _validate_xml_input

HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_HTML_FEED_CHARACTERS = 64 * 1024


class MarkupReadError(ValueError):
    """Markup is malformed, undecodable, or outside the selected input bounds."""


@dataclass(frozen=True, slots=True)
class MarkupEvent:
    """A parser observation; only text events carry complete original-byte spans.

    XML names retain their prefix; HTML names follow HTMLParser's lowercase
    spelling. Namespace declarations remain separate from ordinary attributes.
    Start/end positions are anchors, including synthetic XML empty-element ends.
    ``is_literal`` compares decoded UTF-8 text with its original source bytes.
    """

    kind: Literal["start", "empty", "end", "text", "comment", "pi", "declaration"]
    byte_start: int
    name: str | None = None
    attributes: tuple[tuple[str, str | None], ...] = ()
    text: str | None = None
    byte_end: int | None = None
    is_literal: bool = False
    namespace_declarations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MarkupRead:
    events: tuple[MarkupEvent, ...]
    element_count: int
    root_name: str | None
    root_expanded_name: str | None


class _Events:
    def __init__(self, body: bytes, max_events: int) -> None:
        if type(max_events) is not int or max_events <= 0:
            raise MarkupReadError("max_events must be a positive integer")
        self.body = body
        self.max_events = max_events
        self.events: list[MarkupEvent] = []
        self.element_count = 0
        self.root_name: str | None = None
        self.root_expanded_name: str | None = None
        self._literal_parts: list[str] = []
        self._literal_start = self._literal_end = 0
        self._literal_utf8 = True

    def _append(self, event: MarkupEvent) -> None:
        if len(self.events) >= self.max_events:
            raise MarkupReadError("markup exceeds max_events")
        self.events.append(event)

    def flush(self) -> None:
        if self._literal_parts:
            self._append(
                MarkupEvent(
                    "text",
                    self._literal_start,
                    text="".join(self._literal_parts),
                    byte_end=self._literal_end,
                    is_literal=self._literal_utf8,
                )
            )
            self._literal_parts.clear()

    def add(self, event: MarkupEvent) -> None:
        self.flush()
        self._append(event)
        if event.kind in {"start", "empty"}:
            self.element_count += 1
            if self.root_name is None:
                self.root_name = event.name

    def text(self, text: str, start: int, end: int, *, source_encoding: str = "utf-8") -> None:
        if not text:
            if end > start:
                self.add(MarkupEvent("text", start, text="", byte_end=end))
            return
        literal = self.body[start:end] == text.encode("utf-8")
        try:
            source_literal = literal or self.body[start:end] == text.encode(source_encoding)
        except UnicodeEncodeError:
            source_literal = False  # A numeric reference can exceed the declared source encoding.
        if source_literal:
            if self._literal_parts and start != self._literal_end:
                self.flush()
            if not self._literal_parts:
                if len(self.events) >= self.max_events:
                    raise MarkupReadError("markup exceeds max_events")
                self._literal_start = start
                self._literal_utf8 = literal
            else:
                self._literal_utf8 = self._literal_utf8 and literal
            self._literal_parts.append(text)
            self._literal_end = end
        else:
            self.add(MarkupEvent("text", start, text=text, byte_end=end))

    def result(self) -> MarkupRead:
        self.flush()
        return MarkupRead(tuple(self.events), self.element_count, self.root_name, self.root_expanded_name)


def _xml_name(name: str) -> tuple[str, str]:
    """Resolve Expat's namespace triplet into the source QName and expanded name."""
    parts = name.split("}")
    if len(parts) == 1:
        return name, name
    uri, local, *prefix = parts
    return (f"{prefix[0]}:{local}" if prefix else local), f"{{{uri}}}{local}"


def read_xml_events(
    body: bytes,
    *,
    max_bytes: int = 64 * 1024**2,
    max_events: int = 1_000_000,
    max_depth: int = 256,
    allow_external_doctype: bool = False,
) -> MarkupRead:
    """Read complete namespace-valid XML with literal text and original-byte spans.

    Declared entities refuse under the shared XML safety rules. An inert external
    DOCTYPE requires an explicit choice and never loads its resource. XML encoding
    declarations remain effective; byte positions always address the original
    input, not a UTF-8 re-encoding. No external resource is read.
    """
    _validate_xml_input(body, max_bytes=max_bytes, error_type=MarkupReadError, label="XML markup")
    if type(allow_external_doctype) is not bool:
        raise MarkupReadError("allow_external_doctype must be a boolean")
    events = _Events(body, max_events)
    parser = expat.ParserCreate(namespace_separator="}")
    parser.namespace_prefixes = True
    pending: tuple[str, int] | None = None
    namespaces: list[tuple[str, str]] = []
    # Expat recognizes both BOM and zero-byte signatures before a declaration.
    encoding = (
        "utf-16-le"
        if body.startswith((b"\xff\xfe", b"<\0"))
        else "utf-16-be"
        if body.startswith((b"\xfe\xff", b"\0<"))
        else "utf-8"
    )

    def close_text() -> None:
        nonlocal pending
        if pending is not None:
            text, start = pending
            pending = None
            events.text(text, start, parser.CurrentByteIndex, source_encoding=encoding)

    def start(name: str, attributes: dict[str, str]) -> None:
        close_text()
        qualified, expanded = _xml_name(name)
        if events.root_name is None:
            events.root_expanded_name = expanded
        events.add(
            MarkupEvent(
                "start",
                parser.CurrentByteIndex,
                name=qualified,
                attributes=tuple((_xml_name(key)[0], value) for key, value in attributes.items()),
                namespace_declarations=tuple(namespaces),
            )
        )
        namespaces.clear()

    def end(name: str) -> None:
        close_text()
        events.add(MarkupEvent("end", parser.CurrentByteIndex, name=_xml_name(name)[0]))

    def data(text: str) -> None:
        nonlocal pending
        close_text()
        pending = text, parser.CurrentByteIndex

    def other(kind: Literal["comment", "pi", "declaration"], text: str, name: str | None = None) -> None:
        close_text()
        events.add(MarkupEvent(kind, parser.CurrentByteIndex, name=name, text=text))

    def declaration(version: str, declared_encoding: str | None, standalone: int) -> None:
        nonlocal encoding
        close_text()
        attributes: list[tuple[str, str | None]] = [("version", version)]
        if declared_encoding is not None:
            attributes.append(("encoding", declared_encoding))
            if not encoding.startswith("utf-16-"):
                encoding = declared_encoding
        if standalone != -1:
            attributes.append(("standalone", "yes" if standalone else "no"))
        events.add(MarkupEvent("declaration", parser.CurrentByteIndex, name="xml", attributes=tuple(attributes)))

    def doctype(name: str, system_id: str | None, public_id: str | None) -> None:
        close_text()
        attributes: list[tuple[str, str | None]] = [("name", name)]
        if system_id is not None:
            attributes.append(("system", system_id))
        if public_id is not None:
            attributes.append(("public", public_id))
        events.add(MarkupEvent("declaration", parser.CurrentByteIndex, name="doctype", attributes=tuple(attributes)))

    _configure_xml_parser(
        parser,
        start=start,
        end=end,
        data=data,
        error_type=MarkupReadError,
        label="XML markup",
        max_depth=max_depth,
        allow_external_doctype=allow_external_doctype,
        doctype=doctype,
    )
    parser.StartNamespaceDeclHandler = lambda prefix, uri: namespaces.append((prefix or "", uri or ""))
    parser.CommentHandler = lambda text: other("comment", text)
    parser.ProcessingInstructionHandler = lambda name, text: other("pi", text, name)
    parser.XmlDeclHandler = declaration
    # Delimiters close a run even when no semantic element event occurs.
    parser.StartCdataSectionHandler = close_text
    parser.EndCdataSectionHandler = close_text
    try:
        _feed_xml(body, parser, error_type=MarkupReadError, label="XML markup")
    except LookupError as error:
        raise MarkupReadError("XML markup declares an unsupported encoding") from error
    close_text()
    return events.result()


class _HtmlEvents(HTMLParser):
    def __init__(self, body: bytes, text: str, *, max_events: int, max_depth: int) -> None:
        super().__init__(convert_charrefs=False)
        if type(max_depth) is not int or max_depth <= 0:
            raise MarkupReadError("max_depth must be a positive integer")
        self.events = _Events(body, max_events)
        self.text = text
        self.max_depth = max_depth
        self.stack: list[str] = []
        self._line = 1
        self._column = self._character = self._byte = 0

    def position(self) -> tuple[int, int]:
        # HTMLParser counts only LF as a line boundary. Advance once through the
        # source instead of allocating one Python integer per source character.
        line, column = self.getpos()
        character = self._character
        if line == self._line:
            character += column - self._column
        else:
            for _ in range(line - self._line):
                character = self.text.index("\n", character) + 1
            character += column
        self._byte += len(self.text[self._character : character].encode("utf-8"))
        self._line, self._column, self._character = line, column, character
        return self._byte, character

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in HTML_VOID_TAGS:
            if len(self.stack) >= self.max_depth:
                raise MarkupReadError("HTML markup exceeds the supported nesting depth")
            self.stack.append(tag)
        self.events.add(MarkupEvent("start", self.position()[0], name=tag, attributes=tuple(attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.stack) >= self.max_depth:
            raise MarkupReadError("HTML markup exceeds the supported nesting depth")
        self.events.add(MarkupEvent("empty", self.position()[0], name=tag, attributes=tuple(attrs)))

    def handle_endtag(self, tag: str) -> None:
        self.events.add(MarkupEvent("end", self.position()[0], name=tag))
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        start, _ = self.position()
        # HTMLParser can deliver a final unterminated reference as data on close.
        # Match convert_charrefs=True there, while keeping script/style data raw.
        decoded = data if self.cdata_elem else unescape(data)
        self.events.text(decoded, start, start + len(data.encode("utf-8")))

    def _reference(self, name: str) -> None:
        start, character = self.position()
        end = character + len(name) + 1
        if self.text[end : end + 1] == ";":
            end += 1
        raw = self.text[character:end]
        self.events.text(unescape(raw), start, start + len(raw.encode("utf-8")))

    def handle_entityref(self, name: str) -> None:
        self._reference(name)

    def handle_charref(self, name: str) -> None:
        self._reference("#" + name)

    def handle_comment(self, data: str) -> None:
        self.events.add(MarkupEvent("comment", self.position()[0], text=data))

    def handle_pi(self, data: str) -> None:
        self.events.add(MarkupEvent("pi", self.position()[0], text=data))

    def handle_decl(self, decl: str) -> None:
        self.events.add(MarkupEvent("declaration", self.position()[0], text=decl))

    def unknown_decl(self, data: str) -> None:
        self.events.add(MarkupEvent("declaration", self.position()[0], text=data))


def read_html_events(
    body: bytes,
    *,
    max_bytes: int = 64 * 1024**2,
    max_events: int = 1_000_000,
    max_depth: int = 256,
) -> MarkupRead:
    """Read UTF-8 HTML using HTMLParser's tolerant grammar, without suppressing text.

    Unknown tags and duplicate attributes survive. This is a source parser, not
    browser DOM construction: it does not infer missing tags or layout breaks.
    """
    _validate_xml_input(body, max_bytes=max_bytes, error_type=MarkupReadError, label="HTML markup", allow_empty=True)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MarkupReadError("HTML markup must be UTF-8") from error
    parser = _HtmlEvents(body, text, max_events=max_events, max_depth=max_depth)
    try:
        for offset in range(0, len(text), _HTML_FEED_CHARACTERS):
            parser.feed(text[offset : offset + _HTML_FEED_CHARACTERS])
        parser.close()
    except (AssertionError, ValueError) as error:
        if isinstance(error, MarkupReadError):
            raise
        raise MarkupReadError(f"HTML markup cannot be parsed: {error}") from error
    return parser.events.result()
