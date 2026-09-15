"""Check offline replay through the production Federal Register profile and page iterator.

A URL-to-bytes dictionary replaces live fetches. Each release uses two traversals
to satisfy stable-consecutive-traversals acceptance; one traversal is refused.
A URL visited once per traversal therefore produces two retained acquisition-page
rows but one distinct request.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from rulespec_artifacts import LocalMemberSource, Producer

import spicy_docs.sources.federal_register.replay as replay_tool
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native.profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import (
    federal_register_documents_url,
    iter_federal_register_pages,
)
from spicy_docs.sources.federal_register.replay import (
    ReplayEvidenceMissingError,
    build_replay_fetch,
    build_request_map,
    replay,
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


def _source_started_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


def _replay_started_at() -> datetime:
    return datetime(2026, 8, 25, 1, 0, 0, tzinfo=UTC)


def _document(number: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "agencies": [],
        "body_html_url": None,
        "document_number": number,
        "html_url": f"https://www.federalregister.gov/d/{number}",
        "pdf_url": None,
        "publication_date": "2026-08-25",
        "regulation_id_numbers": ["not-a-rin"],
        "title": f"A source-native rule {number}",
        "topics": [],
        "type": "Rule",
    }
    value.update(changes)
    return value


def _single_page_fetch_map(*documents: dict[str, object]) -> tuple[dict[str, bytes], str]:
    """One window, one page, one distinct requestKey."""

    url = federal_register_documents_url(QUERY_SCOPE)
    return {url: federal_response(*documents)}, url


def _two_page_fetch_map(first: dict[str, object], second: dict[str, object]) -> tuple[dict[str, bytes], list[str]]:
    """One window split across two pages -- two distinct requestKeys."""

    page_one_url = federal_register_documents_url(QUERY_SCOPE)
    page_two_url = "https://www.federalregister.gov/api/v1/documents.json?cursor=page-2"
    fetch_map = {
        page_one_url: federal_response(first, next_page_url=page_two_url, count=2, total_pages=2),
        page_two_url: federal_response(second, next_page_url=None, count=2, total_pages=2),
    }
    return fetch_map, [page_one_url, page_two_url]


def _publish_source_release(
    tmp_path: Path,
    fetch_map: dict[str, bytes],
    *,
    subdir: str = "source",
) -> tuple[Path, Path]:
    """Publish one real Federal Register source-native release, backed by the
    fake ``fetch_map`` in place of a live HTTP client, and return its root and
    the blob store holding its retained evidence."""

    blob_store = tmp_path / "blobs"

    def fetch(url: str) -> bytes:
        return fetch_map[url]

    SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=LocalSourceNativeBlobStore(blob_store),
        clock=_source_started_at,
    ).publish(
        iter_federal_register_pages(fetch, query_scope=QUERY_SCOPE),
        build=SourceNativeReleaseBuild(
            query_scope=QUERY_SCOPE,
            producer=PRODUCER,
            started_at="2026-08-25T00:00:00Z",
        ),
        destination=tmp_path / subdir,
    )
    return tmp_path / subdir, blob_store


def _release_reader(root: Path, blob_store: Path) -> SourceNativeReleaseReader:
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(blob_store, create=False),
        profile=FEDERAL_REGISTER_PROFILE,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )


def _release_records(root: Path, blob_store: Path) -> dict[str, Any]:
    reader = _release_reader(root, blob_store)
    return {row["sourceRecordId"]: row["record"] for row in reader.iter_records()}


def test_replay_reproduces_the_same_record_set(tmp_path: Path) -> None:
    documents = [_document("2026-00001"), _document("2026-00002")]
    fetch_map, _url = _single_page_fetch_map(*documents)
    release_root, blob_store = _publish_source_release(tmp_path, fetch_map)

    destination = tmp_path / "replayed"
    summary = replay(
        release_root=release_root,
        blob_store=blob_store,
        destination=destination,
        implementation_id=IMPLEMENTATION_ID,
        clock=_replay_started_at,
    )

    assert summary["publishedRecordCount"] == 2
    assert summary["discardedObservationCount"] == 0
    assert summary["inputObservationCount"] == 2
    assert summary["distinctRequestKeysMatchSource"] is True

    source_records = _release_records(release_root, blob_store)
    replayed_records = _release_records(destination, blob_store)
    assert len(source_records) == 2
    assert replayed_records == source_records


def test_publisher_xml_links_absence_and_null_survive_admission_and_replay(tmp_path: Path) -> None:
    xml_url = "https://www.federalregister.gov/documents/full_text/xml/2026/08/25/2026-00001.xml"
    documents = [
        _document("2026-00001", full_text_xml_url=xml_url),
        _document("2026-00002", full_text_xml_url=None),
        _document(
            "2026-00003",
            body_html_url="https://www.federalregister.gov/documents/full_text/html/2026/08/25/2026-00003.html",
        ),
    ]
    fetch_map, url = _single_page_fetch_map(*documents)
    assert "fields%5B%5D=full_text_xml_url" in url
    release_root, blob_store = _publish_source_release(tmp_path, fetch_map)
    destination = tmp_path / "replayed"
    summary = replay(
        release_root=release_root,
        blob_store=blob_store,
        destination=destination,
        implementation_id=IMPLEMENTATION_ID,
        clock=_replay_started_at,
    )
    assert summary["publishedRecordCount"] == 3
    for root in (release_root, destination):
        reader = _release_reader(root, blob_store)
        records = list(reader.iter_records())
        assert [row["record"] for row in records] == documents
        assert {row["schemaVersion"] for row in records} == {"1.1"}
        schema = json.loads((root / "schemas/federal-register-document-1.1.schema.json").read_bytes())
        assert schema["$id"] == "urn:spicy-regs:schema:federal-register-document:1.1"
        assert schema["properties"]["full_text_xml_url"] == {"minLength": 1, "type": ["string", "null"]}
        assert not (root / "schemas/federal-register-document-1.0.schema.json").exists()
        xml_renditions = [row for row in reader.iter_renditions() if row["renditionId"] == "body-xml"]
        assert xml_renditions == [
            {
                "expectedByteSize": None,
                "expectedSha256": None,
                "locator": locator,
                "mediaType": "application/xml",
                "renditionId": "body-xml",
                "sourceField": "full_text_xml_url",
                "sourceRecordId": f"2026-0000{index}@2026-08-25",
            }
            for index, locator in enumerate((xml_url, None, None), start=1)
        ]


def test_replay_fetch_raises_naming_a_missing_request_key(tmp_path: Path) -> None:
    fetch_map, _url = _single_page_fetch_map(_document("2026-00001"))
    release_root, blob_store = _publish_source_release(tmp_path, fetch_map)

    request_map, _page_row_count = build_request_map(release_root, blob_store)
    missing_url = next(iter(request_map))
    del request_map[missing_url]

    fetch, stats = build_replay_fetch(request_map, LocalSourceNativeBlobStore(blob_store, create=False))
    with pytest.raises(ReplayEvidenceMissingError, match=re.escape(missing_url)):
        fetch(missing_url)
    # The raise happened before anything was recorded as served.
    assert stats.call_count == 1
    assert missing_url not in stats.served_urls


def test_distinct_request_key_count_equals_one_traversals_page_row_count(tmp_path: Path) -> None:
    """Two traversals each visit the same two pages, so the release retains
    four acquisition-page rows total -- but only two distinct requestKeys,
    exactly the row count of either traversal alone. See the module
    docstring for why one traversal is not enough to build an accepted
    Federal Register release at all."""

    fetch_map, urls = _two_page_fetch_map(_document("2026-00001"), _document("2026-00002"))
    release_root, blob_store = _publish_source_release(tmp_path, fetch_map)

    request_map, page_row_count = build_request_map(release_root, blob_store)
    assert set(request_map) == set(urls)
    assert len(request_map) == len(urls) == 2
    assert page_row_count == 2 * len(urls) == 4


def test_repeated_url_across_traversals_is_served_not_missed(tmp_path: Path) -> None:
    documents = [_document("2026-00001"), _document("2026-00002")]
    fetch_map, _url = _single_page_fetch_map(*documents)
    release_root, blob_store = _publish_source_release(tmp_path, fetch_map)

    request_map, page_row_count = build_request_map(release_root, blob_store)
    assert page_row_count == 2  # one acquisition-page row per traversal
    assert len(request_map) == 1  # the same requestKey both times

    destination = tmp_path / "replayed"
    summary = replay(
        release_root=release_root,
        blob_store=blob_store,
        destination=destination,
        implementation_id=IMPLEMENTATION_ID,
        clock=_replay_started_at,
    )

    assert summary["sourceDistinctRequestKeyCount"] == 1
    assert summary["sourcePageRowCount"] == 2
    assert summary["replayFetchCallCount"] == 2  # both traversals asked for it during replay too
    assert summary["replayDistinctRequestKeysServed"] == 1
    assert summary["distinctRequestKeysMatchSource"] is True


def test_replay_uses_the_shared_source_profile() -> None:
    assert replay_tool.FEDERAL_REGISTER_PROFILE is FEDERAL_REGISTER_PROFILE


def test_record_scope_validator_refuses_a_record_outside_its_window() -> None:
    from spicy_docs.sources.federal_register.native import FederalRegisterSourceError

    window = (date(2026, 8, 25), date(2026, 8, 25))
    validate = FEDERAL_REGISTER_PROFILE.validate_record_scope
    validate({"publication_date": "2026-08-25"}, query_scope={}, page_window=window)
    with pytest.raises(FederalRegisterSourceError, match="date window"):
        validate({"publication_date": "2026-08-26"}, query_scope={}, page_window=window)
