"""Select declared equivalent renditions, resolve retained embedded text, and check original prefixes.

Equivalence is the caller's claim: an archive, filing, summary and PDF image are
different source units unless the caller establishes otherwise, and no URL is
ever guessed from one rendition to another.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from rulespec_artifacts import LocalBlobSource

from spicy_docs.reading.media_types import media_type
from spicy_docs.sources.fec.catalog import official_url
from spicy_docs.sources.fec.metadata import parse_api

FORMAT_ORDER = (
    "application/xml",
    "text/xml",
    "application/json",
    "application/xhtml+xml",
    "text/csv",
    "text/plain",
    "application/pdf",
    "text/html",
)


def choose_rendition(renditions: list[dict]) -> dict:
    """Choose only among caller-established equivalents, without guessing URLs.

    An archive, filing, summary and PDF image are different source units unless
    the caller establishes otherwise. Never pass unrelated collection links.
    Unknown native formats rank ahead of HTML, behind recognized structured text.
    """
    if not renditions:
        raise ValueError("no declared renditions to choose from")

    def rank(row: dict) -> int:
        official_url(row["url"])
        kind = media_type(row.get("media_type"), row["url"]).split(";", 1)[0]
        return FORMAT_ORDER.index(kind) if kind in FORMAT_ORDER else FORMAT_ORDER.index("text/html") - 1

    return min(renditions, key=rank)


def embedded_text(*, store: Path, sha256: str, source_pointer: str, max_bytes: int = 8 * 1024**2) -> str:
    """Verify a retained API response and resolve one JSON Pointer offline."""
    if type(max_bytes) is not int or max_bytes <= 0 or not source_pointer.startswith("/"):
        raise ValueError("embedded text needs a positive byte bound and an absolute JSON Pointer")
    with LocalBlobSource(store).open(sha256) as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("retained API response exceeds its byte bound")
    value = parse_api(raw)
    for token in source_pointer[1:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not key.isascii() or not key.isdecimal() or (len(key) > 1 and key.startswith("0")):
                raise ValueError("JSON Pointer has an invalid array index")
            value = value[int(key)]
        else:
            value = value[key]
    if not isinstance(value, str):
        raise TypeError("embedded body pointer does not identify source text")
    return value


def validate_original_prefix(chunk: bytes, *, url: str) -> None:
    """Check recognizable originals, without claiming to parse archive members."""
    path = urlsplit(url).path.lower()
    for suffix, signatures in (
        (".pdf", (b"%PDF-",)),
        (".zip", (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")),
        (".gz", (b"\x1f\x8b",)),
        (".bz2", (b"BZh",)),
    ):
        if path.endswith(suffix) and not chunk.startswith(signatures):
            raise ValueError("asset prefix does not match its selected original format")
    if path.endswith((".xml", ".xhtml")):
        parser = ET.XMLPullParser(events=("start",))
        try:
            parser.feed(chunk)
            first = next(parser.read_events(), None)
            if first is None or first[1].tag.lower() == "html":
                raise ValueError("selected XML original omitted its XML root or returned HTML")
        except ET.ParseError:
            raise ValueError("selected XML original has an invalid XML prefix") from None
