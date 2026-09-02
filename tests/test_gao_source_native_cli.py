"""GAO has a real source-native operator path with no sibling imports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from spicy_docs.source_native_cli import main
from spicy_docs.sources.zyte import ZyteHttpResponse

IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
PRODUCT_ID = "gao-26-107693"
PRODUCT_URL = f"https://www.gao.gov/products/{PRODUCT_ID}"
FIXED_NOW = datetime(2026, 9, 1, tzinfo=UTC)
HTML = (
    "<!doctype html><html><head>"
    f'<link rel="canonical" href="{PRODUCT_URL}" />'
    "</head><body>"
    '<div class="views-field views-field-field-topic"><div class="field-content">'
    '<a href="/topics/information-security" hreflang="en">Information Security</a>'
    "</div></div></body></html>"
).encode()


def _capture(url: str) -> ZyteHttpResponse:
    assert url == PRODUCT_URL
    return ZyteHttpResponse(url, url, 200, "text/html; charset=UTF-8", HTML)


def _publish_args(destination: Path, *product_ids: str) -> list[str]:
    args = ["publish", "--source", "gao-product-pages"]
    for product_id in product_ids:
        args.extend(["--product-id", product_id])
    return [
        *args,
        "--destination",
        str(destination),
        "--blob-store",
        str(destination.parent / "blobs"),
        "--implementation-id",
        IMPLEMENTATION_ID,
    ]


def test_cli_publishes_and_independently_verifies_gao_product_pages(tmp_path: Path) -> None:
    destination = tmp_path / "gao"
    output = StringIO()

    assert (
        main(
            _publish_args(destination, PRODUCT_ID),
            fetch_gao=_capture,
            clock=lambda: FIXED_NOW,
            stdout=output,
            stderr=StringIO(),
        )
        == 0
    )
    published = json.loads(output.getvalue())
    assert published["source"] == "gao-product-pages"
    assert published["sourceStateScope"] == "complete-snapshot"

    verified_output = StringIO()
    assert (
        main(
            [
                "verify",
                "--source",
                "gao-product-pages",
                "--release",
                str(destination),
                "--blob-store",
                str(tmp_path / "blobs"),
                "--logical-id",
                published["logicalId"],
                "--artifact-digest",
                published["artifactDigest"],
                "--accepted-verifier-implementation-id",
                IMPLEMENTATION_ID,
            ],
            stdout=verified_output,
            stderr=StringIO(),
        )
        == 0
    )
    verified = json.loads(verified_output.getvalue())
    assert verified["sourceStateDigest"] == published["sourceStateDigest"]


def test_cli_refuses_duplicate_product_ids_before_fetching(tmp_path: Path) -> None:
    calls: list[str] = []
    errors = StringIO()

    assert (
        main(
            _publish_args(tmp_path / "gao", PRODUCT_ID, PRODUCT_ID),
            fetch_gao=lambda url: calls.append(url) or _capture(url),
            clock=lambda: FIXED_NOW,
            stdout=StringIO(),
            stderr=errors,
        )
        == 1
    )
    assert calls == []
    failure = json.loads(errors.getvalue())
    assert failure["error"]["code"] == "release-invalid"
    assert "distinct" in failure["error"]["message"]
