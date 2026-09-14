import runpy
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from spicy_docs.extraction import (
    Box,
    DefaultReader,
    DocumentExtractor,
    ExtractionError,
    FullPage,
    NativeText,
    NativeWithRegions,
    Recognition,
    TextBlock,
)
from spicy_docs.transport.credentials import CredentialRefusedError


def png(size=(100, 80)):
    out = BytesIO()
    Image.new("RGB", size, "white").save(out, format="PNG")
    return out.getvalue()


def pdf(*, rotation=0):
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.insert_text((30, 40), "Native heading")
        page.insert_text((30, 340), "Keep this sentence.")
        page.insert_image(pymupdf.Rect(30, 80, 270, 160), stream=png())
        page.set_rotation(rotation)
        document.new_page(width=300, height=400)
        return document.tobytes()


class Backend:
    def __init__(self, text="Image observation"):
        self.text, self.images = text, []

    def recognize(self, image):
        self.images.append(image)
        return Recognition(
            self.text, {"backend": "test"}, {"original": self.text}, (TextBlock(self.text, Box(0.1, 0.2, 0.8, 0.9)),)
        )


def test_native_pdf_source_identity_and_blank_control():
    source = pdf()
    results = list(DocumentExtractor(NativeText()).extract(source, media_type="application/pdf"))
    assert results[0].text == "Native heading\nKeep this sentence."
    assert results[0].metadata["source_sha256"] == sha256(source).hexdigest()
    assert results[0].metadata["page"] == 1
    assert results[0].content.observations[0].raw["blocks"]
    assert results[1].text == ""
    assert results[1].metadata["page"] == 2
    assert not results[0].content.observations[0].images


def test_image_and_pdf_share_backend_and_override_api():
    backend = Backend()
    extractor = DocumentExtractor(NativeText())
    source = pdf()
    results = list(extractor.extract(source, media_type="application/pdf", overrides={2: FullPage(backend)}))
    assert "Native heading" in results[0].text
    assert results[1].text == "Image observation"
    assert len(backend.images) == 1
    image = next(DocumentExtractor(FullPage(backend)).extract(png(), media_type="image/png"))
    assert image.text == results[1].text
    assert image.metadata["geometry"]["display_size"] == [100, 80]
    assert backend.images[-1].width == 100  # Images are not upscaled to PDF DPI.
    with pytest.raises(ExtractionError, match="native extraction"):
        next(extractor.extract(png(), media_type="image/png"))


@pytest.mark.parametrize("pages", [[], [0], [3], [1, 1], [True], [1.0]])
def test_invalid_selection_is_rejected_before_recognition(pages):
    backend = Backend()
    with pytest.raises(ValueError):
        list(DocumentExtractor(FullPage(backend)).extract(pdf(), media_type="application/pdf", pages=pages))
    assert not backend.images


def test_reader_is_injected_lazy_and_closed_on_generator_close():
    events = []

    class Page:
        number, geometry, has_native_layer = 1, {}, True

        def native(self):
            events.append("native")
            return Recognition("x", {}, {}, (TextBlock("x", Box()),))

        def render(self):
            pytest.fail("native mode must not render")

    class Reader:
        @contextmanager
        def open(self, source, media_type):
            class Document:
                page_count = 1_000_000_000

                def page(self, number):
                    events.append(number)
                    return Page()

            events.append("open")
            try:
                yield Document()
            finally:
                events.append("close")

    stream = DocumentExtractor(NativeText(), reader=Reader()).extract(b"input", media_type="application/pdf")
    assert events == []
    assert next(stream).text == "x"
    stream.close()
    assert events == ["open", 1, "native", "close"]


def test_regions_keep_native_and_retain_replaced_observation():
    backend = Backend()
    region = Box(0, 0, 1, 0.18)
    result = next(
        DocumentExtractor(NativeWithRegions(backend, {1: [region]})).extract(
            pdf(), media_type="application/pdf", pages=[1]
        )
    )
    assert result.text == "Image observation\nKeep this sentence."
    assert result.content.observations[0].text == "Native heading\nKeep this sentence."
    assert len(result.content.observations) == 2
    block = result.content.blocks[0]
    actual_crop = backend.images[0].box
    assert block.box == actual_crop.place(Box(0.1, 0.2, 0.8, 0.9))
    assert block.observation == "region-1"
    assert result.content.observations[1].raw == {"original": "Image observation"}


@pytest.mark.parametrize("error_type", [ExtractionError, CredentialRefusedError])
def test_later_region_failure_retains_earlier_observations_without_completing_page(error_type):
    class FailsLater(Backend):
        def recognize(self, image):
            if self.images:
                raise error_type("second region failed")
            return super().recognize(image)

    regions = [Box(0, 0, 1, 0.2), Box(0, 0.5, 1, 0.7)]
    with pytest.raises(error_type) as error:
        next(
            DocumentExtractor(NativeWithRegions(FailsLater(), {2: regions})).extract(
                pdf(), media_type="application/pdf", pages=[2]
            )
        )
    observations = error.value.details["observations"]
    assert [o.id for o in observations] == ["native", "region-1"]
    assert observations[1].text == "Image observation"
    assert observations[1].images[0].data.startswith(b"\x89PNG")
    assert error.value.details["failed_image"].box.y0 >= 0.49


@pytest.mark.parametrize("regions", [[Box(0, 0, 1, 0.08)], [Box(0, 0, 1, 0.2), Box(0, 0.1, 1, 0.3)]])
def test_clipped_native_or_overlapping_regions_fail_before_model(regions):
    backend = Backend()
    with pytest.raises(ValueError):
        next(
            DocumentExtractor(NativeWithRegions(backend, {1: regions})).extract(
                pdf(), media_type="application/pdf", pages=[1]
            )
        )
    assert backend.images == []


def test_region_bound_is_enforced_and_accepts_its_limit():
    backend = Backend()
    boxes = [Box(0, i / 64, 1, (i + 1) / 64) for i in range(64)]
    # A one-pixel-per-strip render avoids introducing accidental rounding overlap.
    extractor = DocumentExtractor(NativeWithRegions(backend, {2: boxes}), reader=DefaultReader(dpi=72))
    with pymupdf.open() as document:
        document.new_page(width=64, height=64)
        document.new_page(width=64, height=64)
        source = document.tobytes()
    result = next(extractor.extract(source, media_type="application/pdf", pages=[2]))
    assert len(result.content.observations) == 65 and len(backend.images) == 64
    with pytest.raises(ValueError, match="at most 64"):
        next(
            DocumentExtractor(NativeWithRegions(backend, {2: boxes + [Box()]})).extract(
                source, media_type="application/pdf", pages=[2]
            )
        )
    assert len(backend.images) == 64


def test_empty_native_layer_can_receive_a_regional_observation():
    backend = Backend()
    result = next(
        DocumentExtractor(NativeWithRegions(backend, {2: [Box(0, 0, 1, 0.5)]})).extract(
            pdf(), media_type="application/pdf", pages=[2]
        )
    )
    assert result.text == "Image observation"


def test_crop_can_cross_native_whitespace_without_refusing_meaningful_region():
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.insert_text((30, 40), " ")
        page.insert_text((30, 100), "Preserve this line")
        source = document.tobytes()
    result = next(
        DocumentExtractor(NativeWithRegions(Backend(), {1: [Box(0, 0, 1, 0.1)]})).extract(
            source, media_type="application/pdf"
        )
    )
    assert "Preserve this line" in result.text
    assert result.content.observations[0].text == " \nPreserve this line"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_coordinates_follow_display_rotation(rotation):
    result = next(
        DocumentExtractor(NativeText()).extract(pdf(rotation=rotation), media_type="application/pdf", pages=[1])
    )
    first, last = result.content.blocks
    assert result.metadata["geometry"]["rotation"] == rotation
    if rotation == 0:
        assert first.box.y1 < last.box.y0
    elif rotation == 90:
        assert first.box.x0 > last.box.x1
    elif rotation == 180:
        assert first.box.y0 > last.box.y1
    else:
        assert first.box.x1 < last.box.x0


def test_bounds_and_image_content_type():
    backend = Backend()
    with pytest.raises(ValueError, match="max_input_bytes"):
        next(DocumentExtractor(FullPage(backend), max_input_bytes=1).extract(png(), media_type="image/png"))
    with pytest.raises(ExtractionError, match="max_pixels"):
        next(
            DocumentExtractor(FullPage(backend), reader=DefaultReader(max_pixels=10)).extract(
                png(), media_type="image/png"
            )
        )
    with pytest.raises(ValueError, match="media type"):
        next(DocumentExtractor(FullPage(backend)).extract(png(), media_type="image/jpeg"))
    assert not backend.images


def test_image_orientation_transparency_and_multiple_frames():
    backend = Backend()
    stream = BytesIO()
    image = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    exif = image.getexif()
    exif[274] = 6
    image.save(stream, format="PNG", exif=exif)
    result = next(DocumentExtractor(FullPage(backend)).extract(stream.getvalue(), media_type="image/png"))
    assert result.metadata["geometry"]["original_size"] == [30, 20]
    assert result.metadata["geometry"]["display_size"] == [20, 30]
    with Image.open(BytesIO(backend.images[-1].data)) as rendered:
        assert rendered.getpixel((0, 0)) == (255, 255, 255)

    stream = BytesIO()
    Image.new("RGB", (30, 20), "red").save(
        stream, format="TIFF", save_all=True, append_images=[Image.new("RGB", (30, 20), "blue")]
    )
    results = list(DocumentExtractor(FullPage(backend)).extract(stream.getvalue(), media_type="image/tiff"))
    assert [r.metadata["page"] for r in results] == [1, 2]
    assert all(r.metadata["page_count"] == 2 for r in results)
    assert results[0].metadata["source_sha256"] == results[1].metadata["source_sha256"]
    for image, expected in zip(backend.images[-2:], [(255, 0, 0), (0, 0, 255)], strict=True):
        with Image.open(BytesIO(image.data)) as rendered:
            assert rendered.getpixel((0, 0)) == expected


def test_recognition_cannot_silently_drop_body_when_blocks_are_supplied():
    with pytest.raises(ValueError, match="complete recognition text"):
        Recognition("all the text", {}, {}, (TextBlock("some text"),))


def test_offline_example_exercises_native_and_injected_paths():
    example = runpy.run_path(str(Path(__file__).parents[2] / "examples/pdf_extraction.py"))
    results = example["run_example"]()
    assert results[0]["metadata"]["strategy"] == "NativeText"
    assert results[1]["metadata"]["strategy"] == "FullPage"
    assert results[1]["observations"][0]["configuration"]["backend"] == "example-test-double"
