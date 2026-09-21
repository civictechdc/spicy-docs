"""Five separate findings over one reconstruction, and the gates as a pure function over them.

They are separate because they fail for different reasons and a caller acts on
each differently -- a schema violation is a serializer bug, a content mismatch
an extraction or join bug, a structural mismatch a parser bug, and an
uncovered block honest ignorance -- so collapsing them into one score would
hide which. :func:`schema_validity` validates with lxml against the profile's
pinned bundle using a **local catalog and no network** (the document's own
``noNamespaceSchemaLocation`` is refused rather than fetched) and is the one
check needing the ``reconstruct`` extra; :func:`content_fidelity`,
:func:`structural_fidelity` and :func:`coverage` are standard library, and
:func:`acceptance` applies the §3.3 gates over the other four findings and
nothing else, so a stored finding set re-decides the same way. ``check`` runs
all five, everything ``O(C)`` in the compared characters except schema
validation, which is lxml's.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

from spicy_docs.extraction.gpo_normalize import normalize_gpo_glyphs

from . import EXTRA_REQUIRED
from .evidence import EvidenceDocument
from .parse import SECTION_ROOT, ReconstructedDocument, marker_pairs
from .profiles import CFR_PROFILE, Profile, check_schema_bundle, schema_path
from .serialize import SECTION, Serialized


#: §3.3's engineering targets, as data so a caller can state the slice they ran against.
@dataclass(frozen=True, slots=True)
class Gates:
    """The proposal's §3.3 thresholds. Targets, not results."""

    schema_valid: bool = True
    text_precision: float = 0.999
    text_recall: float = 0.999
    hierarchy_f1: float = 0.98
    critical_discrepancies: int = 0
    coverage_complete: bool = True


DEFAULT_GATES = Gates()


class ValidateError(ValueError):
    """A finding cannot be produced from what was supplied."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's answer: its name, whether it passed, and the numbers behind that."""

    check: str
    passed: bool
    detail: str
    measures: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed, "detail": self.detail, "measures": dict(self.measures)}


# --- 1. schema validity -------------------------------------------------------------


def schema_validity(xml: bytes, *, profile: Profile = CFR_PROFILE) -> Finding:
    """Validate against the pinned bundle with a local catalog and no network.

    The document's own ``noNamespaceSchemaLocation`` is *not* followed: the
    schema is the one the profile pins, read from this package and checked
    against its digest first, so what a document claims about its schema can
    never decide what it is validated against. Raises ``ValidateError`` when
    the extra is missing or the profile pins anything but one schema file.
    """
    try:
        # lxml ships no type stubs; `_catalog` below states the one shape used.
        from lxml import etree  # ty: ignore[unresolved-import]
    except ModuleNotFoundError as error:  # pragma: no cover - exercised by the skip guard
        raise ValidateError(EXTRA_REQUIRED) from error
    entries = list(check_schema_bundle(profile))
    if len(entries) != 1:
        raise ValidateError(f"profile {profile.identity} pins {len(entries)} schema files; this check reads one")
    # no_network and the catalog are two independent refusals of the same thing.
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    parser.resolvers.add(_catalog(etree, profile))
    with schema_path(entries[0]).open("rb") as handle:
        schema = etree.XMLSchema(etree.parse(handle, parser))
    try:
        document = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError as error:
        return Finding("schema_validity", False, f"the serialized XML is not well formed: {error}", {"errors": 1})
    passed = bool(schema.validate(document))
    errors = [f"{entry.path}: {entry.message}" for entry in schema.error_log]
    return Finding(
        "schema_validity",
        passed,
        f"valid against {entries[0].name}" if passed else "; ".join(errors[:5]),
        {"schema": entries[0].name, "sha256": entries[0].sha256, "errors": len(errors), "catalogOnly": True},
    )


def _catalog(etree: Any, profile: Profile) -> Any:
    """A resolver that answers only with files this profile pins, and refuses everything else.

    It subclasses ``etree.Resolver``, which exists only when the extra is
    installed, so the class is built here rather than at module scope: core
    must import this module without lxml present.
    """
    allowed = {entry.name: entry for entry in profile.schema_bundle}

    class LocalCatalog(etree.Resolver):  # type: ignore[misc, name-defined]
        def resolve(self, system_url: str, public_id: str, context: Any) -> Any:
            entry = allowed.get((system_url or "").rsplit("/", 1)[-1])
            if entry is None:
                raise ValidateError(
                    f"schema validation refused to resolve {system_url!r}; only the pinned bundle resolves"
                )
            return self.resolve_filename(str(schema_path(entry)), context)

    return LocalCatalog()


# --- 2. content fidelity ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizationRule:
    """One named, recorded step of the comparison normalization."""

    name: str
    statement: str


#: What is normalized before two texts are compared, in order. Each step is
#: named and its effect is counted, so a reader can see what the equality was
#: allowed to ignore. Nothing here removes a word, a number or a negation.
NORMALIZATION_RULES: tuple[NormalizationRule, ...] = (
    NormalizationRule("unicode_nfc", "Unicode NFC, so one accented character compares equal to its decomposition"),
    NormalizationRule("quotes", "Typographic quotes and apostrophes to their ASCII spelling"),
    NormalizationRule("dashes", "Non-breaking hyphen and soft hyphen to the ASCII hyphen; the em and en dash stay"),
    NormalizationRule("spaces", "Every whitespace run, including a non-breaking space, to one space"),
    NormalizationRule("trim", "Leading and trailing whitespace"),
)

_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "′": "'", "″": '"'}
_DASHES = {"‑": "-", "­": "-"}
_SPACES = re.compile(r"\s+")


def normalize_for_comparison(text: str) -> tuple[str, dict[str, int]]:
    """Apply :data:`NORMALIZATION_RULES` in order, returning the text and what each rule touched."""
    counts: dict[str, int] = {}
    composed = unicodedata.normalize("NFC", text)
    counts["unicode_nfc"] = sum(1 for a, b in zip(text, composed, strict=False) if a != b) + abs(
        len(text) - len(composed)
    )
    counts["quotes"] = sum(composed.count(char) for char in _QUOTES)
    for char, plain in _QUOTES.items():
        composed = composed.replace(char, plain)
    counts["dashes"] = sum(composed.count(char) for char in _DASHES)
    for char, plain in _DASHES.items():
        composed = composed.replace(char, plain)
    collapsed = _SPACES.sub(" ", composed)
    counts["spaces"] = len(composed) - len(collapsed)
    stripped = collapsed.strip()
    counts["trim"] = len(collapsed) - len(stripped)
    return stripped, counts


def _tokens(text: str) -> list[str]:
    return text.split(" ") if text else []


#: Every dash a publisher sets inside a number. The en dash is the one that
#: matters most and was the one originally missing: GPO's print sets a range
#: as ``95–87`` where its own XML spells it ``95-87``, so a class built from
#: the ASCII hyphen alone could not see a changed digit on either side of the
#: dominant spelling. A check that cannot fail on the corpus's own spelling is
#: not a check.
#: Written as regex escapes, with the ASCII hyphen escaped, so the class is
#: correct wherever it is interpolated rather than only when it happens to sit
#: last (an unescaped ``-`` after ``§`` silently became the range ``§``-``‐``,
#: which admitted hundreds of characters and not the hyphen itself).
_DASHES_IN_NUMBERS = r"\-‐‑‒–—―"
#: What may follow the first digit of a numeric token: more digits, the
#: separators a citation uses, a dash of any spelling, and letters, so that
#: ``30-day``, ``95th`` and ``716.2a`` are one token rather than a number
#: followed by something this check stops looking at.
_NUMERIC_TAIL = rf"[0-9A-Za-z,.:;/()§{_DASHES_IN_NUMBERS}]*"
#: A month, spelled as the Federal Register and the CFR spell it. A date is
#: critical under §3.3, and half of a printed date is a word.
_MONTHS = (
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
    "|January|February|March|April|June|July|August|September|October|November|December"
)
_NEGATIONS = "no|not|nor|none|never|neither|nothing|unless|except|without|fail|fails|failure"
#: Trailing punctuation a word carries into a space-split token: a negation at
#: the end of a clause reaches here as ``not,`` or ``otherwise.``
_WORD_TAIL = r"[,.;:)\]]*"

#: A discrepancy in one of these is critical: §3.3 admits no unresolved change
#: to a number, a date, a negation or a provision marker.
#:
#: What it still cannot see, stated so nobody reads a zero as proof: a changed
#: word that is none of these (an amount written out as "twenty", a changed
#: unit, a changed proper noun), and a number that both renditions spell the
#: same way but place differently. The count is a floor on the critical
#: differences between two token streams, not a ceiling on the errors between
#: two documents.
_CRITICAL = re.compile(
    rf"^(?:"
    rf"\$?[0-9]{_NUMERIC_TAIL}%?"  # 95–87, $500, 10%, 30-day, 716.2(a), 1977,
    rf"|(?:{_MONTHS})\.?{_WORD_TAIL}"  # Dec., September,
    rf"|(?:{_NEGATIONS}){_WORD_TAIL}"  # not, unless,
    rf"|\([0-9A-Za-z]{{1,6}}\){_WORD_TAIL}"  # (a), (iii),
    rf")$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TextComparison:
    """Precision and recall over normalized word tokens, the critical tokens that differ, and what the normalization touched.

    ``normalization`` is :data:`NORMALIZATION_RULES`' per-rule counts summed
    over both sides; it travels with the comparison rather than being thrown
    away inside it, because a rule that fired on nothing and a rule that folded
    a thousand characters make the same equality and mean opposite things.
    """

    precision: float
    recall: float
    reference_tokens: int
    candidate_tokens: int
    matched_tokens: int
    critical: tuple[str, ...]
    normalization: Mapping[str, int] = field(default_factory=dict)


def compare_text(reference: str, candidate: str) -> TextComparison:
    """Token precision and recall between a reference text and a reconstruction, ``O(n log n)`` in practice."""
    left_text, left_counts = normalize_for_comparison(reference)
    right_text, right_counts = normalize_for_comparison(candidate)
    left, right = _tokens(left_text), _tokens(right_text)
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    critical: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        critical.extend(token for token in left[i1:i2] if _CRITICAL.match(token))
        critical.extend(token for token in right[j1:j2] if _CRITICAL.match(token))
    return TextComparison(
        precision=matched / len(right) if right else 0.0,
        recall=matched / len(left) if left else 0.0,
        reference_tokens=len(left),
        candidate_tokens=len(right),
        matched_tokens=matched,
        critical=tuple(critical),
        normalization={rule.name: left_counts[rule.name] + right_counts[rule.name] for rule in NORMALIZATION_RULES},
    )


def content_fidelity(serialized: Serialized, evidence: EvidenceDocument) -> Finding:
    """Every character the serialized XML carries must come from the evidence it names.

    The comparison is per element, against exactly the blocks the source map
    names for it, so a paragraph cannot pass by borrowing text from another;
    that is the direction that matters here, because the coverage finding, not
    this one, says whether evidence was left out.
    """
    total = matched = 0
    mismatched: list[str] = []
    touched = {rule.name: 0 for rule in NORMALIZATION_RULES}
    # Index both sides once. Walking the node list and the block list per
    # entry made this O(E·N + E·B) on a document where O(E + N + B) does.
    nodes = {node.id: node for node in serialized.nodes}
    blocks = {block.id: block for block in evidence.blocks}
    for entry in serialized.source_map.entries:
        node = nodes.get(entry.node)
        if node is None or entry.element == SECTION:
            continue
        source = normalize_gpo_glyphs(" ".join(blocks[block_id].text for block_id in entry.evidence))
        wanted, wanted_counts = normalize_for_comparison(node.text)
        available, available_counts = normalize_for_comparison(source)
        for rule in NORMALIZATION_RULES:
            touched[rule.name] += wanted_counts[rule.name] + available_counts[rule.name]
        total += 1
        # The join removes a print wrap's hyphen, so the node's text is not a
        # substring of its evidence; comparing the two with the hyphen and the
        # spaces taken out compares what the join was allowed to do.
        if _welded(wanted) in _welded(available):
            matched += 1
        else:
            mismatched.append(entry.path)
    passed = not mismatched
    return Finding(
        "content_fidelity",
        passed,
        "every element's text is its own evidence's text"
        if passed
        else f"{len(mismatched)} elements carry text their evidence does not: {', '.join(mismatched[:3])}",
        {
            "elements": total,
            "matched": matched,
            "mismatched": len(mismatched),
            "normalization": touched,
        },
    )


def _welded(text: str) -> str:
    """The comparison spelling, and what each part of it deliberately cannot see.

    Spaces and hyphens go, because the join removes a print wrap's hyphen and
    adds a space between lines; case goes, because the print encodes small
    capitals as *size* rather than as case, so the restored case comes from the
    style observation and not from the characters. What survives is every
    letter, digit and mark in order -- which is what this check is for: that an
    element's text came from the evidence the source map names for it, and not
    from somewhere else in the document.
    """
    return text.replace(" ", "").replace("-", "").casefold()


# --- 3. structural fidelity ----------------------------------------------------------


def document_marker_pairs(document: ReconstructedDocument, *, section: str | None = None) -> set[tuple[str, str]]:
    """``(parent marker, child marker)`` for every marked paragraph: the parser's own tree, as comparable pairs.

    ``section`` restricts the pairs to one section's descendants, which is
    what a paired comparison against one published granule needs.
    """
    inside = None
    if section is not None:
        node = document.section(section)
        inside = {node.id for node in document.descendants(node.id)} if node is not None else set()
    # A paragraph hanging directly from its section hangs from the root of the
    # ladder, not from the section's number: a section number is an address,
    # not a paragraph designation, and pairing against it would compare two
    # different things on the reference and candidate sides.
    markers = {node.id: (None if node.kind == "section" else node.marker) for node in document.nodes}
    pairs: set[tuple[str, str]] = set()
    for node in document.nodes:
        if node.kind != "paragraph" or node.marker is None or (inside is not None and node.id not in inside):
            continue
        parent = markers.get(node.parent or "") if node.parent else None
        pairs.add((parent or SECTION_ROOT, node.marker))
    return pairs


def structural_fidelity(document: ReconstructedDocument, *, expected_sections: Sequence[str] | None = None) -> Finding:
    """Section boundaries and marker hierarchy: are the sections the ones expected, and is the ladder sound?

    When ``expected_sections`` names exactly one section the marker check is
    scoped to it, because a section PDF is a page range that carries its
    neighbours and their markers belong to another granule. The section list
    the rendition yielded is reported either way, so the boundary is visible
    rather than assumed.
    """
    found = [node.marker for node in document.sections() if node.marker]
    unnumbered = [node for node in document.sections() if not node.marker]
    scope: set[str] | None = None
    scoped: str | None = None
    if expected_sections is not None and len(expected_sections) == 1:
        scoped = expected_sections[0]
        node = document.section(scoped)
        scope = {child.id for child in document.descendants(node.id)} if node is not None else set()
    out_of_sequence = [
        node.marker
        for node in document.nodes
        if node.kind == "paragraph" and node.review_status == "needs_review" and (scope is None or node.id in scope)
    ]
    problems: list[str] = []
    if expected_sections is not None:
        missing = [number for number in expected_sections if number not in found]
        if missing:
            problems.append(f"sections not found: {', '.join(missing)}")
    if unnumbered and expected_sections is None:
        problems.append(f"{len(unnumbered)} run(s) of text before the first section heading")
    if out_of_sequence:
        problems.append(
            f"{len(out_of_sequence)} marker(s) out of sequence: {', '.join(str(m) for m in out_of_sequence[:3])}"
        )
    return Finding(
        "structural_fidelity",
        not problems,
        "; ".join(problems) if problems else f"{len(found)} section(s), marker ladder consistent",
        {
            "sections": found,
            "unnumberedSections": len(unnumbered),
            "markersOutOfSequence": len(out_of_sequence),
            "markerPairs": len(document_marker_pairs(document, section=scoped)),
            "scopedToSection": scoped,
        },
    )


@dataclass(frozen=True, slots=True)
class HierarchyComparison:
    """F1 over parent-child marker pairs, with both sides' counts kept.

    Both counts are kept because either one being zero means something
    different and a caller filtering on one of them alone hides the other: a
    reference with no ladder is a section the publisher wrote without
    designations, while a candidate with no ladder against a reference that
    has one is a ladder the parser missed, and a candidate with a ladder
    against a reference without one is a ladder the parser invented.
    """

    f1: float
    shared: int
    reference_pairs: int
    candidate_pairs: int

    @property
    def has_ladder(self) -> bool:
        """Whether either side proposed a ladder at all, which is when the F1 says anything."""
        return bool(self.reference_pairs or self.candidate_pairs)


def hierarchy_f1(reference: set[tuple[str, str]], candidate: set[tuple[str, str]]) -> tuple[float, int, int, int]:
    """F1 over ``(parent marker, child marker)`` pairs, and the three counts behind it.

    Both sides are pair sets so a reference read from the publisher's own
    ``<P>`` markers (``parse.marker_pairs``) compares with a candidate read
    from the print (``document_marker_pairs``) on the one ladder. **Two empty
    sides agree**, with 1.0 and both counts zero: plenty of CFR sections are a
    single undesignated paragraph and scoring that 0.0 would report
    disagreement where both sides say the same thing; a caller wanting the mean
    over sections that *have* a ladder filters on ``reference_pairs``.
    """
    left, right = reference, candidate
    shared = len(left & right)
    if not left and not right:
        return 1.0, 0, 0, 0
    precision = shared / len(right) if right else 0.0
    recall = shared / len(left) if left else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, shared, len(left), len(right)


# --- 4. coverage ----------------------------------------------------------------------


def coverage(document: ReconstructedDocument, serialized: Serialized | None = None) -> Finding:
    """Every block is classified; what is not is listed, and out-of-scope evidence is not loss."""
    classified = {block_id for node in document.nodes for block_id in node.evidence_refs}
    unresolved = {block_id for region in document.unresolved for block_id in region.evidence_refs}
    blocks = {block.id for block in document.evidence.blocks}
    unaccounted = sorted(blocks - classified - unresolved)
    out_of_scope = len(serialized.source_map.out_of_scope) if serialized is not None else 0
    review = [node.id for node in document.nodes if node.review_status != "accepted"]
    passed = not unaccounted
    return Finding(
        "coverage",
        passed,
        "every evidence block is accounted for"
        if passed
        else f"{len(unaccounted)} block(s) reached no node and no region: {', '.join(unaccounted[:5])}",
        {
            "blocks": len(blocks),
            "classified": len(classified),
            "unresolvedBlocks": len(unresolved),
            "unresolvedRegions": len(document.unresolved),
            "unaccounted": len(unaccounted),
            "outOfScopeBlocks": out_of_scope,
            "nodesNeedingReview": len(review),
            "issues": sorted({region.issue for region in document.unresolved}),
        },
    )


# --- 5. acceptance --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewLoad:
    """What a reviewer would have to look at in the part of the document that was serialized.

    Counted **in scope**: over the elements the source map actually emitted,
    not over the whole rendition, because a section PDF carries its neighbours
    and a flagged marker three sections away is not this granule's problem.
    """

    elements: int
    flagged_nodes: int
    model_nodes: int
    unresolved_regions: int

    @property
    def clean(self) -> bool:
        """Whether this document could be accepted *without review*, which is what §3.3 asks."""
        return not (self.flagged_nodes or self.model_nodes or self.unresolved_regions)


def review_load(serialized: Serialized) -> ReviewLoad:
    """Count the in-scope decisions a reviewer would have to confirm."""
    flagged = model = 0
    for entry in serialized.source_map.entries:
        if entry.review_status != "accepted":
            flagged += 1
        if entry.method == "model":
            model += 1
    return ReviewLoad(len(serialized.source_map.entries), flagged, model, len(serialized.source_map.unresolved))


def acceptance(
    findings: Sequence[Finding],
    *,
    gates: Gates = DEFAULT_GATES,
    comparison: TextComparison | None = None,
    hierarchy: float | None = None,
    review: ReviewLoad | None = None,
) -> Finding:
    """The §3.3 gates over the findings, as a pure function.

    ``comparison`` and ``hierarchy`` come from a *paired* run, where a
    reference exists; without them the text and hierarchy gates cannot be
    decided, and this says so rather than passing by default, because an
    undecided gate is not a met gate. ``review`` is what §3.3's "accepted
    **without review**" turns on: a flagged, model-placed or unresolved
    in-scope decision is exactly the work a reviewer does, so it blocks
    acceptance.
    """
    by_name = {finding.check: finding for finding in findings}
    reasons: list[str] = []
    undecided: list[str] = []
    schema_finding = by_name.get("schema_validity", Finding("", False, "absent"))
    if gates.schema_valid and not schema_finding.passed:
        # A check that did not run and a check that failed are different
        # answers, and reporting the first as the second would read as a
        # serializer defect that nobody had evidence for.
        reasons.append("schema not checked" if schema_finding.measures.get("skipped") else "schema invalid")
    if not by_name.get("content_fidelity", Finding("", False, "absent")).passed:
        reasons.append("content fidelity failed")
    if gates.coverage_complete and not by_name.get("coverage", Finding("", False, "absent")).passed:
        reasons.append("coverage incomplete")
    if not by_name.get("structural_fidelity", Finding("", False, "absent")).passed:
        reasons.append("structural fidelity failed")
    measures: dict[str, Any] = {"gates": asdict(gates)}
    if comparison is None:
        undecided.append("text precision and recall (no reference)")
    else:
        measures |= {"precision": comparison.precision, "recall": comparison.recall}
        measures["criticalDiscrepancies"] = len(comparison.critical)
        if comparison.precision < gates.text_precision:
            reasons.append(f"precision {comparison.precision:.5f} below {gates.text_precision}")
        if comparison.recall < gates.text_recall:
            reasons.append(f"recall {comparison.recall:.5f} below {gates.text_recall}")
        if len(comparison.critical) > gates.critical_discrepancies:
            reasons.append(f"{len(comparison.critical)} critical discrepancies")
    if hierarchy is None:
        undecided.append("hierarchy F1 (no reference)")
    else:
        measures["hierarchyF1"] = hierarchy
        if hierarchy < gates.hierarchy_f1:
            reasons.append(f"hierarchy F1 {hierarchy:.4f} below {gates.hierarchy_f1}")
    if review is None:
        undecided.append("review load (no serialized document)")
    else:
        measures |= {
            "elementsInScope": review.elements,
            "nodesNeedingReviewInScope": review.flagged_nodes,
            "modelPlacedNodesInScope": review.model_nodes,
            "unresolvedInScope": review.unresolved_regions,
        }
        if not review.clean:
            parts = [
                f"{review.flagged_nodes} flagged node(s)" if review.flagged_nodes else "",
                f"{review.model_nodes} model-placed node(s)" if review.model_nodes else "",
                f"{review.unresolved_regions} unresolved region(s)" if review.unresolved_regions else "",
            ]
            reasons.append("needs review: " + ", ".join(part for part in parts if part))
    measures["undecided"] = undecided
    measures["reasons"] = reasons
    passed = not reasons and not undecided
    detail = "accepted" if passed else "; ".join(reasons + [f"undecided: {item}" for item in undecided])
    return Finding("acceptance", passed, detail, measures)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Every finding, and the two paired measurements the acceptance gate read.

    They are returned rather than recomputed by the caller: the token alignment
    behind ``comparison`` is the most expensive thing this module does, and a
    second run of it could quietly disagree with the one the gate actually
    decided on.
    """

    findings: tuple[Finding, ...]
    comparison: TextComparison | None = None
    hierarchy: HierarchyComparison | None = None

    def __iter__(self) -> Iterator[Finding]:
        """Iterating a result yields its findings, which is what most callers want."""
        return iter(self.findings)

    def by_name(self) -> dict[str, Finding]:
        return {finding.check: finding for finding in self.findings}


def check(
    document: ReconstructedDocument,
    serialized: Serialized,
    *,
    profile: Profile = CFR_PROFILE,
    section: str | None = None,
    reference_text: str | None = None,
    reference_markers: Sequence[str] | None = None,
    gates: Gates = DEFAULT_GATES,
    schema: bool = True,
) -> CheckResult:
    """Run every check; ``schema=False`` skips the one that needs the extra and says so.

    ``section`` is the one section a paired run asked for: the structural
    finding then expects it, and the hierarchy comparison is scoped to it,
    because a section PDF carries its neighbours and their markers are not
    this granule's.
    """
    findings = [
        schema_validity(serialized.xml, profile=profile)
        if schema
        else Finding("schema_validity", False, EXTRA_REQUIRED, {"skipped": True}),
        content_fidelity(serialized, document.evidence),
        structural_fidelity(document, expected_sections=None if section is None else [section]),
        coverage(document, serialized),
    ]
    comparison = None if reference_text is None else compare_text(reference_text, serialized_text(serialized))
    hierarchy = (
        None
        if reference_markers is None
        else HierarchyComparison(
            *hierarchy_f1(marker_pairs(reference_markers), document_marker_pairs(document, section=section))
        )
    )
    findings.append(
        acceptance(
            findings,
            gates=gates,
            comparison=comparison,
            hierarchy=None if hierarchy is None else hierarchy.f1,
            review=review_load(serialized),
        )
    )
    return CheckResult(tuple(findings), comparison, hierarchy)


def serialized_text(serialized: Serialized) -> str:
    """The text the derivative carries, in document order, for a reference comparison.

    The section node itself is left out: its text is the heading line, which
    ``SECTNO`` and ``SUBJECT`` already carry, and counting it would compare a
    sentence the publisher writes once against one written twice.
    """
    return " ".join(node.text for node in serialized.nodes if node.kind != "section" and node.text)


__all__ = [
    "DEFAULT_GATES",
    "NORMALIZATION_RULES",
    "CheckResult",
    "Finding",
    "Gates",
    "HierarchyComparison",
    "NormalizationRule",
    "ReviewLoad",
    "TextComparison",
    "ValidateError",
    "acceptance",
    "check",
    "compare_text",
    "content_fidelity",
    "coverage",
    "document_marker_pairs",
    "hierarchy_f1",
    "normalize_for_comparison",
    "review_load",
    "schema_validity",
    "serialized_text",
    "structural_fidelity",
]
