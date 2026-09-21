"""Read declared PNG/GIF/JPEG dimensions without decoding image data.

Header observations, not proof of validity or completeness: GIF reports the logical screen, JPEG the
first frame before scan data, and an unsupported or truncated header keeps the format with no dimensions.
No EXIF orientation, PNG CRC, later JPEG DNL, or animation frames are applied.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ImageHeader:
    format: Literal["png", "gif", "jpeg", "unknown"]
    width: int | None = None
    height: int | None = None


def read_image_header(content: bytes) -> ImageHeader:
    """Observe header fields, retaining zero values exactly as declared.

    PNG needs its first 24 bytes and GIF its first 10; JPEG needs a complete
    declared frame segment, and a recognized-but-incomplete header keeps its
    format with no dimensions. Runtime is O(header bytes), with constant
    auxiliary memory.
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        if content[8:12] != b"\x00\x00\x00\r" or content[12:16] != b"IHDR":
            return ImageHeader("png")
        return ImageHeader("png", int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big"))
    if content[:6] in {b"GIF87a", b"GIF89a"} and len(content) >= 10:
        return ImageHeader("gif", int.from_bytes(content[6:8], "little"), int.from_bytes(content[8:10], "little"))
    if content.startswith(b"\xff\xd8"):
        dimensions = _jpeg_dimensions(content)
        return ImageHeader("jpeg", *dimensions) if dimensions is not None else ImageHeader("jpeg")
    return ImageHeader("unknown")


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    """Scan marker segments to the first start-of-frame; ``None`` before scan data or any malformed segment."""
    position = 2
    start_of_frame = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
    while position < len(content):
        if content[position] != 0xFF:
            return None
        # T.81 permits any number of FF fill bytes before a marker.
        while position < len(content) and content[position] == 0xFF:
            position += 1
        if position == len(content):
            return None
        marker = content[position]
        position += 1
        if marker in {0x00, 0xD8, 0xD9, 0xDA}:
            return None
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(content):
            return None
        length = int.from_bytes(content[position : position + 2], "big")
        if length < 2 or position + length > len(content):
            return None
        if marker in start_of_frame:
            if length < 7:
                return None
            return (
                int.from_bytes(content[position + 5 : position + 7], "big"),
                int.from_bytes(content[position + 3 : position + 5], "big"),
            )
        position += length
    return None
