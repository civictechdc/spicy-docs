"""Publish retained, explicitly selected OpenFEC committee census responses.

Call ``committee_census_scope(captures)`` for ``SourceNativeReleaseBuild`` and
pass ``iter_retained_committee_pages(captures, blob_source=...)`` to the existing
``SourceNativeReleasePublisher(FEC_COMMITTEE_CENSUS_PROFILE, ...)``. Each capture
pins ``requestUrl``, ``observedAt``, ``responseSha256`` and ``byteSize``; optional
``resolvedUrl``, ``mediaType`` and ``via`` preserve the acquisition description.

Evidence contains the exact JSON bytes plus that capture description. Replay
derives every record and body pointer from those bytes. The published ``record``
contains ``capture`` and the existing ``split_record`` result: full ``metadata``
apart from lifted body fields, ``embedded_bodies``, ``assets``, and a source JSON
pointer. Decimal numbers use exact decimal strings, as in the FEC raw-reader CLI;
their original JSON type and spelling remain in the retained response.

This first profile requires one complete, exactly counted API traversal ordered
by committee ID. Completeness is limited to the pinned requests and their source
filters. It establishes neither a frozen publisher snapshot nor historical FEC
coverage. No request is made here, and linked files remain unrequested.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import cache
from io import BytesIO
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from rulespec_artifacts import BlobSource, canonical_json_bytes, schema_bundle_digest

from spicy_docs.releases.format import MAX_ROW_BYTES
from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.sources.evidence_zip import deterministic_zip_entry, has_deterministic_zip_metadata
from spicy_docs.sources.fec.catalog import MAX_METADATA_BYTES, official_url
from spicy_docs.sources.fec.metadata import api_page, parse_api, split_record
from spicy_docs.sources.json_input import load_integer_json

SOURCE_SYSTEM_ID = "https://api.open.fec.gov/v1/committees/"
SCHEMA_NAME = "fec-committee-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = "schemas/fec-committee-observation-1.0.json"
SCOPE_ID = "fec-retained-committee-census"
MAX_CAPTURES = 1_000
MAX_MANIFEST_BYTES = 16 * 1024
# The scope is one common release row; leave space for its enclosing fields.
MAX_SCOPE_BYTES = MAX_ROW_BYTES // 2
_REQUIRED_CAPTURE = {"requestUrl", "observedAt", "responseSha256", "byteSize"}
_OPTIONAL_CAPTURE = {"resolvedUrl", "mediaType", "via"}
_RECORD_FIELDS = {"capture", "metadata", "embedded_bodies", "assets", "source_pointer"}


def _request(url: object) -> tuple[list[tuple[str, str]], int]:
    if not isinstance(url, str) or len(url) > MAX_MANIFEST_BYTES:
        raise ValueError("FEC census request must be a bounded URL")
    parsed = urlsplit(official_url(url))
    if urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) != SOURCE_SYSTEM_ID:
        raise ValueError("FEC census request must use the current committees endpoint")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    controls = {key: [value for name, value in pairs if name == key] for key in ("page", "per_page", "sort")}
    if controls["sort"] != ["committee_id"] or len(controls["per_page"]) != 1 or len(controls["page"]) > 1:
        raise ValueError("FEC census requests require committee_id order and one page size")
    try:
        page = int(controls["page"][0]) if controls["page"] else 1
        size = int(controls["per_page"][0])
    except ValueError as error:
        raise ValueError("FEC census page controls must be integers") from error
    if page < 1 or not 1 <= size <= 100 or any(key.startswith("last_") for key, _ in pairs):
        raise ValueError("FEC census page controls are outside the selected profile")
    return pairs, page


def _capture(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _REQUIRED_CAPTURE <= set(value) <= _REQUIRED_CAPTURE | _OPTIONAL_CAPTURE:
        raise ValueError("FEC capture descriptor fields differ")
    result = dict(value)
    _request(result["requestUrl"])
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
        raise ValueError("FEC census capture resolved to a different request")
    if "mediaType" in result and (
        not isinstance(result["mediaType"], str)
        or result["mediaType"].split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise ValueError("FEC census capture must contain JSON")
    if "via" in result and (not isinstance(result["via"], str) or not result["via"]):
        raise ValueError("FEC capture transport description is invalid")
    if len(canonical_json_bytes(result)) > MAX_MANIFEST_BYTES:
        raise ValueError("FEC capture descriptor exceeds its bound")
    return result


def committee_census_scope(captures: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pin the ordered capture inventory without inferring source coverage."""
    if not isinstance(captures, (list, tuple)) or not 1 <= len(captures) <= MAX_CAPTURES:
        raise ValueError("FEC census needs a bounded, nonempty capture sequence")
    values = [_capture(value) for value in captures]
    base = None
    for index, capture in enumerate(values):
        pairs, page = _request(capture["requestUrl"])
        filters = [(key, value) for key, value in pairs if key != "page"]
        if page != index + 1 or base is not None and filters != base:
            raise ValueError("FEC census capture inventory omits pages or changes source filters")
        base = filters
    scope = {"captures": values}
    if len(canonical_json_bytes(scope)) > MAX_SCOPE_BYTES:
        raise ValueError("FEC census capture scope exceeds the release row byte bound")
    return scope


def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"captures"}:
        raise ValueError("FEC census scope fields differ")
    return committee_census_scope(value["captures"])


def _decimal_strings(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _decimal_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_strings(item) for item in value]
    return value


def _pack(capture: Mapping[str, Any], raw: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(deterministic_zip_entry("manifest.json"), canonical_json_bytes(dict(capture)))
        archive.writestr(deterministic_zip_entry("response.json"), raw)
    return output.getvalue()


def _parse(raw: bytes) -> Mapping[str, Any]:
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
            capture = _capture(load_integer_json(archive.read(infos[0]), source="FEC capture", error_type=ValueError))
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
    pairs, page = _request(capture["requestUrl"])
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
            {"capture": capture, **_decimal_strings(split_record(record, source_pointer=pointer))}
            for pointer, record in rows
        ],
    }


@dataclass(frozen=True, slots=True)
class RetainedCommitteePage:
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


def iter_retained_committee_pages(
    captures: Sequence[Mapping[str, Any]], *, blob_source: BlobSource
) -> Iterator[RetainedCommitteePage]:
    """Read and pin each original once; retain O(captures + largest page) memory.

    Exact byte integrity is checked before each page reaches publication. Source
    pagination/counts/order and full selected membership are checked again by the
    publisher and its independent replay through this profile.
    """
    scope = committee_census_scope(captures)
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
        yield RetainedCommitteePage(
            index, capture["requestUrl"], capture["requestUrl"] if index else None, _pack(capture, raw)
        )


@dataclass(slots=True)
class _Traversal:
    count: int | None = None
    pages: int | None = None
    observed: int = 0
    last_id: str | None = None

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        pagination = response["pagination"]
        count, pages = pagination.get("count"), pagination.get("pages")
        if pagination.get("is_count_exact") is not True or type(count) is not int or count < 0:
            raise ValueError("FEC census requires an exact nonnegative publisher count")
        if self.count is None:
            self.count, self.pages = count, pages
        if count != self.count or pages != self.pages or response["page"] != page_index + 1:
            raise ValueError("FEC census counts or page inventory changed during traversal")
        pairs, _ = _request(response["capture"]["requestUrl"])
        size = int(dict(pairs)["per_page"])
        expected_pages = (count + size - 1) // size
        expected_rows = min(size, max(0, count - page_index * size))
        if (
            pagination.get("per_page") != size
            or pages not in ({0, 1} if count == 0 else {expected_pages})
            or len(response["results"]) != expected_rows
        ):
            raise ValueError("FEC census page size or record count differs from publisher pagination")
        for row in response["results"]:
            record = _classify(row)
            identity = record["metadata"]["committee_id"]
            if self.last_id is not None and identity <= self.last_id:
                raise ValueError("FEC census committee IDs repeat or cease increasing")
            self.last_id = identity
            self.observed += 1

    def finish(self) -> None:
        if self.count is None or self.observed != self.count:
            raise ValueError("FEC census records differ from its publisher count")


def _included(response: Mapping[str, Any], *, query_scope: Mapping[str, Any], page_window: object | None) -> bool:
    captures = query_scope["captures"]
    index = response["page"] - 1
    if not 0 <= index < len(captures) or response["capture"] != captures[index]:
        raise ValueError("FEC response capture differs from the selected scope")
    if page_window != captures[0]["requestUrl"]:
        raise ValueError("FEC census initial request differs from the selected scope")
    expected_next = captures[index + 1]["requestUrl"] if index + 1 < len(captures) else None
    if response["next_url"] != expected_next:
        raise ValueError("FEC census continuation differs from its selected capture inventory")
    return True


def _next(response: Mapping[str, Any], *, seen_urls: set[str]) -> str | None:
    url = response["next_url"]
    if url is not None:
        if url in seen_urls:
            raise ValueError("FEC census continuation repeats")
        seen_urls.add(url)
    return url


@dataclass(slots=True)
class _Acquisition:
    windows: int = 0

    def add_window(self, response, *, page_window, records_included, response_bytes) -> None:
        if not records_included or response["page"] != 1 or page_window != response["capture"]["requestUrl"]:
            raise ValueError("FEC census requires one complete selected request chain")
        self.windows += 1

    def finish(self, *, query_scope) -> None:
        if self.windows != 1:
            raise ValueError("FEC census must contain exactly one traversal window")


def _classify(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS or not isinstance(value["metadata"], Mapping):
        raise ValueError("FEC committee observation fields differ")
    identity = value["metadata"].get("committee_id")
    if not isinstance(identity, str) or re.fullmatch(r"C[0-9]{8}", identity) is None:
        raise ValueError("FEC committee observation lacks a source committee ID")
    return dict(value)


def _record_scope(record, *, query_scope, page_window) -> None:
    # Request filters, including cycle selection, are publisher controls rather
    # than inferred historical coverage of each current committee metadata row.
    index = _request(record["capture"]["requestUrl"])[1] - 1
    if not 0 <= index < len(query_scope["captures"]) or record["capture"] != query_scope["captures"][index]:
        raise ValueError("FEC committee observation falls outside its selected capture")


def _wrap(record: Mapping[str, Any], *, schema_digest: str) -> dict[str, Any]:
    return {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": SCOPE_ID,
        "sourceRecordId": record["metadata"]["committee_id"],
    }


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:spicy-docs:schema:fec-committee-observation:1.0",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_RECORD_FIELDS),
    "properties": {
        "capture": {"type": "object"},
        "metadata": {
            "type": "object",
            "required": ["committee_id"],
            "properties": {"committee_id": {"type": "string", "pattern": "^C[0-9]{8}$"}},
        },
        "embedded_bodies": {"type": "array"},
        "assets": {"type": "array"},
        "source_pointer": {"type": "string", "pattern": "^/results/[0-9]+$"},
    },
    "x-spicy-record-order": [
        {
            "fieldPath": "/metadata/committee_id",
            "nullOrder": "forbidden",
            "tupleComparison": "utf16-code-unit",
            "valueType": "string",
        }
    ],
}


@cache
def _schema_digest() -> str:
    return schema_bundle_digest({SCHEMA_KEY: _SCHEMA})


@cache
def _schema_declaration() -> dict[str, str]:
    return {"schemaDigest": _schema_digest(), "schemaName": SCHEMA_NAME, "schemaVersion": SCHEMA_VERSION}


FEC_COMMITTEE_CENSUS_PROFILE = SourceNativeProfile(
    name="Retained OpenFEC committee census",
    source_system_id=SOURCE_SYSTEM_ID,
    source_system_version="v1",
    acquisition_policy_id="urn:spicy-docs:acquisition:fec-retained-committee-census",
    acquisition_policy_version="1.0",
    scope_id=SCOPE_ID,
    source_schema_key=SCHEMA_KEY,
    source_schema=_SCHEMA,
    record_stem="fec-committee",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=lambda scope: {
        "initialQueryScope": _scope(scope),
        "strategy": "replay-pinned-exact-count-committee-id-traversal",
        "coverageLimits": [
            "Only the pinned requests and their explicit publisher filters are covered.",
            "One observed traversal establishes no frozen publisher snapshot or historical FEC completeness.",
            "Linked originals and other API collections remain outside this release.",
        ],
        "decimalRepresentation": "exact decimal strings; source JSON bytes retain original numbers",
    },
    validate_query_scope=_scope,
    parse_page_response=_parse,
    next_page=_next,
    traversal_check=_Traversal,
    classify_record=_classify,
    wrap_record=_wrap,
    record_digest=lambda record: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest(),
    rendition_rows=lambda record: (),
    source_schema_declaration=_schema_declaration,
    source_schema_digest=_schema_digest,
    validate_record_scope=_record_scope,
    records_included=_included,
    acquisition_check=_Acquisition,
    page_window=lambda request: (_request(request), request)[1],
)


__all__ = ["FEC_COMMITTEE_CENSUS_PROFILE", "committee_census_scope", "iter_retained_committee_pages"]
