"""Page streaming and composition, independent of recognition providers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace

from spicy_docs.transport.credentials import CredentialRefusedError

from .model import (
    Box,
    DocumentReader,
    ExtractionError,
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


def _observation(id: str, recognition: Recognition, image: Raster | None = None) -> Observation:
    # Provider block coordinates are relative to the supplied image, not the PDF.
    blocks = recognition.blocks or ((TextBlock(recognition.text, Box()),) if recognition.text else ())
    blocks = tuple(replace(b, box=image.box.place(b.box) if image and b.box else b.box, observation=id) for b in blocks)
    return Observation(
        id,
        recognition.text,
        recognition.configuration,
        recognition.raw,
        blocks,
        recognition.images or ((image,) if image else ()),
    )


@dataclass(frozen=True)
class NativeText:
    def extract(self, page: Page) -> PageContent:
        if not page.has_native_layer:
            raise ExtractionError("native extraction requires a PDF text layer; choose an image backend")
        observation = _observation("native", page.native())
        return PageContent(observation.blocks, (observation,))


@dataclass(frozen=True)
class FullPage:
    backend: ImageBackend

    def extract(self, page: Page) -> PageContent:
        image = page.render()
        observation = _observation("full", self.backend.recognize(image), image)
        return PageContent(observation.blocks, (observation,))


@dataclass(frozen=True)
class NativeWithRegions:
    backend: ImageBackend
    regions: Mapping[int, Sequence[Box]]

    def extract(self, page: Page) -> PageContent:
        from .pages import crop

        native = NativeText().extract(page).observations[0]
        selected = tuple(self.regions.get(page.number, ()))
        if not selected:
            return PageContent(native.blocks, (native,))
        if len(selected) > 64:
            raise ValueError("select at most 64 regions per page")
        if any(a.intersects(b) for i, a in enumerate(selected) for b in selected[i + 1 :]):
            raise ValueError("selected regions overlap")
        image = page.render()
        crops = tuple(crop(image, box) for box in selected)
        # Check actual pixel-rounded crop bounds before any paid/model operation.
        actual = tuple(c.box for c in crops)
        if any(a.intersects(b) for i, a in enumerate(actual) for b in actual[i + 1 :]):
            raise ValueError("pixel-rounded regions overlap")
        kept = []
        for block in native.blocks:
            if block.box is None:
                if block.text:
                    raise ExtractionError("regional composition requires native block coordinates")
                continue
            intersects = [box for box in actual if box.intersects(block.box)]
            if intersects and not any(box.contains(block.box) for box in intersects):
                if block.text.strip():
                    raise ValueError("selected region clips a native text line")
                # PDF producers often emit whitespace lines across otherwise empty gaps.
                kept.append(block)
            elif not intersects:
                kept.append(block)
        observations = [native]
        for i, raster in enumerate(crops, 1):
            try:
                observation = _observation(f"region-{i}", self.backend.recognize(raster), raster)
            except (ExtractionError, CredentialRefusedError) as exc:
                exc.details = {"observations": tuple(observations), "failed_image": raster, "failure": exc.details}
                raise
            observations.append(observation)
            kept.extend(observation.blocks)
        kept.sort(key=lambda b: (b.box.y0, b.box.x0) if b.box else (0, 0))
        return PageContent(tuple(kept), tuple(observations))


class DocumentExtractor:
    """One API for PDFs and images; caller owns acquisition and result retention.

    Iterate to exhaustion or close the returned generator to release the document.
    A failure after earlier yielded pages does not make the whole document complete.
    ``tables=True`` runs PyMuPDF's ``find_tables()`` on each retained PDF page
    and attaches the result to ``PageResult.tables``, independent of ``strategy``
    and never merged into ``PageResult.text``; it costs nothing extra for image
    input (``PageResult.tables`` stays empty) and defaults to ``False`` so no
    existing caller's output changes.
    """

    def __init__(
        self,
        strategy: PageStrategy,
        *,
        reader: DocumentReader | None = None,
        max_input_bytes: int = 64 * 1024**2,
        tables: bool = False,
    ):
        if max_input_bytes < 1:
            raise ValueError("max_input_bytes must be positive")
        if reader is None:
            from .pages import DefaultReader

            reader = DefaultReader()
        self.strategy, self.reader, self.max_input_bytes, self.tables = strategy, reader, max_input_bytes, tables

    def extract(
        self,
        source: bytes,
        *,
        media_type: str,
        pages: Sequence[int] | None = None,
        overrides: Mapping[int, PageStrategy] | None = None,
    ) -> Iterator[PageResult]:
        if not isinstance(source, bytes) or not source or len(source) > self.max_input_bytes:
            raise ValueError("source must be nonempty bytes within max_input_bytes")
        media_type = media_type.partition(";")[0].strip().lower()
        if media_type != "application/pdf" and not media_type.startswith("image/"):
            raise ValueError("expected application/pdf or an image media type")
        digest = hashlib.sha256(source).hexdigest()
        with self.reader.open(source, media_type) as document:
            selected = range(1, document.page_count + 1) if pages is None else tuple(pages)
            selected_members = selected if pages is None else set(selected)
            if not selected or len(selected_members) != len(selected):
                raise ValueError("select at least one distinct page")
            if pages is not None and any(type(n) is not int or not 1 <= n <= document.page_count for n in selected):
                raise ValueError("page selection is outside the document")
            if overrides and any(type(n) is not int or n not in selected_members for n in overrides):
                raise ValueError("page override is outside the selected pages")
            for number in selected:
                page = document.page(number)
                strategy = (overrides or {}).get(number, self.strategy)
                content = strategy.extract(page)
                yield PageResult(
                    {
                        "source_sha256": digest,
                        "source_size_bytes": len(source),
                        "media_type": media_type,
                        "page": number,
                        "page_count": document.page_count,
                        "geometry": page.geometry,
                        "strategy": type(strategy).__name__,
                        "coordinates": "normalized displayed page; top-left origin",
                    },
                    content,
                    page.find_tables() if self.tables else (),
                )
