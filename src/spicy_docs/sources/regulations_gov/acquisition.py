"""Capture a complete Mirrulations enumeration into bounded evidence pages."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from spicy_docs.sources.regulations_gov.definitions import (
    _ASCII_KEY,
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    MAX_EVIDENCE_PACK_OBJECTS,
    MAX_EVIDENCE_PACK_RAW_BYTES,
    MAX_OBJECT_BYTES,
    RegulationsGovPage,
    RegulationsGovRead,
    RegulationsGovSourceError,
)
from spicy_docs.sources.regulations_gov.evidence import (
    _decode_json,
    _pack_bytes,
    _PackedObject,
)
from spicy_docs.sources.regulations_gov.records import (
    _key_claimed_identity,
    classify_comment,
    classify_docket,
    classify_document,
    source_record_id,
)
from spicy_docs.sources.regulations_gov.scope import (
    _pack_request,
    _record_in_scope,
    regulations_gov_comment_query_scope,
    regulations_gov_docket_query_scope,
    regulations_gov_document_query_scope,
)


def _iter_pages(
    read: RegulationsGovRead,
    *,
    query_scope: Mapping[str, Any],
    collection: str,
    scope_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    classifier: Callable[[object], Mapping[str, Any]],
    scratch_directory: Path | None,
) -> Iterator[RegulationsGovPage]:
    scope = scope_validator(query_scope)
    path_collection = {
        COMMENT_COLLECTION: COMMENT_COLLECTION,
        DOCUMENT_COLLECTION: DOCUMENT_COLLECTION,
        DOCKET_COLLECTION: "docket",
    }[collection]
    del scratch_directory
    page_index = 0
    previous_global_key: str | None = None
    for agency in cast(Sequence[str], scope["agencies"]):
        pack: list[_PackedObject] = []
        pack_raw_bytes = 0
        pack_index = 0
        reader = read(agency)
        for source_object in reader.iter_source_objects(max_bytes=MAX_OBJECT_BYTES):
            key = source_object.key
            etag = source_object.etag
            version_id = source_object.version_id
            content = source_object.content
            if (
                not isinstance(key, str)
                or _ASCII_KEY.fullmatch(key) is None
                or not key.startswith(f"raw-data/{agency}/")
                or f"/{path_collection}/" not in key
                or previous_global_key is not None
                and key <= previous_global_key
            ):
                raise RegulationsGovSourceError(
                    "Mirrulations object keys must be globally sorted, distinct, and match agency/collection"
                )
            if not isinstance(etag, str) or not etag:
                raise RegulationsGovSourceError(f"Mirrulations object {key} lacks a source ETag")
            if version_id is not None and (not isinstance(version_id, str) or not version_id):
                raise RegulationsGovSourceError(f"Mirrulations object {key} version is invalid")
            if not isinstance(content, bytes) or not content or len(content) > MAX_OBJECT_BYTES:
                raise RegulationsGovSourceError(f"Mirrulations object {key} bytes are invalid")
            record = classifier(_decode_json(content))
            identity = source_record_id(record)
            if _key_claimed_identity(key) != identity:
                raise RegulationsGovSourceError(
                    f"Mirrulations object key {key} does not match body identity {identity}"
                )
            included = _record_in_scope(
                record,
                query_scope=scope,
                agency=agency,
                collection=collection,
            )
            if pack and (
                len(pack) == MAX_EVIDENCE_PACK_OBJECTS or pack_raw_bytes + len(content) > MAX_EVIDENCE_PACK_RAW_BYTES
            ):
                request_key = _pack_request(
                    collection=collection,
                    agency=agency,
                    pack_index=pack_index,
                    terminal=False,
                )
                yield RegulationsGovPage(
                    traversal_index=0,
                    page_index=page_index,
                    window_index=page_index,
                    window_page_index=0,
                    request_key=request_key,
                    source_cursor=None,
                    response_bytes=_pack_bytes(
                        pack,
                        collection=collection,
                        agency=agency,
                        pack_index=pack_index,
                        terminal=False,
                    ),
                )
                page_index += 1
                pack_index += 1
                pack = []
                pack_raw_bytes = 0
            pack.append(
                _PackedObject(
                    key=key,
                    etag=etag,
                    version_id=version_id,
                    content=content,
                    included=included,
                )
            )
            pack_raw_bytes += len(content)
            previous_global_key = key
        request_key = _pack_request(
            collection=collection,
            agency=agency,
            pack_index=pack_index,
            terminal=True,
        )
        yield RegulationsGovPage(
            traversal_index=0,
            page_index=page_index,
            window_index=page_index,
            window_page_index=0,
            request_key=request_key,
            source_cursor=None,
            response_bytes=_pack_bytes(
                pack,
                collection=collection,
                agency=agency,
                pack_index=pack_index,
                terminal=True,
            ),
        )
        page_index += 1


def iter_regulations_gov_document_pages(
    read: RegulationsGovRead,
    *,
    query_scope: Mapping[str, Any],
    scratch_directory: Path | None = None,
) -> Iterator[RegulationsGovPage]:
    return _iter_pages(
        read,
        query_scope=query_scope,
        collection=DOCUMENT_COLLECTION,
        scope_validator=regulations_gov_document_query_scope,
        classifier=classify_document,
        scratch_directory=scratch_directory,
    )


def iter_regulations_gov_docket_pages(
    read: RegulationsGovRead,
    *,
    query_scope: Mapping[str, Any],
    scratch_directory: Path | None = None,
) -> Iterator[RegulationsGovPage]:
    return _iter_pages(
        read,
        query_scope=query_scope,
        collection=DOCKET_COLLECTION,
        scope_validator=regulations_gov_docket_query_scope,
        classifier=classify_docket,
        scratch_directory=scratch_directory,
    )


def iter_regulations_gov_comment_pages(
    read: RegulationsGovRead,
    *,
    query_scope: Mapping[str, Any],
    scratch_directory: Path | None = None,
) -> Iterator[RegulationsGovPage]:
    return _iter_pages(
        read,
        query_scope=query_scope,
        collection=COMMENT_COLLECTION,
        scope_validator=regulations_gov_comment_query_scope,
        classifier=classify_comment,
        scratch_directory=scratch_directory,
    )
