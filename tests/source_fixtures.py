"""Routine fixture encoding and inspection, shared across source tests.

Adversarial release builders stay in source_native_release_fixtures.py. These
helpers do not generate verifier expectations through the publisher under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from spicy_docs.source_native_store import LocalSourceNativeBlobStore


def federal_response(
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


def payload_rows(root: Path, partition_kind: str) -> list[dict[str, Any]]:
    receipt = json.loads((root / "receipts/publication.json").read_bytes())
    store = LocalSourceNativeBlobStore(root.parent / "blobs")
    rows: list[dict[str, Any]] = []
    for partition in receipt["payloadPartitions"]:
        if partition["partitionKind"] != partition_kind:
            continue
        with store.open(partition["blobRef"]) as stream:
            rows.extend(json.loads(line) for line in stream)
    return rows


def counted_subsets(node: object) -> list[dict[str, Any]]:
    """Every dict carrying a ``count`` key, found anywhere in the report -- used to prove
    the CRITICAL rule: no count is reported without a population string beside it."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "count" in node:
            found.append(cast("dict[str, Any]", node))
        for value in node.values():
            found.extend(counted_subsets(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(counted_subsets(item))
    return found
