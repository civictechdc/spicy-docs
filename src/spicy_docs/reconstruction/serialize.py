"""Deterministic CFR XML from the document model, and a source map beside it.

The vocabulary is the guide's and the pinned schema's, and nothing else
travels in it -- no ``id``, confidence, rule name or evidence reference
becomes an attribute -- so a consumer who wants to know where a paragraph came
from reads the **source map**, a separate JSON document keyed by the XML path
of each element, which is what keeps the output a file the publisher's own
schema accepts while still being auditable back to the evidence. Paragraph
nesting lives in the markers, not the elements: a real CFR granule sets
``(a)``, ``(1)``, ``(i)`` and ``(A)`` as *sibling* ``<P>`` elements, so the
parser's tree is flattened back to document order here and carried by the
source map, checked by ``validate.structural_fidelity`` -- emitting nested
``<P>`` would be this repository's invention. ``FDSYS`` is emitted only from
facts a caller passes in and never from the evidence, and page furniture and
part matter are classified by the parser and left out of a section granule as
out-of-scope evidence rather than loss.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .evidence import DocumentNode, StyledRun, UnresolvedRegion
from .parse import CFR_KINDS, ReconstructedDocument

GRANULE_ROOT = "CFRGRANULE"
SECTION = "SECTION"
#: The one emphasis type the profile can observe from print: italic.
ITALIC_EMPHASIS = "03"
#: ``xsi:noNamespaceSchemaLocation`` is what a published granule states; the
#: reconstruction states it too so the file names the schema it was checked
#: against. It is the publisher's own attribute, not a custom one.
XSI = "http://www.w3.org/2001/XMLSchema-instance"


class SerializeError(ValueError):
    """The document model cannot be written in this profile's vocabulary."""


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    """One element of the output, the node behind it and the evidence behind that."""

    path: str
    element: str
    node: str
    kind: str
    rule: str
    method: str
    review_status: str
    evidence: tuple[str, ...]
    marker: str | None = None
    parent_node: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMap:
    """The sidecar: every emitted element's provenance, plus what was left out and why."""

    profile: str
    serializer: str
    derivation: str
    root: str
    entries: tuple[SourceMapEntry, ...]
    unresolved: tuple[UnresolvedRegion, ...]
    out_of_scope: tuple[str, ...]
    id_origin: str

    def to_json(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "serializer": self.serializer,
            "derivation": self.derivation,
            "root": self.root,
            "idOrigin": self.id_origin,
            "entries": [
                {
                    "path": entry.path,
                    "element": entry.element,
                    "node": entry.node,
                    "kind": entry.kind,
                    "rule": entry.rule,
                    "method": entry.method,
                    "reviewStatus": entry.review_status,
                    "marker": entry.marker,
                    "parentNode": entry.parent_node,
                    "evidence": list(entry.evidence),
                }
                for entry in self.entries
            ],
            "unresolved": [
                {
                    "id": region.id,
                    "issue": region.issue,
                    "detail": region.detail,
                    "parentNode": region.parent,
                    "evidence": list(region.evidence_refs),
                }
                for region in self.unresolved
            ],
            "outOfScopeEvidence": list(self.out_of_scope),
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=1, ensure_ascii=False) + "\n"

    def evidence_for(self, path: str) -> tuple[str, ...]:
        for entry in self.entries:
            if entry.path == path:
                return entry.evidence
        raise SerializeError(f"source map has no entry for {path!r}")


@dataclass(frozen=True, slots=True)
class Serialized:
    """The derivative: its bytes, its source map, and the nodes it carried."""

    xml: bytes
    source_map: SourceMap
    nodes: tuple[DocumentNode, ...]

    @property
    def text(self) -> str:
        return self.xml.decode("utf-8")


def _element_for(node: DocumentNode) -> str | None:
    try:
        return CFR_KINDS[node.kind]
    except KeyError:
        raise SerializeError(f"node {node.id} has kind {node.kind!r}, which this profile does not serialize") from None


def _segments(runs: Sequence[StyledRun]) -> list[tuple[str, bool, str | None]]:
    """``(text, italic, break_to_page)`` runs, merged so one emphasis is one element.

    Two joins matter here, and both come from the evidence being *lines*: a
    run of italic set across a print line reaches the model as two italic runs
    with the join space between them, and a print line can end inside the
    emphasis. So a whitespace-only run between two italic runs is taken as part
    of the emphasis, adjacent runs of the same face are merged, and the
    emphasis's own leading and trailing spaces are then moved outside it,
    which is how the publisher sets it. No character is added or removed.
    """
    merged: list[tuple[str, bool, str | None]] = []
    for index, run in enumerate(runs):
        italic = run.italic
        if not italic and run.text and not run.text.strip():
            following = next((later for later in runs[index + 1 :] if later.text.strip()), None)
            italic = bool(merged and merged[-1][1] and following is not None and following.italic)
        if merged and merged[-1][1] == italic and run.break_to_page is None:
            text, _, page = merged[-1]
            merged[-1] = (text + run.text, italic, page)
        else:
            merged.append((run.text, italic, run.break_to_page))
    out: list[tuple[str, bool, str | None]] = []
    for text, italic, page in merged:
        if not italic or not text.strip():
            out.append((text, italic, page))
            continue
        body = text.strip()
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
        if lead:
            out.append((lead, False, page))
            page = None
        out.append((body, True, page))
        if trail:
            out.append((trail, False, None))
    return out


def _append_runs(element: ET.Element, runs: Sequence[StyledRun], text: str) -> None:
    """Write a node's text, turning an italic run into ``E`` and a page break into ``PRTPAGE``.

    Runs join to the node's text exactly, so what is written is what was
    extracted; ``E`` and ``PRTPAGE`` add structure around that text and never
    change it.
    """
    if not runs:
        element.text = text
        return
    last: ET.Element | None = None
    for chars, italic, page in _segments(runs):
        if page is not None:
            last = ET.SubElement(element, "PRTPAGE", {"P": page})
        if not chars:
            continue
        if italic:
            emphasis = ET.SubElement(element, "E", {"T": ITALIC_EMPHASIS})
            emphasis.text = chars
            last = emphasis
        elif last is None:
            element.text = (element.text or "") + chars
        else:
            last.tail = (last.tail or "") + chars


def _flatten(document: ReconstructedDocument, section: DocumentNode) -> Iterator[DocumentNode]:
    """The section's descendants in reading order; nesting is carried by the markers, not the elements."""
    inside = {section.id}
    for node in document.nodes:
        if node.parent in inside:
            inside.add(node.id)
            yield node


def _indent(element: ET.Element, level: int = 0) -> None:
    """Two-space indentation, applied only where an element has no text of its own."""
    pad = "\n" + "  " * level
    children = list(element)
    if children:
        if not element.text:
            element.text = pad + "  "
        for index, child in enumerate(children):
            _indent(child, level + 1)
            if not child.tail:
                child.tail = pad + "  " if index + 1 < len(children) else pad


def serialize_cfr(
    document: ReconstructedDocument,
    *,
    section: str | None = None,
    fdsys: Mapping[str, str] | None = None,
) -> Serialized:
    """Write one section (or every section found) as a CFR granule, with its source map.

    ``section`` selects by section number, the way a caller names the granule
    it asked for; every block outside the selected section is out-of-scope
    evidence, listed in the source map, and a requested section that is not
    found raises ``SerializeError``. ``fdsys`` writes the publisher metadata
    block from facts the *caller* holds -- the request's own coordinates or the
    package MODS -- and is never derived from the rendition.
    """
    sections = document.sections()
    if section is not None:
        chosen = [node for node in sections if node.marker == section]
        if not chosen:
            found = ", ".join(node.marker or "?" for node in sections) or "none"
            raise SerializeError(f"no section {section!r} in the reconstruction; found {found}")
    else:
        chosen = list(sections)
    root = ET.Element(GRANULE_ROOT, {f"{{{XSI}}}noNamespaceSchemaLocation": "CFRMergedXML.xsd"})
    ET.register_namespace("xsi", XSI)
    entries: list[SourceMapEntry] = []
    carried: list[DocumentNode] = []
    in_scope: set[str] = set()
    counts: dict[str, int] = {}

    def path_for(parent_path: str, name: str) -> str:
        key = f"{parent_path}/{name}"
        counts[key] = counts.get(key, 0) + 1
        return f"{key}[{counts[key]}]"

    if fdsys:
        block = ET.SubElement(root, "FDSYS")
        for name, value in fdsys.items():
            ET.SubElement(block, name).text = value

    for node in chosen:
        section_path = path_for(f"/{GRANULE_ROOT}", SECTION)
        element = ET.SubElement(root, SECTION)
        entries.append(_entry(section_path, SECTION, node))
        carried.append(node)
        in_scope.update(node.evidence_refs)
        for child in _flatten(document, node):
            name = _element_for(child)
            in_scope.update(child.evidence_refs)
            if name is None:
                continue
            child_path = path_for(section_path, name)
            sub = ET.SubElement(element, name)
            _append_runs(sub, child.runs, child.text)
            entries.append(_entry(child_path, name, child))
            carried.append(child)
        for region in document.unresolved_under(node.id):
            in_scope.update(region.evidence_refs)
    _indent(root)
    root.tail = "\n"
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8", xml_declaration=False)
    out_of_scope = tuple(block.id for block in document.evidence.blocks if block.id not in in_scope)
    source_map = SourceMap(
        profile=document.profile,
        serializer="cfr-granule-xml",
        derivation="reconstructed",
        root=f"/{GRANULE_ROOT}",
        entries=tuple(entries),
        unresolved=tuple(
            region for region in document.unresolved if section is None or region.parent in {n.id for n in chosen}
        ),
        out_of_scope=out_of_scope,
        id_origin=document.evidence.id_origin,
    )
    return Serialized(xml, source_map, tuple(carried))


def _entry(path: str, element: str, node: DocumentNode) -> SourceMapEntry:
    return SourceMapEntry(
        path=path,
        element=element,
        node=node.id,
        kind=node.kind,
        rule=node.decision.rule,
        method=node.decision.method,
        review_status=node.review_status,
        evidence=node.evidence_refs,
        marker=node.marker,
        parent_node=node.parent,
    )


__all__ = [
    "GRANULE_ROOT",
    "ITALIC_EMPHASIS",
    "SECTION",
    "SerializeError",
    "Serialized",
    "SourceMap",
    "SourceMapEntry",
    "serialize_cfr",
]
