"""Pure parsing of CourtListener's bulk-object listing and filename conventions.

Publisher revision markers remain exact source values. They help compare two
listings; they neither hash object content nor pin a later HTTP transfer.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

# Downloads use the public alias, which does not answer the listing API.
# Enumeration therefore uses the S3 bucket host below.
BULK_BASE_URL = "https://storage.courtlistener.com/bulk-data"
BULK_LIST_URL = "https://com-courtlistener-storage.s3.amazonaws.com/"
BULK_PREFIX = "bulk-data/"
MAX_LISTING_PAGE_BYTES = 8 * 1024**2

_NAMESPACE = "http://s3.amazonaws.com/doc/2006-03-01/"
_BUCKET = "com-courtlistener-storage"
_MEDIA_TYPES = {
    ".csv.bz2": "application/x-bzip2",
    ".csv": "text/csv",
    ".sql": "application/sql",
    ".sh": "application/x-sh",
    ".zip": "application/zip",
}


def _filename_parts(filename: str) -> tuple[str, date | None, str]:
    suffix = next((ending for ending in _MEDIA_TYPES if filename.endswith(ending)), "")
    stem = filename[: -len(suffix)] if suffix else filename
    media_type = _MEDIA_TYPES.get(suffix, "application/octet-stream")
    if len(stem) > 11 and stem[-11] == "-":
        tail = stem[-10:]
        try:
            parsed = date.fromisoformat(tail)
        except ValueError:
            pass
        else:
            if parsed.isoformat() == tail:
                return stem[:-11], parsed, media_type
    return stem, None, media_type


@dataclass(frozen=True, slots=True)
class BulkObject:
    """One listed object, including its exact XML-decoded ETag and timestamp."""

    key: str
    size: int
    etag: str
    last_modified: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.startswith(BULK_PREFIX):
            raise ValueError("bulk object key must stay under bulk-data/")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("bulk object size must be a non-negative integer")
        for label, value in (("ETag", self.etag), ("last-modified stamp", self.last_modified)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"bulk object is missing {label}")
        try:
            modified = datetime.fromisoformat(self.last_modified)
        except ValueError as error:
            raise ValueError("bulk object last-modified stamp is not an ISO timestamp") from error
        if modified.tzinfo is None:
            raise ValueError("bulk object last-modified stamp must include a timezone")

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    @property
    def dataset(self) -> str | None:
        return _filename_parts(self.filename)[0] or None

    @property
    def dump_date(self) -> date | None:
        """A YYYY-MM-DD filename suffix, or None for an undated export."""
        return _filename_parts(self.filename)[1]

    @property
    def media_type(self) -> str:
        return _filename_parts(self.filename)[2]

    @property
    def url(self) -> str:
        relative_key = self.key[len(BULK_PREFIX) :]
        if any(part in {".", ".."} for part in relative_key.split("/")):
            raise ValueError("bulk object key has a dot path segment; its download URL would be ambiguous")
        return f"{BULK_BASE_URL}/{quote(relative_key, safe='/')}"

    @property
    def transport_version(self) -> str:
        """Combine listed revision markers; this is not a content digest."""
        return f"s3-listing:{self.etag}:{self.size}:{self.last_modified}"


def _text(node: ET.Element, tag: str) -> str:
    fields = node.findall(f"{{{_NAMESPACE}}}{tag}")
    if len(fields) != 1 or fields[0].text is None or not fields[0].text.strip():
        raise ValueError(f"bulk listing must carry one nonempty {tag}")
    return fields[0].text


def parse_listing_page(payload: bytes, *, prefix: str = BULK_PREFIX) -> tuple[tuple[BulkObject, ...], str | None]:
    """Read one bounded S3 listing page, preserving order and publisher values.

    The continuation token is None only when IsTruncated explicitly says false.
    Callers own traversal or captured-page admission; one page alone cannot
    establish that they retained the complete listing.
    """
    if not isinstance(prefix, str) or not prefix.startswith(BULK_PREFIX):
        raise ValueError("bulk listing prefix must stay under bulk-data/")
    if len(payload) > MAX_LISTING_PAGE_BYTES:
        raise ValueError(f"bulk listing page exceeds the {MAX_LISTING_PAGE_BYTES}-byte limit")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError("bulk listing page is not well-formed XML") from error
    if root.tag != f"{{{_NAMESPACE}}}ListBucketResult" or _text(root, "Name") != _BUCKET:
        raise ValueError("bulk listing page does not name the CourtListener S3 bucket")
    if _text(root, "Prefix") != prefix:
        raise ValueError(f"bulk listing page does not cover the requested prefix {prefix!r}")
    truncated = _text(root, "IsTruncated")
    if truncated not in {"true", "false"}:
        raise ValueError("bulk listing IsTruncated must be true or false")
    token = _text(root, "NextContinuationToken") if truncated == "true" else None
    objects = []
    seen: set[str] = set()
    for node in root.findall(f"{{{_NAMESPACE}}}Contents"):
        key = _text(node, "Key")
        if not key.startswith(prefix):
            raise ValueError(f"bulk listing key escapes the requested prefix: {key}")
        if key in seen:
            raise ValueError(f"bulk listing repeats object key: {key}")
        seen.add(key)
        size = _text(node, "Size")
        if not size.isascii() or not size.isdecimal():
            raise ValueError("bulk listing Size must be a non-negative decimal integer")
        objects.append(
            BulkObject(
                key=key,
                size=int(size),
                etag=_text(node, "ETag"),
                last_modified=_text(node, "LastModified"),
            )
        )
    return tuple(objects), token
