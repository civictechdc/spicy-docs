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

**Complexity.** One pass over the reader's events or the evidence blocks, O(E)
for E events, plus O(N + S) over nodes and spans to number and check them. The
only step that is not linear is the sub-line split of a reconstruction block
shared by a parent and its children, which scans that one line's text once
per child.

Run from the repository root through the project's runner:

    uv run --frozen python -m tools.analysis.document_capture --output docs/research/document-capture-schema-2026-09-19

Design record: ``docs/research/document-capture-schema-2026-09-19.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
CONVERTER_VERSION = "1"
FIXTURES = ROOT / "tests" / "fixtures"

#: Node kinds every family shares; anything else is ``<profile>:<Kind>``.
CORE_KINDS = frozenset(
    [
        "document", "frontMatter", "body", "backMatter", "metadata", "title", "division", "section", "heading",
        "paragraph", "list", "item", "quote", "table", "row", "cell", "note", "footnote", "figure", "signature",
        "page", "line", "pageNumber", "runningHead", "printFooter", "text", "label",
    ]
)  # fmt: skip
_NAMESPACED = re.compile(r"^([a-z][a-z0-9-]*):[A-Za-z][A-Za-z0-9-]*$")
NONE = {"coordinateSystem": "none"}


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(name).read_text(encoding="utf-8"))


def schema_pin(name: str) -> dict[str, Any]:
    return {"$id": load_schema(name)["$id"], "sha256": sha256(SCHEMAS.joinpath(name).read_bytes())}


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


def span_json(span: Span) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": span.id,
        "start": span.start,
        "end": span.end,
        "exact": span.exact,
        "sha256": sha256(span.exact),
        "source": span.source,
    }
    if span.tags:
        out["tags"] = list(span.tags)
    if span.style:
        out["style"] = span.style
    return out


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

    def has_structure(self, grammar: Grammar) -> bool:
        for part in self.parts:
            if isinstance(part, Elem) and (
                grammar.role(part.name) is not None or (part.name not in grammar.inline and part.has_structure(grammar))
            ):
                return True
        return False


def element_tree(read: MarkupRead, body: bytes) -> Elem:
    """Fold the reader's flat events into a tree, keeping every text event and its byte span."""
    root = Elem("", {}, 0, len(body), "")
    stack: list[Elem] = [root]
    counts: list[dict[str, int]] = [{}]
    for event in read.events:
        if event.kind in ("start", "empty"):
            name = event.name or ""
            counts[-1][name] = counts[-1].get(name, 0) + 1
            path = f"{stack[-1].path}/{name}[{counts[-1][name]}]"
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
            leaf = Node("text", node, self.grammar.derivation)
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
        if self.grammar.heading_level is not None and node.kind == "heading":
            node.level = self.grammar.heading_level(elem)


def preformatted_blocks(
    events: Sequence[MarkupEvent], container: Node, builder: Builder, classify: Callable[[str], tuple[str, str | None]]
) -> None:
    """Split a preformatted run into blank-line blocks; ``classify`` names each line's kind.

    A block's lines and its interior newlines belong to the block; the newline
    after its last line, blank lines, and their newlines belong to the
    container. Byte coordinates are exact only where the reader said the run
    was literal; otherwise a piece's source covers its whole event.
    """
    pieces: list[tuple[str, dict[str, Any]]] = []
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
    lines: list[list[tuple[str, dict[str, Any]]]] = [[]]
    for piece in pieces:
        lines[-1].append(piece)
        if piece[0] == "\n":
            lines.append([])
    block: Node | None = None
    pending: tuple[str, dict[str, Any]] | None = None
    for line in lines:
        newline = line[-1] if line and line[-1][0] == "\n" else None
        content = line[:-1] if newline else line
        text = "".join(p for p, _ in content)
        kind, designation = classify(text) if text.strip() else ("", None)
        single = kind in ("pageNumber", "committee-report-html:banner", "committee-report-html:rule")
        if kind and block is not None and block.kind == kind and not single and pending is not None:
            builder.span(block, *pending)
        elif pending is not None:
            builder.span(container, *pending)
        pending = None
        if kind:
            if block is None or block.kind != kind or single:
                block = Node(kind, container, "markup", designation=designation)
            for piece in content:
                builder.span(block, *piece)
        else:
            block = None
            for piece in content:
                builder.span(container, *piece)
        if newline is not None:
            pending = newline if kind else None
            if not kind:
                builder.span(container, *newline)
    if pending is not None:
        builder.span(container, *pending)


# --- evidence-line renditions (PDF extraction, reconstruction) --------------------------


def block_source(block: Any) -> dict[str, Any]:
    if block.page is not None and block.box is not None:
        box = [round(v * 1000) for v in (block.box.x0, block.box.y0, block.box.x1, block.box.y1)]
        return {"coordinateSystem": "page-region", "page": block.page, "box": box, "line": block.line}
    if block.span is not None:
        return {"coordinateSystem": "utf8-byte", "start": block.span[0], "end": block.span[1], "literal": True}
    return dict(NONE)


def block_style(block: Any) -> dict[str, Any] | None:
    runs = [run for run in block.runs if run.text.strip()]
    if not runs or all(run.font is None and run.size is None for run in runs):
        return None
    style: dict[str, Any] = {"bold": block.bold, "italic": block.italic}
    if block.size is not None:
        style["size"] = block.size
    if block.fonts:
        style["font"] = ", ".join(block.fonts)
    return style


def lines_to_pages(evidence: Any, builder: Builder, derivation: str) -> None:
    """One ``page`` per extractor page, one ``line`` leaf per block; separators go to the container."""
    document = builder.root
    pages: dict[int, Node] = {}
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
                source={"coordinateSystem": "page-region", "page": block.page},
            )
        elif previous is not None:
            builder.span(page, "\n", NONE)
        leaf = Node("line", page, derivation, source=block_source(block))
        if block.text:
            builder.span(leaf, block.text, block_source(block), style=block_style(block))
        else:
            leaf.issues.append({"code": "empty-block"})
        previous = block


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
    """The composition rule: reference the parent by id and digest; narrow only ``profile`` and node ``kind``/``ext``."""
    problems = []
    if profile.get("x-parent") != {
        "$id": parent["$id"],
        "sha256": sha256(SCHEMAS.joinpath(PARENT_SCHEMA).read_bytes()),
    }:
        problems.append("x-parent pin differs from the vendored parent")
    clauses = profile.get("allOf", [])
    if len(clauses) != 2 or clauses[0] != {"$ref": parent["$id"]}:
        problems.append("allOf must be exactly [{$ref: parent $id}, own narrowing]")
        return problems
    own = clauses[1]
    if set(own) - {"properties"} or set(own.get("properties", {})) - {"profile", "nodes"}:
        problems.append("a profile may narrow only properties.profile and properties.nodes")
    if set(own.get("properties", {}).get("profile", {}).get("properties", {})) - {"name", "version", "ext"}:
        problems.append("a profile may narrow only profile.name, profile.version and profile.ext")
    node_keys: set[str] = set()
    items = own.get("properties", {}).get("nodes", {}).get("items", {})
    for clause in items.get("allOf", []):
        node_keys |= set(clause.get("properties", {})) | set(clause.get("then", {}).get("properties", {}))
    if set(items) - {"allOf"} or node_keys - {"kind", "ext"}:
        problems.append(f"a profile may narrow only node kind and ext, not {sorted(node_keys - {'kind', 'ext'})}")
    return problems


def check_invariants(capture: Mapping[str, Any]) -> list[str]:
    """What JSON Schema cannot see: the partition, ownership, tree shape, kind namespace and leaf text."""
    problems = []
    spans = capture["evidence"]
    cursor = 0
    for span in spans:
        if span["start"] != cursor or span["end"] != span["start"] + len(span["exact"]):
            problems.append(f"{span['id']} breaks the partition at {cursor}")
        cursor = span["end"]
    stream = "".join(s["exact"] for s in spans)
    declared = capture["rendition"]["textStream"]
    if cursor != declared["codePoints"] or sha256(stream) != declared["sha256"]:
        problems.append("text stream digest or length differs from the span partition")
    owners: dict[str, str] = {}
    for holder in (*capture["nodes"], *capture["unresolved"]):
        for span_id in holder["evidence"]:
            if span_id in owners:
                problems.append(f"{span_id} owned by {owners[span_id]} and {holder['id']}")
            owners[span_id] = holder["id"]
    unowned = [s["id"] for s in spans if s["id"] not in owners]
    if unowned:
        problems.append(f"{len(unowned)} spans owned by nothing, first {unowned[0]}")
    by_id = {n["id"]: n for n in capture["nodes"]}
    span_by_id = {s["id"]: s for s in spans}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for node in capture["nodes"]:
        children.setdefault(node["parent"], []).append(node)
        match = _NAMESPACED.match(node["kind"])
        if match and match.group(1) != capture["profile"]["name"]:
            problems.append(f"{node['id']} kind {node['kind']} is outside profile {capture['profile']['name']}")
        elif not match and node["kind"] not in CORE_KINDS:
            problems.append(f"{node['id']} kind {node['kind']} is neither core nor namespaced")
        if node["parent"] is not None and node["depth"] != by_id[node["parent"]]["depth"] + 1:
            problems.append(f"{node['id']} depth is not its parent's plus one")
    if capture["nodes"][0]["kind"] != "document" or capture["nodes"][0]["parent"] is not None:
        problems.append("nodes[0] must be the document root")
    for parent, siblings in children.items():
        if [n["ordinal"] for n in siblings] != list(range(len(siblings))):
            problems.append(f"children of {parent} are not densely ordered")
    for node in capture["nodes"]:
        is_leaf = node["id"] not in children
        if is_leaf != ("text" in node):
            problems.append(f"{node['id']} text presence disagrees with leafness")
        if is_leaf and node["text"] != "".join(span_by_id[s]["exact"] for s in node["evidence"]):
            problems.append(f"{node['id']} text differs from its spans")
    return problems


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


def enclosing_identifier(capture: Mapping[str, Any], node: Mapping[str, Any]) -> str | None:
    """The publisher's identifier on this node or its nearest ancestor (a USLM ``identifier`` attribute)."""
    by_id = {n["id"]: n for n in capture["nodes"]}
    current: Mapping[str, Any] | None = node
    while current is not None:
        if (current.get("ext") or {}).get("identifier"):
            return current["ext"]["identifier"]
        current = by_id[current["parent"]] if current["parent"] else None
    return None


def leaf_fragments(
    capture: Mapping[str, Any], node: Mapping[str, Any], span_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Two fragments for one leaf: one into the text stream, one into the rendition artifact."""
    runs = contiguous_runs(capture, node, span_by_id)
    text = node["text"]
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
    source = node["source"]
    owned = [span_by_id[s] for s in node["evidence"]]
    selectors: list[dict[str, Any]] = []
    kinds: list[str] = []
    if source["coordinateSystem"] == "xml-node-path":
        selectors.append({"@type": "oa:XPathSelector", "rdf:value": source["path"]})
        kinds.append("oa:XPathSelector")
        identifier = enclosing_identifier(capture, node)
        if identifier and capture["profile"]["name"] == "uslm-law":
            # Names the enclosing USLM unit; the position and quote selectors narrow within it.
            selectors.append({"@type": "rkaf:uslm-section", "rdf:value": identifier})
            kinds.append("rkaf:uslm-section")
    regions = [source] if source["coordinateSystem"] == "page-region" and "box" in source else []
    regions = regions or [
        s["source"] for s in owned if s["source"]["coordinateSystem"] == "page-region" and "box" in s["source"]
    ]
    for region in regions:  # one RFC 8118 fragment per printed line the leaf rests on
        x0, y0, x1, y1 = region["box"]
        selectors.append(
            {
                "@type": "oa:FragmentSelector",
                "dcterms:conformsTo": "https://www.rfc-editor.org/rfc/rfc8118",
                "rdf:value": f"page={region['page']}&viewrect={x0},{y0},{x1 - x0},{y1 - y0}",
            }
        )
    if regions:
        kinds.append("oa:FragmentSelector")
    byte_spans = [s["source"] for s in owned if s["source"]["coordinateSystem"] == "utf8-byte"]
    if byte_spans:
        selectors.append(
            {
                "@type": "oa:TextPositionSelector",
                "oa:start": min(s["start"] for s in byte_spans),
                "oa:end": max(s["end"] for s in byte_spans),
                "rkaf:coordinateSystem": "rkaf:utf8-byte",
            }
        )
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
_CRPT_RULE = re.compile(r"^\s*[=_]{5,}\s*$")


def classify_report_line(line: str) -> tuple[str, str | None]:
    if match := _CRPT_PAGE.match(line):
        return "pageNumber", match.group(1)
    if _CRPT_BANNER.match(line):
        return "committee-report-html:banner", None
    if _CRPT_RULE.match(line):
        return "committee-report-html:rule", None
    return "paragraph", None


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


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def converter_record(family: str, extra: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
    deps = [("python", sys.version.split()[0]), ("spicy-docs", importlib.metadata.version("spicy-docs")), *extra]
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


def artifact_record(
    data: bytes,
    media_type: str,
    locator: Mapping[str, Any],
    identifiers: Sequence[tuple[str, str]],
    retrieved: str | None,
) -> dict[str, Any]:
    digest = sha256(data)
    out: dict[str, Any] = {
        "iri": f"urn:document-capture:artifact:sha256:{digest}",
        "sha256": digest,
        "byteSize": len(data),
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

    def capture(self) -> dict[str, Any]:
        nodes, stream = self.builder.finish()
        digest = sha256(stream)
        norm_id, statement = NORMALIZATIONS[self.rendition]
        preimage = "\n".join(
            [self.artifact["sha256"], self.converter["id"], self.converter["version"], self.family, "1", digest]
        )
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
            "evidence": [span_json(s) for s in self.builder.spans],
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
    artifact = artifact_record(
        data,
        "application/xml",
        {
            "url": "https://www.govinfo.gov/bulkdata/PLAW/119/public/PLAW-119-public.zip",
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "PLAW-119publ1",
        },
        [("rkaf:uslm", "/us/pl/119/1"), *(("rkaf:partner-defined", f"citableAs:{c}") for c in meta.citable_as)],
        None,
    )
    ext = {
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
    for node in conversion.builder.nodes():
        attrs = node.source.get("attributes") or {}
        node_ext = {
            k: attrs[a]
            for k, a in (("identifier", "identifier"), ("role", "role"), ("numValue", "value"))
            if attrs.get(a)
        }
        if node_ext:
            node.ext = node_ext
    return conversion


def convert_bill(path: Path) -> Conversion:
    from spicy_docs.sources.congress.bill_tree import parse_bill_tree

    data = path.read_bytes()
    bill = parse_bill_tree(data, version="enr")
    artifact = artifact_record(
        data,
        "application/xml",
        {
            "url": "https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml",
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "BILLS-119hjres25enr",
        },
        [("rkaf:partner-defined", "govinfo:BILLS-119hjres25enr")],
        None,
    )
    engine_version = importlib.metadata.version("deltatrack")
    conversion = convert_markup(
        "bills-119hjres25enr", BILL, data, "xml", artifact, external_doctype=True, deps=[("deltatrack", engine_version)]
    )
    by_element_id = {n.element_id: n for n in bill.sections}
    joined = []
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
    unjoined = [n for n in bill.sections if n.element_id not in joined]
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
    artifact = artifact_record(
        data,
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
    for node in conversion.builder.nodes():
        attrs = node.source.get("attributes") or {}
        if (
            node.kind == "cell"
            and node.parent is not None
            and node.parent.kind == "row"
            and node.parent.parent is not None
        ):
            row, table = node.parent, node.parent.parent
            rows = [c for c in table.children if c.kind == "row"]
            node.cell = {
                "row": rows.index(row),
                "column": row.children.index(node),
                "header": row.source.get("element") == "BOXHD",
            }
            node_ext = {k: v for k, v in (("headLevel", attrs.get("H")), ("indent", attrs.get("I"))) if v}
            if node_ext:
                node.ext = node_ext
        elif node.kind == "table":
            node.ext = {"cols": attrs.get("COLS"), "cdef": attrs.get("CDEF")}
    return conversion


def convert_committee_report(path: Path) -> Conversion:
    data = path.read_bytes()
    artifact = artifact_record(
        data,
        "text/html",
        {
            "url": "https://www.govinfo.gov/content/pkg/CRPT-119hrpt1/html/CRPT-119hrpt1.htm",
            "path": str(path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": "CRPT-119hrpt1",
        },
        [("rkaf:partner-defined", "govinfo:CRPT-119hrpt1")],
        None,
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


def convert_cfr(evidence_path: Path, provenance: Mapping[str, Any]) -> Conversion:
    from spicy_docs.reconstruction.evidence import EvidenceDocument
    from spicy_docs.reconstruction.parse import parse_cfr
    from spicy_docs.reconstruction.serialize import serialize_cfr

    evidence_json = json.loads(evidence_path.read_text())
    evidence = EvidenceDocument.from_json(evidence_json)
    reconstructed = parse_cfr(evidence)
    serialized = serialize_cfr(reconstructed, section=provenance["section"])
    data = evidence_path.read_bytes()
    artifact = artifact_record(
        data,
        "application/json",
        {
            "url": provenance["pdfUrl"],
            "path": str(evidence_path.relative_to(ROOT)),
            "publisher": "GovInfo",
            "publisherId": provenance["granuleId"],
        },
        [
            ("rkaf:partner-defined", f"govinfo:{provenance['granuleId']}"),
            ("rkaf:partner-defined", f"pdf:sha256:{provenance['pdfSha256']}"),
        ],
        None,
    )
    builder = Builder(Node("document", None, "reconstructed", container=True))
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
    }
    return Conversion(
        "cfr-2025-title30-vol3-sec716-2",
        "cfr-reconstruction",
        "evidence-lines",
        artifact,
        converter_record("cfr-reconstruction", [("pymupdf", importlib.metadata.version("pymupdf"))]),
        ext,
        builder,
        data,
        evidence_json,
    )


def convert_slip_opinion(pdf_path: Path | None, evidence_path: Path, receipt: Mapping[str, Any]) -> Conversion:
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
        data,
        "application/json",
        {
            "url": receipt["url"],
            "path": str(evidence_path.relative_to(ROOT)),
            "publisher": "Supreme Court of the United States",
            "publisherId": "25pdf/26a274_l537",
        },
        [
            ("rkaf:partner-defined", "supremecourt:25pdf/26a274_l537"),
            ("rkaf:partner-defined", f"pdf:sha256:{receipt['sha256']}"),
        ],
        receipt["requestedAt"],
    )
    builder = Builder(Node("document", None, "pdf-text", container=True))
    lines_to_pages(evidence, builder, "pdf-text")
    ext = {
        "pdfSha256": receipt["sha256"],
        "pdfBytes": receipt["bytes"],
        "pageCount": evidence.page_count,
        "extractor": "extraction.DocumentExtractor(NativeText())",
        "lineAssembly": "reconstruction.evidence.evidence_from_pages",
        "classification": "none: the no-reference case, pages and lines only",
    }
    return Conversion(
        "scotus-26a274_l537",
        "slip-opinion-pdf",
        "evidence-lines",
        artifact,
        converter_record("slip-opinion-pdf", [("pymupdf", importlib.metadata.version("pymupdf"))]),
        ext,
        builder,
        data,
        evidence_json,
    )


# --- driver -------------------------------------------------------------------


def choose_leaves(capture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The first and last leaf with at least twenty characters, preferring classified kinds over bare lines."""
    candidates = [n for n in capture["nodes"] if "text" in n and len(n["text"].strip()) >= 20]
    preferred = [n for n in candidates if n["kind"] in ("paragraph", "heading", "cell", "footnote", "note")]
    if len(preferred) < 2:
        preferred = candidates
    return [preferred[0], preferred[-1]] if len(preferred) > 1 else preferred


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
    text = json.dumps(capture, ensure_ascii=False, indent=1) + "\n"
    (output / f"{conversion.name}.capture.json").write_text(text, encoding="utf-8")
    schema_errors = [e.message for e in parent.iter_errors(capture)]
    profile_errors = [e.message for e in profiles[conversion.family].iter_errors(capture)]
    invariants = check_invariants(capture)
    span_by_id = {s["id"]: s for s in capture["evidence"]}
    fragments = [leaf_fragments(capture, leaf, span_by_id) for leaf in choose_leaves(capture)]
    fragment_errors = validate_fragments(fragments, fragment_validator)
    (output / f"{conversion.name}.fragments.json").write_text(
        json.dumps(fragments, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
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
        convert_cfr(FIXTURES / "reconstruction/cfr/CFR-2025-title30-vol3-sec716-2.evidence.json", provenance["716.2"]),
        convert_slip_opinion(args.scotus_pdf, inputs / "26a274_l537.evidence.json", receipts["26a274_l537.pdf"]),
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
