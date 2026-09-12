"""The standalone example retains exactly the bytes that proved both identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from examples.govinfo_body import FIXTURES, run_example
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore


def test_example_retains_mods_body_and_source_facts_without_refetch(tmp_path: Path) -> None:
    result = json.loads(json.dumps(run_example(tmp_path)))
    assert json.loads((tmp_path / "capture.json").read_text()) == result
    assert result["requestCount"] == len(result["requests"]) == 2
    assert result["identity"]["source_document_number"] == "X98-10603"
    assert result["identity"]["access_id"] == result["identity"]["marker_document_number"] == "98-14931"
    assert result["resolution"]["start_page"] == 30359
    store = LocalSourceNativeBlobStore(Path(result["blobStore"]), create=False)
    for item, filename in zip(result["captures"], ("mods.xml", "granule.html"), strict=True):
        original = (FIXTURES / filename).read_bytes()
        with store.open(item["sha256"]) as stream:
            assert stream.read() == original
        assert item["sha256"] == "sha256:" + hashlib.sha256(original).hexdigest()
        assert item["byteSize"] == len(original)
