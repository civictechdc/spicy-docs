"""Media types stated by publishers, with a deterministic URL-suffix fallback to application/octet-stream."""

from pathlib import PurePosixPath
from urllib.parse import urlsplit

_ALIASES = {
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "htm": "text/html",
    "html": "text/html",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "xml": "application/xml",
    "json": "application/json",
    "xhtml": "application/xhtml+xml",
    "csv": "text/csv",
    "ics": "text/calendar",
    "fec": "text/plain",
    "zip": "application/zip",
    "gz": "application/gzip",
    "bz2": "application/x-bzip2",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
}


def media_type_policy() -> dict[str, object]:
    """Describe rendition typing in the source's hashed acquisition policy."""
    return {
        "aliases": dict(_ALIASES),
        "statedType": "trim-and-lowercase; accept-media-type-or-known-alias-before-url-inference",
        "locatorInference": "known-final-url-path-suffix; ignore-query-fragment-and-directory-names",
        "fallback": "application/octet-stream",
    }


def media_type(value: object, locator: str) -> str:
    """The stated type or a known alias, else the locator's final path suffix, else octet-stream."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if "/" in normalized:
            return normalized
        if normalized in _ALIASES:
            return _ALIASES[normalized]
    try:
        path = urlsplit(locator).path
    except ValueError:
        return "application/octet-stream"
    suffix = "" if path.endswith("/") else PurePosixPath(path).suffix
    if suffix:
        return media_type(suffix[1:], "")
    return "application/octet-stream"
