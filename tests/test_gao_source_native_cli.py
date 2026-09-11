"""GAO has a real source-native operator path with no sibling imports."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from examples.offline_release import FIXED_NOW, IMPLEMENTATION_ID, PRODUCT_ID, capture, run_example
from spicy_docs.source_native_cli import main


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
