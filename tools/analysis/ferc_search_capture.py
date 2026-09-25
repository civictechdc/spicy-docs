"""Retain one bounded FERC search and its live vocabulary; replay completion offline.

Each run uses a fresh output directory. Interrupted or refused runs keep their
responses but never claim completion; retry the full query in a new directory.
This diagnostic captures metadata, not file originals or a published release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.reading.refusals import retain_refused_response
from spicy_docs.sources.ferc.elibrary import FercElibraryReader, search_hit_reference
from spicy_docs.sources.ferc.vocabulary import CLASS_TYPE_PAIRS, FERC_CLASS_TYPE_PDF_SHA256, FERC_CLASS_TYPE_PDF_URL
from spicy_docs.storage.publication import write_bytes_once
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture
from spicy_docs.transport.credentials import failure_reason
from spicy_docs.transport.source_acquirer import check_request_count


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _retain(output: Path, label: str, capture: CapturedBodyResponse) -> dict[str, Any]:
    body_path = f"{label}.body"
    write_bytes_once(output / body_path, capture.body)
    record = {
        "body_path": body_path,
        "sha256": capture.sha256,
        "byte_size": capture.byte_size,
        "requested_url": capture.requested_url,
        "resolved_url": capture.resolved_url,
        "status_code": capture.status_code,
        "content_type": capture.content_type,
        "content_encoding": capture.content_encoding,
        "observed_at": capture.observed_at,
        "method": capture.method,
        "request_body_path": None,
        "request_body_sha256": None,
    }
    if capture.request_body is not None:
        record["request_body_path"] = f"{label}.request"
        record["request_body_sha256"] = _digest(capture.request_body)
        write_bytes_once(output / record["request_body_path"], capture.request_body)
    # Flush each receipt as it arrives, even if the process never reaches its summary.
    write_bytes_once(output / f"{label}.json", _json_bytes(record))
    return record


def _walk(
    reader: FercElibraryReader,
    body: Mapping[str, Any],
    max_pages: int,
    retain: Callable[[str, CapturedBodyResponse], None],
    report: dict[str, Any],
) -> None:
    vocabulary = reader.class_types()
    retain("class-types", vocabulary.capture)
    live_pairs = {(row["Class"], row["Type"]) for row in vocabulary.records}
    pdf_pairs = set(CLASS_TYPE_PAIRS)
    report["vocabulary"] = {
        "outcome": "observed" if vocabulary.records else "requested-empty",
        "row_count": len(vocabulary.records),
        "pair_count": len(live_pairs),
        "pdf_url": FERC_CLASS_TYPE_PDF_URL,
        "pdf_sha256": FERC_CLASS_TYPE_PDF_SHA256,
        "pdf_pair_count": len(pdf_pairs),
        "api_only_pairs": sorted(live_pairs - pdf_pairs),
        "pdf_only_pairs": sorted(pdf_pairs - live_pairs),
    }
    references: set[str] = set()
    report.update(page_count=0, observed_count=0, distinct_reference_count=0, declared_count=None)
    for page in reader.search_pages(body, max_pages=max_pages):
        retain(f"page-{page.page_index + 1:04d}", page.capture)
        references.update(search_hit_reference(row) for row in page.records)
        report.update(
            page_count=report["page_count"] + 1,
            observed_count=report["observed_count"] + len(page.records),
            distinct_reference_count=len(references),
            declared_count=page.declared_count,
        )
    # This runs only after the generator's terminal count check, including its
    # final empty page when a result fills the preceding page exactly.
    report["outcome"] = "complete" if references else "requested-empty"


def capture_search(
    reader: FercElibraryReader, body: Mapping[str, Any], output: Path, *, max_pages: int = 100
) -> dict[str, Any]:
    """Persist successful and refused captures, marking complete only after the full walk."""
    check_request_count(max_pages, "max_pages")
    output.mkdir(parents=True, exist_ok=False)
    request = _json_bytes(dict(body))
    write_bytes_once(output / "request.json", request)
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "outcome": "incomplete",
        "request_sha256": _digest(request),
        "max_pages": max_pages,
        "captures": [],
    }

    def retain(label: str, capture: CapturedBodyResponse) -> None:
        report["captures"].append(_retain(output, label, capture))

    try:
        _walk(reader, body, max_pages, retain, report)
    except BaseException as error:
        report["error"] = failure_reason(error)
        if capture := attached_capture(error):
            report["refused_capture"] = _retain(output, "refused", capture)
        elif isinstance(error, Exception):
            report["refusal"] = retain_refused_response(
                error, store=output / "refused-blobs", max_bytes=reader.budget.max_page_bytes
            )
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        # The reader's request counter resets per operation; this counts the
        # retained responses, not hidden retry attempts or a client lifetime.
        report["retained_response_count"] = (
            len(report["captures"]) + ("refused_capture" in report) + bool((report.get("refusal") or {}).get("sha256"))
        )
        write_bytes_once(output / "summary.json", _json_bytes(report))
    return report


def _verified_bytes(output: Path, name: str, digest: str) -> bytes:
    if Path(name).name != name:
        raise ValueError("capture member must be a filename")
    payload = (output / name).read_bytes()
    if _digest(payload) != digest:
        raise ValueError(f"capture digest mismatch: {name}")
    return payload


def replay_search(output: Path) -> dict[str, Any]:
    """Recompute one completed walk from verified bytes, enforcing every actual request."""
    import httpx

    recorded = json.loads((output / "summary.json").read_bytes())
    if recorded["outcome"] not in {"complete", "requested-empty"}:
        raise ValueError("capture is incomplete; retry the query into a fresh directory")
    if recorded.get("retained_response_count") != len(recorded["captures"]):
        raise ValueError("capture retained-response count differs from its responses")
    body = json.loads(_verified_bytes(output, "request.json", recorded["request_sha256"]))
    captures = iter(recorded["captures"])
    consumed = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal consumed
        record = next(captures, None)
        if record is None:
            raise ValueError("capture ends before the requested walk")
        payload = _verified_bytes(output, record["body_path"], record["sha256"])
        if len(payload) != record["byte_size"]:
            raise ValueError("capture byte size mismatch")
        request_body = (
            _verified_bytes(output, record["request_body_path"], record["request_body_sha256"])
            if record["request_body_path"] is not None
            else b""
        )
        if (
            request.method != record["method"]
            or str(request.url) != record["requested_url"]
            or record["resolved_url"] != record["requested_url"]
            or request.read() != request_body
        ):
            raise ValueError("capture request differs from the replayed query or continuation")
        consumed += 1
        return httpx.Response(
            record["status_code"],
            headers={"content-type": record["content_type"] or "application/octet-stream"},
            stream=httpx.ByteStream(payload),
        )

    replayed: dict[str, Any] = {}
    # Bound each replayed page by the largest retained response, whatever budget captured it.
    largest = max((record["byte_size"] for record in recorded["captures"]), default=1)
    budget = PagedJsonBudget(len(recorded["captures"]) + 1, max(largest, 1), 60, 0)
    with FercElibraryReader(budget=budget, transport=httpx.MockTransport(respond)) as reader:
        _walk(reader, body, recorded["max_pages"], lambda *_: None, replayed)
    if consumed != len(recorded["captures"]):
        raise ValueError("capture has responses beyond the terminal page")
    # JSON round-tripping makes the pair tuples comparable to their stored arrays.
    replayed = json.loads(_json_bytes(replayed))
    if any(recorded.get(key) != value for key, value in replayed.items()):
        raise ValueError("capture summary differs from the retained responses")
    return replayed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", type=Path, help="AdvancedSearch JSON body to capture")
    mode.add_argument("--replay", type=Path, help="verify a retained run offline")
    parser.add_argument("--out", type=Path, help="fresh directory for a live capture")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--min-request-interval-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    if args.request and args.out is None:
        parser.error("--request requires --out")
    if args.replay and args.out is not None:
        parser.error("--out is only for a live capture")
    try:
        if args.replay:
            report = replay_search(args.replay)
        else:
            body = json.loads(args.request.read_bytes())
            if not isinstance(body, dict):
                raise ValueError("search request must be a JSON object")
            # PagedJsonBudget bounds each capture's attempts, while max_pages
            # bounds the traversal. Do not grant a whole walk's retry budget
            # anew on every page.
            budget = PagedJsonBudget(3, 4 * 1024**2, args.timeout_seconds, args.min_request_interval_seconds)
            with FercElibraryReader(budget=budget) as reader:
                report = capture_search(reader, body, args.out, max_pages=args.max_pages)
        print(json.dumps({key: report[key] for key in ("outcome", "page_count", "declared_count", "observed_count")}))
    except (OSError, KeyError, ValueError, RuntimeError) as error:
        print(failure_reason(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
