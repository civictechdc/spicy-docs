"""GAO product pages remain exact source evidence, not inferred topic tags."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

import spicy_docs.sources.gao.native as gao
from spicy_docs.sources.gao.native import (
    MAX_PAGE_BYTES,
    GaoProductSourceError,
    GaoProductWindow,
    gao_product_query_scope,
    gao_product_records_included,
    iter_gao_product_pages,
    parse_gao_product_page_response,
    validate_record_scope,
)
from spicy_docs.sources.zyte import ZyteHttpResponse

PRODUCT_ID = "gao-26-107693"
PRODUCT_URL = f"https://www.gao.gov/products/{PRODUCT_ID}"


def _html(
    *,
    canonical_url: str = PRODUCT_URL,
    topics: tuple[tuple[str, str], ...] = (("information-security", "Information Security"),),
) -> bytes:
    anchors = "".join(f'<a href="/topics/{slug}" hreflang="en">{label}</a>' for slug, label in topics)
    return (
        "<!doctype html><html><head>"
        f'<link rel="canonical" href="{canonical_url}" />'
        "</head><body>"
        '<div class="views-field views-field-field-topic"><div class="field-content">'
        f"{anchors}</div></div>"
        "</body></html>"
    ).encode()


def _capture(body: bytes | None = None, *, resolved_url: str = PRODUCT_URL) -> ZyteHttpResponse:
    return ZyteHttpResponse(
        requested_url=PRODUCT_URL,
        resolved_url=resolved_url,
        status_code=200,
        content_type="text/html; charset=UTF-8",
        body=body if body is not None else _html(),
    )


def test_exact_html_is_wrapped_deterministically_and_replayed_as_one_source_record() -> None:
    body = _html()
    fetch = lambda _url: _capture(body)
    scope = {"productIds": [PRODUCT_ID]}

    first = list(iter_gao_product_pages(fetch, query_scope=scope))
    second = list(iter_gao_product_pages(fetch, query_scope=scope))

    assert len(first) == 1
    assert first[0].response_bytes == second[0].response_bytes
    assert first[0].evidence_media_type == "application/zip"
    response = parse_gao_product_page_response(first[0].response_bytes)
    assert response["count"] == 1
    assert response["results"] == [
        {
            "canonicalUrl": PRODUCT_URL,
            "contentType": "text/html; charset=UTF-8",
            "htmlByteLength": len(body),
            "htmlSha256": "sha256:" + hashlib.sha256(body).hexdigest(),
            "productId": PRODUCT_ID,
            "publisherTopic": {
                "href": "/topics/information-security",
                "label": "Information Security",
                "slug": "information-security",
            },
            "requestedUrl": PRODUCT_URL,
            "resolvedUrl": PRODUCT_URL,
            "targetStatus": 200,
            "transport": "zyte-raw-http-v1",
        }
    ]


def test_unrelated_publisher_markup_drift_does_not_change_the_closed_source_rule() -> None:
    body = _html().replace(b"<body>", b'<body><div class="node" class="node"></div>')

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(body),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )

    assert parse_gao_product_page_response(page.response_bytes)["results"][0]["publisherTopic"]["slug"] == (
        "information-security"
    )


def test_topic_links_outside_the_publisher_field_remain_evidence_without_becoming_topics() -> None:
    body = (Path(__file__).parent / "fixtures" / "gao-product-page-navigation-topics.html").read_bytes()

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(body),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )

    response = parse_gao_product_page_response(page.response_bytes)
    assert response["count"] == 1
    assert response["results"][0]["publisherTopic"] == {
        "href": "/topics/information-security",
        "label": "Information Security",
        "slug": "information-security",
    }
    with ZipFile(BytesIO(page.response_bytes)) as evidence:
        assert evidence.read("product.html") == body


def test_publisher_topic_is_preserved_without_refspec_membership_filtering() -> None:
    body = _html(topics=(("science-and-technology", "Science and Technology"),))

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(body),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )

    assert parse_gao_product_page_response(page.response_bytes)["results"][0]["publisherTopic"] == {
        "href": "/topics/science-and-technology",
        "label": "Science and Technology",
        "slug": "science-and-technology",
    }


def test_publisher_topic_label_uses_visible_text_not_html_entity_spelling() -> None:
    body = _html(topics=(("research-and-development", "Research &amp; Development"),))

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(body),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )

    assert parse_gao_product_page_response(page.response_bytes)["results"][0]["publisherTopic"] == {
        "href": "/topics/research-and-development",
        "label": "Research & Development",
        "slug": "research-and-development",
    }


def test_publisher_topic_label_ignores_html_formatting_whitespace_at_its_edges() -> None:
    body = _html(topics=(("information-security", "\n  Information Security\t"),))

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(body),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )

    assert parse_gao_product_page_response(page.response_bytes)["results"][0]["publisherTopic"]["label"] == (
        "Information Security"
    )


def test_replay_refuses_html_that_differs_from_its_capture_digest() -> None:
    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )
    with ZipFile(BytesIO(page.response_bytes)) as source:
        manifest = source.read("manifest.json")
        changed_html = source.read("product.html") + b" "
    changed = BytesIO()
    with ZipFile(changed, "w") as archive:
        archive.writestr("manifest.json", manifest)
        archive.writestr("product.html", changed_html)

    with pytest.raises(GaoProductSourceError, match="metadata differs"):
        parse_gao_product_page_response(changed.getvalue())


def test_replay_refuses_zip_metadata_that_differs_from_the_deterministic_shape() -> None:
    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )
    with ZipFile(BytesIO(page.response_bytes)) as source:
        manifest = source.read("manifest.json")
        product = source.read("product.html")
    changed = BytesIO()
    with ZipFile(changed, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        changed_manifest = ZipInfo("manifest.json", date_time=(2026, 9, 1, 0, 0, 0))
        changed_manifest.compress_type = ZIP_DEFLATED
        changed_manifest.external_attr = 0o100644 << 16
        archive.writestr(changed_manifest, manifest)
        archive.writestr("product.html", product)

    with pytest.raises(GaoProductSourceError, match="ZIP member metadata"):
        parse_gao_product_page_response(changed.getvalue())


def test_replay_refuses_zip_version_metadata_that_differs_from_the_deterministic_shape() -> None:
    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )
    with ZipFile(BytesIO(page.response_bytes)) as source:
        manifest = source.read("manifest.json")
        product = source.read("product.html")
    changed = BytesIO()
    with ZipFile(changed, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        changed_manifest = ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        changed_manifest.compress_type = ZIP_DEFLATED
        changed_manifest.external_attr = 0o100644 << 16
        changed_manifest.create_version = 63
        archive.writestr(changed_manifest, manifest)
        product_entry = ZipInfo("product.html", date_time=(1980, 1, 1, 0, 0, 0))
        product_entry.compress_type = ZIP_DEFLATED
        product_entry.external_attr = 0o100644 << 16
        archive.writestr(product_entry, product)

    with pytest.raises(GaoProductSourceError, match="ZIP member metadata"):
        parse_gao_product_page_response(changed.getvalue())


def test_per_page_scope_checks_do_not_rescan_the_complete_product_id_list() -> None:
    class _MembershipTrap(list[str]):
        def __contains__(self, value: object) -> bool:
            raise AssertionError(f"linear membership scan for {value!r}")

    page = next(
        iter_gao_product_pages(
            lambda _url: _capture(),
            query_scope={"productIds": [PRODUCT_ID]},
        )
    )
    response = parse_gao_product_page_response(page.response_bytes)
    window = GaoProductWindow(product_id=PRODUCT_ID)
    scope = {"productIds": _MembershipTrap([PRODUCT_ID])}

    assert gao_product_records_included(response, query_scope=scope, page_window=window)
    validate_record_scope(response["results"][0], query_scope=scope, page_window=window)


def test_gao_profile_imports_without_spicysearch_or_refspec() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import spicy_docs.sources.gao.native; "
                "unexpected=[name for name in sys.modules if name.startswith(('spicysearch', 'refspec'))]; "
                "print(','.join(unexpected)); raise SystemExit(bool(unexpected))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout


@pytest.mark.parametrize(
    "product_ids",
    [
        [],
        [PRODUCT_ID, PRODUCT_ID],
        ["../secret"],
        ["GAO-26-107693"],
        ["gao-26-107693?token=secret"],
    ],
)
def test_query_scope_refuses_missing_duplicate_or_unsafe_product_ids(product_ids: list[str]) -> None:
    with pytest.raises(GaoProductSourceError):
        gao_product_query_scope({"productIds": product_ids})


@pytest.mark.parametrize(
    ("capture", "message"),
    [
        (_capture(resolved_url="https://www.gao.gov/products/other"), "resolved URL"),
        (
            ZyteHttpResponse(PRODUCT_URL, PRODUCT_URL, 403, "text/html", _html()),
            "target status",
        ),
        (
            ZyteHttpResponse(PRODUCT_URL, PRODUCT_URL, 200, "application/pdf", _html()),
            "Content-Type",
        ),
        (_capture(_html(canonical_url="https://www.gao.gov/products/other")), "canonical URL"),
        (_capture(_html(topics=())), "topic anchor"),
        (_capture(_html(topics=(("information-security", "x" * 513),))), "topic label"),
        (
            _capture(
                _html(
                    topics=(
                        ("information-security", "Information Security"),
                        ("health-care", "Health Care"),
                    )
                )
            ),
            "topic anchor",
        ),
    ],
)
def test_acquisition_fails_closed_on_transport_or_publisher_drift(
    capture: ZyteHttpResponse,
    message: str,
) -> None:
    with pytest.raises(GaoProductSourceError, match=message):
        list(iter_gao_product_pages(lambda _url: capture, query_scope={"productIds": [PRODUCT_ID]}))


def test_acquisition_refuses_oversized_html_before_building_evidence() -> None:
    capture = _capture(b"x" * (MAX_PAGE_BYTES + 1))

    with pytest.raises(GaoProductSourceError, match="byte bound"):
        list(iter_gao_product_pages(lambda _url: capture, query_scope={"productIds": [PRODUCT_ID]}))


def test_acquisition_refuses_a_corpus_over_the_total_byte_bound(monkeypatch) -> None:
    product_ids = [PRODUCT_ID, "gao-26-107694"]
    bodies = {
        product_id: _html(canonical_url=f"https://www.gao.gov/products/{product_id}") for product_id in product_ids
    }
    monkeypatch.setattr(gao, "MAX_TOTAL_HTML_BYTES", sum(map(len, bodies.values())) - 1)

    def fetch(url: str) -> ZyteHttpResponse:
        body = bodies[url.rsplit("/", 1)[-1]]
        return ZyteHttpResponse(url, url, 200, "text/html", body)

    with pytest.raises(GaoProductSourceError, match="total HTML byte bound"):
        list(iter_gao_product_pages(fetch, query_scope={"productIds": product_ids}))
