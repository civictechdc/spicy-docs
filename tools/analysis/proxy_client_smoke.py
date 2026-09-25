"""Probe each publisher target once through one proxy provider (Zyte or Firecrawl) and record the answers.

Command:

    uv run --frozen python -m tools.analysis.proxy_client_smoke --provider zyte
    uv run --frozen python -m tools.analysis.proxy_client_smoke --provider firecrawl

Each target in :data:`TARGETS` is fetched once in the provider's publisher-bytes mode: Zyte
``httpResponseBody`` or Firecrawl ``rawBase64`` (PDF parsing disabled). The targets are the walled
publishers and one unwalled docs.fcc.gov control. When the target itself answers 403 or 429, it gets
one more fetch in the provider's fallback mode: Zyte ``browserHtml``, a rendering, or Firecrawl
``rawHtml``. At most :data:`MAX_RETRIES` fallbacks run per run.

One receipt row per target records the requested and resolved URLs, status, media type, byte length,
mode, an 80-character body prefix, and whether the bytes look like the wall page or the real
publisher page. The wall markers come from the shared vocabulary in
``spicy_docs.sources.walled_fetch.detect_wall``. The report names the marker it found and quotes
nothing else from the body.

The receipt JSONL is the only retained artifact. It lives in a campaign receipts directory named for
the provider and the run's UTC date. The receipt is opened exclusively before any request, so a rerun
can never overwrite retained evidence; pass ``--receipt`` to choose a new path. Every string field is
scrubbed with ``scrub_record`` before it is written or printed, and the body prefix is scrubbed
before it is cut. A missing provider credential fails fast with the provider client's own error, and
the harness exits 2 before any request.

This harness replaces the separate ``zyte_client_smoke`` and ``firecrawl_client_smoke`` modules. Their
2026-09-24 receipts (``zyte-client-smoke-2026-09-24`` and ``firecrawl-client-smoke-2026-09-24``) name
those modules in their ``command`` field. The receipt ``kind`` is unchanged. The header's retry limit
is now ``max_retries`` for both providers. Zyte runs also probe the docs.fcc.gov control, which only
the Firecrawl harness used to probe.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from spicy_docs.sources.fcc_ecfs_attachments import OLE2_MAGIC, ZIP_MAGIC
from spicy_docs.sources.firecrawl import RAW_BASE64, RAW_HTML, FirecrawlFetcher, FirecrawlTransportError
from spicy_docs.sources.walled_fetch import detect_wall
from spicy_docs.sources.zyte import BROWSER_HTML, HTTP_RESPONSE_BODY, ZyteHttpFetcher, ZyteTransportError
from spicy_docs.transport.credentials import scrub_record

MAX_BYTES: int = 1024 * 1024
TIMEOUT_SECONDS: float = 60.0
PREFIX_CHARS: int = 80
#: Only a target's own 403/429 answer earns the one fallback fetch; a
#: provider-side failure names no target status, so it is recorded and moved on.
RETRY_STATUSES: frozenset[int] = frozenset({403, 429})
MAX_RETRIES: int = 2
RECEIPT_NAME = "receipt.jsonl"
RECEIPTS_ROOT = Path.home() / "Work/corpora/supply-2026-09-02/receipts"
RUN_COMMAND = "uv run --frozen python -m tools.analysis.proxy_client_smoke --provider {provider}"


class _Response(Protocol):
    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes
    mode: str
    request_id: str | None


class _Fetcher(Protocol):
    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int, mode: str) -> _Response: ...


@dataclass(frozen=True, slots=True)
class Provider:
    """One proxy client: its publisher-bytes mode, its 403/429 fallback mode and its own error type."""

    name: str
    body_mode: str
    retry_mode: str
    fetcher_type: type
    transport_error: type[ValueError]
    #: The fetcher attribute holding the credential, scrubbed from every receipt string.
    credential_attribute: str


PROVIDERS: dict[str, Provider] = {
    "zyte": Provider("zyte", HTTP_RESPONSE_BODY, BROWSER_HTML, ZyteHttpFetcher, ZyteTransportError, "token"),
    "firecrawl": Provider("firecrawl", RAW_BASE64, RAW_HTML, FirecrawlFetcher, FirecrawlTransportError, "key"),
}


@dataclass(frozen=True, slots=True)
class Target:
    """One route and what its real answer is known to look like."""

    name: str
    url: str
    documented_wall: str
    real_markers: tuple[bytes, ...]


TARGETS: tuple[Target, ...] = (
    Target(
        "fcc-ecfs-attachment",
        "https://www.fcc.gov/ecfs/document/26110074740/1",
        "Akamai Access Denied page (Server: AkamaiGHost); direct GETs answered 403 on 2026-09-24",
        # The real answer is a document file, so the magic signatures that
        # fcc_ecfs_attachments gates on are the publisher-page telltales.
        (b"%PDF-", ZIP_MAGIC, OLE2_MAGIC),
    ),
    Target(
        "cftc-comments",
        "https://comments.cftc.gov/",
        "Cloudflare 'Attention Required!' block page; direct clients answered 403 on 2026-09-24",
        # Real portal pages are ASP.NET WebForms; the retained fixtures carry
        # the ctl00 repeater ids the challenge page never has.
        (b"ctl00_ctl00", b"__VIEWSTATE", b"aspNetHidden"),
    ),
    Target(
        "usitc-edis",
        "https://edis.usitc.gov/data/investigation?pageNumber=1",
        "Akamai Access Denied to curl and httpx alike on 2026-09-24",
        (b"<results><investigations>", b"<investigationNumber>", b"<?xml"),
    ),
    Target(
        "ferc-ecomment",
        "https://www.ferc.gov/ferc-online/ecomment",
        "bot wall on www.ferc.gov; 403 to a scripted browser-profiled GET on 2026-09-24",
        # ferc.gov is Drupal; its theme and files paths are artifacts a block
        # page echoing the URL never carries.
        (b"/themes/custom/", b"/sites/default/files"),
    ),
    Target(
        "docs-fcc-gov-pdf",
        "https://docs.fcc.gov/public/attachments/DA-26-1030A1.pdf",
        "no wall measured: direct curl answered 200 application/pdf on 2026-09-24",
        (b"%PDF-",),
    ),
)


@dataclass(frozen=True, slots=True)
class BodyVerdict:
    """What the retained body looks like, with the named marker that decided it."""

    classification: str
    marker: str | None


def classify_body(body: bytes, target: Target) -> BodyVerdict:
    """Whether the body is a wall page or the real publisher page, naming the marker found.

    Wall markers come from the shared vocabulary in
    ``spicy_docs.sources.walled_fetch.detect_wall`` and are checked first: a
    block page can echo the requested URL, so no URL-derived substring is ever
    a real-page marker. A body in neither shape reads ``unrecognized`` rather
    than being guessed at; a rendered DOM (Zyte ``browserHtml``) need not carry
    either marker set.
    """
    wall = detect_wall(body)
    if wall is not None:
        return BodyVerdict("wall", wall)
    for marker in target.real_markers:
        if marker in body:
            return BodyVerdict("publisher-page", marker.decode("utf-8", "backslashreplace"))
    return BodyVerdict("unrecognized", None)


def _response_record(target: Target, response: _Response) -> dict[str, Any]:
    verdict = classify_body(response.body, target)
    return {
        "target": target.name,
        "requested_url": response.requested_url,
        "resolved_url": response.resolved_url,
        "status_code": response.status_code,
        "content_type": response.content_type,
        "byte_length": len(response.body),
        "mode": response.mode,
        "classification": verdict.classification,
        "marker": verdict.marker,
        # Full decoded text here; scrubbed, then truncated, at record time.
        "body_prefix": response.body.decode("utf-8", "replace"),
        "request_id": response.request_id,
    }


def probe_target(
    fetcher: _Fetcher, provider: Provider, target: Target, retries_left: int
) -> tuple[dict[str, Any], bool]:
    """One bounded fetch per target; a target 403/429 gets one fallback fetch while the budget allows."""
    try:
        first = fetcher.fetch(target.url, timeout_seconds=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, mode=provider.body_mode)
    except provider.transport_error as error:
        return {"target": target.name, "requested_url": target.url, "error": str(error)}, False
    if first.status_code in RETRY_STATUSES and retries_left > 0:
        try:
            second = fetcher.fetch(
                target.url, timeout_seconds=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, mode=provider.retry_mode
            )
        except provider.transport_error as error:
            return {
                **_response_record(target, first),
                "retried_after_status": first.status_code,
                "retry_error": str(error),
            }, True
        return {**_response_record(target, second), "retried_after_status": first.status_code}, True
    return _response_record(target, first), False


def _scrubbed(record: dict[str, Any], credential: str) -> dict[str, Any]:
    """Every string and key scrubbed, nested ones included; the body prefix is scrubbed before it is truncated."""
    result = scrub_record(record, credential)
    if "body_prefix" in result:
        result["body_prefix"] = result["body_prefix"][:PREFIX_CHARS]
    return result


def _run_header(provider: Provider, started: datetime) -> dict[str, Any]:
    return {
        "kind": f"{provider.name}-client-smoke-run",
        "provider": provider.name,
        "started_utc": started.isoformat(),
        "command": RUN_COMMAND.format(provider=provider.name),
        "limits": {
            "timeout_seconds": TIMEOUT_SECONDS,
            "max_bytes": MAX_BYTES,
            "body_mode": provider.body_mode,
            "retry_mode": provider.retry_mode,
            "max_retries": MAX_RETRIES,
            "retry_statuses": sorted(RETRY_STATUSES),
        },
        "targets": [
            {"name": target.name, "url": target.url, "documented_wall": target.documented_wall} for target in TARGETS
        ],
    }


def _report_line(record: dict[str, Any]) -> str:
    """One scrubbed line per target; the marker name is the only evidence quoted."""
    if "error" in record:
        line = f"{record['target']} requested={record['requested_url']} error={record['error']!r}"
        if record.get("retry_error"):
            line += f" retry_error={record['retry_error']!r}"
        return line
    line = (
        f"{record['target']} requested={record['requested_url']} resolved={record['resolved_url']} "
        f"status={record['status_code']} type={record['content_type']} bytes={record['byte_length']} "
        f"mode={record['mode']} verdict={record['classification']}"
    )
    if record["marker"]:
        line += f" marker={record['marker']!r}"
    if record.get("retried_after_status") is not None:
        line += f" retried_after_status={record['retried_after_status']}"
    return f"{line} prefix={record['body_prefix']!r}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def default_receipt_path(provider: Provider, started: datetime) -> Path:
    """The provider's campaign receipt, in a directory named for the run's UTC date (see AGENTS.md)."""
    day = started.astimezone(UTC).date().isoformat()
    return RECEIPTS_ROOT / f"{provider.name}-client-smoke-{day}" / RECEIPT_NAME


def run(fetcher: _Fetcher, provider: Provider, receipt_path: Path, *, started: datetime | None = None) -> int:
    """Probe every target, writing each scrubbed row as it lands, then report one line per target.

    The receipt is created exclusively before the first request: an existing
    file raises ``FileExistsError`` and no request is made. Rows are flushed
    as they are written, so an interrupted run keeps what it observed.
    """
    started = started or _utc_now()
    credential = getattr(fetcher, provider.credential_attribute)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with receipt_path.open("x") as handle:
        handle.write(json.dumps(_scrubbed(_run_header(provider, started), credential), sort_keys=True) + "\n")
        handle.flush()
        retries_left = MAX_RETRIES
        for target in TARGETS:
            record, retried = probe_target(fetcher, provider, target, retries_left)
            if retried:
                retries_left -= 1
            scrubbed = _scrubbed(record, credential)
            handle.write(json.dumps(scrubbed, sort_keys=True) + "\n")
            handle.flush()
            records.append(scrubbed)
    print(f"receipt: {receipt_path}", file=sys.stderr)
    for record in records:
        print(_report_line(record))
    return 0


def main(argv: list[str] | None = None, *, clock: Callable[[], datetime] = _utc_now) -> int:
    parser = argparse.ArgumentParser(description="Probe the walled publishers once each through one proxy provider.")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS), help="proxy client to probe through")
    parser.add_argument("--receipt", type=Path, default=None, help="new receipt JSONL path; default is dated")
    args = parser.parse_args(argv)
    provider = PROVIDERS[args.provider]
    try:
        fetcher = provider.fetcher_type.from_environment()
    except provider.transport_error as error:
        print(error, file=sys.stderr)
        return 2
    started = clock()
    receipt = args.receipt if args.receipt is not None else default_receipt_path(provider, started)
    try:
        return run(fetcher, provider, receipt, started=started)
    except FileExistsError:
        print(
            f"receipt {receipt} already exists; retained evidence is never overwritten. Pass --receipt NEW_PATH.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
