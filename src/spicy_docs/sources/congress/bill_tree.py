"""Read one GPO bill, resolution or amendment XML with DeltaTrack, accounting for every element.

DeltaTrack is the sibling Civic Tech DC engine that flattens bill XML into
content-bearing nodes (https://github.com/civictechdc/DeltaTrack); nothing here
reimplements it. This module supplies the two things it leaves to its caller:
a bounded, inert parse through :mod:`spicy_docs.reading.xml` as the gate before
the engine sees the document, and an account of what the flattening dropped
(``discarded_elements``, by name per document, since the engine walks only a
fraction of the elements the corpus contains). It handles ``legis-body``,
``resolution-body`` and the amendment chain, and refuses a resolution carrying
paired committee-amendment variants rather than silently rendering the struck
text. Install the engine with the ``bill-diff`` extra; nothing here imports it
at module scope, so the rest of ``spicy_docs`` imports without it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import Element

from spicy_docs.reading.xml import parse_xml

from .bill_status import BillSourceError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deltatrack.bill_tree import BillNode

# The largest file in the 40-file structure sample is 9.4 MB and the deepest
# nests to <subclause>. 24 MiB leaves headroom without admitting an unbounded parse.
DEFAULT_MAX_BYTES = 24 * 1024 * 1024

_VERSION_CHARACTERS = re.compile(r"[^A-Za-z0-9.-]")
EXTRA_REQUIRED = "bill tree reading needs the 'bill-diff' extra: uv sync --extra bill-diff"


def _bill_tree_module() -> Any:
    """DeltaTrack's ``bill_tree``, or a refusal naming the extra that supplies it."""
    try:
        from deltatrack import bill_tree
    except ModuleNotFoundError as error:  # pragma: no cover - exercised by the skip guard
        raise BillSourceError(EXTRA_REQUIRED) from error
    return bill_tree


def engine_available() -> bool:
    """Whether the ``bill-diff`` extra is installed. Tests skip on this rather than fail."""
    try:
        import deltatrack.bill_tree  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class BillDocument:
    """One parsed version: the engine's tree, and this repository's account of the bytes.

    ``tree`` is DeltaTrack's own ``BillTree`` and ``sections`` its ``BillNode``
    list, passed through rather than copied into a local shape: a node carries
    the ``match_path``/``display_path``/``element_id``/header and body text the
    ``bill_sections`` columns need, and more. ``stage`` is the root's own
    ``@bill-stage`` / ``@resolution-stage``; an ``amendment-doc`` states none.
    """

    tree: Any
    root_tag: str
    body_tags: tuple[str, ...]
    stage: str | None
    element_counts: Mapping[str, int]
    kept_elements: Mapping[str, int]
    discarded_elements: Mapping[str, int]

    @property
    def sections(self) -> tuple[BillNode, ...]:
        """The engine's content-bearing nodes, in document order."""
        return tuple(self.tree.nodes)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _accounted_text(nodes: Iterable[BillNode]) -> frozenset[str]:
    """Every string a node carries as *text*, whole and line by line.

    Matching on text lets front-matter elements (``<congress>``,
    ``<legis-num>``, ``<official-title>``) be recognised as read: the engine
    composes those nodes from the ``<form>`` block without recording which
    element each line came from. ``display_path``, ``match_path`` and
    ``division_label`` are deliberately not used, because the engine composes
    them the same way GPO spells a table-of-contents entry, so crediting them
    would mark the whole ``<toc>`` read -- the silent under-report this count
    exists to avoid. The cost is that a title's or division's own ``<header>``
    and ``<enum>`` report as dropped, which is the safe direction.
    """
    accounted: set[str] = set()
    for node in nodes:
        for text in (node.body_text, node.display_text, node.header_text):
            if not text:
                continue
            accounted.add(_collapse(text))
            accounted.update(_collapse(line) for line in text.splitlines() if line.strip())
    accounted.discard("")
    return frozenset(accounted)


# A front-matter field is a handful of elements; a body, division or title holds
# the whole bill. Only the small ones are worth reading text from, and the large
# ones are settled by the container rule below without an O(subtree) join.
_TEXT_RULE_MAX_ELEMENTS = 64


def _inventory(
    root: Element,
    nodes: Sequence[BillNode],
    bodies: Sequence[Element],
) -> tuple[Mapping[str, int], Mapping[str, int], Mapping[str, int]]:
    """Count every element, and split it by whether the output still contains its text.

    Three rules, each measured against this document rather than a tag list
    that would drift upstream: (1) the element sits inside an element whose
    ``id`` the engine put on a node; (2) its own text is one of the strings, or
    lines, the nodes carry -- this accounts for the front matter the engine
    composes without recording a source element; (3) it is a container whose
    children are all read and which contributes no text of its own, meaning
    both ``element.text`` and every child's ``tail``, since GPO mixed content
    puts real words in tails. The root and each body are read by construction:
    their tag, stage attribute and body spelling are what :class:`BillDocument`
    reports.

    **What this cannot see.** It measures whether text survives *somewhere*,
    not whether the flattening read that element: rule 1 credits a whole
    subtree, and rule 2 can credit a coincidence. The error therefore runs
    toward **over**-reporting, so a name in ``discarded_elements`` means
    "nothing downstream can get these words back as a field", not "the engine
    never looked at it".
    """
    node_ids = frozenset(node.element_id for node in nodes if node.element_id)
    accounted = _accounted_text(nodes)
    order = list(root.iter())
    parents: dict[int, Element] = {id(child): element for element in order for child in element}

    inside: dict[int, bool] = {}
    counts: Counter[str] = Counter()
    for element in order:
        counts[element.tag] += 1
        parent = parents.get(id(element))
        enclosed = parent is not None and inside[id(parent)]
        inside[id(element)] = enclosed or element.attrib.get("id", "") in node_ids

    by_construction = {id(root), *(id(body) for body in bodies)}
    read: dict[int, bool] = {}
    size: dict[int, int] = {}
    kept: Counter[str] = Counter()
    # Reversed document order is children-before-parents, so the container rule
    # reads results that are already settled.
    for element in reversed(order):
        children = list(element)
        size[id(element)] = 1 + sum(size[id(child)] for child in children)
        settled = (
            inside[id(element)]
            or id(element) in by_construction
            or (
                size[id(element)] <= _TEXT_RULE_MAX_ELEMENTS
                and (text := _collapse("".join(element.itertext()))) != ""
                and text in accounted
            )
            or (
                bool(children)
                and all(read[id(child)] for child in children)
                and not (element.text or "").strip()
                and not any((child.tail or "").strip() for child in children)
            )
        )
        read[id(element)] = settled

    for element in order:
        if read[id(element)]:
            kept[element.tag] += 1
    return (
        MappingProxyType(dict(counts)),
        MappingProxyType(dict(kept)),
        MappingProxyType(dict(counts - kept)),
    )


def parse_bill_tree(xml_bytes: bytes, *, version: str = "", max_bytes: int = DEFAULT_MAX_BYTES) -> BillDocument:
    """Flatten one bill, resolution or amendment XML into a :class:`BillDocument`.

    ``version`` is the caller's version code ("ih", "eh", "enr"). The engine reads
    a version from the file name it is given rather than from the document, so
    the code is supplied here and reaches it through the temporary file's stem;
    passing nothing leaves ``tree.version`` empty, which is accurate rather than
    guessed.

    The engine's entry point takes a path and parses the file itself, exactly as
    its own ``compare/xml.py`` does for uploaded bytes. It is handed the
    publisher's original bytes, and only after the scan above has bounded them
    and refused any declared entity — so the second parse reads a document
    already proved safe, and no byte is rewritten in between.
    """
    module = _bill_tree_module()
    root = parse_xml(
        xml_bytes,
        max_bytes=max_bytes,
        error_type=BillSourceError,
        label="bill XML",
        allow_external_doctype=True,
    )

    stem = f"bill_{_VERSION_CHARACTERS.sub('', version)}" if version else "bill"
    with TemporaryDirectory(prefix="spicy-docs-bill-tree-") as directory:
        path = Path(directory) / f"{stem}.xml"
        path.write_bytes(xml_bytes)
        try:
            tree = module.normalize_bill(path)
            bodies = module.find_bill_bodies(root)
        except BillSourceError:
            raise
        except ValueError as error:
            # The engine refuses a document it cannot read unambiguously — no body,
            # or a resolution carrying both the struck and the amended text. Its
            # words are the reason; only the type is restated in this package's terms.
            raise BillSourceError(f"bill XML cannot be flattened: {error}") from error

    counts, kept, discarded = _inventory(root, tree.nodes, bodies)
    return BillDocument(
        tree=tree,
        root_tag=root.tag,
        body_tags=tuple(body.tag for body in bodies),
        stage=root.get(f"{root.tag}-stage"),
        element_counts=counts,
        kept_elements=kept,
        discarded_elements=discarded,
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "EXTRA_REQUIRED",
    "BillDocument",
    "engine_available",
    "parse_bill_tree",
]
