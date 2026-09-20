"""What a committee print says *happened to* a bill it names.

Publisher fact in: one document's normalized text and the ``bill_number``
:class:`~spicy_docs.interpretation.citations.CitationFinding`s already read out
of it.

Interpretation out: one :class:`BillActionFinding` per (action phrase, bill)
pair -- the print's own phrasing, the sealed ``bill_stage`` rung it maps to or
``None``, the BILLSTATUS action code the publisher's guide gives for that
phrasing in that chamber or ``()``, the date the sentence states, the spans of
both the phrase and the bill designator, how many bills the sentence names, and
which attachment class produced the pair.

``citations`` says *that* a print names ``H.R. 1093``; this says what the print
says happened to it. The package MODS states the first and states nothing about
the second, which is why this exists.

**This is measured, and the measurement is what the rows are worth.** See
``docs/research/bill-action-relationship-2026-09-20.md``: 1,249 pages of eight
retained House activity reports, 6,365 bill mentions, 4,456 action rows, and 60
hand-checked mentions behind every figure quoted in this module.

**Three failure shapes, all measured, none of them tunable away.**

1. **The multi-bill sentence.** A published row is both the right kind and
   the right bill **83.3% of the time where the sentence names one bill** (30
   of 36 hand-checked) and **50% where it names several** (2 of 4).
   :attr:`BillActionFinding.attachment` carries the class so a consumer
   filters instead of guessing, and ``bills_in_sentence`` carries the
   predicate it was derived from. 4,089 of 4,456 rows (91.8%) are
   single-bill, so restricting to the trusted class costs 8% of the volume.
2. **The entry is not a sentence, and every committee sets it differently.**
   A print writes a bill's long title as its own sentence and the disposition
   as the fragment after it, or states an en-bloc disposition about "the
   measures" with the bills listed above it. 2,952 phrase occurrences across
   the eight prints sit in a sentence that names no bill at all, against 4,456
   that reach one; :func:`find_bill_actions` reports them as
   ``orphan_phrasings`` rather than attaching them to whichever bill happens to
   be nearest, which is the one thing that would turn a miss into a wrong row.
3. **The print writes "the bill".** Recall against what a reader sees in the
   entry is 59.6%, and anaphora is most of the gap.

**The phrasing vocabulary is sealed and additions-only.** A key here is
published in ``bill_committee_actions.print_phrasing``, so renaming or
removing one rewrites history in a hosted table. New phrasings are appended and
:data:`PRINT_ACTION_VOCABULARY_VERSION` moves; the derived
:data:`PRINT_ACTION_RULE_SET_VERSION` moves when any pattern does, even when
someone forgets the first.

**Rungs come from ``bill_stage`` and are never invented here.**
:func:`sealed_stage` runs the print's own matched phrase through
``infer_stage_from_text``, so a phrasing either resolves to a sealed rung with
the matcher that fired or is reported unmapped. Ten of the twenty-five
phrasings resolve; the rest are the *print register*, and they are recorded as
such rather than patched into ``STAGE_RULES``. ``passed the House`` is the
sharpest case: the sealed matcher is ``passed house``, one word away, and
widening it would make one rule set read two publishers' prose.

**Complexity.** For text of ``C`` characters and ``K`` = 25 rules, one pass per
rule over each sentence is ``O(K*C)``, plus a binary search per mention into
the sentence offsets. Nothing here is superlinear in the corpus.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.bill_stage import infer_stage_from_text
from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, bill_type_and_number


class BillActionError(ValueError):
    """The text and the citations handed to these rules do not describe one document."""


# --- the flattened matching text -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlatText:
    """The retained text with line-wrap hyphens closed, and the offsets back to it.

    A GPO print that is not gutter-numbered keeps its line-wrap hyphens --
    ``normalize_gpo_pages`` rejoins them only where the document's layout
    verdict says they are wraps -- so ``held a hear-\\ning`` is the page's own
    text and a phrase rule run over it reads no hearing at all. This builds the
    text the rules match in and keeps both offset maps, so **every span a
    finding carries is an offset into the retained text**, the same text the
    citation spans and the row's ``text_sha256`` are against. Nothing is
    measured in one text and published against another.
    """

    retained: str
    flat: str
    origin: tuple[int, ...]
    flat_index: tuple[int, ...]

    def to_flat(self, offset: int) -> int:
        return self.flat_index[min(offset, len(self.flat_index) - 1)]

    def to_retained(self, offset: int) -> int:
        return self.origin[min(offset, len(self.origin) - 1)] if self.origin else 0


#: A hyphen at end of line is a print wrap in this family; the character it
#: joins to is on the next line.  ``‐`` is the Unicode hyphen GPO's own
#: typesetting occasionally sets instead of the ASCII one.
WRAP_HYPHENS = "-‐"


def flatten(text: str) -> FlatText:
    """Close line-wrap hyphens, space the newlines, and keep both offset maps."""
    out: list[str] = []
    origin: list[int] = []
    index = 0
    size = len(text)
    while index < size:
        character = text[index]
        if character in WRAP_HYPHENS and index + 1 < size and text[index + 1] == "\n":
            index += 2
            continue
        out.append(" " if character == "\n" else character)
        origin.append(index)
        index += 1
    flat_index = [0] * (size + 1)
    for position, source in enumerate(origin):
        flat_index[source] = position
    for position in range(1, size + 1):
        if flat_index[position] == 0:
            flat_index[position] = flat_index[position - 1]
    return FlatText(text, "".join(out), tuple(origin), tuple(flat_index))


# --- sentences -----------------------------------------------------------------------

#: A sentence may close inside its own quotation marks or parentheses -- this
#: family sets a bill's short title as ``the "PHE Congressional Review Act of
#: 2023."`` A break rule that demands whitespace immediately after the stop
#: reads the whole of the next sentence as part of that title, which is how a
#: hearing held on a *discussion draft* came to be attached to the bill named
#: in the sentence after it (found by hand check, 2026-09-20).
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")

#: Tokens that end in a period without ending a sentence. Measured, not
#: guessed: every one appears immediately before a would-be break in the eight
#: sampled prints, and ``H.J.`` alone mis-split 20 mentions before it was
#: added -- a bill designator is the one abbreviation this corpus cannot afford
#: to split on, since the split separates a bill from its own action.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "h.r", "h.j", "s.j", "h.con", "s.con", "h.res", "s.res", "hr", "h", "s", "j", "con", "res", "conres",
        "jres", "no", "nos", "mr", "mrs", "ms", "dr", "jr", "sr", "rept", "repts", "rep", "sen", "u.s", "u.s.c",
        "p.l", "pub", "l", "cong", "st", "inc", "co", "corp", "ct", "stat", "doc", "ex", "fed", "reg", "c.f.r",
        "sec", "secs", "art", "vs", "v", "hon", "adm", "gen", "gov", "lt", "col", "maj", "capt", "ph", "d",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sept", "sep", "oct", "nov", "dec", "cal", "dist",
    }
)  # fmt: skip

_LAST_TOKEN = re.compile(r"[\s(\[“‘]")

#: A list number (``1.``), a lettered item (``c.``) or a roman numeral (``II.``)
#: stands for an entry heading only when it *opens* the sentence. Measured,
#: because the obvious version of this rule was wrong: reading any short number
#: as a list marker merged "the House passed H.R. 1121 by a vote of 229 to
#: 118." into the sentence after it, and a merged sentence is exactly how an
#: action reaches the wrong bill. Five characters is enough for ``23. `` and
#: ``iii. ``.
_LIST_MARKER = re.compile(r"\d{1,3}|[a-z]|[ivxl]+")
_LIST_MARKER_COLUMN = 5


def sentence_starts(flat: str) -> tuple[int, ...]:
    """Where each sentence begins in the flattened text.

    A break after an abbreviation is never a break -- ``H.J.`` and ``H. Rept.``
    are how this family spells a bill and a report -- and a break after an
    entry marker at the head of its own sentence is not one either.
    """
    starts = [0]
    for match in _SENTENCE_BREAK.finditer(flat):
        left = flat[max(0, match.start() - 14) : match.start() - 1]
        token = _LAST_TOKEN.split(left)[-1].lower() if left else ""
        opening = match.start() - len(token) - 1 - starts[-1] <= _LIST_MARKER_COLUMN
        if token in ABBREVIATIONS or (opening and _LIST_MARKER.fullmatch(token)):
            continue
        starts.append(match.end())
    return tuple(starts)


def sentence_at(starts: Sequence[int], flat: str, offset: int) -> tuple[int, int]:
    """``(begin, end)`` of the sentence that contains ``offset``."""
    index = bisect.bisect_right(starts, offset) - 1
    return starts[index], starts[index + 1] if index + 1 < len(starts) else len(flat)


# --- the publisher's own action-code vocabulary ---------------------------------------

#: Chambers a section-3 action code's **own text** names. ``unstated`` is not a
#: guess dressed as a fact: the guide's action-code table has no chamber
#: column, so a code is attributed to a chamber only where its description says
#: one ("Reported to House", "Senate committee/subcommittee markups") and is
#: left unstated otherwise ("Committee reported"). The ``H`` prefix looks like
#: a House namespace and is *not* read as one here, because the publisher never
#: says so.
HOUSE = "house"
SENATE = "senate"
UNSTATED = "unstated"


#: Where a code's existence was established. The distinction is the whole
#: lesson of this module's second correction: the guide's own section 3 says
#: *"Codes in this table are representational... It is provided as a courtesy;
#: a complete, authoritative list of action codes does not exist."* Reading it
#: as the publisher's vocabulary anyway -- and then self-checking this mapping
#: against that same list -- produced a check that agreed with itself and could
#: not fail.
FROM_GUIDE = "guide-section-3"
FROM_THE_WIRE = "observed-2026-09-20"


@dataclass(frozen=True, slots=True)
class GuideCode:
    """One ``<actionCode>`` value, whose chamber, and how its existence is known.

    ``source`` is ``FROM_GUIDE`` for a code the retained user guide's section 3
    lists and ``FROM_THE_WIRE`` for one only the publisher's own responses
    show. Both are real; only the first can be checked against a committed
    fixture, and conflating them is what made the earlier self-check vacuous.
    """

    code: str
    chamber: str
    text: str
    source: str = FROM_GUIDE


#: What the publisher states for each print phrasing.
#:
#: **Two corrections are recorded here, and the second reversed the first.**
#:
#: The first version of this mapping cited 72 *Hearing held in House* and 74
#: *Markup in House* as action codes. They are **section 5** values -- the
#: mapping of *LOC summaries version codes* to ``<actionDesc>`` text, the
#: ``<versionCode>`` child of ``<summaries>`` -- and the self-check scanned the
#: whole guide, so it validated against a 123-code superset drawn from three
#: tables and could not fail.
#:
#: The correction to that then over-corrected, in the same shape: scoped to
#: section 3, the table has no House hearing or markup code, and this module
#: concluded the publisher therefore **has** none and the print was the only
#: structured source. **That is false on the wire.** Section 3 states in its own
#: first paragraph that it is representational and not authoritative, and the
#: 20 retained BILLSTATUS responses
#: (``~/Work/corpora/supply-2026-09-02/receipts/bill-action-relationship-2026-09-20/billstatus/``)
#: carry **13 of their 35 distinct action codes nowhere in section 3**,
#: including every House committee-actor code below. A check that reads an
#: explicitly incomplete list as a vocabulary and then validates against it is
#: the same defect one level down.
#:
#: What the same bytes do support is narrower and is what the hosted contract
#: rests on: on the 20-bill probe the publisher states **10 of 15** of the
#: print's subcommittee hearings **not at all**, and codes only 2 of the 5 it
#: does state. For markups the print is a **second, coded** source, not the
#: only one.
BILLSTATUS_ACTION_CODES: Mapping[str, tuple[GuideCode, ...]] = {
    "became_public_law": (
        GuideCode("36000", UNSTATED, "Became Public Law"),
        GuideCode("E40000", UNSTATED, "Became Public Law No: 114-47"),
        GuideCode("E30000", UNSTATED, "Signed by President"),
    ),
    "presented_to_president": (
        GuideCode("E20000", UNSTATED, "Presented to President"),
        GuideCode("28000", UNSTATED, "Presented to President."),
    ),
    "passed_house": (GuideCode("8000", HOUSE, "Passed/agreed to in House"),),
    "passed_senate": (GuideCode("17000", SENATE, "Passed/agreed to in Senate"),),
    "agreed_to": (
        GuideCode("8000", HOUSE, "Passed/agreed to in House"),
        GuideCode("17000", SENATE, "Passed/agreed to in Senate"),
    ),
    "suspension": (GuideCode("H37300", UNSTATED, "Final Passage Under Suspension of the Rules Results"),),
    "placed_on_calendar": (GuideCode("H12410", UNSTATED, "Union Calendar assignment"),),
    "rule_for_consideration": (GuideCode("H1L210", UNSTATED, "Rule provides for consideration of"),),
    "considered": (GuideCode("H30000", HOUSE, "Consideration by House"),),
    "ordered_reported": (
        GuideCode("H12200", UNSTATED, "Committee reported"),
        GuideCode("5000", HOUSE, "Reported to House"),
        GuideCode("14000", SENATE, "Reported to Senate"),
    ),
    "favorably_reported": (
        GuideCode("H12200", UNSTATED, "Committee reported"),
        GuideCode("5000", HOUSE, "Reported to House"),
        GuideCode("14000", SENATE, "Reported to Senate"),
    ),
    "reported": (
        GuideCode("H12200", UNSTATED, "Committee reported"),
        GuideCode("5000", HOUSE, "Reported to House"),
        GuideCode("14000", SENATE, "Reported to Senate"),
    ),
    "report_filed": (
        GuideCode("H12100", UNSTATED, "Committee report of an original measure"),
        GuideCode("14900", SENATE, "Senate committee report filed after reporting"),
    ),
    "discharged": (
        GuideCode("H12300", UNSTATED, "Committee discharged"),
        GuideCode("14500", SENATE, "Senate committee discharged"),
    ),
    "referred": (
        GuideCode("H11100", UNSTATED, "Referred to the Committee"),
        GuideCode("2000", HOUSE, "Referred to House committee"),
        GuideCode("11000", SENATE, "Referred to Senate committee"),
    ),
    "introduced": (
        GuideCode("1000", HOUSE, "Introduced in House"),
        GuideCode("10000", SENATE, "Introduced in Senate"),
    ),
    "received_in_chamber": (GuideCode("H14000", HOUSE, "Received in the House"),),
    "conference": (GuideCode("H25200", UNSTATED, "Conference report [free text] filed"),),
    # The two committee-actor events, and the reason ``source`` exists. Section
    # 3 lists only the Senate-side codes; the House-side ones below are in the
    # publisher's own responses and in no committed fixture, which is exactly
    # why they must be marked as observed rather than quietly asserted.
    "held_hearing": (
        GuideCode("13100", SENATE, "Senate committee/subcommittee hearings"),
        GuideCode("H21000", HOUSE, "Subcommittee Hearings Held", FROM_THE_WIRE),
    ),
    "held_markup": (
        GuideCode("13200", SENATE, "Senate committee/subcommittee markups"),
        GuideCode("H15000-B", HOUSE, "Committee Consideration and Mark-up Session Held", FROM_THE_WIRE),
        GuideCode("H15001", HOUSE, "Committee Consideration and Mark-up Session Held", FROM_THE_WIRE),
        GuideCode("H22000", HOUSE, "Subcommittee Consideration and Mark-up Session Held", FROM_THE_WIRE),
    ),
}

#: The codes a committed fixture can check. Everything else was learned from a
#: response and is checkable only against the retained receipt, which is what
#: ``source`` records and what the tool's cross-check reports.
GUIDE_LISTED_CODES: frozenset[str] = frozenset(
    entry.code for codes in BILLSTATUS_ACTION_CODES.values() for entry in codes if entry.source == FROM_GUIDE
)

#: Phrasings the publisher codes only through a code the retained guide does
#: **not** list. Named for what it is -- a gap in the *document*, never a gap
#: in the publisher's vocabulary -- because the earlier name
#: (``HOUSE_COMMITTEE_EVENTS_WITHOUT_A_CODE``) asserted the second and the wire
#: refuted it.
HOUSE_CODES_ABSENT_FROM_THE_GUIDE: frozenset[str] = frozenset(
    key
    for key, codes in BILLSTATUS_ACTION_CODES.items()
    if any(entry.chamber == HOUSE and entry.source == FROM_THE_WIRE for entry in codes)
)


def guide_codes_for(phrasing: str, chamber: str | None) -> tuple[str, ...]:
    """The action codes that apply to ``chamber``, or ``()`` where none is known.

    A code applies when its own text names this chamber or names none at all;
    one that names the *other* chamber is excluded. ``chamber`` of ``None``
    asks for every code known for the phrasing.
    """
    codes = BILLSTATUS_ACTION_CODES.get(phrasing, ())
    if chamber is None:
        return tuple(entry.code for entry in codes)
    return tuple(entry.code for entry in codes if entry.chamber in {chamber, UNSTATED})


#: Phrasings that name their own chamber, so the code is chosen by the phrase
#: rather than by anything around it.
_CHAMBER_IN_THE_PHRASE: Mapping[str, str] = {"passed_house": HOUSE, "passed_senate": SENATE}

#: Phrasings whose **actor is the committee**, not the measure. A House
#: committee holding a hearing on a Senate bill is a House committee action,
#: and falling through to the measure's type published ``13100`` *Senate
#: committee hearings* for it. Latent rather than observed -- 0 of the 639
#: hearing and markup rows in the measured corpus sits on a Senate measure --
#: and fixed anyway, because the next print to do it would publish a confidently
#: wrong code.
_COMMITTEE_IS_THE_ACTOR: frozenset[str] = frozenset({"held_hearing", "held_markup"})


def chamber_of(
    phrasing: str,
    matched_text: str,
    bill_designator: str,
    committee_chamber: str | None = None,
) -> str | None:
    """Which chamber's code vocabulary this one row is answerable to.

    Three rules, in order, and none of them is "the document's chamber", which
    would be an assumption: a House committee's activity report states *"the
    Senate passed H.R. 2365"* and reports a Senate committee acting on a Senate
    bill, and both belong to the Senate side while sitting in a House print.

    1. **The phrase names one** -- ``passed the Senate``, ``received in the
       House`` -- and then the phrase decides.
    2. **The committee is the actor** -- a hearing, a markup -- and then the
       *stating committee's* chamber decides, because the event is the
       committee's and not the measure's. ``committee_chamber`` of ``None``
       leaves it unresolved rather than guessed.
    3. Otherwise the action is on the measure, and the **measure's own type**
       decides: ``H.R. 2365`` is a House measure whatever document discusses it.
    """
    if phrasing in _CHAMBER_IN_THE_PHRASE:
        return _CHAMBER_IN_THE_PHRASE[phrasing]
    if phrasing == "received_in_chamber":
        return SENATE if "senate" in matched_text.lower() else HOUSE
    if phrasing in _COMMITTEE_IS_THE_ACTOR:
        return committee_chamber
    parts = bill_type_and_number(bill_designator)
    if parts is None:
        return None
    return HOUSE if parts[0].startswith("h") else SENATE


# --- the print's own action phrasings ------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrintAction:
    """One measured print phrasing, and why it is spelled the way it is.

    ``key`` names *what the print wrote*, never the legislative event: the
    event is read off ``bill_stage`` by :func:`sealed_stage` or reported as
    unmapped. A parallel event vocabulary declared here is exactly what this
    package forbids.
    """

    key: str
    pattern: str
    note: str = ""

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


#: The public-law spelling, imported rather than re-written: the citation rule
#: already reads all four forms these prints set, including the Bluebook one.
_PUBLIC_LAW = CITATION_RULES_BY_NAME["public_law"].pattern

#: The sealed vocabulary, **additions-only**: a key here is published in
#: ``bill_committee_actions.print_phrasing``, so renaming or deleting one
#: rewrites rows that are already out. Append, move
#: :data:`PRINT_ACTION_VOCABULARY_VERSION`, re-pin the fixtures.
#:
#: Ordered by precedence the way ``STAGE_RULES`` is, and for the same reason:
#: the first rule whose match covers a span owns it, so ``discharged from
#: further consideration`` is a discharge and not also a consideration, and
#: ``declined to mark up`` is a refusal and not a markup. Every pattern was
#: derived from the recurring phrasings across all 1,249 pages of the eight
#: sampled prints, not from the hand-check sample.
PRINT_ACTION_RULES: tuple[PrintAction, ...] = (
    PrintAction(
        "became_public_law",
        rf"became (?:a )?public law|signed into law|{_PUBLIC_LAW}|president \w+ signed|signed by the president",
        "the one phrasing whose sealed rung is `law`; also the one whose commonest false positive is a "
        "`Pub. L.` cite naming the law a bill AMENDS",
    ),
    PrintAction("vetoed", r"veto(?:ed|es)?\b", "no sealed rung and no section-3 code: a veto is neither"),
    PrintAction(
        "presented_to_president",
        r"presented to the president|transmitted to the president",
        "here so the sealed `presented` rung is reachable from a print phrasing at all",
    ),
    PrintAction(
        "conference",
        r"conference report|appointed conferees|conferees|resolving differences",
        "here so the sealed `conference` rung is reachable; measured at 2 rows in this family",
    ),
    PrintAction(
        "not_considered",
        r"was not considered|was not taken up|declined consideration|declined to (?:consider|take up)",
        "a negative statement: the print says an action did NOT happen, which no index states and no action code can",
    ),
    PrintAction("declined_markup", r"declined to mark ?up", "before held_markup, whose text it contains"),
    PrintAction("passed_senate", r"passed the senate|senate passed|senate agreed to"),
    PrintAction(
        "passed_house",
        r"passed the house|house passed|passed by the house|house agreed to",
        "the sealed matcher is `passed house`; the print writes `passed the House`, one word apart. "
        "Recorded as print register rather than patched into STAGE_RULES",
    ),
    PrintAction("suspension", r"suspend the rules and pass\w*|under suspension of the rules|suspension of the rules"),
    PrintAction("agreed_to", r"was agreed to|agreed to the (?:motion|resolution|amendment)"),
    PrintAction("placed_on_calendar", r"placed on the (?:union|house|senate) calendar"),
    PrintAction("rule_for_consideration", r"providing for consideration of|rule provid\w+ for consideration"),
    PrintAction(
        "ordered_reported",
        r"ordered (?:to be )?(?:favorably )?reported|ordered [^.;]{0,80}?favorably reported",
    ),
    PrintAction("favorably_reported", r"favorably reported|reported favorably"),
    PrintAction(
        "favorably_forwarded",
        r"favorably forwarded|forwarded [^.;]{0,60}?to the full committee",
        "the subcommittee-to-full-committee step: no sealed rung and no section-3 code at all",
    ),
    PrintAction(
        "received_in_chamber",
        r"received in the (?:senate|house)",
        "before referred, which the same sentence usually also states of the receiving committee",
    ),
    PrintAction(
        "discharged",
        r"\bdischarged\b",
        "the bare verb: the print writes both `was discharged from further consideration of` and "
        "`the Committee ... discharged H.R. 2365`, and a rule reading only the first missed the second",
    ),
    PrintAction("report_filed", r"h(?:ouse)? ?rept?\.? ?\d{2,3}[-–]\d{1,4}|house report \d{2,3}[-–]\d{1,4}"),
    PrintAction(
        "reported",
        r"\breported\b",
        "past tense only: the plural noun in a bill's own title (`updated reports relating to`) is not a "
        "committee reporting it, and reading it as one produced 23 false rows against 162 real ones",
    ),
    PrintAction(
        "held_markup",
        r"held a mark ?up|met in open mark ?up session|marked up|mark ?up of|\bmark ?up\b",
        "219 rows. Section 3 has NO House markup code: 13200 says Senate. For these House prints the "
        "sentence is the only structured statement of the event",
    ),
    PrintAction(
        "held_hearing",
        r"held a hearing|hearing on|hearing (?:entitled|titled)|\bhearing\b",
        "420 rows. Section 3 has NO House hearing code: 13100 says Senate. Its 1,590 orphans are general "
        "oversight hearings and index lines, not bill hearings (reviewer sample of 25)",
    ),
    PrintAction("referred", r"\breferred\b"),
    PrintAction("introduced", r"\bintroduced\b"),
    PrintAction(
        "included_in",
        r"(?:were|was) included in|provisions of [^.;]{0,60}?included|incorporated into",
        "a bill-to-bill relationship, not a bill action; the commonest multi-bill sentence in the corpus",
    ),
    PrintAction(
        "considered",
        r"(?<!further )\bconsider(?:ed|s)\b|business meeting to consider",
        "the lookbehind keeps `further consideration` with the discharge that states it",
    ),
)

#: Phrasings with **no code in either chamber**: the guide's action-code table
#: has no entry for the event at all. Kept apart from
#: :data:`SENATE_ONLY_IN_THE_GUIDE`, which is a different fact about a
#: different set, because conflating the two double-counts both.
UNCODED_IN_THE_GUIDE: frozenset[str] = frozenset(
    rule.key for rule in PRINT_ACTION_RULES if rule.key not in BILLSTATUS_ACTION_CODES
)


#: Hand-set, moved when a phrasing is appended.  See the additions-only note on
#: :data:`PRINT_ACTION_RULES`.
PRINT_ACTION_VOCABULARY_VERSION = "001"


def _rule_set_version(
    rules: Sequence[PrintAction],
    codes: Mapping[str, tuple[GuideCode, ...]] | None = None,
    chamber_rules: Mapping[str, str] | None = None,
) -> str:
    """A digest over everything that decides what a published row says.

    The device ``citations.CITATION_RULE_SET_VERSION`` uses, widened twice over
    what it first covered. A pattern is not the only input to a row: the
    code mapping fills ``billstatus_action_code`` and the chamber rules decide
    which of its entries apply, so an edit to either changes **every** row's
    published code while leaving the patterns untouched. Digesting only the
    patterns let that happen without moving a version -- and the two
    corrections this module has already been through were both edits to exactly
    those inputs.
    """
    codes = BILLSTATUS_ACTION_CODES if codes is None else codes
    chamber_rules = _CHAMBER_IN_THE_PHRASE if chamber_rules is None else chamber_rules
    parts = [f"{rule.key}|{rule.pattern}" for rule in rules]
    parts += [
        f"{key}|" + ",".join(f"{entry.code}:{entry.chamber}:{entry.source}" for entry in codes[key])
        for key in sorted(codes)
    ]
    parts += [f"{key}|{value}" for key, value in sorted(chamber_rules.items())]
    parts += sorted(_COMMITTEE_IS_THE_ACTOR)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


PRINT_ACTION_RULE_SET_VERSION = _rule_set_version(PRINT_ACTION_RULES)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple((rule.key, rule.compiled()) for rule in PRINT_ACTION_RULES)


def sealed_stage(phrase: str) -> tuple[str | None, str | None]:
    """``(stage, matcher)`` if ``bill_stage``'s sealed rules read this phrase, else ``(None, None)``.

    Derived, not declared. ``infer_stage_from_text`` returns the default rung
    with ``rule is None`` when nothing matched, and that -- not a rung of this
    module's choosing -- is what "the sealed vocabulary does not reach this
    phrasing" means.
    """
    finding = infer_stage_from_text(phrase)
    return (None, None) if finding.rule is None else (finding.stage, finding.matcher)


def phrase_matches(sentence: str) -> tuple[tuple[str, int, int, str], ...]:
    """``(phrasing, start, end, matched)`` per phrase this sentence states, in span order.

    Precedence resolves overlap: a later rule never claims a span an earlier
    one already owns, so one span is one phrasing and the row counts are counts
    of events rather than of patterns.
    """
    taken: list[tuple[int, int]] = []
    found: list[tuple[str, int, int, str]] = []
    for key, pattern in _COMPILED:
        for match in pattern.finditer(sentence):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            found.append((key, match.start(), match.end(), match.group(0)))
    found.sort(key=lambda entry: entry[1])
    return tuple(found)


# --- dates the print states ----------------------------------------------------------

_MONTHS: Mapping[str, str] = {
    name: f"{number:02d}"
    for number, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}  # fmt: skip
_PRINT_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b|\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
    re.IGNORECASE,
)


def print_dates(sentence: str) -> tuple[str, ...]:
    """Every date the sentence states, ISO, in printed order.

    Both spellings this family sets: ``On June 13, 2023,`` in prose and
    ``3/24/23`` in a markup-summary heading. A two-digit year reads as 20xx,
    which is safe for a 118th-Congress print and is stated rather than silently
    assumed.

    **Unscored.** The dates are extracted and published; whether the date
    belongs to *this* action rather than to a neighbouring clause was not
    hand-checked, and ``bill_committee_actions.stated_date`` says so.
    """
    found: list[str] = []
    for match in _PRINT_DATE.finditer(sentence):
        if match.group(1):
            found.append(f"{match.group(3)}-{_MONTHS[match.group(1).lower()]}-{int(match.group(2)):02d}")
        else:
            year = int(match.group(6))
            found.append(f"{2000 + year if year < 100 else year}-{int(match.group(4)):02d}-{int(match.group(5)):02d}")
    return tuple(found)


# --- findings ------------------------------------------------------------------------

#: Measured attachment precision per class, on 36 hand-checked rows whose
#: phrase reading was correct. These are the numbers the hosted contract's
#: ``attachment_confidence`` column publishes, so they live beside the rule
#: that assigns the class.
ATTACHMENT_SINGLE = "single"
ATTACHMENT_MULTI = "multi"

#: **Joint** precision per class: the share of published rows that are both the
#: right kind and the right bill, hand-checked 2026-09-20. 30 of 36 single-bill
#: rows and 2 of 4 multi-bill rows. This is a statement about what is
#: published, never about what a reader sees -- recall is a separate axis and
#: is 59.6%.
ATTACHMENT_PRECISION: Mapping[str, float] = {ATTACHMENT_SINGLE: 0.833, ATTACHMENT_MULTI: 0.500}

#: The class a consumer's trusted view filters to. Measured cost of the
#: restriction: 4,089 of 4,456 rows across the eight prints already carry it,
#: so the trusted view keeps 91.8% of the volume.
TRUSTED_ATTACHMENT = ATTACHMENT_SINGLE


@dataclass(frozen=True, slots=True)
class BillActionFinding:
    """One action phrase, attached to one bill the same sentence names.

    ``span_start``/``span_end`` locate the **phrase** and are what make the row
    unique; ``mention_span_start``/``mention_span_end`` locate the bill
    designator. Both are offsets into the retained text, so a consumer holding
    that text re-reads exactly what the rule saw.
    """

    bill_id: str
    phrasing: str
    stage: str | None
    stage_matcher: str | None
    billstatus_action_codes: tuple[str, ...]
    #: Which chamber's vocabulary the codes were chosen from; see :func:`chamber_of`.
    chamber: str | None
    stated_dates: tuple[str, ...]
    attachment: str
    bills_in_sentence: int
    matched_text: str
    span_start: int
    span_end: int
    mention_span_start: int
    mention_span_end: int
    sentence_start: int
    sentence_end: int
    page: int | None
    rule_version: str = PRINT_ACTION_VOCABULARY_VERSION
    rule_set_version: str = PRINT_ACTION_RULE_SET_VERSION


@dataclass(frozen=True, slots=True)
class BillActionReading:
    """Every attached action in one document, and every phrase that reached no bill.

    ``orphan_phrasings`` is not a defect list and not padding: it is the
    ceiling on what a sentence-scoped rule can never attach, and publishing it
    beside the rows is what stops the row count from reading as the print's
    whole content. 2,952 against 4,456 across the eight measured prints.
    """

    findings: tuple[BillActionFinding, ...]
    orphan_phrasings: Mapping[str, int]
    sentences: int
    #: Bill mentions whose sentence names more than one bill, whether or not
    #: that sentence states an action. The corpus-wide exposure the row-level
    #: ``attachment`` classes are drawn from, and the number a reader should
    #: weigh rather than the hand check's 4-row multi-bill cell.
    mentions_in_multi_bill_sentence: int


def find_bill_actions(
    text: str,
    citations: Iterable[object],
    *,
    committee_chamber: str | None = None,
) -> BillActionReading:
    """Every action the print states about a bill it names, from the text and its cites.

    ``citations`` are the ``bill_number`` :class:`CitationFinding`s already
    read out of ``text`` -- passed in rather than re-derived, so one document
    is read once and the citation rows and the action rows cannot disagree
    about where a bill was named. Anything else is ignored, so a caller may
    hand over the whole finding tuple.

    ``committee_chamber`` is the chamber of the committee whose document this
    is, and it is used for one thing only: a hearing and a markup are the
    committee's own acts, so their action code follows the actor and not the
    measure (see :func:`chamber_of`). Every other row's chamber is read off the
    row.

    **The attachment rule is nearest-mention-in-sentence**, ties going to the
    designator after the phrase, because the print's grammar puts the measure
    after the verb (*ordered H.R. 1432 favorably reported*, *held a hearing on
    H.R. 2691*). The obvious alternative -- give the action to every bill in
    the sentence -- publishes 5,138 rows against 4,456 on the measured corpus,
    and the extra 682 are the ones a multi-bill sentence gets wrong.
    """
    if not isinstance(text, str):
        raise BillActionError(f"text must be a string, not {type(text).__name__}")
    mentions = [
        finding
        for finding in citations
        if getattr(finding, "kind", None) == "bill_number" and getattr(finding, "span_start", None) is not None
    ]
    flat = flatten(text)
    starts = sentence_starts(flat.flat)
    located = [(finding, flat.to_flat(finding.span_start)) for finding in mentions]
    if any(position > len(flat.flat) for _finding, position in located):
        raise BillActionError("a citation span falls outside the text these rules were given")

    by_sentence: dict[tuple[int, int], list[tuple[object, int]]] = {}
    for finding, position in located:
        by_sentence.setdefault(sentence_at(starts, flat.flat, position), []).append((finding, position))

    findings: list[BillActionFinding] = []
    orphans: dict[str, int] = {}
    for index, begin in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(flat.flat)
        sentence = flat.flat[begin:end]
        here = by_sentence.get((begin, end))
        phrases = phrase_matches(sentence)
        if here is None:
            for key, _start, _end, _matched in phrases:
                orphans[key] = orphans.get(key, 0) + 1
            continue
        bills = {finding.target_key for finding, _ in here}
        attachment = ATTACHMENT_SINGLE if len(bills) == 1 else ATTACHMENT_MULTI
        dates = print_dates(sentence)
        for key, phrase_start, phrase_end, matched in phrases:
            anchor = begin + phrase_start
            mention, _position = min(
                here,
                key=lambda entry: (abs(entry[1] - anchor), 0 if entry[1] >= anchor else 1),
            )
            stage, matcher = sealed_stage(matched)
            chamber = chamber_of(key, matched, mention.matched_text, committee_chamber)
            findings.append(
                BillActionFinding(
                    bill_id=mention.target_key,
                    phrasing=key,
                    stage=stage,
                    stage_matcher=matcher,
                    billstatus_action_codes=guide_codes_for(key, chamber),
                    chamber=chamber,
                    stated_dates=dates,
                    attachment=attachment,
                    bills_in_sentence=len(bills),
                    matched_text=matched,
                    span_start=flat.to_retained(anchor),
                    span_end=flat.to_retained(max(anchor, begin + phrase_end - 1)) + 1,
                    mention_span_start=mention.span_start,
                    mention_span_end=mention.span_end,
                    sentence_start=flat.to_retained(begin),
                    sentence_end=flat.to_retained(max(begin, end - 1)) + 1,
                    page=mention.page,
                )
            )
    findings.sort(key=lambda finding: (finding.span_start, finding.bill_id, finding.phrasing))
    exposed = sum(len(here) for here in by_sentence.values() if len({mention.target_key for mention, _ in here}) > 1)
    return BillActionReading(tuple(findings), dict(sorted(orphans.items())), len(starts), exposed)


__all__ = [
    "ATTACHMENT_MULTI",
    "ATTACHMENT_PRECISION",
    "ATTACHMENT_SINGLE",
    "BILLSTATUS_ACTION_CODES",
    "FROM_GUIDE",
    "FROM_THE_WIRE",
    "GUIDE_LISTED_CODES",
    "HOUSE",
    "HOUSE_CODES_ABSENT_FROM_THE_GUIDE",
    "PRINT_ACTION_RULES",
    "PRINT_ACTION_RULE_SET_VERSION",
    "PRINT_ACTION_VOCABULARY_VERSION",
    "SENATE",
    "TRUSTED_ATTACHMENT",
    "UNCODED_IN_THE_GUIDE",
    "UNSTATED",
    "WRAP_HYPHENS",
    "BillActionError",
    "BillActionFinding",
    "BillActionReading",
    "FlatText",
    "GuideCode",
    "PrintAction",
    "chamber_of",
    "find_bill_actions",
    "flatten",
    "guide_codes_for",
    "phrase_matches",
    "print_dates",
    "sealed_stage",
    "sentence_at",
    "sentence_starts",
]
