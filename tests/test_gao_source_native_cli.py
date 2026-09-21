"""GAO has a real source-native operator path with no sibling imports.

Pins CLI publication and independent verification of product pages, and refusal
of duplicate product ids before any fetch.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from examples.offline_release import FIXED_NOW, IMPLEMENTATION_ID, PRODUCT_ID, capture, run_example
from spicy_docs.cli.source_native import main


def _publish_args(destination: Path, *product_ids: str) -> list[str]:
    """The CLI arguments publishing the fixture product page."""
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
    """The CLI publishes and independently verifies GAO product pages, with matching state digests."""
    result = run_example(tmp_path)
    published = result["publication"]
    verified = result["verification"]
    assert published["source"] == "gao-product-pages"
    assert published["sourceStateScope"] == "complete-snapshot"
    assert verified["sourceStateDigest"] == published["sourceStateDigest"]
    (row,) = result["records"]
    assert row["sourceRecordId"] == PRODUCT_ID
    assert row["record"]["publisherTopic"] == {
        "href": "/topics/information-security",
        "label": "Information Security",
        "slug": "information-security",
    }


def test_cli_refuses_duplicate_product_ids_before_fetching(tmp_path: Path) -> None:
    """The CLI refuses duplicate product ids before fetching, as a release-invalid failure."""
    calls: list[str] = []
    errors = StringIO()

    assert (
        main(
            _publish_args(tmp_path / "gao", PRODUCT_ID, PRODUCT_ID),
            fetch_gao=lambda url: calls.append(url) or capture(url),
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
