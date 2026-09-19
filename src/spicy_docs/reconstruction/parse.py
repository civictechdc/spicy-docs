"""The deterministic CFR structural parser: blocks in, a tree of decisions out.

One pass over the evidence blocks in reading order, ``O(B)`` for ``B``
blocks. Numbering, indentation, typography and context jointly propose the
tree, and every node carries the blocks it rests on and a :class:`Decision`
naming the rule from ``profiles.CFR_RULES`` that placed it.

Three things are rewritten, each by a named profile rule and each visible to
the checks that compare text: the case of a small-capital run
(``small_caps_restore``, because the print encodes case as size), the hyphen
of a print wrap (``wrap_hyphen_rejoin``), and GPO's typewriter quote pairs
(``gpo_quote_pair``, the shared ``normalize_gpo_glyphs`` spelling). Beyond
those, assembly only: a node's text is its blocks' text joined with a single
space between lines, and the serializer's source map leads back to the
blocks.

What the parser reads from a block, in this order (the profile's ladder):

1. **Furniture** -- the printed page number (bottom band, digits only) and
   the running head (top band). Kept as nodes so coverage can account for
   them; never serialized.
2. **Section headings** -- a bold line beginning with ``§`` and a section
   number opens a section; the remainder of the line, and any bold line that
   follows without a ``§``, is the subject.
3. **Part front matter** outside any section -- the part heading, the
   contents list, the AUTHORITY and SOURCE notes. A section PDF is a page
   range of the printed volume (proposal §3.1), so this material and the
   neighbouring sections are expected and are classified, not dropped.
4. **Inside a section** -- small-face lines are a citation (``[...]``), a
   note (a note label) or an unresolved region (a table, or anything else
   the print sets small); body-face lines are paragraphs, opened by a
   first-line indent, with their leading designations as marker and nested
   under ``marker_hierarchy``; a whole-line bold or italic body-face line
   after a vertical gap is a heading.

Where rules cannot decide -- an unresolved small-face run inside a section --
the :class:`ClassifyAndAttach` seam takes an injected model call that chooses
among evidence-backed alternatives or abstains. No model is called in this
module and no default is wired: without a classifier every such run stays an
:class:`UnresolvedRegion`, which is what the coverage check reports.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from spicy_docs.extraction.gpo_normalize import METADATA_RULES, normalize_gpo_glyphs

from .evidence import (
    Decision,
    DocumentNode,
    EvidenceBlock,
    EvidenceDocument,
    StyledRun,
    UnresolvedRegion,
    node_id,
    region_id,
)
from .profiles import CFR_PROFILE, Profile

#: Node kinds the CFR profile places, with the vocabulary element each becomes
#: (``None`` for kinds the serializer leaves out: furniture and part matter
#: outside the section, which the granule vocabulary does not carry).
CFR_KINDS: dict[str, str | None] = {
    "page_number": None,
    "running_head": None,
    "print_footer": None,
    "blank": None,
    "part_heading": None,
    "division_heading": None,
    "contents": None,
    "authority": None,
    "source_note": None,
    "section": "SECTION",
    "section_number": "SECTNO",
    "subject": "SUBJECT",
    "paragraph": "P",
    # The guide's own element for a paragraph set flush rather than indented.
    # The model seam's second alternative places one of these, and it must
    # serialize as what its rule names rather than as an ordinary P.
    "flush_paragraph": "FP",
    "heading": "HD",
    "citation": "CITA",
    "note": "NOTE",
}

_NUMBER = r"[0-9]+(?:-[0-9]+)*\.[0-9]+[A-Za-z]?(?:-[0-9]+[A-Za-z]?)*"
_SECTION_HEADING = re.compile(rf"^§\s*(?P<number>{_NUMBER})\s*(?P<subject>.*)$")
_MARKER = re.compile(r"^(?P<marker>(?:\([0-9A-Za-z]{1,6}\))+)")
_DESIGNATION = re.compile(r"\(([0-9A-Za-z]{1,6})\)")
_CONTENTS_ENTRY = re.compile(rf"^{_NUMBER}\s")
_PAGE_NUMBER = re.compile(r"^[0-9]{1,4}$")
_NOTE_LABEL = re.compile(r"^(NOTE|EDITORIAL NOTE|EFFECTIVE DATE NOTE|CROSS REFERENCE)S?\b")
_PART_HEADING = re.compile(r"^PART\s+[0-9]")
_LEADERS = re.compile(r"\.{4,}|(?:\. ){4,}")
_ROMAN = re.compile(r"^[ivxlc]+$")

#: Page bands the running head and the page number sit in (``running_head_furniture``, ``page_number_furniture``).
TOP_BAND = 0.215
BOTTOM_BAND = 0.9
#: ``first_line_indent``: 4 pt of a 612 pt page.
INDENT = 4 / 612
#: A face is small or large when it differs from the body size by at least this much.
SIZE_STEP = 0.5
#: A run is the reduced part of a small-capital setting when it sits at least
#: this far below its line's full size. Measured on the corpus: body 8.0 pt
#: beside small-cap 6.5 pt, and note 7.0 pt beside small-cap 5.7 pt, so a
#: 0.5 pt difference never qualifies and both real settings do.
SMALL_CAP_STEP = 1.0
#: A vertical gap at least this many body line pitches above a line marks a heading (``heading_hd``).
HEADING_GAP = 1.6
#: ``table_region``: a small-face line assembled from at least this many fragments reads as a table row.
TABLE_FRAGMENTS = 3
#: ``print_shop_footer``: the two ``extraction.gpo_normalize`` rules that name
#: GPO's own print-shop chrome. Reused rather than restated, so the corpus that
#: measured them is the corpus this rule rests on.
_PRINT_SHOP_RULES = tuple(rule for rule in METADATA_RULES if rule.name in ("verdate_footer", "dsk_user"))


class ParseError(ValueError):
    """The evidence cannot be parsed under this profile."""


# --- the model seam ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Alternative:
    """One evidence-backed way to place a run of blocks; the model chooses among these or abstains."""

    kind: str
    rule: str
    statement: str


@dataclass(frozen=True, slots=True)
class Classification:
    """``choice`` indexes ``alternatives``; ``None`` is an abstention and leaves the run unresolved."""

    choice: int | None
    reason: str
    model: str | None = None


class ClassifyAndAttach(Protocol):
    """A bounded model call over one unresolved run: it never sees or returns text, only a choice."""

    def __call__(
        self,
        *,
        blocks: tuple[EvidenceBlock, ...],
        context: tuple[DocumentNode, ...],
        alternatives: tuple[Alternative, ...],
    ) -> Classification: ...


#: What a model may choose for a small-face run inside a section; the print gives no cell structure, so
#: ``table`` stays unresolved even when chosen and is only labelled.
SMALL_FACE_ALTERNATIVES: tuple[Alternative, ...] = (
    Alternative("note", "note_line", "a note or editorial note set small under the section"),
    Alternative("flush_paragraph", "flush_paragraph_fp", "an extract or flush paragraph set small"),
    Alternative("table", "table_region", "a table; left unresolved with the label attached"),
)


# --- output -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconstructedDocument:
    """The tree: nodes in reading order (``parent`` links make the tree), plus what stayed unresolved."""

    profile: str
    evidence: EvidenceDocument
    nodes: tuple[DocumentNode, ...]
    unresolved: tuple[UnresolvedRegion, ...]

    def node(self, identifier: str) -> DocumentNode:
        for node in self.nodes:
            if node.id == identifier:
                return node
        raise ParseError(f"no node {identifier!r}")

    def children(self, identifier: str | None) -> tuple[DocumentNode, ...]:
        return tuple(node for node in self.nodes if node.parent == identifier)

    def sections(self) -> tuple[DocumentNode, ...]:
        return tuple(node for node in self.nodes if node.kind == "section")

    def section(self, number: str) -> DocumentNode | None:
        return next((node for node in self.sections() if node.marker == number), None)

    def descendants(self, identifier: str) -> tuple[DocumentNode, ...]:
        """Every node under ``identifier`` in reading order, ``O(N)``."""
        inside = {identifier}
        found: list[DocumentNode] = []
        for node in self.nodes:
            if node.parent in inside:
                inside.add(node.id)
                found.append(node)
        return tuple(found)

    def unresolved_under(self, identifier: str) -> tuple[UnresolvedRegion, ...]:
        return tuple(region for region in self.unresolved if region.parent == identifier)


# --- geometry ---------------------------------------------------------------------


@dataclass
class _Geometry:
    """What the profile measures once over the whole evidence: the body size, the pitch and the column edges."""

    body_size: float | None
    pitch: float
    left_edges: dict[tuple[int, int], float]
    page_numbers: dict[int, str]

    def face(self, block: EvidenceBlock) -> str:
        size = block.size
        if size is None or self.body_size is None:
            return "body"
        if size <= self.body_size - SIZE_STEP:
            return "small"
        if size >= self.body_size + SIZE_STEP:
            return "large"
        return "body"

    def indent(self, block: EvidenceBlock) -> float | None:
        if block.box is None or block.page is None:
            return None
        edge = self.left_edges.get((block.page, _half(block)))
        return None if edge is None else block.box.x0 - edge


def _half(block: EvidenceBlock) -> int:
    return 0 if block.box is None or block.box.x0 < 0.5 else 1


def _is_page_number(block: EvidenceBlock) -> bool:
    return (
        block.box is not None and block.box.y0 > BOTTOM_BAND and _PAGE_NUMBER.fullmatch(block.text.strip()) is not None
    )


def _is_running_head(block: EvidenceBlock) -> bool:
    return block.box is not None and block.box.y1 < TOP_BAND


def _measure(evidence: EvidenceDocument) -> _Geometry:
    """``column_left_edge`` and the body face, measured once, ``O(B)``."""
    sizes = Counter(block.size for block in evidence.blocks if block.size is not None and len(block.text.strip()) > 20)
    body = sizes.most_common(1)[0][0] if sizes else None
    pitches: Counter[float] = Counter()
    edges: dict[tuple[int, int], float] = {}
    numbers: dict[int, str] = {}
    previous: EvidenceBlock | None = None
    for block in evidence.blocks:
        if _is_page_number(block) and block.page is not None:
            numbers[block.page] = block.text.strip()
            continue
        if block.box is None or block.page is None or _is_running_head(block):
            continue
        if body is not None and block.size is not None and abs(block.size - body) < SIZE_STEP:
            key = (block.page, _half(block))
            edges[key] = min(edges.get(key, 1.0), block.box.x0)
            if previous is not None and previous.box is not None and (previous.page, _half(previous)) == key:
                pitches[round(block.box.y0 - previous.box.y0, 3)] += 1
            previous = block
    pitch = pitches.most_common(1)[0][0] if pitches else 0.0115
    return _Geometry(body, pitch, edges, numbers)


# --- markers -----------------------------------------------------------------------

_LEVEL_CLASSES = ("lower", "digit", "roman", "upper", "digit", "roman")
_LEVEL_FIRST = ("a", "1", "i", "A", "1", "i")


def _classes(designation: str) -> tuple[str, ...]:
    """Which designation classes a token can belong to; ``i`` is both a letter and a numeral."""
    if designation.isdigit():
        return ("digit",)
    if designation.islower():
        return ("lower", "roman") if _ROMAN.fullmatch(designation) else ("lower",)
    if designation.isupper():
        return ("upper",)
    return ()


def _roman(value: int) -> str:
    numerals = (
        (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    )  # fmt: skip
    out = ""
    for number, numeral in numerals:
        while value >= number:
            out += numeral
            value -= number
    return out


def _from_roman(text: str) -> int:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    for index, char in enumerate(text):
        value = values[char]
        total += -value if index + 1 < len(text) and values[text[index + 1]] > value else value
    return total


def _successor(designation: str, cls: str) -> str | None:
    """The designation that follows this one in its own class, or ``None`` if it is not of that class.

    It is total on purpose: a level can hold a designation of a class other
    than the one the ladder expects there (the out-of-sequence path puts it
    wherever it fits), and asking for its successor in the wrong class must
    answer "no successor" rather than raise. Letters run bijective base 26,
    so ``(z)`` is followed by ``(aa)`` -- which is how the CFR numbers a long
    run of lettered paragraphs.
    """
    if cls not in _classes(designation):
        return None
    if cls == "digit":
        return str(int(designation) + 1)
    if cls == "roman":
        return _roman(_from_roman(designation) + 1)
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if cls == "upper":
        alphabet = alphabet.upper()
    letters = list(designation)
    position = len(letters) - 1
    while position >= 0:
        if letters[position] != alphabet[-1]:
            letters[position] = alphabet[alphabet.index(letters[position]) + 1]
            return "".join(letters)
        letters[position] = alphabet[0]
        position -= 1
    return alphabet[0] + "".join(letters)


@dataclass(frozen=True, slots=True)
class _Open:
    """One open level: the designation, the class it was read as, and the node that holds it."""

    designation: str
    cls: str
    node: str


class _Hierarchy:
    """``marker_hierarchy``: one open designation per level, from (a) at level 0 to italic (i) at level 5.

    Each level remembers the class its designation was read as, not just the
    class the ladder expects there, so a designation placed out of sequence
    cannot make the next lookup ask a nonsense question.
    """

    def __init__(self) -> None:
        self.open: list[_Open] = []

    def place(self, designation: str) -> tuple[int, str, bool]:
        """The level and class this designation takes, and whether it continued a run already open."""
        classes = _classes(designation)
        for level in range(len(self.open) - 1, -1, -1):
            entry = self.open[level]
            if entry.cls in classes and _successor(entry.designation, entry.cls) == designation:
                return level, entry.cls, True
        level = len(self.open)
        if level < len(_LEVEL_CLASSES) and _LEVEL_CLASSES[level] in classes and _LEVEL_FIRST[level] == designation:
            return level, _LEVEL_CLASSES[level], True
        for candidate, cls in enumerate(_LEVEL_CLASSES):
            if cls in classes:
                return min(candidate, len(self.open)), cls, False
        fallback = min(level, len(_LEVEL_CLASSES) - 1)
        return fallback, _LEVEL_CLASSES[fallback], False

    def parent_of(self, level: int) -> str | None:
        return self.open[level - 1].node if level else None

    def opened(self, designation: str, cls: str, level: int, identifier: str) -> None:
        del self.open[level:]
        self.open.append(_Open(designation, cls, identifier))


#: The marker a top-level paragraph hangs from, in a pair set.
SECTION_ROOT = "§"


def marker_pairs(markers: Sequence[str | None]) -> set[tuple[str, str]]:
    """``(parent marker, child marker)`` for paragraph markers in reading order, under ``marker_hierarchy``.

    The reference side of the benchmark reads its markers from the
    publisher's own ``<P>`` elements and the candidate side from the print,
    and both hang them on this one ladder, so the comparison measures whether
    the same markers were found in the same nesting rather than comparing two
    different rules.
    """
    hierarchy = _Hierarchy()
    pairs: set[tuple[str, str]] = set()
    for marker in markers:
        if not marker:
            continue
        parent: str | None = None
        for position, designation in enumerate(_DESIGNATION.findall(marker)):
            level, cls, _ok = hierarchy.place(designation)
            if position == 0:
                parent = hierarchy.parent_of(level)
            hierarchy.opened(designation, cls, level, marker)
        pairs.add((parent or SECTION_ROOT, marker))
    return pairs


def paragraph_marker(text: str) -> str | None:
    """The parenthesized designations a paragraph opens with, or ``None`` (``paragraph_marker``)."""
    match = _MARKER.match(text.lstrip())
    return match["marker"] if match else None


# --- joins -------------------------------------------------------------------------


def _rstrip_runs(runs: list[StyledRun]) -> list[StyledRun]:
    out = list(runs)
    while out:
        last = out[-1]
        text = last.text.rstrip()
        if text:
            out[-1] = replace(last, text=text)
            break
        out.pop()
        if last.break_to_page:
            out.append(replace(last, text=""))
            break
    return out


def _lstrip_runs(runs: list[StyledRun]) -> list[StyledRun]:
    out = list(runs)
    while out:
        first = out[0]
        text = first.text.lstrip()
        if text:
            out[0] = replace(first, text=text)
            break
        out.pop(0)
        if first.break_to_page and out:
            out[0] = replace(out[0], break_to_page=first.break_to_page)
    return out


def _drop_last_character(runs: list[StyledRun]) -> list[StyledRun]:
    out = list(runs)
    for index in range(len(out) - 1, -1, -1):
        if out[index].text:
            out[index] = replace(out[index], text=out[index].text[:-1])
            break
    return out


def is_small_cap_run(run: StyledRun, line_size: float | None) -> bool:
    """Whether this run is the reduced part of a small-capital setting on its line.

    GPO sets a small-capital word by *size*, not by case: ``FEDERAL
    REGISTER`` reaches the extractor as ``F`` and ``R`` at the body size and
    ``EDERAL``/``EGISTER`` a point and a half smaller, all as capitals (the
    measurement is in ``CFR-2022-title40-vol1-sec23-2``: MIonic 8.0 beside
    MIonic 6.5 on one line). The case is therefore recoverable and is not a
    property of the characters, which is why this reads the style rather than
    the text.
    """
    return (
        run.size is not None
        and line_size is not None
        and run.size <= line_size - SMALL_CAP_STEP
        and any(char.isalpha() for char in run.text)
        and run.text == run.text.upper()
    )


def restore_small_caps(runs: Sequence[StyledRun], line_size: float | None) -> list[StyledRun]:
    """``small_caps_restore``: lower the reduced capitals of a small-capital setting.

    Applied only where the line also carries a full-size run, so a line set
    wholly in the smaller face -- a note, a citation, a table row -- is left
    exactly as extracted.
    """
    if line_size is None or not any(is_small_cap_run(run, line_size) for run in runs):
        return list(runs)
    return [replace(run, text=run.text.lower()) if is_small_cap_run(run, line_size) else run for run in runs]


def _hyphen_join(tail: str, head: str) -> str | None:
    """How a line-ending hyphen joins to the next line, or ``None`` when it is not a hyphen at all.

    ``""`` means join with nothing in between, which is what a print wrap
    needs: the hyphen is dropped by the caller. ``"-"`` means keep the hyphen
    and add no space, which is what a real compound word broken at the line
    end needs.

    Three cases, each measured on the corpus:

    * a lowercase successor is the ordinary print wrap (``ini-`` / ``tial``);
    * an uppercase successor after an all-capital word is a small-capital
      word wrapped mid-word (``FED-`` / ``ERAL``), so the hyphen goes too;
    * an uppercase successor otherwise is a genuine compound that the line
      break happens to fall inside (``non-`` / ``speculative purpose.`` in
      12 CFR 1.1, which the published XML spells ``non-speculative``), so
      the hyphen stays and no space is added.
    """
    if not tail.endswith("-") or not head:
        return None
    if head[0].islower():
        return ""
    if not head[0].isupper():
        return None
    word = tail[:-1].rsplit(" ", 1)[-1]
    return "" if word and word.isupper() else "-"


def _wraps(tail: str, head: str) -> bool:
    """``wrap_hyphen_rejoin``: whether the trailing hyphen is a print wrap, so the hyphen goes."""
    return _hyphen_join(tail, head) == ""


def join_lines(
    blocks: Sequence[EvidenceBlock], page_numbers: dict[int, str] | None = None
) -> tuple[str, tuple[StyledRun, ...]]:
    """The profile's joins, applied to a node's blocks in order.

    A single space separates two lines. A line ending with a hyphen that
    :func:`_wraps` judges a print wrap loses the hyphen and joins directly. A
    line the extractor saw on a later page than its predecessor carries
    ``break_to_page`` on its first run (``page_break_in_paragraph``). A
    small-capital run is lowered back to the case the print encoded as size
    (:func:`restore_small_caps`), per block, so the block's own full-size runs
    decide what counts as reduced. Finally ``normalize_gpo_glyphs`` collapses
    GPO's doubled-backtick/doubled-apostrophe typewriter quote pairs -- the same shared rule
    ``extraction.body_text`` applies to every rendition, so the PDF and the
    XML of one document spell a quotation the same way.
    """
    numbers = page_numbers or {}
    runs: list[StyledRun] = []
    previous: EvidenceBlock | None = None
    raw_tail = ""
    for block in blocks:
        head = block.text.lstrip()
        # `small_caps_continuation`: a line that is wholly the reduced face has
        # no full-size run of its own to judge against, but when it continues a
        # hyphen wrap out of a larger line it is the rest of that line's word
        # (`FED-` / `ERAL`), so the previous line's size is what "reduced"
        # means for it.
        reference = block.size
        if previous is not None and _wraps(raw_tail, head) and previous.size is not None:
            reference = max(reference or 0.0, previous.size)
        incoming = _lstrip_runs(restore_small_caps(block.runs, reference))
        if previous is not None and incoming:
            if block.page is not None and previous.page is not None and block.page != previous.page:
                incoming[0] = replace(incoming[0], break_to_page=numbers.get(block.page, str(block.page)))
            runs = _rstrip_runs(runs)
            join = _hyphen_join(raw_tail, head)
            if join == "":
                runs = _drop_last_character(runs)
            elif join is None and "".join(run.text for run in runs):
                runs.append(StyledRun(" "))
        runs.extend(incoming)
        previous = block
        raw_tail = block.text.rstrip()
    runs = _rstrip_runs(runs)
    runs = [replace(run, text=normalize_gpo_glyphs(run.text)) for run in runs]
    runs = [run for run in runs if run.text or run.break_to_page]
    return "".join(run.text for run in runs), tuple(runs)


# --- the parser --------------------------------------------------------------------


@dataclass
class _Node:
    kind: str
    rule: str
    parent: str | None
    blocks: list[EvidenceBlock] = field(default_factory=list)
    marker: str | None = None
    review: str = "accepted"
    detail: str = ""
    method: str = "rule"
    id: str = ""
    literal: tuple[str, tuple[StyledRun, ...]] | None = None


class _Parser:
    def __init__(self, evidence: EvidenceDocument, profile: Profile, classify: ClassifyAndAttach | None) -> None:
        self.evidence = evidence
        self.profile = profile
        self.classify = classify
        self.geometry = _measure(evidence)
        self.nodes: list[_Node] = []
        self.regions: list[UnresolvedRegion] = []
        self.section: _Node | None = None
        self.subject: _Node | None = None
        self.paragraph: _Node | None = None
        #: A multi-line small-face or large-face node still taking continuation lines.
        self.open_node: _Node | None = None
        self.small_run: list[EvidenceBlock] = []
        self.hierarchy = _Hierarchy()
        self.previous: EvidenceBlock | None = None

    # -- bookkeeping

    def _add(self, node: _Node) -> _Node:
        node.id = node_id(len(self.nodes) + 1)
        self.nodes.append(node)
        return node

    def _freeze(self, node: _Node) -> DocumentNode:
        text, runs = node.literal if node.literal is not None else join_lines(node.blocks, self.geometry.page_numbers)
        return DocumentNode(
            id=node.id,
            kind=node.kind,
            marker=node.marker,
            parent=node.parent,
            evidence_refs=tuple(b.id for b in node.blocks),
            decision=Decision(node.method, node.rule, node.detail),
            review_status=node.review,
            text=text,
            runs=runs,
        )

    def _settle(self) -> None:
        """Close whatever is taking continuation lines."""
        self.paragraph = None
        self.open_node = None

    def _flush_small_run(self) -> None:
        """A small-face run inside a section no rule placed: ask the classifier, else leave it unresolved."""
        if not self.small_run:
            return
        blocks = tuple(self.small_run)
        self.small_run = []
        parent = self.section.id if self.section else None
        is_table = any(b.fragments >= TABLE_FRAGMENTS or _LEADERS.search(b.text) for b in blocks)
        issue = "table_region" if is_table else "unclassified_small_face"
        if not is_table and self.classify is not None:
            context = tuple(self._freeze(n) for n in self.nodes[-3:])
            answer = self.classify(blocks=blocks, context=context, alternatives=SMALL_FACE_ALTERNATIVES)
            if answer.choice is None or not 0 <= answer.choice < len(SMALL_FACE_ALTERNATIVES):
                issue = "abstained"
            else:
                choice = SMALL_FACE_ALTERNATIVES[answer.choice]
                if choice.kind != "table":
                    # A model choice is a reviewable decision, not a rule
                    # firing: it is placed, and it is flagged, so the
                    # "accepted without review" gate can never count it as
                    # unreviewed work.
                    node = self._add(
                        _Node(choice.kind, choice.rule, parent, list(blocks), method="model", review="needs_review")
                    )
                    node.detail = answer.reason
                    return
                issue = "table_region"
        rule = "table_region" if issue == "table_region" else "unclassified_block"
        self.regions.append(
            UnresolvedRegion(
                region_id(len(self.regions) + 1),
                tuple(b.id for b in blocks),
                issue,
                self.profile.rule(rule).statement,
                parent,
            )
        )

    # -- placing

    def _open_section(self, block: EvidenceBlock | None, number: str | None, subject: str) -> None:
        self._flush_small_run()
        self._settle()
        self.hierarchy = _Hierarchy()
        rule = "section_heading" if number is not None else "section_truncated"
        section = self._add(_Node("section", rule, None, [block] if block is not None else [], marker=number))
        self.section, self.subject = section, None
        if number is None or block is None:
            section.review = "needs_review"
            section.detail = "text before the first heading: the section began before this rendition"
            return
        sign = block.text[: block.text.index(number) + len(number)].strip()
        numbered = self._add(_Node("section_number", "section_number_then_subject", section.id, [block]))
        numbered.literal = (sign, (StyledRun(sign, bold=True),))
        self.subject = self._add(_Node("subject", "section_number_then_subject", section.id, [block]))
        self.subject.literal = (subject.strip(), (StyledRun(subject.strip(), bold=True),))

    def _continue_subject(self, block: EvidenceBlock) -> None:
        """Extend the subject with a second bold line, through the one join every node uses.

        The subject's first line is a slice of the heading line, so it cannot
        come from ``join_lines`` alone; its continuation lines can and must,
        or a subject that wraps at a hyphen ("exam-" / "ination.") keeps the
        hyphen that every other node would have lost.
        """
        assert self.subject is not None and self.subject.literal is not None
        head = self.subject.literal[0]
        join = _hyphen_join(head, block.text.lstrip())
        separator = "" if join == "" else " " if join is None else ""
        if join == "":
            head = head[:-1]
        text = (head + separator + block.text.strip()).strip()
        self.subject.blocks.append(block)
        self.subject.literal = (text, (StyledRun(text, bold=True),))
        self.subject.rule = "section_heading_continuation"

    def _paragraph(self, block: EvidenceBlock, *, opens: bool, rule: str) -> None:
        self._flush_small_run()
        if self.section is None:
            self._open_section(None, None, "")
        assert self.section is not None
        if not opens and self.paragraph is not None:
            self.paragraph.blocks.append(block)
            return
        self.open_node = None
        node = self._add(_Node("paragraph", rule, self.section.id, [block]))
        marker = _MARKER.match(block.text.lstrip())
        if marker is not None:
            node.marker, node.rule = marker["marker"], "paragraph_marker"
            in_sequence = True
            parent: str | None = None
            for index, designation in enumerate(_DESIGNATION.findall(node.marker)):
                level, cls, ok = self.hierarchy.place(designation)
                in_sequence = in_sequence and ok
                if index == 0:
                    parent = self.hierarchy.parent_of(level)
                self.hierarchy.opened(designation, cls, level, node.id)
            node.parent = parent or self.section.id
            if not in_sequence:
                node.review = "needs_review"
                node.detail = f"marker {node.marker} is out of sequence under marker_hierarchy"
        self.paragraph = node

    def _heading(self, block: EvidenceBlock) -> None:
        self._flush_small_run()
        self._settle()
        self._add(_Node("heading", "heading_hd", self.section.id if self.section else None, [block]))

    def _open_multiline(self, kind: str, rule: str, block: EvidenceBlock, parent: str | None) -> None:
        self._flush_small_run()
        self.paragraph = None
        self.open_node = self._add(_Node(kind, rule, parent, [block]))

    def _small(self, block: EvidenceBlock, text: str) -> None:
        """A small-face line: citation, note, part note, contents, or a run for the classifier."""
        section = self.section.id if self.section else None
        open_node = self.open_node
        if text.startswith("[") and section is not None:
            self._open_multiline("citation", "citation_line", block, section)
            if "]" in text:
                self.open_node = None
        elif open_node is not None and open_node.kind == "citation":
            open_node.blocks.append(block)
            if "]" in text:
                self.open_node = None
        elif _NOTE_LABEL.match(text):
            self._open_multiline("note", "note_line", block, section)
        elif text.startswith(("AUTHORITY:", "SOURCE:")):
            kind = "authority" if text.startswith("AUTHORITY:") else "source_note"
            self._open_multiline(kind, "authority_source_note", block, None)
        elif open_node is not None and open_node.kind in ("note", "authority", "source_note"):
            open_node.blocks.append(block)
        elif self.section is None and (text == "Sec." or _CONTENTS_ENTRY.match(text)):
            if open_node is not None and open_node.kind == "contents":
                open_node.blocks.append(block)
            else:
                self._open_multiline("contents", "contents_list", block, None)
        elif open_node is not None and open_node.kind == "contents":
            open_node.blocks.append(block)
        elif self.section is None:
            self._flush_small_run()
            self.open_node = self._add(_Node("note", "note_line", None, [block]))
        else:
            self.paragraph = None
            self.open_node = None
            self.small_run.append(block)

    def _small_caps_continuation(self, block: EvidenceBlock, text: str) -> bool:
        """A wholly reduced-face line that finishes a hyphen wrap out of a larger line."""
        previous = self.previous
        return (
            previous is not None
            and previous.size is not None
            and block.size is not None
            and block.size <= previous.size - SMALL_CAP_STEP
            and _wraps(previous.text.rstrip(), text)
        )

    def _gap_above(self, block: EvidenceBlock) -> bool:
        previous = self.previous
        if previous is None or block.box is None or previous.box is None or previous.page != block.page:
            return True
        if _half(previous) != _half(block):
            return True
        return block.box.y0 - previous.box.y0 >= HEADING_GAP * self.geometry.pitch

    def _body(self, block: EvidenceBlock, text: str) -> None:
        indent = self.geometry.indent(block)
        marker = _MARKER.match(text)
        if (block.bold or block.italic) and marker is None and self._gap_above(block):
            self._heading(block)
            return
        opens = (
            self.paragraph is None
            or (indent is not None and indent >= INDENT)
            or (indent is None and marker is not None)
        )
        self._paragraph(block, opens=opens, rule="first_line_indent" if indent is not None else "paragraph_p")

    def run(self) -> ReconstructedDocument:
        for block in self.evidence.blocks:
            text = block.text.strip()
            if not text:
                self._add(_Node("blank", "unclassified_block", None, [block]))
                continue
            if _is_page_number(block):
                self._add(_Node("page_number", "page_number_furniture", None, [block]))
                continue
            if _is_running_head(block):
                self._add(_Node("running_head", "running_head_furniture", None, [block]))
                continue
            if any(rule.pattern.match(text) for rule in _PRINT_SHOP_RULES):
                # GPO's print-shop footer, by `extraction.gpo_normalize`'s own
                # rules. It is set in the reduced face and reaches the
                # extractor as a dozen fragments, so without this it reads as
                # a table row and every page of the volume yields a spurious
                # unresolved region.
                self._add(_Node("print_footer", "print_shop_footer", None, [block]))
                continue
            self._place(block, text)
            self.previous = block
        self._flush_small_run()
        self._mark_truncated()
        return ReconstructedDocument(
            self.profile.identity, self.evidence, tuple(self._freeze(n) for n in self.nodes), tuple(self.regions)
        )

    def _place(self, block: EvidenceBlock, text: str) -> None:
        heading = _SECTION_HEADING.match(text)
        if heading is not None and (block.bold or block.box is None):
            self._open_section(block, heading["number"], heading["subject"])
            return
        if self.subject is not None and block.bold and self.subject.blocks[-1] is self.previous:
            self._continue_subject(block)
            return
        face = self.geometry.face(block)
        if face == "small" and self._small_caps_continuation(block, text):
            # The tail of a small-capital word that wrapped out of a body line
            # (`small_caps_continuation`); it is body text, not a note.
            face = "body"
        if face == "large":
            # The print reserves this face for a division heading -- PART,
            # Subpart, or a subject group. Every one of them ends the section
            # above it and belongs to the part, not to any section, so it
            # closes the current section rather than becoming a heading inside
            # it (`division_heading`).
            kind = "part_heading" if _PART_HEADING.match(text) else "division_heading"
            if self.open_node is not None and self.open_node.kind in ("part_heading", "division_heading"):
                self.open_node.blocks.append(block)
                return
            self._flush_small_run()
            self._settle()
            self.section = self.subject = None
            self._open_multiline(kind, "part_heading" if kind == "part_heading" else "division_heading", block, None)
            return
        if face == "small":
            self._small(block, text)
            return
        self.open_node = None
        self._body(block, text)

    def _mark_truncated(self) -> None:
        """``section_truncated``: the last section may continue past the rendition's last line.

        The open section owns the last line whenever *any* node beneath it
        does, at any depth. Checking only its direct children missed the
        common shape: a rendition cut inside a nested paragraph -- last line
        ``(1) ...`` under ``(a)`` under the section -- left the section
        ``accepted``, which is the one case where the reader most needs to be
        told the text may go on.
        """
        section, last = self.section, self.previous
        if section is None or last is None:
            return
        beneath = {section.id}
        for node in self.nodes:
            if node.parent in beneath:
                beneath.add(node.id)
        if any(n.blocks and n.blocks[-1] is last and (n is section or n.id in beneath) for n in self.nodes):
            section.review = "needs_review"
            note = "ends at the rendition's last line: the section may continue beyond it"
            section.detail = f"{section.detail}; {note}" if section.detail else note


def parse_cfr(
    evidence: EvidenceDocument,
    *,
    profile: Profile = CFR_PROFILE,
    classify: ClassifyAndAttach | None = None,
) -> ReconstructedDocument:
    """Parse one rendition's evidence under the CFR profile; ``classify`` is the optional model seam."""
    if profile.family != "cfr":
        raise ParseError(f"parse_cfr reads the cfr profile, not {profile.identity}")
    return _Parser(evidence, profile, classify).run()


__all__ = [
    "BOTTOM_BAND",
    "CFR_KINDS",
    "HEADING_GAP",
    "INDENT",
    "SECTION_ROOT",
    "SMALL_FACE_ALTERNATIVES",
    "TOP_BAND",
    "Alternative",
    "Classification",
    "ClassifyAndAttach",
    "ParseError",
    "ReconstructedDocument",
    "join_lines",
    "marker_pairs",
    "paragraph_marker",
    "parse_cfr",
]
