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
class PageResult:
    metadata: dict[str, Any]
    content: PageContent

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
