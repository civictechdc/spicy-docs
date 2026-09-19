"""The evidence-linked document model: what was extracted, where, and how it looked.

An :class:`EvidenceBlock` is one printed line as the extractor saw it -- its
text verbatim, its page and line coordinates, and the style the extractor
observed (font, size, bold, italic for a PDF; the enclosing elements for a
markup rendition). A :class:`DocumentNode` is one thing the parser decided
about a run of blocks -- a section, a paragraph, a citation -- and carries the
ids of the blocks it rests on plus a :class:`Decision` naming the method and
the rule. An :class:`UnresolvedRegion` is a run of blocks no rule could place,
kept with its issue rather than dropped. Every id here is minted by this
module and marked so (:data:`ID_ORIGIN`).

Blocks come from what ``extraction`` already retains: a PDF's ``PageResult``
pages (the native observation's PyMuPDF lines, with the boxes ``pages.py``
already normalized, plus the span fonts it kept in ``raw``), or the markup
reader's events for an HTML or XML rendition, or the lines of a text
rendition. Nothing is extracted twice and nothing is dropped: page furniture,
running heads and neighbouring sections are blocks like any other, and it is
the parser's job to classify them.

**Line assembly** is the one transformation applied on the way in, because a
justified column reaches the extractor as word fragments: PyMuPDF emits
``in``, ``the``, ``following``, ``special``, ``cir-`` as five lines at one
baseline (the fixture PDF, page 1, y=356). Consecutive extractor lines in one
vertical band that advance left to right are joined with a single space where
the fragment carries none. The rule is ``line_assembly`` in the CFR profile
and the block records how many fragments it joined.

Building is ``O(L)`` for ``L`` extractor lines or text lines; no file is read
and no request is made.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from spicy_docs.extraction.body_text import METADATA_ELEMENTS
from spicy_docs.extraction.model import Box, PageResult
from spicy_docs.reading.markup import MarkupRead

from . import ID_ORIGIN

#: PyMuPDF span flags: bit 1 italic, bit 4 bold (``TEXT_FONT_ITALIC``, ``TEXT_FONT_BOLD``).
_ITALIC_FLAG = 1 << 1
_BOLD_FLAG = 1 << 4
#: The native observation ``extraction.api.NativeText`` records.
_NATIVE_OBSERVATION = "native"
#: Two extractor lines share a baseline when their vertical overlap covers at
#: least this fraction of the shorter one.
_BAND_OVERLAP = 0.5
#: A fragment continues the line when it starts no further left than this
#: fraction of the page width before the previous fragment's right edge.
_ADVANCE_TOLERANCE = 0.002

REVIEW_STATUSES = ("accepted", "needs_review", "abstained")
DECISION_METHODS = ("rule", "model", "generated")


class EvidenceError(ValueError):
    """The retained evidence is not shaped the way this model reads it."""


@dataclass(frozen=True, slots=True)
class StyledRun:
    """A run of one line's text with the style the extractor observed for it; ``tags`` for markup.

    ``break_to_page`` is set on the first run of a node's text that the
    extractor observed on a later page than the run before it, and names that
    page's printed number when the evidence states one (``page_number``
    furniture) or its 1-based index otherwise; the serializer turns it into
    the vocabulary's page-break element.
    """

    text: str
    font: str | None = None
    size: float | None = None
    bold: bool = False
    italic: bool = False
    tags: tuple[str, ...] = ()
    break_to_page: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceBlock:
    """One printed line as extracted; ``runs`` join to ``text`` exactly."""

    id: str
    text: str
    runs: tuple[StyledRun, ...]
    rendition: str
    page: int | None = None
    line: int | None = None
    box: Box | None = None
    span: tuple[int, int] | None = None
    fragments: int = 1

    def __post_init__(self) -> None:
        if "".join(run.text for run in self.runs) != self.text:
            raise EvidenceError(f"block {self.id}: runs must join to the block text")

    @property
    def bold(self) -> bool:
        """Every non-blank run is bold."""
        runs = [run for run in self.runs if run.text.strip()]
        return bool(runs) and all(run.bold for run in runs)

    @property
    def italic(self) -> bool:
        runs = [run for run in self.runs if run.text.strip()]
        return bool(runs) and all(run.italic for run in runs)

    @property
    def size(self) -> float | None:
        """The largest observed size, so a line with a small-cap lead-in reads at its body size."""
        sizes = [run.size for run in self.runs if run.size is not None and run.text.strip()]
        return max(sizes) if sizes else None

    @property
    def fonts(self) -> tuple[str, ...]:
        return tuple(sorted({run.font for run in self.runs if run.font and run.text.strip()}))


@dataclass(frozen=True, slots=True)
class Decision:
    """How a node was placed: by which method, under which rule; ``detail`` is the rule's own witness."""

    method: str
    rule: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.method not in DECISION_METHODS:
            raise EvidenceError(f"decision method must be one of {', '.join(DECISION_METHODS)}")


@dataclass(frozen=True, slots=True)
class DocumentNode:
    """One structural decision over a run of blocks; ``text`` is the profile's assembly of those blocks."""

    id: str
    kind: str
    marker: str | None
    parent: str | None
    evidence_refs: tuple[str, ...]
    decision: Decision
    review_status: str
    text: str = ""
    runs: tuple[StyledRun, ...] = ()
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.review_status not in REVIEW_STATUSES:
            raise EvidenceError(f"review status must be one of {', '.join(REVIEW_STATUSES)}")


@dataclass(frozen=True, slots=True)
class UnresolvedRegion:
    """Blocks no rule placed, kept with the issue that says why."""

    id: str
    evidence_refs: tuple[str, ...]
    issue: str
    detail: str = ""
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceDocument:
    """Every block of one rendition in reading order, and where the bytes came from."""

    rendition: str
    derivation: str
    blocks: tuple[EvidenceBlock, ...]
    page_count: int | None = None
    source_sha256: str | None = None
    id_origin: str = ID_ORIGIN

    def __post_init__(self) -> None:
        ids = [block.id for block in self.blocks]
        if len(set(ids)) != len(ids):
            raise EvidenceError("evidence block ids must be distinct")

    def block(self, block_id: str) -> EvidenceBlock:
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise EvidenceError(f"no evidence block {block_id!r}")

    def to_json(self) -> dict[str, Any]:
        """A plain mapping for fixtures and sidecars; ``from_json`` reads it back exactly."""
        return {
            "rendition": self.rendition,
            "derivation": self.derivation,
            "pageCount": self.page_count,
            "sourceSha256": self.source_sha256,
            "idOrigin": self.id_origin,
            "blocks": [_block_json(block) for block in self.blocks],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> EvidenceDocument:
        return cls(
            rendition=data["rendition"],
            derivation=data["derivation"],
            blocks=tuple(_block_from_json(entry) for entry in data["blocks"]),
            page_count=data.get("pageCount"),
            source_sha256=data.get("sourceSha256"),
            id_origin=data.get("idOrigin", ID_ORIGIN),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=1, ensure_ascii=False) + "\n"


def _block_json(block: EvidenceBlock) -> dict[str, Any]:
    data = asdict(block)
    data["box"] = None if block.box is None else [block.box.x0, block.box.y0, block.box.x1, block.box.y1]
    data["runs"] = [
        {key: value for key, value in asdict(run).items() if value not in (None, False, ())} for run in block.runs
    ]
    return {key: value for key, value in data.items() if value is not None}


def _block_from_json(data: Mapping[str, Any]) -> EvidenceBlock:
    box = data.get("box")
    span = data.get("span")
    return EvidenceBlock(
        id=data["id"],
        text=data["text"],
        runs=tuple(StyledRun(**{**run, "tags": tuple(run.get("tags", ()))}) for run in data["runs"]),
        rendition=data["rendition"],
        page=data.get("page"),
        line=data.get("line"),
        box=None if box is None else Box(*box),
        span=None if span is None else (span[0], span[1]),
        fragments=data.get("fragments", 1),
    )


def block_id(index: int) -> str:
    return f"b{index:04d}"


def node_id(index: int) -> str:
    return f"n{index:04d}"


def region_id(index: int) -> str:
    return f"u{index:04d}"


# --- PDF pages -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    box: Box
    runs: tuple[StyledRun, ...]


def _native_lines(page: PageResult) -> Iterator[_Line]:
    """Pair the native observation's raw PyMuPDF lines with the boxes ``pages.py`` already normalized.

    The retained ``TextBlock`` list is exactly the raw lines whose rotated
    rectangle lay on the page, in order, so a two-pointer walk pairs them
    without recomputing the rotation. A raw line the extractor skipped (an
    empty rectangle carrying only whitespace) has no block and is skipped
    here too.
    """
    observation = next((o for o in page.content.observations if o.id == _NATIVE_OBSERVATION), None)
    if observation is None or not isinstance(observation.raw, Mapping):
        raise EvidenceError("PDF evidence needs the native observation with its retained PyMuPDF dict")
    blocks = [block for block in page.content.blocks if block.observation == _NATIVE_OBSERVATION]
    cursor = 0
    for raw_block in observation.raw.get("blocks", ()):
        for line in raw_block.get("lines", ()):
            spans = line.get("spans", ())
            text = "".join(span["text"] for span in spans)
            if cursor < len(blocks) and blocks[cursor].text == text and blocks[cursor].box is not None:
                box = blocks[cursor].box
                cursor += 1
            elif not text.strip():
                continue
            else:
                raise EvidenceError(f"page {page.metadata.get('page')}: native lines and retained blocks disagree")
            runs = tuple(
                StyledRun(
                    span["text"],
                    font=span.get("font"),
                    size=round(float(span["size"]), 2) if span.get("size") is not None else None,
                    bold=bool(int(span.get("flags", 0)) & _BOLD_FLAG),
                    italic=bool(int(span.get("flags", 0)) & _ITALIC_FLAG),
                )
                for span in spans
                if span["text"]
            )
            assert box is not None
            yield _Line(text, box, runs)
    if cursor != len(blocks):
        raise EvidenceError(f"page {page.metadata.get('page')}: {len(blocks) - cursor} retained blocks unpaired")


def _same_band(a: Box, b: Box) -> bool:
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return overlap >= _BAND_OVERLAP * min(a.y1 - a.y0, b.y1 - b.y0)


def _assemble(lines: Iterable[_Line]) -> Iterator[tuple[_Line, int]]:
    """``line_assembly``: join fragments that share a band and advance rightwards; yield the fragment count."""
    current: _Line | None = None
    count = 0
    for line in lines:
        if (
            current is not None
            and _same_band(current.box, line.box)
            and line.box.x0 >= current.box.x1 - _ADVANCE_TOLERANCE
        ):
            runs = list(current.runs)
            if current.text and not current.text[-1].isspace() and line.text and not line.text[0].isspace():
                runs.append(StyledRun(" "))
            runs.extend(line.runs)
            box = Box(
                min(current.box.x0, line.box.x0),
                min(current.box.y0, line.box.y0),
                max(current.box.x1, line.box.x1),
                max(current.box.y1, line.box.y1),
            )
            current = _Line("".join(run.text for run in runs), box, tuple(runs))
            count += 1
            continue
        if current is not None:
            yield current, count
        current, count = line, 1
    if current is not None:
        yield current, count


def evidence_from_pages(pages: Iterable[PageResult], *, source_sha256: str | None = None) -> EvidenceDocument:
    """Build the document from ``extraction``'s retained pages, one block per assembled printed line."""
    blocks: list[EvidenceBlock] = []
    page_count: int | None = None
    digest = source_sha256
    for page in pages:
        number = page.metadata.get("page")
        page_count = page.metadata.get("page_count", page_count)
        digest = digest or page.metadata.get("source_sha256")
        if type(number) is not int:
            raise EvidenceError("PageResult metadata must state its 1-based page number")
        for index, (line, fragments) in enumerate(_assemble(_native_lines(page)), 1):
            blocks.append(
                EvidenceBlock(
                    id=block_id(len(blocks) + 1),
                    text=line.text,
                    runs=line.runs,
                    rendition="pdf",
                    page=number,
                    line=index,
                    box=line.box,
                    fragments=fragments,
                )
            )
    return EvidenceDocument("pdf", "pdf-extraction-lines", tuple(blocks), page_count, digest)


# --- markup and text renditions ------------------------------------------------


def evidence_from_markup(read: MarkupRead, *, rendition: str, source_sha256: str | None = None) -> EvidenceDocument:
    """One block per text line of a markup read; the enclosing elements are the style observation.

    Text inside ``body_text.METADATA_ELEMENTS`` (the GovInfo ``<title>``) is
    document metadata, not body text, and is left out the same way
    ``body_text`` leaves it out. A block's ``span`` is the byte range of its
    first through last literal run when the reader could state one.
    """
    if rendition not in ("htm", "xml"):
        raise EvidenceError("markup evidence is built for the htm or xml rendition")
    blocks: list[EvidenceBlock] = []
    stack: list[str] = []
    metadata_depth = 0
    runs: list[StyledRun] = []
    starts: list[int | None] = []
    ends: list[int | None] = []
    line_number = 1

    def flush() -> None:
        nonlocal runs, starts, ends, line_number
        if runs:
            span = None
            known = [s for s in starts if s is not None], [e for e in ends if e is not None]
            if known[0] and known[1]:
                span = (min(known[0]), max(known[1]))
            blocks.append(
                EvidenceBlock(
                    id=block_id(len(blocks) + 1),
                    text="".join(run.text for run in runs),
                    runs=tuple(runs),
                    rendition=rendition,
                    line=line_number,
                    span=span,
                )
            )
        runs, starts, ends = [], [], []
        line_number += 1

    for event in read.events:
        if event.kind == "start":
            stack.append(event.name or "")
            if event.name in METADATA_ELEMENTS:
                metadata_depth += 1
            continue
        if event.kind == "end":
            if event.name in METADATA_ELEMENTS:
                metadata_depth = max(metadata_depth - 1, 0)
            for index in range(len(stack) - 1, -1, -1):
                if stack[index] == event.name:
                    del stack[index:]
                    break
            continue
        if event.kind != "text" or event.text is None or metadata_depth:
            continue
        tags = tuple(stack)
        offset = event.byte_start
        pieces = event.text.split("\n")
        for index, piece in enumerate(pieces):
            if piece:
                start = offset if event.is_literal else None
                runs.append(StyledRun(piece, tags=tags))
                starts.append(start)
                ends.append(None if start is None else start + len(piece.encode("utf-8")))
            if event.is_literal:
                offset += len(piece.encode("utf-8")) + 1
            if index < len(pieces) - 1:
                flush()
    if runs:
        flush()
    return EvidenceDocument(rendition, "markup-reader-lines", tuple(blocks), None, source_sha256)


def evidence_from_text(text: str, *, rendition: str = "txt", source_sha256: str | None = None) -> EvidenceDocument:
    """One block per line of a text rendition, with no style to observe."""
    lines = text.split("\n")
    blocks = tuple(
        EvidenceBlock(block_id(index), line, (StyledRun(line),) if line else (), rendition, line=index)
        for index, line in enumerate(lines, 1)
    )
    return EvidenceDocument(rendition, "text-rendition-lines", blocks, None, source_sha256)


__all__ = [
    "DECISION_METHODS",
    "REVIEW_STATUSES",
    "Decision",
    "DocumentNode",
    "EvidenceBlock",
    "EvidenceDocument",
    "EvidenceError",
    "StyledRun",
    "UnresolvedRegion",
    "block_id",
    "evidence_from_markup",
    "evidence_from_pages",
    "evidence_from_text",
    "node_id",
    "region_id",
]
