"""Exact publisher metadata and complete live listing traversal, without network access."""

from __future__ import annotations

import io
from datetime import date
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

import pytest

from spicy_docs.sources.courtlistener import bulk, listing
from spicy_docs.sources.courtlistener.listing import BulkObject, parse_listing_page


def _entry(key: str, *, size: str = "10", etag: str = '"etag-3"', modified: str = "2026-06-30T04:11:47.000Z") -> str:
    return (
        f"<Contents><Key>{escape(key)}</Key><Size>{escape(size)}</Size>"
        f"<ETag>{escape(etag)}</ETag><LastModified>{escape(modified)}</LastModified></Contents>"
    )


def _page(
    entries: str = "", *, truncated: str = "false", token: str | None = None, prefix: str = "bulk-data/"
) -> bytes:
    continuation = f"<NextContinuationToken>{escape(token)}</NextContinuationToken>" if token is not None else ""
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Name>com-courtlistener-storage</Name><Prefix>{escape(prefix)}</Prefix>"
        f"<IsTruncated>{truncated}</IsTruncated>{continuation}{entries}</ListBucketResult>"
    ).encode()


def test_page_preserves_revision_markers_and_full_nested_object_keys() -> None:
    key = "bulk-data/randoms/scotus network?#%.csv"
    objects, token = parse_listing_page(_page(_entry(key), truncated="true", token="opaque+token&value"))
    (obj,) = objects
    assert obj.key == key
    assert obj.etag == '"etag-3"'
    assert obj.last_modified == "2026-06-30T04:11:47.000Z"
    assert obj.size == 10
    assert obj.url == "https://storage.courtlistener.com/bulk-data/randoms/scotus%20network%3F%23%25.csv"
    assert obj.transport_version == 's3-listing:"etag-3":10:2026-06-30T04:11:47.000Z'
    assert token == "opaque+token&value"


@pytest.mark.parametrize("key", ["bulk-data/../outside.csv", "bulk-data/x/../y.csv", "bulk-data/./same.csv"])
def test_dot_segments_remain_observed_keys_but_cannot_become_ambiguous_urls(key: str) -> None:
    (obj,), _ = parse_listing_page(_page(_entry(key)))
    assert obj.key == key
    with pytest.raises(ValueError, match="dot path segment"):
        _ = obj.url


@pytest.mark.parametrize(
    ("filename", "dataset", "dump_date", "media_type"),
    [
        ("opinions-2026-06-30.csv.bz2", "opinions", date(2026, 6, 30), "application/x-bzip2"),
        ("schema-2026-06-30.sql", "schema", date(2026, 6, 30), "application/sql"),
        ("load.sh", "load", None, "application/x-sh"),
        ("randoms.zip", "randoms", None, "application/zip"),
        ("scotus_network.csv", "scotus_network", None, "text/csv"),
        ("future.unknown", "future.unknown", None, "application/octet-stream"),
        ("opinions-2026-02-30.csv.bz2", "opinions-2026-02-30", None, "application/x-bzip2"),
        ("opinions2026-06-30.csv.bz2", "opinions2026-06-30", None, "application/x-bzip2"),
        ("opinions-2026-W01-1.csv.bz2", "opinions-2026-W01-1", None, "application/x-bzip2"),
    ],
)
def test_filename_rules_retain_undated_and_unrecognized_exports(filename, dataset, dump_date, media_type) -> None:
    obj = BulkObject(f"bulk-data/{filename}", 0, '"etag"', "2026-06-30T04:11:47Z")
    assert (obj.filename, obj.dataset, obj.dump_date, obj.media_type) == (filename, dataset, dump_date, media_type)


def test_empty_listing_requires_an_explicit_complete_answer() -> None:
    assert parse_listing_page(_page()) == ((), None)
    with pytest.raises(ValueError, match="IsTruncated"):
        parse_listing_page(_page().replace(b"<IsTruncated>false</IsTruncated>", b""))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"<html><body>Please sign in</body></html>", "requested S3 bucket"),
        (_page().replace(b"com-courtlistener-storage", b"another-bucket"), "requested S3 bucket"),
        (_page().replace(b"http://s3.amazonaws.com/doc/2006-03-01/", b"urn:other"), "requested S3 bucket"),
        (_page(prefix="other/"), "requested prefix"),
        (_page(_entry("elsewhere/object.csv")), "escapes the requested prefix"),
        (_page(truncated="perhaps"), "IsTruncated"),
        (_page(truncated="true"), "NextContinuationToken"),
        (_page(truncated="true", token=" "), "NextContinuationToken"),
        (_page(_entry("bulk-data/a.csv") * 2), "repeats object key"),
        (_page(_entry("bulk-data/a.csv")).replace(b"<Size>10</Size>", b"<Size>10</Size><Size>11</Size>"), "Size"),
        (b"<broken XML", "not well-formed XML"),
    ],
)
def test_page_refuses_wrong_scope_ambiguous_metadata_or_unfinished_listing(payload: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_listing_page(payload)


@pytest.mark.parametrize("field", ["Key", "Size", "ETag", "LastModified"])
def test_page_requires_every_object_fact(field: str) -> None:
    payload = _page(_entry("bulk-data/a.csv"))
    start = payload.index(f"<{field}>".encode())
    end = payload.index(f"</{field}>".encode()) + len(field) + 3
    with pytest.raises(ValueError, match=field):
        parse_listing_page(payload[:start] + payload[end:])


@pytest.mark.parametrize("size", ["-1", "+10", "1.5", "ten", " 10"])
def test_page_refuses_invalid_size_instead_of_defaulting_to_zero(size: str) -> None:
    with pytest.raises(ValueError, match="Size"):
        parse_listing_page(_page(_entry("bulk-data/a.csv", size=size)))


@pytest.mark.parametrize("modified", ["not a date", "2026-06-30", "2026-06-30T04:11:47"])
def test_page_refuses_invalid_or_timezone_free_timestamp(modified: str) -> None:
    with pytest.raises(ValueError, match="last-modified stamp"):
        parse_listing_page(_page(_entry("bulk-data/a.csv", modified=modified)))


def test_page_byte_bound_includes_the_whole_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _page()
    monkeypatch.setattr(listing, "MAX_LISTING_PAGE_BYTES", len(payload))
    assert parse_listing_page(payload) == ((), None)
    with pytest.raises(ValueError, match="byte limit"):
        parse_listing_page(payload + b" ")


def _live_pages(monkeypatch: pytest.MonkeyPatch, pages: list[bytes]) -> list[str]:
    calls: list[str] = []
    pending = iter(pages)

    class BoundedResponse(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            assert size == bulk.MAX_LISTING_PAGE_BYTES + 1
            return super().read(size)

    def open_page(url: str):
        calls.append(url)
        return BoundedResponse(next(pending))

    monkeypatch.setattr(bulk, "_open", open_page)
    return calls


def test_live_listing_uses_the_public_parser_and_exact_continuation(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = "bulk-data/randoms/"
    calls = _live_pages(
        monkeypatch,
        [
            _page(_entry(f"{prefix}first.csv"), truncated="true", token="opaque+token&value", prefix=prefix),
            _page(_entry(f"{prefix}second.csv"), prefix=prefix),
        ],
    )
    objects = bulk.list_bulk_dumps(prefix)
    assert [obj.key for obj in objects] == [f"{prefix}first.csv", f"{prefix}second.csv"]
    assert all(obj.etag == '"etag-3"' for obj in objects)
    assert parse_qs(urlsplit(calls[1]).query)["continuation-token"] == ["opaque+token&value"]


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([_page(truncated="true")], "NextContinuationToken"),
        (
            [_page(truncated="true", token="again"), _page(truncated="true", token="again")],
            "repeats a continuation token",
        ),
        (
            [_page(_entry("bulk-data/a.csv"), truncated="true", token="next"), _page(_entry("bulk-data/a.csv"))],
            "across pages",
        ),
        ([b"x" * (bulk.MAX_LISTING_PAGE_BYTES + 2)], "byte limit"),
    ],
)
def test_live_listing_never_returns_a_partial_or_duplicate_population(monkeypatch, pages, message) -> None:
    calls = _live_pages(monkeypatch, pages)
    with pytest.raises(ValueError, match=message):
        bulk.list_bulk_dumps()
    assert len(calls) == len(pages)


def test_live_listing_rejects_an_unrelated_prefix_before_requesting(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _live_pages(monkeypatch, [])
    with pytest.raises(ValueError, match="under bulk-data/"):
        bulk.list_bulk_dumps("other/")
    assert calls == []
