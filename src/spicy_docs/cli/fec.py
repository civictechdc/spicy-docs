"""Raw FEC acquisition, deliberately separate from sealed release publication."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from spicy_docs.sources.fec.catalog import official_sources
from spicy_docs.sources.refusals import retain_refused_response
from spicy_docs.transport.credentials import read_api_key, scrub_credential


def _decimal(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("unsupported FEC output value")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", type=Path, default=Path("fec-blobs"), help="Content-addressed response and asset store")
    p.add_argument("--output", type=Path, help="Create a new JSONL observation file; defaults to stdout")
    p.add_argument("--env-file", type=Path, help="Read FEC_API_KEY from this explicit file instead of the environment")
    p.add_argument(
        "--zyte-on-denial", action="store_true", help="Use ZYTE_TOKEN for bounded public-site HTTP 403 recovery"
    )
    p.add_argument("--max-requests", type=int, default=1000)
    p.add_argument("--min-interval", type=float, default=0.25, help="Minimum seconds between request starts")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("collections", help="List official collections, bulk families and acquisition routes offline")
    api = sub.add_parser("api", help="Traverse an explicit OpenFEC JSON GET path")
    api.add_argument("path", help="For example /v1/committees/; substitute IDs in template paths")
    api.add_argument(
        "--param", action="append", default=[], metavar="NAME=VALUE", help="Repeat for multi-valued filters"
    )
    api.add_argument("--max-pages", type=int, default=100)
    objects = sub.add_parser("objects", help="Read XML object listings without fetching the objects")
    objects.add_argument("prefix", help="bulk-downloads/, legal/, user-downloads/, or a narrower prefix")
    objects.add_argument("--max-pages", type=int, default=1000)
    objects.add_argument("--page-size", type=int, default=1000)
    sitemap = sub.add_parser("sitemap", help="Traverse XML indexes without fetching leaf documents")
    sitemap.add_argument("url")
    sitemap.add_argument("--max-pages", type=int, default=100)
    links = sub.add_parser("links", help="Discover links on one explicit HTML/XHTML collection page")
    links.add_argument("url")
    download = sub.add_parser("download", help="Stream one selected original asset separately from metadata")
    download.add_argument("url")
    download.add_argument("--max-bytes", type=int, required=True)
    download.add_argument("--sha256", help="Expected sha256: digest; with size, permits verified offline reuse")
    download.add_argument("--size", type=int)
    download.add_argument("--etag", help="Exact publisher ETag, including its quotes; direct transfers only")
    download.add_argument(
        "--allow-html", action="store_true", help="Explicitly select HTML when no suitable native original exists"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    key = ""
    try:
        with args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout) as output:

            def emit(kind: str, value: dict) -> None:
                output.write(json.dumps({"kind": kind, **value}, default=_decimal, ensure_ascii=False) + "\n")
                output.flush()

            if args.command == "collections":
                for row in official_sources():
                    emit("collection", row)
                return 0
            # HTTP remains optional for core/offline imports and collection listing.
            from spicy_docs.sources.fec.client import FecClient
            from spicy_docs.sources.zyte import ZyteHttpFetcher

            run_id = str(uuid4())
            emit("started", {"run_id": run_id, "operation": args.command})
            try:
                key = read_api_key(args.env_file, "FEC_API_KEY") if args.env_file else os.environ.get("FEC_API_KEY", "")
                zyte = ZyteHttpFetcher.from_environment() if args.zyte_on_denial else None
                with FecClient(
                    store=args.store,
                    api_key=key or None,
                    zyte_on_denial=zyte,
                    max_requests=args.max_requests,
                    min_interval=args.min_interval,
                ) as client:
                    match args.command:
                        case "api":
                            params = {}
                            for param in args.param:
                                name, sep, value = param.partition("=")
                                if not sep or not name:
                                    raise ValueError("--param needs NAME=VALUE")
                                params.setdefault(name, []).append(value)
                            rows = client.api(args.path, params=params, max_pages=args.max_pages)
                        case "objects":
                            rows = client.objects(args.prefix, max_pages=args.max_pages, page_size=args.page_size)
                        case "sitemap":
                            rows = client.sitemap(args.url, max_pages=args.max_pages)
                        case "links":
                            rows = [client.page_links(args.url)]
                        case "download":
                            rows = [
                                client.download(
                                    args.url,
                                    max_bytes=args.max_bytes,
                                    expected_sha256=args.sha256,
                                    expected_size=args.size,
                                    etag=args.etag,
                                    allow_html=args.allow_html,
                                )
                            ]
                    for row in rows:
                        emit("asset" if args.command == "download" else "page", {"run_id": run_id, **row})
                    emit(
                        "complete",
                        {
                            "run_id": run_id,
                            "requests": client.http.request_count,
                            "scope": "selected operation only; live observations are not a frozen FEC dataset",
                        },
                    )
            except (ValueError, RuntimeError, OSError, TypeError, SystemExit) as error:
                detail = {"run_id": run_id, "error": scrub_credential(str(error), key)[:1000], "complete": False}
                refused = retain_refused_response(error, store=args.store, max_bytes=8 * 1024**2, credential=key)
                if refused is not None:
                    detail["refused_evidence"] = refused
                emit("failed", detail)
                return 1
        return 0
    except OSError as error:
        print(scrub_credential(str(error), key), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
