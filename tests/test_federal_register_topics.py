"""Literal topics observations, source bounds and explicit mocked acquisition."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
import pytest

from spicy_docs.sources.federal_register.topics import (
    FR_TOPICS_URL,
    FrTopicsAcquirer,
    FrTopicsBudget,
    FrTopicsSourceError,
    FrTopicsUnavailableError,
    read_fr_topics,
)
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURE = Path(__file__).parent / "fixtures/federal_register_topics/federal-register-topics-2026-08-03.json"


def example() -> dict:
    return {
        "meta": {"count": {"thesaurus": 1, "ad_hoc": 0, "total": 1}},
        "results": {
            "thesaurus": [
                {
                    "name": " A topic ",
                    "slug": "topic",
                    "see": [],
                    "see_also": [{"name": "Target", "slug": "target"}],
                    "cfr_references": [],
                }
            ],
            "ad_hoc": [],
        },
    }


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


def test_full_retained_response_preserves_every_row_and_path():
    payload = FIXTURE.read_bytes()
    raw = json.loads(payload)
    result = read_fr_topics(payload)
    assert result.input_sha256 == "aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b"
    assert result.input_bytes == 920705
    assert result.raw == raw
    assert result.declared_counts == result.observed_counts == {"thesaurus": 1044, "ad_hoc": 6723, "total": 7767}
    collisions = empty_slugs = 0
    for collection in result.collections:
        rows = raw["results"][collection.name]
        assert collection.raw == rows
        assert collection.source_path == f"$.results.{collection.name}"
        assert len(collection.rows) == len(rows)
        counts = Counter(row.slug for row in collection.rows)
        collisions += sum(count > 1 for count in counts.values())
        empty_slugs += counts[""]
        for index, row in enumerate(collection.rows):
            assert row.raw == rows[index]
            assert row.source_ordinal == index
            assert row.source_path == f"{collection.source_path}[{index}]"
            assert (row.name, row.slug) == (rows[index]["name"], rows[index]["slug"])
            for name in ("see", "see_also"):
                links = getattr(row, name)
                assert [link.raw for link in links] == rows[index][name]
                for ordinal, link in enumerate(links):
                    assert link.source_path == f"{row.source_path}.{name}[{ordinal}]"
                    assert (link.name, link.slug) == (link.raw["name"], link.raw["slug"])
            assert row.cfr_references == ()
    assert (collisions, empty_slugs) == (76, 3)


def test_unknown_fields_empty_values_counts_and_collection_order_survive():
    raw = example()
    raw["extension"] = {"a/b~c": [None, False, 1.25]}
    raw["meta"]["extension"] = "literal"
    raw["meta"]["count"]["total"] = -10
    raw["meta"]["count"]["unknown"] = ["count metadata"]
    row = raw["results"]["thesaurus"][0]
    row.update(name="", slug="", extension=" kept ")
    row["see_also"] = [{"name": "", "slug": "", "unknown": []}]
    row["cfr_references"] = [None, 42, 1.25, True, "raw", [], {"title": "unknown", "part": ["x"]}]
    raw["results"] = {"ad_hoc": [], "unknown": {"unparsed": None}, "thesaurus": [row, copy.deepcopy(row)]}
    payload = encoded(raw)
    result = read_fr_topics(payload)
    assert result.raw == raw
    assert result.input_sha256 == hashlib.sha256(payload).hexdigest()
    assert [collection.name for collection in result.collections] == ["ad_hoc", "thesaurus"]
    assert result.declared_counts["total"] == -10
    assert result.observed_counts == {"ad_hoc": 0, "thesaurus": 2, "total": 2}
    first = result.collections[1].rows[0]
    assert first.name == first.slug == first.see_also[0].name == ""
    assert [reference.raw for reference in first.cfr_references] == row["cfr_references"]
    assert [reference.source_path for reference in first.cfr_references] == [
        f"$.results.thesaurus[0].cfr_references[{i}]" for i in range(7)
    ]


@pytest.mark.parametrize(
    "path",
    [
        ("meta",),
        ("results",),
        ("meta", "count"),
        ("meta", "count", "total"),
        ("results", "thesaurus"),
        ("results", "ad_hoc"),
        *(("results", "thesaurus", 0, key) for key in ("name", "slug", "see", "see_also", "cfr_references")),
        ("results", "thesaurus", 0, "see_also", 0, "name"),
        ("results", "thesaurus", 0, "see_also", 0, "slug"),
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "null", "wrong-type"])
def test_missing_null_or_wrong_typed_known_fields_refuse(path, mutation):
    raw = example()
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    if mutation == "missing":
        del parent[path[-1]]
    else:
        parent[path[-1]] = None if mutation == "null" else False
    with pytest.raises(FrTopicsSourceError):
        read_fr_topics(encoded(raw))


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"meta":{},"meta":{}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b'{"x":' + b"9" * 5000 + b"}",
    ],
)
def test_invalid_ambiguous_or_unrecognized_json_refuses(payload):
    with pytest.raises(FrTopicsSourceError):
        read_fr_topics(payload)


@pytest.mark.parametrize("limits", [{"max_bytes": 1}, {"max_nodes": 1}, {"max_depth": 1}, {"max_nodes": True}])
def test_bounds_cover_unknown_input_too(limits):
    raw = example()
    raw["extension"] = {"deep": [1, 2, 3]}
    with pytest.raises(FrTopicsSourceError):
        read_fr_topics(encoded(raw), **limits)


def acquirer(handler, *, max_bytes=16 * 1024**2):
    return FrTopicsAcquirer(budget=FrTopicsBudget(1, max_bytes, 10, 0), transport=httpx.MockTransport(handler))


def test_explicit_capture_returns_exact_bytes_and_one_shared_read():
    payload = encoded(example())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(payload), headers={"content-type": "application/json"})

    with acquirer(respond) as source:
        result = source.acquire_topics()
    assert len(requests) == result.request_count == 1
    assert str(requests[0].url) == FR_TOPICS_URL
    assert requests[0].headers["accept"] == "application/json"
    assert result.capture.body == payload
    assert result.capture.resolved_url == FR_TOPICS_URL
    assert result.topics.observed_counts["total"] == 1


@pytest.mark.parametrize(
    "status,body,headers,error",
    [
        (200, b"<html>challenge</html>", {"content-type": "text/html"}, FrTopicsSourceError),
        (200, b"{}", {"content-type": "application/json"}, FrTopicsSourceError),
        (302, b"redirect", {"location": "https://example.com/challenge"}, FrTopicsSourceError),
        (404, b"missing", {}, FrTopicsUnavailableError),
    ],
)
def test_transport_or_source_refusal_never_returns_topics(status, body, headers, error):
    def respond(request):
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)

    with acquirer(respond) as source, pytest.raises(error):
        source.acquire_topics()


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("body", [b"", b"refused", b"x" * 11])
def test_public_access_refusal_retains_only_complete_bounded_evidence(status, body):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": "text/plain"})

    with acquirer(respond, max_bytes=10) as source, pytest.raises(CredentialRefusedError) as caught:
        source.acquire_topics()
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers
    assert caught.value.fr_topics_acquisition == {"operation": "topics", "requestCount": 1}
    refusal = caught.value.refused_response
    assert refusal.request_key == FR_TOPICS_URL
    assert refusal.observed_byte_size == len(body)
    if len(body) <= 10:
        assert refusal.response_bytes == body
        assert refusal.unavailable_reason == "access-refused"
    else:
        assert refusal.response_bytes is None
        assert refusal.unavailable_reason == "response-byte-limit"


def test_capture_byte_budget_refuses_oversized_response():
    payload = encoded(example())
    with (
        acquirer(lambda request: httpx.Response(200, stream=httpx.ByteStream(payload)), max_bytes=10) as source,
        pytest.raises(FrTopicsSourceError, match="byte bound"),
    ):
        source.acquire_topics()


def test_changed_final_url_refuses_with_response_evidence():
    payload = encoded(example())

    class ChangedUrlResponse(httpx.Response):
        @property
        def url(self):
            return httpx.URL("https://example.com/challenge")

    def respond(request):
        return ChangedUrlResponse(200, stream=httpx.ByteStream(payload), headers={"content-type": "application/json"})

    with acquirer(respond) as source, pytest.raises(FrTopicsSourceError, match="final URL differs") as caught:
        source.acquire_topics()
    assert caught.value.capture.body == payload
    assert caught.value.capture.resolved_url == "https://example.com/challenge"
    assert caught.value.fr_topics_acquisition == {"operation": "topics", "requestCount": 1}


def test_parser_import_does_not_require_httpx():
    code = """
import importlib.abc
import sys
class NoHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "httpx" or fullname.startswith("httpx."):
            raise AssertionError("core parser imported HTTPX")
sys.meta_path.insert(0, NoHttpx())
from spicy_docs.sources.federal_register.topics import read_fr_topics
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
