"""Retain synthetic Federal Register XML, or demonstrate XML-to-HTML fallback.

Run ``uv run --frozen python examples/federal_register_body.py`` offline.
Add ``--case html-fallback`` to retain an XML 404 and the MODS/HTML responses.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from spicy_docs.sources.federal_register.body_acquisition import FederalRegisterBodyAcquirer, FederalRegisterBodyBudget
from spicy_docs.sources.federal_register.body_sources import govinfo_granule_locator, govinfo_mods_locator
from spicy_docs.sources.federal_register.body_xml import publisher_xml_locator
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

FIXTURES = Path(__file__).parent / "fixtures"
XML_MISSING = b"XML unavailable for this synthetic example."


def run_example(directory: Path, *, case: str = "xml") -> dict[str, object]:
    """Run one acquisition against mocked responses and retain the captures under ``directory``."""
    if case not in ("xml", "html-fallback"):
        raise ValueError("case must be xml or html-fallback")
    fallback = case == "html-fallback"
    document_number = "X98-10603" if fallback else "2026-00001"
    publication_date = "1998-06-03" if fallback else "2026-09-11"
    responses = {
        publisher_xml_locator(document_number, publication_date): (
            (404, XML_MISSING) if fallback else (200, (FIXTURES / "federal-register" / "document.xml").read_bytes())
        ),
        govinfo_mods_locator("1998-06-03"): (200, (FIXTURES / "govinfo" / "mods.xml").read_bytes()),
        govinfo_granule_locator("98-14931", "1998-06-03"): (200, (FIXTURES / "govinfo" / "granule.html").read_bytes()),
    }
    calls: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        status, body = responses[url]
        media_type = "application/xml" if url.endswith(".xml") else "text/html"
        return httpx.Response(status, stream=httpx.ByteStream(body), headers={"content-type": media_type})

    budget = FederalRegisterBodyBudget(
        max_requests=3,
        max_body_bytes=4096,
        max_mods_bytes=4096,
        timeout_seconds=10,
        min_request_interval_seconds=0,
    )
    with FederalRegisterBodyAcquirer(
        budget=budget,
        transport=httpx.MockTransport(capture),
        clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
    ) as client:
        result = client.acquire(
            document_number=document_number,
            publication_date=publication_date,
            html_route="mods-start-page" if fallback else "granule",
            start_page=30359 if fallback else None,
        )

    store = LocalSourceNativeBlobStore(directory / "blobs")
    captures = []
    for role, item in (("unavailable-xml", result.unavailable_xml), ("mods", result.mods), ("body", result.body)):
        if item is None:
            continue
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
        "input": "synthetic local responses; no live requests",
        "case": case,
        "requestedFormat": result.requested_format,
        "format": result.format,
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
    """Run the selected example case, writing captures to ``--output`` or a temp directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Retain exact bytes and capture facts here")
    parser.add_argument("--case", choices=("xml", "html-fallback"), default="xml")
    args = parser.parse_args()
    directory = args.output or Path(tempfile.mkdtemp(prefix="spicy-docs-fr-body-"))
    print(json.dumps(run_example(directory, case=args.case), indent=2))


if __name__ == "__main__":
    main()
