"""Hermetic coverage for ``tools/replay_federal_register_release.py`` (SD-25).

Every release built below goes through the real, unmodified
``FEDERAL_REGISTER_PROFILE`` and ``iter_federal_register_pages`` -- the same
pipeline ``spicy_docs.source_native_cli``'s ``publish`` command drives -- with
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

import dataclasses
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from rulespec_artifacts import LocalMemberSource, Producer

import tools.replay_federal_register_release as replay_tool
from spicy_docs.federal_register_source_native import (
    federal_register_documents_url,
    iter_federal_register_pages,
)
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native_profile import SourceNativeProfile
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from tools.replay_federal_register_release import (
    ReplayEvidenceMissingError,
    build_replay_fetch,
    build_request_map,
    replay,
)

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


def _response(
    *documents: dict[str, object],
    next_page_url: str | None = None,
    count: int | None = None,
    total_pages: int | None = None,
) -> bytes:
    return json.dumps(
        {
            "count": len(documents) if count is None else count,
            "next_page_url": next_page_url,
            "results": list(documents),
            "total_pages": (1 if next_page_url is None else 2) if total_pages is None else total_pages,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _single_page_fetch_map(*documents: dict[str, object]) -> tuple[dict[str, bytes], str]:
    """One window, one page, one distinct requestKey."""

    url = federal_register_documents_url(QUERY_SCOPE)
    return {url: _response(*documents)}, url


def _two_page_fetch_map(first: dict[str, object], second: dict[str, object]) -> tuple[dict[str, bytes], list[str]]:
    """One window split across two pages -- two distinct requestKeys."""

    page_one_url = federal_register_documents_url(QUERY_SCOPE)
    page_two_url = "https://www.federalregister.gov/api/v1/documents.json?cursor=page-2"
    fetch_map = {
        page_one_url: _response(first, next_page_url=page_two_url, count=2, total_pages=2),
        page_two_url: _response(second, next_page_url=None, count=2, total_pages=2),
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


def test_local_profile_matches_the_canonical_profile_field_for_field() -> None:
    """Guards the deliberate duplication the tool's module docstring names:
    ``tools.replay_federal_register_release.FEDERAL_REGISTER_PROFILE`` is
    built locally (from ``federal_register_source_native`` directly) instead
    of imported from ``spicy_docs.source_native_profiles``, so importing this
    tool never pulls GAO's ``spicy_docs.sources.zyte`` -- and therefore
    ``urllib.request`` -- into the process. Every field but
    ``validate_record_scope`` must be the exact same object (not just an
    equal-looking copy) as the canonical profile; a change to the real
    profile that this tool does not mirror fails here, not silently at the
    real corpus's replay."""

    canonical = FEDERAL_REGISTER_PROFILE
    local = replay_tool.FEDERAL_REGISTER_PROFILE
    for profile_field in dataclasses.fields(SourceNativeProfile):
        if profile_field.name == "validate_record_scope":
            continue
        assert getattr(local, profile_field.name) == getattr(canonical, profile_field.name), profile_field.name


def test_local_record_scope_validator_matches_canonical_behavior() -> None:
    """``validate_record_scope`` is the one field that cannot be the same
    object (each module defines its own private closure) -- so it is pinned
    by behavior instead: both accept a record inside its page window and
    both refuse one outside it, the same way."""

    window = (date(2026, 8, 25), date(2026, 8, 25))
    in_window = {"publication_date": "2026-08-25"}
    out_of_window = {"publication_date": "2026-08-26"}
    for validate in (
        FEDERAL_REGISTER_PROFILE.validate_record_scope,
        replay_tool.FEDERAL_REGISTER_PROFILE.validate_record_scope,
    ):
        validate(in_window, query_scope={}, page_window=window)  # does not raise
        with pytest.raises(Exception, match="date window"):
            validate(out_of_window, query_scope={}, page_window=window)
