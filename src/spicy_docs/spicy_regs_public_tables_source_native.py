"""Exact spicy-regs public-table captures as a source-native release.

Acquisition begins at the spicy-regs public tables — the community's already
collected data — captured and digest-pinned like any other source (PLAN.md,
"Supply-precedence ruling", accepted 2026-08-31).  spicy-docs reaches an origin
API only for what those tables cannot supply.

The acquisition unit is one Hive partition file:
``comments/agency/agency_code={X}/part-{n}.parquet``.  The whole object is
fetched, its SHA-256, byte size, fetch instant, upstream locator, and whatever
freshness the mirror stated (``ETag``, ``Last-Modified``) are written into a
capture manifest, and manifest plus exact partition bytes are sealed into one
bounded ZIP pack.  That pack is the evidence page: rows are classified out of
the pinned bytes on every publish *and* on every independent replay, never out
of a live query.

Faithfulness is the whole point at this layer.  Every declared column is
preserved, nulls included; ``See attached`` comment bodies and empty
``text_content`` are recorded exactly as the table holds them.  The upstream
pipeline has already selected the current row per ``comment_id``; this profile
reports that selection rather than re-running it, and refuses a capture that
repeats an identity instead of quietly collapsing one away.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Final, Literal, cast
from urllib.parse import parse_qs, quote, urlencode, urlparse
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import polars as pl
from rulespec_artifacts import (
    FramedSection,
    canonical_json_bytes,
    framed_section_digest,
    schema_bundle_digest,
)

from spicy_docs.schemas.spicy_regs_public_tables import (
    PUBLIC_COMMENT_COLUMNS,
    PUBLIC_COMMENT_FILE_COLUMNS,
    PUBLIC_COMMENT_IDENTITY_COLUMN,
    PUBLIC_COMMENT_PARTITION_KEY,
    PUBLIC_COMMENT_VERSION_COLUMN,
    project_public_comment_row,
)

PUBLIC_TABLE_BASE_URL: Final = "https://data.spicy-regs.dev"
PUBLIC_TABLE_HOST: Final = "data.spicy-regs.dev"
COMMENT_TABLE: Final = "comments"
SOURCE_SYSTEM_ID: Final = "urn:spicy-regs:source:spicy-regs-public-tables:comments"
SOURCE_SYSTEM_VERSION: Final = "spicy-regs-public-tables-comments-hive-agency-v1"
COMMENT_SCOPE_ID: Final = "spicy-regs-public-comments"
COMMENT_SCHEMA_NAME: Final = "spicy-regs-public-comment"
SCHEMA_VERSION: Final = "1.0"
COMMENT_SCHEMA_PATH: Final = "sources/spicy-regs-public-comment-1.0.schema.json"
COMMENT_SOURCE_SCHEMA_KEY: Final = "schemas/spicy-regs-public-comment-1.0.schema.json"
COMMENT_RECORD_STEM: Final = "spicy-regs-public-comment"
COMMENT_ACQUISITION_POLICY_ID: Final = "urn:spicy-regs:acquisition:spicy-regs-public-comment-partition-capture"
ACQUISITION_POLICY_VERSION: Final = "1.0"

MAX_TRAVERSALS: Final = 1
MAX_SCOPE_AGENCIES: Final = 512
MAX_PARTS_PER_AGENCY: Final = 64
MAX_PARTITION_BYTES: Final = 16 * 1024 * 1024
MAX_PARTITION_ROWS: Final = 250_000

CAPTURE_PACK_TYPE: Final = "spicy-regs-public-table-capture-v1"
CAPTURE_PACK_MEDIA_TYPE: Final = "application/zip"
PARTITION_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
MANIFEST_ENTRY: Final = "manifest.json"
PARTITION_ENTRY: Final = "partition.parquet"

_CAPTURE_MANIFEST_FIELDS: Final = frozenset(
    {
        "agency",
        "byteSize",
        "captureType",
        "etag",
        "fetchedAt",
        "lastModified",
        "locator",
        "partIndex",
        "sha256",
        "table",
        "terminal",
    }
)

_AGENCY_CODE: Final = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


class PublicTableSourceError(ValueError):
    """The carried spicy-regs public-table evidence is not safely publishable."""


@dataclass(frozen=True, slots=True)
class PublicTableCapture:
    """One whole partition object as fetched, with its stated freshness."""

    locator: str
    content: bytes
    fetched_at: str
    etag: str | None = None
    last_modified: str | None = None


PublicTableFetch = Callable[[str], PublicTableCapture | None]


@dataclass(frozen=True, slots=True)
class PublicTablePartitionPage:
    """One bounded ZIP capture of exact partition bytes and its pin."""

    traversal_index: int
    page_index: int
    window_index: int
    window_page_index: int
    request_key: str
    source_cursor: str | None
    response_bytes: bytes

    @property
    def evidence_media_type(self) -> str:
        return CAPTURE_PACK_MEDIA_TYPE

    def __post_init__(self) -> None:
        if (
            min(
                self.traversal_index,
                self.page_index,
                self.window_index,
                self.window_page_index,
            )
            < 0
        ):
            raise PublicTableSourceError("public-table page indexes must be non-negative")
        if self.traversal_index != 0:
            raise PublicTableSourceError("public-table capture has one traversal")
        if self.window_index != self.page_index or self.window_page_index != 0:
            raise PublicTableSourceError("public-table capture pages are explicit windows")
        if self.source_cursor is not None:
            raise PublicTableSourceError("public-table capture does not use caller-authored cursors")
        if not self.request_key or not self.response_bytes:
            raise PublicTableSourceError("public-table evidence must be nonempty")


@dataclass(frozen=True, slots=True)
class PublicTableWindow:
    """The one partition a capture page covers."""

    kind: Literal["partition"]
    table: str
    agency: str
    part_index: int
    terminal: bool


def comment_partition_locator(agency: str, part_index: int) -> str:
    """Build the one canonical public locator for a comment partition file."""

    if not isinstance(agency, str) or _AGENCY_CODE.fullmatch(agency) is None:
        raise PublicTableSourceError("public-table agency code is invalid")
    if isinstance(part_index, bool) or not isinstance(part_index, int) or not 0 <= part_index < MAX_PARTS_PER_AGENCY:
        raise PublicTableSourceError("public-table part index is outside the source bound")
    partition = quote(f"{PUBLIC_COMMENT_PARTITION_KEY}={agency}", safe="=._-")
    return f"{PUBLIC_TABLE_BASE_URL}/{COMMENT_TABLE}/agency/{partition}/part-{part_index}.parquet"


def spicy_regs_public_comment_query_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one closed, agency-partitioned public-table query scope.

    A capture names the partitions it covers.  The published tree is keyed by
    agency and by nothing else, so the agency list *is* the bounded scope: no
    date window is applied, because filtering rows out of a pinned partition
    would make the release unfaithful to the bytes it pins.
    """

    if set(value) != {"agencies", "table"}:
        raise PublicTableSourceError("spicy-regs public-table query scope fields differ")
    if value.get("table") != COMMENT_TABLE:
        raise PublicTableSourceError("this profile publishes the comments table only")
    agencies = value.get("agencies")
    if (
        not isinstance(agencies, list)
        or not agencies
        or len(agencies) > MAX_SCOPE_AGENCIES
        or any(not isinstance(agency, str) or _AGENCY_CODE.fullmatch(agency) is None for agency in agencies)
        or agencies != sorted(set(agencies))
    ):
        raise PublicTableSourceError("public-table agencies must be nonempty, ASCII, sorted, distinct, and bounded")
    return {"agencies": list(agencies), "table": COMMENT_TABLE}


def _partition_request(*, table: str, agency: str, part_index: int, terminal: bool) -> str:
    query = urlencode(
        {
            "agency": agency,
            "partIndex": str(part_index),
            "terminal": "true" if terminal else "false",
        }
    )
    return f"spicy-regs-tables://public/{table}/partition?{query}"


def parse_public_table_request(value: str) -> PublicTableWindow:
    """Parse one canonical capture request and refuse request drift."""

    parsed = urlparse(value)
    path = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "spicy-regs-tables"
        or parsed.netloc != "public"
        or len(path) != 2
        or path[0] != COMMENT_TABLE
        or path[1] != "partition"
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PublicTableSourceError("public-table request key is invalid")
    table = path[0]
    parameters = parse_qs(parsed.query, keep_blank_values=True)
    if set(parameters) != {"agency", "partIndex", "terminal"} or any(
        len(values) != 1 for values in parameters.values()
    ):
        raise PublicTableSourceError("public-table request fields differ")
    agency = parameters["agency"][0]
    part_index_text = parameters["partIndex"][0]
    terminal_text = parameters["terminal"][0]
    if _AGENCY_CODE.fullmatch(agency) is None:
        raise PublicTableSourceError("public-table request agency is invalid")
    if not part_index_text.isdigit() or terminal_text not in {"false", "true"}:
        raise PublicTableSourceError("public-table request values are invalid")
    part_index = int(part_index_text)
    if part_index >= MAX_PARTS_PER_AGENCY:
        raise PublicTableSourceError("public-table part index is outside the source bound")
    terminal = terminal_text == "true"
    if _partition_request(table=table, agency=agency, part_index=part_index, terminal=terminal) != value:
        raise PublicTableSourceError("public-table request is not canonical")
    return PublicTableWindow(
        kind="partition",
        table=table,
        agency=agency,
        part_index=part_index,
        terminal=terminal,
    )


def _instant(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PublicTableSourceError(f"public-table {label} must be a UTC instant")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise PublicTableSourceError(f"public-table {label} is invalid") from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise PublicTableSourceError(f"public-table {label} must be a UTC instant")
    return value


def _header_or_null(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or not value.isprintable():
        raise PublicTableSourceError(f"public-table {label} must be printable text or null")
    return value


def _zip_entry(name: str) -> ZipInfo:
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    return entry


def capture_manifest(
    capture: PublicTableCapture,
    *,
    agency: str,
    part_index: int,
    terminal: bool,
) -> dict[str, Any]:
    """Pin one fetched partition object: digest, size, instant, locator, freshness."""

    if not isinstance(capture, PublicTableCapture):
        raise PublicTableSourceError("public-table capture is not a capture record")
    if not isinstance(capture.content, bytes) or not capture.content:
        raise PublicTableSourceError("public-table capture carries no partition bytes")
    if len(capture.content) > MAX_PARTITION_BYTES:
        raise PublicTableSourceError("public-table partition exceeds its capture byte bound")
    expected = comment_partition_locator(agency, part_index)
    if capture.locator != expected:
        raise PublicTableSourceError("public-table capture locator differs from its partition")
    if not isinstance(terminal, bool):
        raise PublicTableSourceError("public-table capture terminality must be boolean")
    return {
        "agency": agency,
        "byteSize": len(capture.content),
        "captureType": CAPTURE_PACK_TYPE,
        "etag": _header_or_null(capture.etag, "capture ETag"),
        "fetchedAt": _instant(capture.fetched_at, "capture instant"),
        "lastModified": _header_or_null(capture.last_modified, "capture Last-Modified"),
        "locator": expected,
        "partIndex": part_index,
        "sha256": "sha256:" + hashlib.sha256(capture.content).hexdigest(),
        "table": COMMENT_TABLE,
        "terminal": terminal,
    }


def capture_pack_bytes(
    capture: PublicTableCapture,
    *,
    agency: str,
    part_index: int,
    terminal: bool,
) -> bytes:
    """Seal one capture manifest and its exact partition bytes into evidence."""

    manifest = capture_manifest(capture, agency=agency, part_index=part_index, terminal=terminal)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(_zip_entry(MANIFEST_ENTRY), canonical_json_bytes(manifest))
        archive.writestr(_zip_entry(PARTITION_ENTRY), capture.content)
    return output.getvalue()


def _decode_json(raw: bytes) -> object:
    def duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicTableSourceError(f"public-table JSON repeats field {key!r}")
            result[key] = value
        return result

    def unsupported_number(value: str) -> None:
        raise PublicTableSourceError(f"public-table JSON contains unsupported number {value!r}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=duplicate_keys,
            parse_float=unsupported_number,
            parse_constant=unsupported_number,
        )
    except PublicTableSourceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PublicTableSourceError(f"invalid public-table JSON: {error}") from error


def _validated_manifest(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicTableSourceError("public-table capture manifest must be an object")
    unknown = set(value) - _CAPTURE_MANIFEST_FIELDS
    missing = _CAPTURE_MANIFEST_FIELDS - set(value)
    if unknown:
        raise PublicTableSourceError(f"unclassified public-table capture manifest fields: {sorted(unknown)}")
    if missing:
        raise PublicTableSourceError(f"public-table capture manifest lacks fields: {sorted(missing)}")
    agency = value.get("agency")
    part_index = value.get("partIndex")
    terminal = value.get("terminal")
    byte_size = value.get("byteSize")
    digest = value.get("sha256")
    if (
        value.get("captureType") != CAPTURE_PACK_TYPE
        or value.get("table") != COMMENT_TABLE
        or not isinstance(agency, str)
        or _AGENCY_CODE.fullmatch(agency) is None
        or isinstance(part_index, bool)
        or not isinstance(part_index, int)
        or not 0 <= part_index < MAX_PARTS_PER_AGENCY
        or not isinstance(terminal, bool)
    ):
        raise PublicTableSourceError("public-table capture manifest identity differs")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or not 1 <= byte_size <= MAX_PARTITION_BYTES:
        raise PublicTableSourceError("public-table capture manifest byte size is invalid")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise PublicTableSourceError("public-table capture manifest digest is invalid")
    if value.get("locator") != comment_partition_locator(agency, part_index):
        raise PublicTableSourceError("public-table capture manifest locator differs from its partition")
    return {
        "agency": agency,
        "byteSize": byte_size,
        "captureType": CAPTURE_PACK_TYPE,
        "etag": _header_or_null(value.get("etag"), "capture ETag"),
        "fetchedAt": _instant(value.get("fetchedAt"), "capture instant"),
        "lastModified": _header_or_null(value.get("lastModified"), "capture Last-Modified"),
        "locator": str(value["locator"]),
        "partIndex": part_index,
        "sha256": digest,
        "table": COMMENT_TABLE,
        "terminal": terminal,
    }


def validate_partition_columns(columns: Sequence[str], dtypes: Sequence[object]) -> None:
    """Refuse any partition whose columns drift from the declared table shape.

    A column appearing, disappearing, being renamed, being reordered, or
    changing type all fail closed here.  The published tree encodes the
    partition key in the directory name, so a file that carries an
    ``agency_code`` column is itself drift.
    """

    observed = tuple(str(name) for name in columns)
    if observed != PUBLIC_COMMENT_FILE_COLUMNS:
        added = sorted(set(observed) - set(PUBLIC_COMMENT_FILE_COLUMNS))
        removed = sorted(set(PUBLIC_COMMENT_FILE_COLUMNS) - set(observed))
        detail = f"added {added}, removed {removed}" if added or removed else "reordered"
        raise PublicTableSourceError(f"public comments partition columns drifted: {detail}")
    for name, dtype in zip(observed, dtypes, strict=True):
        if dtype != pl.String:
            raise PublicTableSourceError(f"public comments partition column {name} drifted to {dtype!r}")


def _partition_rows(content: bytes) -> list[dict[str, Any]]:
    try:
        schema = pl.read_parquet_schema(BytesIO(content))
    except Exception as error:  # any reader refusal is one source refusal
        raise PublicTableSourceError(f"public comments partition is not readable Parquet: {error}") from error
    validate_partition_columns(tuple(schema.keys()), tuple(schema.values()))
    try:
        frame = pl.read_parquet(BytesIO(content))
    except Exception as error:  # any reader refusal is one source refusal
        raise PublicTableSourceError(f"public comments partition is not readable Parquet: {error}") from error
    validate_partition_columns(tuple(frame.columns), tuple(frame.dtypes))
    if frame.height > MAX_PARTITION_ROWS:
        raise PublicTableSourceError("public comments partition exceeds its capture row bound")
    return frame.to_dicts()


def parse_comment_page_response(raw: bytes) -> Mapping[str, Any]:
    """Classify one capture pack without changing a byte of its evidence."""

    try:
        archive = ZipFile(BytesIO(raw), "r")
    except BadZipFile as error:
        raise PublicTableSourceError("public-table capture pack is not a ZIP file") from error
    with archive:
        infos = archive.infolist()
        if [info.filename for info in infos] != [MANIFEST_ENTRY, PARTITION_ENTRY]:
            raise PublicTableSourceError("public-table capture pack membership differs")
        manifest_info, partition_info = infos
        if manifest_info.file_size > MAX_PARTITION_BYTES:
            raise PublicTableSourceError("public-table capture manifest exceeds its bound")
        manifest = _validated_manifest(_decode_json(archive.read(manifest_info)))
        if partition_info.file_size != manifest["byteSize"]:
            raise PublicTableSourceError("public-table capture partition size differs from its manifest")
        content = archive.read(partition_info)
    if len(content) != manifest["byteSize"]:
        raise PublicTableSourceError("public-table capture partition is truncated")
    if "sha256:" + hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        raise PublicTableSourceError("public-table capture partition differs from its pinned digest")
    agency = str(manifest["agency"])
    results = [
        classify_comment_row(project_public_comment_row(row, agency_code=agency)) for row in _partition_rows(content)
    ]
    return {
        "_agency": agency,
        "_capture": manifest,
        "_captureType": CAPTURE_PACK_TYPE,
        "_partIndex": manifest["partIndex"],
        "_table": COMMENT_TABLE,
        "_terminal": manifest["terminal"],
        "count": len(results),
        "next_page_url": None,
        "results": results,
        "total_pages": 1,
    }


def classify_comment_row(value: object) -> dict[str, Any]:
    """Return one faithful, closed source row and reject schema drift."""

    if not isinstance(value, Mapping):
        raise PublicTableSourceError("public comments row must be an object")
    source = cast(Mapping[str, Any], value)
    # Column *order* is checked against the partition file, which carries it.
    # A record is canonical JSON by the time it is replayed, so only the closed
    # column set is meaningful here.
    added = sorted(set(source) - set(PUBLIC_COMMENT_COLUMNS))
    removed = sorted(set(PUBLIC_COMMENT_COLUMNS) - set(source))
    if added or removed:
        raise PublicTableSourceError(f"public comments row columns drifted: added {added}, removed {removed}")
    for name in PUBLIC_COMMENT_COLUMNS:
        cell = source[name]
        if cell is not None and not isinstance(cell, str):
            raise PublicTableSourceError(f"public comments column {name} must be text or null")
    for name in (PUBLIC_COMMENT_IDENTITY_COLUMN, PUBLIC_COMMENT_PARTITION_KEY):
        cell = source[name]
        if not isinstance(cell, str) or not cell:
            raise PublicTableSourceError(f"public comments row lacks {name}")
    if _AGENCY_CODE.fullmatch(str(source[PUBLIC_COMMENT_PARTITION_KEY])) is None:
        raise PublicTableSourceError("public comments row agency_code is invalid")
    record = dict(source)
    canonical_json_bytes(record)
    return record


def comment_source_issued_version(record: Mapping[str, Any]) -> str | None:
    """Return the version column exactly as the table holds it; null is a fact."""

    value = record[PUBLIC_COMMENT_VERSION_COLUMN]
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise PublicTableSourceError("public comments modify_date must be nonempty text or null")
    return value


def _media_type(value: object, locator: str) -> str:
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
        }
        if normalized in aliases:
            return aliases[normalized]
    suffix = locator.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
    if suffix and suffix != locator.lower():
        return _media_type(suffix, "")
    return "application/octet-stream"


def _attachment_groups(record: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the attachments column into usable groups and nonfatal diagnostics.

    The column is publisher-authored JSON text.  A malformed value is preserved
    exactly and described, never repaired and never a reason to drop the row.
    """

    raw = record["attachments_json"]
    if raw is None:
        return [], []
    diagnostics: list[dict[str, Any]] = []
    try:
        parsed = _decode_json(str(raw).encode("utf-8"))
    except PublicTableSourceError:
        return [], [{"code": "malformed-attachments-json", "field": "attachments_json", "value": raw}]
    if not isinstance(parsed, list):
        return [], [{"code": "malformed-attachments-json", "field": "attachments_json", "value": raw}]
    groups: list[dict[str, Any]] = []
    for index, item in enumerate(parsed):
        formats = item.get("formats") if isinstance(item, Mapping) else None
        if not isinstance(item, Mapping) or not isinstance(formats, list):
            diagnostics.append(
                {
                    "code": "malformed-attachment",
                    "field": f"attachments_json[{index}]",
                    "value": raw,
                }
            )
            groups.append({"index": index, "formats": []})
            continue
        usable: list[Mapping[str, Any]] = []
        for format_index, value in enumerate(formats):
            url = value.get("url") if isinstance(value, Mapping) else None
            size = value.get("size") if isinstance(value, Mapping) else None
            if (
                not isinstance(value, Mapping)
                or not isinstance(url, str)
                or not url
                or (size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0))
            ):
                diagnostics.append(
                    {
                        "code": "malformed-attachment-format",
                        "field": f"attachments_json[{index}].formats[{format_index}]",
                        "value": raw,
                    }
                )
                continue
            usable.append(value)
        groups.append({"index": index, "formats": usable})
    return groups, diagnostics


def field_diagnostics(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Describe malformed publisher-authored JSON without removing its evidence."""

    return _attachment_groups(record)[1]


def comment_rendition_rows(record: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Preserve every attachment locator the table states for one comment."""

    identity = str(record[PUBLIC_COMMENT_IDENTITY_COLUMN])
    rows: list[dict[str, Any]] = []
    for group in _attachment_groups(record)[0]:
        index = int(group["index"])
        for format_index, value in enumerate(cast(Sequence[Mapping[str, Any]], group["formats"])):
            locator = str(value["url"])
            rows.append(
                {
                    "expectedByteSize": value.get("size"),
                    "expectedSha256": None,
                    "locator": locator,
                    "mediaType": _media_type(value.get("format"), locator),
                    "renditionId": f"attachment-{index:04d}-{format_index:04d}",
                    "sourceField": f"attachments_json[{index}].formats[{format_index}]",
                    "sourceRecordId": identity,
                }
            )
    return tuple(rows)


def comment_source_record(record: Mapping[str, Any], *, schema_digest: str) -> dict[str, Any]:
    """Wrap classified source columns with their source schema reference."""

    return {
        "fieldDiagnostics": field_diagnostics(record),
        "record": dict(record),
        "schemaDigest": schema_digest,
        "schemaName": COMMENT_SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "scopeId": COMMENT_SCOPE_ID,
        "sourceRecordId": str(record[PUBLIC_COMMENT_IDENTITY_COLUMN]),
    }


def public_table_next_page(response: Mapping[str, Any], *, seen_urls: set[str]) -> None:
    """One capture pack is one whole partition; it cannot paginate."""

    del seen_urls
    if response.get("next_page_url") is not None:
        raise PublicTableSourceError("public-table capture evidence cannot paginate")


@dataclass(slots=True)
class PublicTableTraversalCheck:
    """Check that one capture window carries exactly one declared inventory."""

    observed_pages: int = 0

    def add(self, response: Mapping[str, Any], *, page_index: int) -> None:
        results = response.get("results")
        if (
            page_index != 0
            or not isinstance(results, list)
            or not 0 <= len(results) <= MAX_PARTITION_ROWS
            or response.get("count") != len(results)
        ):
            raise PublicTableSourceError("public-table capture inventory differs")
        self.observed_pages += 1

    def finish(self) -> None:
        if self.observed_pages != 1:
            raise PublicTableSourceError("public-table capture window is incomplete")


@dataclass(slots=True)
class PublicTableAcquisitionCheck:
    """Validate one complete, bounded, ordered capture of the named partitions."""

    table: str
    observed_agencies: list[str] = field(default_factory=list)
    observed_locators: set[str] = field(default_factory=set)
    current_agency: str | None = None
    next_part_index: int = 0
    current_terminal: bool = True

    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes,
    ) -> None:
        del response_bytes
        if not isinstance(page_window, PublicTableWindow) or page_window.table != self.table:
            raise PublicTableSourceError("public-table capture request table differs")
        capture = response.get("_capture")
        if (
            response.get("_captureType") != CAPTURE_PACK_TYPE
            or response.get("_table") != self.table
            or response.get("_agency") != page_window.agency
            or response.get("_partIndex") != page_window.part_index
            or response.get("_terminal") is not page_window.terminal
            or not isinstance(capture, Mapping)
            or records_included is not bool(response.get("results"))
        ):
            raise PublicTableSourceError("public-table capture request and bytes differ")
        agency = page_window.agency
        if agency != self.current_agency:
            if self.current_agency is not None and not self.current_terminal:
                raise PublicTableSourceError("public-table agency capture lacks a terminal partition")
            if self.observed_agencies and agency <= self.observed_agencies[-1]:
                raise PublicTableSourceError("public-table capture agencies are not ASCII-sorted")
            if page_window.part_index != 0:
                raise PublicTableSourceError("public-table agency capture does not start at part zero")
            self.observed_agencies.append(agency)
            self.current_agency = agency
            self.next_part_index = 0
        elif self.current_terminal:
            raise PublicTableSourceError("public-table agency capture continues after its terminal partition")
        if page_window.part_index != self.next_part_index:
            raise PublicTableSourceError("public-table capture partitions are missing or reordered")
        locator = str(capture["locator"])
        if locator in self.observed_locators:
            raise PublicTableSourceError("public-table capture repeats a partition locator")
        self.observed_locators.add(locator)
        self.next_part_index += 1
        self.current_terminal = page_window.terminal

    def finish(self, *, query_scope: Mapping[str, Any]) -> None:
        if self.observed_agencies != query_scope.get("agencies"):
            raise PublicTableSourceError("public-table capture does not cover exact agencies")
        if not self.current_terminal:
            raise PublicTableSourceError("public-table capture is missing a terminal partition")


def _record_in_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    agency: str,
) -> None:
    record_agency = record[PUBLIC_COMMENT_PARTITION_KEY]
    if record_agency != agency:
        raise PublicTableSourceError("public comments row agency differs from its partition")
    if record_agency not in query_scope["agencies"]:
        raise PublicTableSourceError("public comments row falls outside the captured partitions")


def comment_records_included(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    """A pinned partition is wholly in scope; an empty one carries no records."""

    if not isinstance(page_window, PublicTableWindow) or page_window.table != COMMENT_TABLE:
        raise PublicTableSourceError("public-table page lacks a validated request")
    if (
        response.get("_captureType") != CAPTURE_PACK_TYPE
        or response.get("_agency") != page_window.agency
        or response.get("_partIndex") != page_window.part_index
        or response.get("_terminal") is not page_window.terminal
    ):
        raise PublicTableSourceError("public-table capture request differs from its evidence")
    results = response.get("results")
    if not isinstance(results, list):
        raise PublicTableSourceError("public-table capture has no record inventory")
    for record in results:
        if not isinstance(record, Mapping):
            raise PublicTableSourceError("public-table capture has an invalid row")
        _record_in_scope(record, query_scope=query_scope, agency=page_window.agency)
    return bool(results)


def validate_comment_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    if not isinstance(page_window, PublicTableWindow) or page_window.table != COMMENT_TABLE:
        raise PublicTableSourceError("public-table page lacks a validated request")
    _record_in_scope(record, query_scope=query_scope, agency=page_window.agency)


def comment_acquisition_policy(query_scope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "acquisitionRung": "community-mirror",
        "baseUrl": PUBLIC_TABLE_BASE_URL,
        "evidence": "bounded-zip-packs-of-a-capture-manifest-and-exact-partition-bytes",
        "initialQueryScope": dict(spicy_regs_public_comment_query_scope(query_scope)),
        "maxPartitionBytes": MAX_PARTITION_BYTES,
        "maxPartitionRows": MAX_PARTITION_ROWS,
        "maxPartsPerAgency": MAX_PARTS_PER_AGENCY,
        "maxScopeAgencies": MAX_SCOPE_AGENCIES,
        "maxTraversals": MAX_TRAVERSALS,
        "observationSelection": {
            "reselectedHere": False,
            "selectedBy": "upstream-spicy-regs-pipeline",
            "statedRule": "newest observed row per comment_id by modify_date DESC NULLS LAST",
            "tieDisposition": "refuse-repeated-source-record-id",
        },
        "strategy": "complete-public-table-partition-capture",
        "table": COMMENT_TABLE,
    }


def iter_spicy_regs_public_comment_pages(
    fetch: PublicTableFetch,
    *,
    query_scope: Mapping[str, Any],
) -> Iterator[PublicTablePartitionPage]:
    """Capture every named agency partition, in ASCII order, whole objects only."""

    scope = spicy_regs_public_comment_query_scope(query_scope)
    page_index = 0
    for agency in cast(Sequence[str], scope["agencies"]):
        pending: tuple[int, PublicTableCapture] | None = None
        for part_index in range(MAX_PARTS_PER_AGENCY):
            capture = fetch(comment_partition_locator(agency, part_index))
            if capture is None:
                break
            if not isinstance(capture, PublicTableCapture):
                raise PublicTableSourceError("public-table fetch returned no capture record")
            if pending is not None:
                yield _page(page_index, pending[1], agency=agency, part_index=pending[0], terminal=False)
                page_index += 1
            pending = (part_index, capture)
        else:
            raise PublicTableSourceError(f"public-table capture for {agency} exceeded its partition bound")
        if pending is None:
            raise PublicTableSourceError(
                f"the spicy-regs public tables publish no {COMMENT_TABLE} partition for {agency}"
            )
        yield _page(page_index, pending[1], agency=agency, part_index=pending[0], terminal=True)
        page_index += 1


def _page(
    page_index: int,
    capture: PublicTableCapture,
    *,
    agency: str,
    part_index: int,
    terminal: bool,
) -> PublicTablePartitionPage:
    return PublicTablePartitionPage(
        traversal_index=0,
        page_index=page_index,
        window_index=page_index,
        window_page_index=0,
        request_key=_partition_request(
            table=COMMENT_TABLE,
            agency=agency,
            part_index=part_index,
            terminal=terminal,
        ),
        source_cursor=None,
        response_bytes=capture_pack_bytes(capture, agency=agency, part_index=part_index, terminal=terminal),
    )


_NULLABLE_TEXT_SCHEMA: Final = {"type": ["string", "null"]}

SPICY_REGS_PUBLIC_COMMENT_SCHEMA: Final[dict[str, Any]] = {
    "$id": "urn:spicy-regs:schema:spicy-regs-public-comment:1.0",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        name: (
            {"minLength": 1, "type": "string"}
            if name in {PUBLIC_COMMENT_IDENTITY_COLUMN, PUBLIC_COMMENT_PARTITION_KEY}
            else _NULLABLE_TEXT_SCHEMA
        )
        for name in PUBLIC_COMMENT_COLUMNS
    },
    "required": [PUBLIC_COMMENT_IDENTITY_COLUMN, PUBLIC_COMMENT_PARTITION_KEY],
    "type": "object",
    "x-spicy-record-order": [
        {
            "fieldPath": f"/{PUBLIC_COMMENT_IDENTITY_COLUMN}",
            "nullOrder": "forbidden",
            "tupleComparison": "utf16-code-unit",
            "valueType": "string",
        }
    ],
    # Provenance the source itself carries and this profile does not re-derive.
    "x-spicy-source-provenance": {
        "acquisitionRung": "community-mirror",
        "identityColumn": PUBLIC_COMMENT_IDENTITY_COLUMN,
        "locatorPattern": (
            f"{PUBLIC_TABLE_BASE_URL}/{COMMENT_TABLE}/agency/{PUBLIC_COMMENT_PARTITION_KEY}="
            "{agency}/part-{n}.parquet"
        ),
        "observationSelection": {
            "reselectedHere": False,
            "selectedBy": "upstream-spicy-regs-pipeline",
            "statedRule": "newest observed row per comment_id by modify_date DESC NULLS LAST",
        },
        "partitionKey": PUBLIC_COMMENT_PARTITION_KEY,
        "partitionKeySource": "hive-directory-name",
        "sourceTable": COMMENT_TABLE,
        "versionColumn": PUBLIC_COMMENT_VERSION_COLUMN,
    },
}


def comment_source_schema_digest() -> str:
    """Use the installed Rulespec schema-family identity implementation."""

    return schema_bundle_digest({COMMENT_SCHEMA_PATH: SPICY_REGS_PUBLIC_COMMENT_SCHEMA})


def comment_source_schema_declaration() -> dict[str, str]:
    return {
        "schemaDigest": comment_source_schema_digest(),
        "schemaName": COMMENT_SCHEMA_NAME,
        "schemaVersion": SCHEMA_VERSION,
    }


def comment_source_record_digest(record: Mapping[str, Any]) -> str:
    """Digest one source row through Rulespec's sole ordered-record digester."""

    return framed_section_digest(
        "spicyregs-public-table-comment-record/1",
        (FramedSection("record", 1, (dict(record),)),),
    )


__all__ = [
    "ACQUISITION_POLICY_VERSION",
    "CAPTURE_PACK_MEDIA_TYPE",
    "CAPTURE_PACK_TYPE",
    "COMMENT_ACQUISITION_POLICY_ID",
    "COMMENT_RECORD_STEM",
    "COMMENT_SCHEMA_NAME",
    "COMMENT_SCHEMA_PATH",
    "COMMENT_SCOPE_ID",
    "COMMENT_SOURCE_SCHEMA_KEY",
    "COMMENT_TABLE",
    "MAX_PARTITION_BYTES",
    "MAX_PARTITION_ROWS",
    "MAX_PARTS_PER_AGENCY",
    "MAX_SCOPE_AGENCIES",
    "MAX_TRAVERSALS",
    "PARTITION_MEDIA_TYPE",
    "PUBLIC_TABLE_BASE_URL",
    "PUBLIC_TABLE_HOST",
    "SCHEMA_VERSION",
    "SOURCE_SYSTEM_ID",
    "SOURCE_SYSTEM_VERSION",
    "SPICY_REGS_PUBLIC_COMMENT_SCHEMA",
    "PublicTableAcquisitionCheck",
    "PublicTableCapture",
    "PublicTableFetch",
    "PublicTablePartitionPage",
    "PublicTableSourceError",
    "PublicTableTraversalCheck",
    "PublicTableWindow",
    "capture_manifest",
    "capture_pack_bytes",
    "classify_comment_row",
    "comment_acquisition_policy",
    "comment_partition_locator",
    "comment_records_included",
    "comment_rendition_rows",
    "comment_source_issued_version",
    "comment_source_record",
    "comment_source_record_digest",
    "comment_source_schema_declaration",
    "comment_source_schema_digest",
    "field_diagnostics",
    "iter_spicy_regs_public_comment_pages",
    "parse_comment_page_response",
    "parse_public_table_request",
    "public_table_next_page",
    "spicy_regs_public_comment_query_scope",
    "validate_comment_record_scope",
    "validate_partition_columns",
]
