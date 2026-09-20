"""Whether a committee report reprints the CBO cost-estimate letter, where it is, and why it is not.

Publisher fact in: the normalized text of one GovInfo ``CRPT`` body
(``extraction.body_text.rendition_text``'s ``BodyText.text``).  Interpretation
out: one :class:`CboEstimateFinding` naming the rule, its version, what the
report's own cover declared, the letter's span and digest where it is
reprinted, and -- where it is not -- the publisher's own sentence saying why.

It lives here rather than in ``sources/agency_reports/`` for the reason
``interpretation/citations.py`` does: this is a named, versioned rule over
already-normalized text that returns a frozen finding carrying the rule that
fired, which is what this package is for.  ``sources/agency_reports/
report_blocks.py`` is a heading *splitter* ported for parity with stored
BillTrax rows, and its all-caps header patterns do not reach these headings
(``Congressional Budget Office Cost Estimate`` is title case) -- so nothing
there is duplicated here and nothing here belongs there.

**The gate is the cover recital, never a heading.**  Rule XIII cl. 3(a)(1)(B)
makes a reported measure's cover carry ``[Including cost estimate of the
Congressional Budget Office]`` when the estimate is in the report, in both
chambers, identically.  A heading is not that statement, in either direction,
and the corpus shows both failures (measured 2026-09-20 over the 17 retained
CRPT bodies,
``docs/research/cbo-cost-estimate-routes-2026-09-20.md``):

* **A heading over no estimate.**  Three reports print a CBO heading above a
  section that then says the estimate was **not received** -- ``CRPT-118hrpt18``
  ("At the time this report was filed, the estimate was not available"),
  ``-118hrpt21`` and ``-118hrpt58``.  A heading gate publishes those as
  estimates.
* **An estimate under a heading no pattern knows.**  ``CRPT-118hrpt111``
  writes ``C. Cost Estimate Prepared by the Congressional Budget Office``,
  which the five committee-specific patterns the routes measurement tried did
  not count.  **The heading vocabulary below is a floor and is only ever used
  to locate a span the recital already declared.**
* **A signature over no letter.**  ``CRPT-118srpt99`` states ``Director,
  Congressional Budget Office.`` in a *witness list* and a
  ``Washington, DC, March 1, 2023.`` dateline on the Senate Budget Committee's
  own letter of transmittal.  Both markers are false positives outside the
  recital gate; inside it, all 7 recital-declared bodies are letters.

**Requested-empty, with the publisher's reason.**  A report whose cover does
not declare the estimate is not evidence that none exists -- 3 of 13 reported
bills whose index named an estimate had none in the report -- and four of the
retained bodies say why in their own words.  :func:`read_cbo_estimate` returns
that paragraph whole, with its span, so the absence carries its reason instead
of being a NULL.  The absence patterns are **not** gated on a heading, because
``CRPT-118hrpt111``'s reason sits under a heading no pattern matched.

**No letter date is read, and that is a measurement, not a gap.**  No retained
body states a CBO letterhead dateline inside a located span: 0 of the 7
recital-declared spans carries one and 0 of 17 bodies carries one at all.
Writing a pattern against a form nothing here has seen is the guess this
repository refuses elsewhere, and it is unnecessary: the estimate's date is
CBO's own ``pubDate``, already published on ``cbo_cost_estimates.pub_date``,
and joining to it beats re-deriving it from prose.  One retained body whose
reprint carries the letterhead would add the rule.

**Complexity.** For text of ``C`` characters this is a constant number of
single passes -- ``O(C)`` -- plus one linear walk of the heading blocks.
Nothing fetches, reads a clock or touches a file.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.citations import bill_type_and_number
from spicy_docs.schemas.tables import natural_key

#: This rule's name, published on every row it fills.
CBO_ESTIMATE_RULE = "cbo_cost_estimate_letter"


class CboEstimateError(ValueError):
    """The text handed to the rule is not one document's text."""


@dataclass(frozen=True, slots=True)
class LetterPattern:
    """One named pattern, and the reason it exists.

    Rules are data here for the reason they are in
    ``interpretation/citations.py``: a vocabulary has one home and a reviewer
    reads the table rather than the control flow.  ``rejects`` are the
    lookalikes the pattern must *not* match, asserted in
    ``tests/test_cbo_estimates.py`` so a pattern that widened into prose fails
    a check rather than raising a hit rate.
    """

    name: str
    pattern: str
    reason: str
    rejects: tuple[str, ...] = ()

    def compiled(self, flags: int = 0) -> re.Pattern[str]:
        return re.compile(self.pattern, flags)


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
    r"Director,[ \t]*\n?[ \t]*Congressional Budget Office\)?\.?",
    "the letter's own close, in all three measured styles; 6 of the 7 recital-declared bodies end here",
    rejects=(
        "the estimate prepared by the Director of the Congressional Budget Office",
        "an estimate and comparison prepared by the Director of the Congressional\nBudget Office",
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
    ),
    LetterPattern(
        "not_received",
        r"requested but not received",
        "CRPT-118hrpt58 and -118hrpt111: the committee asked and CBO had not answered",
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


@dataclass(frozen=True, slots=True)
class HeadingBlock:
    """One centered heading, collapsed to a single line, with its span and numbering series."""

    text: str
    span: tuple[int, int]
    series: str | None


def heading_blocks(text: str) -> Iterator[HeadingBlock]:
    """Every centered heading in one report's normalized text, in document order."""
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
    nothing else.  ``letter_span`` is present only when that declaration was
    made *and* both ends of the reprint were located; a declared letter whose
    end could not be found returns the declaration with a NULL span rather
    than a boundary this rule invented.  ``absence_reason`` is the publisher's
    paragraph, verbatim, and is read whether or not a heading precedes it.
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


def _rule_version(patterns: Sequence[LetterPattern]) -> str:
    """A digest over every pattern's name, pattern text **and** rejects.

    Derived, not written, for the reason ``citations._rule_set_version`` is:
    editing a pattern moves this even when nobody remembers to, and the pinned
    test then names it.  The rejects are in the input because a reject that is
    no longer asserted cannot fail, so deleting one changes the rule.
    """
    joined = "\n".join(f"{p.name}|{p.pattern}|{'|'.join(p.rejects)}" for p in patterns)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


#: Every pattern this rule runs, in the order it runs them.
LETTER_PATTERNS: tuple[LetterPattern, ...] = (
    COVER_RECITAL,
    ACCOMPANIES,
    *HEADINGS,
    DIRECTOR_ATTRIBUTION,
    SIGNATORY,
    *ABSENCE_REASONS,
)

#: The identity of the whole rule, published beside every span it produced.
CBO_ESTIMATE_RULE_VERSION = _rule_version(LETTER_PATTERNS)

_HEADING_TEXTS: dict[str, str] = {pattern.name: pattern.pattern for pattern in HEADINGS}


def _match_heading(block: HeadingBlock) -> str | None:
    folded = block.text.casefold().rstrip(".")
    return next((name for name, spelling in _HEADING_TEXTS.items() if re.fullmatch(spelling, folded)), None)


def _paragraph(text: str, position: int) -> tuple[int, int]:
    """The blank-line-bounded paragraph containing ``position``.

    The publisher's own unit.  A sentence splitter over GPO's fixed-width text
    would have to guess where a line break ends a sentence, and these reasons
    run to four printed lines.
    """
    start = text.rfind("\n\n", 0, position)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", position)
    return start, len(text) if end < 0 else end


def _absence(text: str) -> tuple[str | None, tuple[int, int] | None, str | None]:
    for pattern in ABSENCE_REASONS:
        for match in pattern.compiled(re.IGNORECASE).finditer(text):
            start, end = _paragraph(text, match.start())
            if _REASON_REQUIRES.search(text[start:end]):
                return text[start:end].strip(), (start, end), pattern.name
    return None, None, None


def _letter_end(text: str, heading: HeadingBlock) -> tuple[int, str] | None:
    """Where the reprinted letter ends: its attribution, or the next heading in the same series.

    The attribution is the measured end on 6 of 7 recital-declared bodies.
    The one that has none -- ``CRPT-118srpt298``, whose estimate is a summary
    table rather than a letter -- has a numbered heading, so the fallback ends
    at the next heading of that same series (``VI.`` to ``VII.``).  An
    *unnumbered* heading gets no fallback: nothing measured needs one and a
    stray indented line is not a boundary worth guessing.
    """
    attribution = DIRECTOR_ATTRIBUTION.compiled().search(text, heading.span[1])
    if attribution is not None:
        return attribution.end(), DIRECTOR_ATTRIBUTION.name
    if heading.series is None:
        return None
    for block in heading_blocks(text):
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
    recital = COVER_RECITAL.compiled(re.MULTILINE).search(text)
    accompanies = ACCOMPANIES.compiled(re.MULTILINE).search(text)
    heading: HeadingBlock | None = None
    heading_rule: str | None = None
    for block in heading_blocks(text):
        matched = _match_heading(block)
        if matched is not None:
            heading, heading_rule = block, matched
            break
    span: tuple[int, int] | None = None
    end_rule: str | None = None
    signatory: str | None = None
    if recital is not None and heading is not None:
        located = _letter_end(text, heading)
        if located is not None:
            end, end_rule = located
            span = (heading.span[0], end)
            found = SIGNATORY.compiled().search(re.sub(r"\s+", " ", text[span[0] : span[1]]))
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
        letter_sha256=None
        if span is None
        else "sha256:" + hashlib.sha256(text[span[0] : span[1]].encode("utf-8")).hexdigest(),
        letter_end_rule=end_rule,
        signatory=signatory,
        absence_reason=reason,
        absence_span=reason_span,
        absence_rule=reason_rule,
    )


def recital_bill_id(finding: CboEstimateFinding, congress: object) -> str | None:
    """``[To accompany H.R. 801]`` in a 118th report is ``118-hr-801``.

    **The Congress is the package's, not the print's**, exactly as
    ``interpretation.citations`` stamps one on a bare designator: the cover
    writes ``H.R. 801`` and never a Congress, so the caller supplies the one
    its own package identity states.  ``None`` where the cover names no
    measure -- a report can accompany none -- or names something outside the
    eight bill types, which is the honest answer rather than a key nothing
    addresses.
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
