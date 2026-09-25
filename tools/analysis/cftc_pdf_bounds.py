"""Measure CFTC comment-letter PDF sizes and prove one full download through the wall.

Command:

    uv run --frozen python -m tools.analysis.cftc_pdf_bounds

Closes the two open items of the CFTC comments source (``docs/sources/cftc-comments.md``):

1. the PDF size distribution: fetch up to six letter PDFs through the shared
   walled-fetch ladder (DIRECT, Zyte ``httpResponseBody``, Firecrawl
   ``rawBase64``), each bounded at 16 MiB and the run's downloaded bytes at
   50 MiB of recorded PDF response bodies, seeded with the handler ids the fixtures declare and topped up
   with up to three current ids harvested from one live listing page read through the production page
   acquirer (``CftcPortalAcquirer(recover_walls=True)``);
2. one full end-to-end download: every clean answer passes the production
   gate -- :meth:`~spicy_docs.sources.cftc_comments.attachments.CftcPdfAcquirer.acquire_pdf`
   with its media-type, ``%PDF-`` magic, trailer, final-URL and byte-cap
   checks -- and complete letter bytes are retained in the campaign blob
   store.

One receipt row per PDF records the locator, its provenance, the outcome,
status, media type, the rung that answered, byte size, sha256, the PDF
version the bytes state and the blob ref; exhausted rungs are listed from
the ladder's own vocabulary. Page fetches that harvest current handler ids
record one row each. The receipt JSONL under the campaign receipts directory
and the content-addressed letter blobs are the only retained artifacts;
every string is scrubbed with ``scrub_record`` before it is written, and
credentials never appear. An existing receipt is refused before any request. Missing ``ZYTE_TOKEN`` or
``FIRECRAWL_API_KEY`` fails fast before any request.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rulespec_artifacts import LocalBlobWriter

from spicy_docs.sources.cftc_comments.acquisition import CftcPortalAcquirer, CftcPortalBudget, CftcPortalRefusedError
from spicy_docs.sources.cftc_comments.attachments import (
    CftcPdfAcquirer,
    CftcPdfError,
    CftcPdfRefusedError,
    CftcPdfUnavailableError,
    PdfBudget,
)
from spicy_docs.sources.cftc_comments.pages import (
    CftcCommentsSourceError,
    comment_list_url,
    pdf_url,
    releases_url,
    view_comment_url,
)
from spicy_docs.sources.firecrawl import require_firecrawl_api_key_from_environment
from spicy_docs.sources.zyte import require_zyte_token_from_environment
from spicy_docs.transport.captured import observed_instant
from spicy_docs.transport.credentials import scrub_record
from spicy_docs.transport.source_acquirer import utc_now

MAX_PDF_FETCHES = 6
PDF_BYTE_CAP = 16 * 1024 * 1024
CUMULATIVE_BYTE_BUDGET = 50 * 1024 * 1024
PAGE_BYTE_CAP = 4 * 1024 * 1024
TIMEOUT_SECONDS = 60.0
MIN_INTERVAL_SECONDS = 1.0
#: One attempt per ladder rung: DIRECT, Zyte, Firecrawl.
MAX_REQUESTS = 3
MAX_HARVEST_FILES = 3
MAX_HARVEST_DETAILS = 3
RECEIPT_NAME = "receipt.jsonl"
RUN_COMMAND = "uv run --frozen python -m tools.analysis.cftc_pdf_bounds"
BLOB_STORE = Path.home() / "Work/corpora/supply-2026-09-02/blobs"
RECEIPT_DIR = Path.home() / "Work/corpora/supply-2026-09-02/receipts/cftc-pdf-bounds-2026-09-24"

#: Handler ids the fixtures declare, with the fixture row that pins each.
SEED_LOCATORS: tuple[tuple[int, str], ...] = (
    (25524, "tests/fixtures/cftc_comments/view-comment-59866.html attachment link (Wayback 20250503203627)"),
    (10, "tests/fixtures/cftc_comments/comment-letter.pdf.head provenance (Wayback 20111015183534)"),
    (10000, "tests/fixtures/cftc_comments/comment-letter.pdf.head second head provenance (Wayback 20160521233024)"),
)


def _rungs(error: Exception) -> list[dict[str, Any]]:
    """The per-rung outcomes an exhausted ladder capture carries, in the ladder's own vocabulary."""
    return [
        {"transport": rung.transport.value, "kind": rung.kind, "detail": rung.detail or ""}
        for rung in getattr(error, "rung_outcomes", ())
    ]


def _page(
    records: list[dict[str, Any]], step: str, url: str, capture: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """One production page capture, recorded whatever its outcome; the parsed page, or ``None`` when refused."""
    row: dict[str, Any] = {"kind": "cftc-pdf-bounds-page", "step": step, "url": url}
    page = None
    try:
        acquisition = capture(*args, **kwargs)
    except CftcPortalRefusedError as error:
        row.update(outcome="exhausted", refusalKind=error.refusal_kind, message=str(error), rungOutcomes=_rungs(error))
    except CftcCommentsSourceError as error:
        found = getattr(error, "capture", None)
        row.update(outcome="refused", status=getattr(found, "status_code", None), message=str(error))
    else:
        captured = acquisition.capture
        row.update(
            outcome="fetched",
            status=captured.status_code,
            contentType=captured.content_type,
            transport=acquisition.transport.value if acquisition.transport else None,
            byteSize=captured.byte_size,
            sha256=captured.sha256,
            requestId=acquisition.request_id,
            requestCount=acquisition.request_count,
        )
        page = acquisition.page
    records.append(row)
    return page


def _harvest(records: list[dict[str, Any]], portal: CftcPortalAcquirer) -> list[tuple[int, str]]:
    """Harvest up to ``MAX_HARVEST_FILES`` current handler ids from one live listing, recording every page outcome.

    Prefers the fixture-declared listing (rule 1647); when it does not serve,
    walks the 2026 releases listing to its first rule's listing. At most
    ``MAX_HARVEST_DETAILS`` detail pages are read.
    """
    listing_url = comment_list_url(1647)
    listing = _page(records, "listing-1647", listing_url, portal.comment_list_page, listing_url)
    if listing is None:
        releases = _page(records, "releases-2026", releases_url(year=2026), portal.releases_page, year=2026)
        if releases is not None and releases.releases:
            listing_url = releases.releases[0].comment_list_url
            listing = _page(records, "listing-rule", listing_url, portal.comment_list_page, listing_url)
    fresh: list[tuple[int, str]] = []
    for row in listing.rows[:MAX_HARVEST_DETAILS] if listing is not None else ():
        if len(fresh) >= MAX_HARVEST_FILES:
            break
        detail = _page(records, "detail", view_comment_url(row.comment_id), portal.view_comment_page, row.comment_id)
        for file in detail.files if detail is not None else ():
            if len(fresh) < MAX_HARVEST_FILES:
                fresh.append((file.file_id, f"live {listing_url} row {row.comment_id} detail -> file {file.file_name}"))
    return fresh


def _retain_blob(body: bytes, digest: str, byte_size: int) -> str:
    """Content-address the letter bytes in the campaign blob store; the receipt names the ref."""
    try:
        written = LocalBlobWriter(BLOB_STORE).put([body], max_bytes=byte_size, expected_digest=digest)
    except (OSError, ValueError) as error:  # the blob store is a convenience, not the measurement
        return f"blob-write-failed: {error}"
    return written.digest


def _pdf_row(
    acquirer: CftcPdfAcquirer,
    file_id: int,
    provenance: str,
    observed_at: str,
    retain: bool,
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """One letter capture through the production gate; every outcome recorded honestly."""
    row: dict[str, Any] = {
        "kind": "cftc-pdf-bounds-row",
        "fileId": file_id,
        "url": pdf_url(file_id),
        "locatorSource": provenance,
        "observedAt": observed_at,
    }
    try:
        acquisition = acquirer.acquire_pdf(file_id, max_bytes=max_bytes)
    except CftcPdfUnavailableError as error:
        capture = error.capture
        row.update(
            {
                "outcome": "unavailable",
                "status": capture.status_code,
                "contentType": capture.content_type,
                "byteSize": capture.byte_size,
                "requestCount": acquirer.request_count,
                "message": str(error),
            }
        )
        return row
    except CftcPdfRefusedError as error:
        refused = getattr(error, "refused_response", None)
        row.update(
            {
                "outcome": "refused",
                "refusalKind": error.refusal_kind,
                "byteSize": getattr(refused, "observed_byte_size", None),
                "requestCount": acquirer.request_count,
                "message": str(error),
                "rungOutcomes": _rungs(error),
            }
        )
        return row
    except CftcPdfError as error:
        capture = getattr(error, "capture", None)
        row.update(
            {
                "outcome": "invalid",
                "status": getattr(capture, "status_code", None),
                "contentType": getattr(capture, "content_type", None),
                "byteSize": getattr(capture, "byte_size", None),
                "requestCount": acquirer.request_count,
                "message": str(error),
            }
        )
        return row
    except (OSError, TypeError, ValueError) as error:
        row.update(
            {
                "outcome": "error",
                "requestCount": acquirer.request_count,
                "message": str(error),
            }
        )
        return row
    capture = acquisition.capture
    blob_ref = None
    blob_error = None
    if retain:
        retained = _retain_blob(capture.body, capture.sha256, capture.byte_size)
        if retained.startswith("blob-write-failed: "):
            blob_error = retained
        else:
            blob_ref = retained
    row.update(
        {
            "outcome": "complete",
            "status": capture.status_code,
            "contentType": capture.content_type,
            "transport": acquisition.transport.value,
            "requestId": acquisition.request_id,
            "byteSize": capture.byte_size,
            "sha256": capture.sha256,
            "pdfVersion": acquisition.pdf_version,
            "blobRef": blob_ref,
            "blobError": blob_error,
            "requestCount": acquisition.request_count,
        }
    )
    return row


def run(receipt_path: Path) -> int:
    """Run the bounded sample, write the scrubbed receipt, and report one line per PDF.

    An existing receipt refuses before any request: retained evidence is never overwritten.
    """
    if receipt_path.exists():
        raise FileExistsError(f"receipt {receipt_path} already exists; pass --receipt NEW_PATH")
    require_zyte_token_from_environment()
    require_firecrawl_api_key_from_environment()
    started_utc = observed_instant(utc_now)
    records: list[dict[str, Any]] = []
    page_budget = CftcPortalBudget(
        max_requests=MAX_REQUESTS,
        max_page_bytes=PAGE_BYTE_CAP,
        timeout_seconds=TIMEOUT_SECONDS,
        min_request_interval_seconds=MIN_INTERVAL_SECONDS,
    )
    with CftcPortalAcquirer(budget=page_budget, recover_walls=True) as portal:
        fresh = _harvest(records, portal)
    locators: list[tuple[int, str]] = list(SEED_LOCATORS)
    locators.extend(
        (file_id, provenance) for file_id, provenance in fresh if file_id not in {seed for seed, _ in locators}
    )
    budget = PdfBudget(
        max_requests=MAX_REQUESTS,
        max_bytes=PDF_BYTE_CAP,
        timeout_seconds=TIMEOUT_SECONDS,
        min_request_interval_seconds=MIN_INTERVAL_SECONDS,
    )
    downloaded = 0
    pdf_rows: list[dict[str, Any]] = []
    with CftcPdfAcquirer(budget=budget) as acquirer:
        for file_id, provenance in locators:
            if len(pdf_rows) >= MAX_PDF_FETCHES:
                break
            if downloaded >= CUMULATIVE_BYTE_BUDGET:
                break
            row = _pdf_row(
                acquirer,
                file_id,
                provenance,
                started_utc,
                retain=True,
                max_bytes=min(PDF_BYTE_CAP, CUMULATIVE_BYTE_BUDGET - downloaded),
            )
            if row.get("byteSize") is not None:
                downloaded += int(row["byteSize"])
            pdf_rows.append(row)
    header = scrub_record(
        {
            "kind": "cftc-pdf-bounds-run",
            "command": RUN_COMMAND,
            "startedUtc": started_utc,
            "limits": {
                "maxPdfFetches": MAX_PDF_FETCHES,
                "pdfByteCap": PDF_BYTE_CAP,
                "cumulativeByteBudget": CUMULATIVE_BYTE_BUDGET,
                "timeoutSeconds": TIMEOUT_SECONDS,
                "minIntervalSeconds": MIN_INTERVAL_SECONDS,
            },
            "seeds": [{"fileId": file_id, "provenance": provenance} for file_id, provenance in SEED_LOCATORS],
            "harvestedFileIds": [file_id for file_id, _ in fresh],
            "downloadedBytes": downloaded,
        }
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("x") as handle:
        handle.write(json.dumps(header, sort_keys=True) + "\n")
        for record in records:
            handle.write(json.dumps(scrub_record(record), sort_keys=True) + "\n")
        for row in pdf_rows:
            handle.write(json.dumps(scrub_record(row), sort_keys=True) + "\n")
    print(f"receipt: {receipt_path}", file=sys.stderr)
    for row in pdf_rows:
        transport = row.get("transport") or "-"
        size = row.get("byteSize")
        print(
            f"file {row['fileId']}: {row['outcome']} status={row.get('status')} "
            f"bytes={size} transport={transport} version={row.get('pdfVersion')}"
        )
    return 0


def _default_receipt_path() -> Path:
    return RECEIPT_DIR / RECEIPT_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure CFTC letter PDF sizes through the walled-fetch ladder.")
    parser.add_argument("--receipt", type=Path, default=_default_receipt_path(), help="receipt JSONL path")
    args = parser.parse_args(argv)
    try:
        return run(args.receipt)
    except FileExistsError as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
