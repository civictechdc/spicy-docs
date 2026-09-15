"""Publish selected original bulk files and exact ZIP member inventories.

Release records are files, not financial rows. Each original stays one separately
stored evidence blob. Member ordinals preserve repeated names and directories;
row parsing, amendment selection and dataset-wide completeness remain separate.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from urllib.parse import unquote, urlsplit

from rulespec_artifacts import canonical_json_bytes, schema_bundle_digest

from spicy_docs.releases.format import MAX_ROW_BYTES
from spicy_docs.releases.profile import SourceNativeBlobPage, SourceNativeProfile
from spicy_docs.sources.fec.catalog import BUCKET_URL, official_url
from spicy_docs.sources.fec.originals import MAX_FILE_BYTES, original_capture
from spicy_docs.sources.fec.retained import MAX_CAPTURES, MAX_SCOPE_BYTES
from spicy_docs.sources.zip_archive import inspect_archive_stream

SOURCE_SYSTEM_ID = BUCKET_URL + "bulk-downloads/"
SCHEMA_NAME = "fec-bulk-file-observation"
SCHEMA_VERSION = "1.0"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-{SCHEMA_VERSION}.json"
SCOPE_ID = "fec-retained-bulk-files"
MAX_DECODED_BYTES = 1024**4
MAX_MEMBERS = 10_000
MAX_INVENTORY_BYTES = MAX_ROW_BYTES // 2
_CAPTURE_FIELDS = {"requestUrl", "observedAt", "responseSha256", "byteSize", "objectKey", "representation"}
_OPTIONAL_FIELDS = {"resolvedUrl", "mediaType", "via", "etag", "lastModified", "contentEncoding", "contentLength"}


def _object_key(url):
    if not isinstance(url, str) or len(url) > 16 * 1024:
        raise ValueError("FEC bulk URL must be bounded text")
    parsed = urlsplit(official_url(url))
    if parsed.query:
        raise ValueError("FEC bulk original URL cannot contain query controls")
    path = unquote(parsed.path, errors="strict")
    if parsed.netloc == urlsplit(BUCKET_URL).netloc:
        key = path.removeprefix("/")
    elif parsed.netloc in {"www.fec.gov", "fec.gov"} and path.startswith("/files/"):
        key = path.removeprefix("/files/")
    else:
        raise ValueError("FEC bulk original is outside the published object routes")
    if not key.startswith("bulk-downloads/") or key.endswith("/") or not key.isascii() or any(ord(c) < 32 for c in key):
        raise ValueError("FEC bulk original must name one published bulk-downloads object")
    return key


def bulk_file_scope(captures, *, max_members, max_decoded_bytes):
    """Pin caller-selected files and ZIP inspection bounds without claiming a census."""
    if not isinstance(captures, (list, tuple)) or not 1 <= len(captures) <= MAX_CAPTURES:
        raise ValueError("FEC bulk capture inventory must be nonempty and bounded")
    if type(max_members) is not int or not 1 <= max_members <= MAX_MEMBERS:
        raise ValueError("FEC bulk member bound is invalid")
    if type(max_decoded_bytes) is not int or not 1 <= max_decoded_bytes <= MAX_DECODED_BYTES:
        raise ValueError("FEC bulk decoded byte bound is invalid")
    selected, keys = [], set()
    for capture in captures:
        if (
            not isinstance(capture, Mapping)
            or not _CAPTURE_FIELDS <= set(capture) <= _CAPTURE_FIELDS | _OPTIONAL_FIELDS
        ):
            raise ValueError("FEC bulk capture fields differ")
        value = dict(capture)
        key = _object_key(value["requestUrl"])
        if value["objectKey"] != key or key in keys:
            raise ValueError("FEC bulk object identity differs or repeats")
        keys.add(key)
        if "resolvedUrl" in value and _object_key(value["resolvedUrl"]) != key:
            raise ValueError("FEC bulk resolved URL names a different object")
        if value["representation"] not in ("zip", "opaque"):
            raise ValueError("FEC bulk representation must be explicitly zip or opaque")
        original_capture(value)
        selected.append(value)
    result = {"captures": selected, "maxMembers": max_members, "maxDecodedBytes": max_decoded_bytes}
    if len(canonical_json_bytes(result)) > MAX_SCOPE_BYTES:
        raise ValueError("FEC bulk capture inventory exceeds the scope byte bound")
    return result


def _scope(value):
    if not isinstance(value, Mapping) or set(value) != {"captures", "maxMembers", "maxDecodedBytes"}:
        raise ValueError("FEC bulk scope fields differ")
    return bulk_file_scope(
        value["captures"], max_members=value["maxMembers"], max_decoded_bytes=value["maxDecodedBytes"]
    )


def _window(key):
    if not isinstance(key, str) or re.fullmatch(r"fec-bulk://capture/(0|[1-9][0-9]*)", key) is None:
        raise ValueError("FEC bulk capture request key is invalid")
    return int(key.rsplit("/", 1)[1])


def iter_retained_bulk_files(scope, *, blob_source):
    for index, capture in enumerate(_scope(scope)["captures"]):
        yield SourceNativeBlobPage(
            index,
            index,
            f"fec-bulk://capture/{index}",
            capture["responseSha256"],
            capture["byteSize"],
            blob_source,
            "application/zip" if capture["representation"] == "zip" else "application/octet-stream",
        )


def _parse_stream(stream, *, query_scope, request_key, evidence_ref, byte_size, media_type):
    index = _window(request_key)
    if index >= len(query_scope["captures"]):
        raise ValueError("FEC bulk page is outside the selected inventory")
    capture = query_scope["captures"][index]
    if (evidence_ref, byte_size) != (capture["responseSha256"], capture["byteSize"]):
        raise ValueError("FEC bulk bytes differ from the selected capture pin")
    expected_media_type = "application/zip" if capture["representation"] == "zip" else "application/octet-stream"
    if media_type != expected_media_type:
        raise ValueError("FEC bulk evidence media type differs from its selected representation")
    inventory = None
    if capture["representation"] == "zip":
        inventory = inspect_archive_stream(
            stream,
            byte_size=byte_size,
            max_entries=query_scope["maxMembers"],
            max_decoded_bytes=query_scope["maxDecodedBytes"],
            max_metadata_bytes=MAX_INVENTORY_BYTES,
        )
    return {"index": index, "results": [{"capture": capture, "archive": inventory}]}


def _parse_bytes(raw):
    raise ValueError("FEC bulk files require the stream parser")


def _classify(value):
    if not isinstance(value, Mapping) or set(value) != {"capture", "archive"}:
        raise ValueError("FEC bulk file observation fields differ")
    return dict(value)


def _included(response, *, query_scope, page_window):
    if response["index"] != page_window:
        raise ValueError("FEC bulk page differs from its selected capture")
    return True


def _record_scope(record, *, query_scope, page_window):
    if record["capture"] != query_scope["captures"][page_window]:
        raise ValueError("FEC bulk record differs from its selected capture")


@dataclass
class _Traversal:
    observed: bool = False

    def add(self, response, *, page_index):
        if self.observed or page_index != 0 or len(response["results"]) != 1:
            raise ValueError("FEC bulk window must contain one complete original")
        self.observed = True

    def finish(self):
        if not self.observed:
            raise ValueError("FEC bulk window omitted its original")


@dataclass
class _Acquisition:
    observed: int = 0

    def add_window(self, response, *, page_window, records_included, response_bytes):
        if not records_included or response["index"] != self.observed or page_window != self.observed:
            raise ValueError("FEC bulk capture inventory changed or omitted a file")
        self.observed += 1

    def finish(self, *, query_scope):
        if self.observed != len(query_scope["captures"]):
            raise ValueError("FEC bulk acquisition omitted selected files")


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:spicy-docs:schema:{SCHEMA_NAME}:1.0",
    "type": "object",
    "additionalProperties": False,
    "required": ["capture", "archive"],
    "properties": {"capture": {"type": "object", "required": ["objectKey"]}, "archive": {"type": ["object", "null"]}},
    "x-spicy-record-order": [
        {
            "fieldPath": "/capture/objectKey",
            "nullOrder": "forbidden",
            "tupleComparison": "utf16-code-unit",
            "valueType": "string",
        }
    ],
}


@cache
def _schema_digest():
    return schema_bundle_digest({SCHEMA_KEY: _SCHEMA})


FEC_BULK_FILES_PROFILE = SourceNativeProfile(
    name="Retained FEC bulk originals",
    source_system_id=SOURCE_SYSTEM_ID,
    source_system_version="1",
    acquisition_policy_id="urn:spicy-docs:acquisition:fec-retained-bulk-files",
    acquisition_policy_version="1.0",
    scope_id=SCOPE_ID,
    source_schema_key=SCHEMA_KEY,
    source_schema=_SCHEMA,
    record_stem="fec-bulk-file",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=lambda value: {
        "initialQueryScope": _scope(value),
        "strategy": "selected-pinned-originals-and-complete-zip-inventory",
        "coverageLimits": [
            "Each release record is a selected original file, not a financial row or an archive member.",
            "ZIP entries preserve central-directory ordinal, repeated names, directories and exact member digests.",
            "ZIP inspection supports stored and deflate entries; other compression methods refuse.",
            "Opaque originals retain bytes without format or member interpretation; missing length witnesses do not prove publisher completeness.",
            "Source object keys are ASCII; ZIP member names retain their original Unicode spelling.",
            "The selected files establish no complete cycle, publisher snapshot, financial schema or amendment view.",
            "Capture facts are caller-retained observations, not independent publisher authentication.",
        ],
        "maxOriginalBytes": MAX_FILE_BYTES,
        "maxInventoryBytes": MAX_INVENTORY_BYTES,
    },
    validate_query_scope=_scope,
    parse_page_response=_parse_bytes,
    parse_page_stream=_parse_stream,
    max_evidence_bytes=MAX_FILE_BYTES,
    next_page=lambda response, *, seen_urls: None,
    traversal_check=_Traversal,
    classify_record=_classify,
    wrap_record=lambda record, *, schema_digest: {
        "fieldDiagnostics": [],
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": SCOPE_ID,
        "sourceRecordId": record["capture"]["objectKey"],
    },
    record_digest=lambda record: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest(),
    rendition_rows=lambda record: (),
    source_schema_digest=_schema_digest,
    source_schema_declaration=lambda: {
        "schemaDigest": _schema_digest(),
        "schemaName": SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    },
    validate_record_scope=_record_scope,
    records_included=_included,
    acquisition_check=_Acquisition,
    page_window=_window,
)

__all__ = ["FEC_BULK_FILES_PROFILE", "bulk_file_scope", "iter_retained_bulk_files"]
