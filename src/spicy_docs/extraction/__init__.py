"""Optional PDF/image extraction; importing this API loads no model or renderer."""

from .api import DocumentExtractor, FullPage, NativeText, NativeWithRegions
from .body_text import BodyText, BodyTextError, RenditionCleanup, body_text, rendition_text
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
    "BodyText",
    "BodyTextError",
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
    "RenditionCleanup",
    "TextBlock",
    "body_text",
    "rendition_text",
]
