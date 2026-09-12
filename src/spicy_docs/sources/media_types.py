"""Media types stated by publishers, with a deterministic extension fallback."""

from pathlib import PurePosixPath
from urllib.parse import urlsplit


def media_type(value: object, locator: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if "/" in normalized:
            return normalized
        aliases = {
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
        if normalized in aliases:
            return aliases[normalized]
    path = urlsplit(locator).path
    suffix = "" if path.endswith("/") else PurePosixPath(path).suffix
    if suffix:
        return media_type(suffix[1:], "")
    return "application/octet-stream"
