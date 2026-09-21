"""Shared fixtures for the releases tests: Federal Register document and page builders, a collapsing profile
with a swappable observation version, and publisher/reader helpers over a temporary blob store.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rulespec_artifacts import (
    LocalMemberSource,
    Producer,
)

from spicy_docs.releases.profile import SourceNativeProfile
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native.profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import (
    FederalRegisterPage,
    federal_register_documents_url,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.source_fixtures import federal_response

IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="2.0",
    verifier_implementation_id=IMPLEMENTATION_ID,
)
QUERY_SCOPE = {"publishedFrom": "2026-08-25", "publishedThrough": "2026-08-25"}


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


class _PassAcquisitionCheck:
    def add_window(
        self,
        response: Mapping[str, Any],
        *,
        page_window: object | None,
        records_included: bool,
        response_bytes: bytes,
    ) -> None:
        del response, page_window, records_included, response_bytes

    def finish(self, *, query_scope: Mapping[str, Any]) -> None:
        del query_scope


def _accept_all_records(
    response: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> bool:
    del response, query_scope, page_window
    return True


def _accept_record_scope(
    record: Mapping[str, Any],
    *,
    query_scope: Mapping[str, Any],
    page_window: object | None,
) -> None:
    del record, query_scope, page_window


def _request_window(request_key: str) -> object:
    return request_key


def _publication_version(record: Mapping[str, Any]) -> str | None:
    return str(record["publication_date"])


def _signing_date_version(record: Mapping[str, Any]) -> str | None:
    """A version proxy independent of publication_date: composite identity (SD-24) folds publication_date into
    sourceRecordId itself, so it cannot vary within one identity. Tests that want several observations of one
    identity to carry different versions hold publication_date fixed and vary this stand-in instead.
    """

    return str(record["signing_date"])


def _document(number: str = "2026-00001", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "agencies": [],
        "body_html_url": None,
        "document_number": number,
        "html_url": f"https://www.federalregister.gov/d/{number}",
        "pdf_url": None,
        "publication_date": "2026-08-25",
        "regulation_id_numbers": ["not-a-rin"],
        "title": "A source-native rule",
        "topics": [],
        "type": "Rule",
    }
    value.update(changes)
    return value


def _page(
    traversal: int,
    page: int,
    response: bytes,
    *,
    cursor: str | None = None,
    window: dict[str, str] | None = None,
) -> FederalRegisterPage:
    return FederalRegisterPage(
        traversal_index=traversal,
        page_index=page,
        request_key=cursor or federal_register_documents_url(window or QUERY_SCOPE),
        source_cursor=cursor,
        response_bytes=response,
        window_index=0,
        window_page_index=page,
    )


def _build(*, query_scope: dict[str, str] | None = None) -> SourceNativeReleaseBuild:
    return SourceNativeReleaseBuild(
        query_scope=query_scope or QUERY_SCOPE,
        producer=PRODUCER,
        started_at="2026-08-25T00:00:00Z",
    )


def _stable_pages(
    *documents: dict[str, object],
    window: dict[str, str] | None = None,
) -> list[FederalRegisterPage]:
    response = federal_response(*documents)
    return [_page(0, 0, response, window=window), _page(1, 0, response, window=window)]


def _stable_paged_pages(
    *documents: dict[str, object],
) -> list[FederalRegisterPage]:
    pages: list[FederalRegisterPage] = []
    for traversal in range(2):
        cursor: str | None = None
        for page_index, document in enumerate(documents):
            next_cursor = (
                None
                if page_index == len(documents) - 1
                else (f"https://www.federalregister.gov/api/v1/documents?format=json&page={page_index + 2}")
            )
            pages.append(
                _page(
                    traversal,
                    page_index,
                    federal_response(
                        document,
                        next_page_url=next_cursor,
                        count=len(documents),
                        total_pages=len(documents),
                    ),
                    cursor=cursor,
                )
            )
            cursor = next_cursor
    return pages


def _collapsing_profile(
    *,
    refuse_equal_observation_versions: bool = False,
    observation_version: Callable[[Mapping[str, Any]], str | None] = _publication_version,
) -> SourceNativeProfile:
    """The Federal Register profile taught to collapse repeated observations."""

    return replace(
        FEDERAL_REGISTER_PROFILE,
        acquisition_check=_PassAcquisitionCheck,
        observation_version=observation_version,
        page_window=_request_window,
        records_included=_accept_all_records,
        refuse_equal_observation_versions=refuse_equal_observation_versions,
        validate_record_scope=_accept_record_scope,
    )


def _publish(
    tmp_path: Path,
    pages: list[FederalRegisterPage],
    *,
    profile: SourceNativeProfile = FEDERAL_REGISTER_PROFILE,
    query_scope: dict[str, str] | None = None,
):
    return SourceNativeReleasePublisher(
        profile,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        pages,
        build=_build(query_scope=query_scope),
        destination=tmp_path / "release",
    )


def _reader(root: Path, pin, *, profile: SourceNativeProfile = FEDERAL_REGISTER_PROFILE):
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(root.parent / "blobs"),
        profile=profile,
        expected_pin=pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )


def _partition_map(root: Path) -> dict[tuple[str, str], dict[str, object]]:
    receipt = json.loads((root / "receipts/publication.json").read_bytes())
    return {(value["partitionKind"], value["partitionId"]): value for value in receipt["payloadPartitions"]}


class _CountingBlobSource:
    def __init__(self, store: LocalSourceNativeBlobStore) -> None:
        self._store = store
        self.active = 0
        self.maximum = 0

    @contextmanager
    def open(self, blob_ref: str):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            with self._store.open(blob_ref) as stream:
                yield stream
        finally:
            self.active -= 1
