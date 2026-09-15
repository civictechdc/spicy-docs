"""Bounded retained JSON pages shared by FEC release profiles.

These helpers preserve byte evidence and one explicitly pinned ordinary-page
query. Each source profile supplies its endpoint, identity and coverage policy.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from rulespec_artifacts import BlobSource, canonical_json_bytes

from spicy_docs.releases.format import MAX_ROW_BYTES
from spicy_docs.sources.evidence_zip import deterministic_zip_entry, has_deterministic_zip_metadata
from spicy_docs.sources.fec.catalog import MAX_METADATA_BYTES, official_url
from spicy_docs.sources.fec.metadata import api_page, parse_api, split_record
from spicy_docs.sources.json_input import load_integer_json

MAX_CAPTURES = 1_000
MAX_MANIFEST_BYTES = 16 * 1024
MAX_SCOPE_BYTES = MAX_ROW_BYTES // 2
_REQUIRED_CAPTURE = {"requestUrl", "observedAt", "responseSha256", "byteSize"}
_OPTIONAL_CAPTURE = {"resolvedUrl", "mediaType", "via"}
RequestCheck = Callable[[object], tuple[list[tuple[str, str]], int]]


def page_request(url: object, *, endpoint: str, order_by: str | None = None) -> tuple[list[tuple[str, str]], int]:
    if not isinstance(url, str) or len(url) > MAX_MANIFEST_BYTES:
        raise ValueError("FEC query request must be a bounded URL")
    parsed = urlsplit(official_url(url))
    if urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) != endpoint:
        raise ValueError("FEC query request must use the selected endpoint")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    controls = {key: [value for name, value in pairs if name == key] for key in ("page", "per_page", "sort")}
    if (
        (order_by is not None and controls["sort"] != [order_by])
        or len(controls["per_page"]) != 1
        or len(controls["page"]) > 1
    ):
        raise ValueError("FEC query controls differ from the required order or page size")
    try:
        page = int(controls["page"][0]) if controls["page"] else 1
        size = int(controls["per_page"][0])
    except ValueError as error:
        raise ValueError("FEC query page controls must be integers") from error
    if page < 1 or not 1 <= size <= 100 or any(key.startswith("last_") for key, _ in pairs):
        raise ValueError("FEC query page controls are outside the selected profile")
    return pairs, page


def capture_descriptor(value: object, *, request: RequestCheck) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _REQUIRED_CAPTURE <= set(value) <= _REQUIRED_CAPTURE | _OPTIONAL_CAPTURE:
        raise ValueError("FEC capture descriptor fields differ")
    result = dict(value)
    request(result["requestUrl"])
    if (
        not isinstance(result["responseSha256"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", result["responseSha256"]) is None
    ):
        raise ValueError("FEC capture digest is invalid")
    if type(result["byteSize"]) is not int or not 0 < result["byteSize"] <= MAX_METADATA_BYTES:
        raise ValueError("FEC capture byte size exceeds its bound")
    observed = result["observedAt"]
    try:
        instant = datetime.fromisoformat(observed) if isinstance(observed, str) else None
    except ValueError as error:
        raise ValueError("FEC capture observation time is invalid") from error
    if instant is None or instant.utcoffset() is None:
        raise ValueError("FEC capture observation time must include a timezone")
    if "resolvedUrl" in result and result["resolvedUrl"] != result["requestUrl"]:
        raise ValueError("FEC query capture resolved to a different request")
    if "mediaType" in result and (
        not isinstance(result["mediaType"], str)
        or result["mediaType"].split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise ValueError("FEC query capture must contain JSON")
    if "via" in result and (not isinstance(result["via"], str) or not result["via"]):
        raise ValueError("FEC capture transport description is invalid")
    if len(canonical_json_bytes(result)) > MAX_MANIFEST_BYTES:
        raise ValueError("FEC capture descriptor exceeds its bound")
    return result


def query_scope(captures: Sequence[Mapping[str, Any]], *, request: RequestCheck) -> dict[str, Any]:
    """Pin the ordered capture inventory without inferring source coverage."""
    if not isinstance(captures, (list, tuple)) or not 1 <= len(captures) <= MAX_CAPTURES:
        raise ValueError("FEC query needs a bounded, nonempty capture sequence")
    values = [capture_descriptor(value, request=request) for value in captures]
    base = None
    for index, capture in enumerate(values):
        pairs, page = request(capture["requestUrl"])
        filters = [(key, value) for key, value in pairs if key != "page"]
        if page != index + 1 or base is not None and filters != base:
            raise ValueError("FEC query capture inventory omits pages or changes source filters")
        base = filters
    scope = {"captures": values}
    if len(canonical_json_bytes(scope)) > MAX_SCOPE_BYTES:
        raise ValueError("FEC query capture scope exceeds the release row byte bound")
    return scope


def decimal_strings(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: decimal_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimal_strings(item) for item in value]
    return value


def pack_response(capture: Mapping[str, Any], raw: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(deterministic_zip_entry("manifest.json"), canonical_json_bytes(dict(capture)))
        archive.writestr(deterministic_zip_entry("response.json"), raw)
    return output.getvalue()


def parse_response(raw: bytes, *, request: RequestCheck) -> Mapping[str, Any]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = ("manifest.json", "response.json")
            if len(infos) != 2 or any(
                not has_deterministic_zip_metadata(info, name=name) for info, name in zip(infos, names, strict=True)
            ):
                raise ValueError("FEC evidence ZIP membership or metadata differs")
            if infos[0].file_size > MAX_MANIFEST_BYTES or infos[1].file_size > MAX_METADATA_BYTES:
                raise ValueError("FEC evidence ZIP member exceeds its byte bound")
            capture = capture_descriptor(
                load_integer_json(archive.read(infos[0]), source="FEC capture", error_type=ValueError), request=request
            )
            response = archive.read(infos[1])
    except BadZipFile as error:
        raise ValueError("FEC evidence ZIP is invalid") from error
    if (
        len(response) != capture["byteSize"]
        or "sha256:" + hashlib.sha256(response).hexdigest() != capture["responseSha256"]
    ):
        raise ValueError("FEC capture bytes differ from their declared pin")
    value = parse_api(response)
    rows, changes, _ = api_page(value, url=capture["requestUrl"], mode="page")
    parsed = urlsplit(capture["requestUrl"])
    pairs, page = request(capture["requestUrl"])
    next_url = None
    if changes is not None:
        pairs = [(key, item) for key, item in pairs if key not in changes]
        pairs.extend((key, str(item)) for key, item in changes.items())
        next_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), ""))
    return {
        "capture": capture,
        "page": page,
        "pagination": value["pagination"],
        "next_url": next_url,
        "results": [
            {"capture": capture, **decimal_strings(split_record(record, source_pointer=pointer))}
            for pointer, record in rows
        ],
    }


@dataclass(frozen=True, slots=True)
class RetainedPage:
    page_index: int
    request_key: str
    source_cursor: str | None
    response_bytes: bytes
    traversal_index: int = 0
    window_index: int = 0
    evidence_media_type: str = "application/zip"

    @property
    def window_page_index(self) -> int:
        return self.page_index


def iter_pages(
    captures: Sequence[Mapping[str, Any]], *, blob_source: BlobSource, request: RequestCheck
) -> Iterator[RetainedPage]:
    """Read and pin each original once; retain O(captures + largest page) memory.

    Exact byte integrity is checked before each page reaches publication. Source
    pagination/counts/order and full selected membership are checked again by the
    publisher and its independent replay through this profile.
    """
    scope = query_scope(captures, request=request)
    for index, capture in enumerate(scope["captures"]):
        content = bytearray()
        with blob_source.open(capture["responseSha256"]) as stream:
            # Binary streams may return fewer bytes than requested before EOF.
            # Retain at most the declared size plus one byte to detect excess.
            while len(content) <= capture["byteSize"]:
                requested = min(64 * 1024, capture["byteSize"] + 1 - len(content))
                chunk = stream.read(requested)
                if not isinstance(chunk, bytes) or len(chunk) > requested:
                    raise ValueError("FEC retained stream did not return bounded binary bytes")
                if not chunk:
                    break
                content.extend(chunk)
        raw = bytes(content)
        if len(raw) != capture["byteSize"] or "sha256:" + hashlib.sha256(raw).hexdigest() != capture["responseSha256"]:
            raise ValueError("FEC retained response bytes differ from the selected capture")
        yield RetainedPage(
            index, capture["requestUrl"], capture["requestUrl"] if index else None, pack_response(capture, raw)
        )


def records_included(
    response: Mapping[str, Any], *, query_scope: Mapping[str, Any], page_window: object | None
) -> bool:
    captures = query_scope["captures"]
    index = response["page"] - 1
    if not 0 <= index < len(captures) or response["capture"] != captures[index]:
        raise ValueError("FEC response capture differs from the selected scope")
    if page_window != captures[0]["requestUrl"]:
        raise ValueError("FEC query initial request differs from the selected scope")
    expected_next = captures[index + 1]["requestUrl"] if index + 1 < len(captures) else None
    if response["next_url"] != expected_next:
        raise ValueError("FEC query continuation differs from its selected capture inventory")
    return True


def next_page(response: Mapping[str, Any], *, seen_urls: set[str]) -> str | None:
    url = response["next_url"]
    if url is not None:
        if url in seen_urls:
            raise ValueError("FEC query continuation repeats")
        seen_urls.add(url)
    return url


@dataclass(slots=True)
class QueryAcquisition:
    windows: int = 0

    def add_window(self, response, *, page_window, records_included, response_bytes) -> None:
        if not records_included or response["page"] != 1 or page_window != response["capture"]["requestUrl"]:
            raise ValueError("FEC query requires one complete selected request chain")
        self.windows += 1

    def finish(self, *, query_scope) -> None:
        if self.windows != 1:
            raise ValueError("FEC query must contain exactly one traversal window")


def exact_page_count(response: Mapping[str, Any], *, request: RequestCheck) -> tuple[int, int]:
    """Validate one ordinary API page against its exact source count and size."""
    pagination = response["pagination"]
    count, pages = pagination.get("count"), pagination.get("pages")
    if pagination.get("is_count_exact") is not True or type(count) is not int or count < 0:
        raise ValueError("FEC query requires an exact nonnegative publisher count")
    pairs, page = request(response["capture"]["requestUrl"])
    size = int(dict(pairs)["per_page"])
    expected_pages = (count + size - 1) // size
    expected_rows = min(size, max(0, count - (page - 1) * size))
    if (
        pagination.get("per_page") != size
        or pages not in ({0, 1} if count == 0 else {expected_pages})
        or len(response["results"]) != expected_rows
    ):
        raise ValueError("FEC query page size or record count differs from publisher pagination")
    return count, pages
