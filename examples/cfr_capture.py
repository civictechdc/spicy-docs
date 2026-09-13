"""Retain one explicit CFR/eCFR source response and its acquisition evidence.

Run ``uv run --frozen python -m examples.cfr_capture --help`` for routes.
Requests are live unless a caller injects a fixture transport into run_capture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx

from spicy_docs.sources.cfr.acquisition import CfrAcquirer, CfrAcquisitionBudget
from spicy_docs.sources.cfr.models import AnnualCfrSelection, EcfrSelection
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.credentials import scrub_credential

Selection = EcfrSelection | AnnualCfrSelection | int | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _selection_fields(selection: Selection) -> dict | None:
    if isinstance(selection, (EcfrSelection, AnnualCfrSelection)):
        return asdict(selection)
    return {"title": selection} if selection is not None else None


def _acquire(client: CfrAcquirer, route: str, selection: Selection):
    if route == "ecfr-titles" and selection is None:
        return client.acquire_ecfr_titles()
    if route == "ecfr" and isinstance(selection, EcfrSelection):
        return client.acquire_ecfr(selection)
    if route == "annual" and isinstance(selection, AnnualCfrSelection):
        return client.acquire_annual(selection)
    if route == "annual-edition" and isinstance(selection, AnnualCfrSelection):
        return client.acquire_annual_edition(selection)
    if route == "ecfr-bulk" and type(selection) is int:
        return client.acquire_ecfr_bulk(selection)
    raise ValueError("route and selection must identify one supported CFR/eCFR request")


def _failure(error: Exception, output: Path) -> dict:
    details = {
        "type": type(error).__name__,
        "message": scrub_credential(str(error), ""),
        "acquisition": getattr(error, "cfr_acquisition", None),
    }
    refused = getattr(error, "refused_response", None)
    if refused is not None:
        details["response"] = {
            "requestKey": refused.request_key,
            "stage": refused.stage,
            "mediaType": refused.media_type,
            "unavailableReason": refused.unavailable_reason,
            "observedByteSize": refused.observed_byte_size,
        }
        if refused.response_bytes is not None:
            (output / "refused-response.body").write_bytes(refused.response_bytes)
            details["response"].update(
                {
                    "file": "refused-response.body",
                    "sha256": "sha256:" + hashlib.sha256(refused.response_bytes).hexdigest(),
                    "byteSize": len(refused.response_bytes),
                }
            )
    capture = getattr(error, "capture", None)
    if isinstance(capture, CapturedBodyResponse):
        details["capture"] = _capture_fields(capture)
    return details


def _capture_fields(capture: CapturedBodyResponse) -> dict:
    return {
        "requestedUrl": capture.requested_url,
        "resolvedUrl": capture.resolved_url,
        "statusCode": capture.status_code,
        "contentType": capture.content_type,
        "contentEncoding": capture.content_encoding,
        "observedAt": capture.observed_at,
        "byteSize": capture.byte_size,
        "sha256": capture.sha256,
    }


def _write_receipt(output: Path, receipt: dict) -> None:
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_capture(
    output: Path,
    *,
    route: str,
    selection: Selection,
    budget: CfrAcquisitionBudget,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> dict:
    """Call one source API; retain exact bytes or a failure before re-raising."""
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "route": route,
        "selection": _selection_fields(selection),
        "requestedBudget": asdict(budget),
        "producer": {"package": "spicy-docs", "version": version("spicy-docs")},
    }
    try:
        with CfrAcquirer(budget=budget, transport=transport, clock=clock) as client:
            result = _acquire(client, route, selection)
    except Exception as error:
        _write_receipt(output, receipt | {"outcome": "failed", "failure": _failure(error, output)})
        raise
    capture = result.capture
    filename = "response.json" if route == "ecfr-titles" else "response.xml"
    if capture.content_encoding == "gzip":
        filename += ".gz"
    (output / filename).write_bytes(capture.body)
    if route not in ("ecfr-titles", "annual-edition"):
        if capture.content_encoding == "gzip":
            (output / "response.xml").write_bytes(result.xml)
        receipt["xml"] = {
            "file": "response.xml",
            "byteSize": len(result.xml),
            "sha256": "sha256:" + hashlib.sha256(result.xml).hexdigest(),
            "transformation": "gzip-decode" if capture.content_encoding == "gzip" else "identity",
        }
    if route == "ecfr-titles":
        source = {
            "titles": {
                "date": result.titles.date,
                "import_in_progress": result.titles.import_in_progress,
                "title_count": len(result.titles.titles),
            }
        }
    elif route == "annual-edition":
        metadata = (json.dumps(asdict(result.metadata), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (output / "metadata.json").write_bytes(metadata)
        source = {
            "edition": {**asdict(result.edition), "edition_type": result.edition.edition_type.value},
            "metadata": {
                "file": "metadata.json",
                "sha256": "sha256:" + hashlib.sha256(metadata).hexdigest(),
                "byteSize": len(metadata),
                "constituentCount": len(result.metadata.constituents),
                "elementCount": result.metadata.element_count,
                "inputCaptureSha256": capture.sha256,
            },
        }
    else:
        source = {"identity": asdict(result.identity)}
    receipt.update(
        {
            "outcome": "captured",
            "requestCount": result.request_count,
            "budget": asdict(result.budget),
            "capture": {"file": filename, **_capture_fields(capture)},
            "source": source,
        }
    )
    _write_receipt(output, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", type=Path, required=True, help="new directory for original bytes and receipt")
    common.add_argument("--max-bytes", type=int, required=True, help="explicit response-byte ceiling")
    common.add_argument("--max-requests", type=int, default=2)
    common.add_argument("--timeout-seconds", type=float, default=20)
    common.add_argument("--min-request-interval-seconds", type=float, default=1)
    routes = parser.add_subparsers(dest="route", required=True)
    routes.add_parser("ecfr-titles", parents=[common], help="observe the current eCFR JSON title index")
    ecfr = routes.add_parser("ecfr", parents=[common], help="request explicitly dated eCFR API XML")
    ecfr.add_argument("--title", type=int, required=True)
    ecfr.add_argument("--date", required=True)
    ecfr.add_argument("--part")
    ecfr.add_argument("--section")
    annual = routes.add_parser("annual", parents=[common], help="request an annual CFR volume or section XML")
    annual.add_argument("--year", type=int, required=True)
    annual.add_argument("--title", type=int, required=True)
    annual.add_argument("--volume", type=int, required=True)
    annual.add_argument("--section")
    edition = routes.add_parser("annual-edition", parents=[common], help="request annual CFR edition MODS metadata")
    edition.add_argument("--year", type=int, required=True)
    edition.add_argument("--title", type=int, required=True)
    edition.add_argument("--volume", type=int, required=True)
    bulk = routes.add_parser("ecfr-bulk", parents=[common], help="observe undated bulk eCFR title XML")
    bulk.add_argument("--title", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        selection: Selection = None
        if args.route == "ecfr":
            selection = EcfrSelection(title=args.title, date=args.date, part=args.part, section=args.section)
        elif args.route in ("annual", "annual-edition"):
            selection = AnnualCfrSelection(
                year=args.year,
                title=args.title,
                volume=args.volume,
                section=args.section if args.route == "annual" else None,
            )
        elif args.route == "ecfr-bulk":
            selection = args.title
        budget = CfrAcquisitionBudget(
            max_requests=args.max_requests,
            max_bytes=args.max_bytes,
            timeout_seconds=args.timeout_seconds,
            min_request_interval_seconds=args.min_request_interval_seconds,
        )
        report = run_capture(args.output, route=args.route, selection=selection, budget=budget)
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as error:
        parser.exit(2, scrub_credential(str(error), "") + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
