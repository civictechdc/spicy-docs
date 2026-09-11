"""Pack and decode exact Mirrulations listing metadata and captured bytes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from rulespec_artifacts import (
    canonical_json_bytes,
)

from spicy_docs.sources.evidence_zip import deterministic_zip_entry
from spicy_docs.sources.json_input import load_integer_json
from spicy_docs.sources.regulations_gov.definitions import (
    _ASCII_ID,
    _ASCII_KEY,
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    EVIDENCE_PACK_TYPE,
    MAX_EVIDENCE_PACK_OBJECTS,
    MAX_EVIDENCE_PACK_RAW_BYTES,
    MAX_OBJECT_BYTES,
    RegulationsGovSourceError,
)
from spicy_docs.sources.regulations_gov.records import (
    _data_attributes,
    classify_comment,
    classify_docket,
    classify_document,
)
from spicy_docs.sources.regulations_gov.validation import (
    _closed_mapping,
)

_decode_json = partial(
    load_integer_json, source="Regulations.gov", error_type=RegulationsGovSourceError, number_label="float"
)


def _enumeration_entry(value: object) -> dict[str, Any]:
    row = _closed_mapping(
        value,
        allowed=frozenset({"byteSize", "etag", "key", "versionId"}),
        label="Mirrulations enumeration entry",
        required=frozenset({"byteSize", "etag", "key", "versionId"}),
    )
    key = row.get("key")
    etag = row.get("etag")
    version_id = row.get("versionId")
    byte_size = row.get("byteSize")
    if not isinstance(key, str) or _ASCII_KEY.fullmatch(key) is None:
        raise RegulationsGovSourceError("Mirrulations enumeration key is not strict ASCII")
    if not isinstance(etag, str) or not etag:
        raise RegulationsGovSourceError("Mirrulations enumeration ETag is invalid")
    if version_id is not None and (not isinstance(version_id, str) or not version_id):
        raise RegulationsGovSourceError("Mirrulations enumeration versionId is invalid")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 1:
        raise RegulationsGovSourceError("Mirrulations enumeration byteSize is invalid")
    return {
        "byteSize": byte_size,
        "etag": etag,
        "key": key,
        "versionId": version_id,
    }


@dataclass(frozen=True, slots=True)
class _PackedObject:
    key: str
    etag: str
    version_id: str | None
    content: bytes
    included: bool


def _pack_bytes(
    objects: Sequence[_PackedObject],
    *,
    collection: str,
    agency: str,
    pack_index: int,
    terminal: bool,
) -> bytes:
    if len(objects) > MAX_EVIDENCE_PACK_OBJECTS:
        raise RegulationsGovSourceError("Mirrulations evidence pack has too many objects")
    if sum(len(item.content) for item in objects) > MAX_EVIDENCE_PACK_RAW_BYTES:
        raise RegulationsGovSourceError("Mirrulations evidence pack exceeds its raw-byte bound")
    manifest_objects = [
        {
            "byteSize": len(item.content),
            "entry": f"objects/{index:06d}.json",
            "etag": item.etag,
            "included": item.included,
            "key": item.key,
            "versionId": item.version_id,
        }
        for index, item in enumerate(objects)
    ]
    manifest = canonical_json_bytes(
        {
            "agency": agency,
            "collection": collection,
            "evidenceType": EVIDENCE_PACK_TYPE,
            "objects": manifest_objects,
            "packIndex": pack_index,
            "terminal": terminal,
        }
    )
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(deterministic_zip_entry("manifest.json"), manifest)
        for item, descriptor in zip(objects, manifest_objects, strict=True):
            archive.writestr(deterministic_zip_entry(str(descriptor["entry"])), item.content)
    return output.getvalue()


def _parse_page_response(
    raw: bytes,
    *,
    collection: str,
    classifier: Callable[[object], Mapping[str, Any]],
) -> Mapping[str, Any]:
    try:
        archive = ZipFile(BytesIO(raw), "r")
    except BadZipFile as error:
        raise RegulationsGovSourceError("Mirrulations evidence pack is not a ZIP file") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if not names or names[0] != "manifest.json" or len(names) != len(set(names)):
            raise RegulationsGovSourceError("Mirrulations evidence pack membership differs")
        manifest_info = infos[0]
        if manifest_info.file_size > MAX_OBJECT_BYTES:
            raise RegulationsGovSourceError("Mirrulations evidence manifest exceeds its bound")
        manifest = _closed_mapping(
            _decode_json(archive.read(manifest_info)),
            allowed=frozenset({"agency", "collection", "evidenceType", "objects", "packIndex", "terminal"}),
            required=frozenset({"agency", "collection", "evidenceType", "objects", "packIndex", "terminal"}),
            label="Mirrulations evidence-pack manifest",
        )
        agency = manifest.get("agency")
        pack_index = manifest.get("packIndex")
        terminal = manifest.get("terminal")
        if (
            manifest.get("collection") != collection
            or manifest.get("evidenceType") != EVIDENCE_PACK_TYPE
            or not isinstance(agency, str)
            or _ASCII_ID.fullmatch(agency) is None
            or isinstance(pack_index, bool)
            or not isinstance(pack_index, int)
            or pack_index < 0
            or not isinstance(terminal, bool)
        ):
            raise RegulationsGovSourceError("Mirrulations evidence-pack identity differs")
        values = manifest.get("objects")
        if not isinstance(values, list) or len(values) > MAX_EVIDENCE_PACK_OBJECTS:
            raise RegulationsGovSourceError("Mirrulations evidence-pack objects differ")
        expected_names = ["manifest.json"]
        entries: list[dict[str, Any]] = []
        packed_records: list[dict[str, Any]] = []
        raw_byte_count = 0
        for index, value in enumerate(values):
            row = _closed_mapping(
                value,
                allowed=frozenset({"byteSize", "entry", "etag", "included", "key", "versionId"}),
                required=frozenset({"byteSize", "entry", "etag", "included", "key", "versionId"}),
                label="Mirrulations evidence-pack object",
            )
            entry = row.get("entry")
            included = row.get("included")
            expected_entry = f"objects/{index:06d}.json"
            if entry != expected_entry or not isinstance(included, bool):
                raise RegulationsGovSourceError("Mirrulations evidence-pack object fields differ")
            metadata = _enumeration_entry(
                {
                    "byteSize": row.get("byteSize"),
                    "etag": row.get("etag"),
                    "key": row.get("key"),
                    "versionId": row.get("versionId"),
                }
            )
            expected_names.append(expected_entry)
            info = infos[index + 1] if index + 1 < len(infos) else None
            if info is None or info.filename != expected_entry or info.file_size != metadata["byteSize"]:
                raise RegulationsGovSourceError("Mirrulations evidence-pack object size differs")
            raw_byte_count += info.file_size
            if raw_byte_count > MAX_EVIDENCE_PACK_RAW_BYTES:
                raise RegulationsGovSourceError("Mirrulations evidence pack exceeds its raw-byte bound")
            content = archive.read(info)
            if len(content) != metadata["byteSize"]:
                raise RegulationsGovSourceError("Mirrulations evidence-pack object is truncated")
            record = dict(classifier(_decode_json(content)))
            if _data_attributes(record).get("agencyId") != agency:
                raise RegulationsGovSourceError("Mirrulations evidence-pack record agency differs")
            entries.append({"agency": agency, **metadata})
            packed_records.append({"included": included, "record": record})
        if names != expected_names:
            raise RegulationsGovSourceError("Mirrulations evidence pack has extra or reordered members")
    results = [item["record"] for item in packed_records if item["included"]]
    return {
        "_agency": agency,
        "_collection": collection,
        "_evidenceType": EVIDENCE_PACK_TYPE,
        "_objects": entries,
        "_packIndex": pack_index,
        "_packedRecords": packed_records,
        "_terminal": terminal,
        "count": len(results),
        "next_page_url": None,
        "results": results,
        "total_pages": 1,
    }


def parse_document_page_response(raw: bytes) -> Mapping[str, Any]:
    return _parse_page_response(raw, collection=DOCUMENT_COLLECTION, classifier=classify_document)


def parse_docket_page_response(raw: bytes) -> Mapping[str, Any]:
    return _parse_page_response(raw, collection=DOCKET_COLLECTION, classifier=classify_docket)


def parse_comment_page_response(raw: bytes) -> Mapping[str, Any]:
    return _parse_page_response(raw, collection=COMMENT_COLLECTION, classifier=classify_comment)
