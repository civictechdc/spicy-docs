"""Walk any registered publisher JSON list page by page, retaining every page's exact bytes.

The list routes built on ``sources/paged_json.py`` differ only in which
publisher contract they name, which key holds their rows, and whether the
first request is a GET URL or a POST body. ``FAMILIES`` states
exactly that as data, so a pipeline walks any of them through one command
instead of one wrapper per publisher. Each page's bytes go to a
content-addressed store under their own SHA-256 and become one JSONL receipt
row; a refusal writes a failure row carrying the acquisition context the reader
attached, retains any refused bytes, and exits non-zero. A credential is read
only from an explicit file, travels only as the header its family names, and is
scrubbed from every row and message this command writes. A walk is an
observation of one query on one day, never a frozen inventory.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from rulespec_artifacts import LocalBlobWriter

from spicy_docs.sources.congress.listing import BILLS_KEY, CONGRESS_GOV, CRS_REPORTS_KEY
from spicy_docs.sources.courtlistener_search import COURTLISTENER
from spicy_docs.sources.courtlistener_search import RESULTS_KEY as SEARCH_RESULTS_KEY
from spicy_docs.sources.fcc_ecfs import FCC_ECFS, PROCEEDINGS_KEY
from spicy_docs.sources.fcc_ecfs import FILINGS_KEY as FCC_FILINGS_KEY
from spicy_docs.sources.govinfo.discovery import GOVINFO, GRANULES_KEY, PACKAGES_KEY
from spicy_docs.sources.lda import FILINGS_KEY as LDA_FILINGS_KEY
from spicy_docs.sources.lda import LDA
from spicy_docs.sources.paged_json import (
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_MAX_PAGES,
    JsonPage,
    JsonPageFamily,
    PagedJsonBudget,
    PagedJsonReader,
    PagedJsonSourceError,
)
from spicy_docs.sources.refusals import retain_refused_response
from spicy_docs.sources.regulations_gov.api import DOCUMENTS_KEY, REGULATIONS_GOV_API
from spicy_docs.sources.sam import ENTITIES_KEY, SAM
from spicy_docs.sources.usaspending import RECIPIENTS_URL, USASPENDING
from spicy_docs.sources.usaspending import RESULTS_KEY as RECIPIENT_RESULTS_KEY
from spicy_docs.transport.credentials import read_api_key, scrub_credential

if TYPE_CHECKING:
    import httpx
    from rulespec_artifacts import LocalBlobWrite


@dataclass(frozen=True, slots=True)
class ListRoute:
    """One registered route: a publisher contract, the key holding its rows, and how it is keyed and paced.

    The family already states the host, the request method, the continuation
    kind, the credential header and whether a credential is required, so a
    route adds only what the family cannot know: which rows this endpoint
    serves, which environment variable conventionally holds the key, the fixed
    URL of a POST list, and the publisher's own pacing where its rate limit
    demands more than the shared default.
    """

    family: JsonPageFamily
    records_key: str
    env_var: str | None = None
    url: str | None = None
    min_request_interval_seconds: float = 0.25


FAMILIES: dict[str, ListRoute] = {
    "congress-bills": ListRoute(CONGRESS_GOV, BILLS_KEY, "API_GOV"),
    "congress-crs": ListRoute(CONGRESS_GOV, CRS_REPORTS_KEY, "API_GOV"),
    "govinfo-packages": ListRoute(GOVINFO, PACKAGES_KEY, "API_GOV"),
    "govinfo-granules": ListRoute(GOVINFO, GRANULES_KEY, "API_GOV"),
    "lda-filings": ListRoute(LDA, LDA_FILINGS_KEY),
    "courtlistener-search": ListRoute(COURTLISTENER, SEARCH_RESULTS_KEY),
    "sam-entities": ListRoute(SAM, ENTITIES_KEY, "SAM_GOV"),
    "usaspending-recipients": ListRoute(USASPENDING, RECIPIENT_RESULTS_KEY, url=RECIPIENTS_URL),
    "fcc-proceedings": ListRoute(FCC_ECFS, PROCEEDINGS_KEY, "API_GOV"),
    "fcc-filings": ListRoute(FCC_ECFS, FCC_FILINGS_KEY, "API_GOV"),
    # api.regulations.gov metered 1,000 requests per hour on 2026-09-14, so its
    # own pacing is 3.7s; see docs/sources/regulations-gov-api.md.
    "regulations-gov-documents": ListRoute(
        REGULATIONS_GOV_API, DOCUMENTS_KEY, "API_GOV", min_request_interval_seconds=3.7
    ),
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Walk one registered publisher JSON list with exact page evidence")
    p.add_argument("--family", choices=sorted(FAMILIES), help="Registered list route to walk")
    p.add_argument("--list-families", action="store_true", help="Describe every registered route offline and exit")
    p.add_argument("--url", help="First page URL of a GET list, spelled as the publisher spells it")
    p.add_argument("--body", help="First page JSON body of a POST list; the URL is the family's own")
    p.add_argument("--store", type=Path, default=Path("list-blobs"), help="Content-addressed page store")
    p.add_argument("--output", type=Path, help="Create a new JSONL receipt file; defaults to stdout")
    p.add_argument("--env-file", type=Path, help="Read the credential from this explicit file, never the environment")
    p.add_argument("--env-var", help="Credential variable name; defaults to the family's conventional one")
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Continuations beyond this bound refuse")
    p.add_argument("--max-requests", type=int, default=3, help="Attempts allowed per page, retries included")
    p.add_argument("--max-page-bytes", type=int, default=DEFAULT_MAX_PAGE_BYTES)
    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument(
        "--min-request-interval-seconds", type=float, help="Seconds between request starts; default is the family's"
    )
    return p


def _describe(name: str, route: ListRoute) -> dict:
    family = route.family
    return {
        "family": name,
        "publisher": family.label,
        "host": family.host,
        "method": family.method,
        "first_request": "body" if family.method == "POST" else "url",
        "url": route.url,
        "records_key": route.records_key,
        "continuation": family.next_kind,
        "declared_count": family.count_kind if family.count_path else None,
        "credential": (
            "required" if family.requires_credential else "optional" if family.credential_header else "none"
        ),
        "credential_header": family.credential_header,
        "env_var": route.env_var,
        "min_request_interval_seconds": route.min_request_interval_seconds,
    }


def _credential(args: argparse.Namespace, route: ListRoute) -> str:
    """Read the key only from the named file, and only where the family names a header for it."""
    name = args.env_var or route.env_var
    if args.env_file is not None and not name:
        raise PagedJsonSourceError(f"{route.family.label} has no conventional credential variable; name one --env-var")
    key = read_api_key(args.env_file, name) if args.env_file is not None else ""
    if route.family.requires_credential and not key:
        raise PagedJsonSourceError(
            f"{route.family.label} requires a credential; pass --env-file with --env-var {name or '<NAME>'}"
        )
    if key and not route.family.credential_header:
        raise PagedJsonSourceError(f"{route.family.label} accepts no credential; omit --env-file")
    return key


def _request(args: argparse.Namespace, route: ListRoute) -> tuple[str, dict | None]:
    """A GET list names its first page by URL; a POST list names it by body on the family's own URL."""
    post = route.family.method == "POST"
    if post == (args.body is None):
        raise PagedJsonSourceError(
            f"{route.family.label} {route.family.method} lists {'require' if post else 'forbid'} --body"
        )
    url = args.url or route.url
    if not url:
        raise PagedJsonSourceError(f"{route.family.label} needs an explicit --url for its first page")
    body = json.loads(args.body) if post else None
    if body is not None and not isinstance(body, dict):
        raise PagedJsonSourceError("--body must be a JSON object")
    return url, body


def _page_row(name: str, page: JsonPage, stored: LocalBlobWrite) -> dict:
    capture = page.capture
    return {
        "family": name,
        "page_index": page.page_index,
        "records_key": page.records_key,
        "request_url": capture.requested_url,
        "resolved_url": capture.resolved_url,
        "request_body": dict(page.request_body) if page.request_body is not None else None,
        "status": capture.status_code,
        "media_type": (capture.content_type or "").split(";", 1)[0].strip() or None,
        "observed_at": capture.observed_at,
        "bytes": capture.byte_size,
        "sha256": capture.sha256,
        "blob_path": stored.object_key,
        "records": len(page.records),
        "declared_count": page.declared_count,
        "continuation_offered": page.next_url is not None,
    }


def run(args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> int:
    """One walk, or one offline registry listing. ``transport`` is for tests; ``main`` leaves it unset."""
    key = ""
    try:
        with args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout) as output:

            def emit(kind: str, value: dict) -> None:
                # Scrub the whole serialized row: a credential must not reach evidence through any field.
                output.write(scrub_credential(json.dumps({"kind": kind, **value}, ensure_ascii=False), key) + "\n")
                output.flush()

            if args.list_families:
                for name, route in FAMILIES.items():
                    emit("family", _describe(name, route))
                return 0
            route = FAMILIES[args.family]
            run_id = str(uuid4())
            emit("started", {"run_id": run_id, "family": args.family, "max_pages": args.max_pages})
            pages = records = requests = 0
            reader = None
            try:
                key = _credential(args, route)
                url, body = _request(args, route)
                budget = PagedJsonBudget(
                    max_requests=args.max_requests,
                    max_page_bytes=args.max_page_bytes,
                    timeout_seconds=args.timeout_seconds,
                    min_request_interval_seconds=(
                        route.min_request_interval_seconds
                        if args.min_request_interval_seconds is None
                        else args.min_request_interval_seconds
                    ),
                )
                writer = LocalBlobWriter(args.store)
                with PagedJsonReader(
                    family=route.family, budget=budget, api_key=key or None, transport=transport
                ) as reader:
                    for page in reader.pages(url, records_key=route.records_key, max_pages=args.max_pages, body=body):
                        stored = writer.put(
                            [page.capture.body], max_bytes=budget.max_page_bytes, expected_digest=page.capture.sha256
                        )
                        pages, records, requests = (
                            pages + 1,
                            records + len(page.records),
                            requests + reader.request_count,
                        )
                        emit("page", {"run_id": run_id, **_page_row(args.family, page, stored)})
                emit(
                    "complete",
                    {
                        "run_id": run_id,
                        "pages": pages,
                        "records": records,
                        "requests": requests,
                        "scope": "one list query observed on this day; not a frozen publisher inventory",
                    },
                )
            except (ValueError, RuntimeError, OSError, TypeError, SystemExit) as error:
                detail = {
                    "run_id": run_id,
                    "family": args.family,
                    "error_type": type(error).__name__,
                    # Scrub before truncating: truncating first can cut a key and leave its front standing.
                    "error": scrub_credential(str(error), key)[:1000],
                    "pages": pages,
                    "complete": False,
                }
                context = getattr(error, reader.context_key, None) if reader is not None else None
                if isinstance(context, Mapping):
                    detail["acquisition"] = dict(context)
                refused = retain_refused_response(
                    error, store=args.store, max_bytes=args.max_page_bytes, credential=key
                )
                if refused is not None:
                    detail["refused_evidence"] = refused
                emit("failed", detail)
                return 1
        return 0
    except OSError as error:
        print(scrub_credential(str(error), key), file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not args.list_families and not args.family:
        p.error("--family is required unless --list-families")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
