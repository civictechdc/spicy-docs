"""Pure parsing of CourtListener's bulk-object listing and filename conventions.

Publisher revision markers remain exact source values. They help compare two
listings; they neither hash object content nor pin a later HTTP transfer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

from spicy_docs.reading.s3_listing import MAX_LISTING_PAGE_BYTES, parse_s3_listing

# Downloads use the public alias, which does not answer the listing API.
# Enumeration therefore uses the S3 bucket host below.
BULK_BASE_URL = "https://storage.courtlistener.com/bulk-data"
BULK_LIST_URL = "https://com-courtlistener-storage.s3.amazonaws.com/"
BULK_PREFIX = "bulk-data/"

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


def parse_listing_page(payload: bytes, *, prefix: str = BULK_PREFIX) -> tuple[tuple[BulkObject, ...], str | None]:
    """Read one bounded CourtListener page through the shared S3 parser."""
    if not isinstance(prefix, str) or not prefix.startswith(BULK_PREFIX):
        raise ValueError("bulk listing prefix must stay under bulk-data/")
    if len(payload) > MAX_LISTING_PAGE_BYTES:
        raise ValueError("bulk listing page exceeds its byte limit")
    objects, token = parse_s3_listing(payload, bucket=_BUCKET, prefix=prefix)
    return tuple(BulkObject(x.key, x.size, x.etag, x.last_modified) for x in objects), token
