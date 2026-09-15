"""Pre-yield Federal Register failures retain the response that actually failed."""

from __future__ import annotations

from typing import cast

import pytest

from spicy_docs.reading.refusals import RefusedResponse
from spicy_docs.sources.federal_register import native as federal
from tests.releases.fixtures import _document
from tests.source_fixtures import federal_response

SCOPE = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
INITIAL = federal.federal_register_documents_url(SCOPE)
NEXT = "https://www.federalregister.gov/api/v1/documents?format=json&page=2&cursor=stable"


def _diagnostic(error: Exception) -> RefusedResponse:
    diagnostic = getattr(error, "refused_response", None)
    assert isinstance(diagnostic, RefusedResponse)
    return diagnostic


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not JSON", "invalid Federal Register response JSON"),
        (b"", "no response bytes"),
        (b'{"count":0,"results":[],"total_pages":0}', "total_pages"),
        (federal_response(_document(), next_page_url=INITIAL, count=2, total_pages=2), "cyclic page cursor"),
    ],
)
def test_first_response_refusal_retains_exact_bytes(payload: bytes, message: str) -> None:
    pages = federal.iter_federal_register_pages(lambda _url: payload, query_scope=SCOPE, traversals=1)
    with pytest.raises(federal.FederalRegisterSourceError, match=message) as caught:
        next(pages)
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == INITIAL
    assert diagnostic.response_bytes == payload
    assert diagnostic.observed_byte_size == len(payload)
    assert diagnostic.unavailable_reason is None
    assert diagnostic.stage == "source-validation"
    assert list(pages) == []


def test_continuation_inventory_refusal_retains_the_new_page() -> None:
    first = federal_response(_document(), count=2, total_pages=2, next_page_url=NEXT)
    refused = federal_response(_document("2026-00002"), count=3, total_pages=2)
    responses = {INITIAL: first, NEXT: refused}
    pages = federal.iter_federal_register_pages(responses.__getitem__, query_scope=SCOPE, traversals=1)
    assert next(pages).response_bytes == first
    with pytest.raises(federal.FederalRegisterSourceError, match="inventory declarations changed") as caught:
        next(pages)
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == NEXT
    assert diagnostic.response_bytes == refused
    assert diagnostic.response_bytes != first


def test_continuation_parse_refusal_retains_the_new_page() -> None:
    first = federal_response(_document(), count=2, total_pages=2, next_page_url=NEXT)
    refused = b'{"count":'
    responses = {INITIAL: first, NEXT: refused}
    pages = federal.iter_federal_register_pages(responses.__getitem__, query_scope=SCOPE, traversals=1)
    assert next(pages).response_bytes == first
    with pytest.raises(federal.FederalRegisterSourceError, match="invalid Federal Register response JSON") as caught:
        next(pages)
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == NEXT
    assert diagnostic.response_bytes == refused
    with pytest.raises(federal.FederalRegisterSourceError) as offline:
        federal.parse_page_response(diagnostic.response_bytes)
    assert str(offline.value) == str(caught.value)


def test_continuation_transport_failure_never_attaches_the_previous_page() -> None:
    first = federal_response(_document(), count=2, total_pages=2, next_page_url=NEXT)
    original = OSError("connection ended before a response")

    def fetch(url: str) -> bytes:
        if url == INITIAL:
            return first
        assert url == NEXT
        raise original

    pages = federal.iter_federal_register_pages(fetch, query_scope=SCOPE, traversals=1)
    assert next(pages).response_bytes == first
    with pytest.raises(OSError) as caught:
        next(pages)
    assert caught.value is original
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == NEXT
    assert diagnostic.stage == "transport"
    assert diagnostic.response_bytes is None
    assert diagnostic.unavailable_reason == "transport-unavailable"


def test_nested_split_refusal_keeps_child_context() -> None:
    scope = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-14"}
    parent_url = federal.federal_register_documents_url(scope)
    parent = federal_response(_document(), count=10_000, total_pages=10)
    child = b"refused child response"
    requests = []

    def fetch(url: str) -> bytes:
        requests.append(url)
        return parent if url == parent_url else child

    pages = federal.iter_federal_register_pages(fetch, query_scope=scope, traversals=1)
    assert next(pages).response_bytes == parent
    with pytest.raises(federal.FederalRegisterSourceError, match="invalid Federal Register response JSON") as caught:
        next(pages)
    diagnostic = _diagnostic(caught.value)
    assert requests == [parent_url, INITIAL]
    assert diagnostic.request_key == INITIAL
    assert diagnostic.response_bytes == child


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (federal_response(_document(), count=2, total_pages=1), "declared and observed record counts"),
        (federal_response(_document(), count=10_000, total_pages=10), "result cap is ambiguous"),
    ],
)
def test_post_yield_refusal_keeps_the_relevant_terminal_evidence(payload: bytes, message: str) -> None:
    pages = federal.iter_federal_register_pages(lambda _url: payload, query_scope=SCOPE, traversals=1)
    assert next(pages).response_bytes == payload
    with pytest.raises(federal.FederalRegisterSourceError, match=message) as caught:
        next(pages)
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.request_key == INITIAL
    assert diagnostic.response_bytes == payload


def test_oversized_response_records_no_truncated_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = federal_response(_document())
    monkeypatch.setattr(federal, "MAX_PAGE_BYTES", len(payload) - 1)
    with pytest.raises(federal.FederalRegisterSourceError, match="evidence byte bound") as caught:
        next(federal.iter_federal_register_pages(lambda _url: payload, query_scope=SCOPE, traversals=1))
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size == len(payload)
    assert diagnostic.unavailable_reason == "response-byte-limit"


def test_nonbytes_fetch_result_is_unavailable_instead_of_coerced() -> None:
    fetch = cast(federal.FederalRegisterFetch, lambda _url: "not exact bytes")
    with pytest.raises(federal.FederalRegisterSourceError, match="no response bytes") as caught:
        next(federal.iter_federal_register_pages(fetch, query_scope=SCOPE, traversals=1))
    diagnostic = _diagnostic(caught.value)
    assert diagnostic.response_bytes is None
    assert diagnostic.observed_byte_size is None
    assert diagnostic.unavailable_reason == "unsupported-response"
