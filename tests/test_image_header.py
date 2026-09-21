"""Image-header parsing from the leading bytes: format and dimensions.

Covers PNG IHDR, GIF87a/GIF89a and JPEG frame markers, and proves malformed
marker boundaries and truncated prefixes never borrow another frame's
dimensions; complete encoder output agrees with an independent decoder.
"""

from io import BytesIO

import pytest

from spicy_docs.reading.image_header import ImageHeader, read_image_header

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x80\x00\x00\x01\xe0"
SOF = b"\xff\xc0\x00\x0b\x08\x01\xe0\x02\x80\x01\x01\x11\x00"


@pytest.mark.parametrize(
    "header,expected",
    [
        (PNG, ImageHeader("png", 640, 480)),
        (b"GIF87a\x80\x02\xe0\x01", ImageHeader("gif", 640, 480)),
        (b"GIF89a\x00\x00\x00\x00", ImageHeader("gif", 0, 0)),
        (b"\xff\xd8" + SOF, ImageHeader("jpeg", 640, 480)),
        (b"\xff\xd8\xff\xff\xff" + SOF, ImageHeader("jpeg", 640, 480)),
        (b"\xff\xd8\xff\x01" + SOF, ImageHeader("jpeg", 640, 480)),
        (b"\xff\xd8\xff\xe0\x00\x04xx" + SOF, ImageHeader("jpeg", 640, 480)),
        (b"RIFFxxxxWEBP", ImageHeader("unknown")),
        (b"", ImageHeader("unknown")),
    ],
)
def test_observed_headers(header, expected):
    """PNG, both GIF signatures and JPEG after filler segments detect; WEBP and empty bytes are unknown."""
    assert read_image_header(header) == expected


@pytest.mark.parametrize("header", [PNG[:12] + b"IDAT" + PNG[16:], PNG[:8] + b"\x00\x00\x00\x0c" + PNG[12:]])
def test_png_needs_ihdr_with_declared_length(header):
    """A PNG with the wrong chunk type or declared length still reports format png but no dimensions."""
    assert read_image_header(header) == ImageHeader("png")


@pytest.mark.parametrize(
    "prefix", [b"\xff\xd9", b"\xff\xda\x00\x02", b"junk", b"\xff\x00", b"\xff\xd8", b"\xff\xe0\x00\x01"]
)
def test_jpeg_cannot_borrow_dimensions_after_invalid_boundary(prefix):
    """An invalid marker or zero-length segment stops the scan, so a later frame cannot supply dimensions."""
    assert read_image_header(b"\xff\xd8" + prefix + SOF) == ImageHeader("jpeg")


@pytest.mark.parametrize("length", range(2, 7))
def test_jpeg_cannot_borrow_dimensions_after_short_first_frame(length):
    """A first frame too short to hold dimensions leaves them unset instead of reading a following frame."""
    first = b"\xff\xc0" + length.to_bytes(2, "big") + b"x" * (length - 2)
    assert read_image_header(b"\xff\xd8" + first + SOF) == ImageHeader("jpeg")


@pytest.mark.parametrize("header", [PNG, b"GIF89a\x80\x02\xe0\x01", b"\xff\xd8" + SOF])
def test_every_truncated_prefix_has_no_dimensions(header):
    """Every proper prefix of a real header reports no dimensions, and JPEG prefixes still report their format."""
    for size in range(len(header)):
        result = read_image_header(header[:size])
        assert result.width is result.height is None
        assert result.format == ("jpeg" if header[:size].startswith(b"\xff\xd8") else "unknown")


@pytest.mark.parametrize("marker", [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF])
def test_each_frame_marker_and_deferred_zero_height(marker):
    """Every SOF frame marker is recognized, and a declared height of zero is kept as ``0``, not treated as absent."""
    frame = bytes([0xFF, marker]) + SOF[2:5] + b"\x00\x00" + SOF[7:]
    assert read_image_header(b"\xff\xd8" + frame) == ImageHeader("jpeg", 640, 0)


@pytest.mark.parametrize("format", ["PNG", "GIF", "JPEG"])
def test_complete_encoder_output_agrees_with_independent_decoder(format):
    """On real encoder output, the parsed dimensions equal the decoder's size and the format is lowercased."""
    image = pytest.importorskip("PIL.Image")
    output = BytesIO()
    image.new("RGB", (31, 17), color=(12, 45, 78)).save(output, format=format)
    source = output.getvalue()
    observed = read_image_header(source)
    with image.open(BytesIO(source)) as decoded:
        decoded.load()
        assert (observed.width, observed.height) == decoded.size == (31, 17)
        assert observed.format == format.lower()
