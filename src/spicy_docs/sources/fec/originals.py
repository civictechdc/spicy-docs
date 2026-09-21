"""Shared validation of retained original capture facts, without format inference."""

import re
from collections.abc import Mapping
from datetime import datetime

from rulespec_artifacts import canonical_json_bytes

from spicy_docs.sources.fec.catalog import official_url
from spicy_docs.sources.fec.retained import MAX_SCOPE_BYTES

MAX_FILE_BYTES = 64 * 1024**3
_REQUIRED = {"requestUrl", "observedAt", "responseSha256", "byteSize", "representation"}
_OPTIONAL_FIELDS = {
    "resolvedUrl",
    "mediaType",
    "via",
    "etag",
    "lastModified",
    "contentEncoding",
    "contentLength",
    "objectKey",
}


def original_capture(capture):
    """Validate one retained original capture's URL, digest, size, timezone and representation, returning a copy."""
    if not isinstance(capture, Mapping) or not _REQUIRED <= set(capture) <= _REQUIRED | _OPTIONAL_FIELDS:
        raise ValueError("FEC original capture fields differ")
    value = dict(capture)
    for name in ("requestUrl", "resolvedUrl"):
        if name in value:
            if not isinstance(value[name], str) or len(value[name]) > 16 * 1024:
                raise ValueError("FEC original URL must be bounded text")
            official_url(value[name])
    if value["representation"] not in ("zip", "opaque"):
        raise ValueError("FEC representation must be explicitly zip or opaque")
    if type(value["byteSize"]) is not int or not 0 < value["byteSize"] <= MAX_FILE_BYTES:
        raise ValueError("FEC bulk original size exceeds its bound")
    if (
        not isinstance(value["responseSha256"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value["responseSha256"]) is None
    ):
        raise ValueError("FEC bulk original digest is invalid")
    try:
        instant = datetime.fromisoformat(value["observedAt"])
    except (TypeError, ValueError) as error:
        raise ValueError("FEC bulk observation time is invalid") from error
    if instant.utcoffset() is None:
        raise ValueError("FEC bulk observation time must include a timezone")
    if any(not isinstance(value[field], str) for field in _OPTIONAL_FIELDS if field in value):
        raise ValueError("FEC bulk optional capture facts must be source strings")
    if "contentLength" in value:
        if re.fullmatch(r"[0-9]+", value["contentLength"]) is None:
            raise ValueError("FEC bulk Content-Length is not a nonnegative integer")
        if (
            value.get("contentEncoding", "").strip().lower() == "identity"
            and int(value["contentLength"]) != value["byteSize"]
        ):
            raise ValueError("FEC bulk identity Content-Length differs from captured byte size")
    if len(canonical_json_bytes(value)) > MAX_SCOPE_BYTES:
        raise ValueError("FEC original capture exceeds its metadata bound")
    return value
