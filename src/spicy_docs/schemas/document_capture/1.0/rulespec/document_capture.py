"""The DocumentCapture v1 checks that are not expressible as a schema.

Two kinds of check live here, and nothing else:

* :func:`check_invariants` -- the invariants ``spec/document-capture.md`` §2
  states and JSON Schema cannot see: the partition, ownership, the tree, leaf
  text, the kind namespace and the digests. This is the one implementation. A
  product that produces or consumes captures imports it rather than restating
  it; the two hand-written copies this replaces had already drifted apart.
* :func:`check_profile_bindings` -- the two bindings the profile meta-schema
  cannot state, because JSON Schema cannot read one part of a document from
  another: that a profile's ``x-parent`` digest is the parent's own bytes, and
  that every kind it enumerates and refuses carries its own name. The
  structural half of the composition rule is
  ``release-records/schemas/document-capture-profile-v1.schema.json``, shipped
  beside this module as data, and a caller validates against it with whatever
  JSON Schema implementation it already has. This package requires none.

Both schemas ship in the wheel's ``_data``; see
:mod:`rulespec_artifacts.resources`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "check_invariants",
    "check_profile_bindings",
    "core_kinds",
    "effective_source",
]

_NAMESPACED = re.compile(r"^([a-z][a-z0-9-]*):[A-Za-z][A-Za-z0-9-]*$")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def core_kinds(parent_schema: Mapping[str, Any] | None = None) -> frozenset[str]:
    """The closed core vocabulary, read from the parent schema rather than copied beside it."""

    if parent_schema is None:
        from . import resources

        parent_schema = resources.document_capture_schema()
    return frozenset(parent_schema["$defs"]["CoreKind"]["enum"])


def effective_source(capture: Mapping[str, Any], span: Mapping[str, Any]) -> dict[str, Any]:
    """A span's source locator with ``rendition.spanDefaults`` filled in.

    Fields that are the same for every span of one document are stated once on
    the rendition; a span states only what differs. Reading a span's
    coordinates means reading the merge, never the literal object.
    """

    merged = dict(capture["rendition"].get("spanDefaults") or {})
    merged.update(span.get("source") or {})
    return merged


def check_invariants(capture: Mapping[str, Any], *, parent_schema: Mapping[str, Any] | None = None) -> list[str]:
    """Every §2 invariant, as a list of what failed; empty means the capture holds them.

    Complexity is O(N + S) over nodes and spans: one pass to index, one to
    check. Nothing here re-reads the artifact -- a capture is checked from its
    own bytes, so a consumer with no fixture checkout can still refuse a
    malformed one.
    """

    problems: list[str] = []
    spans: Sequence[Mapping[str, Any]] = capture["evidence"]

    # 1. Partition, and 6. digests: contiguous, non-empty, covering the stream exactly.
    cursor = 0
    for span in spans:
        if span["start"] != cursor or span["end"] != span["start"] + len(span["exact"]):
            problems.append(f"{span['id']} breaks the partition at {cursor}")
        cursor = span["end"]
        stated = span.get("sha256")
        if stated is not None and stated != _sha256(span["exact"]):
            problems.append(f"{span['id']} content digest differs from its exact text")
        if "coordinateSystem" not in effective_source(capture, span):
            problems.append(f"{span['id']} states no coordinate system and the rendition defaults none")
    stream = "".join(s["exact"] for s in spans)
    declared = capture["rendition"]["textStream"]
    if cursor != declared["codePoints"] or _sha256(stream) != declared["sha256"]:
        problems.append("text stream digest or length differs from the span partition")

    # 2. Ownership: every span belongs to exactly one node or one unresolved region.
    owners: dict[str, str] = {}
    for holder in (*capture["nodes"], *capture["unresolved"]):
        for span_id in holder["evidence"]:
            if span_id in owners:
                problems.append(f"{span_id} owned by {owners[span_id]} and {holder['id']}")
            owners[span_id] = holder["id"]
    unowned = [s["id"] for s in spans if s["id"] not in owners]
    if unowned:
        problems.append(f"{len(unowned)} spans owned by nothing, first {unowned[0]}")
    # The converse: an evidence id that names no span is a dangling citation, and the
    # leaf-text check below must not hide it by skipping what it cannot find.
    span_ids = {s["id"] for s in spans}
    dangling = [s for s in owners if s not in span_ids]
    if dangling:
        problems.append(f"{len(dangling)} evidence ids name no span, first {dangling[0]}")

    # 3. Tree, and 5. kind namespace.
    kinds = core_kinds(parent_schema)
    profile_name = capture["profile"]["name"]
    by_id = {n["id"]: n for n in capture["nodes"]}
    span_by_id = {s["id"]: s for s in spans}
    children: dict[str | None, list[Mapping[str, Any]]] = {}
    for node in capture["nodes"]:
        children.setdefault(node["parent"], []).append(node)
        match = _NAMESPACED.match(node["kind"])
        if match and match.group(1) != profile_name:
            problems.append(f"{node['id']} kind {node['kind']} is outside profile {profile_name}")
        elif not match and node["kind"] not in kinds:
            problems.append(f"{node['id']} kind {node['kind']} is neither core nor namespaced")
        parent_id = node["parent"]
        if parent_id is not None:
            if parent_id not in by_id:
                problems.append(f"{node['id']} names a parent that is not a node")
            elif node["depth"] != by_id[parent_id]["depth"] + 1:
                problems.append(f"{node['id']} depth is not its parent's plus one")
    root = capture["nodes"][0]
    if root["kind"] != "document" or root["parent"] is not None:
        problems.append("nodes[0] must be the document root")
    for parent_id, siblings in children.items():
        if [n["ordinal"] for n in siblings] != list(range(len(siblings))):
            problems.append(f"children of {parent_id} are not densely ordered")

    # 4. Leaf text: citable text sits on a leaf, and a stated text is the spans'.
    for node in capture["nodes"]:
        # A dangling id is reported by the ownership check above; skip it here.
        own = "".join(span_by_id[s]["exact"] for s in node["evidence"] if s in span_by_id)
        if node["id"] in children:
            if "text" in node:
                problems.append(f"{node['id']} has children and carries text")
            elif own.strip():
                problems.append(f"{node['id']} has children and owns non-whitespace text")
        elif "text" in node and node["text"] != own:
            problems.append(f"{node['id']} text differs from its spans")
    return problems


def check_profile_bindings(
    profile: Mapping[str, Any],
    *,
    parent_id: str | None = None,
    parent_digest: str | None = None,
) -> list[str]:
    """The two bindings the profile meta-schema cannot state.

    Run this after validating ``profile`` against the profile meta-schema: the
    meta-schema settles the shape (closed everywhere, node clauses only
    ``if``/``then`` on ``kind`` and ``properties.ext``), and this settles the
    values that must agree with something outside the clause -- the parent's
    bytes and the profile's own name.
    """

    problems: list[str] = []
    pin = profile.get("x-parent") or {}
    if parent_id is not None and pin.get("$id") != parent_id:
        problems.append("x-parent names a different parent schema")
    if parent_digest is not None and pin.get("sha256") != parent_digest:
        problems.append("x-parent digest is not the parent's bytes")
    clauses = profile.get("allOf") or []
    if len(clauses) == 2 and clauses[0].get("$ref") not in (None, pin.get("$id")):
        problems.append("allOf[0] references a schema other than the pinned parent")

    def at(value: Any, *keys: str) -> Any:
        """Read a path that the meta-schema guarantees; missing means the meta-schema already refused it."""
        for key in keys:
            if not isinstance(value, Mapping):
                return None
            value = value.get(key)
        return value

    own = (at(clauses[1], "properties") if len(clauses) == 2 else None) or {}
    name = at(own, "profile", "properties", "name", "const")
    if not name:
        problems.append("the profile does not name itself")
        return problems
    node_clauses = ((own.get("nodes") or {}).get("items") or {}).get("allOf") or []
    if len(node_clauses) != 3:
        return [*problems, "the node narrowing is not the three clauses the meta-schema requires"]
    kind_clause, foreign_clause, _ = node_clauses

    if at(kind_clause, "if", "properties", "kind", "pattern") != f"^{name}:":
        problems.append(f"the kind clause tests a namespace other than {name}:")
    for kind in at(kind_clause, "then", "properties", "kind", "enum") or ():
        if not isinstance(kind, str) or not kind.startswith(f"{name}:"):
            problems.append(f"{kind} is enumerated by profile {name} but is not in its namespace")
    if at(foreign_clause, "properties", "kind", "not", "pattern") != f"^(?!{name}:)[a-z][a-z0-9-]*:":
        problems.append(f"the foreign-namespace refusal does not name {name}")
    return problems
