"""Worked conversions of real federal documents into the DocumentCapture v1 shape.

The parent schema is Rulespec's (``release-records/schemas/document-capture-v1.schema.json``,
vendored under ``spicy_docs/schemas/document_capture/1.0`` and pinned by digest);
the family profiles are this repository's. This tool proves that one shape fits
six renditions -- a USLM public law, a bill XML through DeltaTrack, a
committee-report HTML body, a Federal Register notice XML, a reconstructed CFR
section and a slip-opinion PDF's extracted lines -- with no per-family branch
in the core: each family supplies a *grammar* (element name to structural
role) and an extension block, nothing else.

**What a capture is.** A tree of nodes (structure) over an ordered partition of
the rendition's text into evidence spans (exact text with the artifact's own
coordinates). Every span belongs to exactly one node or one unresolved region;
concatenating the spans reproduces the text stream, whose digest is the
round-trip witness. Nothing here interprets: node kinds are structural, the
publisher's element names travel in ``source.element``, and a rule that
assembled text names itself in ``derived``.

**Complexity.** One pass over the reader's events or the evidence blocks and
O(N + S) over nodes and spans to number and check them, so the whole of a
conversion is linear in its input except for three steps, each named where it
sits: ``Elem.has_structure`` asks whether a subtree contains structure and is
memoized per element, because without the memo the walk re-scans each subtree
once per enclosing level (O(n*depth)); the Federal Register cell geometry
reads a row's and a table's index from prebuilt maps rather than by scanning;
and the sub-line split of a reconstruction block shared by a parent and its
children scans that one line's text once per child. The docstring claimed
plain O(E) before the 2026-09-19 review measured it; at these sizes every
document converts in under a millisecond either way, and the fix is the
memo, not a different algorithm.

Run from the repository root through the project's runner:

    uv run --frozen python -m tools.analysis.document_capture --output docs/research/document-capture-schema-2026-09-19

Design record: ``docs/research/document-capture-schema-2026-09-19.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from spicy_docs.reading.markup import MarkupEvent, MarkupRead, read_html_events, read_xml_events

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = files("spicy_docs").joinpath("schemas/document_capture/1.0")
PARENT_SCHEMA = "document-capture-v1.schema.json"
PROFILE_META_SCHEMA = "document-capture-profile-v1.schema.json"
#: Rulespec's invariant validator, vendored beside its schemas and pinned in ``PINS.json``.
VENDORED_INVARIANTS = "rulespec/document_capture.py"
CONVERTER_VERSION = "2"
FIXTURES = ROOT / "tests" / "fixtures"

NONE = {"coordinateSystem": "none"}
#: Node kinds that enclose a unit, for the heading-level rule; see the parent's ``level``.
UNIT_KINDS = frozenset(
    ["division", "section", "paragraph", "list", "item", "quote", "note", "footnote", "table", "row"]
)


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(name).read_text(encoding="utf-8"))


def schema_pin(name: str) -> dict[str, Any]:
    return {"$id": load_schema(name)["$id"], "sha256": sha256(SCHEMAS.joinpath(name).read_bytes())}


@cache
def rulespec_invariants() -> Any:
    """Rulespec's ``document_capture`` module: the wheel's copy when it carries one, else the vendored file.

    The invariant validator and the profile bindings are Rulespec's, shipped in
    ``rulespec-artifacts``. The pinned wheel here predates that module, so the
    file is vendored beside the schemas the same way ``source-fragment.schema.json``
    is -- as bytes, pinned in ``PINS.json``, never as a second implementation to
    maintain. ``tests/test_document_capture.py`` asserts the vendored bytes equal
    the wheel's the moment the wheel carries them, which is when this shim and
    the vendored copy both go away.
    """
    try:
        from rulespec_artifacts import document_capture as shipped  # ty: ignore[unresolved-import]

        return shipped
    except ImportError:
        spec = importlib.util.spec_from_file_location(
            "spicy_docs._vendored_rulespec_document_capture", str(SCHEMAS.joinpath(VENDORED_INVARIANTS))
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def core_kinds() -> frozenset[str]:
    """The closed core vocabulary, read from the parent schema rather than copied beside it."""
    return frozenset(load_schema(PARENT_SCHEMA)["$defs"]["CoreKind"]["enum"])


def effective_source(capture: Mapping[str, Any], span: Mapping[str, Any]) -> dict[str, Any]:
    """A span's locator with ``rendition.spanDefaults`` filled in; Rulespec's own merge."""
    return rulespec_invariants().effective_source(capture, span)


def node_text(capture: Mapping[str, Any], node: Mapping[str, Any], span_by_id: Mapping[str, Mapping[str, Any]]) -> str:
    """A leaf's text, stated or derived. ``text`` is derivable, so a capture may omit it."""
    if "text" in node:
        return node["text"]
    return "".join(span_by_id[s]["exact"] for s in node["evidence"])


# --- the capture builder -----------------------------------------------------------


@dataclass
class Span:
    exact: str
    source: dict[str, Any]
    tags: tuple[str, ...] = ()
    style: dict[str, Any] | None = None
    start: int = 0
    end: int = 0
    id: str = ""


@dataclass
class Node:
    kind: str
    parent: Node | None
    derivation: str
    #: Decided at creation: a container never carries citable text of its own, only whitespace.
    container: bool = False
    designation: str | None = None
    level: int | None = None
    source: dict[str, Any] = field(default_factory=lambda: dict(NONE))
    page_size: dict[str, Any] | None = None
    cell: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    review_status: str | None = None
    derived: dict[str, Any] | None = None
    ext: dict[str, Any] | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    id: str = ""
    depth: int = 0
    ordinal: int = 0

    def __post_init__(self) -> None:
        if self.parent is not None:
            self.parent.children.append(self)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def text(self) -> str:
        return "".join(span.exact for span in self.spans)


@dataclass
class Region:
    spans: list[Span]
    issue: str
    detail: str = ""
    parent: Node | None = None


class Builder:
    """Accumulates spans in stream order and nodes in a tree; ``finish`` numbers them."""

    def __init__(self, root: Node) -> None:
        self.root = root
        self.spans: list[Span] = []
        self.regions: list[Region] = []
        self.issues: list[dict[str, Any]] = []
        self._cursor = 0

    def span(self, owner: Node | Region, exact: str, source: Mapping[str, Any], **extra: Any) -> Span:
        if not exact:
            raise ValueError("a span must carry text")
        span = Span(exact, dict(source), start=self._cursor, end=self._cursor + len(exact), **extra)
        self._cursor = span.end
        self.spans.append(span)
        owner.spans.append(span)
        return span

    def nodes(self) -> Iterator[Node]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def finish(self) -> tuple[list[Node], str]:
        nodes = list(self.nodes())
        for index, node in enumerate(nodes, 1):
            node.id = f"n{index:04d}"
            node.depth = 0 if node.parent is None else node.parent.depth + 1
            for ordinal, child in enumerate(node.children):
                child.ordinal = ordinal
        for index, span in enumerate(self.spans, 1):
            span.id = f"s{index:04d}"
        for node in nodes:
            # One rule for every family: a leaf that carries no text the print
            # shows says so, whether the publisher wrote an empty element or the
            # extractor emitted a line of spaces. The markup families raised
            # this and the PDF families did not, which made an empty leaf mean
            # different things in two captures of the same shape.
            if node.is_leaf and not node.text.strip() and not any(i["code"] == "empty-leaf" for i in node.issues):
                detail = "no text" if not node.spans else "whitespace only"
                node.issues.append({"code": "empty-leaf", "detail": detail})
        return nodes, "".join(span.exact for span in self.spans)


def node_json(node: Node) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": node.id,
        "kind": node.kind,
        "parent": None if node.parent is None else node.parent.id,
        "ordinal": node.ordinal,
        "depth": node.depth,
        "derivation": node.derivation,
    }
    if node.designation is not None:
        out["designation"] = node.designation
    if node.level is not None:
        out["level"] = node.level
    if node.is_leaf:
        out["text"] = node.text
    out["evidence"] = [span.id for span in node.spans]
    out["source"] = node.source
    for key, value in (
        ("pageSize", node.page_size),
        ("cell", node.cell),
        ("decision", node.decision),
        ("reviewStatus", node.review_status),
        ("derived", node.derived),
        ("ext", node.ext),
    ):
        if value is not None:
            out[key] = value
    if node.issues:
        out["issues"] = node.issues
    return out


def span_json(span: Span, *, digests: bool = False) -> dict[str, Any]:
    """One span. ``sha256`` is derivable from ``exact``, so it is written only when asked for.

    Stating it costs about a tenth of a capture's bytes and tells a reader
    nothing a validator does not recompute; the parent made it optional for
    that reason and the invariant validator refuses a stated digest that
    differs either way.
    """
    out: dict[str, Any] = {"id": span.id, "start": span.start, "end": span.end, "exact": span.exact}
    if digests:
        out["sha256"] = sha256(span.exact)
    out["source"] = span.source
    if span.tags:
        out["tags"] = list(span.tags)
    if span.style:
        out["style"] = span.style
    return out


def hoist_span_defaults(spans: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Move the span source fields every span agrees on onto the rendition, and drop them from the spans."""
    defaults: dict[str, Any] = {}
    for key in ("coordinateSystem", "literal"):
        values = {json.dumps(s["source"].get(key)) for s in spans}
        if len(values) == 1 and (value := json.loads(values.pop())) is not None:
            defaults[key] = value
    for span in spans:
        span["source"] = {k: v for k, v in span["source"].items() if k not in defaults}
    return defaults


# --- markup renditions -------------------------------------------------------------


@dataclass(frozen=True)
class Grammar:
    """A family's element roles. Anything unnamed is transparent; its text becomes a ``text`` leaf.

    Element names keep their prefix (``dc:title``), because a local name can
    collide with the family's own vocabulary: a bill's ``<title>`` is a
    division, its Dublin Core ``<dc:title>`` is metadata.
    """

    name: str
    containers: Mapping[str, str]
    leaves: Mapping[str, str]
    inline: frozenset[str]
    furniture: Mapping[str, str] = field(default_factory=dict)
    derivation: str = "native"
    heading_level: Callable[[Elem], int | None] | None = None

    def role(self, name: str) -> str | None:
        for table in (self.containers, self.leaves, self.furniture):
            if name in table:
                return table[name]
        return None


@dataclass
class Elem:
    name: str
    attributes: dict[str, str | None]
    byte_start: int
    byte_end: int | None
    path: str
    parts: list[Elem | MarkupEvent] = field(default_factory=list)
    #: Memo for ``has_structure``. Without it the walk asks the same subtree
    #: once per enclosing level, which is O(n*depth) over one document.
    _structure: bool | None = field(default=None, repr=False, compare=False)

    def has_structure(self, grammar: Grammar) -> bool:
        if self._structure is None:
            self._structure = any(
                isinstance(part, Elem)
                and (
                    grammar.role(part.name) is not None
                    or (part.name not in grammar.inline and part.has_structure(grammar))
                )
                for part in self.parts
            )
        return self._structure


def element_tree(read: MarkupRead, body: bytes) -> Elem:
    """Fold the reader's flat events into a tree, keeping every text event and its byte span."""
    root = Elem("", {}, 0, len(body), "")
    stack: list[Elem] = [root]
    counts: list[dict[str, int]] = [{}]
    for event in read.events:
        if event.kind in ("start", "empty"):
            name = event.name or ""
            # Counted by local name, not by the prefixed name, so the index is
            # the one an XPath with no namespace context would compute. The
            # step keeps the publisher's own spelling; leaf_fragments rewrites
            # it to *[local-name()='...'] and the index still selects.
            local = name.rpartition(":")[2]
            counts[-1][local] = counts[-1].get(local, 0) + 1
            path = f"{stack[-1].path}/{name}[{counts[-1][local]}]"
            elem = Elem(name, dict(event.attributes), event.byte_start, None, path)
            stack[-1].parts.append(elem)
            if event.kind == "start":
                stack.append(elem)
                counts.append({})
            else:
                elem.byte_end = event.byte_end
        elif event.kind == "end":
            elem = stack.pop()
            counts.pop()
            tag = f"</{event.name}>".encode()
            end = event.byte_start + len(tag)
            elem.byte_end = end if body[event.byte_start : end] == tag else None
        elif event.kind == "text" and event.text:
            stack[-1].parts.append(event)
    return root


def locator(elem: Elem) -> dict[str, Any]:
    out: dict[str, Any] = {"coordinateSystem": "xml-node-path", "path": elem.path, "element": elem.name}
    if elem.attributes:
        out["attributes"] = elem.attributes
    if elem.byte_end is not None:
        out.update(start=elem.byte_start, end=elem.byte_end)
    return out


def text_source(event: MarkupEvent) -> dict[str, Any]:
    return {
        "coordinateSystem": "utf8-byte",
        "start": event.byte_start,
        "end": event.byte_end,
        "literal": event.is_literal,
    }


class MarkupConverter:
    """Walk an element tree under a grammar; the structure is the publisher's, the text is exact."""

    def __init__(self, grammar: Grammar, builder: Builder) -> None:
        self.grammar, self.builder = grammar, builder

    def convert(self, root_elem: Elem) -> None:
        for part in root_elem.parts:
            self.part(part, self.builder.root, ())

    def part(self, part: Elem | MarkupEvent, node: Node, tags: tuple[str, ...]) -> None:
        if isinstance(part, MarkupEvent):
            self._text(part, node, tags)
            return
        grammar = self.grammar
        role = grammar.role(part.name)
        if part.name in grammar.furniture:
            self._furniture(part, node)
        elif role is None and part.name in grammar.inline:
            self._inline(part, node, (*tags, part.name))
        elif role is not None and (part.name in grammar.containers or part.has_structure(grammar)):
            self._container(part, node, role)
        elif role is not None:
            self._leaf(part, node, role)
        elif part.has_structure(grammar):
            for inner in part.parts:
                self.part(inner, node, ())
        else:
            self._leaf(part, node, "text")

    def _text(self, event: MarkupEvent, node: Node, tags: tuple[str, ...]) -> None:
        text = event.text or ""
        if not node.container:
            self.builder.span(node, text, text_source(event), tags=tags)
        elif text.strip():
            leaf = Node(
                "text",
                node,
                self.grammar.derivation,
                decision={"method": "generated", "rule": "implicit-character-data-leaf-v1"},
            )
            self.builder.span(leaf, text, text_source(event), tags=tags)
        else:
            self.builder.span(node, text, text_source(event))

    def _inline(self, elem: Elem, node: Node, tags: tuple[str, ...]) -> None:
        for part in elem.parts:
            if isinstance(part, MarkupEvent):
                self._text(part, node, tags)
            elif self.grammar.role(part.name) is None:
                self._inline(part, node, (*tags, part.name))
            else:
                node.issues.append({"code": "structure-inside-inline", "detail": f"{part.name} inside {elem.name}"})
                self.part(part, node, tags)

    def _furniture(self, elem: Elem, node: Node) -> None:
        kind = self.grammar.furniture[elem.name]
        text = "".join(p.text or "" for p in elem.parts if isinstance(p, MarkupEvent))
        designation = text.strip() or next((v for v in elem.attributes.values() if v), None)
        leaf = Node(kind, node, self.grammar.derivation, designation=designation, source=locator(elem))
        for part in elem.parts:
            if isinstance(part, MarkupEvent):
                self._text(part, leaf, ())
            else:
                self._inline(part, leaf, (part.name,))

    def _container(self, elem: Elem, node: Node, kind: str) -> None:
        child = Node(kind, node, self.grammar.derivation, container=True, source=locator(elem))
        self._extend(child, elem)
        for part in elem.parts:
            self.part(part, child, ())
        label = next((c for c in child.children if c.kind == "label" and c.is_leaf), None)
        if label is not None:
            child.designation = label.text

    def _leaf(self, elem: Elem, node: Node, kind: str) -> None:
        leaf = Node(kind, node, self.grammar.derivation, source=locator(elem))
        self._extend(leaf, elem)
        for part in elem.parts:
            if isinstance(part, MarkupEvent):
                self._text(part, leaf, ())
            else:
                self._inline(part, leaf, (part.name,))
        if not leaf.spans:
            leaf.issues.append({"code": "empty-leaf", "detail": f"{elem.name} carries no text"})

    def _extend(self, node: Node, elem: Elem) -> None:
        """A heading's level: the publisher's when it states one, else the depth of the unit it opens.

        The parent defines ``level`` as heading depth from 1, and a family that
        sets it sets it on every heading it can. The Federal Register states the
        depth itself (``HD SOURCE``); USLM and the bill DTD do not, so the level
        is the number of enclosing units, which is the same number the print's
        indentation shows.
        """
        if node.kind != "heading":
            return
        stated = self.grammar.heading_level(elem) if self.grammar.heading_level is not None else None
        if stated is not None:
            node.level = stated
            return
        depth, current = 0, node.parent
        while current is not None:
            if current.kind in UNIT_KINDS:
                depth += 1
            current = current.parent
        node.level = max(depth, 1)
        node.decision = {"method": "rule", "rule": "enclosing-unit-heading-level-v1"}


Piece = tuple[str, dict[str, Any]]


def _split_piece(piece: Piece, widths: Sequence[str]) -> list[Piece]:
    """Cut one text piece into consecutive parts, carrying its byte range with it."""
    _, source = piece
    out: list[Piece] = []
    offset = source.get("start")
    for part in widths:
        if not part:
            continue
        if offset is None or not source.get("literal"):
            out.append((part, dict(source)))
        else:
            width = len(part.encode("utf-8"))
            out.append((part, {**source, "start": offset, "end": offset + width}))
            offset += width
    return out


def _columns(text: str) -> list[str]:
    """The alternating cell texts and column gaps of one fixed-pitch row, in order."""
    return [part for part in _CRPT_COLUMN_GAP.split(text) if part is not None]


def preformatted_blocks(
    events: Sequence[MarkupEvent], container: Node, builder: Builder, classify: Callable[[str], tuple[str, str | None]]
) -> None:
    """Split a preformatted run into blank-line blocks and name what each one is.

    A block's lines and its interior newlines belong to the block; the newline
    after its last line, blank lines, and their newlines belong to the
    container. Byte coordinates are exact only where the reader said the run
    was literal; otherwise a piece's source covers its whole event.

    Three block shapes are read off the typesetting the ``<pre>`` preserves, in
    this order: a ruled column-aligned table, a heading, and otherwise the
    line-by-line classification (page marker, banner, rule, paragraph).
    """
    pieces: list[Piece] = []
    for event in events:
        offset = event.byte_start
        for piece in re.split(r"(\n)", event.text or ""):
            if not piece:
                continue
            if event.is_literal:
                width = len(piece.encode("utf-8"))
                pieces.append(
                    (piece, {"coordinateSystem": "utf8-byte", "start": offset, "end": offset + width, "literal": True})
                )
                offset += width
            else:
                pieces.append((piece, {**text_source(event), "literal": False}))
    lines: list[list[Piece]] = [[]]
    for piece in pieces:
        lines[-1].append(piece)
        if piece[0] == "\n":
            lines.append([])
    # One pass, in stream order: a blank line flushes the block before it, so
    # spans are minted in the order the bytes appear. Buffering the blocks and
    # emitting them afterwards would put every blank line ahead of every block.
    block: list[list[Piece]] = []
    for line in lines:
        if "".join(p for p, _ in line).strip():
            block.append(line)
            continue
        if block:
            _emit_report_block(block, container, builder, classify)
            block = []
        for piece in line:
            builder.span(container, *piece)
    if block:
        _emit_report_block(block, container, builder, classify)


def _emit_report_block(
    block: Sequence[Sequence[Piece]],
    container: Node,
    builder: Builder,
    classify: Callable[[str], tuple[str, str | None]],
) -> None:
    texts = ["".join(p for p, _ in line).rstrip("\n") for line in block]
    rows = report_table(texts)
    if rows is not None:
        _emit_report_table(block, texts, container, builder)
        return
    heading = report_heading_level(texts)
    if heading is not None:
        level, rule = heading
        node = Node(
            "committee-report-html:heading",
            container,
            "markup",
            level=level,
            decision={"method": "rule", "rule": rule},
        )
        _emit_lines(block, node, container, builder)
        return
    if len(texts) > 3 and _CRPT_RULE.match(texts[0]) and _CRPT_RULE.match(texts[-1]):
        # Ruled top and bottom like a vote table, but the rows do not split
        # into the header's columns. That is the declared gap, recorded rather
        # than guessed at: a table read wrongly is worse than a table not read.
        container.issues.append(
            {
                "code": "table-columns-ambiguous",
                "detail": f"a block ruled top and bottom whose {len(texts) - 2} rows do not match its header's columns",
            }
        )
    node: Node | None = None
    for line, text in zip(block, texts, strict=True):
        kind, designation = classify(text)
        single = kind in ("pageNumber", "committee-report-html:banner", "committee-report-html:rule")
        if node is None or node.kind != kind or single:
            node = Node(
                kind,
                container,
                "markup",
                designation=designation,
                decision={"method": "rule", "rule": "gpo-blank-line-block-and-line-kind-v1"},
            )
        content = line[:-1] if line and line[-1][0] == "\n" else line
        newline = line[-1] if line and line[-1][0] == "\n" else None
        for piece in content:
            builder.span(node, *piece)
        if newline is not None:
            builder.span(container if line is block[-1] or single else node, *newline)
            if single:
                node = None


def _emit_lines(block: Sequence[Sequence[Piece]], node: Node, container: Node, builder: Builder) -> None:
    for line in block:
        content = line[:-1] if line and line[-1][0] == "\n" else line
        newline = line[-1] if line and line[-1][0] == "\n" else None
        for piece in content:
            builder.span(node, *piece)
        if newline is not None:
            builder.span(container if line is block[-1] else node, *newline)


def _emit_report_table(
    block: Sequence[Sequence[Piece]], texts: Sequence[str], container: Node, builder: Builder
) -> None:
    """A ruled vote table: the rules stay as rule leaves, the aligned fields become cells.

    The gaps between columns and the newline that ends each row belong to the
    table, the way whitespace belongs to any container. Nothing is dropped, so
    the block's own text still concatenates to what the publisher sent.
    """
    table = Node("table", container, "markup", decision={"method": "rule", "rule": "gpo-fixed-pitch-ruled-table"})
    row_index = 0
    for index, (line, text) in enumerate(zip(block, texts, strict=True)):
        content = line[:-1] if line and line[-1][0] == "\n" else line
        newline = line[-1] if line and line[-1][0] == "\n" else None
        if _CRPT_RULE.match(text):
            rule = Node(
                "committee-report-html:rule",
                table,
                "markup",
                decision={"method": "rule", "rule": "gpo-fixed-pitch-rule-v1"},
            )
            for piece in content:
                builder.span(rule, *piece)
        else:
            row = Node("row", table, "markup", decision={"method": "rule", "rule": "gpo-fixed-pitch-row-v1"})
            column = 0
            for piece in content:
                for part in _split_piece(piece, _columns(piece[0])):
                    if part[0].strip():
                        cell = Node(
                            "cell", row, "markup", decision={"method": "rule", "rule": "gpo-fixed-pitch-column-v1"}
                        )
                        cell.cell = {"row": row_index, "column": column, "header": index == 1}
                        builder.span(cell, *part)
                        column += 1
                    else:
                        builder.span(row, *part)
            row_index += 1
        if newline is not None:
            builder.span(container if line is block[-1] else table, *newline)


# --- evidence-line renditions (PDF extraction, reconstruction) --------------------------


def block_source(block: Any) -> dict[str, Any]:
    if block.page is not None and block.box is not None:
        box = [round(v * 1000) for v in (block.box.x0, block.box.y0, block.box.x1, block.box.y1)]
        return {"coordinateSystem": "page-region", "page": block.page, "box": box, "line": block.line}
    if block.span is not None:
        return {"coordinateSystem": "utf8-byte", "start": block.span[0], "end": block.span[1], "literal": True}
    return dict(NONE)


def _run_italic(run: Any) -> bool:
    """Italic as the extractor flagged it, or as the font it named says.

    The CFR run-in headings carry ``MIonic-Italic`` with no italic flag, which
    the 2026-09-19 visual review found reported as ``italic: false`` beside an
    italic font name. The font name is the publisher's own evidence; reading it
    is not a guess.
    """
    return bool(run.italic) or bool(run.font and "italic" in run.font.lower())


def block_style(block: Any) -> dict[str, Any] | None:
    """What the extractor observed about one line's type, and nothing it did not.

    ``bold`` and ``italic`` are stated only when every run of the line agrees.
    A line that mixes an italic run-in heading with roman text has no single
    answer, and writing ``false`` there asserted something the line denies; the
    ``font`` list already shows the mixture.
    """
    runs = [run for run in block.runs if run.text.strip()]
    if not runs or all(run.font is None and run.size is None for run in runs):
        return None
    style: dict[str, Any] = {}
    for key, observed in (("bold", [bool(r.bold) for r in runs]), ("italic", [_run_italic(r) for r in runs])):
        if len(set(observed)) == 1:
            style[key] = observed[0]
    if block.size is not None:
        style["size"] = block.size
    if block.fonts:
        style["font"] = ", ".join(block.fonts)
    return style


def read_page_sizes(path: Path | None, pdf_sha256: str) -> dict[int, dict[str, Any]]:
    """The displayed size of each PDF page, in points, from the retained sidecar.

    ``evidence_from_pages`` keeps each line's box in permille of the displayed
    page and drops the page size that produced it, so the points a PDF
    fragment identifier needs cannot be recovered from the evidence document
    alone. The sidecar retains them beside the evidence, pinned to the PDF
    digest, rather than reaching for the PDF at capture time.
    """
    if path is None or not path.exists():
        return {}
    record = json.loads(path.read_text())
    if record["pdfSha256"] != pdf_sha256 or record["unit"] != "point":
        raise ValueError(f"{path.name} does not describe this PDF in points")
    return {p["page"]: {"width": p["width"], "height": p["height"], "unit": "point"} for p in record["pages"]}


def lines_to_pages(
    evidence: Any,
    builder: Builder,
    derivation: str,
    sizes: Mapping[int, dict[str, Any]] | None = None,
    classify: Callable[[Node, Any, list[Any]], None] | None = None,
) -> dict[int, Node]:
    """One ``page`` per extractor page, one ``line`` leaf per block; separators go to the container.

    A block whose text is only whitespace gets no node: its text belongs to the
    page container, which is where a capture puts a separator. Making it a
    ``line`` leaf claimed the print showed a line where it shows nothing -- 77
    of the slip opinion's 237 lines, ordered before the real ones, so ``line``
    ordinals did not match printed line numbers either.
    """
    document = builder.root
    pages: dict[int, Node] = {}
    lines: dict[int, list[tuple[Node, Any]]] = {}
    previous: Any = None
    for block in evidence.blocks:
        page = pages.get(block.page)
        if page is None:
            if previous is not None:
                builder.span(document, "\f", NONE)
            page = pages[block.page] = Node(
                "page",
                document,
                derivation,
                container=True,
                designation=str(block.page),
                page_size=(sizes or {}).get(block.page),
                source={"coordinateSystem": "page-region", "page": block.page, "box": [0, 0, 1000, 1000]},
                decision={"method": "generated", "rule": "extractor-page-container-v1"},
            )
            lines[block.page] = []
        elif previous is not None:
            builder.span(page, "\n", NONE)
        previous = block
        if not block.text:
            continue
        if not block.text.strip():
            builder.span(page, block.text, block_source(block))
            continue
        leaf = Node(
            "line",
            page,
            derivation,
            source=block_source(block),
            decision={"method": "rule", "rule": "retained-evidence-block-to-line-v1"},
        )
        builder.span(leaf, block.text, block_source(block), style=block_style(block))
        lines[block.page].append((leaf, block))
    if classify is not None:
        for number, page in pages.items():
            classify(page, number, lines[number])
    return pages


# --- validation and round trip ---------------------------------------------------


def validators() -> tuple[Draft202012Validator, dict[str, Draft202012Validator], Draft202012Validator]:
    parent = load_schema(PARENT_SCHEMA)
    registry = Registry().with_resource(parent["$id"], Resource.from_contents(parent))
    profiles = {}
    for path in sorted(SCHEMAS.joinpath("profiles").iterdir()):
        schema = json.loads(path.read_text(encoding="utf-8"))
        name = schema["allOf"][1]["properties"]["profile"]["properties"]["name"]["const"]
        profiles[name] = Draft202012Validator(schema, registry=registry)
    return (
        Draft202012Validator(parent, registry=registry),
        profiles,
        Draft202012Validator(load_schema("rulespec/source-fragment.schema.json")),
    )


def check_profile_composition(profile: Mapping[str, Any], parent: Mapping[str, Any]) -> list[str]:
    """Validate a profile against the meta-schema, then the two bindings a schema cannot state.

    Rulespec states the composition rule as data
    (``document-capture-profile-v1.schema.json``, vendored beside the parent),
    so the shape is checked by the same JSON Schema implementation that checks
    a capture. Only the values that must agree with something outside the
    clause -- the parent's bytes, and the profile's own name inside its kind
    patterns -- are code, and that code is Rulespec's too.
    """
    meta = Draft202012Validator(load_schema(PROFILE_META_SCHEMA))
    problems = [e.message for e in meta.iter_errors(profile)]
    return problems + rulespec_invariants().check_profile_bindings(
        profile, parent_id=parent["$id"], parent_digest=sha256(SCHEMAS.joinpath(PARENT_SCHEMA).read_bytes())
    )


def check_invariants(capture: Mapping[str, Any]) -> list[str]:
    """The invariants JSON Schema cannot see, checked by Rulespec's own validator."""
    return rulespec_invariants().check_invariants(capture, parent_schema=load_schema(PARENT_SCHEMA))


class _StdlibText(HTMLParser):
    """Character data inside the root element, the way the normalization statement bounds it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.root: str | None = None
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.root = self.root or tag

    def handle_endtag(self, tag: str) -> None:
        self.done = self.done or tag == self.root

    def handle_data(self, data: str) -> None:
        if self.root is not None and not self.done:
            self.parts.append(data)


def independent_text(rendition: str, artifact: bytes, evidence_json: Mapping[str, Any] | None) -> tuple[str, str]:
    """Re-derive the text stream with another implementation, so the round trip is not a self-check.

    XML: libxml2 through lxml, against the reader's expat. HTML: the standard
    library's HTMLParser with its own character-reference decoding, against
    the reader's hand-decoded references on the same tokenizer; libxml2's HTML
    parser drops inter-element whitespace and so cannot witness a
    whitespace-exact stream. Evidence lines: the retained JSON rejoined.
    """
    if rendition == "xml":
        from lxml import etree  # ty: ignore[unresolved-import]

        parser = etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True, remove_comments=True, remove_pis=True
        )
        return "".join(etree.fromstring(artifact, parser).itertext()), "lxml.etree (libxml2) itertext"
    if rendition == "html":
        parser = _StdlibText()
        parser.feed(artifact.decode("utf-8"))
        parser.close()
        return "".join(parser.parts), "html.parser.HTMLParser(convert_charrefs=True) handle_data"
    assert evidence_json is not None
    out: list[str] = []
    page = None
    for block in evidence_json["blocks"]:
        if page is not None:
            out.append("\n" if block.get("page") == page else "\f")
        page = block.get("page")
        out.append(block["text"])
    return "".join(out), "json: evidence blocks rejoined by page"


# --- rulespec SourceFragment rendering --------------------------------------------


def contiguous_runs(
    capture: Mapping[str, Any], node: Mapping[str, Any], span_by_id: Mapping[str, Mapping[str, Any]]
) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for span_id in node["evidence"]:
        span = span_by_id[span_id]
        if runs and runs[-1][1] == span["start"]:
            runs[-1] = (runs[-1][0], span["end"])
        else:
            runs.append((span["start"], span["end"]))
    return runs


XPATH_STEP = re.compile(r"/([^/\[]+)\[(\d+)\]")


def resolvable_xpath(path: str) -> str:
    """Rewrite a recorded element path into one that selects with no namespace context.

    A capture carries an ``oa:XPathSelector`` as a string and has nowhere to
    declare a prefix binding, so ``/pLaw[1]`` selects nothing against a
    default-namespaced USLM document and ``/bill[1]/dc:title[1]`` raises an
    undefined-prefix error. ``element_tree`` already counts siblings by local
    name, so every index here is the one this form computes.
    """
    return XPATH_STEP.sub(lambda m: f"/*[local-name()='{m.group(1).rpartition(':')[2]}'][{m.group(2)}]", path)


def enclosing_identifier(by_id: Mapping[str, Mapping[str, Any]], node: Mapping[str, Any]) -> str | None:
    """The publisher's identifier on this node or its nearest ancestor (a USLM ``identifier`` attribute)."""
    current: Mapping[str, Any] | None = node
    while current is not None:
        if (current.get("ext") or {}).get("identifier"):
            return current["ext"]["identifier"]
        current = by_id[current["parent"]] if current["parent"] else None
    return None


def byte_runs(sources: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Merge adjacent byte ranges; never collapse disjoint ones into their hull.

    A leaf whose text is interrupted by markup has several byte runs. One
    selector from the minimum start to the maximum end would select the markup
    between them, so the position selector and the content digest would
    describe different regions -- the defect the 2026-09-19 review found on a
    USLM short-title leaf, where 93 bytes of markup stood for 57 bytes of text.
    """
    runs: list[tuple[int, int]] = []
    for source in sorted(sources, key=lambda s: (s["start"], s["end"])):
        if runs and runs[-1][1] == source["start"]:
            runs[-1] = (runs[-1][0], source["end"])
        else:
            runs.append((source["start"], source["end"]))
    return runs


def page_sizes(capture: Mapping[str, Any]) -> dict[int, tuple[float, float]]:
    """Every retained page size in points, keyed by the extractor's page number.

    A family whose tree has ``page`` nodes carries the size there, which is
    where the parent puts it. A reconstruction's tree has no page node -- its
    units are the publisher's, and a page is a coordinate rather than a
    container -- so that family states the same sizes in its own ``profile.ext``
    and this reads both.
    """
    out = {}
    for entry in (capture["profile"].get("ext") or {}).get("pageSizes") or ():
        if isinstance(entry, Mapping):
            out[entry["page"]] = (entry["width"], entry["height"])
    for node in capture["nodes"]:
        size, page = node.get("pageSize"), (node.get("source") or {}).get("page")
        if size and page is not None:
            out[page] = (size["width"], size["height"])
    return out


def region_selector(region: Mapping[str, Any], sizes: Mapping[int, tuple[float, float]]) -> dict[str, Any]:
    """One page region as a fragment identifier, in the unit the identifier's own definition names.

    RFC 8118 states ``viewrect`` in the default user space unit, 1/72 inch,
    and addresses ``application/pdf``. A capture stores boxes in integer
    permille because permille integers are admissible to canonical identity
    JSON; the page's retained ``pageSize`` converts one to the other. A page
    whose size was not retained gets an ``rkaf:partner-defined`` selector
    whose value states the permille rule, rather than an RFC 8118 conformance
    claim in a unit the RFC does not use.
    """
    x0, y0, x1, y1 = region["box"]
    size = sizes.get(region["page"])
    if size is None:
        return {
            "@type": "oa:FragmentSelector",
            "rkaf:fragmentIdentityScheme": "rkaf:partner-defined",
            "rdf:value": (
                f"page={region['page']}&box={x0},{y0},{x1},{y1}"
                ";unit=permille of the displayed page, top-left origin, x0,y0,x1,y1"
            ),
        }
    width, height = size
    to_x = lambda v: round(v * width / 1000, 2)
    to_y = lambda v: round(v * height / 1000, 2)
    return {
        "@type": "oa:FragmentSelector",
        "dcterms:conformsTo": "https://www.rfc-editor.org/rfc/rfc8118",
        "rdf:value": (
            f"page={region['page']}&viewrect={to_x(x0)},{to_y(y0)},"
            f"{round(to_x(x1) - to_x(x0), 2)},{round(to_y(y1) - to_y(y0), 2)}"
        ),
    }


def leaf_fragments(
    capture: Mapping[str, Any],
    node: Mapping[str, Any],
    span_by_id: Mapping[str, Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]] | None = None,
    sizes: Mapping[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Two fragments for one leaf: one into the text stream, one into the publisher's artifact."""
    by_id = by_id if by_id is not None else {n["id"]: n for n in capture["nodes"]}
    sizes = sizes if sizes is not None else page_sizes(capture)
    runs = contiguous_runs(capture, node, span_by_id)
    text = node_text(capture, node, span_by_id)
    stream_iri = capture["rendition"]["textStream"]["iri"]
    position = [
        {
            "@type": "oa:TextPositionSelector",
            "oa:start": s,
            "oa:end": e,
            "rkaf:coordinateSystem": "rkaf:unicode-codepoint",
        }
        for s, e in runs
    ]
    stream = {
        "@type": "rkaf:SourceFragment",
        "oa:hasSource": stream_iri,
        "oa:hasSelector": [*position, {"@type": "oa:TextQuoteSelector", "oa:exact": text}],
        "rkaf:selectorKind": ["oa:TextPositionSelector", "oa:TextQuoteSelector"],
        "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
        "rkaf:sourceArtifactDigest": "sha256:" + capture["rendition"]["textStream"]["sha256"],
        "rkaf:fragmentContentDigest": "sha256:" + sha256(text),
    }
    urn = None
    if len(runs) == 1:
        encoded = urllib.parse.quote(stream_iri, safe="-._~")
        urn = f"urn:rkaf:fragment:{encoded}:{runs[0][0]}:{runs[0][1]}:sha256-{sha256(text)}"
    source = node["source"] if "source" in node else dict(NONE)
    owned = [effective_source(capture, span_by_id[s]) for s in node["evidence"]]
    selectors: list[dict[str, Any]] = []
    kinds: list[str] = []
    if source.get("coordinateSystem") == "xml-node-path":
        selectors.append({"@type": "oa:XPathSelector", "rdf:value": resolvable_xpath(source["path"])})
        kinds.append("oa:XPathSelector")
        identifier = enclosing_identifier(by_id, node)
        if identifier and capture["profile"]["name"] == "uslm-law":
            # Names the enclosing USLM unit; the position and quote selectors narrow within it.
            selectors.append({"@type": "rkaf:uslm-section", "rdf:value": identifier})
            kinds.append("rkaf:uslm-section")
    regions = [source] if source.get("coordinateSystem") == "page-region" and "box" in source else []
    regions = regions or [s for s in owned if s.get("coordinateSystem") == "page-region" and "box" in s]
    for region in regions:  # one fragment identifier per printed line the leaf rests on
        selectors.append(region_selector(region, sizes))
    if regions:
        kinds.append("oa:FragmentSelector")
    byte_spans = [s for s in owned if s.get("coordinateSystem") == "utf8-byte"]
    for start, end in byte_runs(byte_spans):
        selectors.append(
            {
                "@type": "oa:TextPositionSelector",
                "oa:start": start,
                "oa:end": end,
                "rkaf:coordinateSystem": "rkaf:utf8-byte",
            }
        )
    if byte_spans:
        kinds.append("oa:TextPositionSelector")
    selectors.append({"@type": "oa:TextQuoteSelector", "oa:exact": text})
    kinds.append("oa:TextQuoteSelector")
    rendition = {
        "@type": "rkaf:SourceFragment",
        "oa:hasSource": capture["artifact"]["iri"],
        "oa:hasSelector": selectors,
        "rkaf:selectorKind": kinds,
        "rkaf:fragmentIdentityScheme": "rkaf:published-fragment",
        "rkaf:sourceArtifactDigest": "sha256:" + capture["artifact"]["sha256"],
        "rkaf:fragmentContentDigest": "sha256:" + sha256(text),
    }
    return {
        "node": node["id"],
        "kind": node["kind"],
        "streamFragment": stream,
        "carrierLocalFragmentUrn": urn,
        "renditionFragment": rendition,
    }


def validate_fragments(fragments: Sequence[Mapping[str, Any]], validator: Draft202012Validator) -> list[str]:
    schema = validator.schema
    defs = {
        name: Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}) for name in schema["$defs"]
    }
    problems = []
    for entry in fragments:
        for key in ("streamFragment", "renditionFragment"):
            fragment = entry[key]
            problems += [f"{entry['node']} {key}: {e.message}" for e in defs["SourceFragment"].iter_errors(fragment)]
            for selector in fragment["oa:hasSelector"]:
                name = selector["@type"].removeprefix("oa:")
                if name in defs:
                    problems += [f"{entry['node']} {key} {name}: {e.message}" for e in defs[name].iter_errors(selector)]
            for kind in fragment["rkaf:selectorKind"]:
                if kind not in schema["$defs"]["SelectorKind"]["enum"]:
                    problems.append(f"{entry['node']} {key}: selector kind {kind} is not in rkaf's enum")
    return problems


# --- families ----------------------------------------------------------------


USLM = Grammar(
    name="uslm-law",
    containers={
        "meta": "metadata",
        "preface": "frontMatter",
        "main": "body",
        "signatures": "backMatter",
        "section": "section",
        "subsection": "paragraph",
        "paragraph": "paragraph",
        "subparagraph": "paragraph",
        "clause": "paragraph",
        "subclause": "paragraph",
        "item": "paragraph",
        "quotedContent": "quote",
        "amendingAction": "uslm-law:amendingAction",
        "note": "note",
        "sidenote": "uslm-law:sidenote",
        "longTitle": "title",
        "toc": "uslm-law:toc",
        "legislativeHistory": "backMatter",
    },
    leaves={
        "heading": "heading",
        "num": "label",
        "content": "paragraph",
        "chapeau": "paragraph",
        "p": "paragraph",
        "continuation": "paragraph",
        "proviso": "paragraph",
        "docTitle": "title",
        "officialTitle": "title",
        "enactingFormula": "uslm-law:enactingFormula",
        "sourceCredit": "uslm-law:sourceCredit",
    },
    furniture={"page": "pageNumber", "centerRunningHead": "runningHead"},
    inline=frozenset({"ref", "inline", "quotedText", "date", "term", "b", "i", "span", "shortTitle", "def", "br"}),
)

BILL = Grammar(
    name="bill-xml",
    containers={
        "dublinCore": "metadata",
        "form": "frontMatter",
        "legis-body": "body",
        "resolution-body": "body",
        "amendment-block": "body",
        "attestation": "backMatter",
        "attestation-group": "bill-xml:attestationGroup",
        "section": "section",
        "subsection": "paragraph",
        "paragraph": "paragraph",
        "subparagraph": "paragraph",
        "clause": "paragraph",
        "subclause": "paragraph",
        "item": "paragraph",
        "title": "division",
        "subtitle": "division",
        "division": "division",
        "chapter": "division",
        "part": "division",
        "quoted-block": "quote",
        "toc": "bill-xml:toc",
    },
    leaves={"enum": "label", "header": "heading", "text": "paragraph", "official-title": "title"},
    inline=frozenset(
        {"quote", "external-xref", "internal-xref", "term", "italic", "bold", "sponsor", "cosponsor", "linebreak"}
    ),
)


def _fr_heading_level(elem: Elem) -> int | None:
    source = elem.attributes.get("SOURCE") or ""
    if source == "HED":
        return 1
    return int(source[2:]) if source.startswith("HD") and source[2:].isdigit() else None


FEDERAL_REGISTER = Grammar(
    name="federal-register-xml",
    containers={
        "PREAMB": "frontMatter",
        "SUPLINF": "body",
        "AGY": "section",
        "ACT": "section",
        "SUM": "section",
        "DATES": "section",
        "ADD": "section",
        "FURINF": "section",
        "GPOTABLE": "table",
        "BOXHD": "row",
        "ROW": "row",
        "FTNT": "footnote",
        "NOTE": "note",
        "EXTRACT": "quote",
        "SIG": "signature",
        "LSTSUB": "federal-register-xml:listOfSubjects",
        "REGTEXT": "federal-register-xml:regText",
    },
    leaves={
        "HD": "heading",
        "P": "paragraph",
        "FP": "paragraph",
        "AMDPAR": "paragraph",
        "SUBJECT": "title",
        "TTITLE": "title",
        "CHED": "cell",
        "ENT": "cell",
    },
    furniture={"PRTPAGE": "pageNumber"},
    inline=frozenset({"E", "SU", "FTREF", "LI"}),
    heading_level=_fr_heading_level,
)

_CRPT_PAGE = re.compile(r"^\s*\[\[Page (\S+)\]\]\s*$")
_CRPT_BANNER = re.compile(
    r"^\s*\[(House|Senate) Report [0-9]+-[0-9]+\]\s*$|^\s*\[From the U\.S\. Government Publishing Office\]\s*$"
)
_CRPT_RULE = re.compile(r"^\s*[=_-]{5,}\s*$")
#: The Rules Committee sets each record vote's number as a run-in italic head.
_CRPT_VOTE_HEAD = re.compile(r"^Rules Committee record vote No\. [0-9]+$")
#: Two or more spaces separate columns in a GPO fixed-pitch table; a cell never
#: contains one, because names are filled to the column edge with dot leaders.
#: The group captures the gap, so a split keeps every character of the line.
_CRPT_COLUMN_GAP = re.compile(r"(\s{2,})")


def classify_report_line(line: str) -> tuple[str, str | None]:
    if match := _CRPT_PAGE.match(line):
        return "pageNumber", match.group(1)
    if _CRPT_BANNER.match(line):
        return "committee-report-html:banner", None
    if _CRPT_RULE.match(line):
        return "committee-report-html:rule", None
    return "paragraph", None


def report_heading_level(lines: Sequence[str]) -> tuple[int, str] | None:
    """A committee report's headings, by the two typographic rules the print states.

    The `<pre>` rendition keeps the typesetting: a section head is centred and
    set in capitals, and a record-vote head is set on its own line in italic.
    Neither is markup, so both are ``derivation: markup`` with the rule named.
    The design record says which of the visual review's two findings this
    closes and which it declines.
    """
    if len(lines) != 1:
        return None
    text = lines[0].strip()
    if not text:
        return None
    if any(c.isalpha() for c in text) and not any(c.islower() for c in text):
        return 1, "centred-capitals"
    if _CRPT_VOTE_HEAD.match(text):
        return 2, "rules-committee-record-vote-head"
    return None


def report_table(lines: Sequence[str]) -> list[list[str]] | None:
    """A ruled, column-aligned vote table, or ``None`` when the columns are not unambiguous.

    The print rules a line above the header, below the header and below the
    body, and the `<pre>` keeps those rules as runs of hyphens. Between them the
    columns are separated by two or more spaces and never contain one. A block
    whose rows split into more fields than the header has is refused here and
    stays a paragraph with an issue, because a table read wrongly is worse than
    a table not read.
    """
    rules = [i for i, line in enumerate(lines) if _CRPT_RULE.match(line)]
    if len(rules) != 3 or rules[0] != 0 or rules[2] != len(lines) - 1 or rules[1] != 2:
        return None
    header = [c for c in _CRPT_COLUMN_GAP.split(lines[1].strip()) if c.strip()]
    if len(header) < 2:
        return None
    rows = [header]
    for line in lines[3:-1]:
        cells = [c for c in _CRPT_COLUMN_GAP.split(line.strip()) if c.strip()]
        if not cells or len(cells) > len(header):
            return None
        rows.append(cells)
    return rows


CFR_KIND_MAP = {
    "section": "section",
    "section_number": "label",
    "subject": "heading",
    "paragraph": "paragraph",
    "flush_paragraph": "cfr-reconstruction:flushParagraph",
    "heading": "heading",
    "citation": "cfr-reconstruction:cita",
    "note": "note",
    "page_number": "pageNumber",
    "running_head": "runningHead",
    "print_footer": "printFooter",
    "blank": "cfr-reconstruction:blank",
    "part_heading": "cfr-reconstruction:partHeading",
    "division_heading": "heading",
    "contents": "cfr-reconstruction:contents",
    "authority": "cfr-reconstruction:authority",
    "source_note": "cfr-reconstruction:sourceNote",
}


# --- slip opinion: the opinion division the print marks three ways -------------------

#: The running-head band, as a fraction of the displayed page height. Every page
#: of this print sets the page number and the case line at y 144 permille and the
#: opinion designator at 174; the body starts at 197. Fixed geometry, not a corpus.
SLIP_HEAD_BAND = 190

_SLIP_DESIGNATOR = re.compile(
    r"^(?P<author>[A-Z][A-Za-z.\u2019' -]*?), (?P<role>J\.|JJ\.), (?P<type>concurring|dissenting)"
    r"(?: in part)?(?:.*)$|^(?P<plain>Per Curiam|Syllabus|Opinion of the Court|"
    r"Opinion of [A-Z][A-Za-z.\u2019' -]*, J\.)$"
)
_SLIP_FORMULA = re.compile(
    r"^(?:(?P<percuriam>PER CURIAM)\.|(?:JUSTICE|CHIEF JUSTICE) (?P<author>[A-Z][A-Za-z\u2019'-]*)"
    r"(?:, with whom (?P<joined>.+?),)?[, ]*(?P<type>delivered the opinion of the Court|concurring"
    r"(?: in the judgment)?|dissenting)(?: in part)?\.)$"
)
#: The designator line names the opinion; this maps it to the profile's kind.
SLIP_KINDS = {
    "syllabus": "slip-opinion-pdf:syllabus",
    "percuriam": "slip-opinion-pdf:perCuriam",
    "opinion": "slip-opinion-pdf:opinion",
    "concurring": "slip-opinion-pdf:concurrence",
    "dissenting": "slip-opinion-pdf:dissent",
}


def slip_designator(text: str) -> tuple[str, str | None] | None:
    """Read the opinion designator the print sets at the head of every page.

    Returns the opinion type and its author, or ``None`` when the line is not a
    designator. The three signals the print gives -- this line, the opening
    formula, and the restart of the printed page number -- are read separately
    and compared; a disagreement is an issue, never a guess.
    """
    match = _SLIP_DESIGNATOR.match(text.strip())
    if match is None:
        return None
    if plain := match.group("plain"):
        if plain == "Per Curiam":
            return "percuriam", None
        if plain == "Syllabus":
            return "syllabus", None
        return "opinion", plain.removeprefix("Opinion of ").removesuffix(", J.") if "Opinion of " in plain else None
    return match.group("type").split()[0], match.group("author")


def slip_formula(text: str) -> tuple[str, str | None, str | None] | None:
    """Read the opening formula: ``PER CURIAM.``, ``JUSTICE JACKSON, dissenting.``"""
    match = _SLIP_FORMULA.match(text.strip())
    if match is None:
        return None
    if match.group("percuriam"):
        return "percuriam", None, None
    kind = "opinion" if "delivered" in (match.group("type") or "") else match.group("type").split()[0]
    return kind, match.group("author"), match.group("joined")


def classify_slip_page(page: Node, number: int, lines: Sequence[tuple[Node, Any]]) -> None:
    """Separate the page furniture the print repeats from the body, and read the designator.

    The running-head band is the fixed geometry above; inside it the leading
    integer run is the printed page number and the rest is the running head. The
    designator line sits in the same band and is kept as a running head too,
    because the print repeats it on every page of the opinion, with the opinion
    it names recorded in ``ext`` for the opinion pass to read.
    """
    printed: str | None = None
    for leaf, block in lines:
        if block.box is None or round(block.box.y0 * 1000) >= SLIP_HEAD_BAND:
            continue
        text = leaf.text
        digits = re.match(r"^\s*(\d+)\s*$", text)
        if digits is not None:
            leaf.kind, leaf.designation, printed = "pageNumber", digits.group(1), digits.group(1)
            leaf.decision = {"method": "rule", "rule": "head-band-page-number"}
            leaf.derivation = "reconstructed"
            continue
        if (designator := slip_designator(text)) is not None:
            leaf.kind = "runningHead"
            leaf.derivation = "reconstructed"
            leaf.decision = {"method": "rule", "rule": "head-band-opinion-designator"}
            leaf.ext = {"opinionType": designator[0], **({"author": designator[1]} if designator[1] else {})}
            continue
        leaf.kind, leaf.derivation = "runningHead", "reconstructed"
        leaf.decision = {"method": "rule", "rule": "head-band-running-head"}
        merged = re.match(r"^\s*(\d+)\s+(\S.*)$", text)
        if merged is not None and len(block.runs) > 1 and block.runs[0].text.strip() == merged.group(1):
            # The print sets the page number and the case line on one baseline;
            # the extractor kept them as two runs, so they split without guessing.
            leaf.issues.append({"code": "page-number-merged-into-running-head", "detail": merged.group(1)})
            printed = printed or merged.group(1)
    if printed is not None:
        page.ext = {"pdfOrdinal": number}
        page.designation = printed
    else:
        page.ext = {"pdfOrdinal": number}
        page.issues.append({"code": "printed-page-number-not-found", "detail": f"pdf page {number}"})


def group_slip_opinions(pages: Mapping[int, Node], builder: Builder) -> list[dict[str, Any]]:
    """Wrap each opinion's pages in a container named by the print's own three signals.

    A new opinion begins where the designator changes, and the opening formula
    on that page must agree with it. Where the two disagree, or where the
    printed page number does not restart, the container records an issue and
    keeps the designator's answer rather than inventing one.
    """
    document = builder.root
    order = sorted(pages)
    groups: list[tuple[dict[str, Any], list[int]]] = []
    for number in order:
        page = pages[number]
        designator = next(
            (
                child.ext
                for child in page.children
                if child.kind == "runningHead" and (child.ext or {}).get("opinionType")
            ),
            None,
        )
        formula = next(
            (slip_formula(child.text) for child in page.children if child.kind == "line" and slip_formula(child.text)),
            None,
        )
        opened = formula is not None
        if not groups or (opened and designator != groups[-1][0]):
            groups.append((designator or {"opinionType": "opinion"}, []))
            if designator is None:
                builder.issues.append(
                    {"code": "slip-opinion-unlabelled", "detail": f"page {number} opens an opinion with no designator"}
                )
            elif formula is not None and formula[0] != designator.get("opinionType"):
                builder.issues.append(
                    {
                        "code": "slip-opinion-signals-disagree",
                        "detail": f"page {number}: designator {designator.get('opinionType')}, formula {formula[0]}",
                    }
                )
            if formula is not None and formula[2]:
                groups[-1][0]["joinedBy"] = formula[2]
        groups[-1][1].append(number)
    records = []
    document.children.clear()
    for ext, numbers in groups:
        kind = SLIP_KINDS[ext.get("opinionType", "opinion")]
        first, last = pages[numbers[0]], pages[numbers[-1]]
        opinion = Node(
            kind,
            document,
            "reconstructed",
            container=True,
            decision={"method": "rule", "rule": "slip-opinion-designator-and-opening-formula"},
            ext={
                **{k: v for k, v in ext.items() if k in ("author", "joinedBy")},
                "pageRange": {
                    "firstPrinted": first.designation,
                    "lastPrinted": last.designation,
                    "firstPdfPage": numbers[0],
                    "lastPdfPage": numbers[-1],
                },
            },
        )
        for number in numbers:
            pages[number].parent = opinion
            opinion.children.append(pages[number])
        records.append({"kind": kind, "pages": numbers, **(opinion.ext or {})})
    return records


def check_page_designations(pages: Sequence[Node], builder: Builder, pattern: str) -> None:
    """Printed page designations run unique and increasing; a repeat is the publisher's error.

    GovInfo's USLM for Public Law 119-1 labels its four page markers STAT. 3, 4,
    4, 5 where the print runs 3 through 6. The capture stays faithful to the
    bytes and says so here, rather than passing the error on silently.
    """
    seen: dict[str, Node] = {}
    previous = None
    for node in pages:
        match = re.match(pattern, node.designation or "")
        if match is None:
            continue
        value = int(match.group(1))
        if (node.designation or "") in seen:
            node.issues.append(
                {"code": "page-designation-repeated", "detail": f"{node.designation} also labels an earlier page"}
            )
        elif previous is not None and value <= previous:
            node.issues.append({"code": "page-designation-not-increasing", "detail": node.designation or ""})
        seen[node.designation or ""] = node
        previous = value


def wrap_children(parent: Node, kind: str, derivation: str, chosen: Sequence[Node]) -> Node | None:
    """Put a contiguous run of a parent's trailing children inside a new container, in place."""
    if not chosen:
        return None
    index = parent.children.index(chosen[0])
    container = Node(
        kind,
        parent,
        derivation,
        container=True,
        decision={"method": "generated", "rule": "trailing-source-elements-wrapper-v1"},
    )
    for child in chosen:
        parent.children.remove(child)
        child.parent = container
        container.children.append(child)
    parent.children.remove(container)
    parent.children.insert(index, container)
    return container


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def converter_record(family: str, extra: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
    deps = [("python", sys.version.split()[0]), ("spicy-docs", importlib.metadata.version("spicy-docs")), *extra]
    deps.append(
        (
            "document_capture_sources.py",
            "sha256:" + sha256(Path(__file__).with_name("document_capture_sources.py").read_bytes()),
        )
    )
    return {
        "id": f"spicy-docs/tools/analysis/document_capture.py#{family}",
        "version": CONVERTER_VERSION,
        "implementation": {
            "repository": "spicy-docs",
            "revision": _git_revision(),
            "fileSha256": sha256(Path(__file__).read_bytes()),
        },
        "dependencies": [{"name": n, "version": v} for n, v in deps],
    }


#: When each retained fixture was read, to the precision its own README states.
#: A date is what those records hold; the two receipted fetches hold a second.
FIXTURE_RETRIEVED = {
    "tests/fixtures/uslm/README.md": "2026-09-14",
    "tests/fixtures/govinfo_bills/README.md": "2026-09-12",
    "tests/fixtures/govinfo_bodies/README.md": "2026-09-19",
    "tests/fixtures/reconstruction/cfr/README.md": "2026-09-19",
}


def artifact_record(
    digest: str,
    byte_size: int,
    media_type: str,
    locator: Mapping[str, Any],
    identifiers: Sequence[tuple[str, str]],
    retrieved: str | None,
) -> dict[str, Any]:
    """The publisher's own bytes, always: the digest here is what locator.url serves."""
    out: dict[str, Any] = {
        "iri": f"urn:document-capture:artifact:sha256:{digest}",
        "sha256": digest,
        "byteSize": byte_size,
        "mediaType": media_type,
        "locator": dict(locator),
        "identifiers": [
            {"scheme": "rkaf:hash-sha256", "value": f"sha256:{digest}"},
            *({"scheme": s, "value": v} for s, v in identifiers),
        ],
    }
    if retrieved:
        out["retrievedAt"] = retrieved
    return out


def read_artifact(
    path: Path,
    media_type: str,
    locator: Mapping[str, Any],
    identifiers: Sequence[tuple[str, str]],
    retrieved: str | None,
) -> dict[str, Any]:
    """An artifact whose bytes are the retained file itself: every markup rendition."""
    data = path.read_bytes()
    return artifact_record(sha256(data), len(data), media_type, locator, identifiers, retrieved)


def intermediate_record(path: Path, media_type: str, producer: str) -> dict[str, Any]:
    """The extractor document between a PDF and the text stream.

    Its digest is not the artifact's: the capture says PDF, then extractor
    output, then text stream, and names each once. Before the 2026-09-19
    review the two PDF families put this file in the ``artifact`` slot while
    ``locator.url`` still pointed at the PDF, so a consumer that followed the
    url and checked the digest found two different documents.
    """
    data = path.read_bytes()
    digest = sha256(data)
    return {
        "iri": f"urn:document-capture:intermediate:sha256:{digest}",
        "sha256": digest,
        "byteSize": len(data),
        "mediaType": media_type,
        "producer": producer,
        "locator": {"path": str(path.relative_to(ROOT))},
    }


NORMALIZATIONS = {
    "xml": (
        "markup-character-data",
        (
            "The decoded character data of every text event of spicy_docs.reading.markup in document order, inside the "
            "root element: entity and character references decoded, CDATA unwrapped; comments, processing instructions, "
            "declarations, and the prolog and epilog outside the root excluded; no whitespace changed. Reversible: each "
            "span carries the byte range of the artifact that produced it."
        ),
    ),
    "html": (
        "markup-character-data",
        (
            "The decoded character data of every text event of spicy_docs.reading.markup in document order, inside the "
            "root element, read with the tolerant HTML grammar; otherwise the XML statement. Reversible by the retained "
            "byte ranges."
        ),
    ),
    "evidence-lines": (
        "evidence-lines-joined",
        (
            "Every block of the retained reconstruction.evidence.EvidenceDocument in order, the block text verbatim, "
            "consecutive blocks on one page joined by U+000A and a page change by U+000C. Reversible over the retained "
            "evidence document; that document's own relation to the PDF is the pinned extractor's, and each block records "
            "how many extractor fragments line assembly joined."
        ),
    ),
}


@dataclass
class Conversion:
    name: str
    family: str
    rendition: str
    artifact: dict[str, Any]
    converter: dict[str, Any]
    profile_ext: dict[str, Any]
    builder: Builder
    artifact_bytes: bytes
    evidence_json: dict[str, Any] | None = None
    intermediate: dict[str, Any] | None = None

    @property
    def stream_source(self) -> bytes:
        """The bytes the text stream is derived from: the intermediate when there is one."""
        return self.artifact_bytes

    def capture(self) -> dict[str, Any]:
        from tools.analysis.document_capture_sources import populate

        populate(self)
        nodes, stream = self.builder.finish()
        digest = sha256(stream)
        norm_id, statement = NORMALIZATIONS["evidence-lines" if self.intermediate else self.rendition]
        preimage = "\n".join(
            [self.artifact["sha256"], self.converter["id"], self.converter["version"], self.family, "1", digest]
        )
        spans = [span_json(s) for s in self.builder.spans]
        defaults = hoist_span_defaults(spans)
        return {
            "recordType": "DocumentCapture",
            "captureVersion": 1,
            "schema": schema_pin(PARENT_SCHEMA),
            "capture": {
                "id": f"urn:document-capture:sha256:{sha256(preimage)}",
                "capturedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                "idOrigin": "generated",
                "idScheme": "document-order",
            },
            "artifact": self.artifact,
            "rendition": {
                "kind": self.rendition,
                **({"intermediate": self.intermediate} if self.intermediate else {}),
                "spanDefaults": defaults,
                "textStream": {
                    "iri": f"urn:document-capture:text-stream:sha256:{digest}",
                    "sha256": digest,
                    "codePoints": len(stream),
                    "normalization": {"id": norm_id, "statement": statement, "reversible": True},
                },
            },
            "converter": self.converter,
            "profile": {
                "name": self.family,
                "version": "1",
                "schema": schema_pin(f"profiles/{self.family}.schema.json"),
                "ext": self.profile_ext,
            },
            "nodes": [node_json(n) for n in nodes],
            "evidence": spans,
            "unresolved": [
                {
                    "id": f"u{i:04d}",
                    "evidence": [s.id for s in r.spans],
                    "issue": r.issue,
                    "detail": r.detail,
                    "parent": None if r.parent is None else r.parent.id,
                }
                for i, r in enumerate(self.builder.regions, 1)
            ],
            "issues": self.builder.issues,
        }


def convert_markup(
    name: str,
    grammar: Grammar,
    data: bytes,
    rendition: str,
    artifact: dict[str, Any],
    *,
    ext: dict[str, Any] | None = None,
    deps: Sequence[tuple[str, str]] = (),
    external_doctype: bool = False,
) -> Conversion:
    read = (
        read_xml_events(data, allow_external_doctype=external_doctype) if rendition == "xml" else read_html_events(data)
    )
    tree = element_tree(read, data)
    root_elem = next(p for p in tree.parts if isinstance(p, Elem))
    builder = Builder(Node("document", None, grammar.derivation, container=True, source=locator(root_elem)))
    converter = MarkupConverter(grammar, builder)
    for part in tree.parts:
        if part is root_elem:
            converter.convert(part)
        elif isinstance(part, MarkupEvent) and part.text:
            builder.span(builder.root, part.text, text_source(part))
    return Conversion(
        name, grammar.name, rendition, artifact, converter_record(grammar.name, deps), ext or {}, builder, data
    )


def convert_uslm(path: Path) -> Conversion:
    from spicy_docs.sources.govinfo.uslm import PublicLawSelection, public_law_xml_locator, validate_public_law_xml

    data = path.read_bytes()
    selection = PublicLawSelection(119, "public", 1)
    meta = validate_public_law_xml(data, selection=selection, final_url=public_law_xml_locator(selection))
    member = json.loads((FIXTURES / "document_capture_provenance/public-law.json").read_bytes())["archiveMember"]
    if sha256(data) != member["sha256"] or len(data) != member["byteSize"]:
        raise ValueError("public-law fixture differs from the retained archive member")
    artifact = read_artifact(
        path,
        "application/xml",
        {
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "PLAW-119publ1",
        },
        [("rkaf:uslm", "/us/pl/119/1"), *(("rkaf:partner-defined", f"citableAs:{c}") for c in meta.citable_as)],
        member["archive"]["retrievedAt"],
    )
    ext = {
        "archiveMember": member,
        "source": meta.source,
        "title": meta.title,
        "docNumber": meta.doc_number,
        "congress": meta.congress,
        "citableAs": list(meta.citable_as),
        "approvedDate": meta.approved_date,
        "schemaLocation": meta.schema_location,
        "processedBy": meta.processed_by,
        "processedDate": meta.processed_date,
    }
    conversion = convert_markup("plaw-119publ1", USLM, data, "xml", artifact, ext=ext)
    printed: list[Node] = []
    for node in conversion.builder.nodes():
        attrs = node.source.get("attributes") or {}
        node_ext = {
            k: attrs[a]
            for k, a in (("identifier", "identifier"), ("role", "role"), ("numValue", "value"))
            if attrs.get(a)
        }
        if node_ext:
            node.ext = node_ext
        if node.kind == "pageNumber":
            printed.append(node)
    check_page_designations(printed, conversion.builder, r"^139 STAT\. (\d+)$")
    return conversion


def convert_bill(path: Path) -> Conversion:
    from spicy_docs.sources.congress.bill_tree import parse_bill_tree

    data = path.read_bytes()
    bill = parse_bill_tree(data, version="enr")
    artifact = read_artifact(
        path,
        "application/xml",
        {
            "url": "https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml",
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "BILLS-119hjres25enr",
        },
        [("rkaf:partner-defined", "govinfo:BILLS-119hjres25enr")],
        FIXTURE_RETRIEVED["tests/fixtures/govinfo_bills/README.md"],
    )
    engine_version = importlib.metadata.version("deltatrack")
    conversion = convert_markup(
        "bills-119hjres25enr", BILL, data, "xml", artifact, external_doctype=True, deps=[("deltatrack", engine_version)]
    )
    by_element_id = {n.element_id: n for n in bill.sections}
    joined: list[str] = []
    joined_ids: set[str] = set()
    for node in conversion.builder.nodes():
        engine = by_element_id.get((node.source.get("attributes") or {}).get("id") or "")
        if engine is not None:
            node.ext = {
                "matchPath": list(engine.match_path),
                "displayPath": list(engine.display_path),
                "tag": engine.tag,
                "elementId": engine.element_id,
                "sectionNumber": engine.section_number,
                "bodyIndex": engine.body_index,
            }
            joined.append(engine.element_id)
            joined_ids.add(engine.element_id)
    # A set, not the list: membership over the list made the join O(n^2).
    unjoined = [n for n in bill.sections if n.element_id not in joined_ids]
    conversion.profile_ext = {
        "rootTag": bill.root_tag,
        "bodyTags": list(bill.body_tags),
        "stage": bill.stage,
        "congress": bill.tree.congress,
        "billType": bill.tree.bill_type,
        "billNumber": bill.tree.bill_number,
        "version": bill.tree.version,
        "deltatrack": {
            "version": engine_version,
            "nodes": len(bill.sections),
            "joined": joined,
            "unjoined": [{"tag": n.tag, "elementId": n.element_id, "matchPath": list(n.match_path)} for n in unjoined],
        },
        "discardedElements": dict(bill.discarded_elements),
        "keptElements": dict(bill.kept_elements),
    }
    for engine in unjoined:
        conversion.builder.issues.append(
            {
                "code": "deltatrack-node-without-element",
                "detail": f"{engine.tag} {engine.element_id} is synthesized by the engine, not an element",
            }
        )
    return conversion


def convert_federal_register(xml_path: Path, json_path: Path, receipt: Mapping[str, Any]) -> Conversion:
    data = xml_path.read_bytes()
    document = json.loads(json_path.read_text())
    artifact = read_artifact(
        xml_path,
        "text/xml",
        {
            "url": receipt["url"],
            "path": str(xml_path.relative_to(ROOT)),
            "publisher": "Federal Register",
            "publisherId": document["document_number"],
        },
        [
            ("rkaf:partner-defined", f"federalregister:{document['document_number']}"),
            ("rkaf:urn-persistent", document["html_url"]),
        ],
        receipt["requestedAt"],
    )
    ext = {
        "documentNumber": document["document_number"],
        "type": document["type"],
        "publicationDate": document["publication_date"],
        "citation": document["citation"],
        "startPage": document["start_page"],
        "endPage": document["end_page"],
        "agencies": [a.get("name") for a in document["agencies"]],
        "documentJsonSha256": sha256(json_path.read_bytes()),
    }
    conversion = convert_markup("fr-2026-19200", FEDERAL_REGISTER, data, "xml", artifact, ext=ext)
    # Built once per table and once per row: reading a cell's geometry with
    # list.index() cost O(cells * (rows + columns)) for the same answer.
    index: dict[int, int] = {}
    for node in conversion.builder.nodes():
        if node.kind in ("table", "row"):
            for ordinal, child in enumerate(c for c in node.children if c.kind in ("row", "cell")):
                index[id(child)] = ordinal
    for node in conversion.builder.nodes():
        attrs = node.source.get("attributes") or {}
        if (
            node.kind == "cell"
            and node.parent is not None
            and node.parent.kind == "row"
            and node.parent.parent is not None
        ):
            row = node.parent
            node.cell = {
                "row": index[id(row)],
                "column": index[id(node)],
                "header": row.source.get("element") == "BOXHD",
            }
            node_ext = {k: v for k, v in (("headLevel", attrs.get("H")), ("indent", attrs.get("I"))) if v}
            if node_ext:
                node.ext = node_ext
        elif node.kind == "table":
            node.ext = {"cols": attrs.get("COLS"), "cdef": attrs.get("CDEF")}
    # FRDOC and BILCOD are the printed tail of the document and sat beside
    # frontMatter and body at the root; core backMatter is what names that, and
    # every family with printed back matter now uses it.
    root = conversion.builder.root
    tail = [c for c in root.children if (c.source.get("element") or "") in ("FRDOC", "BILCOD")]
    wrap_children(root, "backMatter", "native", tail)
    return conversion


def convert_committee_report(path: Path) -> Conversion:
    data = path.read_bytes()
    artifact = read_artifact(
        path,
        "text/html",
        {
            "url": "https://www.govinfo.gov/content/pkg/CRPT-119hrpt1/html/CRPT-119hrpt1.htm",
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "CRPT-119hrpt1",
        },
        [("rkaf:partner-defined", "govinfo:CRPT-119hrpt1")],
        FIXTURE_RETRIEVED["tests/fixtures/govinfo_bodies/README.md"],
    )
    tree = element_tree(read_html_events(data), data)
    html = next(p for p in tree.parts if isinstance(p, Elem))
    builder = Builder(Node("document", None, "native", container=True, source=locator(html)))
    grammar = Grammar(
        name="committee-report-html", containers={"body": "body"}, leaves={"title": "title"}, inline=frozenset()
    )
    converter = MarkupConverter(grammar, builder)
    for part in html.parts:
        if isinstance(part, Elem) and part.name == "body":
            body = Node("body", builder.root, "native", container=True, source=locator(part))
            for inner in part.parts:
                if isinstance(inner, Elem) and inner.name == "pre":
                    pre = Node(
                        "committee-report-html:preformatted", body, "native", container=True, source=locator(inner)
                    )
                    preformatted_blocks(
                        [p for p in inner.parts if isinstance(p, MarkupEvent)], pre, builder, classify_report_line
                    )
                else:
                    converter.part(inner, body, ())
        else:
            converter.part(part, builder.root, ())
    return Conversion(
        "crpt-119hrpt1",
        "committee-report-html",
        "html",
        artifact,
        converter_record("committee-report-html"),
        {"packageId": "CRPT-119hrpt1", "blockRule": "blank-line"},
        builder,
        data,
    )


def _split_shared_block(block_text: str, children: Sequence[tuple[Any, str]]) -> list[tuple[Any | None, str]] | None:
    """Locate each child's text in order inside one shared line; leftovers go to the parent."""
    out: list[tuple[Any | None, str]] = []
    cursor = 0
    for child, text in children:
        at = block_text.find(text, cursor)
        if at < 0 or not text:
            return None
        if at > cursor:
            out.append((None, block_text[cursor:at]))
        out.append((child, text))
        cursor = at + len(text)
    if cursor < len(block_text):
        out.append((None, block_text[cursor:]))
    return out


def convert_cfr(evidence_path: Path, provenance: Mapping[str, Any], pages_path: Path | None = None) -> Conversion:
    from spicy_docs.reconstruction.evidence import EvidenceDocument
    from spicy_docs.reconstruction.parse import parse_cfr
    from spicy_docs.reconstruction.serialize import serialize_cfr

    evidence_json = json.loads(evidence_path.read_text())
    evidence = EvidenceDocument.from_json(evidence_json)
    reconstructed = parse_cfr(evidence)
    serialized = serialize_cfr(reconstructed, section=provenance["section"])
    data = evidence_path.read_bytes()
    artifact = artifact_record(
        provenance["pdfSha256"],
        provenance["pdfBytes"],
        "application/pdf",
        {
            "url": provenance["pdfUrl"],
            "publisher": "GovInfo",
            "publisherId": provenance["granuleId"],
        },
        [("rkaf:partner-defined", f"govinfo:{provenance['granuleId']}")],
        FIXTURE_RETRIEVED["tests/fixtures/reconstruction/cfr/README.md"],
    )
    intermediate = intermediate_record(
        evidence_path,
        "application/json",
        "extraction.DocumentExtractor(NativeText()) then reconstruction.evidence.evidence_from_pages",
    )
    builder = Builder(
        Node(
            "document",
            None,
            "reconstructed",
            container=True,
            decision={"method": "generated", "rule": "reconstruction-document-root-v1"},
        )
    )
    sizes = read_page_sizes(pages_path, provenance["pdfSha256"])
    holders: dict[str, Node | Region] = {}
    paths = {entry.node: entry.path for entry in serialized.source_map.entries}
    for rn in reconstructed.nodes:
        parent = holders[rn.parent] if rn.parent else builder.root
        assert isinstance(parent, Node)
        parent.container = True
        node = Node(
            CFR_KIND_MAP[rn.kind],
            parent,
            "reconstructed",
            designation=rn.marker,
            decision={
                "method": rn.decision.method,
                "rule": rn.decision.rule,
                **({"detail": rn.decision.detail} if rn.decision.detail else {}),
            },
            review_status=rn.review_status,
            derived={
                "text": rn.text,
                "rule": rn.decision.rule,
                "method": "model" if rn.decision.method == "model" else "rule",
            },
            ext={
                "reconstructionNode": rn.id,
                "reconstructionKind": rn.kind,
                **({"xmlPath": paths[rn.id]} if rn.id in paths else {}),
            },
        )
        if rn.kind == "subject":
            node.level = 1
        holders[rn.id] = node
    for ur in reconstructed.unresolved:
        parent = holders.get(ur.parent or "")
        region = Region([], ur.issue, ur.detail, parent if isinstance(parent, Node) else None)
        holders[ur.id] = region
        builder.regions.append(region)
    claimants: dict[str, list[Any]] = {}
    for record in (*reconstructed.nodes, *reconstructed.unresolved):
        for ref in record.evidence_refs:
            claimants.setdefault(ref, []).append(record)
    own_text: dict[str, Node] = {}

    def text_holder(record: Any) -> Node | Region:
        """A node with children keeps its own lines in an implicit first ``text`` child, as markup does."""
        holder = holders[record.id]
        if isinstance(holder, Region) or not holder.children:
            return holder
        if record.id not in own_text:
            leaf = Node(
                "text",
                holder,
                "reconstructed",
                decision={"method": "generated", "rule": "reconstructed-parent-own-text-v1"},
                ext={"reconstructionNode": record.id, "reconstructionKind": record.kind},
            )
            holder.children.remove(leaf)
            holder.children.insert(0, leaf)
            own_text[record.id] = leaf
        return own_text[record.id]

    previous: Any = None
    last_owner: Node | Region | None = None
    for block in evidence.blocks:
        records = claimants.get(block.id, [])
        if previous is not None:
            # A separator between two lines of one holder is that holder's; otherwise the document's.
            same = len(records) == 1 and last_owner is not None and text_holder(records[0]) is last_owner
            builder.span(last_owner if same else builder.root, "\n" if block.page == previous.page else "\f", NONE)
        previous = block
        if not block.text:
            continue
        source, style = block_source(block), block_style(block)
        if not records:
            region = Region([], "unclaimed-block", f"{block.id} is referenced by no node or region")
            builder.regions.append(region)
            builder.span(region, block.text, source, style=style)
            last_owner = region
            continue
        if len(records) == 1:
            last_owner = text_holder(records[0])
            builder.span(last_owner, block.text, source, style=style)
            continue
        # A block shared by a parent and its children: the children take their own text, the parent the rest.
        ids = {r.id for r in records}
        parents = [r for r in records if any(getattr(o, "parent", None) == r.id for o in records)]
        children = [r for r in records if r.id not in {p.id for p in parents}]
        pieces = None
        if len(parents) == 1 and all(hasattr(c, "text") for c in children) and ids >= {p.id for p in parents}:
            pieces = _split_shared_block(block.text, [(c, c.text) for c in children])
        if pieces is None:
            holder = holders[records[0].id]
            (holder.issues if isinstance(holder, Node) else builder.issues).append(
                {"code": "shared-block-unsplit", "detail": block.id}
            )
            builder.span(holder, block.text, source, style=style)
            last_owner = holder
        else:
            for record, text in pieces:
                last_owner = holders[record.id] if record is not None else holders[parents[0].id]
                builder.span(last_owner, text, source, style=style)
    ext = {
        "reconstructionProfile": reconstructed.profile,
        "selectedSection": provenance["section"],
        "granuleId": provenance["granuleId"],
        "pdfSha256": provenance["pdfSha256"],
        "pdfBytes": provenance["pdfBytes"],
        "pages": provenance["pages"],
        "serializedXmlSha256": sha256(serialized.xml),
        "serializer": serialized.source_map.serializer,
        "outOfScopeBlocks": len(serialized.source_map.out_of_scope),
        "unresolvedRegions": len(reconstructed.unresolved),
        "pageSizes": [{"page": n, **s} for n, s in sorted(sizes.items())],
    }
    return Conversion(
        "cfr-2025-title30-vol3-sec716-2",
        "cfr-reconstruction",
        "pdf",
        artifact,
        converter_record("cfr-reconstruction", [("pymupdf", importlib.metadata.version("pymupdf"))]),
        ext,
        builder,
        data,
        evidence_json,
        intermediate,
    )


def convert_slip_opinion(
    pdf_path: Path | None, evidence_path: Path, receipt: Mapping[str, Any], pages_path: Path | None = None
) -> Conversion:
    from spicy_docs.reconstruction.evidence import EvidenceDocument, evidence_from_pages

    if pdf_path is not None and pdf_path.exists():
        from spicy_docs.extraction import DocumentExtractor, NativeText

        pdf = pdf_path.read_bytes()
        if sha256(pdf) != receipt["sha256"]:
            raise ValueError("the slip opinion PDF differs from the receipt's digest")
        pages = list(DocumentExtractor(NativeText()).extract(pdf, media_type="application/pdf"))
        evidence_path.write_text(evidence_from_pages(pages).dumps())
    evidence_json = json.loads(evidence_path.read_text())
    evidence = EvidenceDocument.from_json(evidence_json)
    if evidence.source_sha256 != receipt["sha256"]:
        raise ValueError("the retained evidence document was not extracted from the receipted PDF")
    data = evidence_path.read_bytes()
    artifact = artifact_record(
        receipt["sha256"],
        receipt["bytes"],
        "application/pdf",
        {
            "url": receipt["url"],
            "publisher": "Supreme Court of the United States",
            "publisherId": "25pdf/26a274_l537",
        },
        [("rkaf:partner-defined", "supremecourt:25pdf/26a274_l537")],
        receipt["requestedAt"],
    )
    intermediate = intermediate_record(
        evidence_path,
        "application/json",
        "extraction.DocumentExtractor(NativeText()) then reconstruction.evidence.evidence_from_pages",
    )
    builder = Builder(
        Node(
            "document",
            None,
            "pdf-text",
            container=True,
            decision={"method": "generated", "rule": "extractor-document-root-v1"},
        )
    )
    sizes = read_page_sizes(pages_path, receipt["sha256"])
    pages = lines_to_pages(
        evidence,
        builder,
        "pdf-text",
        sizes,
        classify_slip_page,
    )
    opinions = group_slip_opinions(pages, builder)
    ext = {
        "pdfSha256": receipt["sha256"],
        "pdfBytes": receipt["bytes"],
        "pageCount": evidence.page_count,
        "extractor": "extraction.DocumentExtractor(NativeText())",
        "lineAssembly": "reconstruction.evidence.evidence_from_pages",
        "classification": "opinion-designator-and-opening-formula",
        "opinions": [
            {"kind": o["kind"], "pages": o["pages"], **{k: o[k] for k in ("author", "joinedBy") if k in o}}
            for o in opinions
        ],
    }
    return Conversion(
        "scotus-26a274_l537",
        "slip-opinion-pdf",
        "pdf",
        artifact,
        converter_record("slip-opinion-pdf", [("pymupdf", importlib.metadata.version("pymupdf"))]),
        ext,
        builder,
        data,
        evidence_json,
        intermediate,
    )


# --- driver -------------------------------------------------------------------


def choose_leaves(capture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The first and last leaf with at least twenty characters, preferring classified kinds over bare lines."""
    candidates = [n for n in capture["nodes"] if "text" in n and len(n["text"].strip()) >= 20]
    preferred = [n for n in candidates if n["kind"] in ("paragraph", "heading", "cell", "footnote", "note")]
    if len(preferred) < 2:
        preferred = candidates
    return [preferred[0], preferred[-1]] if len(preferred) > 1 else preferred


def size_decomposition(capture: Mapping[str, Any], text: str) -> dict[str, Any]:
    """Where a capture's bytes go, measured rather than asserted.

    The design record used to say the size was the text repeated; it is not.
    Each row below is the whole document re-serialized with one thing removed,
    so the numbers add up against the same encoder that wrote the file.
    """

    def without(mutate: Callable[[dict[str, Any]], object]) -> int:
        doc = json.loads(json.dumps(capture))
        mutate(doc)
        return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1

    def drop_leaf_text(doc: dict[str, Any]) -> None:
        for node in doc["nodes"]:
            node.pop("text", None)

    def drop_span_ids(doc: dict[str, Any]) -> None:
        for span in doc["evidence"]:
            span.pop("id", None)
            span.pop("end", None)
        for holder in (*doc["nodes"], *doc["unresolved"]):
            holder["evidence"] = len(holder["evidence"])

    total = len(text.encode("utf-8"))
    exact = sum(len(s["exact"].encode("utf-8")) for s in capture["evidence"])
    return {
        "bytes": total,
        "indentedBytes": len((json.dumps(capture, ensure_ascii=False, indent=1) + "\n").encode("utf-8")),
        "exactTextBytes": exact,
        "withoutLeafText": without(drop_leaf_text),
        "withoutSpanIdAndEnd": without(drop_span_ids),
        "withoutSpanSource": without(lambda d: [s.pop("source", None) for s in d["evidence"]]),
        "withoutNodeSource": without(lambda d: [n.pop("source", None) for n in d["nodes"]]),
    }


def measure(
    conversion: Conversion,
    output: Path,
    parent: Draft202012Validator,
    profiles: Mapping[str, Draft202012Validator],
    fragment_validator: Draft202012Validator,
) -> dict[str, Any]:
    started = time.perf_counter()
    capture = conversion.capture()
    seconds = time.perf_counter() - started
    # Compact: one capture per line-free document. Indenting every field cost
    # about a quarter of the bytes and told a reader nothing a formatter cannot
    # put back, which is the largest single item in the size decomposition.
    text = json.dumps(capture, ensure_ascii=False, separators=(",", ":")) + "\n"
    (output / f"{conversion.name}.capture.json").write_text(text, encoding="utf-8")
    decomposition = size_decomposition(capture, text)
    schema_errors = [e.message for e in parent.iter_errors(capture)]
    profile_errors = [e.message for e in profiles[conversion.family].iter_errors(capture)]
    invariants = check_invariants(capture)
    span_by_id = {s["id"]: s for s in capture["evidence"]}
    fragments = [leaf_fragments(capture, leaf, span_by_id) for leaf in choose_leaves(capture)]
    fragment_errors = validate_fragments(fragments, fragment_validator)
    (output / f"{conversion.name}.fragments.json").write_text(
        json.dumps(fragments, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )  # two fragments per document: small, and read by a person
    independent, tool = independent_text(conversion.rendition, conversion.artifact_bytes, conversion.evidence_json)
    declared = capture["rendition"]["textStream"]["sha256"]
    leaves = [n for n in capture["nodes"] if "text" in n]
    return {
        "name": conversion.name,
        "family": conversion.family,
        "rendition": conversion.rendition,
        "artifactBytes": capture["artifact"]["byteSize"],
        "captureBytes": len(text.encode("utf-8")),
        "nodes": len(capture["nodes"]),
        "leaves": len(leaves),
        "emptyLeaves": sum(1 for n in leaves if not n["evidence"]),
        "nonContiguousLeaves": sum(1 for n in leaves if len(contiguous_runs(capture, n, span_by_id)) > 1),
        "spans": len(capture["evidence"]),
        "unresolved": len(capture["unresolved"]),
        "issues": len(capture["issues"]) + sum(len(n.get("issues", ())) for n in capture["nodes"]),
        "codePoints": capture["rendition"]["textStream"]["codePoints"],
        "textStreamSha256": declared,
        "roundTrip": {
            "partitionDigestMatches": sha256("".join(s["exact"] for s in capture["evidence"])) == declared,
            "independentDerivationMatches": sha256(independent) == declared,
            "independentTool": tool,
        },
        "schemaValid": not schema_errors,
        "profileValid": not profile_errors,
        "invariantsHold": not invariants,
        "fragmentsValid": not fragment_errors,
        "fragments": [f["node"] for f in fragments],
        "size": decomposition,
        "seconds": round(seconds, 4),
        "errors": schema_errors[:5] + profile_errors[:5] + invariants[:5] + fragment_errors[:5],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=None, help="retained fetched inputs (default: <output>/inputs)")
    parser.add_argument(
        "--scotus-pdf",
        type=Path,
        default=None,
        help="the fetched slip opinion PDF; without it the retained evidence document is read",
    )
    parser.add_argument(
        "--receipts",
        type=Path,
        default=Path.home() / "Work/corpora/supply-2026-09-02/receipts/document-capture-schema-2026-09-19",
    )
    args = parser.parse_args(argv)
    output: Path = args.output.resolve()
    inputs = (args.inputs or output / "inputs").resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipts = {}
    for line in (inputs / "requests.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row.get("retainedAs"):
            receipts[row["retainedAs"]] = row
    parent, profiles, fragment_validator = validators()
    composition = {
        name: check_profile_composition(load_schema(f"profiles/{name}.schema.json"), parent.schema) for name in profiles
    }
    provenance = {e["section"]: e for e in json.loads((FIXTURES / "reconstruction/cfr/provenance.json").read_text())}
    conversions = [
        convert_uslm(FIXTURES / "uslm/plaw-119publ1.xml"),
        convert_bill(FIXTURES / "govinfo_bills/text-119hjres25enr.xml"),
        convert_committee_report(FIXTURES / "govinfo_bodies/body-CRPT-119hrpt1.htm"),
        convert_federal_register(
            inputs / "fr-2026-19200.xml", inputs / "fr-2026-19200.json", receipts["fr-2026-19200.xml"]
        ),
        convert_cfr(
            FIXTURES / "reconstruction/cfr/CFR-2025-title30-vol3-sec716-2.evidence.json",
            provenance["716.2"],
            inputs / "CFR-2025-title30-vol3-sec716-2.pages.json",
        ),
        convert_slip_opinion(
            args.scotus_pdf,
            inputs / "26a274_l537.evidence.json",
            receipts["26a274_l537.pdf"],
            inputs / "26a274_l537.pages.json",
        ),
    ]
    rows = [measure(c, output, parent, profiles, fragment_validator) for c in conversions]
    summary = {
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "parentSchema": schema_pin(PARENT_SCHEMA),
        "sourceFragmentSchema": schema_pin("rulespec/source-fragment.schema.json"),
        "profileComposition": composition,
        "receipts": str(args.receipts),
        "documents": rows,
    }
    (output / "measurement.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for row in rows:
        flags = " ".join(k for k in ("schemaValid", "profileValid", "invariantsHold", "fragmentsValid") if not row[k])
        trip = row["roundTrip"]
        print(
            f"{row['name']:34} nodes={row['nodes']:4} leaves={row['leaves']:4} spans={row['spans']:4} cp={row['codePoints']:6} "
            f"partition={trip['partitionDigestMatches']} independent={trip['independentDerivationMatches']} {flags or 'ok'}"
        )
        for error in row["errors"]:
            print("   ", error[:200])
    for name, problems in composition.items():
        for problem in problems:
            print(f"profile {name}: {problem}")
    return 1 if any(row["errors"] for row in rows) or any(composition.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
