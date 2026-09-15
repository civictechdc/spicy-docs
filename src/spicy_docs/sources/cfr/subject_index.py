"""Read Archives CFR subject-index markup without assigning terms to parts."""

from __future__ import annotations

import re
from array import array
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

from .models import DEFAULT_MAX_BYTES, CfrSourceError, _limit

CFR_SUBJECT_INDEX_URL_TEMPLATE = "https://www.archives.gov/federal-register/cfr/subject-title-{title:02d}.html"
_HEADING = re.compile(
    r"(?P<title>\d{1,2})\s*CFR\s*(?:(?P<keyword>Parts?|Oart|Chapter)\s*)?"
    r"(?P<part>[0-9][0-9A-Za-z.\-]*)\s*(?P<separator>[_\u2014\u2013-])\s*(?P<heading>.*)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class CfrSubjectHeading:
    title: str
    keyword: str | None
    part: str
    separator: str
    heading: str
    irregularities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CfrSubjectBlock:
    tag: str
    attributes: tuple[tuple[str, str | None], ...]
    list_index: int | None
    byte_span: tuple[int, int]
    raw_html: bytes
    text_fragments: tuple[str, ...]
    heading: CfrSubjectHeading | None
    issues: tuple[str, ...]

    @property
    def text(self) -> str:
        """Decoded descendant text; markup boundaries remain in text_fragments."""
        return "".join(self.text_fragments)


@dataclass(frozen=True, slots=True)
class CfrSubjectIndex:
    blocks: tuple[CfrSubjectBlock, ...]
    metadata: tuple[CfrSubjectBlock, ...]
    issues: tuple[str, ...]


def _heading(fragments: tuple[str, ...]) -> CfrSubjectHeading | None:
    value = " ".join(fragments).strip()
    irregularities = []
    if value.lower().startswith("strong>"):
        value = value[len("strong>") :].lstrip()
        irregularities.append("leaked_strong_tag")
    match = _HEADING.fullmatch(value)
    if match is None:
        return None
    if match["keyword"] is None:
        irregularities.append("missing_keyword")
    elif match["keyword"].lower() == "oart":
        irregularities.append("keyword_Oart")
    if match["separator"] != "_":
        irregularities.append("alternate_separator")
    return CfrSubjectHeading(
        match["title"], match["keyword"], match["part"], match["separator"], match["heading"], tuple(irregularities)
    )


@dataclass
class _Capture:
    tag: str
    attributes: tuple[tuple[str, str | None], ...]
    list_index: int | None
    start: int
    fragments: list[list[str]] = field(default_factory=lambda: [[]])


class _SubjectReader(HTMLParser):
    def __init__(self, payload: bytes, *, max_blocks: int, max_block_bytes: int) -> None:
        super().__init__(convert_charrefs=False)
        self.payload = payload
        self.max_blocks = max_blocks
        self.max_block_bytes = max_block_bytes
        self.source = payload.decode("utf-8", "surrogateescape")
        self.lines = [0]
        self.lines.extend(i + 1 for i, character in enumerate(self.source) if character == "\n")
        self.byte_offsets = array("I", [0])
        for character in self.source:
            self.byte_offsets.append(self.byte_offsets[-1] + len(character.encode("utf-8", "surrogateescape")))
        self.blocks: list[CfrSubjectBlock] = []
        self.metadata: list[CfrSubjectBlock] = []
        self.current: _Capture | None = None
        self.list_indices: list[int] = []
        self.list_count = 0

    def _position(self) -> int:
        line, column = self.getpos()
        return self.byte_offsets[self.lines[line - 1] + column]

    def _append(self, block: CfrSubjectBlock) -> None:
        if block.byte_span[1] - block.byte_span[0] > self.max_block_bytes:
            raise CfrSourceError("CFR subject index exceeds max_block_bytes")
        if len(self.blocks) + len(self.metadata) >= self.max_blocks:
            raise CfrSourceError("CFR subject index exceeds max_blocks")
        (self.metadata if block.tag in {"h1", "h3", "p"} else self.blocks).append(block)

    def _finish(self, end: int, *issues: str) -> None:
        current = self.current
        if current is None:
            return
        if end - current.start > self.max_block_bytes:
            raise CfrSourceError("CFR subject index exceeds max_block_bytes")
        fragments = tuple("".join(parts) for parts in current.fragments)
        self._append(
            CfrSubjectBlock(
                current.tag,
                current.attributes,
                current.list_index,
                (current.start, end),
                self.payload[current.start : end],
                fragments,
                _heading(fragments) if current.tag in {"dt", "dd"} else None,
                issues,
            )
        )
        self.current = None

    def _check_current(self, end: int) -> None:
        if self.current is not None and end - self.current.start > self.max_block_bytes:
            raise CfrSourceError("CFR subject index exceeds max_block_bytes")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self._position()
        raw = self.get_starttag_text()
        end = start + len(raw.encode("utf-8", "surrogateescape"))
        attributes = tuple((name, _decode(value) if value is not None else None) for name, value in attrs)
        if tag == "dl":
            self._finish(start, "unclosed_element")
            if len(self.list_indices) >= 128:
                raise CfrSourceError("CFR subject index exceeds definition-list nesting limit")
            self.list_indices.append(self.list_count)
            self.list_count += 1
        elif tag in {"dt", "dd"} or (tag in {"h1", "h3", "p"} and self.current is None):
            self._finish(start, "unclosed_element")
            self.current = _Capture(tag, attributes, self.list_indices[-1] if self.list_indices else None, end)
        elif self.current is not None:
            self._check_current(end)
            self.current.fragments.append([])
        elif self.list_indices:
            self._append(
                CfrSubjectBlock(
                    tag,
                    attributes,
                    self.list_indices[-1],
                    (start, end),
                    self.payload[start:end],
                    (),
                    None,
                    ("unexpected_list_element",),
                )
            )

    def handle_endtag(self, tag: str) -> None:
        start = self._position()
        if self.current is not None and tag == self.current.tag:
            self._finish(start)
        elif tag == "dl":
            self._finish(start, "unclosed_element")
            if self.list_indices:
                self.list_indices.pop()
        elif self.current is not None:
            self._check_current(self.payload.find(b">", start) + 1)
            self.current.fragments.append([])
        elif self.list_indices:
            end = self.payload.find(b">", start) + 1
            self._append(
                CfrSubjectBlock(
                    f"/{tag}",
                    (),
                    self.list_indices[-1],
                    (start, end),
                    self.payload[start:end],
                    (),
                    None,
                    ("unexpected_list_close",),
                )
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "dl":
            self.list_indices.pop()
        elif self.current is not None and self.current.tag == tag:
            self._finish(self.current.start)

    def handle_comment(self, data: str) -> None:
        if self.current is not None:
            self._check_current(self._position() + len(data.encode("utf-8", "surrogateescape")))
            self.current.fragments.append([])

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self._check_current(self._position() + len(data.encode("utf-8", "surrogateescape")))
            self.current.fragments[-1].append(_decode(data))
        elif self.list_indices and data.strip():
            self._orphan_text(_decode(data), len(data.encode("utf-8", "surrogateescape")))

    def _orphan_text(self, text: str, byte_length: int) -> None:
        start = self._position()
        end = start + byte_length
        if byte_length > self.max_block_bytes:
            raise CfrSourceError("CFR subject index exceeds max_block_bytes")
        self._append(
            CfrSubjectBlock(
                "#text",
                (),
                self.list_indices[-1],
                (start, end),
                self.payload[start:end],
                (text,),
                None,
                ("orphan_list_text",),
            )
        )

    def _reference(self, spelling: str) -> None:
        start = self._position()
        length = len(spelling)
        if self.payload[start + length : start + length + 1] == b";":
            spelling += ";"
            length += 1
        value = unescape(spelling)
        if self.current is not None:
            self._check_current(start + length)
            self.current.fragments[-1].append(value)
        elif self.list_indices:
            self._orphan_text(value, length)

    def handle_entityref(self, name: str) -> None:
        self._reference(f"&{name}")

    def handle_charref(self, name: str) -> None:
        self._reference(f"&#{name}")


def _decode(value: str) -> str:
    # Surrogate escape preserves invalid bytes for coordinates. Only displayed
    # text uses replacement characters; raw_html always retains the input.
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def read_cfr_subject_index(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_blocks: int = 100_000,
    max_block_bytes: int = 1024 * 1024,
) -> CfrSubjectIndex:
    """Return ordered markup observations and native page headings/revision text.

    ``byte_span`` identifies the inner HTML in the original bytes, or the raw
    tag/text for unexpected list content. Metadata contains h1/h3/p observations;
    callers choose the relevant identity and revision statements. Incomplete
    elements are retained with an issue. No term association, N/A filtering,
    reserved-title policy or punctuation cleanup occurs here.
    """

    _limit(max_bytes)
    if not isinstance(payload, bytes) or not payload or len(payload) > max_bytes:
        raise CfrSourceError("CFR subject index must be non-empty bytes within max_bytes")
    if any(type(value) is not int or value <= 0 for value in (max_blocks, max_block_bytes)):
        raise CfrSourceError("CFR subject index max_blocks and max_block_bytes must be positive integers")
    issues = []
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        issues.append("invalid_utf8")
    reader = _SubjectReader(payload, max_blocks=max_blocks, max_block_bytes=max_block_bytes)
    reader.feed(reader.source)
    reader.close()
    reader._finish(len(payload), "unclosed_element")
    if not reader.list_count:
        issues.append("no_definition_lists")
    return CfrSubjectIndex(tuple(reader.blocks), tuple(reader.metadata), tuple(issues))
