"""Retain one explicit GovInfo USLM response (a law, a compilation or an archive) and its evidence.

Run ``uv run --frozen python -m examples.uslm_capture --help`` for routes.
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

from spicy_docs.sources.govinfo.uslm import PublicLawSelection, StatuteCompilationSelection
from spicy_docs.sources.govinfo.uslm_acquisition import UslmAcquirer, UslmAcquisitionBudget, UslmSelection
from spicy_docs.transport.capture import CapturedBodyResponse
from spicy_docs.transport.credentials import scrub_credential


def _utc_now() -> datetime:
    """The default clock: the current UTC time."""
    return datetime.now(UTC)


def _selection_fields(selection: UslmSelection) -> dict | None:
    """A selection as the receipt's plain JSON fields: a dataclass, a congress/kind pair, or None."""
    if isinstance(selection, (PublicLawSelection, StatuteCompilationSelection)):
        return asdict(selection)
    return {"congress": selection[0], "kind": selection[1]} if selection is not None else None


def _acquire(client: UslmAcquirer, route: str, selection: UslmSelection):
    """Dispatch one route and selection to the acquirer method it names, or refuse the pair."""
    if route == "public-law" and isinstance(selection, PublicLawSelection):
        return client.acquire_public_law(selection)
    if route == "statute-compilation" and isinstance(selection, StatuteCompilationSelection):
        return client.acquire_statute_compilation(selection)
    if route == "public-law-archive" and isinstance(selection, tuple):
        return client.acquire_public_law_archive(*selection)
    if route == "statute-compilations-archive" and selection is None:
        return client.acquire_statute_compilations_archive()
    raise ValueError("route and selection must identify one supported USLM request")


def _capture_fields(capture: CapturedBodyResponse) -> dict:
    """One capture's URL, status, media type, time, size and digest, as the receipt records it."""
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


def _failure(error: Exception, output: Path) -> dict:
    """A failed acquisition as receipt fields, writing any refused response body under ``output``."""
    details = {
        "type": type(error).__name__,
        "message": scrub_credential(str(error), ""),
        "acquisition": getattr(error, "uslm_acquisition", None),
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


def _write_receipt(output: Path, receipt: dict) -> None:
    """Write the receipt as ``receipt.json`` in the output directory."""
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_capture(
    output: Path,
    *,
    route: str,
    selection: UslmSelection,
    budget: UslmAcquisitionBudget,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> dict:
    """Call one source route; retain exact bytes or a failure before re-raising."""
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "route": route,
        "selection": _selection_fields(selection),
        "requestedBudget": asdict(budget),
        "producer": {"package": "spicy-docs", "version": version("spicy-docs")},
    }
    try:
        with UslmAcquirer(budget=budget, transport=transport, clock=clock) as client:
            result = _acquire(client, route, selection)
    except Exception as error:
        _write_receipt(output, receipt | {"outcome": "failed", "failure": _failure(error, output)})
        raise
    capture = result.capture
    filename = "response.zip" if route.endswith("archive") else "response.xml"
    (output / filename).write_bytes(capture.body)
    if route.endswith("archive"):
        entries = [
            {
                "name": entry.name,
                "byteSize": entry.byte_size,
                "sha256": entry.sha256,
                "metadata": asdict(entry.metadata),
            }
            for entry in result.archive.entries
        ]
        listing = (json.dumps(entries, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (output / "entries.json").write_bytes(listing)
        source = {
            "archive": {
                "source": result.archive.source,
                "entryCount": len(entries),
                "file": "entries.json",
                "sha256": "sha256:" + hashlib.sha256(listing).hexdigest(),
                "byteSize": len(listing),
            }
        }
    else:
        source = {"metadata": asdict(result.metadata)}
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
    """Parse the route and its selection, run one live capture, and exit 2 on a refused request."""
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", type=Path, required=True, help="new directory for original bytes and receipt")
    common.add_argument("--max-bytes", type=int, required=True, help="explicit response-byte ceiling")
    common.add_argument("--max-requests", type=int, default=2)
    common.add_argument("--timeout-seconds", type=float, default=60)
    common.add_argument("--min-request-interval-seconds", type=float, default=1)
    routes = parser.add_subparsers(dest="route", required=True)
    law = routes.add_parser("public-law", parents=[common], help="request one public or private law's USLM XML")
    law.add_argument("--congress", type=int, required=True)
    law.add_argument("--kind", choices=("public", "private"), default="public")
    law.add_argument("--number", type=int, required=True)
    comp = routes.add_parser("statute-compilation", parents=[common], help="request one statute compilation")
    comp.add_argument("--file-id", type=int, required=True)
    laws = routes.add_parser("public-law-archive", parents=[common], help="request one Congress/kind zip of laws")
    laws.add_argument("--congress", type=int, required=True)
    laws.add_argument("--kind", choices=("public", "private"), default="public")
    routes.add_parser("statute-compilations-archive", parents=[common], help="request the whole compilations zip")
    args = parser.parse_args(argv)
    try:
        selection: UslmSelection = None
        if args.route == "public-law":
            selection = PublicLawSelection(args.congress, args.kind, args.number)
        elif args.route == "statute-compilation":
            selection = StatuteCompilationSelection(args.file_id)
        elif args.route == "public-law-archive":
            selection = (args.congress, args.kind)
        budget = UslmAcquisitionBudget(
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
