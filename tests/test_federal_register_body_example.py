"""The offline example keeps exact XML and every response used for fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from examples.federal_register_body import FIXTURES, XML_MISSING, run_example
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore


@pytest.mark.parametrize("case", ["xml", "html-fallback"])
def test_example_retains_selected_body_and_fallback_evidence(tmp_path: Path, case: str) -> None:
    """The example retains the selected body and every response used for fallback, with identity, route, counts,
    digests and sizes.
    """
    result = json.loads(json.dumps(run_example(tmp_path, case=case)))
    assert json.loads((tmp_path / "capture.json").read_text()) == result
    assert result["requestedFormat"] == "prefer-xml"
    if case == "xml":
        expected = [("body", (FIXTURES / "federal-register" / "document.xml").read_bytes(), 200)]
        assert result["format"] == "xml" and result["route"] == "publisher-xml"
        assert result["identity"]["source_document_number"] == "2026-00001"
        assert result["identity"]["publication_date"] == "2026-09-11"
        assert result["resolution"] is None
    else:
        expected = [
            ("unavailable-xml", XML_MISSING, 404),
            ("mods", (FIXTURES / "govinfo" / "mods.xml").read_bytes(), 200),
            ("body", (FIXTURES / "govinfo" / "granule.html").read_bytes(), 200),
        ]
        assert result["format"] == "html" and result["route"] == "mods-start-page"
        assert result["identity"]["source_document_number"] == "X98-10603"
        assert result["identity"]["access_id"] == result["identity"]["marker_document_number"] == "98-14931"
        assert result["resolution"]["start_page"] == 30359
    assert result["requestCount"] == len(result["requests"]) == len(expected)
    store = LocalSourceNativeBlobStore(Path(result["blobStore"]), create=False)
    for item, (role, original, status) in zip(result["captures"], expected, strict=True):
        assert item["role"] == role and item["statusCode"] == status
        with store.open(item["sha256"]) as stream:
            assert stream.read() == original
        assert item["sha256"] == "sha256:" + hashlib.sha256(original).hexdigest()
        assert item["byteSize"] == len(original)
