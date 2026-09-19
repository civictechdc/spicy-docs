"""Compare two bill versions with DeltaTrack, and shape the result as diff-table rows.

The engine is the sibling Civic Tech DC package (https://github.com/civictechdc/DeltaTrack),
installed by the ``bill-diff`` extra. Nothing here decides which sections
correspond, what a similarity threshold is, or which dollar figures pair: that
is all upstream's, and this module reimplements none of it. What it does is turn
upstream's records into the rows ``section_diffs``, ``section_diff_items`` and
``financial_changes`` hold, carrying the provenance upstream computes and its
own published contract drops.

**Why the stage sequence and not just ``diff_bills``.** ``diff_bills`` returns
``BillDiff``, whose ``NodeDiff`` records say *what* changed and not *why the two
sections were paired*. Upstream's ADR 0020 separates retrieval, evidence,
assignment and classification into public functions precisely so a caller can
hold the middle: ``SettledCorrespondence`` carries the assignment round, and
``Correspondence.evidence`` the named signals — ``word_overlap``, the similarity
score, and ``body_unchanged``. This module runs that same published sequence,
keeps the evidence, and then calls upstream's own ``classify``. The
recomposition is pinned by a test that asserts it produces exactly
``diff_bills``'s change list, so upstream changing the sequence fails here
rather than drifting silently.

**Amount pairing is not an account claim, and is off by default.** Upstream
removed paired amounts from both published contracts (#671, #687): pairing a
figure on one side with a figure on the other and publishing the difference is a
claim about an account, and an appropriations paragraph mixes top-line
appropriations, sub-allocations, "not to exceed" ceilings and loan-guarantee
limitations with nothing distinguishing them. ``match_amounts`` remains public
and tested upstream, and ``financial_changes`` has
``from_amount``/``to_amount``/``delta`` columns to fill, so the pairing is
offered here — behind ``diff_sections(..., pair_amounts=True)``, and only for a
section whose amounts actually changed. The default output carries
``amounts_changed`` and the two multisets, which are facts that need no account
model to be true.

**Complexity.** The matching is upstream's and is bounded by upstream's guards:
retrieval gates every candidate ratio behind ``real_quick_ratio`` and
``quick_ratio``, documented upper bounds on ``ratio``, so the O(w²) alignment
runs only for pairs that can still clear the threshold. Shaping the rows is one
linear pass over the settled correspondences.

**This module adds one cost upstream's published path does not pay.**
``match_amounts`` runs ``SequenceMatcher(autojunk=False)`` over both bodies'
words — O(w²) per section, with the popular-element heuristic that would cap it
switched off, because that heuristic is what would drop a repeated ``$1,000``
out of the alignment. Upstream's own ``bill_diff_to_dict`` stopped calling it
when #687 removed the field.

The quadratic is not theoretical, and it bites on exactly the text this is for.
Measured on one section pair: 8,000 words of *distinct* wording pairs in 0.007 s,
but 8,000 words of repetitive appropriations phrasing ("For necessary expenses
of", "not to exceed", "to remain available until expended") takes 0.46 s, and
16,000 words 1.88 s — four times the cost for twice the input. Two gates keep it
off the common path: it runs only under ``pair_amounts=True``, and then only for
a section whose amounts changed, which in a real version pair is a small
minority of sections and in a self-diff is none.

The three caps BillTrax's TypeScript fork learned in production — a
collision-group cap, an asymmetric-pair guard and a body-size cap on inline word
segments — have no upstream equivalent; they are recorded for upstream in
``docs/sources/congress-bill-tree.md`` rather than patched in here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from spicy_docs.sources.congress.bill_tree import BillDocument, engine_available

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deltatrack.bill_tree import BillNode

# section-diff.ts:46 and upstream's _count_changes agree on this vocabulary.
OPS = ("added", "removed", "modified", "unchanged", "moved")

EXTRA_REQUIRED = "section diffing needs the 'bill-diff' extra: uv sync --extra bill-diff"


class SectionDiffError(ValueError):
    """Two versions cannot be compared as they were given."""


def _engine() -> tuple[Any, Any]:
    """DeltaTrack's ``diff_bill`` and ``similarity``, or a refusal naming the extra."""
    try:
        from deltatrack import diff_bill, similarity
    except ModuleNotFoundError as error:  # pragma: no cover - exercised by the skip guard
        raise SectionDiffError(EXTRA_REQUIRED) from error
    return diff_bill, similarity


@dataclass(frozen=True, slots=True)
class AmountPair:
    """One ``financial_changes`` row.

    A row states that these two figures sit at the same place in the word-level
    alignment of the two texts. It does **not** state that they are the same
    account: upstream removed exactly this pairing from its published contracts
    for that reason, and #115 is where the account model that would justify it
    lives. ``label`` carries the section heading, which BillTrax left as ``""``
    at every construction site, so the column held nothing in every row written.
    """

    label: str
    from_amount: int | None
    to_amount: int | None
    delta: int | None


@dataclass(frozen=True, slots=True)
class FinancialChange:
    """Upstream's multiset facts about one section's money, plus the offered pairing.

    ``from_amounts``, ``to_amounts`` and ``amounts_changed`` are upstream's
    published contract and need no account model to be true. ``pairs`` is the
    alignment described in :class:`AmountPair`.
    """

    from_amounts: tuple[int, ...]
    to_amounts: tuple[int, ...]
    amounts_changed: bool
    has_amendment_annotations: bool
    pairs: tuple[AmountPair, ...]


@dataclass(frozen=True, slots=True)
class SectionDiffItem:
    """One ``section_diff_items`` row, with the provenance upstream computed.

    ``pairing_rule`` is the upstream assignment round that selected this
    correspondence, ``similarity`` its ``word_overlap`` signal, and ``evidence``
    every named signal the round recorded. ``from_element_id``/``to_element_id``
    are the publisher's own ``id`` attributes, which is what a writer resolves
    ``from_sec_id``/``to_sec_id`` against.
    """

    seq: int
    op: str
    similarity: float | None
    moved: bool
    pairing_rule: str
    evidence: Mapping[str, object]
    match_path: tuple[str, ...]
    display_path_old: tuple[str, ...] | None
    display_path_new: tuple[str, ...] | None
    section_number: str
    heading: str
    from_element_id: str
    to_element_id: str
    from_text: str | None
    to_text: str | None
    text_diff: tuple[str, ...] | None
    financial: FinancialChange | None


@dataclass(frozen=True, slots=True)
class SectionDiff:
    """One ``section_diffs`` row and its items. ``summary`` counts each op."""

    from_version: str
    to_version: str
    summary: Mapping[str, int]
    items: tuple[SectionDiffItem, ...]


@dataclass(frozen=True, slots=True)
class VersionRef:
    """The three fields :func:`pair_type` needs from one ``bill_versions`` row."""

    version_id: str
    source: str
    equivalent_xml_version_id: str | None = None


#: A version row whose body is a PDF and nothing else. It has no XML to read.
PDF_ONLY_SOURCES = frozenset({"upload", "govinfo-pdf"})
#: A version row that carries bill XML.
XML_SOURCES = frozenset({"congress", "govinfo"})


def pair_type(base_id: str, new_id: str, versions: Sequence[VersionRef]) -> str:
    """Which comparison strategy a version pair calls for: xml-xml, pdf-pdf or pdf-xml.

    From BillTrax's ``pair-type.ts``, which has no upstream counterpart:
    DeltaTrack compares two XML documents or two PDFs and does not model a
    catalog of versions with uploads and twins in it.

    Each side is classified on its own, which the original did not do. It asked
    only whether *either* side was an upload, so two uploads and a
    ``govinfo-pdf`` against an upload — pairs with no XML anywhere — both came
    back ``pdf-xml``, naming a comparison neither side can supply. Classified
    independently:

    - a PDF-only row (an upload, or a GovInfo PDF) reads as a PDF;
    - an XML row reads as XML, and can *also* be read as a PDF when it has a
      GovInfo PDF twin.

    Two XML rows compare as XML even when a twin exists, because the twin is a
    fallback for reaching a PDF-only counterpart and XML is the better reading
    when both sides have it. A shape this does not cover — an unknown version
    id, or a ``source`` outside the two vocabularies — refuses rather than
    guessing a strategy.
    """
    by_id = {version.version_id: version for version in versions}
    sides = []
    for version_id in (base_id, new_id):
        version = by_id.get(version_id)
        if version is None:
            raise SectionDiffError(f"pair_type was given no version row for {version_id!r}")
        if version.source not in PDF_ONLY_SOURCES | XML_SOURCES:
            raise SectionDiffError(f"pair_type does not cover a {version.source!r} version")
        sides.append(version)

    base, new = sides
    if base.source in PDF_ONLY_SOURCES and new.source in PDF_ONLY_SOURCES:
        return "pdf-pdf"
    if base.source in XML_SOURCES and new.source in XML_SOURCES:
        return "xml-xml"
    xml_side = new if base.source in PDF_ONLY_SOURCES else base
    twin = any(
        version.source == "govinfo-pdf" and version.equivalent_xml_version_id == xml_side.version_id
        for version in versions
    )
    return "pdf-pdf" if twin else "pdf-xml"


def _financial(engine: Any, change: Any, label: str, *, pair_amounts: bool) -> FinancialChange | None:
    """One section's money reading. ``pairs`` is filled only when asked for, and only when it says something.

    Two gates, both deliberate. ``amounts_changed`` false means every figure is
    on both sides, so a pairing could only state that each equals itself —
    rows of ``delta`` 0 that read as findings. And ``pair_amounts`` is off by
    default, so a caller takes the account claim by name rather than by reading
    a field that was already populated. This is the trap upstream's #671/#687
    closed by deleting the field: a populated field that nothing reads presents
    as available, which makes re-publishing the claim the path of least
    resistance.

    Skipping the pairing is also what keeps the common case cheap; see the
    Complexity note in the module docstring.
    """
    stated = engine.compute_financial_change(change.amount_source_old, change.amount_source_new)
    if stated is None:
        return None
    pairs: tuple[AmountPair, ...] = ()
    if pair_amounts and stated.amounts_changed:
        pairs = tuple(
            AmountPair(label, old, new, new - old if old is not None and new is not None else None)
            for old, new in engine.match_amounts(change.amount_source_old, change.amount_source_new)
        )
    return FinancialChange(
        from_amounts=tuple(stated.old_amounts),
        to_amounts=tuple(stated.new_amounts),
        amounts_changed=stated.amounts_changed,
        has_amendment_annotations=stated.has_amendment_annotations,
        pairs=pairs,
    )


def _heading(old_node: BillNode | None, new_node: BillNode | None) -> str:
    for node in (new_node, old_node):
        if node is not None and node.header_text:
            return node.header_text
    return ""


def _settled_nodes(registry: Any, correspondence: Any) -> tuple[BillNode | None, BillNode | None]:
    old = registry.node(correspondence.old[0]) if correspondence.old else None
    new = registry.node(correspondence.new[0]) if correspondence.new else None
    return old, new


def _check_alignment(change: Any, old_node: BillNode | None, new_node: BillNode | None) -> None:
    """Refuse a change record that does not describe the correspondence beside it.

    ``classify`` sorts the settled correspondences by round and emits one record
    each, so position i of its output describes position i of the same stable
    sort. That is an implementation detail of upstream's, and this is it checked
    rather than assumed: a reordering there would otherwise attach one section's
    provenance to another section's change.
    """
    expected_old = old_node.body_text if old_node is not None else None
    expected_new = new_node.body_text if new_node is not None else None
    if change.old_text != expected_old or change.new_text != expected_new:
        raise SectionDiffError(
            "the engine's change records and settled correspondences are no longer in one order; "
            "provenance cannot be attached to the right section"
        )


def diff_sections(
    old: BillDocument,
    new: BillDocument,
    *,
    from_version: str,
    to_version: str,
    pair_amounts: bool = False,
) -> SectionDiff:
    """Compare two parsed versions and return the rows the diff tables hold.

    ``from_version`` and ``to_version`` are the caller's own version identifiers:
    the engine reads the publisher's XML, not the caller's key space.

    ``pair_amounts`` fills ``FinancialChange.pairs``, the ``from_amount`` /
    ``to_amount`` / ``delta`` columns of ``financial_changes``. It is off by
    default because that pairing is a claim about an *account* that upstream
    declines to publish, and because a field populated by default is a field
    that gets read by accident; see :func:`_financial`. Even when asked for, a
    section whose amounts did not change contributes no rows.
    """
    engine, similarity = _engine()
    old_tree, new_tree = old.tree, new.tree
    # Keyed off the engine's own round constants rather than the literals 1 and
    # 2, so a renumbering upstream reaches the rule names instead of silently
    # making every row read "unpaired".
    round_rules = {engine.PATH_ROUND: "path-round", engine.MOVE_ROUND: "move-round"}

    # Upstream's published stage sequence, as diff_bills runs it. Pinned against
    # diff_bills by tests/test_section_diff.py so this cannot drift unnoticed.
    registry = engine.observation_registry(old_tree, new_tree)
    pairings = engine.match_nodes(old_tree, new_tree)
    round1 = engine.similarity_correspondence_evidence(pairings, registry)
    pairs = engine.apply_similarity_assignment_rule(
        pairings, round1, registry, threshold=similarity.SIMILARITY_THRESHOLD
    )
    population = engine.unmatched_population(pairs, registry)
    candidates = engine.retrieve_move_candidates(population, bound=similarity.MOVE_THRESHOLD)
    evidence = engine.move_correspondence_evidence(candidates)
    moves = engine.assign_moves(population, evidence, threshold=similarity.MOVE_THRESHOLD)
    settled = engine.settle_correspondences(pairs, registry, moves, round1_evidence=round1)
    changes = engine.classify(settled, registry)
    ordered = sorted(settled, key=lambda item: item.round)

    items: list[SectionDiffItem] = []
    for seq, (change, item) in enumerate(zip(changes, ordered, strict=True)):
        old_node, new_node = _settled_nodes(registry, item.correspondence)
        _check_alignment(change, old_node, new_node)
        signals = dict(item.correspondence.evidence[0].signals) if item.correspondence.evidence else {}
        overlap = signals.get(engine.WORD_OVERLAP)
        heading = _heading(old_node, new_node)
        items.append(
            SectionDiffItem(
                seq=seq,
                op=change.change_type,
                similarity=round(float(overlap), 4) if isinstance(overlap, (int, float)) else None,
                moved=change.change_type == "moved",
                pairing_rule=round_rules.get(item.round, "unpaired") if item.correspondence.evidence else "unpaired",
                evidence=MappingProxyType(signals),
                match_path=tuple(change.match_path),
                display_path_old=tuple(change.display_path_old) if change.display_path_old else None,
                display_path_new=tuple(change.display_path_new) if change.display_path_new else None,
                section_number=change.section_number,
                heading=heading,
                from_element_id=change.element_id_old,
                to_element_id=change.element_id_new,
                from_text=change.old_text,
                to_text=change.new_text,
                text_diff=tuple(change.text_diff) if change.text_diff else None,
                financial=_financial(engine, change, heading, pair_amounts=pair_amounts),
            )
        )

    counts = {op: 0 for op in OPS}
    for entry in items:
        counts[entry.op] = counts.get(entry.op, 0) + 1
    return SectionDiff(
        from_version=from_version,
        to_version=to_version,
        summary=MappingProxyType(counts),
        items=tuple(items),
    )


__all__ = [
    "EXTRA_REQUIRED",
    "OPS",
    "AmountPair",
    "FinancialChange",
    "SectionDiff",
    "SectionDiffError",
    "SectionDiffItem",
    "VersionRef",
    "diff_sections",
    "engine_available",
    "pair_type",
]
