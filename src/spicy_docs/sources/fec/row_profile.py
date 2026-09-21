"""Bounded positional rows from one pinned FEC original or selected ZIP member.

Coordinates identify observations; financial identifiers remain literal fields.
No header names, transaction deduplication or amendment interpretation is inferred.
"""

import csv
import hashlib
import re
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from zipfile import ZipFile

from rulespec_artifacts import canonical_json_bytes, schema_bundle_digest

from spicy_docs.reading.zip_archive import inspect_archive_stream, seekable_stream
from spicy_docs.releases.profile import SourceNativeBlobPage, SourceNativeProfile
from spicy_docs.sources.fec.bulk_profile import MAX_DECODED_BYTES, MAX_INVENTORY_BYTES, MAX_MEMBERS
from spicy_docs.sources.fec.filings import _Lines, filing_records_from_stream
from spicy_docs.sources.fec.originals import MAX_FILE_BYTES, original_capture

SCHEMA_NAME = "fec-positional-row"
SCHEMA_KEY = f"schemas/{SCHEMA_NAME}-1.0.json"
SCOPE_ID = "fec-retained-positional-rows"
MAX_PAGE_BYTES = 1024**2
MAX_RECORD_BYTES = 128 * 1024


def positional_row_scope(
    capture,
    *,
    format,
    encoding,
    member=None,
    delimiter=None,
    quoting=None,
    max_records_per_page=1000,
    max_record_bytes=MAX_RECORD_BYTES,
    max_members=MAX_MEMBERS,
    max_decoded_bytes=MAX_DECODED_BYTES,
):
    """Select one complete decoded stream, with explicit syntax and resource bounds.

    member is None for opaque originals or {ordinal, name} for a ZIP member.
    Delimited input includes header and blank rows; no field mapping is implied.
    """
    capture = original_capture(capture)
    if format not in {"delimited", "fec"} or encoding not in {"utf-8", "latin-1", "cp1252"}:
        raise ValueError("select a supported format and whole-stream encoding")
    if format == "delimited":
        if delimiter not in {",", "|", "\t", "\x1c"} or quoting not in {"csv", "literal"}:
            raise ValueError("delimited input requires explicit delimiter and quoting")
    elif delimiter is not None or quoting is not None:
        raise ValueError("FEC filing syntax comes from its native header")
    for value, maximum in (
        (max_records_per_page, 1000),
        (max_record_bytes, MAX_RECORD_BYTES),
        (max_members, MAX_MEMBERS),
        (max_decoded_bytes, MAX_DECODED_BYTES),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("FEC row parsing bound is invalid")
    if capture["representation"] == "zip":
        if (
            not isinstance(member, Mapping)
            or set(member) != {"ordinal", "name"}
            or type(member["ordinal"]) is not int
            or not 0 <= member["ordinal"] < max_members
            or not isinstance(member["name"], str)
            or not member["name"]
            or len(member["name"].encode()) > 65535
        ):
            raise ValueError("ZIP rows require an exact member ordinal and name")
        member = dict(member)
    elif member is not None:
        raise ValueError("opaque originals have no ZIP member selector")
    return {
        "capture": capture,
        "format": format,
        "encoding": encoding,
        "member": member,
        "delimiter": delimiter,
        "quoting": quoting,
        "max_records_per_page": max_records_per_page,
        "max_record_bytes": max_record_bytes,
        "max_members": max_members,
        "max_decoded_bytes": max_decoded_bytes,
    }


def _scope(value):
    if not isinstance(value, Mapping) or set(value) != {
        "capture",
        "format",
        "encoding",
        "member",
        "delimiter",
        "quoting",
        "max_records_per_page",
        "max_record_bytes",
        "max_members",
        "max_decoded_bytes",
    }:
        raise ValueError("FEC row scope fields differ")
    return positional_row_scope(**value)


def _key(index):
    return f"fec-rows://page/{index}"


def iter_retained_positional_rows(scope, *, blob_source):
    """Yield the scope's one selected original as a single blob page."""
    capture = _scope(scope)["capture"]
    yield SourceNativeBlobPage(
        0,
        0,
        _key(0),
        capture["responseSha256"],
        capture["byteSize"],
        blob_source,
        "application/zip" if capture["representation"] == "zip" else "application/octet-stream",
    )


@contextmanager
def _decoded_stream(stream, scope):
    capture = scope["capture"]
    if scope["member"] is None:
        if capture["byteSize"] > scope["max_decoded_bytes"]:
            raise ValueError("FEC original exceeds its decoded byte bound")
        yield stream, None, capture["responseSha256"]
        return
    with seekable_stream(stream, byte_size=capture["byteSize"]) as original:
        inventory = inspect_archive_stream(
            original,
            byte_size=capture["byteSize"],
            max_entries=scope["max_members"],
            max_decoded_bytes=scope["max_decoded_bytes"],
            max_metadata_bytes=MAX_INVENTORY_BYTES,
        )
        ordinal = scope["member"]["ordinal"]
        if ordinal >= len(inventory["members"]):
            raise ValueError("FEC selected ZIP member is missing")
        selected = inventory["members"][ordinal]
        if selected["name"] != scope["member"]["name"] or selected["isDirectory"]:
            raise ValueError("FEC selected ZIP member identity differs or is a directory")
        # The complete bounded decoder has verified every member. Reuse the same
        # original for standard streaming reads; never reopen it for each row/page.
        with ZipFile(original) as archive, archive.open(archive.infolist()[ordinal]) as decoded:
            yield decoded, scope["member"], selected["sha256"]


def _delimited_rows(stream, *, sha256, scope):
    lines = _Lines(stream, scope["encoding"], scope["max_record_bytes"])
    while True:
        lines.start = lines.end
        fields = next(
            csv.reader(
                lines,
                delimiter=scope["delimiter"],
                quoting=csv.QUOTE_MINIMAL if scope["quoting"] == "csv" else csv.QUOTE_NONE,
                strict=True,
            ),
            None,
        )
        if fields is None:
            return
        yield {
            "kind": "row",
            "fields": fields,
            "source": {
                "sha256": sha256,
                "byte_offset": lines.start,
                "byte_length": lines.end - lines.start,
                "encoding": scope["encoding"],
            },
        }


def _page(index, rows, *, terminal):
    return {"requestKey": _key(index), "page": index, "results": rows, "terminal": terminal}


def _parse_file(stream, *, query_scope, request_key, evidence_ref, byte_size, media_type):
    scope = query_scope
    capture = scope["capture"]
    expected_media = "application/zip" if capture["representation"] == "zip" else "application/octet-stream"
    if (request_key, evidence_ref, byte_size, media_type) != (
        _key(0),
        capture["responseSha256"],
        capture["byteSize"],
        expected_media,
    ):
        raise ValueError("FEC row original differs from its selected capture")
    with _decoded_stream(stream, scope) as (decoded, member, digest):
        records = (
            filing_records_from_stream(
                decoded, sha256=digest, encoding=scope["encoding"], max_record_bytes=scope["max_record_bytes"]
            )
            if scope["format"] == "fec"
            else _delimited_rows(decoded, sha256=digest, scope=scope)
        )
        page, rows, size = 0, [], 0
        for ordinal, parsed in enumerate(records):
            member_id = "original" if member is None else str(member["ordinal"])
            row = {
                "id": f"{evidence_ref}/{member_id}/{ordinal:020d}",
                "ordinal": ordinal,
                "member": member,
                "record": parsed,
            }
            row_size = len(canonical_json_bytes(row))
            overhead = len(canonical_json_bytes(_page(page, [], terminal=False)))
            if overhead + row_size > MAX_PAGE_BYTES:
                raise ValueError("FEC parsed record exceeds its page byte bound")
            if rows and (
                len(rows) == scope["max_records_per_page"] or overhead + size + row_size + len(rows) > MAX_PAGE_BYTES
            ):
                yield _page(page, rows, terminal=False)
                page, rows, size = page + 1, [], 0
                if len(canonical_json_bytes(_page(page, [], terminal=False))) + row_size > MAX_PAGE_BYTES:
                    raise ValueError("FEC parsed record exceeds its page byte bound")
            rows.append(row)
            size += row_size
        yield _page(page, rows, terminal=True)


@dataclass
class _Traversal:
    pages: int = 0
    terminal: bool = False

    def add(self, response, *, page_index):
        if self.terminal or response["page"] != page_index or page_index != self.pages:
            raise ValueError("FEC row page sequence differs")
        self.pages += 1
        self.terminal = response["terminal"]

    def finish(self):
        if not self.pages or not self.terminal:
            raise ValueError("FEC row stream did not finish")


@dataclass
class _Acquisition:
    observed: bool = False

    def add_window(self, response, *, page_window, records_included, response_bytes):
        if self.observed or page_window != 0 or response["page"] != 0 or not records_included:
            raise ValueError("FEC row acquisition requires one original window")
        self.observed = True

    def finish(self, *, query_scope):
        if not self.observed:
            raise ValueError("FEC row original is missing")


def _window(key):
    if not isinstance(key, str) or re.fullmatch(r"fec-rows://page/(0|[1-9][0-9]*)", key) is None:
        raise ValueError("FEC row page key is invalid")
    return 0


def _validate_record(record, *, query_scope, page_window):
    digest = query_scope["capture"]["responseSha256"]
    member = query_scope["member"]
    member_id = "original" if member is None else str(member["ordinal"])
    if record["member"] != member or record["id"] != f"{digest}/{member_id}/{record['ordinal']:020d}":
        raise ValueError("FEC row coordinates differ from the selected stream")


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:spicy-docs:schema:{SCHEMA_NAME}:1.0",
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "ordinal", "member", "record"],
    "properties": {
        "id": {"type": "string"},
        "ordinal": {"type": "integer", "minimum": 0},
        "member": {"type": ["object", "null"]},
        "record": {"type": "object"},
    },
    "x-spicy-record-order": [
        {"fieldPath": "/id", "nullOrder": "forbidden", "tupleComparison": "utf16-code-unit", "valueType": "string"}
    ],
}


@cache
def _schema_digest():
    return schema_bundle_digest({SCHEMA_KEY: _SCHEMA})


FEC_POSITIONAL_ROWS_PROFILE = SourceNativeProfile(
    name="Retained FEC positional rows",
    source_system_id="urn:spicy-docs:source:fec-positional-originals",
    source_system_version="1",
    acquisition_policy_id="urn:spicy-docs:acquisition:fec-positional-rows",
    acquisition_policy_version="1.0",
    scope_id=SCOPE_ID,
    source_schema_key=SCHEMA_KEY,
    source_schema=_SCHEMA,
    record_stem="fec-row",
    max_traversals=1,
    source_state_scope="observed-crawl",
    traversal_acceptance="single-observed-traversal",
    acquisition_policy=lambda scope: {
        "initialQueryScope": _scope(scope),
        "maxPageBytes": MAX_PAGE_BYTES,
        "coverageLimits": [
            "One selected original or ZIP member; no complete financial population or archive-wide row coverage.",
            "Rows include headers, blank records, unknown types and repeated contents; coordinates identify observations.",
            "Fields remain positional. No inferred field names, financial identities, data types or amendment selection.",
            "Filing narrative bodies remain separate byte/field references into the decoded stream.",
            "Other ZIP members remain in the exact original; this release parses only the explicit member selector.",
        ],
    },
    validate_query_scope=_scope,
    parse_page_response=lambda raw: {},
    parse_file_stream=_parse_file,
    max_evidence_bytes=MAX_FILE_BYTES,
    next_page=lambda response, *, seen_urls: None if response["terminal"] else _key(response["page"] + 1),
    traversal_check=_Traversal,
    classify_record=lambda row: dict(row),
    wrap_record=lambda row, *, schema_digest: {
        "fieldDiagnostics": [],
        "record": dict(row),
        "schemaDigest": schema_digest,
        "schemaName": SCHEMA_NAME,
        "schemaVersion": "1.0",
        "scopeId": SCOPE_ID,
        "sourceRecordId": row["id"],
    },
    record_digest=lambda row: "sha256:" + hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest(),
    rendition_rows=lambda row: (),
    source_schema_digest=_schema_digest,
    source_schema_declaration=lambda: {
        "schemaDigest": _schema_digest(),
        "schemaName": SCHEMA_NAME,
        "schemaVersion": "1.0",
    },
    validate_record_scope=_validate_record,
    records_included=lambda response, **kwargs: True,
    acquisition_check=_Acquisition,
    page_window=_window,
)

__all__ = ["FEC_POSITIONAL_ROWS_PROFILE", "iter_retained_positional_rows", "positional_row_scope"]
