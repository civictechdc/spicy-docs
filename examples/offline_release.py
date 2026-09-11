"""Publish and independently verify one synthetic GAO page without network access.

Run ``uv run python examples/offline_release.py`` from the repository root.
The printed paths remain available for inspection after the example exits.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rulespec_artifacts import ArtifactPin, LocalMemberSource

from spicy_docs.cli.source_native import main as source_native_main
from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.sources.gao.profile import GAO_PRODUCT_PAGE_PROFILE
from spicy_docs.sources.zyte import ZyteHttpResponse
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
PRODUCT_ID = "gao-26-107693"
PRODUCT_URL = f"https://www.gao.gov/products/{PRODUCT_ID}"
FIXED_NOW = datetime(2026, 9, 1, tzinfo=UTC)
# Synthetic input, shaped like the publisher page. It is not a live capture.
HTML = (
    "<!doctype html><html><head>"
    f'<link rel="canonical" href="{PRODUCT_URL}" />'
    "</head><body>"
    '<div class="views-field views-field-field-topic"><div class="field-content">'
    '<a href="/topics/information-security" hreflang="en">Information Security</a>'
    "</div></div></body></html>"
).encode()


def capture(url: str) -> ZyteHttpResponse:
    """Supply exact local bytes where a live command would make a request."""
    if url != PRODUCT_URL:
        raise ValueError(f"the offline example has no evidence for {url!r}")
    return ZyteHttpResponse(url, url, 200, "text/html; charset=UTF-8", HTML)


def run_example(directory: Path) -> dict[str, object]:
    """Exercise the same publish and verify commands used by operators."""
    release = directory / "gao"
    blobs = directory / "blobs"
    published_output = StringIO()
    errors = StringIO()
    result = source_native_main(
        [
            "publish",
            "--source",
            "gao-product-pages",
            "--product-id",
            PRODUCT_ID,
            "--destination",
            str(release),
            "--blob-store",
            str(blobs),
            "--implementation-id",
            IMPLEMENTATION_ID,
        ],
        fetch_gao=capture,
        clock=lambda: FIXED_NOW,
        stdout=published_output,
        stderr=errors,
    )
    if result != 0:
        raise RuntimeError(errors.getvalue().strip())
    published = json.loads(published_output.getvalue())
    verified_output = StringIO()
    result = source_native_main(
        [
            "verify",
            "--source",
            "gao-product-pages",
            "--release",
            str(release),
            "--blob-store",
            str(blobs),
            "--logical-id",
            published["logicalId"],
            "--artifact-digest",
            published["artifactDigest"],
            "--accepted-verifier-implementation-id",
            IMPLEMENTATION_ID,
        ],
        stdout=verified_output,
        stderr=errors,
    )
    if result != 0:
        raise RuntimeError(errors.getvalue().strip())
    verified = json.loads(verified_output.getvalue())
    reader = SourceNativeReleaseReader(
        LocalMemberSource(release),
        blob_source=LocalSourceNativeBlobStore(blobs, create=False),
        profile=GAO_PRODUCT_PAGE_PROFILE,
        expected_pin=ArtifactPin(verified["logicalId"], verified["artifactDigest"]),
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )
    return {
        "input": "one synthetic GAO page; no live requests",
        "release": str(release),
        "blobStore": str(blobs),
        "publication": published,
        "verification": verified,
        # This fixed example has one record. General consumers should stream it.
        "records": list(reader.iter_records()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="Output parent; gao/ must not already exist")
    args = parser.parse_args()
    directory = args.directory or Path(tempfile.mkdtemp(prefix="spicy-docs-example-"))
    print(json.dumps(run_example(directory), indent=2))


if __name__ == "__main__":
    main()
