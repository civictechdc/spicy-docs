"""Lazy PDF rendering and image decoding; all optional imports stay at use sites."""

from __future__ import annotations

import io
import math
from contextlib import contextmanager
from importlib.metadata import version

from .model import Box, ExtractionError, Raster, Recognition, TextBlock


def _png(image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def crop(image: Raster, box: Box) -> Raster:
    from PIL import Image

    with Image.open(io.BytesIO(image.data)) as source:
        bounds = (
            math.floor(box.x0 * source.width),
            math.floor(box.y0 * source.height),
            math.ceil(box.x1 * source.width),
            math.ceil(box.y1 * source.height),
        )
        part = source.crop(bounds)
        actual = Box(
            bounds[0] / source.width, bounds[1] / source.height, bounds[2] / source.width, bounds[3] / source.height
        )
        return Raster(_png(part), part.width, part.height, image.box.place(actual))


class DefaultReader:
    def __init__(self, *, dpi: int = 200, max_pixels: int = 20_000_000):
        if not 36 <= dpi <= 1200 or max_pixels < 1:
            raise ValueError("dpi must be 36..1200 and max_pixels must be positive")
        self.dpi, self.max_pixels = dpi, max_pixels

    @contextmanager
    def open(self, source: bytes, media_type: str):
        if media_type == "application/pdf":
            import pymupdf

            with pymupdf.open(stream=source, filetype="pdf") as document:
                if document.needs_pass:
                    raise ExtractionError("encrypted PDF requires decryption before extraction")
                yield _PDF(document, self)
        else:
            from PIL import Image

            with Image.open(io.BytesIO(source)) as document:
                actual = Image.MIME.get(document.format)
                if actual != media_type:
                    raise ValueError(f"image bytes have media type {actual}, not {media_type}")
                yield _Images(document, self)

    def check_pixels(self, width: int, height: int):
        if width < 1 or height < 1 or width * height > self.max_pixels:
            raise ExtractionError("render exceeds max_pixels; reduce DPI or choose a larger explicit limit")


class _PDF:
    def __init__(self, document, reader):
        self.document, self.reader, self.page_count = document, reader, len(document)

    def page(self, number):
        return _PDFPage(self.document[number - 1], number, self.reader)


class _PDFPage:
    has_native_layer = True

    def __init__(self, page, number, reader):
        self.page, self.number, self.reader = page, number, reader
        self.geometry = {
            "kind": "pdf",
            "rotation": page.rotation,
            "cropbox": list(page.cropbox),
            "mediabox": list(page.mediabox),
            "display_rect": list(page.rect),
            "dpi": reader.dpi,
        }

    def native(self):
        import pymupdf

        # Image bytes are retained by the source, not duplicated into native text extraction.
        raw = self.page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
        blocks = []
        width, height = self.page.rect.width, self.page.rect.height
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"])
                rect = pymupdf.Rect(line["bbox"]) * self.page.rotation_matrix
                rect &= self.page.rect
                if rect.is_empty:
                    if text.strip():
                        raise ExtractionError("native text falls outside displayed page bounds", details=line)
                    continue
                box = Box(rect.x0 / width, rect.y0 / height, rect.x1 / width, rect.y1 / height)
                blocks.append(TextBlock(text, box))
        return Recognition(
            "\n".join(b.text for b in blocks),
            {"backend": "pymupdf", "version": version("pymupdf"), "sort": False},
            raw,
            tuple(blocks),
        )

    def render(self):
        width = math.ceil(self.page.rect.width * self.reader.dpi / 72)
        height = math.ceil(self.page.rect.height * self.reader.dpi / 72)
        self.reader.check_pixels(width, height)
        pix = self.page.get_pixmap(dpi=self.reader.dpi, alpha=False)
        self.reader.check_pixels(pix.width, pix.height)
        return Raster(pix.tobytes("png"), pix.width, pix.height)


class _Images:
    def __init__(self, document, reader):
        self.document, self.reader = document, reader
        self.page_count = getattr(document, "n_frames", 1)

    def page(self, number):
        from PIL import Image, ImageOps

        self.document.seek(number - 1)
        self.reader.check_pixels(self.document.width, self.document.height)
        geometry = {
            "kind": "image",
            "original_size": list(self.document.size),
            "exif_orientation": self.document.getexif().get(274, 1),
            "pillow_version": version("pillow"),
            "background": "white",
        }
        oriented = ImageOps.exif_transpose(self.document)
        if "A" in oriented.getbands() or "transparency" in oriented.info:
            rgba = oriented.convert("RGBA")
            oriented = Image.new("RGB", rgba.size, "white")
            oriented.paste(rgba, mask=rgba.getchannel("A"))
        else:
            oriented = oriented.convert("RGB")
        geometry["display_size"] = list(oriented.size)
        return _ImagePage(oriented, number, geometry)


class _ImagePage:
    has_native_layer = False

    def __init__(self, image, number, geometry):
        self.image, self.number, self.geometry = image, number, geometry

    def native(self):
        raise ExtractionError("image has no native text layer")

    def render(self):
        return Raster(_png(self.image), self.image.width, self.image.height)
