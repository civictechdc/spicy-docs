"""Read an explicitly scoped public S3 XML listing without fetching objects."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

MAX_LISTING_PAGE_BYTES = 8 * 1024**2
NAMESPACE = "http://s3.amazonaws.com/doc/2006-03-01/"


@dataclass(frozen=True, slots=True)
class ListedObject:
    key: str
    size: int
    etag: str
    last_modified: str


def parse_s3_listing(payload: bytes, *, bucket: str, prefix: str) -> tuple[tuple[ListedObject, ...], str | None]:
    """Require the requested bucket/prefix and an explicit terminal marker.

    ETags are publisher validators, not assumed content hashes. The caller owns
    traversal; an individual response does not establish a complete snapshot.
    """
    if len(payload) > MAX_LISTING_PAGE_BYTES:
        raise ValueError("bulk listing page exceeds its byte limit")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError("bulk listing is not well-formed XML") from error

    def text(node: ET.Element, name: str) -> str:
        fields = node.findall(f"{{{NAMESPACE}}}{name}")
        if len(fields) != 1 or not fields[0].text or not fields[0].text.strip():
            raise ValueError(f"bulk listing must carry one nonempty {name}")
        return fields[0].text

    if root.tag != f"{{{NAMESPACE}}}ListBucketResult" or text(root, "Name") != bucket:
        raise ValueError("bulk listing does not name the requested S3 bucket")
    if text(root, "Prefix") != prefix:
        raise ValueError("bulk listing does not cover the requested prefix")
    if root.find(f"{{{NAMESPACE}}}CommonPrefixes") is not None:
        raise ValueError("flat bulk listing unexpectedly grouped keys into prefixes")
    truncated = text(root, "IsTruncated")
    if truncated not in {"true", "false"}:
        raise ValueError("bulk listing IsTruncated must be true or false")
    token = text(root, "NextContinuationToken") if truncated == "true" else None
    objects = []
    seen = set()
    for node in root.findall(f"{{{NAMESPACE}}}Contents"):
        key = text(node, "Key")
        if not key.startswith(prefix):
            raise ValueError("bulk listing key escapes the requested prefix")
        if key in seen:
            raise ValueError("bulk listing repeats object key")
        seen.add(key)
        size = text(node, "Size")
        if not size.isascii() or not size.isdecimal():
            raise ValueError("bulk listing Size must be a non-negative decimal integer")
        stamp = text(node, "LastModified")
        try:
            if datetime.fromisoformat(stamp).tzinfo is None:
                raise ValueError("timezone missing")
        except ValueError as error:
            raise ValueError("bulk listing last-modified stamp must be a timezone-aware ISO date") from error
        objects.append(ListedObject(key, int(size), text(node, "ETag"), stamp))
    return tuple(objects), token
