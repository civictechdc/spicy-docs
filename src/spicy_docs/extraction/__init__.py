"""Optional PDF/image extraction; importing this API loads no model or renderer."""

from .api import DocumentExtractor, FullPage, NativeText, NativeWithRegions
from .model import (
    Box,
    DocumentReader,
    ExtractionError,
    Extractor,
    ImageBackend,
    Observation,
    Page,
    PageContent,
    PageResult,
    PageStrategy,
    Raster,
    Recognition,
    TextBlock,
)
from .pages import DefaultReader

__all__ = [
    "Box",
    "DefaultReader",
    "DocumentExtractor",
    "DocumentReader",
    "ExtractionError",
    "Extractor",
    "FullPage",
    "ImageBackend",
    "NativeText",
    "NativeWithRegions",
    "Observation",
    "Page",
    "PageContent",
    "PageResult",
    "PageStrategy",
    "Raster",
    "Recognition",
    "TextBlock",
]
