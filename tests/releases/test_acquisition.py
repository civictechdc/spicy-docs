"""Releases: acquisition behavior."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from spicy_docs.federal_register_source_native import (
    DOCUMENT_FIELDS,
    FederalRegisterPage,
    FederalRegisterSourceError,
    federal_register_documents_url,
    iter_federal_register_pages,
    parse_page_response,
)
from spicy_docs.source_native import (
    SourceNativeReleasePublisher,
)
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from tests.releases.fixtures import (
    _build,
    _completed_at,
    _document,
    _page,
    _publish,
    _reader,
)
from tests.source_fixtures import federal_response, payload_rows


def test_injected_page_fetcher_builds_the_closed_query_and_reconciles() -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
    initial = federal_register_documents_url(scope, per_page=1000)
    next_url = "https://www.federalregister.gov/api/v1/documents?format=json&page=2&cursor=stable"
    responses = {
        initial: federal_response(
            _document("2026-00002"),
            next_page_url=next_url,
            count=2,
            total_pages=2,
        ),
        next_url: federal_response(
            _document("2026-00001"),
            count=2,
            total_pages=2,
        ),
    }
    requests: list[str] = []

    def fetch(url: str) -> bytes:
        requests.append(url)
        return responses[url]

    pages = list(iter_federal_register_pages(fetch, query_scope=scope))

    assert requests == [initial, next_url, initial, next_url]
    assert [(page.traversal_index, page.page_index, page.source_cursor) for page in pages] == [
        (0, 0, None),
        (0, 1, next_url),
        (1, 0, None),
        (1, 1, next_url),
    ]
    query = parse_qs(urlparse(initial).query)
    assert query["conditions[publication_date][gte]"] == ["2026-04-13"]
    assert query["conditions[publication_date][lte]"] == ["2026-04-13"]
    assert query["fields[]"] == sorted(DOCUMENT_FIELDS)


def test_injected_page_fetcher_refuses_incomplete_or_cyclic_inventory() -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
    initial = federal_register_documents_url(scope)

    with pytest.raises(FederalRegisterSourceError, match="declared and observed record counts"):
        list(
            iter_federal_register_pages(
                lambda _url: federal_response(_document(), count=2, total_pages=1),
                query_scope=scope,
            )
        )

    with pytest.raises(FederalRegisterSourceError, match="cyclic page cursor"):
        list(
            iter_federal_register_pages(
                lambda _url: federal_response(
                    _document(),
                    next_page_url=initial,
                    count=2,
                    total_pages=2,
                ),
                query_scope=scope,
                traversals=1,
            )
        )


def test_injected_page_fetcher_refuses_off_source_cursor_before_fetching() -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
    initial = federal_register_documents_url(scope)
    off_source_url = "https://another-publisher.example.test/api/v1/documents.json?page=2"
    # Synthetic source response: plausible pagination must still stay on the source host.
    response = federal_response(
        _document(),
        next_page_url=off_source_url,
        count=2,
        total_pages=2,
    )
    requests: list[str] = []

    def fetch(url: str) -> bytes:
        requests.append(url)
        return response

    with pytest.raises(FederalRegisterSourceError, match="unsafe page cursor"):
        list(iter_federal_register_pages(fetch, query_scope=scope, traversals=1))

    assert requests == [initial]


def test_capped_interval_splits_into_exact_ordered_leaf_evidence(tmp_path: Path) -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-14"}
    requests: list[tuple[str, str]] = []

    def fetch(url: str) -> bytes:
        query = parse_qs(urlparse(url).query)
        window = (
            query["conditions[publication_date][gte]"][0],
            query["conditions[publication_date][lte]"][0],
        )
        requests.append(window)
        if window[0] != window[1]:
            return federal_response(
                _document("2026-cap-probe", publication_date=window[0]),
                count=10_000,
                total_pages=10,
            )
        number = "2026-00013" if window[0].endswith("13") else "2026-00014"
        return federal_response(_document(number, publication_date=window[0]))

    destination = tmp_path / "split-release"
    published = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_federal_register_pages(fetch, query_scope=scope),
        build=_build(query_scope=scope),
        destination=destination,
    )
    reader = _reader(published.root, published.artifact.pin)

    assert [row["sourceRecordId"] for row in reader.iter_records()] == [
        "2026-00013@2026-04-13",
        "2026-00014@2026-04-14",
    ]
    assert (
        requests
        == [
            ("2026-04-13", "2026-04-14"),
            ("2026-04-13", "2026-04-13"),
            ("2026-04-14", "2026-04-14"),
        ]
        * 2
    )
    pages = sorted(
        payload_rows(destination, "acquisition-pages"),
        key=lambda row: (row["traversalIndex"], row["pageIndex"]),
    )
    assert [
        (
            row["traversalIndex"],
            row["windowIndex"],
            row["windowPageIndex"],
            row["recordsIncluded"],
        )
        for row in pages
    ] == [
        (0, 0, 0, False),
        (0, 1, 0, True),
        (0, 2, 0, True),
        (1, 0, 0, False),
        (1, 1, 0, True),
        (1, 2, 0, True),
    ]
    evidence_refs = {row["evidenceBlobRef"] for row in pages}
    assert len(evidence_refs) == 3
    assert not (destination / "evidence").exists()
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    evidence_counts = set()
    for blob_ref in evidence_refs:
        with store.open(blob_ref) as stream:
            evidence_counts.add(parse_page_response(stream.read())["count"])
    assert evidence_counts == {1, 10_000}


def test_capped_single_day_refuses_ambiguous_source_state() -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
    pages = iter_federal_register_pages(
        lambda _url: federal_response(
            _document("2026-cap", publication_date="2026-04-13"),
            count=10_000,
            total_pages=10,
        ),
        query_scope=scope,
    )

    probe = next(pages)
    assert parse_page_response(probe.response_bytes)["count"] == 10_000
    with pytest.raises(FederalRegisterSourceError, match="result cap is ambiguous.*2026-04-13"):
        next(pages)


@pytest.mark.parametrize(
    "days",
    [
        ["2026-04-13"],
        ["2026-04-14", "2026-04-13"],
    ],
)
def test_publisher_refuses_missing_or_reordered_date_windows(tmp_path: Path, days: list[str]) -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-14"}
    pages = [
        FederalRegisterPage(
            traversal_index=0,
            page_index=index,
            request_key=federal_register_documents_url({"publishedFrom": day, "publishedThrough": day}),
            source_cursor=None,
            response_bytes=federal_response(_document(f"2026-{day[-2:]}", publication_date=day)),
            window_index=index,
            window_page_index=0,
        )
        for index, day in enumerate(days)
    ]

    with pytest.raises(FederalRegisterSourceError, match="split windows"):
        SourceNativeReleasePublisher(
            FEDERAL_REGISTER_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            pages,
            build=_build(query_scope=scope),
            destination=tmp_path / "invalid-windows",
        )


def test_publisher_independently_refuses_a_false_source_count(tmp_path: Path) -> None:
    response = federal_response(_document(), count=2, total_pages=1)

    with pytest.raises(FederalRegisterSourceError, match="declared and observed record counts"):
        _publish(tmp_path, [_page(0, 0, response)])
