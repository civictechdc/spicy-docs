"""Capture and retain synthetic GovInfo evidence without network access.

Run ``uv run python examples/govinfo_body.py`` from the repository root.
The printed directory retains the exact MODS/body bytes and capture facts.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from spicy_docs.sources.federal_register.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.sources.federal_register.body_sources import govinfo_granule_locator, govinfo_mods_locator
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo"


def run_example(directory: Path) -> dict[str, object]:
    responses = {
        govinfo_mods_locator("1998-06-03"): (FIXTURES / "mods.xml").read_bytes(),
        govinfo_granule_locator("98-14931", "1998-06-03"): (FIXTURES / "granule.html").read_bytes(),
    }
    calls: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        body = responses[url]
        media_type = "application/xml" if url.endswith(".xml") else "text/html"
        return httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": media_type})

    budget = GovInfoBodyBudget(
        max_requests=2,
        max_body_bytes=4096,
        max_mods_bytes=4096,
        timeout_seconds=10,
        min_request_interval_seconds=0,
    )
    with GovInfoBodyAcquirer(
        budget=budget,
        transport=httpx.MockTransport(capture),
        clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
    ) as client:
        result = client.acquire(
            document_number="X98-10603",
            publication_date="1998-06-03",
            route="mods-start-page",
            start_page=30359,
        )

    store = LocalSourceNativeBlobStore(directory / "blobs")
    captures = []
    for role, item in (("mods", result.mods), ("body", result.body)):
        assert item is not None
        stored = store.put_blob(item.sha256, item.byte_size, [item.body])
        with store.open(stored.blob_ref) as retained:
            if retained.read() != item.body:
                raise AssertionError("retained bytes differ from the capture")
        captures.append(
            {
                "role": role,
                "requestedUrl": item.requested_url,
                "resolvedUrl": item.resolved_url,
                "statusCode": item.status_code,
                "contentType": item.content_type,
                "observedAt": item.observed_at,
                "sha256": item.sha256,
                "byteSize": item.byte_size,
            }
        )
    report = {
        "input": "synthetic local MODS and granule; no live requests",
        "route": result.route,
        "identity": asdict(result.identity),
        "resolution": asdict(result.mods_resolution) if result.mods_resolution is not None else None,
        "budget": asdict(result.budget),
        "requestCount": result.request_count,
        "requests": calls,
        "blobStore": str((directory / "blobs").resolve()),
        "captures": captures,
    }
    (directory / "capture.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Retain exact bytes and capture facts here")
    args = parser.parse_args()
    directory = args.output or Path(tempfile.mkdtemp(prefix="spicy-docs-govinfo-"))
    print(json.dumps(run_example(directory), indent=2))


if __name__ == "__main__":
    main()
