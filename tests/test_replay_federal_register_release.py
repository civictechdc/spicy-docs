"""Hermetic coverage for ``src/spicy_docs/sources/federal_register/replay.py`` (SD-25).

Every release built below goes through the real, unmodified
``FEDERAL_REGISTER_PROFILE`` and ``iter_federal_register_pages`` -- the same
pipeline ``spicy_docs.cli.source_native``'s ``publish`` command drives -- with
a small in-memory ``{url: bytes}`` fake standing in for the live Federal
Register API. No test here makes, or could make, an HTTP request: the fake
fetch below is a plain dict lookup, and the tool under test imports no HTTP
client (see its module docstring).

Note: Federal Register's ``traversal_acceptance`` is
``"stable-consecutive-traversals"`` (``SourceNativeProfile`` in
``source_native_profiles.py``), which ``_accepted_traversal`` in
``source_native.py`` requires *at least two* traversals to satisfy -- a
single-traversal acquisition is refused outright. So every release built here
uses the default ``traversals=2``, and a requestKey a single traversal visits
once is therefore retained twice in the release's acquisition-page rows (once
per traversal) even though it is one distinct request.
"""

from __future__ import annotations

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
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
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
    verifier_version="1.0",
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


def _release_records(root: Path, blob_store: Path) -> dict[str, Any]:
    reader = SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(blob_store, create=False),
        profile=FEDERAL_REGISTER_PROFILE,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
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
