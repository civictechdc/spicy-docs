"""FEC metadata/body separation, source paging and bounded acquisition.

Pins embedded-body pointer escaping and tampering refusals, offset and keyset
paging with repeated filters and repeated-cursor refusal, listing/sitemap/HTML
shape parsing without implicit asset fetches, asset streaming and digest reuse,
credential scrubbing, redirect host revalidation, and CLI completion markers.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from rulespec_artifacts import BlobIntegrityError, BlobLimitError

from spicy_docs.cli.fec import main
from spicy_docs.reading.s3_listing import NAMESPACE
from spicy_docs.sources.fec.assets import choose_rendition, embedded_text
from spicy_docs.sources.fec.catalog import API_ROOT, BUCKET, BUCKET_URL, api_operations, official_sources, official_url
from spicy_docs.sources.fec.client import FecClient, api_page
from spicy_docs.sources.fec.metadata import parse_api, parse_page_links, parse_sitemap, split_record
from spicy_docs.sources.zyte import ZyteHttpResponse
from spicy_docs.transport import download
from spicy_docs.transport.download import AcquisitionError, BoundedAcquirer, HttpRefusal, RateLimitExhausted


@pytest.fixture
def clock(monkeypatch):
    """A fake monotonic clock that sleeping advances: no test really waits."""
    state = SimpleNamespace(now=1000.0, slept=[])

    def sleep(seconds):
        state.slept.append(seconds)
        state.now += seconds

    monkeypatch.setattr(download.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(download.time, "sleep", sleep)
    return state


@pytest.fixture
def client(tmp_path, clock):
    """An FEC client over a mock transport and blob store, paced on the fake clock."""

    def make(handler, **options):
        return FecClient(
            store=tmp_path,
            api_key="test-credential-123",
            min_interval=0,
            transport=httpx.MockTransport(handler),
            **options,
        )

    return make


def page(rows, *, number=1, pages=1, exact=True):
    """An FEC page payload over the given results."""
    return {"results": rows, "pagination": {"page": number, "pages": pages, "is_count_exact": exact}}


def listing(*keys, token=None, prefix="bulk-downloads/"):
    """An XML listing payload over the given keys."""
    entries = "".join(
        f'<Contents><Key>{key}</Key><Size>3</Size><ETag>"e"</ETag><LastModified>2026-09-11T00:00:00Z</LastModified></Contents>'
        for key in keys
    )
    continuation = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return f'<ListBucketResult xmlns="{NAMESPACE}"><Name>{BUCKET}</Name><Prefix>{prefix}</Prefix><IsTruncated>{str(bool(token)).lower()}</IsTruncated>{continuation}{entries}</ListBucketResult>'.encode()


def test_metadata_preserves_decimals_links_and_exact_embedded_text_without_body_requests(client, tmp_path):
    """Metadata keeps decimals, links and exact embedded text without extra body requests, with the key in headers
    only.
    """
    payload = b'{"results":[{"amount":0.1000,"id":"01","documents":[{"url":"https://www.fec.gov/a.pdf","text":"Exact\\nbody"}]}],"pagination":{"page":1,"pages":1,"is_count_exact":true}}'
    calls = []

    def serve(request):
        calls.append(request)
        assert request.headers["X-Api-Key"] == "test-credential-123"
        assert "api_key" not in str(request.url)
        return httpx.Response(200, content=payload)

    with client(serve) as c:
        (result,) = c.api("/v1/committees/")
    assert len(calls) == 1
    (record,) = result["records"]
    assert record["metadata"]["amount"] == Decimal("0.1000")
    assert record["metadata"]["documents"] == [{"url": "https://www.fec.gov/a.pdf"}]
    (body,) = record["embedded_bodies"]
    assert body["source_pointer"] == "/results/0/documents/0/text"
    assert (
        embedded_text(store=tmp_path, sha256=result["evidence"]["sha256"], source_pointer=body["source_pointer"])
        == "Exact\nbody"
    )
    assert (tmp_path / result["evidence"]["blob_path"]).read_bytes() == payload
    assert record["assets"][0]["url"].endswith("a.pdf")
    assert split_record({"summary": "A title", "amount": 1})["embedded_bodies"] == []


def test_embedded_pointer_escapes_and_tampering(client, tmp_path):
    """Embedded pointers use JSON-pointer escaping and tampered pointers are refused."""
    with client(lambda _: httpx.Response(200, json=page([{"a/b~c": {"text": "source"}}]))) as c:
        (result,) = c.api("/v1/committees/")
    body = result["records"][0]["embedded_bodies"][0]
    assert body["source_pointer"] == "/results/0/a~1b~0c/text"
    assert (
        embedded_text(store=tmp_path, sha256=result["evidence"]["sha256"], source_pointer=body["source_pointer"])
        == "source"
    )
    (tmp_path / result["evidence"]["blob_path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        embedded_text(store=tmp_path, sha256=result["evidence"]["sha256"], source_pointer=body["source_pointer"])


def test_offset_paging_keeps_repeated_filters(client):
    """Offset paging keeps repeated filter values and ends when next is absent."""
    calls = []

    def serve(request):
        calls.append(request)
        n = int(request.url.params.get("page", 1))
        assert request.url.params.get_list("cycle") == ["2022", "2024"]
        return httpx.Response(200, json=page([{"page": n}], number=n, pages=2))

    with client(serve) as c:
        result = list(c.api("/v1/committees/", params={"cycle": [2022, 2024]}))
    assert len(calls) == len(result) == 2
    assert result[-1]["next_url"] is None


def test_estimated_count_is_not_a_terminal_boundary(client):
    """An estimated count does not terminate the walk; three pages are read."""
    calls = []

    def serve(request):
        n = int(request.url.params.get("page", 1))
        calls.append(n)
        return httpx.Response(200, json=page([n] if n < 3 else [], number=n, pages=1, exact=False))

    with client(serve) as c:
        assert len(list(c.api("/v1/committees/"))) == 3
    assert calls == [1, 2, 3]


def test_keyset_carries_all_cursor_fields_and_preserves_source_filters(client):
    """Keyset paging carries every cursor field and preserves source filters."""
    calls = []

    def serve(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"sub_id": "123"}],
                    "pagination": {
                        "last_indexes": {
                            "last_index": "123",
                            "last_contribution_receipt_amount": "1.20",
                            "sort_null_only": True,
                        },
                        "is_count_exact": False,
                    },
                },
            )
        assert request.url.params["sort_null_only"] == "true"
        assert request.url.params["last_contribution_receipt_amount"] == "1.20"
        assert request.url.params["two_year_transaction_period"] == "2024"
        return httpx.Response(200, json={"results": [], "pagination": {"last_indexes": {}}})

    with client(serve) as c:
        assert len(list(c.api("/v1/schedules/schedule_a/", params={"two_year_transaction_period": 2024}))) == 2


def test_repeated_keyset_refuses_instead_of_looping(client):
    """A repeated keyset cursor refuses instead of looping."""
    with client(
        lambda _: httpx.Response(200, json={"results": [1], "pagination": {"last_indexes": {"last_index": "same"}}})
    ) as c:
        with pytest.raises(AcquisitionError, match="repeated"):
            list(c.api("/v1/schedules/schedule_a/"))
        assert c.http.request_count == 2


@pytest.mark.parametrize("group", ["murs", "advisory_opinions", "admin_fines", "adrs", "statutes", "rulemakings"])
def test_legal_search_offsets(group, client):
    """Legal search walks offset pages and records source pointers per group."""
    calls = []

    def serve(request):
        offset = int(request.url.params.get("from_hit", 0))
        calls.append(offset)
        return httpx.Response(200, json={group: [{"no": str(offset)}], "total_" + group: 2})

    with client(serve) as c:
        path = "/v1/rulemaking/search/" if group == "rulemakings" else "/v1/legal/search/"
        results = list(c.api(path, params={"hits_returned": 1}))
    assert calls == [0, 1]
    assert results[-1]["records"][0]["source_pointer"] == f"/{group}/0"


def test_detail_reference_and_asset_operation_modes(client):
    """Detail, reference and asset operation modes select their own sources and refuse CSV/ICS."""
    with client(
        lambda _: httpx.Response(
            200, json={"docs": [{"no": 1, "documents": [{"text": "exact", "url": "https://www.fec.gov/a.pdf"}]}]}
        )
    ) as c:
        (result,) = c.api("/v1/legal/docs/murs/1")
        assert result["records"][0]["embedded_bodies"][0]["source_pointer"] == "/docs/0/documents/0/text"
    with client(lambda _: httpx.Response(200, json={"results": [{"name": "Example"}]})) as c:
        assert len(list(c.api("/v1/names/candidates/", params={"q": "Example"}))) == 1
    with (
        client(lambda _: pytest.fail("non-JSON operation should not request JSON")) as c,
        pytest.raises(ValueError, match="CSV/ICS"),
    ):
        list(c.api("/v1/calendar-dates/export/"))


@pytest.mark.parametrize(
    ("value", "mode"),
    [
        ({"message": "Unexpected failure"}, "page"),
        ({"results": [], "pagination": {"page": 1, "pages": 2, "is_count_exact": True}}, "page"),
        ({"results": [1], "pagination": {"page": 2, "pages": 2}}, "page"),
        ({"results": [1], "pagination": {"last_indexes": {}}}, "keyset"),
        ({"results": [1], "pagination": {"last_indexes": {"api_key": "bad"}}}, "keyset"),
        ({"murs": [], "total_murs": 1}, "legal"),
        ({"murs": [1], "total_murs": 2}, "legal"),
        ({"docs": "missing list"}, "docs"),
        ({"message": "Unexpected failure"}, ["count", "receipts"]),
    ],
)
def test_success_shape_must_be_present(value, mode):
    """A success without its expected shape is refused."""
    with pytest.raises(ValueError):
        api_page(value, url=API_ROOT + "/v1/legal/search/", mode=mode)


@pytest.mark.parametrize(
    "payload", [b"<html>challenge</html>", b'{"results":[],"results":[1]}', b'{"x":NaN}', b'{"error":"unavailable"}']
)
def test_json_refusals_retain_exact_evidence(payload, client):
    """JSON refusals retain the exact response bytes."""
    with client(lambda _: httpx.Response(200, content=payload)) as c, pytest.raises(ValueError) as refused:
        list(c.api("/v1/committees/"))
    assert refused.value.refused_response.response_bytes == payload


def test_xml_listing_and_sitemaps_never_fetch_assets(client):
    """XML listings and sitemaps never fetch assets and carry checksum metadata."""
    calls = []

    def serve(request):
        calls.append(str(request.url))
        if request.url.host == "www.fec.gov":
            return httpx.Response(
                200,
                content=b"<urlset><url><loc>https://www.fec.gov/a.xml</loc><lastmod>2026-09-11</lastmod></url></urlset>",
            )
        token = request.url.params.get("continuation-token")
        return httpx.Response(
            200,
            content=listing(
                "bulk-downloads/b.zip" if token else "bulk-downloads/a.zip", token=None if token else "opaque+token"
            ),
        )

    with client(serve) as c:
        pages = list(c.objects("bulk-downloads/"))
        (sitemap,) = c.sitemap("https://www.fec.gov/sitemap.xml")
    assert len(calls) == 3
    assert parse_qs(calls[1].split("?", 1)[1])["continuation-token"] == ["opaque+token"]
    assert pages[0]["records"][0]["metadata"]["size"] == 3
    assert pages[0]["records"][0]["embedded_bodies"] == []
    assert sitemap["records"][0]["metadata"]["fields"][0]["text"].endswith("a.xml")
    assert sitemap["records"][0]["source_pointer"] is None


def test_listing_retains_optional_checksum_and_storage_fields(client, tmp_path):
    """Listings retain optional checksum and storage fields, absent ones as empty or None."""
    payload = listing("bulk-downloads/a.zip", "bulk-downloads/b.zip").replace(
        b"</Contents>",
        b"<ChecksumAlgorithm>CRC64NVME</ChecksumAlgorithm><ChecksumAlgorithm>SHA256</ChecksumAlgorithm>"
        b"<ChecksumType>FULL_OBJECT</ChecksumType><StorageClass>STANDARD</StorageClass></Contents>",
        1,
    )
    with client(lambda _: httpx.Response(200, content=payload)) as c:
        (result,) = c.objects("bulk-downloads/")
    first, second = [row["metadata"] for row in result["records"]]
    assert first["checksum_algorithms"] == ["CRC64NVME", "SHA256"]
    assert first["checksum_type"] == "FULL_OBJECT"
    assert first["storage_class"] == "STANDARD"
    assert second["checksum_algorithms"] == []
    assert second["checksum_type"] is None and second["storage_class"] is None
    assert (tmp_path / result["evidence"]["blob_path"]).read_bytes() == payload
    assert c.http.request_count == 1


def test_sitemap_locations_distinguish_repeated_urls(client):
    """Sitemap locations distinguish repeated URLs, with no source pointer."""
    payload = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://www.fec.gov/a.xml</loc><lastmod>2025-01-01</lastmod></url>"
        b"<url><loc>https://www.fec.gov/a.xml</loc><lastmod>2026-01-01</lastmod></url></urlset>"
    )
    with client(lambda _: httpx.Response(200, content=payload)) as c:
        (result,) = c.sitemap("https://www.fec.gov/sitemap.xml")
    assert [row["metadata"]["source_location"] for row in result["records"]] == [
        {"child_index": 0},
        {"child_index": 1},
    ]
    assert all(row["source_pointer"] is None for row in result["records"])


def test_html_link_locations_use_decoded_source_tag_positions(client):
    """HTML link locations use decoded source tag positions."""
    payload = (
        "<title>FEC</title>\n"
        'é<a href="/same.xml">First</a><a href="mailto:ignored">Mail</a>\r\n'
        '  <a href="/same.xml">Second</a>\n'
        '<link rel="alternate" href="/feed.xml" title="Feed">'
    ).encode()
    with client(lambda _: httpx.Response(200, content=payload)) as c:
        result = c.page_links("https://www.fec.gov/reports/")
    links = result["records"][0]["metadata"]["links"]
    assert [link["source_location"] for link in links] == [
        {"line": 2, "column": 1},
        {"line": 3, "column": 2},
        {"line": 4, "column": 0},
    ]
    assert [link["label"] for link in links] == ["First", "Second", "Feed"]
    assert links[0]["url"] == links[1]["url"]
    assert result["records"][0]["source_pointer"] is None


def test_filing_html_navigation_remains_metadata_without_implicit_body_selection():
    """Filing HTML navigation stays metadata with no implicit body selection."""
    value = {"html_url": "https://docquery.fec.gov/cgi-bin/forms/C00000001/123/", "fec_url": "/123.fec"}
    record = split_record(value, source_pointer="/results/0")
    assert record["metadata"] == value
    assert [asset["url"] for asset in record["assets"]] == ["https://www.fec.gov/123.fec"]
    assert record["embedded_bodies"] == []


def test_sitemap_index_duplicates_are_bounded_and_finite(client):
    """Sitemap index duplicates are bounded and finite."""

    def serve(request):
        if request.url.path == "/index.xml":
            return httpx.Response(
                200,
                content=b"<sitemapindex><sitemap><loc>https://www.fec.gov/leaf.xml</loc></sitemap><sitemap><loc>https://www.fec.gov/leaf.xml</loc></sitemap></sitemapindex>",
            )
        return httpx.Response(200, content=b"<urlset/>")

    with client(serve) as c:
        assert len(list(c.sitemap("https://www.fec.gov/index.xml", max_pages=2))) == 2
        assert c.http.request_count == 2


@pytest.mark.parametrize(
    "payload",
    [
        listing("bulk-downloads/a.zip").replace(BUCKET.encode(), b"wrong"),
        listing("elsewhere/a.zip"),
        listing("bulk-downloads/../a.zip"),
        listing("bulk-downloads/a.zip", "bulk-downloads/a.zip"),
        b"<html/>",
    ],
)
def test_wrong_or_ambiguous_listing_is_refused(payload, client):
    """A wrong or ambiguous listing is refused."""
    with client(lambda _: httpx.Response(200, content=payload)) as c, pytest.raises(ValueError):
        list(c.objects("bulk-downloads/"))


def test_page_and_request_bounds_cannot_report_completion(client):
    """Page and request bounds stop without reporting completion."""
    with client(lambda _: httpx.Response(200, json=page([1], pages=2))) as c:
        it = c.api("/v1/committees/", max_pages=1)
        assert next(it)["next_url"]
        with pytest.raises(AcquisitionError, match="page bound"):
            next(it)
    with (
        client(lambda _: httpx.Response(200, json=page([1], pages=2)), max_requests=1) as c,
        pytest.raises(AcquisitionError, match="request budget"),
    ):
        list(c.api("/v1/committees/"))


def _quota_pages(clock, responses, starts, pages=4):
    """Serve ``responses`` (status, headers) in order as a paged walk, noting each request's start."""
    served = iter(responses)

    def serve(request):
        starts.append(clock.now)
        status, headers = next(served)
        n = int(request.url.params.get("page", 1))
        body = {"json": page([n], number=n, pages=pages)} if status == 200 else {}
        return httpx.Response(status, headers=headers, **body)

    return serve


def test_openfec_paces_to_its_stated_quota_and_only_on_the_api_host(client, clock):
    """API starts space window/limit with headroom once stated, 3.6 s before; S3 keeps the caller's pace."""
    starts = []
    responses = [(200, {}), (200, {"X-RateLimit-Limit": "60"}), (200, {"X-RateLimit-Limit": "120"}), (200, {})]
    with client(_quota_pages(clock, [*responses, (200, {})], starts, pages=5)) as c:
        assert len(list(c.api("/v1/committees/"))) == 5
    gaps = [round(b - a, 3) for a, b in pairwise(starts)]
    # Unstated: the documented 1,000/hour; then 60/min and 120/min; a later
    # response without the header keeps the last stated limit.
    assert gaps == [3.6, 1.1, 0.55, 0.55]
    listing_starts = []

    def serve_listing(_request):
        listing_starts.append(clock.now)
        n = len(listing_starts)
        return httpx.Response(200, content=listing(f"bulk-downloads/{n}", token=f"t{n}"))

    with client(serve_listing) as c:
        rows = c.objects("bulk-downloads/", max_pages=2)
        next(rows), next(rows)
    assert listing_starts[1] == listing_starts[0]


def test_openfec_429_waits_its_retry_after_then_succeeds(client, clock, capsys):
    """A 429 waits its Retry-After instead of three quick retries, then the walk completes."""
    starts = []
    responses = [
        (200, {"X-RateLimit-Limit": "60"}),
        (429, {"Retry-After": "37", "X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "0"}),
        (200, {"X-RateLimit-Limit": "60"}),
        (200, {"X-RateLimit-Limit": "60"}),
        (200, {"X-RateLimit-Limit": "60"}),
    ]
    with client(_quota_pages(clock, responses, starts)) as c:
        assert [row["records"][0]["metadata"] for row in c.api("/v1/committees/")] == [1, 2, 3, 4]
        assert c.http.rate_limit_waited == 37
    assert round(starts[2] - starts[1], 3) == 37
    err = capsys.readouterr().err
    assert "waiting 37s (Retry-After; 37s of 600s)" in err
    assert "test-credential-123" not in err


@pytest.mark.parametrize(
    ("headers", "options", "requests", "match"),
    [
        # Each 61 s wait is honored until the next would pass the 600 s budget.
        ({"Retry-After": "61"}, {}, 10, "600s budget"),
        # Without Retry-After a 429 waits one 60 s window.
        ({}, {}, 11, "600s budget"),
        # An hour-long ask means a larger quota is spent: stop at once.
        ({"Retry-After": "3600"}, {}, 1, "beyond the 120s bound"),
        ({"Retry-After": "61"}, {"deadline": 1000.0 + 100}, 2, "deadline"),
    ],
)
def test_openfec_429_past_its_bounds_stops_truthfully(client, clock, capsys, headers, options, requests, match):
    """Repeated 429s end in RateLimitExhausted once a wait would pass the budget, bound or deadline."""
    starts = []
    with (
        client(_quota_pages(clock, [(429, headers)] * requests, starts), **options) as c,
        pytest.raises(RateLimitExhausted, match=match) as refused,
    ):
        list(c.api("/v1/committees/"))
    assert len(starts) == requests
    assert "HTTP 429" in str(refused.value)
    assert "test-credential-123" not in str(refused.value) + capsys.readouterr().err


def test_deadline_stops_before_a_new_request(client, clock):
    """No request starts after the acquirer's deadline."""
    with client(_quota_pages(clock, [(200, {"X-RateLimit-Limit": "60"})] * 4, []), deadline=1000.5) as c:
        walk = c.api("/v1/committees/")
        next(walk)
        with pytest.raises(AcquisitionError, match="deadline"):
            next(walk)


def test_acquirer_without_a_quota_keeps_429_a_quick_transient_retry(clock, monkeypatch):
    """Other BoundedAcquirer callers keep three jittered attempts on HTTP 429."""
    monkeypatch.setattr("spicy_docs.transport.retry.random.uniform", lambda _low, high: high)
    calls = []

    def serve(_request):
        calls.append(clock.now)
        return httpx.Response(429, headers={"Retry-After": "600"})

    with (
        BoundedAcquirer(validate_url=lambda url: url, min_interval=0, transport=httpx.MockTransport(serve)) as http,
        pytest.raises(AcquisitionError, match="retryable HTTP 429"),
    ):
        http.capture("https://example.test/", max_bytes=10)
    assert len(calls) == 3
    assert clock.slept == [2, 4]


def test_html_index_keeps_labels_and_prefers_only_declared_equivalent_renditions():
    """An HTML index keeps labels and prefers only declared equivalent renditions, refusing ambiguity."""
    payload = b'<html><title>Reports | FEC</title><a href="/report.xml">XML</a><a href="/report.pdf">PDF</a><svg><title>Lock</title></svg></html>'
    result = parse_page_links(payload, url="https://www.fec.gov/reports/")
    assert result["title"] == "Reports | FEC"
    assert choose_rendition(result["links"])["url"] == "https://www.fec.gov/report.xml"
    for suffix, mime in [("json", "application/json"), ("xhtml", "application/xhtml+xml")]:
        assert choose_rendition([{"url": "https://www.fec.gov/r.html"}, {"url": f"https://www.fec.gov/r.{suffix}"}])[
            "url"
        ].endswith(suffix)
    with pytest.raises(ValueError):
        parse_page_links(b"<title>Verify you are human | FEC</title>", url="https://www.fec.gov/")
    with pytest.raises(ValueError):
        parse_sitemap(b"<html/>")


def test_asset_streaming_bound_and_known_digest_reuse_cost_zero_requests(client, tmp_path):
    """Asset streaming is bounded and keyless, and a known digest reuses storage at zero requests."""
    data = b"PK\x03\x04" + b"x" * (128 * 1024)
    calls = []

    def serve(request):
        calls.append(request)
        assert "X-Api-Key" not in request.headers
        return httpx.Response(200, content=data, headers={"content-type": "application/zip", "etag": '"e"'})

    with client(serve) as c:
        result = c.download(
            BUCKET_URL + "bulk-downloads/example.zip", max_bytes=len(data), expected_size=len(data), etag='"e"'
        )
        reused = c.download(
            BUCKET_URL + "bulk-downloads/example.zip",
            max_bytes=len(data),
            expected_size=len(data),
            expected_sha256=result["sha256"],
        )
    assert len(calls) == 1
    assert reused["reused"] and not reused["downloaded"]
    assert (tmp_path / result["blob_path"]).read_bytes() == data
    assert result["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()
    with client(serve) as c, pytest.raises(BlobLimitError):
        c.download(BUCKET_URL + "bulk-downloads/example.zip", max_bytes=len(data) - 1)


@pytest.mark.parametrize(
    ("headers", "body", "options", "error"),
    [
        ({"content-type": "text/html"}, b"<html>challenge</html>", {}, AcquisitionError),
        ({"content-type": "application/pdf"}, b"<!DOCTYPE html><html/>", {}, AcquisitionError),
        ({"content-type": "application/xhtml+xml"}, b"<html/>", {}, AcquisitionError),
        ({"content-length": "500"}, b"123", {}, AcquisitionError),
        ({"etag": '"new"'}, b"123", {"etag": '"old"'}, AcquisitionError),
        ({}, b"", {}, AcquisitionError),
        ({}, b"123", {"expected_size": 4}, BlobIntegrityError),
        ({}, b"123", {"expected_sha256": "sha256:" + "0" * 64}, BlobIntegrityError),
    ],
)
def test_invalid_assets_are_not_committed(client, tmp_path, headers, body, options, error):
    """Invalid assets are not committed to the store."""
    with client(lambda _: httpx.Response(200, content=body, headers=headers)) as c, pytest.raises(error):
        c.download("https://www.fec.gov/example", max_bytes=500, **options)
    assert not list((tmp_path / "sha256").glob("*"))


@pytest.mark.parametrize(
    ("kind", "body", "options"),
    [
        (
            "application/xhtml+xml",
            b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>Source</body></html>',
            {},
        ),
        ("text/html", b"<html><title>FEC</title></html>", {"allow_html": True}),
        ("application/xml", b"<report/>", {}),
    ],
)
def test_explicit_native_and_html_assets_remain_distinct(client, kind, body, options):
    """Explicit native and HTML assets remain distinct."""
    with client(lambda _: httpx.Response(200, content=body, headers={"content-type": kind})) as c:
        result = c.download("https://www.fec.gov/document", max_bytes=1024, **options)
    assert result["bytes"] == len(body)


def test_redirect_revalidates_host_and_drops_api_credential(client):
    """A redirect revalidates the host and drops the API credential."""
    calls = []

    def serve(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": "https://www.fec.gov/export.csv"})
        assert "X-Api-Key" not in request.headers
        return httpx.Response(200, content=b"col\nvalue\n")

    with client(serve) as c:
        c.download(API_ROOT + "/v1/calendar-dates/export/?renderer=csv", max_bytes=1024)
    assert len(calls) == 2
    with client(lambda _: httpx.Response(302, headers={"location": "https://unapproved.example/a"})) as c:
        with pytest.raises(ValueError):
            c.download("https://www.fec.gov/a.csv", max_bytes=1024)
        assert c.http.request_count == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://www.fec.gov/a",
        "https://fec.gov.evil.test/a",
        "https://user:pass@www.fec.gov/a",
        "https://www.fec.gov/a?api_key=secret",
        "https://www.fec.gov/%2e%2e/a",
        "https://www.fec.gov/a#fragment",
        "https://www.fec.gov/a\nb",
    ],
)
def test_official_url_refuses_ambiguous_or_credentialed_locators(url):
    """An ambiguous or credentialed official URL is refused."""
    with pytest.raises(ValueError):
        official_url(url)


def test_public_403_can_use_explicit_zyte_but_api_auth_refusal_stops(client):
    """A public 403 may use explicit Zyte while an API auth refusal stops."""

    class Zyte:
        calls = 0

        def fetch(self, url, **kwargs):
            self.calls += 1
            assert kwargs["max_bytes"] <= 32 * 1024**2
            return ZyteHttpResponse(url, url, 200, "application/xml", listing())

    zyte = Zyte()
    with client(lambda _: httpx.Response(403), zyte_on_denial=zyte) as c:
        (result,) = c.objects("bulk-downloads/")
        assert result["via"] == "zyte_after_http_403"
        assert c.http.request_count == 2
        with pytest.raises(HttpRefusal):
            list(c.api("/v1/committees/"))
    assert zyte.calls == 1
    with client(lambda _: httpx.Response(403)) as c, pytest.raises(HttpRefusal):
        list(c.objects("bulk-downloads/"))


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("operation", ["metadata", "original"])
def test_zyte_target_auth_refusal_stops_the_selected_operation(client, status, operation):
    """A Zyte target auth refusal stops the selected operation after one proxy call."""

    class Zyte:
        calls = 0

        def fetch(self, url, **kwargs):
            self.calls += 1
            return ZyteHttpResponse(url, url, status, "text/html", b"<html>Refused</html>")

    zyte = Zyte()
    with client(lambda _: httpx.Response(403), zyte_on_denial=zyte) as c:
        with pytest.raises(HttpRefusal) as refusal:
            if operation == "metadata":
                list(c.objects("bulk-downloads/"))
            else:
                c.download("https://www.fec.gov/example.pdf", max_bytes=1024)
        assert refusal.value.status == status
        assert c.http.request_count == 2
    assert zyte.calls == 1


def test_echoed_api_key_is_never_retained(client, tmp_path):
    """An echoed API key is never retained or committed."""
    with (
        client(lambda _: httpx.Response(200, json=page([{"text": "test-credential-123"}]))) as c,
        pytest.raises(RuntimeError, match="echoed"),
    ):
        list(c.api("/v1/committees/"))
    assert not list((tmp_path / "sha256").glob("*"))


def test_cli_partial_failure_has_no_complete_marker_and_preserves_prior_output(monkeypatch, tmp_path):
    """A CLI partial failure writes no complete marker and preserves prior output."""

    def partial(self, *args, **kwargs):
        yield {"records": [{"metadata": {"amount": Decimal("1.20")}}], "next_url": "next"}
        raise ValueError("source refused api_key=hidden and test-credential-123")

    monkeypatch.setenv("FEC_API_KEY", "test-credential-123")
    monkeypatch.setattr(FecClient, "api", partial)
    output = tmp_path / "out.jsonl"
    args = ["--store", str(tmp_path / "blobs"), "--output", str(output), "api", "/v1/committees/"]
    assert main(args) == 1
    raw = output.read_text()
    rows = [json.loads(x) for x in raw.splitlines()]
    assert [x["kind"] for x in rows] == ["started", "page", "failed"]
    assert rows[1]["records"][0]["metadata"]["amount"] == "1.20"
    assert "test-credential" not in raw and "hidden" not in raw
    assert main(args) == 1
    assert output.read_text() == raw


def test_official_registry_routes_are_executable_not_external_research():
    """Official registry routes are executable, and every declared operation exists."""
    families = official_sources()
    ids = {x["id"] for x in families}
    assert {"fec_receipts", "fec_legal", "fec_ao", "fec_enforcement", "fec_agency_reports", "fec_oig"} <= ids
    declared = set()
    for family in families:
        assert family.get("indexes") or family.get("api")
        for operation in family.get("api", []):
            assert operation["path"] in api_operations()
            declared.add(operation["path"])
        for index in family.get("indexes", []):
            if "url" in index:
                official_url(index["url"])
    assert declared == set(api_operations())


def test_retained_official_response_shapes_and_legal_metadata_null_control():
    """Retained official response shapes parse, with legal metadata's null control left unset."""
    root = Path(__file__).parent / "fixtures/fec"
    for record in json.loads((root / "sources.json").read_text()):
        raw = (root / record["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        parsed = parse_api(raw)
        rows, _, _ = api_page(parsed, url=API_ROOT + record["path"], mode=record["mode"])
        assert rows
        if record["mode"] == "docs":
            result = split_record(rows[0][1], source_pointer=rows[0][0])
            assert result["metadata"]["subject"][0]["text"] == "enforcement"
            assert result["embedded_bodies"] == []
            assert result["assets"][0]["url"] == "https://www.fec.gov/files/legal/murs/206.pdf"
            assert result["metadata"]["documents"][0]["url"] == "/files/legal/murs/206.pdf"


def test_asset_retry_discards_interrupted_bytes_and_bounds_chunk_size(client, monkeypatch, tmp_path):
    """An asset retry discards interrupted bytes, bounds chunk size and commits one blob."""
    from spicy_docs.transport.download import LocalBlobWriter

    # No timing claim: assert stream chunk size and retry request count instead.
    monkeypatch.setattr("spicy_docs.transport.retry.time.sleep", lambda _: None)
    attempts = []
    sizes = []
    original = LocalBlobWriter.put

    def observing_put(self, chunks, **kwargs):
        def observe():
            for chunk in chunks:
                sizes.append(len(chunk))
                yield chunk

        return original(self, observe(), **kwargs)

    monkeypatch.setattr(LocalBlobWriter, "put", observing_put)

    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial" * 20000
            raise httpx.ReadError("httpx contains api_key=must-not-be-logged")

    def serve(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(200, stream=Broken())
        return httpx.Response(200, content=b"complete" * 20000)

    with client(serve) as c:
        result = c.download("https://www.fec.gov/selected.txt", max_bytes=200000)
    assert len(attempts) == 2
    assert max(sizes) == 65536
    assert (tmp_path / result["blob_path"]).read_bytes() == b"complete" * 20000
    assert len(list((tmp_path / "sha256").glob("*"))) == 1


def test_metadata_byte_bound_and_native_asset_signature(client, monkeypatch):
    """Metadata byte bounds and native asset signatures are enforced."""
    monkeypatch.setattr("spicy_docs.sources.fec.client.MAX_METADATA_BYTES", 3)
    with client(lambda _: httpx.Response(200, content=b"1234")) as c, pytest.raises(ValueError, match="byte bound"):
        list(c.api("/v1/committees/"))
    with (
        client(lambda _: httpx.Response(200, content=b'{"error":"no PDF"}')) as c,
        pytest.raises(ValueError, match="original format"),
    ):
        c.download("https://www.fec.gov/document.pdf", max_bytes=100)


def test_cli_success_is_only_after_exhaustion(monkeypatch, tmp_path):
    """The CLI reports success only after exhaustion."""
    monkeypatch.setattr(FecClient, "objects", lambda *a, **kw: iter([{"records": [], "next_url": None}]))
    output = tmp_path / "complete.jsonl"
    assert main(["--store", str(tmp_path / "blobs"), "--output", str(output), "objects", "legal/"]) == 0
    rows = [json.loads(x) for x in output.read_text().splitlines()]
    assert [x["kind"] for x in rows] == ["started", "page", "complete"]
