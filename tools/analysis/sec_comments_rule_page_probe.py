#!/usr/bin/env python3
"""One bounded live probe of SEC rule pages, to confirm the ``parse_rule_page`` shape.

Captures the S7-11-23 rule page, the live rulemaking index and one SRO rule
page the index states, if any, through ``SecCommentsAcquirer``: the declared
fair-access agent (``SPICY_DOCS_CONTACT_EMAIL`` must name a real mailbox),
one-second pacing far under sec.gov's ten-per-second ceiling, one attempt per
page, bounded bytes and no redirects. Each parsed response is written to
``--out`` with its digest in ``probe-record.json``, which a failure keeps with
the refused response's digest; ``--emit-fixture`` then writes the trimmed
``rule-page.html`` test fixture from the S7-11-23 capture, keeping verbatim
only the nodes the parser reads (the ``h1`` and the ``field--name-``
statement divs), wrapped in a synthesized HTML envelope.

    uv run --frozen python tools/analysis/sec_comments_rule_page_probe.py --out ~/Work/corpora/supply-2026-09-02/receipts/sec-comments-rule-page-probe-2026-09-24/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from spicy_docs.sources.sec_comments.acquisition import (
    SecCommentsAcquirer,
    SecCommentsBudget,
    SecPageAcquisition,
    declared_user_agent,
)
from spicy_docs.sources.sec_comments.pages import DEFAULT_MAX_PAGE_BYTES, RULEMAKING_INDEX_PATH, SEC_SITE
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture

if TYPE_CHECKING:
    import httpx

S7_RULE_PAGE = f"{SEC_SITE}/rules-regulations/2025/06/s7-11-23"
INDEX_URL = f"{SEC_SITE}{RULEMAKING_INDEX_PATH}"
#: One attempt per page, one second apart; the probe reads at most three pages.
BUDGET = SecCommentsBudget(
    max_requests=1,
    max_page_bytes=DEFAULT_MAX_PAGE_BYTES,
    max_comment_bytes=DEFAULT_MAX_PAGE_BYTES,
    timeout_seconds=60,
    min_request_interval_seconds=1.0,
)
#: The field machine names the rule-page parser reads, plus the compliance-date field whose
#: item carries the extension's prose citation (``at 90 FR 2837``) the parser's prose scan reads.
FIELD_NODES = (
    "field-file-number",
    "field-release-number",
    "field-document-citation",
    "field-compliance-date",
    "field-comments-received",
)
#: Tags that never need a closing tag, so they do not count toward nesting depth.
_VOID_TAGS = frozenset({"br", "img", "meta", "link", "input", "hr", "source", "wbr"})
_TAG = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)((?:[^\"'>]|\"[^\"]*\"|'[^']*')*?)\s*(/?)>")
_CLASS = re.compile(r'\bclass\s*=\s*"([^"]*)"')


def _node_spans(body: str) -> list[tuple[int, int]]:
    """The byte spans of the first ``h1`` and every ``div`` whose class names a ``FIELD_NODES`` entry."""

    spans: list[tuple[int, int]] = []
    h1_start: int | None = None
    h1_depth = 0
    field_start: int | None = None
    field_depth = 0
    position = 0
    for match in _TAG.finditer(body):
        position = match.end()
        closing, tag, attrs, self_closing = match.groups()
        if closing:
            if h1_depth:
                h1_depth -= 1
                if h1_depth == 0 and h1_start is not None:
                    spans.append((h1_start, position))
                    h1_start = None
            if field_depth:
                field_depth -= 1
                if field_depth == 0 and field_start is not None:
                    spans.append((field_start, position))
                    field_start = None
            continue
        if self_closing or tag in _VOID_TAGS:
            continue
        if h1_depth:
            h1_depth += 1
            continue
        if field_depth:
            field_depth += 1
            continue
        classes = set((_CLASS.search(attrs).group(1) if _CLASS.search(attrs) else "").split())
        if tag == "h1" and h1_start is None:
            h1_start = match.start()
            h1_depth = 1
        elif tag == "div" and any(f"field--name-{name}" in classes for name in FIELD_NODES):
            field_start = match.start()
            field_depth = 1
    return spans


def _emit_fixture(captured: Path, fixture: Path) -> None:
    body = captured.read_bytes().decode("utf-8")
    spans = _node_spans(body)
    assert spans and all(start < end for start, end in spans), spans
    nodes = [body[start:end] for start, end in spans]
    fixture.write_text(
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8" /></head><body>\n'
        + "\n".join(nodes)
        + "\n</body></html>\n",
        encoding="utf-8",
    )
    print(f"fixture: {fixture} ({fixture.stat().st_size} bytes, {len(nodes)} nodes)")


def _described(capture: CapturedBodyResponse) -> dict:
    return {
        "url": capture.requested_url,
        "status": capture.status_code,
        "contentType": capture.content_type,
        "bytes": capture.byte_size,
        "sha256": capture.sha256.removeprefix("sha256:"),
    }


@contextmanager
def _receipt(path: Path, record: dict) -> Iterator[None]:
    """Retain the responses already observed, and a refused one's digest, even when a later fetch or parse fails."""
    record["outcome"] = "failed"
    try:
        yield
        record["outcome"] = "complete"
    except Exception as error:
        record["errorType"] = type(error).__name__
        if (capture := attached_capture(error)) is not None:
            record["refused"] = _described(capture)
        raise
    finally:
        path.write_text(json.dumps(record, indent=1))


def _keep(out: Path, record: dict, acquisition: SecPageAcquisition) -> None:
    capture = acquisition.capture
    record["requests"].append(_described(capture))
    out.joinpath(urlsplit(capture.requested_url).path.strip("/").replace("/", "_") + ".html").write_bytes(capture.body)


def main(transport: httpx.BaseTransport | None = None) -> None:
    """Probe live (``transport`` is for offline tests), or only retrim a retained capture with ``--emit-fixture``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--emit-fixture", type=Path, default=None)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    s7_capture = args.out / "rules-regulations_2025_06_s7-11-23.html"
    if args.emit_fixture is not None and s7_capture.exists():
        _emit_fixture(s7_capture, args.emit_fixture)  # a retained capture: no network
        return
    record: dict = {"userAgent": declared_user_agent(), "requests": []}
    with (
        _receipt(args.out / "probe-record.json", record),
        SecCommentsAcquirer(budget=BUDGET, transport=transport) as source,
    ):
        _keep(args.out, record, source.acquire_rule_page(S7_RULE_PAGE))
        index = source.acquire_rulemaking_index_page(INDEX_URL)
        _keep(args.out, record, index)
        record["sroRulePage"] = next(
            (
                row.rule_url
                for row in index.page.rulemakings
                if row.rule_url is not None and (row.file_number or "").casefold().startswith("sr")
            ),
            None,
        )
        if record["sroRulePage"] is not None:
            _keep(args.out, record, source.acquire_rule_page(record["sroRulePage"]))
    print(json.dumps(record, indent=1))
    if args.emit_fixture is not None:
        _emit_fixture(s7_capture, args.emit_fixture)


if __name__ == "__main__":
    sys.exit(main())
