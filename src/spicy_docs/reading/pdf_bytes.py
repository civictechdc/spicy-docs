"""The PDF facts document routes check: the magic header, the trailer, the linearization length and the final xref.

Publishers state ``application/pdf`` or ``application/octet-stream`` for the
same file, so the media type proves nothing; the bytes do. ``%PDF-x.y`` at the
start proves the format, and ``%%EOF`` inside the last kilobyte proves the
capture reached the file's end, which a Content-Length cannot when the
publisher omits it. :func:`linearized_length` and :func:`terminal_xref_offset`
read two further completeness witnesses; whether a route requires them stays
with the route.
"""

from __future__ import annotations

import re

PDF_MAGIC = b"%PDF-"
_PDF_HEADER = re.compile(rb"%PDF-([0-9]\.[0-9])")
TRAILER_WINDOW = 1024
#: A linearization dictionary sits in the first object, so its ``/L`` is read from the first 2 KiB only.
_LINEARIZED_LENGTH = re.compile(rb"/Linearized[^>]{0,64}?/L\s+([0-9]+)")
_LINEARIZATION_WINDOW = 2048
_FINAL_XREF = re.compile(rb"startxref\s+([0-9]+)\s+%%EOF\s*\Z")
_XREF_OBJECT = re.compile(rb"[0-9]+\s+[0-9]+\s+obj\s*<<")
_XREF_HEADER_WINDOW = 2048


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


def linearized_length(body: bytes) -> int | None:
    """The file length a linearization dictionary states (``/L``), or None for a PDF that is not linearized."""
    stated = _LINEARIZED_LENGTH.search(body, 0, _LINEARIZATION_WINDOW)
    return int(stated[1]) if stated else None


def terminal_xref_offset(body: bytes) -> int | None:
    """The final ``startxref`` offset when it names a cross-reference table or stream inside ``body``, else None.

    The file must end ``startxref N %%EOF``, and ``N`` must point inside the
    capture at an ``xref`` table or an object whose dictionary states
    ``/Type/XRef`` before its stream, which rejects the ``startxref 0`` a
    linearized file's first-page section carries. This is a bounded
    completeness check, not a PDF parser or a semantic-validity claim.
    """
    trailer = _FINAL_XREF.search(body, max(0, len(body) - TRAILER_WINDOW))
    if trailer is None:
        return None
    offset = int(trailer[1])
    if not 0 < offset < trailer.start():
        return None
    header = body[offset : min(offset + _XREF_HEADER_WINDOW, trailer.start())]
    if re.match(rb"xref\s", header):
        return offset
    if _XREF_OBJECT.match(header) is None or (stream := re.search(rb"\bstream(?:\r\n|\r|\n)", header)) is None:
        return None
    dictionary = header[: stream.start()]
    if (
        dictionary.rstrip().endswith(b">>")
        and re.search(rb"\bendobj\b", dictionary) is None
        and re.search(rb"/Type\s*/XRef(?=[\x00\t\n\f\r ()<>\[\]{}/%])", dictionary) is not None
    ):
        return offset
    return None
