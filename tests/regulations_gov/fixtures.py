"""Regulations Gov: fixtures behavior."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rulespec_artifacts import LocalMemberSource, Producer

from spicy_docs.regulations_gov_source_native import (
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    RegulationsGovPage,
    docket_source_record_digest,
    document_source_record_digest,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native_profiles import (
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.source_native_store import LocalSourceNativeBlobStore

_IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
_PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=_IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="1.0",
    verifier_implementation_id=_IMPLEMENTATION_ID,
)


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


def _document(identity: str = "EPA-2026-0001-0001", **attributes: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "additionalRins": ["2060-AV12", "source-value-that-is-not-a-rin"],
        "agencyId": "EPA",
        "commentEndDate": None,
        "docketId": "EPA-2026-0001",
        "documentType": "Notice",
        "fileFormats": [
            {
                "fileUrl": f"https://downloads.regulations.gov/{identity}/content.pdf",
                "format": "pdf",
                "size": 123,
            },
            {
                "fileUrl": f"https://downloads.regulations.gov/{identity}/notice.xml",
                "format": "xml",
                "size": None,
            },
        ],
        "frDocNum": "2026-10001",
        "modifyDate": "2026-08-25T01:02:03Z",
        "postedDate": "2026-08-24T04:00:00Z",
        "reasonWithdrawn": "Issued in error",
        "subtype": None,
        "title": "Exact source title",
        "topics": ["Air quality", {"id": "source-topic", "label": "Source topic"}],
        "withdrawn": True,
    }
    values.update(attributes)
    return {
        "data": {
            "id": identity,
            "type": DOCUMENT_COLLECTION,
            "attributes": values,
            "links": {"self": f"https://api.regulations.gov/v4/documents/{identity}"},
        },
        "included": [
            {
                "id": f"{identity}-attachment-1",
                "type": "attachments",
                "attributes": {
                    "description": None,
                    "fileFormats": [
                        {
                            "fileUrl": (f"https://downloads.regulations.gov/{identity}/attachment.docx"),
                            "format": "docx",
                            "size": "99",
                        }
                    ],
                    "title": "Supporting attachment",
                },
            }
        ],
        "meta": {"hasMore": False, "totalElements": 1},
    }


def _docket(identity: str = "EPA-2026-0001", **attributes: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "agencyId": "EPA",
        "category": None,
        "displayProperties": [{"name": "abstract", "label": "Description", "tooltip": None}],
        "dkAbstract": "Exact docket abstract",
        "docketType": "Rulemaking",
        "keywords": ["air", "emissions"],
        "modifyDate": "2026-08-24T05:00:00Z",
        "rin": None,
        "title": "Exact docket title",
    }
    values.update(attributes)
    return {
        "data": {
            "id": identity,
            "type": DOCKET_COLLECTION,
            "attributes": values,
            "links": {"self": f"https://api.regulations.gov/v4/dockets/{identity}"},
        }
    }


def _bytes(value: object, *, indent: int | None = None) -> bytes:
    return json.dumps(value, indent=indent, separators=None if indent else (",", ":")).encode()


@dataclass(frozen=True, slots=True)
class _Object:
    key: str
    etag: str
    version_id: str | None
    content: bytes


class _Reader:
    def __init__(self, objects: list[_Object], calls: list[tuple[str, int]] | None = None) -> None:
        self.objects = objects
        self.calls = calls

    def iter_source_objects(self, *, max_bytes: int) -> Iterator[_Object]:
        if self.calls is not None:
            self.calls.append(("iter", max_bytes))
        yield from self.objects


def _document_object(
    identity: str = "EPA-2026-0001-0001",
    *,
    value: dict[str, Any] | None = None,
    etag: str = '"document-etag"',
    tag: str = "1",
    agency: str = "EPA",
    docket_id: str = "EPA-2026-0001",
    key_suffix: str = "",
) -> _Object:
    return _Object(
        key=(f"raw-data/{agency}/{docket_id}/text-{tag}/documents/{identity}{key_suffix}.json"),
        etag=etag,
        version_id="document-version-1",
        content=_bytes(value or _document(identity), indent=2),
    )


def _docket_object(
    identity: str = "EPA-2026-0001",
    *,
    value: dict[str, Any] | None = None,
    etag: str = '"docket-etag"',
    tag: str = "1",
    agency: str = "EPA",
    key_suffix: str = "",
) -> _Object:
    return _Object(
        key=f"raw-data/{agency}/{identity}/text-{tag}/docket/{identity}{key_suffix}.json",
        etag=etag,
        version_id=None,
        content=_bytes(value or _docket(identity), indent=2),
    )


def _document_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "publishedFrom": "2026-08-24",
        "publishedThrough": "2026-08-24",
    }


def _docket_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "modifiedFrom": "2026-08-24",
        "modifiedThrough": "2026-08-24",
    }


def _build(query_scope: dict[str, object]) -> SourceNativeReleaseBuild:
    return SourceNativeReleaseBuild(
        query_scope=query_scope,
        producer=_PRODUCER,
        started_at="2026-08-25T00:00:00Z",
    )


def _reader(root: Path, pin, profile) -> SourceNativeReleaseReader:
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(root.parent / "blobs"),
        profile=profile,
        expected_pin=pin,
        accepted_verifier_implementation_ids=frozenset({_IMPLEMENTATION_ID}),
    )


def _acf_docket_scope() -> dict[str, object]:
    return {
        "agencies": ["ACF"],
        "modifiedFrom": "2021-01-01",
        "modifiedThrough": "2024-12-31",
    }


def _acf_document_scope() -> dict[str, object]:
    return {
        "agencies": ["ACF"],
        "publishedFrom": "2021-01-01",
        "publishedThrough": "2024-12-31",
    }


def _reordered(value: Any) -> Any:
    """Rebuild a JSON-decodable value with every mapping's keys reversed.

    Content-equal to ``value`` — a JSON parser decodes the identical record
    either way — but serializing this alongside the original produces two
    byte-different encodings of that one record, proving the collapse keys
    equality on the canonical record digest, not raw bytes.
    """
    if isinstance(value, dict):
        return {key: _reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reordered(item) for item in value]
    return value


@dataclass(frozen=True)
class _CollapseFixture:
    collection: str
    profile: Any
    scope: dict[str, object]
    identity: str
    iter_pages: Callable[..., Iterator[RegulationsGovPage]]
    record_digest: Callable[[Mapping[str, Any]], str]
    older: dict[str, Any]
    newest: dict[str, Any]
    build_object: Callable[..., _Object]


def _docket_collapse_fixture() -> _CollapseFixture:
    identity = "ACF-2007-0125"
    return _CollapseFixture(
        collection="docket",
        profile=REGULATIONS_GOV_DOCKET_PROFILE,
        scope=_acf_docket_scope(),
        identity=identity,
        iter_pages=iter_regulations_gov_docket_pages,
        record_digest=docket_source_record_digest,
        older=_docket(identity, agencyId="ACF", modifyDate="2021-02-12T01:00:50Z", title="older observation"),
        newest=_docket(identity, agencyId="ACF", modifyDate="2024-06-12T01:16:04Z", title="newest observation"),
        build_object=lambda *, value, tag: _docket_object(identity, value=value, tag=tag, agency="ACF"),
    )


def _document_collapse_fixture() -> _CollapseFixture:
    identity = "ACF-2021-0001-0001"
    return _CollapseFixture(
        collection="document",
        profile=REGULATIONS_GOV_DOCUMENT_PROFILE,
        scope=_acf_document_scope(),
        identity=identity,
        iter_pages=iter_regulations_gov_document_pages,
        record_digest=document_source_record_digest,
        older=_document(
            identity,
            agencyId="ACF",
            docketId="ACF-2021-0001",
            modifyDate="2021-03-01T00:00:00Z",
            postedDate="2021-02-15T00:00:00Z",
            title="older observation",
        ),
        newest=_document(
            identity,
            agencyId="ACF",
            docketId="ACF-2021-0001",
            modifyDate="2024-06-12T01:16:04Z",
            postedDate="2021-02-15T00:00:00Z",
            title="newest observation",
        ),
        build_object=lambda *, value, tag: _document_object(
            identity, value=value, tag=tag, agency="ACF", docket_id="ACF-2021-0001"
        ),
    )


def _bis_document_scope() -> dict[str, object]:
    return {
        "agencies": ["BIS"],
        "publishedFrom": "2023-01-01",
        "publishedThrough": "2023-12-31",
    }


def _epa_hq_document_scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "publishedFrom": "2024-01-01",
        "publishedThrough": "2024-12-31",
    }
