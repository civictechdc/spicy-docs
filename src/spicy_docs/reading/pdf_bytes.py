"""The two PDF facts every document route checks: the magic header and the trailer.

Publishers state ``application/pdf`` or ``application/octet-stream`` for the
same file, so the media type proves nothing; the bytes do. ``%PDF-x.y`` at the
start proves the format, and ``%%EOF`` inside the last kilobyte proves the
capture reached the file's end, which a Content-Length cannot when the
publisher omits it. Publisher-specific completeness witnesses (a signature's
byte range, a linearization length, a declared size) stay with their routes.
"""

from __future__ import annotations

import re

PDF_MAGIC = b"%PDF-"
_PDF_HEADER = re.compile(rb"%PDF-([0-9]\.[0-9])")
TRAILER_WINDOW = 1024


def check_pdf_bytes(body: bytes, *, error_type: type[ValueError], label: str) -> str:
    """Refuse empty bytes, a non-``%PDF-`` start, or a missing trailer; return the stated version.

    The ``%%EOF`` check covers the last 1024 bytes, which a publisher-omitted
    Content-Length cannot prove.
    """
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise error_type(f"{label} response is empty; a nonempty PDF was requested")
    header = _PDF_HEADER.match(body)
    if header is None:
        raise error_type(f"{label} does not begin with the %PDF- magic")
    if b"%%EOF" not in bytes(body[-TRAILER_WINDOW:]):
        raise error_type(f"{label} does not end with a PDF trailer; the capture is incomplete")
    return header[1].decode("ascii")
