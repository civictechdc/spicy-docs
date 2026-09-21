"""Whether a committee report reprints the CBO cost-estimate letter, where it is, and why it is not.

Reads the normalized text of one GovInfo ``CRPT`` body and returns one
:class:`CboEstimateFinding` naming the rule and its version, what the report's
cover declared, the letter's span and digest where it is reprinted, and --
where it is not -- the publisher's own paragraph saying why. The gate is the
cover recital ``[Including cost estimate of the Congressional Budget Office]``
(Rule XIII cl. 3(a)(1)(B)), never a heading: measured reports print a CBO
heading over a section saying the estimate was not received, and one writes an
estimate under a heading no pattern knows, so the heading vocabulary is a
floor used only to locate a span the recital already declared. No letter date
is read -- no retained body states one inside a located span, and the
estimate's date is CBO's own ``pubDate``, already published -- and absence
reasons are read whether or not a heading precedes them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.citations import bill_type_and_number
from spicy_docs.schemas.tables import digest, natural_key

#: This rule's name, published on every row it fills.
CBO_ESTIMATE_RULE = "cbo_cost_estimate_letter"


class CboEstimateError(ValueError):
    """The text handed to the rule is not one document's text."""


@dataclass(frozen=True, slots=True)
class LetterPattern:
    """One named pattern, and the reason it exists.

    ``rejects`` are the lookalikes the pattern must not match, asserted in
    ``tests/test_cbo_estimates.py`` so a pattern that widened into prose fails
    a check rather than raising a hit rate.
    """

    name: str
    pattern: str
    reason: str
    rejects: tuple[str, ...] = ()
    flags: int = 0

    def compiled(self, flags: int = 0) -> re.Pattern[str]:
        return re.compile(self.pattern, self.flags | flags)


#: The statutory cover recital, matched as a whole printed line.  Structural
#: rather than positional: prose that quotes the phrase runs inline, and the
#: cover prints it alone between blank lines.  Measured: exactly one
#: occurrence in each of the 7 bodies that carry it, always on the cover.
COVER_RECITAL = LetterPattern(
    "cover_recital",
    r"^[ \t]*\[Including cost estimate of the Congressional Budget Office\][ \t]*$",
    "Rule XIII cl. 3(a)(1)(B): the one statement, identical in both chambers, that the report contains "
    "the estimate. The only gate; a heading is never one.",
    rejects=(
        "  the cost estimate of the Congressional Budget Office was not available",
        "  [Including cost estimate of the Joint Committee on Taxation]",
    ),
    flags=re.MULTILINE,
)

#: The cover's own statement of which measure the report accompanies, printed
#: the same way and two lines above the recital.  This is the print's side of
#: the report-to-bill join the estimate index needs; see ``recital_bill_id``.
ACCOMPANIES = LetterPattern(
    "accompanies",
    r"^[ \t]*\[To accompany ([^\]\n]+)\][ \t]*$",
    "Rule XIII cl. 3(a)(1)(A): the measure the report accompanies, which is what joins a report row to "
    "cbo_cost_estimates.bill_id.",
    rejects=("The report [To accompany H.R. 801] is on the calendar.",),
    flags=re.MULTILINE,
)

#: Where a declared letter *starts*.  A floor by construction and used only
#: after the recital has already decided the report states an estimate: these
#: are committee-specific section titles, and CRPT-118hrpt111 proves the set
#: can miss one.  Matched against a heading block's collapsed text, so a
#: heading GPO wrapped across two centered lines -- CRPT-118hrpt951's
#: ``V. COST ESTIMATE PREPARED BY THE CONGRESSIONAL`` / ``BUDGET OFFICE`` --
#: is one heading and not two lines of nothing.
HEADINGS: tuple[LetterPattern, ...] = (
    LetterPattern(
        "cbo_cost_estimate",
        r"congressional budget office cost estimate",
        "the commonest spelling; measured on CRPT-118hrpt276, -118hrpt780, -118hrpt930, -118srpt289 and -118srpt298",
    ),
    LetterPattern(
        "cbo_estimate",
        r"congressional budget office estimate",
        "the shorter spelling; measured on CRPT-118hrpt53, and on -118hrpt18 and -118hrpt21 over a section "
        "that says the estimate was not received",
    ),
    LetterPattern(
        "cost_estimate_prepared_by_cbo",
        r"cost estimate prepared by the congressional budget office",
        "the spelling the five-pattern set in the routes measurement missed; measured on CRPT-118hrpt111 and, "
        "wrapped across two lines, on -118hrpt951",
    ),
    LetterPattern(
        "committee_cost_estimate",
        r"committee cost estimate",
        "Rule XIII cl. 3(d)(1)'s heading, under which a committee adopts CBO's estimate as its own; measured "
        "on CRPT-118hrpt18 and -118hrpt21",
    ),
    LetterPattern(
        "estimated_costs",
        r"estimated costs?",
        "an older committee spelling recorded by the routes measurement's heading census",
    ),
    LetterPattern(
        "cost_of_legislation",
        r"cost of legislation and the congressional budget act",
        "the numbered-section spelling recorded by the same census",
    ),
)

#: Where a declared letter *ends*: the attribution CBO signs it with.  One
#: pattern covers both measured styles -- the House letter's ``Phillip L.
#: Swagel,`` / ``Director, Congressional Budget Office.`` signature block, the
#: parenthesised ``(For Phillip L. Swagel, Director, Congressional Budget
#: Office).`` of CRPT-118hrpt780, and the newer ``Estimate approved by:``
#: attribution of CRPT-118hrpt930 and -118srpt289 -- because all three end in
#: the same comma-then-Director phrase.  The comma is what separates it from
#: the prose ``the Director of the Congressional Budget Office``, which every
#: one of these reports also prints.
DIRECTOR_ATTRIBUTION = LetterPattern(
    "director_attribution",
    r"Director,[ \t]*\n?[ \t]*Congressional(?:[ \t]+|[ \t]*\n[ \t]*)Budget Office\)?\.?",
    "the letter's own close; PDF CRPT-118hrpt930 and -118srpt289 wrap after Congressional; "
    "6 of the 7 recital-declared HTM bodies end here",
    rejects=(
        "the estimate prepared by the Director of the Congressional Budget Office",
        "an estimate and comparison prepared by the Director of the Congressional\nBudget Office",
        "Director, CongressionalBudget Office.",
        "Director, Congressional\n\nBudget Office.",
    ),
)

#: Who signed, read out of the attribution.  Two to four name tokens before
#: the comma, each either a capitalised word or a single-letter initial, with
#: CRPT-118hrpt780's ``(For `` consumed rather than captured.  A word may not
#: *end* in a period: the sentence before the House signature block closes
#: ``...Deputy Director of Budget Analysis.``, and a looser token read that
#: back as part of the name on 3 of the 5 measured signatures.
SIGNATORY = LetterPattern(
    "signatory",
    r"(?:\(For )?(?P<name>(?:[A-Z]\.|[A-Z][A-Za-z'-]*)(?: (?:[A-Z]\.|[A-Z][A-Za-z'-]*)){1,3}), "
    r"Director, Congressional Budget Office",
    "the Director as the letter names them; NULL where the attribution states no name",
)

#: The publisher's own reason, where the cover declares nothing.  Each pattern
#: is a phrase the report writes about CBO; the paragraph around it is what is
#: returned, because the publisher's unit is the paragraph and a sentence
#: splitter over GPO's fixed-width text invents boundaries.
ABSENCE_REASONS: tuple[LetterPattern, ...] = (
    LetterPattern(
        "not_available",
        r"was not available",
        "CRPT-118hrpt18 and -118hrpt21: the estimate had not arrived when the report was filed",
        rejects=("[GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT]",),
        flags=re.IGNORECASE,
    ),
    LetterPattern(
        "not_received",
        r"requested but not received",
        "CRPT-118hrpt58 and -118hrpt111: the committee asked and CBO had not answered",
        flags=re.IGNORECASE,
    ),
)

#: A reason paragraph must also name CBO.  Without it ``was not available``
#: reads a dropped graphic, an absent witness or an unavailable document as a
#: missing cost estimate; all four measured reasons name the office.
_REASON_REQUIRES = re.compile(r"Congressional\s+Budget\s+Office", re.IGNORECASE)

#: A heading block's optional numbering token, and the series it belongs to.
#: The series is what the end fallback matches on: a letter whose heading is
#: ``VI.`` ends at the next roman-numbered heading, never at a stray indented
#: line.
_NUMBERING = re.compile(r"^(?:(?P<roman>[IVXL]+)|(?P<letter>[A-Z])|(?P<arabic>[0-9]+))\.\s+")

#: A heading block: consecutive lines, every one indented, none carrying the
#: dot leaders a table of contents prints.  Four spaces is GPO's paragraph
#: indent, and a paragraph's continuation lines start at column zero, so
#: requiring *every* line to be indented separates a centered heading from
#: body text without guessing a centering width.
_MIN_HEADING_INDENT = 4
_MAX_HEADING_LINES = 3
_MAX_HEADING_CHARS = 120
_DOT_LEADER = re.compile(r"\.{4,}")
_WHITESPACE = re.compile(r"\s+")
_PARAGRAPH_BREAK = re.compile(r"\n{2,}")
_HEADING_TRAILING_CHARS = "."
# Bump for control-flow changes not represented by the patterns/thresholds.
_RULE_REVISION = 2


@dataclass(frozen=True, slots=True)
class HeadingBlock:
    """One centered heading, collapsed to a single line, with its span and numbering series."""

    text: str
    span: tuple[int, int]
    series: str | None


def heading_blocks(text: str) -> Iterator[HeadingBlock]:
    """Indented heading blocks and flush uppercase lines, in document order."""
    start = 0
    block: list[str] = []
    block_start = 0
    for line in text.split("\n"):
        end = start + len(line)
        indented = line.strip() and len(line) - len(line.lstrip(" \t")) >= _MIN_HEADING_INDENT
        if indented and not _DOT_LEADER.search(line):
            if not block:
                block_start = start
            block.append(line.strip())
        else:
            if block:
                yield from _heading(block, block_start, start - 1)
            block = []
            # Native PDF text loses indentation and blank paragraph lines.
            # Its four retained section titles are whole uppercase lines;
            # prose and contents entries must still fail the exact vocabulary.
            if line == line.lstrip() and line.isupper() and not _DOT_LEADER.search(line):
                yield from _heading([line], start, end)
        start = end + 1
    if block:
        yield from _heading(block, block_start, len(text))


def _heading(lines: Sequence[str], start: int, end: int) -> Iterator[HeadingBlock]:
    if len(lines) > _MAX_HEADING_LINES:
        return
    collapsed = " ".join(lines)
    if len(collapsed) > _MAX_HEADING_CHARS:
        return
    numbering = _NUMBERING.match(collapsed)
    series = None
    if numbering is not None:
        series = next(name for name, value in numbering.groupdict().items() if value)
        collapsed = collapsed[numbering.end() :]
    yield HeadingBlock(collapsed, (start, end), series)


@dataclass(frozen=True, slots=True)
class CboEstimateFinding:
    """What one committee report says about its CBO cost estimate.

    ``report_states_estimate`` is the report's own cover declaration and
    nothing else; ``letter_span`` is present only when that declaration was
    made *and* both ends of the reprint were located, so a declared letter
    whose end could not be found returns the declaration with a NULL span
    rather than an invented boundary; ``absence_reason`` is the publisher's
    paragraph, verbatim, read whether or not a heading precedes it.
    """

    rule: str
    rule_version: str
    report_states_estimate: bool
    recital_span: tuple[int, int] | None
    accompanies: str | None
    heading: str | None
    heading_rule: str | None
    letter_span: tuple[int, int] | None
    letter_sha256: str | None
    letter_end_rule: str | None
    signatory: str | None
    absence_reason: str | None
    absence_span: tuple[int, int] | None
    absence_rule: str | None


def _rule_version(patterns: Sequence[LetterPattern] | None = None) -> str:
    """Digest all pattern text, flags, rejects, heading thresholds and rule revision.

    Derived, not written, for the reason ``citations._rule_set_version`` is:
    editing a pattern moves this even when nobody remembers to. The rejects are
    in the input because a reject that is no longer asserted cannot fail, so
    deleting one changes the rule.
    """
    rules = _letter_patterns() if patterns is None else patterns
    payload = {
        "patterns": [(p.name, p.pattern, p.flags, p.rejects) for p in rules],
        "guards": [
            (p.pattern, p.flags) for p in (_REASON_REQUIRES, _NUMBERING, _DOT_LEADER, _WHITESPACE, _PARAGRAPH_BREAK)
        ],
        "heading_limits": (_MIN_HEADING_INDENT, _MAX_HEADING_LINES, _MAX_HEADING_CHARS),
        "heading_trailing_chars": _HEADING_TRAILING_CHARS,
        "revision": _RULE_REVISION,
    }
    return digest(json.dumps(payload, sort_keys=True))[7:19]


def _letter_patterns() -> tuple[LetterPattern, ...]:
    return (COVER_RECITAL, ACCOMPANIES, *HEADINGS, DIRECTOR_ATTRIBUTION, SIGNATORY, *ABSENCE_REASONS)


#: Every pattern this rule runs, in the order it runs them.
LETTER_PATTERNS: tuple[LetterPattern, ...] = _letter_patterns()

#: The identity of the whole rule, published beside every span it produced.
CBO_ESTIMATE_RULE_VERSION = _rule_version(LETTER_PATTERNS)


def _match_heading(block: HeadingBlock) -> str | None:
    folded = block.text.casefold().rstrip(_HEADING_TRAILING_CHARS)
    return next((p.name for p in HEADINGS if p.compiled().fullmatch(folded)), None)


def _paragraphs(text: str) -> Iterator[tuple[int, int]]:
    """Scan blank-line-bounded paragraphs once, preserving their exact spans.

    The publisher's own unit: a sentence splitter over GPO's fixed-width text
    would have to guess where a line break ends a sentence, and these reasons
    run to four printed lines.
    """
    start = 0
    for boundary in _PARAGRAPH_BREAK.finditer(text):
        yield start, boundary.start()
        start = boundary.end()
    yield start, len(text)


def _absence(text: str) -> tuple[str | None, tuple[int, int] | None, str | None]:
    patterns = [p.compiled() for p in ABSENCE_REASONS]
    found: dict[int, tuple[str, tuple[int, int], str]] = {}
    for start, end in _paragraphs(text):
        paragraph = text[start:end]
        if not _REASON_REQUIRES.search(paragraph):
            continue
        for index, pattern in enumerate(patterns):
            if index not in found and pattern.search(paragraph):
                found[index] = (paragraph.strip(), (start, end), ABSENCE_REASONS[index].name)
    if found:
        # Rule priority precedes document order, as in the original reader.
        return found[min(found)]
    return None, None, None


def _letter_end(text: str, heading: HeadingBlock, blocks: Sequence[HeadingBlock]) -> tuple[int, str] | None:
    """Where the reprinted letter ends: its attribution, or the next heading in the same series.

    The attribution is the measured end on 6 of 7 recital-declared bodies; the
    one that has none -- whose estimate is a summary table rather than a letter
    -- has a numbered heading, so the fallback ends at the next heading of that
    same series. An *unnumbered* heading gets no fallback: nothing measured
    needs one and a stray indented line is not a boundary worth guessing.
    """
    attribution = DIRECTOR_ATTRIBUTION.compiled().search(text, heading.span[1])
    if attribution is not None:
        return attribution.end(), DIRECTOR_ATTRIBUTION.name
    if heading.series is None:
        return None
    for block in blocks:
        if block.span[0] > heading.span[1] and block.series == heading.series:
            return block.span[0], "next_heading_in_series"
    return None


def read_cbo_estimate(text: str) -> CboEstimateFinding:
    """What one CRPT body states about its CBO cost estimate.

    ``text`` is the normalized text of one report -- ``BodyText.text`` -- and
    every span is an offset into exactly that string, so a consumer holding it
    can re-read the span and see what the rule saw.
    """
    if not isinstance(text, str):
        raise CboEstimateError(f"text must be a string, not {type(text).__name__}")
    recital = COVER_RECITAL.compiled().search(text)
    accompanies = ACCOMPANIES.compiled().search(text)
    heading: HeadingBlock | None = None
    heading_rule: str | None = None
    blocks = tuple(heading_blocks(text))
    for block in blocks:
        matched = _match_heading(block)
        if matched is not None:
            heading, heading_rule = block, matched
            break
    span: tuple[int, int] | None = None
    end_rule: str | None = None
    signatory: str | None = None
    if recital is not None and heading is not None:
        located = _letter_end(text, heading, blocks)
        if located is not None:
            end, end_rule = located
            span = (heading.span[0], end)
            found = SIGNATORY.compiled().search(_WHITESPACE.sub(" ", text[span[0] : span[1]]))
            signatory = None if found is None else found["name"]
    reason, reason_span, reason_rule = (None, None, None) if recital is not None else _absence(text)
    return CboEstimateFinding(
        rule=CBO_ESTIMATE_RULE,
        rule_version=CBO_ESTIMATE_RULE_VERSION,
        report_states_estimate=recital is not None,
        recital_span=None if recital is None else (recital.start(), recital.end()),
        accompanies=None if accompanies is None else accompanies.group(1).strip(),
        heading=None if heading is None else heading.text,
        heading_rule=heading_rule,
        letter_span=span,
        letter_sha256=None if span is None else digest(text[span[0] : span[1]]),
        letter_end_rule=end_rule,
        signatory=signatory,
        absence_reason=reason,
        absence_span=reason_span,
        absence_rule=reason_rule,
    )


def recital_bill_id(finding: CboEstimateFinding, congress: object) -> str | None:
    """``[To accompany H.R. 801]`` in a 118th report is ``118-hr-801``.

    **The Congress is the package's, not the print's** -- the cover writes
    ``H.R. 801`` and never a Congress -- so the caller supplies the one its own
    package identity states; ``None`` where the cover names no measure or names
    something outside the eight bill types, which is the honest answer rather
    than a key nothing addresses.
    """
    if finding.accompanies is None or congress is None:
        return None
    parts = bill_type_and_number(finding.accompanies)
    return None if parts is None else natural_key(congress, *parts)


__all__ = [
    "ABSENCE_REASONS",
    "ACCOMPANIES",
    "CBO_ESTIMATE_RULE",
    "CBO_ESTIMATE_RULE_VERSION",
    "COVER_RECITAL",
    "DIRECTOR_ATTRIBUTION",
    "HEADINGS",
    "LETTER_PATTERNS",
    "SIGNATORY",
    "CboEstimateError",
    "CboEstimateFinding",
    "HeadingBlock",
    "LetterPattern",
    "heading_blocks",
    "read_cbo_estimate",
    "recital_bill_id",
]
