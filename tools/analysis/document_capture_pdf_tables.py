"""PDF table observations beside DocumentCapture's line-based text stream.

No family-specific table parser lives here. ``tables_to_nodes`` consumes the
extractor's observations; ``pdf_pages_to_nodes`` composes it with the existing
line adapter. The Senate entry point supplies only provenance and a profile.
"""

from __future__ import annotations

import importlib.metadata
import json
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, replace
from functools import reduce
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from spicy_docs.extraction.model import Box, PageResult
from spicy_docs.reconstruction.evidence import evidence_from_pages
from tools.analysis import document_capture as dc

RULE = "pdf-table-exact-page-text-v1"


def source_box(page: int, box: Box | None) -> dict[str, Any]:
    if box is None:
        return {"coordinateSystem": "page-region", "page": page}
    source = dc.block_source(SimpleNamespace(page=page, box=box, line=None))
    del source["line"]
    return source


def _contained(inner: Sequence[int], outer: Sequence[int]) -> bool:
    # One permille allows only rounding at the boundary, not a neighbouring cell.
    return all(inner[i] >= outer[i] - 1 for i in (0, 1)) and all(inner[i] <= outer[i] + 1 for i in (2, 3))


def tables_to_nodes(page: PageResult, parent: dc.Node, original: Sequence[dc.Span]) -> list[tuple[int, int, dc.Node]]:
    """Retain every observed cell and reconcile exact text without changing the stream.

    None/None means no cell; an empty string means a present empty cell. A text
    with no box (observed on the rotated Senate pages) survives with an issue.
    Table dimensions retain missing trailing rows/columns. Spans/headers are
    not inferred: TableObservation does not state them.

    Match a whole cell verbatim on its own page. For repeated text, require
    all contributing line boxes to fit inside the cell box. Refuse remaining
    ambiguity and overlapping claims. Split and transfer matched spans rather
    than duplicate them. No whitespace normalization, reordering, or BodyText
    offsets: its GPO cleanup and page joins define a different stream.

    Unmatched observations stay in ext.observedText with needs_review and a
    pdf-cell-text-unresolved issue. They cannot be UnresolvedRegion objects:
    the pinned parent requires those to own at least one existing span.

    ``original`` contains only this page's spans, including its separators.
    Return disjoint claims for one document-wide transfer after all pages.
    """
    if not page.tables:
        return []
    number = page.metadata["page"]
    owned = [s for s in original if s.source.get("page") == number]
    lo = min((s.start for s in owned), default=0)
    hi = max((s.end for s in owned), default=lo)
    stream_start = original[0].start if original else 0
    page_text = "".join(s.exact for s in original)[lo - stream_start : hi - stream_start]
    starts = [s.start for s in original]
    claims: list[tuple[int, int, dc.Node]] = []

    def unresolved(cell: dc.Node, reason: str) -> None:
        cell.review_status = "needs_review"
        cell.issues.append({"code": "pdf-cell-text-unresolved", "detail": reason})

    for ordinal, observation in enumerate(page.tables):
        if observation.page != number:
            raise ValueError("table observation belongs to a different page")
        table = dc.Node(
            "table",
            parent,
            "pdf-text",
            container=True,
            source=source_box(number, observation.bbox),
            decision={"method": "rule", "rule": "pdf-table-observation-v1"},
            ext={"tableOrdinal": ordinal, "rowCount": observation.row_count, "columnCount": observation.column_count},
        )
        for r, (texts, boxes) in enumerate(zip(observation.cells, observation.cell_boxes, strict=True)):
            present_boxes = [b for b in boxes if b is not None]
            hull = reduce(Box.union, present_boxes) if present_boxes else None
            row = dc.Node(
                "row",
                table,
                "pdf-text",
                container=True,
                source=source_box(number, hull),
                decision={"method": "rule", "rule": "pdf-table-row-box-union-v1"},
            )
            for c, (text, box) in enumerate(zip(texts, boxes, strict=True)):
                if text is None and box is None:
                    continue
                cell = dc.Node(
                    "cell",
                    row,
                    "pdf-text",
                    source=source_box(number, box),
                    cell={"row": r, "column": c},
                    ext={"observedText": text},
                    decision={"method": "rule", "rule": RULE},
                )
                if box is None:
                    cell.issues.append({"code": "pdf-cell-box-missing", "detail": "text observed without a cell box"})
                if text is None:
                    unresolved(cell, "cell-text-missing")
                    continue
                if not text:
                    continue
                candidates = []
                position = page_text.find(text)
                while position >= 0:
                    end = position + len(text)
                    # Do not bind 0.00 to the suffix of 30.00, or a label to
                    # the middle of a longer word elsewhere on the page.
                    inside_word = (position > 0 and text[0].isalnum() and page_text[position - 1].isalnum()) or (
                        end < len(page_text) and text[-1].isalnum() and page_text[end].isalnum()
                    )
                    if not inside_word:
                        candidates.append((lo + position, lo + end))
                    position = page_text.find(text, position + 1)
                if not candidates:
                    unresolved(cell, "text-not-in-page-stream")
                    continue
                if len(candidates) > 1 and box is not None:
                    bounded = []
                    for start, end in candidates:
                        spans = original[bisect_right(starts, start) - 1 : bisect_right(starts, end - 1)]
                        if all(
                            not s.exact.strip()
                            or (
                                s.source.get("page") == number
                                and "box" in s.source
                                and _contained(s.source["box"], cell.source["box"])
                            )
                            for s in spans
                        ):
                            bounded.append((start, end))
                    candidates = bounded
                if len(candidates) != 1:
                    unresolved(cell, "ambiguous-page-text" if candidates else "repeated-text-without-cell-local-match")
                    continue
                claims.append((*candidates[0], cell))

    # Refuse both sides of an overlap, including duplicate table observations.
    claims.sort(key=lambda claim: (claim[0], claim[1]))
    conflicting: set[int] = set()
    # Sorted interval components let us flag every participant once, even
    # when all claims overlap or one long claim contains many shorter ones.
    component: list[dc.Node] = []
    component_end = -1
    for claim in claims:
        if claim[0] >= component_end:
            if len(component) > 1:
                conflicting.update(id(cell) for cell in component)
            component = []
        component.append(claim[2])
        component_end = max(component_end, claim[1])
    if len(component) > 1:
        conflicting.update(id(cell) for cell in component)
    for _, _, cell in claims:
        if id(cell) in conflicting:
            unresolved(cell, "overlapping-cell-claims")
    return [claim for claim in claims if id(claim[2]) not in conflicting]


def _transfer_spans(builder: dc.Builder, owners: dict[int, dc.Node], claims: list[tuple[int, int, dc.Node]]) -> None:
    """Split the document once and replace each owner's span list without searches."""
    if not claims:
        return
    claims.sort(key=lambda claim: (claim[0], claim[1]))
    claim_starts = [c[0] for c in claims]
    boundaries = sorted({p for start, end, _ in claims for p in (start, end)})
    rebuilt: list[dc.Span] = []
    for owner in {id(owner): owner for owner in owners.values()}.values():
        owner.spans.clear()
    for span in builder.spans:
        owner = owners[id(span)]
        cuts = [
            span.start,
            *boundaries[bisect_right(boundaries, span.start) : bisect_right(boundaries, span.end - 1)],
            span.end,
        ]
        for start, end in pairwise(cuts):
            index = bisect_right(claim_starts, start) - 1
            target = claims[index][2] if index >= 0 and end <= claims[index][1] else owner
            piece = replace(span, exact=span.exact[start - span.start : end - span.start], start=start, end=end, id="")
            target.spans.append(piece)
            rebuilt.append(piece)
    builder.spans = rebuilt


def _order_page(parent: dc.Node, hi: int) -> None:
    # A fully transferred line no longer represents an independent text leaf.
    parent.children[:] = [n for n in parent.children if n.kind != "line" or n.spans]

    def first_span(node: dc.Node) -> int:
        return min([s.start for s in node.spans] + [first_span(child) for child in node.children], default=hi)

    # Place reconciled tables at their first stream evidence. A table without
    # a match remains after the lines, in extractor order; do not guess an anchor.
    parent.children.sort(key=first_span)


def pdf_pages_to_nodes(pages: Sequence[PageResult], builder: dc.Builder) -> dict[str, Any]:
    """Compose the existing lines and the table adapter; return retained extractor evidence."""
    evidence = evidence_from_pages(pages)
    sizes = {}
    for page in pages:
        x0, y0, x1, y1 = page.metadata["geometry"]["display_rect"]
        sizes[page.metadata["page"]] = {"width": x1 - x0, "height": y1 - y0, "unit": "point"}
    nodes = dc.lines_to_pages(evidence, builder, "pdf-text", sizes)
    owners = {id(s): n for n in builder.nodes() for s in n.spans}
    spans_by_page: dict[int, list[dc.Span]] = defaultdict(list)
    for span in builder.spans:
        # Page-owned newlines have no source coordinates; the document owns
        # form feeds, which must never enter a cell's search text.
        number = owners[id(span)].source.get("page")
        if number is not None:
            spans_by_page[number].append(span)
    claims = []
    matched_pages = []
    for page in pages:
        number = page.metadata["page"]
        if number not in nodes:
            nodes[number] = dc.Node(
                "page",
                builder.root,
                "pdf-text",
                container=True,
                designation=str(number),
                source=source_box(number, None),
                page_size=sizes[number],
            )
        nodes[number].ext = {"pageTextSha256": dc.sha256(page.text)}
        original = spans_by_page[number]
        page_claims = tables_to_nodes(page, nodes[number], original)
        claims.extend(page_claims)
        if page_claims:
            hi = max((s.end for s in original if s.source.get("page") == number), default=0)
            matched_pages.append((nodes[number], hi))
    _transfer_spans(builder, owners, claims)
    for parent, hi in matched_pages:
        _order_page(parent, hi)
    builder.root.children.sort(key=lambda n: n.source["page"])
    retained = json.loads(evidence.dumps())
    retained["tablePages"] = [
        {"page": p.metadata["page"], "geometry": p.metadata["geometry"], "tables": [asdict(t) for t in p.tables]}
        for p in pages
    ]
    return retained


def convert_senate_pages(
    pages: Sequence[PageResult],
    *,
    pdf: bytes,
    pdf_path: Path,
    package_id: str,
    file_name: str,
    intermediate_path: Path,
) -> dc.Conversion:
    """A bounded Senate capture; callers select and extract pages with tables=True."""
    digest = dc.sha256(pdf)
    if not pages or any(p.metadata.get("source_sha256") != digest for p in pages):
        raise ValueError("pages must name this PDF's digest")
    builder = dc.Builder(dc.Node("document", None, "pdf-text", container=True))
    retained = pdf_pages_to_nodes(pages, builder)
    data = (json.dumps(retained, ensure_ascii=False, indent=1) + "\n").encode()
    intermediate_path.write_bytes(data)
    converter = dc.converter_record("senate-expenditures-pdf", [("pymupdf", importlib.metadata.version("pymupdf"))])
    converter["id"] = "spicy-docs/tools/analysis/document_capture_pdf_tables.py#senate-expenditures-pdf"
    converter["implementation"]["fileSha256"] = dc.sha256(Path(__file__).read_bytes())
    return dc.Conversion(
        file_name.removesuffix(".pdf"),
        "senate-expenditures-pdf",
        "pdf",
        dc.artifact_record(
            digest, len(pdf), "application/pdf", {"path": str(pdf_path), "publisherId": package_id}, [], None
        ),
        converter,
        {
            "packageId": package_id,
            "fileName": file_name,
            "pagesRead": [p.metadata["page"] for p in pages],
            "pageCount": pages[0].metadata["page_count"],
            "lineConverterSha256": dc.sha256(Path(dc.__file__).read_bytes()),
        },
        builder,
        data,
        retained,
        {
            "iri": f"urn:document-capture:intermediate:sha256:{dc.sha256(data)}",
            "sha256": dc.sha256(data),
            "byteSize": len(data),
            "mediaType": "application/json",
            "locator": {"path": str(intermediate_path)},
            "producer": "DocumentExtractor(NativeText(), tables=True); evidence_from_pages; retained TableObservations",
        },
    )
