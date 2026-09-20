"""Small data types and injectable interfaces for page extraction."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol


class ExtractionError(RuntimeError):
    """A failed extraction, optionally carrying retained provider diagnostics."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


@dataclass(frozen=True, slots=True)
class Box:
    """Normalized displayed-page coordinates, top-left origin."""

    x0: float = 0
    y0: float = 0
    x1: float = 1
    y1: float = 1

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("box coordinates must be finite")
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise ValueError("box must have positive area within [0, 1]")

    def contains(self, other: Box) -> bool:
        return self.x0 <= other.x0 and self.y0 <= other.y0 and self.x1 >= other.x1 and self.y1 >= other.y1

    def intersects(self, other: Box) -> bool:
        return self.x0 < other.x1 and self.x1 > other.x0 and self.y0 < other.y1 and self.y1 > other.y0

    def union(self, other: Box) -> Box:
        """The smallest displayed-page box containing both boxes."""
        return Box(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def place(self, child: Box) -> Box:
        """Map crop-relative coordinates into this page region."""
        w, h = self.x1 - self.x0, self.y1 - self.y0
        return Box(self.x0 + child.x0 * w, self.y0 + child.y0 * h, self.x0 + child.x1 * w, self.y0 + child.y1 * h)


@dataclass(frozen=True, slots=True)
class Raster:
    data: bytes
    width: int
    height: int
    box: Box = field(default_factory=Box)
    media_type: str = "image/png"


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    box: Box | None = None
    confidence: float | None = None
    observation: str = ""


@dataclass(frozen=True, slots=True)
class Recognition:
    text: str
    configuration: dict[str, Any]
    raw: Any
    blocks: tuple[TextBlock, ...] = ()
    images: tuple[Raster, ...] = ()

    def __post_init__(self):
        if self.blocks and "\n".join(block.text for block in self.blocks) != self.text:
            raise ValueError("recognition blocks must preserve the complete recognition text")


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    text: str
    configuration: dict[str, Any]
    raw: Any
    blocks: tuple[TextBlock, ...]
    images: tuple[Raster, ...] = ()


@dataclass(frozen=True, slots=True)
class PageContent:
    blocks: tuple[TextBlock, ...]
    observations: tuple[Observation, ...]

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if block.text)


@dataclass(frozen=True, slots=True)
class TableObservation:
    """One detected table's geometry and cell text, kept beside a page's text.

    Built from PyMuPDF's ``page.find_tables()`` on the retained page (see
    ``pages.py::_PDFPage.find_tables``). Never merged into ``PageContent`` or
    ``PageResult.text``: the CRPT measurement (``docs/sources/govinfo-bodies.md``,
    "Why PDF is last") showed native text extraction emits every table label
    then every amount, destroying the row; a table observation is the row or
    nothing, not a guess folded back into the line-by-line text.
    """

    page: int
    bbox: Box
    row_count: int
    column_count: int
    #: Row-major cell text, exactly as PyMuPDF's ``Table.extract()`` returns
    #: it: ``""`` for a ruled, empty cell; ``None`` where PyMuPDF finds no
    #: cell region at all at that position (measured on a real committee
    #: report's total row, position 0 -- see the pinned real-page test in
    #: ``tests/extraction/test_api.py``), matching a ``None`` at the same
    #: position in ``cell_boxes`` below.
    cells: tuple[tuple[str | None, ...], ...]
    #: Row-major per-cell boxes in the same normalized displayed-page
    #: coordinates as ``TextBlock.box``. ``None`` exactly where ``cells`` is
    #: ``None`` at that position: no cell region there to place.
    cell_boxes: tuple[tuple[Box | None, ...], ...]
    #: The extractor's own confidence, when it states one. PyMuPDF's table
    #: finder does not, so this is ``None`` for every observation it produces.
    confidence: float | None = None

    def __post_init__(self):
        if self.page < 1:
            raise ValueError("table page must be 1 or greater")
        if self.row_count < 1 or self.column_count < 1:
            raise ValueError("table must have at least one row and one column")
        shape = (self.row_count, self.column_count)
        for name, rows in (("cells", self.cells), ("cell_boxes", self.cell_boxes)):
            if len(rows) != shape[0] or any(len(row) != shape[1] for row in rows):
                raise ValueError(f"{name} must be shaped row_count x column_count")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PageResult:
    metadata: dict[str, Any]
    content: PageContent
    #: Table geometry for the page, kept beside ``content`` and never merged
    #: into it. Empty unless the caller opted in (``DocumentExtractor(...,
    #: tables=True)``) and the retained page supports table detection.
    tables: tuple[TableObservation, ...] = ()

    @property
    def text(self) -> str:
        return self.content.text


class ImageBackend(Protocol):
    def recognize(self, image: Raster) -> Recognition: ...


class Page(Protocol):
    number: int
    geometry: dict[str, Any]
    has_native_layer: bool

    def native(self) -> Recognition: ...
    def render(self) -> Raster: ...
    def find_tables(self) -> tuple[TableObservation, ...]: ...


class Document(Protocol):
    page_count: int

    def page(self, number: int) -> Page: ...


class DocumentReader(Protocol):
    def open(self, source: bytes, media_type: str) -> AbstractContextManager[Document]: ...


class PageStrategy(Protocol):
    def extract(self, page: Page) -> PageContent: ...


class Extractor(Protocol):
    def extract(
        self,
        source: bytes,
        *,
        media_type: str,
        pages: Sequence[int] | None = None,
        overrides: Mapping[int, PageStrategy] | None = None,
    ) -> Iterator[PageResult]: ...
